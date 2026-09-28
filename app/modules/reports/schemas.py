from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from app.common.money import MoneyOut


class ContractKpisOut(BaseModel):
    active_count: int
    in_arrears_count: int
    in_extension_count: int
    ready_for_auction_count: int
    auctioned_count: int
    capital_outstanding: MoneyOut


class SalesKpisOut(BaseModel):
    """Ventas del dashboard (F7-07). `today_total`/`month_total` son NETAS de
    devoluciones —la misma cifra que `income-statement.sales_revenue −
    sales_returns` para ese día o mes—; una venta anulada nunca cuenta. El
    bruto y las devoluciones van aparte para poder explicar la resta."""

    #: Ventas netas de hoy: `today_gross − today_returns`.
    today_total: MoneyOut
    #: Ventas `completed` de hoy (cuántas), sin restar devoluciones.
    today_count: int
    #: Ventas netas del mes: `month_gross − month_returns`.
    month_total: MoneyOut
    #: Σ `sale.total` de las ventas `completed` (neto del descuento de cabecera).
    today_gross: MoneyOut = Decimal("0.00")
    #: Devoluciones registradas HOY (por `return_date`), aunque la venta sea
    #: de otro día — el contra-ingreso cae en el período de la devolución.
    today_returns: MoneyOut = Decimal("0.00")
    month_gross: MoneyOut = Decimal("0.00")
    month_returns: MoneyOut = Decimal("0.00")


class InventoryKpisOut(BaseModel):
    available_count: int
    available_value: MoneyOut
    draft_count: int


class CashboxKpisOut(BaseModel):
    session_open: bool
    session_id: UUID | None
    opened_at: datetime | None
    opening_balance: MoneyOut | None


class DashboardOut(BaseModel):
    as_of: date
    contracts: ContractKpisOut
    sales: SalesKpisOut
    inventory: InventoryKpisOut
    cashbox: CashboxKpisOut


class ClosingHistoryOut(BaseModel):
    session_id: UUID
    session_date: date
    opening_balance: MoneyOut
    expected_cash: MoneyOut
    counted_cash: MoneyOut
    difference: MoneyOut
    difference_reason: str | None
    closed_by: UUID
    closed_at: datetime


class ClosingsBreakdownLineOut(BaseModel):
    module: str
    direction: str
    concept: str
    payment_method: str | None
    account_id: UUID
    account_name: str
    account_type: str
    session_date: date
    total: MoneyOut


class SalesCashFlowOut(BaseModel):
    """Ventas vistas desde la CAJA (F7-05): es FLUJO, no ingreso contable.

    El KPI de ventas de la pantalla Reportes se armaba sumando `sale/in` del
    desglose y nunca restaba la anulación (`sale/out`) ni la devolución en
    efectivo (`sale_return/out`): con una venta anulada de 1.200.000 decía
    «Ventas» 6.120.250 contra 5.120.250 del estado de resultados.

    Sigue siendo flujo: lo que se pagó con nota crédito no entró a caja y no
    está; lo vendido por Sistecrédito está el día de la venta, en la cuenta
    `settlement`. Para el INGRESO del período la fuente es
    `/reports/income-statement`.
    """

    #: Siempre `"cash_flow"`: rotula la naturaleza del número.
    kind: str = "cash_flow"
    description: str = (
        "Flujo de caja por ventas: cobros de venta menos anulaciones y devoluciones "
        "pagadas. No es el ingreso contable (ver /reports/income-statement)."
    )
    #: Σ `sale/in`: cobros de venta, en todas las cuentas.
    sales_in: MoneyOut
    #: Σ `sale/out`: contra-movimientos de ventas anuladas.
    voided_out: MoneyOut
    #: Σ `sale_return/out`: devoluciones pagadas (efectivo, transferencia).
    returns_out: MoneyOut
    #: `sales_in − voided_out − returns_out`.
    net_sales_flow: MoneyOut


class ClosingsBreakdownOut(BaseModel):
    lines: list[ClosingsBreakdownLineOut]
    #: Resumen de ventas del mismo rango y las mismas líneas (F7-05).
    sales_flow: SalesCashFlowOut | None = None


