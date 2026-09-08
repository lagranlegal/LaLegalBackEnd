from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = "id, user_id, module, action, entity_type, entity_id, before, after, created_at"


async def list_audit_log(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
    module: str | None,
    entity_type: str | None,
    entity_id: UUID | None,
    user_id: UUID | None,
) -> list[Row[Any]]:
    query = f"select {_COLUMNS} from public.audit_log where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if module is not None:
        query += " and module = :module"
        params["module"] = module
    if entity_type is not None:
        query += " and entity_type = :entity_type"
        params["entity_type"] = entity_type
    if entity_id is not None:
        query += " and entity_id = :entity_id"
        params["entity_id"] = str(entity_id)
    if user_id is not None:
        query += " and user_id = :user_id"
        params["user_id"] = str(user_id)
    # Keyset por `(created_at, id)`, no por `id`.
    #
    # Ordenaba `by id`, y los ids son UUID aleatorios: la auditoría salía en
    # orden ARBITRARIO. Lo último que hizo un empleado podía estar en
    # cualquier página, así que la pantalla no respondía "¿qué pasó hoy?" ni
    # con las acciones que sí se registraban. Reportado el 08/09/2026.
    #
    # El índice que esto necesita —`ix_audit_company_date (company_id,
    # created_at desc)`— ya existía en las migraciones desde el principio;
    # nadie lo usaba.
    if cursor is not None:
        query += " and (created_at, id) < (:cursor_at, :cursor_id)"
        params["cursor_at"] = cursor[0]
        params["cursor_id"] = str(cursor[1])
    query += " order by created_at desc, id desc limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())
