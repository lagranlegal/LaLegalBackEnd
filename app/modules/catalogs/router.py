from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.catalogs import service
from app.modules.catalogs.schemas import (
    CategoryCreateIn,
    CategoryOut,
    CategoryUpdateIn,
    SupplierCreateIn,
    SupplierOut,
    SupplierPurchaseOut,
    SupplierSummaryOut,
    SupplierUpdateIn,
)

router = APIRouter(prefix="/api/v1/catalogs", tags=["catalogs"])

_manage = require_permission("catalogs.manage")
# Los cuatro GET no exigían permiso (`get_current_user` pelado), lo que viola
# la regla 3 de CLAUDE.md y hacía legible el catálogo para cualquier usuario
# autenticado. 00030 crea el permiso y se lo otorga a todos los roles
# existentes, así que esto no le quita el acceso a nadie hoy — lo que gana es
# que a partir de ahora se pueda quitar a conciencia.
_view = require_permission("catalogs.view")

# Lectura de categorías/proveedores: cualquier usuario autenticado y activo de
# la empresa (no requiere catalogs.manage) — son datos de referencia que
# necesitan contracts/inventory/sales para operar, no solo quien administra
# el catálogo. Ver docs/API_GUIDE.md.


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(
    user: Annotated[CurrentUser, Depends(_view)],
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
    user: Annotated[CurrentUser, Depends(_view)],
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
    user: Annotated[CurrentUser, Depends(_view)],
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
    user: Annotated[CurrentUser, Depends(_view)],
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


@router.get("/suppliers/{supplier_id}/summary", response_model=SupplierSummaryOut)
async def get_supplier_summary(
    supplier_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> SupplierSummaryOut:
    """Ficha del proveedor: cuánto se le ha comprado, cuánto se le debe, desde
    cuándo y cuántos productos distintos.

    El CLIENTE tiene su ficha con historial cruzado desde el paso 4; el
    proveedor tenía solo un formulario de creación, así que "¿cuánto le he
    comprado?" no tenía respuesta aunque el dato estuviera completo.
    """
    return await service.get_supplier_summary(
        db, company_id=user.company_id, supplier_id=supplier_id
    )


@router.get("/suppliers/{supplier_id}/purchases", response_model=CursorPage[SupplierPurchaseOut])
async def list_supplier_purchases(
    supplier_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CursorPage[SupplierPurchaseOut]:
    """Historial de compras a este proveedor."""
    return await service.list_supplier_purchases(
        db,
        company_id=user.company_id,
        supplier_id=supplier_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )
