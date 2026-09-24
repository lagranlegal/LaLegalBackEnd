"""`ResendProvider` contra un transporte falso de httpx: NUNCA toca la red.

Lo que importa acá es la clasificación de fallas (§6.3): qué se reintenta y qué
no, porque de eso depende que un Resend caído no se convierta en correos
perdidos, y que una dirección rechazada no se reintente para siempre.
"""

import json
from typing import Any

import httpx
import pytest

from app.modules.notifications import providers
from app.modules.notifications.providers import EmailMessage, ResendProvider

MESSAGE = EmailMessage(
    from_header='"Prendo" <notificaciones@prendo.com.co>',
    to="duena@example.com",
    subject="Resumen",
    html="<p>hola</p>",
    text="hola",
    reply_to="contacto@example.com",
    idempotency_key="delivery-123",
)


def _patch(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        result: httpx.Response = handler(request)
        return result

    real_client = httpx.AsyncClient

    def _client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(_handler), **kwargs)

    monkeypatch.setattr(providers.httpx, "AsyncClient", _client)
    return seen


async def test_success_returns_provider_id_and_sends_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch(monkeypatch, lambda r: httpx.Response(200, json={"id": "re_123"}))
    result = await ResendProvider("key-xyz").send(MESSAGE)
    assert result.ok and result.provider_id == "re_123"
    request = seen[0]
    assert str(request.url) == providers.RESEND_URL
    assert request.headers["Authorization"] == "Bearer key-xyz"
    assert request.headers["Idempotency-Key"] == "delivery-123"
    body = json.loads(request.content)
    assert body["to"] == ["duena@example.com"]
    assert body["reply_to"] == "contacto@example.com"


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (401, True), (403, True), (422, False), (400, False)],
)
async def test_failure_classification(
    monkeypatch: pytest.MonkeyPatch, status: int, retryable: bool
) -> None:
    _patch(monkeypatch, lambda r: httpx.Response(status, json={"message": "x"}))
    result = await ResendProvider("k").send(MESSAGE)
    assert not result.ok
    assert result.retryable is retryable
    assert result.error and result.error.startswith(f"HTTP {status}")


async def test_network_error_is_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    _patch(monkeypatch, _boom)
    result = await ResendProvider("k").send(MESSAGE)
    assert not result.ok and result.retryable


def test_without_key_the_default_is_the_null_provider() -> None:
    assert isinstance(providers.get_default_provider(), providers.NullProvider)
