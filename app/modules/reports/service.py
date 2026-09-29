from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.money import quantize
from app.common.pagination import CursorPage, make_page
from app.common.tenant_time import today_in
from app.core.errors import InvalidDateRangeError
from app.modules.platform import integration as platform_integration
from app.modules.reports import repository
from app.modules.reports.schemas import (
    CashboxKpisOut,
    ClosingHistoryOut,
    ClosingsBreakdownLineOut,
    ClosingsBreakdownOut,
    ContractKpisOut,
    DashboardOut,
    IncomeStatementOut,
    InventoryKpisOut,
    InventoryValuationCategoryOut,
    InventoryValuationOut,
    MonthlySeriesOut,
    MonthlySeriesPointOut,
    PawnPerformanceOut,
    PayablesOut,
    ProfitSummaryOut,
    SalesCashFlowOut,
    SalesKpisOut,
    StaleInventoryOut,
    StaleItemOut,
    SupplierPayableOut,
)


def _dec(value: Any) -> Decimal:
    """`sum(...) filter (...)` devuelve NULL cuando ningún registro cae en el
    tramo, y un tramo vacío es CERO, no "sin dato" — en un reporte de dinero un
    hueco se lee como error del sistema."""
    return Decimal(str(value)) if value is not None else Decimal("0.00")


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
            today_gross=sm["today_gross"],
            today_returns=sm["today_returns"],
            month_gross=sm["month_gross"],
            month_returns=sm["month_returns"],
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


async def get_closings_breakdown(
    db: AsyncSession, *, company_id: UUID, from_date: date | None, to_date: date | None
) -> ClosingsBreakdownOut:
    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    rows = await repository.closings_breakdown(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )

    def _suma(direction: str, concept: str) -> Decimal:
        return sum(
            (
                _dec(r._mapping["total"])
                for r in rows
                if r._mapping["direction"] == direction and r._mapping["concept"] == concept
            ),
            start=Decimal("0.00"),
        )

    # F7-05: el resumen sale de las MISMAS líneas, así que no puede separarse
    # del desglose que acompaña.
    cobros, anuladas, devueltas = (
        _suma("in", "sale"),
        _suma("out", "sale"),
        _suma("out", "sale_return"),
    )
    return ClosingsBreakdownOut(
        sales_flow=SalesCashFlowOut(
            sales_in=cobros,
            voided_out=anuladas,
            returns_out=devueltas,
            net_sales_flow=cobros - anuladas - devueltas,
        ),
        lines=[
            ClosingsBreakdownLineOut(
                module=r._mapping["module"],
                direction=r._mapping["direction"],
                concept=r._mapping["concept"],
                payment_method=r._mapping["payment_method"],
                account_id=r._mapping["account_id"],
                account_name=r._mapping["account_name"],
                account_type=r._mapping["account_type"],
                session_date=r._mapping["session_date"],
                total=r._mapping["total"],
            )
            for r in rows
        ],
    )


_MAX_PROFIT_RANGE_DAYS = 366


def _validate_range(from_date: date, to_date: date, *, max_days: int | None = None) -> None:
    """Una sola regla de rango para todos los reportes por período (F7-14,
    auditoría fase 7): el estado de resultados —y `capital/position`, que lo
    llama— aceptaba un rango invertido y respondía 200 con todo en cero, un
    «no hubo nada» que no es cierto. Y los dos que sí lo rechazaban lo hacían
    con el 400 genérico, indistinguible de cualquier otra falla.

    El tope de días es por endpoint y OPCIONAL: `capital/position` pide la
    utilidad «desde siempre» y es una sola consulta agregada."""
    details = {"from_date": str(from_date), "to_date": str(to_date)}
    if from_date > to_date:
        raise InvalidDateRangeError(
            "La fecha inicial no puede ser posterior a la final.", details=details
        )
    if max_days is not None and (to_date - from_date).days > max_days:
        raise InvalidDateRangeError(
            f"El rango no puede superar {max_days} días.",
            details={**details, "max_days": max_days},
            code="DATE_RANGE_TOO_LONG",
        )


