"""El enlace de baja de los correos al cliente (docs/NOTIFICACIONES.md §9.2-e, §17).

**El enlace abre una PÁGINA; la baja la hace un POST desde esa página.** Nunca
un enlace que dé de baja al abrirse: los escáneres de correo y las vistas
previas de WhatsApp hacen GET sobre cada enlace apenas llega (el proyecto lo
sufrió el 03/09/2026 con un token de un solo uso). Si el GET diera de baja, un
cliente quedaría fuera sin haber abierto el correo — y lo que es peor, sin
enterarse.

**Token sin estado, firmado con HMAC-SHA256.** No hay tabla de tokens: el
token dice a qué cliente de qué empresa se refiere y la firma prueba que lo
emitimos nosotros. Por qué así y no una fila:

- **Tiene que servir meses después.** Un correo viejo en la bandeja sigue
  teniendo su salida; un token que vence convierte "darse de baja" en "marcar
  como spam", que es justo lo que el enlace venía a evitar (§9.2-e).
- **No es una credencial que valga la pena proteger con un solo uso.** Lo
  único que habilita es dar de baja a esa persona de los avisos de esa
  empresa: idempotente, reversible en el mostrador y auditado. Reusarlo no da
  nada nuevo.
- **No expone el id del cliente a quien no tiene el correo.** Quien tiene el
  enlace ya recibió el correo en esa dirección.

Formato: `base64url(v1 ‖ company_id ‖ customer_id) . base64url(hmac[:16])`.
16 bytes de firma (128 bits) sobran para un secreto que nadie puede consultar
en línea más rápido que la API.
"""

import base64
import hashlib
import hmac
from uuid import UUID

from app.core.settings import get_settings

_VERSION = b"\x01"
_SIG_BYTES = 16
_PATH = "/baja/"


class LinkNotConfigured(Exception):
    """Falta `NOTIFICATIONS_LINK_SECRET` o `FRONTEND_URL`: no hay enlace que armar."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _secret() -> bytes | None:
    secret = get_settings().notifications_link_secret.strip()
    return secret.encode() if secret else None


def _sign(secret: bytes, body: bytes) -> bytes:
    # El prefijo separa este uso del secreto de cualquier otro que venga
    # después (un enlace de confirmar correo, §9.3-3): una firma de baja no
    # puede servir de firma de otra cosa.
    return hmac.new(secret, b"unsubscribe:" + body, hashlib.sha256).digest()[:_SIG_BYTES]


def make_token(*, company_id: UUID, customer_id: UUID) -> str:
    secret = _secret()
    if secret is None:
        raise LinkNotConfigured("NOTIFICATIONS_LINK_SECRET vacía: no se firman enlaces de baja.")
    body = _VERSION + company_id.bytes + customer_id.bytes
    return f"{_b64(body)}.{_b64(_sign(secret, body))}"


def read_token(token: str) -> tuple[UUID, UUID] | None:
    """(empresa, cliente) si el token es nuestro; None si no — sin decir por
    qué: a quien fabrica tokens no se le explica en qué se equivocó."""
    secret = _secret()
    if secret is None:
        return None
    try:
        body_txt, sig_txt = token.split(".")
        body, sig = _unb64(body_txt), _unb64(sig_txt)
    except ValueError:
        return None
    if len(body) != 33 or body[:1] != _VERSION or len(sig) != _SIG_BYTES:
        return None
    if not hmac.compare_digest(sig, _sign(secret, body)):
        return None
    return UUID(bytes=body[1:17]), UUID(bytes=body[17:33])


def unsubscribe_link(*, company_id: UUID, customer_id: UUID) -> str:
    base = get_settings().frontend_url.strip().rstrip("/")
    if not base:
        raise LinkNotConfigured("FRONTEND_URL vacía: no hay página de baja a la que apuntar.")
    return base + _PATH + make_token(company_id=company_id, customer_id=customer_id)


def mask_email(email: str | None) -> str | None:
    """`j•••@gmail.com`: lo justo para que la persona se reconozca en la
    página de baja, sin mostrarle la dirección entera a quien tenga el enlace
    reenviado."""
    value = (email or "").strip()
    if not value:
        return None
    local, sep, domain = value.partition("@")
    return f"{local[:1]}•••{sep}{domain}"
