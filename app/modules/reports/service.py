from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.common.tenant_time import today_in
from app.modules.platform import integration as platform_integration
from app.modules.reports import repository
from app.modules.reports.schemas import (
    CashboxKpisOut,
    ClosingHistoryOut,
    ContractKpisOut,
    DashboardOut,
    InventoryKpisOut,
    SalesKpisOut,
)


def _row_to_closing(row: Row[Any]) -> ClosingHistoryOut:
    m = row._mapping
    return ClosingHistoryOut(
        session_id=m["id"],
        session_date=m["session_date"],
        opening_balance=m["opening_balance"],
        expected_cash=m["expected_cash"],
        counted_cash=m["counted_cash"],
        difference=m["difference"],
        difference_reason=m["difference_reason"],
        closed_by=m["closed_by"],
        closed_at=m["closed_at"],
    )


async def get_dashboard(db: AsyncSession, *, company_id: UUID) -> DashboardOut:
    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    today = today_in(tz_name)

    contract_row = await repository.contract_kpis(db, company_id=company_id, today=today)
    sales_row = await repository.sales_kpis(db, company_id=company_id, tz_name=tz_name, today=today)
    inventory_row = await repository.inventory_kpis(db, company_id=company_id)
    session_row = await repository.current_open_session(db, company_id=company_id)

    cm, sm, im = contract_row._mapping, sales_row._mapping, inventory_row._mapping
    session_m = session_row._mapping if session_row is not None else None

    return DashboardOut(
        as_of=today,
        contracts=ContractKpisOut(
            active_count=cm["active_count"],
            in_arrears_count=cm["in_arrears_count"],
            in_extension_count=cm["in_extension_count"],
            ready_for_auction_count=cm["ready_for_auction_count"],
            auctioned_count=cm["auctioned_count"],
            capital_outstanding=cm["capital_outstanding"],
        ),
        sales=SalesKpisOut(
            today_total=sm["today_total"],
            today_count=sm["today_count"],
            month_total=sm["month_total"],
        ),
        inventory=InventoryKpisOut(
            available_count=im["available_count"],
            available_value=im["available_value"],
            draft_count=im["draft_count"],
        ),
        cashbox=CashboxKpisOut(
            session_open=session_m is not None,
            session_id=session_m["id"] if session_m else None,
            opened_at=session_m["opened_at"] if session_m else None,
            opening_balance=session_m["opening_balance"] if session_m else None,
        ),
    )


async def list_closings(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    from_date: date | None,
    to_date: date | None,
) -> CursorPage[ClosingHistoryOut]:
    rows = await repository.list_closings(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    )
    return make_page([_row_to_closing(r) for r in rows], limit, lambda o: o.session_id)
