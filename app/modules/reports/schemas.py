from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ContractKpisOut(BaseModel):
    active_count: int
    in_arrears_count: int
    in_extension_count: int
    ready_for_auction_count: int
    auctioned_count: int
    capital_outstanding: Decimal


class SalesKpisOut(BaseModel):
    today_total: Decimal
    today_count: int
    month_total: Decimal


class InventoryKpisOut(BaseModel):
    available_count: int
    available_value: Decimal
    draft_count: int


class CashboxKpisOut(BaseModel):
    session_open: bool
    session_id: UUID | None
    opened_at: datetime | None
    opening_balance: Decimal | None


class DashboardOut(BaseModel):
    as_of: date
    contracts: ContractKpisOut
    sales: SalesKpisOut
    inventory: InventoryKpisOut
    cashbox: CashboxKpisOut


class ClosingHistoryOut(BaseModel):
    session_id: UUID
    session_date: date
    opening_balance: Decimal
    expected_cash: Decimal
    counted_cash: Decimal
    difference: Decimal
    difference_reason: str | None
    closed_by: UUID
    closed_at: datetime
