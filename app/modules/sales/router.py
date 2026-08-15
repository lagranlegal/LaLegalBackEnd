from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.sales import service
from app.modules.sales.schemas import SaleCreateIn, SaleOut, VoidSaleIn

router = APIRouter(prefix="/api/v1/sales", tags=["sales"])

_create = require_permission("sales.create")
_void = require_permission("sales.void")


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
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[SaleOut]:
    return await service.list_sales(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.get("/{sale_id}", response_model=SaleOut)
async def get_sale(
    sale_id: UUID,
    user: Annotated[CurrentUser, Depends(_create)],
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
