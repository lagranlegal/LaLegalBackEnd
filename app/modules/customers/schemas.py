from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

DocType = Literal["cc", "ce", "passport", "nit"]


class CustomerCreateIn(BaseModel):
    full_name: str
    doc_type: DocType
    doc_number: str
    doc_issue_place: str | None = None
    address: str | None = None
    phone: str
    email: str | None = None
    doc_photo_url: str | None = None
    notes: str | None = None


class CustomerUpdateIn(BaseModel):
    full_name: str | None = None
    doc_issue_place: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    doc_photo_url: str | None = None
    notes: str | None = None


class CustomerOut(BaseModel):
    id: UUID
    full_name: str
    doc_type: str
    doc_number: str
    doc_issue_place: str | None
    address: str | None
    phone: str
    email: str | None
    doc_photo_url: str | None
    status: str
    alert_reason: str | None
    notes: str | None
    created_at: datetime
