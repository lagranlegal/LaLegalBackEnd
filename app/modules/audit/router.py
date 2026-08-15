from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.audit import service
from app.modules.audit.schemas import AuditLogOut

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit"])

_view = require_permission("audit.view")


@router.get("", response_model=CursorPage[AuditLogOut])
async def list_audit_log(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    module: Annotated[str | None, Query()] = None,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[UUID | None, Query()] = None,
    user_id: Annotated[UUID | None, Query()] = None,
) -> CursorPage[AuditLogOut]:
    return await service.list_audit_log(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
    )
