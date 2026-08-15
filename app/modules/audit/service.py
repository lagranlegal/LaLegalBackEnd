from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.modules.audit import repository
from app.modules.audit.schemas import AuditLogOut


def _row_to_out(row: Row[Any]) -> AuditLogOut:
    m = row._mapping
    return AuditLogOut(
        id=m["id"],
        user_id=m["user_id"],
        module=m["module"],
        action=m["action"],
        entity_type=m["entity_type"],
        entity_id=m["entity_id"],
        before=m["before"],
        after=m["after"],
        created_at=m["created_at"],
    )


async def list_audit_log(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    module: str | None,
    entity_type: str | None,
    entity_id: UUID | None,
    user_id: UUID | None,
) -> CursorPage[AuditLogOut]:
    rows = await repository.list_audit_log(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        user_id=user_id,
    )
    return make_page([_row_to_out(r) for r in rows], limit, lambda o: o.id)
