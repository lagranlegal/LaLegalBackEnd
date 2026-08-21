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
    InventoryValuationCategoryOut,
    InventoryValuationOut,
    PawnPerformanceOut,
    PayablesOut,
    ProfitSummaryOut,
    SalesKpisOut,
    StaleInventoryOut,
    StaleItemOut,
    SupplierPayableOut,
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


async def get_pawn_performance(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> PawnPerformanceOut:
    if from_date > to_date:
        raise AppError("`from_date` no puede ser posterior a `to_date`.")
    if (to_date - from_date).days > _MAX_PROFIT_RANGE_DAYS:
        raise AppError(
            f"El rango no puede superar {_MAX_PROFIT_RANGE_DAYS} días.",
            details={"from_date": str(from_date), "to_date": str(to_date)},
        )

    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    row = await repository.pawn_performance(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    m = row._mapping

    interest: Decimal = m["interest_collected"]
    outstanding: Decimal = m["capital_outstanding"]
    # `None` y no 0 sin cartera abierta: 0% afirmaría "presté y no rindió",
    # distinto de "no hay capital prestado contra el cual medir".
    yield_pct = (
        (interest / outstanding * 100).quantize(Decimal("0.01")) if outstanding > 0 else None
    )

    return PawnPerformanceOut(
        from_date=from_date,
        to_date=to_date,
        interest_collected=interest,
        interest_discounts=m["interest_discounts"],
        capital_recovered=m["capital_recovered"],
        capital_disbursed=m["capital_disbursed"],
        payment_count=m["payment_count"],
        contracts_opened=m["contracts_opened"],
        capital_outstanding=outstanding,
        open_contracts=m["open_contracts"],
        yield_on_current_portfolio_pct=yield_pct,
    )


def _dec(value: Any) -> Decimal:
    """`sum(...) filter (...)` devuelve NULL cuando ningún registro cae en el
    tramo, y un tramo vacío es CERO, no "sin dato" — en un reporte de dinero un
    hueco se lee como error del sistema."""
    return Decimal(str(value)) if value is not None else Decimal("0.00")


async def get_payables(db: AsyncSession, *, company_id: UUID) -> PayablesOut:
    """Cuentas por pagar con antigüedad.

    "¿Cuánto debo, a quién, y desde hace cuánto?" — la pregunta que el sistema
    ya podía responder fila por fila y ninguna pantalla sumaba.
    """
    as_of = await platform_integration.get_company_today(db, company_id=company_id)
    rows = await repository.payables_by_supplier(db, company_id=company_id, as_of=as_of)

    by_supplier = [
        SupplierPayableOut(
            supplier_id=r._mapping["supplier_id"],
            supplier_name=r._mapping["supplier_name"],
            entry_count=r._mapping["entry_count"],
            total=_dec(r._mapping["total"]),
            days_0_30=_dec(r._mapping["days_0_30"]),
            days_31_60=_dec(r._mapping["days_31_60"]),
            days_over_60=_dec(r._mapping["days_over_60"]),
            oldest_entry_date=r._mapping["oldest_entry_date"],
        )
        for r in rows
    ]
    return PayablesOut(
        as_of=as_of,
        total=sum((s.total for s in by_supplier), start=Decimal("0.00")),
        entry_count=sum(s.entry_count for s in by_supplier),
        days_0_30=sum((s.days_0_30 for s in by_supplier), start=Decimal("0.00")),
        days_31_60=sum((s.days_31_60 for s in by_supplier), start=Decimal("0.00")),
        days_over_60=sum((s.days_over_60 for s in by_supplier), start=Decimal("0.00")),
        by_supplier=by_supplier,
    )


async def get_inventory_valuation(db: AsyncSession, *, company_id: UUID) -> InventoryValuationOut:
    as_of = await platform_integration.get_company_today(db, company_id=company_id)
    rows = await repository.inventory_valuation(db, company_id=company_id)

    by_category = [
        InventoryValuationCategoryOut(
            cat1_id=r._mapping["cat1_id"],
            cat1_name=r._mapping["cat1_name"],
            units=r._mapping["units"] or 0,
            cost_value=_dec(r._mapping["cost_value"]),
            retail_value=_dec(r._mapping["retail_value"]),
        )
        for r in rows
    ]
    cost_value = sum((c.cost_value for c in by_category), start=Decimal("0.00"))
    retail_value = sum((c.retail_value for c in by_category), start=Decimal("0.00"))
    return InventoryValuationOut(
        as_of=as_of,
        units=sum(c.units for c in by_category),
        lot_count=sum(r._mapping["lot_count"] for r in rows),
        cost_value=cost_value,
        retail_value=retail_value,
        # Puede ser NEGATIVA y eso es información, no un error: significa que
        # hay mercancía cuyo precio de venta quedó por debajo del costo. Vale
        # más verlo que esconderlo detrás de un max(0).
        potential_profit=retail_value - cost_value,
        by_category=by_category,
    )


async def get_stale_inventory(
    db: AsyncSession, *, company_id: UUID, threshold_days: int, limit: int
) -> StaleInventoryOut:
    as_of = await platform_integration.get_company_today(db, company_id=company_id)
    rows = await repository.stale_inventory(
        db,
        company_id=company_id,
        as_of=as_of,
        threshold_days=threshold_days,
        limit=limit,
    )
    items = [
        StaleItemOut(
            product_id=r._mapping["product_id"],
            product_code=r._mapping["product_code"],
            product_name=r._mapping["product_name"],
            units=r._mapping["units"] or 0,
            cost_value=_dec(r._mapping["cost_value"]),
            days_in_stock=r._mapping["days_in_stock"] or 0,
        )
        for r in rows
    ]
    return StaleInventoryOut(
        as_of=as_of,
        threshold_days=threshold_days,
        product_count=len(items),
        total_cost_value=sum((i.cost_value for i in items), start=Decimal("0.00")),
        items=items,
    )
