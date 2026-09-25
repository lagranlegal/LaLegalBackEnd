from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_time_cursor
from app.core.db import get_db
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.notifications import service
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
public_router = APIRouter(prefix="/api/v1/public/unsubscribe", tags=["public"])

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
    token: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> UnsubscribeOut:
    """Lo que muestra la página de baja. **Solo lee: NUNCA da de baja.** Los
    escáneres de correo y las vistas previas abren cada enlace apenas llega
    (03/09/2026); si este GET escribiera, un cliente quedaría fuera sin haber
    abierto el correo. La baja es el `POST`."""
    return await service.get_unsubscribe(db, token=token)


@public_router.post("/{token}", response_model=UnsubscribeOut)
async def confirm_unsubscribe(
    token: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> UnsubscribeOut:
    """Confirma la baja. Idempotente: repetirla devuelve la fecha original.
    Ignora el cuerpo, así que también sirve de destino de un
    `List-Unsubscribe-Post` el día que se agreguen esas cabeceras."""
    return await service.confirm_unsubscribe(db, token=token)
