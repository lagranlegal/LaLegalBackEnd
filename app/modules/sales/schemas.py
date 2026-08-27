from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.money import Money

PaymentMethod = Literal["cash", "transfer", "other"]
ReturnReason = Literal["defect", "change_of_mind", "other"]
ReturnSettlementMethod = Literal["cash", "credit_note"]


class SaleLineIn(BaseModel):
    item_id: UUID
    #: Decimal desde 00036: vender 12,5 g de oro o 3,25 m de cable. El
    #: servicio la valida contra la unidad del producto — si se mide en
    #: unidades, rechaza fracciones.
    quantity: Decimal = Field(gt=0)
    unit_price: Money


class SaleCreateIn(BaseModel):
    #: Cuenta donde entra el dinero. Si se omite, cae en la predeterminada del
    #: medio de pago. Elegir una cuenta `settlement` (Sistecrédito) registra la
    #: venta sin que entre plata: queda como pendiente de cobro, que es
    #: exactamente lo que ocurre en la realidad.
    account_id: UUID | None = None
    customer_id: UUID | None = None
    payment_method: PaymentMethod
    lines: list[SaleLineIn] = Field(min_length=1)
    discount_amount: Money | None = None
    discount_reason: str | None = None
    #: Nota crédito a aplicar. Exige `customer_id` (debe coincidir con el
    #: dueño de la nota — no es transferible entre clientes).
    credit_note_id: UUID | None = None
    #: Monto a redimir. Si se omite y hay `credit_note_id`, se toma
    #: min(saldo_de_la_nota, total) — cubre lo máximo posible sin exceder.
    credit_note_amount: Money | None = None


class SaleLineOut(BaseModel):
    id: UUID
    item_id: UUID
    quantity: Decimal
    unit_price: Decimal
    # Costo CONGELADO al vender, no leído del artículo al consultar: el costo
    # de una venta es un hecho histórico y un reporte de un período cerrado no
    # debe cambiar si alguien corrige el costo del artículo hoy.
    unit_cost: Decimal
    subtotal: Decimal


class SaleOut(BaseModel):
    id: UUID
    number: int
    sold_at: datetime
    customer_id: UUID | None
    discount_amount: Decimal
    total: Decimal
    payment_method: str
    status: str
    void_reason: str | None
    created_at: datetime
    lines: list[SaleLineOut]
    account_id: UUID | None
    #: Cuánto de esta venta se pagó redimiendo una nota crédito. `None` si no
    #: se usó ninguna — distinto de `0`, que significaría que se usó una nota
    #: pero por algún motivo cubrió cero (no debería pasar, pero la
    #: distinción evita ambigüedad en el comprobante).
    credit_note_redeemed_amount: Decimal | None = None


class VoidSaleIn(BaseModel):
    reason: str


class SaleReturnLineIn(BaseModel):
    sale_line_id: UUID
    quantity: Decimal = Field(gt=0)
    #: Si la mercancía vuelve a inventario. `False` es una devolución
    #: puramente financiera: la pieza no regresa (se perdió, se dañó más
    #: allá de uso, o el negocio decide no reingresarla), pero el cliente
    #: igual recibe su plata o su nota crédito.
    restock: bool = True


class SaleReturnCreateIn(BaseModel):
    lines: list[SaleReturnLineIn] = Field(min_length=1)
    reason: ReturnReason
    settlement_method: ReturnSettlementMethod
    #: Requerido si `settlement_method='credit_note'` y la venta original no
    #: tenía cliente (venta de mostrador). Si la venta sí tenía cliente, se
    #: hereda y no hace falta repetirlo.
    customer_id: UUID | None = None
    notes: str | None = None


class SaleReturnLineOut(BaseModel):
    id: UUID
    sale_line_id: UUID
    #: El lote que recibió la cantidad devuelta — el mismo reabierto o uno
    #: nuevo. `None` si `restock=False`.
    item_id: UUID | None
    quantity: Decimal
    unit_cost: Decimal
    restock: bool


class SaleReturnOut(BaseModel):
    id: UUID
    number: int
    sale_id: UUID
    customer_id: UUID | None
    reason: str
    settlement_method: str
    notes: str | None
    return_date: date
    created_at: datetime
    lines: list[SaleReturnLineOut]
    credit_note_id: UUID | None
    #: Derivado de las líneas × el precio de la venta original — nunca
    #: guardado (mismo principio que el saldo de una nota crédito).
    total_amount: Decimal
    #: Se registró pasado el `return_window_days` de la empresa —
    #: informativo, no cambia nada del resultado (advierte, no bloquea).
    time_limit_warning: bool


class CreditNoteOut(BaseModel):
    id: UUID
    number: int
    customer_id: UUID
    sale_return_id: UUID
    amount: Decimal
    #: Ambos DERIVADOS de `credit_note_redemption`, nunca columnas guardadas
    #: — mismo principio que cuentas por pagar a proveedor.
    redeemed_amount: Decimal
    balance: Decimal
    notes: str | None
    created_at: datetime
