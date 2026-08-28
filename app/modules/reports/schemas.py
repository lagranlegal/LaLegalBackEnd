from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ContractKpisOut(BaseModel):
    active_count: int
    in_arrears_count: int
    in_extension_count: int
    ready_for_auction_count: int
    auctioned_count: int
    capital_outstanding: Decimal


class SalesKpisOut(BaseModel):
    today_total: Decimal
    today_count: int
    month_total: Decimal


class InventoryKpisOut(BaseModel):
    available_count: int
    available_value: Decimal
    draft_count: int


class CashboxKpisOut(BaseModel):
    session_open: bool
    session_id: UUID | None
    opened_at: datetime | None
    opening_balance: Decimal | None


class DashboardOut(BaseModel):
    as_of: date
    contracts: ContractKpisOut
    sales: SalesKpisOut
    inventory: InventoryKpisOut
    cashbox: CashboxKpisOut


class ClosingHistoryOut(BaseModel):
    session_id: UUID
    session_date: date
    opening_balance: Decimal
    expected_cash: Decimal
    counted_cash: Decimal
    difference: Decimal
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
    total: Decimal


class ClosingsBreakdownOut(BaseModel):
    lines: list[ClosingsBreakdownLineOut]


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
    units_sold: int
    #: Suma de los subtotales de las líneas, antes de descuentos.
    gross_revenue: Decimal
    #: Descuentos aplicados a nivel de venta — menor ingreso, no un gasto.
    discounts: Decimal
    #: `gross_revenue - discounts`: lo que realmente entró por ventas.
    net_revenue: Decimal
    #: Costo congelado de lo vendido (`sale_line.unit_cost * quantity`).
    cost_of_goods_sold: Decimal
    #: `net_revenue - cost_of_goods_sold`.
    gross_profit: Decimal
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
    interest_collected: Decimal
    #: Descuentos de interés otorgados (permiso especial). Erosionan el
    #: rendimiento: son interés que se dejó de cobrar.
    interest_discounts: Decimal
    #: Capital recuperado vía abonos — reduce cartera, NO es ingreso.
    capital_recovered: Decimal
    #: Capital entregado en contratos nuevos del rango — NO es gasto.
    capital_disbursed: Decimal
    payment_count: int
    contracts_opened: int
    #: Cartera al corte de HOY, no del final del rango: el esquema no guarda
    #: `closed_at` ni histórico de saldos, así que no hay forma exacta de
    #: saber cuánta cartera había en una fecha pasada.
    capital_outstanding: Decimal
    open_contracts: int
    #: `interest_collected / capital_outstanding * 100` — rendimiento del
    #: período sobre la cartera ACTUAL. `null` si no hay cartera abierta.
    #: Es una referencia útil cuando el rango termina hoy (el caso normal);
    #: para rangos históricos la cartera de referencia ya no es la de entonces.
    yield_on_current_portfolio_pct: Decimal | None


class SupplierPayableOut(BaseModel):
    """Lo que se le debe a UN proveedor, con antigüedad.

    La antigüedad se mide desde `entry_date` (cuándo ENTRÓ la mercancía), no
    desde cuándo se digitó: es la fecha que le importa al proveedor y la que
    determina si una deuda está vencida.
    """

    supplier_id: UUID | None
    supplier_name: str
    entry_count: int
    total: Decimal
    #: Antigüedad por tramos — el corte estándar de una cartera por pagar.
    days_0_30: Decimal
    days_31_60: Decimal
    days_over_60: Decimal
    #: La compra pendiente MÁS ANTIGUA: la que más urge.
    oldest_entry_date: date | None


class PayablesOut(BaseModel):
    """Cuentas por pagar: "¿cuánto debo, a quién, y desde hace cuánto?".

    Es el primer reporte que pediría un contador y no existía, aunque cada
    compra ya sabía si estaba pagada: el dato estaba guardado y ninguna
    pantalla lo sumaba.
    """

    as_of: date
    total: Decimal
    entry_count: int
    days_0_30: Decimal
    days_31_60: Decimal
    days_over_60: Decimal
    by_supplier: list[SupplierPayableOut]


class InventoryValuationCategoryOut(BaseModel):
    cat1_id: UUID | None
    cat1_name: str
    units: int
    cost_value: Decimal
    retail_value: Decimal


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
    units: int
    lot_count: int
    #: Valor al costo. Este es EL número del inventario.
    cost_value: Decimal
    #: A precio de venta. Referencia, no valoración.
    retail_value: Decimal
    #: `retail_value - cost_value`: utilidad potencial, aún no realizada.
    potential_profit: Decimal
    by_category: list[InventoryValuationCategoryOut]


class StaleItemOut(BaseModel):
    product_id: UUID
    product_code: str | None
    product_name: str
    units: int
    cost_value: Decimal
    #: Días desde que entró el lote disponible más ANTIGUO de ese producto.
    days_in_stock: int


class StaleInventoryOut(BaseModel):
    """Mercancía disponible que lleva mucho sin moverse — plata congelada en la
    vitrina, y la base de cualquier decisión de descuento o remate.
    """

    as_of: date
    threshold_days: int
    product_count: int
    total_cost_value: Decimal
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

    Sale de los DOCUMENTOS (`sale`, `contract_payment`, `expense`) y no de los
    movimientos de caja. Dos razones, y las dos importan:

      · El desglose de caja solo cubre sesiones CERRADAS: lo de hoy faltaría.
      · Una venta con Sistecrédito ES ingreso aunque no haya entrado plata —
        el ingreso se reconoce al vender, no al cobrar. Armado desde caja, ese
        ingreso aparecería tarde o no aparecería.
    """

    from_date: date
    to_date: date

    #: --- Ingresos ---
    #: Ventas netas de descuento (tienda).
    sales_revenue: Decimal
    #: Intereses efectivamente cobrados (empeño). El empeño no tiene costo de
    #: ventas: su rentabilidad son los intereses sobre el capital prestado.
    interest_revenue: Decimal
    total_revenue: Decimal

    #: --- Costo de ventas ---
    #: Costo congelado de la mercancía vendida. Solo tienda.
    cost_of_goods_sold: Decimal
    #: `total_revenue − cost_of_goods_sold`.
    gross_profit: Decimal

    #: --- Gastos ---
    operating_expenses: Decimal
    expense_count: int

    #: --- Resultado ---
    #: `gross_profit − operating_expenses`. ESTE es "cuánto ganó el negocio".
    operating_profit: Decimal
    #: Sobre el ingreso total, en %. `null` si no hubo ingresos — mostrar 0%
    #: cuando el dato correcto es "no aplica" es peor que no mostrar nada.
    margin_pct: Decimal | None

    #: --- Contexto que NO es resultado, y por eso va aparte ---
    #: Descuentos de interés otorgados: interés que se dejó de cobrar. Erosiona
    #: el resultado del empeño pero no es un gasto.
    interest_discounts: Decimal
    #: Capital prestado y recuperado en el período. NO son gasto ni ingreso —
    #: es cartera moviéndose. Van acá para que nadie tenga que buscarlos en
    #: otra pantalla y concluir que faltan.
    capital_disbursed: Decimal
    capital_recovered: Decimal
    #: Mercancía comprada en el período. Tampoco es gasto: es efectivo que se
    #: convirtió en inventario. Se vuelve gasto cuando se VENDE, y ahí ya está
    #: contado en `cost_of_goods_sold`.
    inventory_purchased: Decimal