class ProfitSummaryOut(BaseModel):
    """Utilidad BRUTA (ingreso por ventas − costo de ventas). NO es la
    utilidad neta: no descuenta gastos operativos, que viven en caja y ya se
    reportan aparte en /reportes. Y cubre solo el módulo Tienda — la
    rentabilidad del empeño son los intereses cobrados, que no tienen costo de
    ventas asociado.
    """

    from_date: date
    to_date: date
    sale_count: int
    #: Unidades VENDIDAS en el rango, brutas de devoluciones: es actividad de
    #: venta, no dinero. Lo devuelto ya está descontado del dinero
    #: (`sales_returns`) y del costo (`returns_cost`). `Decimal` porque se
    #: vende por gramos (F6-02): 1,1 g no es un entero.
    units_sold: Decimal
    #: Suma de los subtotales de las líneas, antes de descuentos.
    gross_revenue: MoneyOut
    #: Descuentos aplicados a nivel de venta — menor ingreso, no un gasto.
    #: Solo la CABECERA (`sale.discount_amount`); el total está abajo.
    discounts: MoneyOut
    #: Descuento por vender bajo el precio PUBLICADO (F7-08): Σ
    #: `max(list_price − unit_price, 0) × quantity` de las líneas. Ya está
    #: dentro de `gross_revenue` (el subtotal viene rebajado), así que NO se
    #: resta otra vez: es informativo. Las ventas anteriores a 00063 solo lo
    #: tienen si quedó en la auditoría.
    price_discounts: MoneyOut = Decimal("0.00")
    #: `discounts + price_discounts`: todo lo que se dejó de cobrar sobre el
    #: precio publicado. El número de «descuentos aplicados».
    total_discounts: MoneyOut = Decimal("0.00")
    #: Interés que el remate capitalizó en el costo de las piezas vendidas,
    #: neto de devoluciones (F7-04). Ya está DENTRO de `gross_profit`: el
    #: costo de ventas usa como base el capital prestado, no el costo con
    #: interés. Informativo — no se suma otra vez.
    auction_interest_realized: MoneyOut = Decimal("0.00")
    #: CONTRA-INGRESO por devoluciones (*devoluciones en ventas*), ya neto del
    #: descuento prorrateado de su venta original. Cae en el período de la
    #: DEVOLUCIÓN (`sale_return.return_date`), no en el de la venta: así un mes
    #: ya cerrado no se reescribe hacia atrás.
    sales_returns: MoneyOut
    #: Cuántas devoluciones cayeron en el rango.
    return_count: int
    #: `gross_revenue - discounts - sales_returns`: lo que realmente entró por
    #: ventas y se quedó adentro.
    net_revenue: MoneyOut
    #: Costo congelado de lo vendido (`(sale_line.unit_cost −
    #: unit_cost_interest) * quantity`: una pieza rematada cuesta el capital
    #: prestado, no el interés capitalizado — F7-04), NETO de `returns_cost`.
    #: Neto y no bruto a propósito: lo devuelto volvió al inventario, así
    #: que dejar su costo acá lo contaría dos veces — una como
    #: costo de algo vendido y otra como mercancía disponible.
    cost_of_goods_sold: MoneyOut
    #: Costo de lo devuelto CON reingreso (`restock=true`), ya descontado de
    #: `cost_of_goods_sold`. Una devolución sin reingreso no descuenta su
    #: costo: la pieza no volvió, así que es costo sin inventario que lo
    #: respalde (F6-04). Se expone para poder auditar el neto, no para volver
    #: a restarlo.
    returns_cost: MoneyOut
    #: `net_revenue - cost_of_goods_sold`.
    gross_profit: MoneyOut
    #: Margen sobre el ingreso neto, en %. `null` si no hubo ventas (evita
    #: mostrar 0% cuando el dato correcto es "no aplica").
    margin_pct: Decimal | None


