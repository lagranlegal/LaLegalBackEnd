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
import os
from uuid import UUID

from app.core.settings import get_settings

_VERSION = b"\x01"
_SIG_BYTES = 16
_PATH = "/baja/"
#: Donde el proveedor de correo hace el POST de un clic (RFC 8058). Es la
#: ruta de `router.public_router`, que ya aceptaba POST e ignoraba el cuerpo.
_API_PATH = "/api/v1/public/unsubscribe/"
#: RFC 8058 §3.1: el valor exacto, literal, que el cliente de correo reenvía
#: como cuerpo del POST.
ONE_CLICK_POST = "List-Unsubscribe=One-Click"


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


def _public_api_base() -> str:
    """La URL pública de este backend, o '' si no se puede saber.

    `PUBLIC_API_URL` manda; sin ella, en Fly se deriva de `FLY_APP_NAME` (Fly
    la pone sola en toda máquina de la app, incluida la del job nocturno), así
    que las cabeceras funcionan en dev y prod sin configurar un secreto más."""
    explicit = get_settings().public_api_url.strip().rstrip("/")
    if explicit:
        return explicit
    app_name = os.environ.get("FLY_APP_NAME", "").strip()
    return f"https://{app_name}.fly.dev" if app_name else ""


def list_unsubscribe_headers(*, company_id: UUID, customer_id: UUID) -> dict[str, str]:
    """`List-Unsubscribe` + `List-Unsubscribe-Post` (RFC 2369 y RFC 8058).

    Gmail y Yahoo las exigen desde 2024 a quien manda en volumen, y las usan
    para mostrar «Anular suscripción» junto al remitente: la persona se da de
    baja sin abrir el correo, en vez de marcarlo como spam — y esa marca la
    paga `prendo.com.co` para todos los inquilinos (§9.2-e).

    **Apuntan a la API, no a la página del front, y es la excepción a la regla
    de este archivo:** acá el que llama es el SERVIDOR del proveedor de correo,
    con un POST y el cuerpo `List-Unsubscribe=One-Click`, y la RFC pide que dé
    de baja sin página intermedia. Un POST no lo manda un escáner que abre
    enlaces: la RFC lo eligió justamente por eso (§1). El enlace del CUERPO
    sigue yendo a la página del front, que solo muestra con el GET.

    La RFC pide exactamente UNA URI HTTPS, así que no se agrega la de la
    página. Un cliente que no sepa hacer el POST y abra esta URI en el
    navegador cae en el GET, que redirige a la página (`router.get_unsubscribe`).

    `{}` si no hay a dónde apuntar: el correo sale igual, con su enlace en el
    cuerpo, que es el requisito (§9.2-e); las cabeceras mejoran la entrega,
    no son la salida.
    """
    base = _public_api_base()
    if not base:
        return {}
    token = make_token(company_id=company_id, customer_id=customer_id)
    return {
        "List-Unsubscribe": f"<{base}{_API_PATH}{token}>",
        "List-Unsubscribe-Post": ONE_CLICK_POST,
    }


def page_link_for_token(token: str) -> str | None:
    """La página de baja del front para un token ya armado, o None sin
    `FRONTEND_URL`. No valida el token: la página lo hace al cargar."""
    base = get_settings().frontend_url.strip().rstrip("/")
    return base + _PATH + token if base else None


def mask_email(email: str | None) -> str | None:
    """`j•••@gmail.com`: lo justo para que la persona se reconozca en la
    página de baja, sin mostrarle la dirección entera a quien tenga el enlace
    reenviado."""
    value = (email or "").strip()
    if not value:
        return None
    local, sep, domain = value.partition("@")
    return f"{local[:1]}•••{sep}{domain}"
