from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.money import Money

EntryOriginType = Literal["purchase", "other"]
ExitType = Literal["adjustment", "damage", "supplier_return", "internal_use"]
PaymentMethod = Literal["cash", "transfer", "other"]


class ItemOut(BaseModel):
    id: UUID
    code: str | None
    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None
    origin: str
    supplier_id: UUID | None
    source_contract_id: UUID | None
    cost: Decimal
    sale_price: Decimal | None
    quantity: int
    status: str
    photos: list[str]
    entry_date: date
    #: Producto al que pertenece este lote (00021). Es lo que permite agrupar
    #: en la lista: dos lotes del mismo producto comparten este id.
    product_id: UUID | None
    #: Consecutivo del lote DENTRO del producto (1, 2, 3…).
    lot_number: int | None
    created_at: datetime


class ItemUpdateIn(BaseModel):
    """Solo FOTOS. Desde 00022 el nombre, la descripción, la categoría y el
    precio pertenecen al producto y se editan con `PATCH /products/{id}`,
    donde el cambio aplica a todos sus lotes — que es el comportamiento
    correcto: dos lotes del mismo producto no pueden llamarse distinto ni
    costar distinto al cliente.

    Las fotos sí son del lote: una pieza de remate tiene las suyas, y un lote
    puede fotografiarse aparte.
    """

    photos: list[str] | None = None


class ItemPublishIn(BaseModel):
    sale_price: Money


class EntryLineIn(BaseModel):
    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None = None
    unit_cost: Money
    quantity: int = Field(default=1, ge=1)
    photos: list[str] = Field(default_factory=list)


class EntryCreateIn(BaseModel):
    origin_type: EntryOriginType
    supplier_id: UUID | None = None
    supplier_invoice: str | None = None
    notes: str | None = None
    # Solo para compras. Si viene, la compra se paga EN EL ACTO: exige caja
    # abierta y genera el egreso. Si se omite, la compra queda PENDIENTE de
    # pago —no toca caja, no exige sesión— y se salda después con
    # `POST /inventory/entries/{id}/pay`.
    #
    # Ese es el camino para cargar facturas de días anteriores o de noche con
    # la caja cerrada: el movimiento de caja no puede insertarse en una sesión
    # ya cerrada (es inmutable), así que se registra cuando efectivamente se
    # paga.
    payment_method: PaymentMethod | None = None
    #: Cuándo ENTRÓ la mercancía (no cuándo se digitó). Por defecto hoy; puede
    #: ser pasada, nunca futura.
    entry_date: date | None = None
    lines: list[EntryLineIn] = Field(min_length=1)


class EntryOut(BaseModel):
    id: UUID
    number: int
    origin_type: str
    supplier_id: UUID | None
    supplier_invoice: str | None
    contract_id: UUID | None
    total_cost: Decimal
    notes: str | None
    payment_method: str | None
    entry_date: date
    #: `None` mientras la compra esté pendiente de pago.
    paid_at: datetime | None
    created_at: datetime
    items: list[ItemOut]


class EntryPayIn(BaseModel):
    payment_method: PaymentMethod


class ExitLineIn(BaseModel):
    item_id: UUID
    quantity: int = Field(ge=1)


class ExitCreateIn(BaseModel):
    exit_type: ExitType
    reason: str
    lines: list[ExitLineIn] = Field(min_length=1)


class ExitOut(BaseModel):
    id: UUID
    number: int
    exit_type: str
    reason: str
    created_at: datetime


class ProductOut(BaseModel):
    """Un producto con el resumen de sus lotes — la vista agrupada del
    inventario. El PRECIO vive acá (aplica a todos los lotes); el COSTO no
    sube nunca a este nivel: cada lote conserva el suyo (identificación
    específica, NIIF) y por eso acá solo se expone el RANGO, como lectura
    informativa y jamás como valor de costeo.
    """

    id: UUID
    code: str | None
    name: str
    cat1_id: UUID
    cat2_id: UUID
    cat3_id: UUID
    description: str | None
    sale_price: Decimal | None
    is_unique: bool
    active: bool
    #: Lotes vivos (sin contar los dados de baja).
    lot_count: int
    #: Unidades listas para vender — el número que busca el vendedor.
    available_quantity: int
    #: Rango de costos entre lotes. Una dispersión grande es señal de que el
    #: precio de compra se movió: vale la pena revisar el precio de venta.
    min_cost: Decimal | None
    max_cost: Decimal | None
    created_at: datetime


class ProductUpdateIn(BaseModel):
    """Editar el producto afecta a TODOS sus lotes a la vez — ese es el punto.
    El costo no está acá y nunca lo estará: pertenece al lote.
    """

    name: str | None = None
    description: str | None = None
    sale_price: Money | None = None
    active: bool | None = None
