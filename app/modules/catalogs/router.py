from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_current_user, get_tenant_db, require_permission
from app.modules.catalogs import service
from app.modules.catalogs.schemas import (
    CategoryCreateIn,
    CategoryOut,
    CategoryUpdateIn,
    SupplierCreateIn,
    SupplierOut,
    SupplierUpdateIn,
)

router = APIRouter(prefix="/api/v1/catalogs", tags=["catalogs"])

_manage = require_permission("catalogs.manage")

# Lectura de categorías/proveedores: cualquier usuario autenticado y activo de
# la empresa (no requiere catalogs.manage) — son datos de referencia que
# necesitan contracts/inventory/sales para operar, no solo quien administra
# el catálogo. Ver docs/API_GUIDE.md.


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[CategoryOut]:
    return await service.list_categories(db, company_id=user.company_id)


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(
    body: CategoryCreateIn,
    user: Annotated[CurrentUser, Depends(_manage)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CategoryOut:
    return await service.create_category(db, company_id=user.company_id, body=body)


@router.get("/categories/{category_id}", response_model=CategoryOut)
async def get_category(
    category_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CategoryOut:
    return await service.get_category(db, company_id=user.company_id, category_id=category_id)


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: UUID,
    body: CategoryUpdateIn,
    user: Annotated[CurrentUser, Depends(_manage)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> CategoryOut:
    return await service.update_category(
        db, company_id=user.company_id, category_id=category_id, body=body
    )


@router.get("/suppliers", response_model=CursorPage[SupplierOut])
async def list_suppliers(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[SupplierOut]:
    return await service.list_suppliers(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.post("/suppliers", response_model=SupplierOut, status_code=201)
async def create_supplier(
    body: SupplierCreateIn,
    user: Annotated[CurrentUser, Depends(_manage)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SupplierOut:
    return await service.create_supplier(db, company_id=user.company_id, body=body)


@router.get("/suppliers/{supplier_id}", response_model=SupplierOut)
async def get_supplier(
    supplier_id: UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SupplierOut:
    return await service.get_supplier(db, company_id=user.company_id, supplier_id=supplier_id)


@router.patch("/suppliers/{supplier_id}", response_model=SupplierOut)
async def update_supplier(
    supplier_id: UUID,
    body: SupplierUpdateIn,
    user: Annotated[CurrentUser, Depends(_manage)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SupplierOut:
    return await service.update_supplier(
        db, company_id=user.company_id, supplier_id=supplier_id, body=body
    )