class PawnPerformanceOut(BaseModel):
    """Rentabilidad del EMPEÑO. Es una pregunta distinta a la de tienda: no hay
    costo de ventas, la rentabilidad son los intereses cobrados sobre el
    capital prestado — rendimiento sobre capital, no margen sobre costo.
    """

    from_date: date
    to_date: date
    #: Intereses efectivamente cobrados en el rango (`contract_payment`, el
    #: documento — no el movimiento de caja, que solo cubre sesiones cerradas).
    interest_collected: MoneyOut
    #: Descuentos de interés otorgados (permiso especial). Erosionan el
    #: rendimiento: son interés que se dejó de cobrar.
    interest_discounts: MoneyOut
    #: `interest_collected − interest_discounts` (F7-06): el interés NETO, la
    #: misma cifra que `income-statement.interest_revenue`. Es la que debe
    #: rotularse «Intereses cobrados»; el bruto y el descuento la explican.
    interest_revenue: MoneyOut = Decimal("0.00")
    #: Capital recuperado vía abonos — reduce cartera, NO es ingreso.
    capital_recovered: MoneyOut
    #: Capital que SALIÓ de caja por préstamos en el rango (contratos nuevos
    #: y el delta de cada recargo, por la fecha del movimiento; un importado
    #: no suma) — NO es gasto (F4-06).
    capital_disbursed: MoneyOut
    payment_count: int
    #: Préstamos nuevos del rango: ni sucesores de recargo ni importados.
    contracts_opened: int
    #: Cartera al corte de HOY, no del final del rango: el esquema no guarda
    #: `closed_at` ni histórico de saldos, así que no hay forma exacta de
    #: saber cuánta cartera había en una fecha pasada.
    capital_outstanding: MoneyOut
    open_contracts: int
    #: `interest_collected / capital_outstanding * 100` — rendimiento del
    #: período sobre la cartera ACTUAL. `null` si no hay cartera abierta.
    #: Es una referencia útil cuando el rango termina hoy (el caso normal);
    #: para rangos históricos la cartera de referencia ya no es la de entonces.
    yield_on_current_portfolio_pct: Decimal | None
    #: Igual, sobre el interés NETO (`interest_revenue`) — F7-06. El de arriba
    #: se conserva por compatibilidad y usa el bruto.
    net_yield_on_current_portfolio_pct: Decimal | None = None


class SupplierPayableOut(BaseModel):
    """Lo que se le debe a UN proveedor, con antigüedad.

    La antigüedad se mide desde `entry_date` (cuándo ENTRÓ la mercancía), no
    desde cuándo se digitó: es la fecha que le importa al proveedor y la que
    determina si una deuda está vencida.
    """

    supplier_id: UUID | None
    supplier_name: str
    entry_count: int
    total: MoneyOut
    #: Antigüedad por tramos — el corte estándar de una cartera por pagar.
    days_0_30: MoneyOut
    days_31_60: MoneyOut
    days_over_60: MoneyOut
    #: La compra pendiente MÁS ANTIGUA: la que más urge.
    oldest_entry_date: date | None


class PayablesOut(BaseModel):
    """Cuentas por pagar: "¿cuánto debo, a quién, y desde hace cuánto?".

    Es el primer reporte que pediría un contador y no existía, aunque cada
    compra ya sabía si estaba pagada: el dato estaba guardado y ninguna
    pantalla lo sumaba.
    """

    as_of: date
    total: MoneyOut
    entry_count: int
    days_0_30: MoneyOut
    days_31_60: MoneyOut
    days_over_60: MoneyOut
    by_supplier: list[SupplierPayableOut]


class InventoryValuationCategoryOut(BaseModel):
    cat1_id: UUID | None
    cat1_name: str
    #: `Decimal`: una cantidad puede ser fraccionaria (gramos, F6-02).
    units: Decimal
    cost_value: MoneyOut
    retail_value: MoneyOut


class InventoryValuationOut(BaseModel):
    """ "¿Cuánta plata tengo en mercancía?" — el activo más grande del negocio.

    Se valora AL COSTO, que es lo correcto contablemente y lo que sale de la
    identificación específica: cada lote con su costo real, nunca promediado.

    `retail_value` va aparte y es lo que se cobraría si se vendiera todo hoy.
    NO es el valor del inventario — contar la utilidad antes de venderla es el
    error clásico. Se expone porque responde otra pregunta legítima (cuánto hay
    en la vitrina a precio de venta) y porque la diferencia entre ambos es la
    utilidad que todavía no se ha realizado.
    """

    as_of: date
    #: `Decimal`: una cantidad puede ser fraccionaria (gramos, F6-02).
    units: Decimal
    lot_count: int
    #: Valor al costo. Este es EL número del inventario.
    cost_value: MoneyOut
    #: A precio de venta. Referencia, no valoración.
    retail_value: MoneyOut
    #: `retail_value - cost_value`: utilidad potencial, aún no realizada.
    potential_profit: MoneyOut
    by_category: list[InventoryValuationCategoryOut]


