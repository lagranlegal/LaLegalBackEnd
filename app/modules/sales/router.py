from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.sales import service
from app.modules.sales.schemas import (
    CreditNoteOut,
    SaleCreateIn,
    SaleOut,
    SaleReturnCreateIn,
    SaleReturnOut,
    VoidSaleIn,
)

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])
credit_notes_router = APIRouter(prefix="/api/v1/credit-notes", tags=["sales"])

_view = require_permission("sales.view")
_create = require_permission("sales.create")
_void = require_permission("sales.void")
_return = require_permission("sales.return")


@router.post("", response_model=SaleOut, status_code=201)
async def create_sale(
    body: SaleCreateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SaleOut:
    return await service.create_sale(
        db, company_id=user.company_id, body=body, user=user, idempotency_key=idempotency_key
    )


@router.get("", response_model=CursorPage[SaleOut])
async def list_sales(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    customer_id: Annotated[UUID | None, Query()] = None,
    status: str | None = Query(default=None),
) -> CursorPage[SaleOut]:
    return await service.list_sales(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        customer_id=customer_id,
        status_filter=status,
    )


@router.get("/{sale_id}", response_model=SaleOut)
async def get_sale(
    sale_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SaleOut:
    return await service.get_sale(db, company_id=user.company_id, sale_id=sale_id)


@router.post("/{sale_id}/void", response_model=SaleOut)
async def void_sale(
    sale_id: UUID,
    body: VoidSaleIn,
    user: Annotated[CurrentUser, Depends(_void)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SaleOut:
    return await service.void_sale(
        db, company_id=user.company_id, sale_id=sale_id, reason=body.reason, actor_id=user.id
    )


@router.post("/{sale_id}/returns", response_model=SaleReturnOut, status_code=201)
async def create_return(
    sale_id: UUID,
    body: SaleReturnCreateIn,
    user: Annotated[CurrentUser, Depends(_return)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> SaleReturnOut:
    return await service.create_return(
        db,
        company_id=user.company_id,
        sale_id=sale_id,
        body=body,
        user=user,
        idempotency_key=idempotency_key,
    )


@router.get("/{sale_id}/returns", response_model=list[SaleReturnOut])
async def list_returns(
    sale_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[SaleReturnOut]:
    return await service.list_returns_for_sale(db, company_id=user.company_id, sale_id=sale_id)


@router.get("/{sale_id}/returns/{return_id}", response_model=SaleReturnOut)
async def get_return(
    sale_id: UUID,
    return_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SaleReturnOut:
    return await service.get_return(db, company_id=user.company_id, return_id=return_id)


@credit_notes_router.get("", response_model=CursorPage[CreditNoteOut])
async def list_credit_notes(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    customer_id: Annotated[UUID | None, Query()] = None,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[CreditNoteOut]:
    return await service.list_credit_notes(
        db,
        company_id=user.company_id,
        customer_id=customer_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@credit_notes_router.get("/{credit_note_id}", response_model=CreditNoteOut)
async def get_credit_note(
    credit_note_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CreditNoteOut:
    return await service.get_credit_note(
        db, company_id=user.company_id, credit_note_id=credit_note_id
    )
