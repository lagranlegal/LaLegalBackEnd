from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_time_cursor
from app.common.rate_limit import FixedWindowLimiter, RateLimitedError, client_ip
from app.core.db import get_db
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.notifications import service, unsubscribe
from app.modules.notifications.schemas import (
    DeliveryOut,
    DeliveryStatus,
    NotificationSettingsOut,
    NotificationSettingsUpdateIn,
    UnsubscribeOut,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

#: SIN sesión, a propósito (NOTIFICACIONES §17): quien abre el enlace de baja
#: es un cliente de la compraventa, no un usuario de Prendo, y no tiene ni va a
#: tener cuenta. Lo que lo autoriza es el token firmado del enlace, que dice a
#: qué cliente de qué empresa se refiere; la sesión es de plataforma (sin RLS)
#: porque no hay tenant en el request, y por eso toda consulta va filtrada por
#: la empresa y el cliente que trae el token. Excepción anotada en
#: `tests/unit/test_endpoint_guards.py`.
#: Límite de tasa del endpoint público (NOTIFICACIONES §17-bis). Es el único
#: de la API sin sesión, y hasta el 25/09/2026 no tenía ninguno. No frena
#: fuerza bruta —el token es un HMAC de 128 bits, no hay qué adivinar—: corta
#: abuso. Dos llaves, porque cuidan cosas distintas:
#:
#: - **Por IP, 60 por minuto (GET + POST juntos).** Una IP barriendo tokens
#:   basura. Holgado A PROPÓSITO: el POST de un clic lo manda el servidor de
#:   Gmail, así que muchas bajas legítimas pueden llegar desde las mismas IPs
#:   de Google, y en Colombia el CGNAT de los operadores móviles pone a mucha
#:   gente detrás de una sola IP. Un 429 a una baja legítima es un correo más
#:   que termina marcado como spam.
#: - **Por token, 10 cada 10 minutos.** Un script golpeando la MISMA URL, que
#:   es el único caso que llega a la base (un token basura muere en el HMAC,
#:   sin consulta). Una persona real hace 2 o 3 (abrir, confirmar, recargar);
#:   los escáneres que abren el enlace también caben.
#:
#: **Son por máquina**, no globales — el porqué y lo que cuesta, en
#: `app/common/rate_limit.py`.
_by_ip = FixedWindowLimiter(limit=60, window_seconds=60)
_by_token = FixedWindowLimiter(limit=10, window_seconds=600)
#: Un token válido mide ~67 caracteres. La llave se recorta para que una ruta
#: de un megabyte no se guarde entera en memoria.
_TOKEN_KEY_CHARS = 128


async def _rate_limit(request: Request, token: str) -> None:
    for limiter, key in ((_by_ip, client_ip(request)), (_by_token, token[:_TOKEN_KEY_CHARS])):
        wait = limiter.hit(key)
        if wait is not None:
            raise RateLimitedError(
                "Demasiados intentos seguidos. Espere un momento y vuelva a intentarlo.",
                retry_after_seconds=wait,
            )


public_router = APIRouter(
    prefix="/api/v1/public/unsubscribe", tags=["public"], dependencies=[Depends(_rate_limit)]
)

# Configurar los avisos es configurar la empresa (docs/NOTIFICACIONES.md §4.3,
# §7): el mismo permiso que ya protege `PATCH /company/settings`. Y ver las
# entregas también, porque trae las direcciones de correo de los clientes.
_configure = require_permission("company.configure")


@router.get("/settings", response_model=NotificationSettingsOut)
async def get_notification_settings(
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> NotificationSettingsOut:
    return await service.get_settings_for_company(db, company_id=user.company_id)


@router.patch("/settings", response_model=NotificationSettingsOut)
async def update_notification_settings(
    body: NotificationSettingsUpdateIn,
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> NotificationSettingsOut:
    return await service.update_settings_for_company(
        db, company_id=user.company_id, body=body, actor_id=user.id
    )


@router.get("/deliveries", response_model=CursorPage[DeliveryOut])
async def list_notification_deliveries(
    user: Annotated[CurrentUser, Depends(_configure)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status: Annotated[DeliveryStatus | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
) -> CursorPage[DeliveryOut]:
    """Entregas recientes, las más nuevas primero. Incluye las que NO salieron
    (`unroutable`, `suppressed`, `skipped_*`): son la mayoría y son información."""
    return await service.list_deliveries(
        db,
        company_id=user.company_id,
        cursor=decode_time_cursor(cursor) if cursor else None,
        limit=limit,
        status=status,
        event_type=event_type,
    )


@public_router.get("/{token}", response_model=UnsubscribeOut)
async def get_unsubscribe(
    token: str, request: Request, db: Annotated[AsyncSession, Depends(get_db)]
) -> UnsubscribeOut | RedirectResponse:
    """Lo que muestra la página de baja. **Solo lee: NUNCA da de baja.** Los
    escáneres de correo y las vistas previas abren cada enlace apenas llega
    (03/09/2026); si este GET escribiera, un cliente quedaría fuera sin haber
    abierto el correo. La baja es el `POST`.

    **Un navegador que llega acá directo se va a la página del front.** Pasa
    con la cabecera `List-Unsubscribe` (§17-bis), que apunta a esta URL: un
    cliente de correo que no sabe hacer el POST de un clic la abre en el
    navegador, y mostrarle a un cliente de la compraventa un JSON crudo sería
    un callejón sin salida. Se distingue por `Accept: text/html`, que manda un
    navegador al navegar y nunca el `fetch` de la página (`*/*`). Redirigir
    tampoco escribe: la baja sigue siendo el clic en la página."""
    if "text/html" in request.headers.get("accept", ""):
        page = unsubscribe.page_link_for_token(token)
        if page is not None:
            return RedirectResponse(page, status_code=303)
    return await service.get_unsubscribe(db, token=token)


@public_router.post("/{token}", response_model=UnsubscribeOut)
async def confirm_unsubscribe(
    token: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> UnsubscribeOut:
    """Confirma la baja. Idempotente: repetirla devuelve la fecha original.

    **Es también el destino del POST de un clic (RFC 8058, §17-bis):** Gmail o
    Yahoo lo mandan desde su servidor con el cuerpo
    `List-Unsubscribe=One-Click` (form-urlencoded) y esperan la baja hecha, sin
    página intermedia. El cuerpo se ignora —no hay nada en él que decida algo—,
    así que el mismo endpoint sirve a la página del front (que no manda
    cuerpo) y al proveedor de correo."""
    return await service.confirm_unsubscribe(db, token=token)
