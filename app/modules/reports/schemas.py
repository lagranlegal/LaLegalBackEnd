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
