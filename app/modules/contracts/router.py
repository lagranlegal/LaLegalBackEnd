from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.contracts import service
from app.modules.contracts.schemas import (
    ContractCreateIn,
    ContractOut,
    ContractUpdateIn,
    PaymentCreateIn,
    PaymentOut,
    PaymentQuoteOut,
)

router = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])

_view = require_permission("contracts.view")
_create = require_permission("contracts.create")
_edit = require_permission("contracts.edit")
_pay = require_permission("payments.create")
_auction = require_permission("contracts.auction")


@router.get("/ready-for-auction", response_model=list[ContractOut])
async def list_ready_for_auction(
    user: Annotated[CurrentUser, Depends(_auction)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[ContractOut]:
    return await service.list_ready_for_auction(db, company_id=user.company_id)


@router.post("", response_model=ContractOut, status_code=201)
async def create_contract(
    body: ContractCreateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ContractOut:
    return await service.create_contract(
        db, company_id=user.company_id, body=body, created_by=user.id
    )


@router.get("", response_model=CursorPage[ContractOut])
async def list_contracts(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
) -> CursorPage[ContractOut]:
    return await service.list_contracts(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        status_filter=status,
    )


@router.get("/{contract_id}", response_model=ContractOut)
async def get_contract(
    contract_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ContractOut:
    return await service.get_contract(db, company_id=user.company_id, contract_id=contract_id)


@router.patch("/{contract_id}", response_model=ContractOut)
async def update_contract(
    contract_id: UUID,
    body: ContractUpdateIn,
    user: Annotated[CurrentUser, Depends(_edit)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ContractOut:
    return await service.update_contract(
        db, company_id=user.company_id, contract_id=contract_id, body=body
    )


@router.get("/{contract_id}/payment-options", response_model=PaymentQuoteOut)
async def get_payment_options(
    contract_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> PaymentQuoteOut:
    return await service.get_payment_quote(db, company_id=user.company_id, contract_id=contract_id)


@router.post("/{contract_id}/payments", response_model=PaymentOut, status_code=201)
async def create_payment(
    contract_id: UUID,
    body: PaymentCreateIn,
    user: Annotated[CurrentUser, Depends(_pay)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> PaymentOut:
    return await service.create_payment(
        db,
        company_id=user.company_id,
        contract_id=contract_id,
        body=body,
        user=user,
        idempotency_key=idempotency_key,
    )


@router.get("/{contract_id}/payments", response_model=CursorPage[PaymentOut])
async def list_payments(
    contract_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[PaymentOut]:
    return await service.list_payments(
        db,
        company_id=user.company_id,
        contract_id=contract_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.post("/{contract_id}/auction", response_model=ContractOut)
async def auction_contract(
    contract_id: UUID,
    user: Annotated[CurrentUser, Depends(_auction)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ContractOut:
    return await service.auction_contract(
        db, company_id=user.company_id, contract_id=contract_id, actor_id=user.id
    )
