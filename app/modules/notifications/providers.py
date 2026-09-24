"""Proveedores de envío de correo, detrás de una interfaz mínima.

- `ResendProvider`: la API HTTP de Resend (`POST /emails`). Es el real.
- `NullProvider`: el que se usa cuando no hay `RESEND_API_KEY`. No manda nada
  y lo dice: el despachador deja la entrega en `skipped_no_provider`.
- `RecordingProvider`: para los tests. Guarda los mensajes en memoria y
  responde como si hubieran salido. **Ningún test manda un correo real.**

El proveedor NUNCA se llama dentro de una transacción de negocio (§5.1): el
despachador marca la entrega `sending`, cierra la transacción, llama, y
registra el resultado en otra.
"""

import logging
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

import httpx

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


@dataclass(frozen=True)
class EmailMessage:
    from_header: str
    to: str
    subject: str
    html: str
    text: str
    reply_to: str | None = None
    #: La entrega es la llave: si el proceso muere entre el envío y el
    #: registro, el reintento no duplica el correo (Resend respeta
    #: `Idempotency-Key` por 24 h).
    idempotency_key: str | None = None


@dataclass(frozen=True)
class SendResult:
    ok: bool
    provider_id: str | None = None
    #: `True` = vale la pena reintentar (5xx, 429, timeout, credenciales);
    #: `False` = el mensaje en sí no va a salir nunca (dirección rechazada).
    retryable: bool = False
    error: str | None = None
    #: `True` solo en el proveedor nulo: no se intentó, porque no hay con qué.
    not_configured: bool = False


class EmailProvider(Protocol):
    name: str

    async def send(self, message: EmailMessage) -> SendResult: ...


class NullProvider:
    name = "null"

    async def send(self, message: EmailMessage) -> SendResult:
        logger.info(
            "correo_no_enviado_sin_proveedor: asunto=%r (falta RESEND_API_KEY)", message.subject
        )
        return SendResult(
            ok=False,
            not_configured=True,
            error="No hay proveedor de correo configurado (RESEND_API_KEY vacía).",
        )


@dataclass
class RecordingProvider:
    name: str = "recording"
    outbox: list[EmailMessage] = field(default_factory=list)
    #: Para simular fallas en tests: lo que devuelve en vez de "enviado".
    fail_with: SendResult | None = None

    async def send(self, message: EmailMessage) -> SendResult:
        if self.fail_with is not None:
            return self.fail_with
        self.outbox.append(message)
        return SendResult(ok=True, provider_id=f"test-{uuid4()}")


class ResendProvider:
    name = "resend"

    def __init__(self, api_key: str, *, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    async def send(self, message: EmailMessage) -> SendResult:
        payload: dict[str, object] = {
            "from": message.from_header,
            "to": [message.to],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        }
        if message.reply_to:
            payload["reply_to"] = message.reply_to
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if message.idempotency_key:
            headers["Idempotency-Key"] = message.idempotency_key
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(RESEND_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            return SendResult(ok=False, retryable=True, error=f"red: {type(exc).__name__}")

        if response.is_success:
            provider_id = None
            try:
                provider_id = response.json().get("id")
            except ValueError:
                pass
            return SendResult(ok=True, provider_id=provider_id)

        # Nunca se loguea el cuerpo del correo ni la key; el mensaje de Resend
        # sí, recortado — es lo que dice por qué no salió.
        detail = response.text[:300]
        status = response.status_code
        # 429 = cuota; 5xx = Resend caído; 401/403 = credencial mal puesta, que
        # se arregla sin tocar el mensaje. Todo eso se reintenta (§6.3).
        retryable = status == 429 or status >= 500 or status in (401, 403)
        return SendResult(ok=False, retryable=retryable, error=f"HTTP {status}: {detail}")


def get_default_provider() -> EmailProvider:
    key = get_settings().resend_api_key
    if key:
        return ResendProvider(key)
    return NullProvider()
