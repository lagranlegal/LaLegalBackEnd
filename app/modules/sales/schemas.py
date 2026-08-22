from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.money import Money

PaymentMethod = Literal["cash", "transfer", "other"]


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


class VoidSaleIn(BaseModel):
    reason: str