async def get_profit_summary(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> ProfitSummaryOut:
    """Utilidad bruta del período. A diferencia de `/reportes` del front —que
    agrega sesiones de caja y por eso tiene tope de 90 días— esto es UNA
    consulta agregada en Postgres, así que un rango de un año no cuesta más
    que uno de un día.
    """
    _validate_range(from_date, to_date, max_days=_MAX_PROFIT_RANGE_DAYS)

    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    row = await repository.profit_summary(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    m = row._mapping

    gross_revenue: Decimal = m["gross_revenue"]
    discounts: Decimal = m["discounts"]
    # F21-12: la devolución es CONTRA-INGRESO del período en que se devolvió,
    # no una borradura de la venta. `returns` ya viene neto del descuento
    # prorrateado de su venta original (ver `repository.profit_summary`), así
    # que restarlo acá no vuelve a quitar ese descuento.
    returns = _dec(m["returns_gross"]) - _dec(m["returns_discounts"])
    returns_cost = _dec(m["returns_cost"])
    # El costo se devuelve NETO: la mercancía volvió al inventario, y dejar su
    # costo dentro del costo de ventas era la otra mitad del doble conteo.
    cogs = _dec(m["cost_of_goods_sold"]) - returns_cost
    net_revenue = gross_revenue - discounts - returns
    gross_profit = net_revenue - cogs

    # `None` y no 0 cuando no hubo ingresos: un margen de 0% dice "vendí sin
    # ganar", que es una afirmación distinta de "no hay datos".
    margin_pct = (
        (gross_profit / net_revenue * 100).quantize(Decimal("0.01")) if net_revenue > 0 else None
    )

    price_discounts = _dec(m["price_discounts"])
    return ProfitSummaryOut(
        from_date=from_date,
        to_date=to_date,
        sale_count=m["sale_count"],
        units_sold=m["units_sold"],
        gross_revenue=gross_revenue,
        discounts=discounts,
        price_discounts=price_discounts,
        total_discounts=discounts + price_discounts,
        auction_interest_realized=_dec(m["auction_interest"]),
        sales_returns=returns,
        return_count=m["return_count"] or 0,
        net_revenue=net_revenue,
        cost_of_goods_sold=cogs,
        returns_cost=returns_cost,
        gross_profit=gross_profit,
        margin_pct=margin_pct,
    )


async def get_pawn_performance(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> PawnPerformanceOut:
    _validate_range(from_date, to_date, max_days=_MAX_PROFIT_RANGE_DAYS)

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

    interest_net = interest - _dec(m["interest_discounts"])
    return PawnPerformanceOut(
        from_date=from_date,
        to_date=to_date,
        interest_collected=interest,
        interest_discounts=m["interest_discounts"],
        interest_revenue=interest_net,
        net_yield_on_current_portfolio_pct=(
            (interest_net / outstanding * 100).quantize(Decimal("0.01"))
            if outstanding > 0
            else None
        ),
        capital_recovered=m["capital_recovered"],
        capital_disbursed=m["capital_disbursed"],
        payment_count=m["payment_count"],
        contracts_opened=m["contracts_opened"],
        capital_outstanding=outstanding,
        open_contracts=m["open_contracts"],
        yield_on_current_portfolio_pct=yield_pct,
    )


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
            units=r._mapping["units"] or Decimal("0"),
            cost_value=_dec(r._mapping["cost_value"]),
            retail_value=_dec(r._mapping["retail_value"]),
        )
        for r in rows
    ]
    cost_value = sum((c.cost_value for c in by_category), start=Decimal("0.00"))
    retail_value = sum((c.retail_value for c in by_category), start=Decimal("0.00"))
    return InventoryValuationOut(
        as_of=as_of,
        units=sum((c.units for c in by_category), start=Decimal("0")),
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
            units=r._mapping["units"] or Decimal("0"),
            cost_value=_dec(r._mapping["cost_value"]),
            days_in_stock=r._mapping["days_in_stock"] or 0,
        )
        for r in rows
    ]
    # Los totales son del UNIVERSO, no de la página (F21-25). Antes salían de
    # `items`, que el front pide con `limit=20`: con más de 20 productos sobre
    # el umbral la tarjeta decía "N productos con $X detenidos" y las dos
    # cifras quedaban CORTAS. Subestimar es la dirección peligrosa —el dueño
    # mira ese número para decidir si remata— y no fallaba ni avisaba: con
    # pocos productos daba bien, así que el error aparecía solo al crecer.
    # La lista sí sigue topada: es un ranking de los más dormidos, no el
    # inventario entero.
    totals = rows[0]._mapping if rows else None
    return StaleInventoryOut(
        as_of=as_of,
        threshold_days=threshold_days,
        product_count=totals["total_product_count"] if totals else 0,
        total_cost_value=_dec(totals["total_cost_value"]) if totals else Decimal("0.00"),
        items=items,
    )


