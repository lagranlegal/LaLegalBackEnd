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
    created_at: datetime


class ItemUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    sale_price: Money | None = None
    photos: list[str] | None = None
    # Solo mientras status='draft' (mismo gate que el resto de este schema).
    # Si se manda alguno de los tres, hay que mandar los tres juntos — ver
    # inventory.service.update_item.
    cat1_id: UUID | None = None
    cat2_id: UUID | None = None
    cat3_id: UUID | None = None


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
    # Obligatorio cuando origin_type='purchase' (lo valida el servicio): una
    # compra entrega plata al proveedor, y el medio es lo que decide si baja
    # el efectivo esperado del cierre o se concilia por otro medio.
    payment_method: PaymentMethod | None = None
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
    created_at: datetime
    items: list[ItemOut]


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
