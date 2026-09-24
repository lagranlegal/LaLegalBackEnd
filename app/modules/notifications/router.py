from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_time_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.notifications import service
from app.modules.notifications.schemas import (
    DeliveryOut,
    DeliveryStatus,
    NotificationSettingsOut,
    NotificationSettingsUpdateIn,
)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

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