async def get_income_statement(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> IncomeStatementOut:
    """Estado de resultados del período: ingresos − costo de ventas − gastos.

    ARREGLA UN NÚMERO QUE ESTABA MAL. La "utilidad operativa" de `/reportes`
    calculaba `ingresos − gastos` y nunca restaba el costo de ventas: una
    cadena vendida en 500.000 que costó 300.000 contaba como 500.000 de
    utilidad. Para una tienda eso sobreestima la ganancia por todo el costo de
    la mercancía, y en la misma pantalla convivía con "Utilidad bruta de
    tienda", que sí lo restaba — dos cifras que se contradecían.

    NO reimplementa ninguna regla: reusa `profit_summary` (tienda) y
    `pawn_performance` (empeño), que ya definen cada número una sola vez y con
    sus salvedades documentadas. Acá solo se suman y se ordenan.

    Los movimientos de CAPITAL van aparte del resultado, no dentro: prestar no
    es un gasto y cobrar no es una ganancia — el principio que este proyecto
    ya pagó caro tres veces. Comprar inventario tampoco es gasto: es efectivo
    que se vuelve activo, y se convierte en gasto cuando se VENDE, momento en
    el que ya está contado en `cost_of_goods_sold`.
    """
    _validate_range(from_date, to_date)
    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)

    tienda = await repository.profit_summary(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    empeno = await repository.pawn_performance(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    gastos = await repository.operating_expenses(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    compras = await repository.inventory_purchased(
        db, company_id=company_id, from_date=from_date, to_date=to_date
    )
    mermas = await repository.inventory_shrinkage(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    comisiones = await repository.settlement_commissions(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    pagos_compras = await repository.inventory_purchase_payments(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )
    descuadres = await repository.cash_differences(
        db, company_id=company_id, tz_name=tz_name, from_date=from_date, to_date=to_date
    )

    t, e, g = tienda._mapping, empeno._mapping, gastos._mapping

    # Cada renglón se redondea a centavos UNA vez, acá, y los subtotales se
    # derivan de los renglones YA redondeados. Antes se sumaba con los
    # valores crudos (el costo sale de `costo × cantidad` con cantidades de 3
    # decimales) y `MoneyOut` redondeaba cada campo al serializar, así que un
    # subtotal podía no ser la resta de los renglones que se ven encima
    # (verificación de la tanda F/G: «1 peso entre renglones»). Un estado de
    # resultados que no se puede rehacer sumando a mano no se cree.
    def _q(value: Any) -> Decimal:
        return quantize(_dec(value))

    # Los dos ingresos se calculan igual: brutos MENOS los descuentos otorgados.
    # Un descuento es plata que se decidió no cobrar —una rebaja del ingreso—, no
    # un dato informativo, y da lo mismo que sea sobre una venta o sobre un
    # interés. Hasta el 09/09/2026 el de intereses no se restaba, así que la
    # utilidad se sobreestimaba por todos los descuentos de interés otorgados, y
    # `/reports/series` arrastraba el mismo sesgo por usar esta definición.
    ventas = _q(t["gross_revenue"]) - _q(t["discounts"])
    intereses = _q(e["interest_collected"]) - _q(e["interest_discounts"])
    # F21-12: las devoluciones son CONTRA-INGRESO con LÍNEA PROPIA, no un
    # descuento silencioso de «Ventas». Restarlas adentro dejaría a «Ventas»
    # bajando sin explicación, que es exactamente lo que hace que nadie
    # confíe en un reporte; y una devolución es un hecho del negocio que el
    # dueño quiere ver. Caen en el período de la devolución, así que un mes
    # ya cerrado no cambia hacia atrás.
    devoluciones = _q(t["returns_gross"]) - _q(t["returns_discounts"])
    ingresos = ventas - devoluciones + intereses
    # Neto del costo de lo devuelto: volvió al inventario, así que ya no es
    # costo de nada vendido. Con eso se cierra el doble conteo — el artículo
    # cuenta como inventario disponible y NO como costo de ventas.
    costo_ventas = _q(t["cost_of_goods_sold"]) - _q(t["returns_cost"])
    utilidad_bruta = ingresos - costo_ventas
    gastos_operativos = _q(g["total"])
    # FASE 7 (auditoría 28/09/2026): lo que movía el patrimonio sin pasar por
    # el resultado. El cuadre patrimonial dejaba un residuo que se explicaba
    # entero por estas tres líneas (y por el interés del remate, que se
    # resuelve en el costo de ventas). Cada una en su propia línea y no
    # dentro de «Gastos operativos»: son hechos distintos que el dueño quiere
    # ver por separado, y `expense` es un documento que ellas no son.
    mermas_total = _q(mermas._mapping["total"])
    comisiones = quantize(comisiones)
    descuadres = quantize(descuadres)
    utilidad = utilidad_bruta - gastos_operativos - mermas_total - comisiones + descuadres

    return IncomeStatementOut(
        from_date=from_date,
        to_date=to_date,
        sales_revenue=ventas,
        sales_returns=devoluciones,
        interest_revenue=intereses,
        total_revenue=ingresos,
        cost_of_goods_sold=costo_ventas,
        gross_profit=utilidad_bruta,
        operating_expenses=gastos_operativos,
        expense_count=g["expense_count"] or 0,
        inventory_shrinkage=mermas_total,
        shrinkage_exit_count=mermas._mapping["exit_count"] or 0,
        settlement_commissions=comisiones,
        cash_differences=descuadres,
        operating_profit=utilidad,
        # `null` y no 0% cuando no hubo ingresos: un margen de cero sugiere que
        # se vendió sin ganar, y lo cierto es que no se vendió.
        margin_pct=(
            (utilidad / ingresos * 100).quantize(Decimal("0.01")) if ingresos > 0 else None
        ),
        interest_discounts=_dec(e["interest_discounts"]),
        sales_discounts=_dec(t["discounts"]) + _dec(t["price_discounts"]),
        auction_interest_realized=_dec(t["auction_interest"]),
        capital_disbursed=_dec(e["capital_disbursed"]),
        capital_recovered=_dec(e["capital_recovered"]),
        inventory_purchased=compras,
        inventory_purchases_paid=_dec(pagos_compras._mapping["purchases_paid"]),
        transformation_costs_paid=_dec(pagos_compras._mapping["transformation_paid"]),
    )


async def monthly_series(db: AsyncSession, *, company_id: UUID, months: int) -> MonthlySeriesOut:
    """Serie mensual de ingresos operativos y gastos, para la gráfica de
    tendencia (`docs/PENDIENTES_BACKEND_INFRA.md` §7).

    No define ninguna regla nueva: el interés y la venta se miden igual que en
    `pawn_performance`/`profit_summary`, y el gasto igual que en
    `operating_expenses`. Si esa definición cambia, tiene que cambiar en un
    solo lugar — por eso esto se apoya en la misma consulta y no inventa otra.
    """
    tz_name = await platform_integration.get_company_timezone(db, company_id=company_id)
    rows = await repository.monthly_series(
        db, company_id=company_id, tz_name=tz_name, months=months
    )
    return MonthlySeriesOut(
        months=months,
        points=[
            MonthlySeriesPointOut(
                month=row._mapping["month"],
                interest_revenue=quantize(row._mapping["interest_revenue"]),
                sales_revenue=quantize(row._mapping["sales_revenue"]),
                sales_returns=quantize(row._mapping["sales_returns"]),
                expenses=quantize(row._mapping["expenses"]),
            )
            for row in rows
        ],
    )
