from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.common.tenant_time import today_in
from app.core.errors import AppError
from app.modules.platform import integration as platform_integration
from app.modules.reports import repository
from app.modules.reports.schemas import (
    CashboxKpisOut,
    ClosingHistoryOut,
    ContractKpisOut,
    DashboardOut,
    InventoryKpisOut,
    ProfitSummaryOut,
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


_MAX_PROFIT_RANGE_DAYS = 366


async def get_profit_summary(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> ProfitSummaryOut:
    """Utilidad bruta del período. A diferencia de `/reportes` del front —que
    agrega sesiones de caja y por eso tiene tope de 90 días— esto es UNA
    consulta agregada en Postgres, así que un rango de un año no cuesta más
    que uno de un día.
    """
    if from_date > to_date:
        raise AppError("`from_date` no puede ser posterior a `to_date`.")
    if (to_date - from_date).days > _MAX_PROFIT_RANGE_DAYS:
        raise AppError(
            f"El rango no puede superar {_MAX_PROFIT_RANGE_DAYS} días.",
            details={"from_date": str(from_date), "to_date": str(to_date)},
        )

    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    row = await repository.profit_summary(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    m = row._mapping

    gross_revenue: Decimal = m["gross_revenue"]
    discounts: Decimal = m["discounts"]
    cogs: Decimal = m["cost_of_goods_sold"]
    net_revenue = gross_revenue - discounts
    gross_profit = net_revenue - cogs

    # `None` y no 0 cuando no hubo ingresos: un margen de 0% dice "vendí sin
    # ganar", que es una afirmación distinta de "no hay datos".
    margin_pct = (
        (gross_profit / net_revenue * 100).quantize(Decimal("0.01")) if net_revenue > 0 else None
    )

    return ProfitSummaryOut(
        from_date=from_date,
        to_date=to_date,
        sale_count=m["sale_count"],
        units_sold=m["units_sold"],
        gross_revenue=gross_revenue,
        discounts=discounts,
        net_revenue=net_revenue,
        cost_of_goods_sold=cogs,
        gross_profit=gross_profit,
        margin_pct=margin_pct,
    )
