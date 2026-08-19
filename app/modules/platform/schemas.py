from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class CompanyCreateIn(BaseModel):
    name: str
    plan_code: str
    subscription_expires_at: date
    first_admin_email: EmailStr
    first_admin_full_name: str


class CompanyOut(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    plan_code: str | None
    plan_name: str | None
    subscription_expires_at: date | None


class SubscriptionExtendIn(BaseModel):
    new_expires_at: date
    notes: str | None = None


class SubscriptionOut(BaseModel):
    id: UUID
    company_id: UUID
    plan_id: UUID
    status: str
    expires_at: date


class PlanOut(BaseModel):
    id: UUID
    name: str
    code: str
    price: Decimal | None
    modules: dict[str, bool]
    active: bool