class StaleItemOut(BaseModel):
    product_id: UUID
    product_code: str | None
    product_name: str
    #: `Decimal`: una cantidad puede ser fraccionaria (gramos, F6-02).
    units: Decimal
    cost_value: MoneyOut
    #: Días desde que entró el lote disponible más ANTIGUO de ese producto.
    days_in_stock: int


class StaleInventoryOut(BaseModel):
    """Mercancía disponible que lleva mucho sin moverse — plata congelada en la
    vitrina, y la base de cualquier decisión de descuento o remate.
    """

    as_of: date
    #: El umbral se aplica con `>=`: un producto con EXACTAMENTE
    #: `threshold_days` días ya aparece — es el que acaba de cruzar la raya y
    #: el que más sirve ver a tiempo. El rótulo de la UI debe decir "N días o
    #: más", no "más de N días" (F21-29).
    threshold_days: int
    #: Del UNIVERSO COMPLETO, no de `items`: cuántos productos superan el
    #: umbral en toda la empresa, aunque `limit` recorte la lista (F21-25).
    product_count: int
    #: Ídem: el costo detenido TOTAL, no el de la página.
    total_cost_value: MoneyOut
    #: Ranking de los más dormidos primero, topado por `limit`. NO es el
    #: inventario completo: para eso están los dos totales de arriba.
    items: list[StaleItemOut]


