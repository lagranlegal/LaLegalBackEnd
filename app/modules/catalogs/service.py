from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import AppError, ConflictError, NotFoundError
from app.modules.catalogs import repository
from app.modules.catalogs.schemas import (
    CategoryCreateIn,
    CategoryOut,
    CategoryUpdateIn,
    SupplierCreateIn,
    SupplierOut,
    SupplierUpdateIn,
)

_MAX_LEVEL = 3


def _row_to_category(row: Row[Any]) -> CategoryOut:
    m = row._mapping
    return CategoryOut(
        id=m["id"],
        parent_id=m["parent_id"],
        level=m["level"],
        name=m["name"],
        code_letter=m["code_letter"],
        applies_to=m["applies_to"],
        default_term_months=m["default_term_months"],
        arrears_window_months=m["arrears_window_months"],
        max_ltv_pct=m["max_ltv_pct"],
        active=m["active"],
    )


def _row_to_supplier(row: Row[Any]) -> SupplierOut:
    m = row._mapping
    return SupplierOut(
        id=m["id"],
        name=m["name"],
        doc_type=m["doc_type"],
        doc_number=m["doc_number"],
        phone=m["phone"],
        email=m["email"],
        address=m["address"],
        code_letter=m["code_letter"],
        notes=m["notes"],
        active=m["active"],
    )


async def create_category(
    db: AsyncSession, *, company_id: UUID, body: CategoryCreateIn
) -> CategoryOut:
    parent_id = body.parent_id
    if parent_id is not None:
        parent = await repository.get_category(db, company_id=company_id, category_id=parent_id)
        if parent is None:
            raise NotFoundError("La categoría padre no existe en esta empresa.")
        if parent._mapping["level"] >= _MAX_LEVEL:
            raise AppError(
                "El árbol de categorías es de máximo 3 niveles.",
                details={"parent_level": parent._mapping["level"]},
            )
        level = parent._mapping["level"] + 1
    else:
        level = 1

    if await repository.sibling_code_letter_exists(
        db, company_id=company_id, parent_id=parent_id, code_letter=body.code_letter
    ):
        raise ConflictError(
            "Ya existe una categoría hermana con esa letra de código.",
            details={"code_letter": body.code_letter},
        )
    if await repository.sibling_name_exists(
        db, company_id=company_id, parent_id=parent_id, name=body.name
    ):
        raise ConflictError(
            "Ya existe una categoría hermana con ese nombre.", details={"name": body.name}
        )

    category_id = uuid4()
    await repository.insert_category(
        db,
        category_id=category_id,
        company_id=company_id,
        parent_id=parent_id,
        level=level,
        name=body.name,
        code_letter=body.code_letter,
        applies_to=body.applies_to,
        default_term_months=body.default_term_months,
        arrears_window_months=body.arrears_window_months,
        max_ltv_pct=body.max_ltv_pct,
    )
    row = await repository.get_category(db, company_id=company_id, category_id=category_id)
    assert row is not None
    return _row_to_category(row)


async def list_categories(db: AsyncSession, *, company_id: UUID) -> list[CategoryOut]:
    rows = await repository.list_categories(db, company_id=company_id)
    return [_row_to_category(r) for r in rows]


async def get_category(db: AsyncSession, *, company_id: UUID, category_id: UUID) -> CategoryOut:
    row = await repository.get_category(db, company_id=company_id, category_id=category_id)
    if row is None:
        raise NotFoundError("La categoría no existe en esta empresa.")
    return _row_to_category(row)


async def update_category(
    db: AsyncSession, *, company_id: UUID, category_id: UUID, body: CategoryUpdateIn
) -> CategoryOut:
    current = await repository.get_category(db, company_id=company_id, category_id=category_id)
    if current is None:
        raise NotFoundError("La categoría no existe en esta empresa.")
    parent_id = current._mapping["parent_id"]

    if body.code_letter is not None and await repository.sibling_code_letter_exists(
        db,
        company_id=company_id,
        parent_id=parent_id,
        code_letter=body.code_letter,
        exclude_id=category_id,
    ):
        raise ConflictError(
            "Ya existe una categoría hermana con esa letra de código.",
            details={"code_letter": body.code_letter},
        )
    if body.name is not None and await repository.sibling_name_exists(
        db, company_id=company_id, parent_id=parent_id, name=body.name, exclude_id=category_id
    ):
        raise ConflictError(
            "Ya existe una categoría hermana con ese nombre.", details={"name": body.name}
        )

    fields = body.model_dump(exclude_unset=True)
    await repository.update_category(
        db, company_id=company_id, category_id=category_id, fields=fields
    )
    row = await repository.get_category(db, company_id=company_id, category_id=category_id)
    assert row is not None
    return _row_to_category(row)


async def create_supplier(
    db: AsyncSession, *, company_id: UUID, body: SupplierCreateIn
) -> SupplierOut:
    if await repository.code_letter_in_use(db, company_id=company_id, code_letter=body.code_letter):
        raise ConflictError(
            "Ya existe un proveedor con esa letra de código en esta empresa.",
            details={"code_letter": body.code_letter},
        )

    supplier_id = uuid4()
    await repository.insert_supplier(
        db,
        supplier_id=supplier_id,
        company_id=company_id,
        name=body.name,
        doc_type=body.doc_type,
        doc_number=body.doc_number,
        phone=body.phone,
        email=body.email,
        address=body.address,
        code_letter=body.code_letter,
        notes=body.notes,
    )
    row = await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id)
    assert row is not None
    return _row_to_supplier(row)


async def list_suppliers(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[SupplierOut]:
    rows = await repository.list_suppliers(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_supplier(r) for r in page.items], next_cursor=page.next_cursor)


async def get_supplier(db: AsyncSession, *, company_id: UUID, supplier_id: UUID) -> SupplierOut:
    row = await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id)
    if row is None:
        raise NotFoundError("El proveedor no existe en esta empresa.")
    return _row_to_supplier(row)


async def update_supplier(
    db: AsyncSession, *, company_id: UUID, supplier_id: UUID, body: SupplierUpdateIn
) -> SupplierOut:
    current = await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id)
    if current is None:
        raise NotFoundError("El proveedor no existe en esta empresa.")

    if body.code_letter is not None and await repository.code_letter_in_use(
        db, company_id=company_id, code_letter=body.code_letter, exclude_id=supplier_id
    ):
        raise ConflictError(
            "Ya existe un proveedor con esa letra de código en esta empresa.",
            details={"code_letter": body.code_letter},
        )

    fields = body.model_dump(exclude_unset=True)
    await repository.update_supplier(
        db, company_id=company_id, supplier_id=supplier_id, fields=fields
    )
    row = await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id)
    assert row is not None
    return _row_to_supplier(row)
