"""El payload de la invitación a Supabase Auth.

Existe por un bug real: `invite_user` no mandaba `redirect_to`, así que
Supabase caía en su "Site URL" por defecto y el link del correo moría en
"This site can't be reached". El usuario quedaba `confirmed` en `auth.users`
pero nunca llegaba a `/auth/callback`, así que jamás creaba contraseña ni
pasaba de `invited` a `active`.

Los tests de integración mockean `invite_user` ENTERO, así que ninguno mira
el payload — por eso el hueco pasó desapercibido y por eso este test es
unitario sobre lo que se le manda a Supabase.
"""

from typing import Any
from uuid import uuid4

import pytest

from app.core.settings import get_settings
from app.modules.identity import auth_admin


class _FakeResponse:
    status_code = 200

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id
        self.text = ""

    def json(self) -> dict[str, Any]:
        return {"id": self._user_id}


class _FakeClient:
    """Captura el payload en vez de salir a la red."""

    captured: dict[str, Any] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _FakeResponse:
        _FakeClient.captured = {"url": url, "headers": headers, "json": json}
        return _FakeResponse(str(uuid4()))


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Any:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_invite_includes_redirect_to_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("nuevo@example.com", "Nuevo Usuario")

    payload = _FakeClient.captured["json"]
    assert payload["redirect_to"] == "https://app.example.com/auth/callback"
    assert payload["email"] == "nuevo@example.com"
    assert payload["data"] == {"full_name": "Nuevo Usuario"}


@pytest.mark.asyncio
async def test_invite_normalizes_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una URL con `/` final produciría `//auth/callback`, que Supabase no
    matchearía contra su lista de Redirect URLs permitidas — y volvería a caer
    en la Site URL, o sea el mismo bug con otra causa."""
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com/")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("otro@example.com", "Otro")

    assert _FakeClient.captured["json"]["redirect_to"] == "https://app.example.com/auth/callback"


@pytest.mark.asyncio
async def test_invite_omits_redirect_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `FRONTEND_URL` no se manda un `redirect_to` vacío (Supabase lo
    rechazaría): se omite y queda el comportamiento anterior."""
    monkeypatch.setenv("FRONTEND_URL", "")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _FakeClient)

    await auth_admin.invite_user("sin@example.com", "Sin Redirect")

    assert "redirect_to" not in _FakeClient.captured["json"]


class _RateLimitedResponse:
    status_code = 429
    text = '{"error_code":"over_email_send_rate_limit"}'

    def json(self) -> dict[str, Any]:
        return {}


class _RateLimitedClient(_FakeClient):
    async def post(self, url: str, headers: dict, json: dict) -> Any:
        return _RateLimitedResponse()


@pytest.mark.asyncio
async def test_rate_limit_no_se_reporta_como_falla_del_sistema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un 429 de Supabase significa "espera", no "algo se rompió".

    Antes caía en `AuthAdminError` (502, "No se pudo invitar al usuario en
    Supabase Auth"), que manda al admin a buscar un problema inexistente: el
    servicio de correo incluido de Supabase tiene un límite bajo a propósito
    porque está pensado para pruebas. Se distingue para poder decirle qué
    hacer — esperar — en vez de dejarlo adivinando.
    """
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setattr(auth_admin.httpx, "AsyncClient", _RateLimitedClient)

    with pytest.raises(auth_admin.InviteRateLimitedError) as exc:
        await auth_admin.invite_user("nuevo@example.com", "Nuevo Usuario")

    assert exc.value.status_code == 429
    assert exc.value.code == "INVITE_RATE_LIMITED"
    assert "espera" in str(exc.value).lower()