class IncomeStatementOut(BaseModel):
    """Estado de resultados del período: **¿cuánto ganó el negocio?**

    Es la vista de arriba que faltaba. `/profit` cubre la tienda y
    `/pawn-performance` el empeño —correctamente separados, porque se miden
    distinto— pero nadie los sumaba en un solo resultado.

    Y arregla un número que estaba MAL: la "utilidad operativa" de `/reportes`
    calculaba `ingresos − gastos` y **nunca restaba el costo de ventas**, así
    que una cadena vendida en 500.000 que costó 300.000 contaba como 500.000
    de utilidad. Para una tienda eso sobreestima la ganancia por todo el costo
    de la mercancía.

    Sale de los DOCUMENTOS (`sale`, `contract_payment`, `expense`, y desde la
    fase 7 `inventory_exit` y `account_settlement`) y no de los movimientos de
    caja — con dos excepciones nombradas: los ajustes de arqueo, que no tienen
    otro documento, y las liquidaciones anteriores a 00061. Dos razones, y las
    dos importan:

      · El desglose de caja solo cubre sesiones CERRADAS: lo de hoy faltaría.
      · Una venta con Sistecrédito ES ingreso aunque no haya entrado plata —
        el ingreso se reconoce al vender, no al cobrar. Armado desde caja, ese
        ingreso aparecería tarde o no aparecería.
    """

    from_date: date
    to_date: date

    #: --- Ingresos ---
    #: Ventas netas de descuento (tienda), BRUTAS de devoluciones: las
    #: devoluciones bajan en su propia línea, `sales_returns`.
    sales_revenue: MoneyOut
    #: Devoluciones en ventas del período — CONTRA-INGRESO, con su propia
    #: línea en el estado de resultados y no restado en silencio de «Ventas».
    #: Un número que baja sin explicación es lo que hace que nadie confíe en
    #: el reporte; y una devolución es un hecho del negocio que merece verse.
    #: Cae en el período de la DEVOLUCIÓN (`sale_return.return_date`).
    sales_returns: MoneyOut
    #: Intereses efectivamente cobrados (empeño). El empeño no tiene costo de
    #: ventas: su rentabilidad son los intereses sobre el capital prestado.
    interest_revenue: MoneyOut
    #: `sales_revenue − sales_returns + interest_revenue`.
    total_revenue: MoneyOut

    #: --- Costo de ventas ---
    #: Costo congelado de la mercancía vendida, NETO del costo de lo devuelto.
    #: Solo tienda. Que lo devuelto vuelva a contar como inventario disponible
    #: es correcto una vez que su costo sale de acá: era el mismo activo
    #: contado dos veces, y se cierra por este lado (F21-12).
    cost_of_goods_sold: MoneyOut
    #: `total_revenue − cost_of_goods_sold`.
    gross_profit: MoneyOut

    #: --- Gastos ---
    operating_expenses: MoneyOut
    expense_count: int
    #: «Mermas y bajas» (F7-01): mercancía que salió del inventario sin
    #: venderse —egresos `loss`, `damage`, `adjustment`, `internal_use`—, al
    #: costo del lote (sin el interés capitalizado de un remate), en la fecha
    #: del egreso. Una devolución al proveedor no es pérdida y no cuenta.
    inventory_shrinkage: MoneyOut = Decimal("0.00")
    shrinkage_exit_count: int = 0
    #: «Comisiones de convenios» (F7-02): `liquidado − recibido` de cada
    #: liquidación de una cuenta `settlement`, en la fecha de la liquidación.
    settlement_commissions: MoneyOut = Decimal("0.00")
    #: «Descuadres de caja» (F7-03): los ajustes del conteo de apertura, del
    #: arqueo de cierre y de la reversa al reabrir. CON SIGNO: un sobrante es
    #: positivo y suma; un faltante es negativo y resta.
    cash_differences: MoneyOut = Decimal("0.00")

    #: --- Resultado ---
    #: `gross_profit − operating_expenses − inventory_shrinkage −
    #: settlement_commissions + cash_differences`. ESTE es "cuánto ganó el
    #: negocio".
    operating_profit: MoneyOut
    #: Sobre el ingreso total, en %. `null` si no hubo ingresos — mostrar 0%
    #: cuando el dato correcto es "no aplica" es peor que no mostrar nada.
    margin_pct: Decimal | None

    #: --- Contexto que NO es resultado, y por eso va aparte ---
    #: Descuentos de interés otorgados: interés que se dejó de cobrar. Erosiona
    #: el resultado del empeño pero no es un gasto.
    interest_discounts: MoneyOut
    #: Descuentos de venta TOTALES (F7-08): cabecera + venta bajo el precio
    #: publicado. Ya están restados de `sales_revenue`; informativo.
    sales_discounts: MoneyOut = Decimal("0.00")
    #: Interés del remate realizado al vender la pieza (F7-04), neto de
    #: devoluciones. Ya está dentro de `gross_profit` porque
    #: `cost_of_goods_sold` usa el capital como base de costo; informativo.
    #: El interés que el contrato adeudaba al rematar se reconoce acá, cuando
    #: la pieza se vende — no al rematar.
    auction_interest_realized: MoneyOut = Decimal("0.00")
    #: Capital prestado y recuperado en el período. NO son gasto ni ingreso —
    #: es cartera moviéndose. Van acá para que nadie tenga que buscarlos en
    #: otra pantalla y concluir que faltan.
    capital_disbursed: MoneyOut
    capital_recovered: MoneyOut
    #: Mercancía comprada en el período. Tampoco es gasto: es efectivo que se
    #: convirtió en inventario. Se vuelve gasto cuando se VENDE, y ahí ya está
    #: contado en `cost_of_goods_sold`.
    inventory_purchased: MoneyOut


class MonthlySeriesPointOut(BaseModel):
    """Un mes de la serie histórica. `month` es el PRIMER día del mes, en la
    zona horaria de la empresa.
    """

    month: date
    #: Intereses cobrados (`contract_payment`) — el ingreso del empeño.
    interest_revenue: MoneyOut
    #: Ventas netas de descuento, solo `completed` — el ingreso de la tienda.
    #: BRUTAS de devoluciones, igual que en `/reports/income-statement`: el
    #: mismo nombre significa lo mismo en los dos endpoints.
    sales_revenue: MoneyOut
    #: Devoluciones del mes (contra-ingreso, neto de descuento prorrateado).
    #: Van por su cuenta para que la serie pueda pintarse neta sin que el
    #: significado de `sales_revenue` cambie entre endpoints.
    sales_returns: MoneyOut
    #: Gastos operativos (`expense`). NO incluye compras de mercancía ni
    #: capital desembolsado: ninguno de los dos es gasto.
    expenses: MoneyOut


class MonthlySeriesOut(BaseModel):
    """Serie mensual para la gráfica de tendencia del dashboard/reportes.

    Incluye los meses sin actividad en cero — un mes faltante haría que la
    gráfica uniera dos meses no consecutivos con una recta y mostrara una
    tendencia que nunca existió.
    """

    months: int
    points: list[MonthlySeriesPointOut]
