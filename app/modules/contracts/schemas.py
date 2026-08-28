from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.money import Money

PaymentMethod = Literal["cash", "transfer", "other"]


class ContractItemIn(BaseModel):
    category_id: UUID
    description: str
    weight_grams: Decimal | None = None
    serial_imei: str | None = None
    item_appraisal: Money | None = None
    photos: list[str] = Field(default_factory=list)


class ContractItemOut(BaseModel):
    id: UUID
    category_id: UUID
    description: str
    weight_grams: Decimal | None
    serial_imei: str | None
    item_appraisal: Decimal | None
    status: str
    photos: list[str]
    inventory_item_id: UUID | None


class ContractCreateIn(BaseModel):
    #: Cuenta de la que sale el desembolso. Si se omite, la predeterminada del
    #: medio de pago.
    account_id: UUID | None = None
    customer_id: UUID
    principal: Money
    interest_rate_pct: Decimal = Field(gt=0, le=100)
    appraisal_value: Money | None = None
    items: list[ContractItemIn] = Field(min_length=1)
    payment_method: PaymentMethod
    extension_months: int = Field(default=1, ge=1)
    legacy_code: str | None = None
    notes: str | None = None


class ContractImportIn(BaseModel):
    """docs/MIGRACION_CONTRATOS.md: importa la foto financiera al corte de
    un contrato del sistema anterior. A diferencia de `ContractCreateIn`,
    `term_months`/`arrears_window_months`/`extension_months` NO salen de la
    categoría: son el snapshot real del contrato viejo, y `capital_balance`
    puede ya ser menor que `principal` (abonos hechos antes del import).
    Los límites de negocio (>0, alineación de fechas, etc.) se validan en el
    servicio -no acá- para poder devolver los códigos de error específicos
    del import (`IMPORT_*`) en vez del genérico `VALIDATION_ERROR`.
    """

    legacy_code: str
    customer_id: UUID
    principal: Money
    capital_balance: Decimal = Field(max_digits=14, decimal_places=2)
    interest_rate_pct: Decimal = Field(gt=0, le=100)
    term_months: int
    arrears_window_months: int
    extension_months: int = 1
    start_date: date
    interest_paid_until: date
    items: list[ContractItemIn]
    appraisal_value: Money | None = None
    signed_photo_url: str | None = None
    notes: str | None = None


class ContractUpdateIn(BaseModel):
    appraisal_value: Money | None = None
    notes: str | None = None
    signed_photo_url: str | None = None


class ContractOut(BaseModel):
    id: UUID
    number: int
    legacy_code: str | None
    customer_id: UUID
    principal: Decimal
    capital_balance: Decimal
    appraisal_value: Decimal | None
    interest_rate_pct: Decimal
    term_months: int
    arrears_window_months: int
    extension_months: int
    start_date: date
    due_date: date
    interest_paid_until: date
    status: str
    extension_ends_at: date | None
    ltv_warning: bool
    notes: str | None
    signed_photo_url: str | None
    created_at: datetime
    items: list[ContractItemOut]


class PaymentOptionOut(BaseModel):
    months: int
    interest_amount: Decimal
    total: Decimal
    allows_capital: bool


class PaymentQuoteOut(BaseModel):
    months_owed: int
    monthly_interest: Decimal
    options: list[PaymentOptionOut]


class PaymentCreateIn(BaseModel):
    #: Cuenta donde entra el abono. Si se omite, la predeterminada del medio
    #: de pago.
    account_id: UUID | None = None
    months_covered: int = Field(ge=0)
    capital_amount: Money | None = None
    payment_method: PaymentMethod
    discount_amount: Money | None = None
    discount_reason: str | None = None


class PaymentOut(BaseModel):
    id: UUID
    receipt_number: int
    paid_at: datetime
    months_covered: int
    interest_amount: Decimal
    capital_amount: Decimal
    discount_amount: Decimal
    discount_reason: str | None
    payment_method: str
    total: Decimal
    new_capital_balance: Decimal
    new_interest_paid_until: date
    created_at: datetime


class SettlementInfoOut(BaseModel):
    """Para el documento de paz y salvo — `settled_at` se deriva del abono
    que saldó el contrato (`new_capital_balance=0`), nunca una columna
    guardada aparte."""

    settled_at: datetime
    receipt_number: int
