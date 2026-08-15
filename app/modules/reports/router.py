from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.reports import service
from app.modules.reports.schemas import ClosingHistoryOut, DashboardOut

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])

_view = require_permission("reports.view")


@router.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> DashboardOut:
    return await service.get_dashboard(db, company_id=user.company_id)


@router.get("/closings", response_model=CursorPage[ClosingHistoryOut])
async def list_closings(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> CursorPage[ClosingHistoryOut]:
    return await service.list_closings(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    )
