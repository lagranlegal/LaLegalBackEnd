from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.customers import service
from app.modules.customers.schemas import CustomerCreateIn, CustomerOut, CustomerUpdateIn

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])

_view = require_permission("customers.view")
_create = require_permission("customers.create")


@router.get("", response_model=CursorPage[CustomerOut])
async def list_customers(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    q: str | None = Query(default=None, description="Búsqueda por nombre o número de documento"),
) -> CursorPage[CustomerOut]:
    return await service.list_customers(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        q=q,
    )


@router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(
    body: CustomerCreateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CustomerOut:
    return await service.create_customer(
        db, company_id=user.company_id, body=body, created_by=user.id
    )


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(
    customer_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CustomerOut:
    return await service.get_customer(db, company_id=user.company_id, customer_id=customer_id)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def update_customer(
    customer_id: UUID,
    body: CustomerUpdateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CustomerOut:
    return await service.update_customer(
        db, company_id=user.company_id, customer_id=customer_id, body=body
    )
