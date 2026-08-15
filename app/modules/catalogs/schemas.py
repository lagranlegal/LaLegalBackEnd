from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AppliesTo = Literal["pawn", "store", "both"]
DocType = Literal["cc", "ce", "passport", "nit"]


class CategoryCreateIn(BaseModel):
    parent_id: UUID | None = None
    name: str
    code_letter: str = Field(min_length=1, max_length=3)
    applies_to: AppliesTo = "both"
    default_term_months: int | None = None
    arrears_window_months: int | None = None
    max_ltv_pct: Decimal | None = None


class CategoryUpdateIn(BaseModel):
    name: str | None = None
    code_letter: str | None = Field(default=None, min_length=1, max_length=3)
    applies_to: AppliesTo | None = None
    default_term_months: int | None = None
    arrears_window_months: int | None = None
    max_ltv_pct: Decimal | None = None
    active: bool | None = None


class CategoryOut(BaseModel):
    id: UUID
    parent_id: UUID | None
    level: int
    name: str
    code_letter: str
    applies_to: str
    default_term_months: int | None
    arrears_window_months: int | None
    max_ltv_pct: Decimal | None
    active: bool


class SupplierCreateIn(BaseModel):
    name: str
    doc_type: DocType | None = None
    doc_number: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    code_letter: str = Field(min_length=1, max_length=3)
    notes: str | None = None


class SupplierUpdateIn(BaseModel):
    name: str | None = None
    doc_type: DocType | None = None
    doc_number: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    code_letter: str | None = Field(default=None, min_length=1, max_length=3)
    notes: str | None = None
    active: bool | None = None


class SupplierOut(BaseModel):
    id: UUID
    name: str
    doc_type: str | None
    doc_number: str | None
    phone: str | None
    email: str | None
    address: str | None
    code_letter: str
    notes: str | None
    active: bool
