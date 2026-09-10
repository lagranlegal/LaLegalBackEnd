from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.common.money import Money

PaymentMethod = Literal["cash", "transfer", "other"]
CashModule = Literal["pawn", "store", "general"]


class SessionOpenIn(BaseModel):
    """Abrir un turno ya NO declara cuánta plata hay (00048).

    El saldo del cajón se deriva de sus movimientos y se sabe solo, así que
    no hay nada que digitar: abrir dice "desde ahora respondo yo".

    Lo que sí se puede hacer —y conviene— es CONTAR. `counted_cash` es ese
    conteo de apertura: si no coincide con lo que el sistema cree que hay,
    la diferencia se registra como un ajuste con motivo, exactamente igual
    que el descuadre de cierre. Ese es el punto: el faltante queda atribuido
    al turno donde apareció y no al siguiente.
    """

    counted_cash: Money | None = None
    difference_reason: str | None = None

    #: DEPRECADO. Era el saldo de apertura escrito a mano, y hasta 00048 fue
    #: el único número de toda la aplicación que aparecía sin documento. Se
    #: sigue aceptando —un bundle viejo del front lo manda y quedarse sin
    #: poder abrir la caja es peor que cualquier otra cosa— y se interpreta
    #: como lo que siempre fue en la práctica: un conteo del cajón. Se
    #: elimina cuando el front desplegado use `counted_cash`.
    opening_balance: Money | None = None


class SessionCloseIn(BaseModel):
    counted_cash: Money
    difference_reason: str | None = None


class SessionReopenIn(BaseModel):
    reason: str


class SessionOut(BaseModel):
    id: UUID
    register_id: UUID
    session_date: date
    opened_by: UUID
    opened_at: datetime
    opening_balance: Decimal
    expected_cash: Decimal | None
    counted_cash: Decimal | None
    difference: Decimal | None
    difference_reason: str | None
    closed_by: UUID | None
    closed_at: datetime | None
    status: str


class BreakdownLineOut(BaseModel):
    module: str
    direction: str
    concept: str
    # Opcional desde 00027: una liquidación mueve plata entre cuentas sin
    # cobrarse por ningún medio — solo cambia de contenedor.
    payment_method: str | None
    account_id: UUID
    account_name: str
    account_type: str
    total: Decimal


class SessionReportOut(BaseModel):
    session_id: UUID
    status: str
    opening_balance: Decimal
    expected_cash: Decimal
    lines: list[BreakdownLineOut]


class ExpenseCategoryCreateIn(BaseModel):
    name: str


class ExpenseCategoryOut(BaseModel):
    id: UUID
    name: str
    active: bool


class ExpenseCreateIn(BaseModel):
    #: Cuenta de la que sale el gasto. Si se omite, la predeterminada del
    #: medio de pago.
    account_id: UUID | None = None
    category_id: UUID
    description: str
    amount: Money
    payment_method: PaymentMethod
    module: CashModule = "general"
    receipt_url: str | None = None


class ExpenseOut(BaseModel):
    id: UUID
    session_id: UUID
    module: str
    category_id: UUID
    description: str
    amount: Decimal
    payment_method: str
    receipt_url: str | None
    created_at: datetime
