from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.common.money import Money

PaymentMethod = Literal["cash", "transfer", "other"]
CashModule = Literal["pawn", "store", "general"]


class SessionOpenIn(BaseModel):
    opening_balance: Money


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
    payment_method: str
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
