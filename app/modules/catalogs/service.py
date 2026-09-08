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
    SupplierPurchaseOut,
    SupplierSummaryOut,
    SupplierUpdateIn,
)
from app.modules.identity import repository as identity_repo

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
    db: AsyncSession, *, company_id: UUID, body: CategoryCreateIn, acting_user_id: UUID
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
    # UNA CATEGORÍA DEFINE LAS CONDICIONES DE LOS CONTRATOS FUTUROS: plazo,
    # ventana de mora y LTV salen de acá y se CONGELAN en cada contrato al
    # firmarlo. Cambiarla no toca los contratos vivos, pero sí los que se
    # firmen después — y esa es exactamente la clase de cambio que hay que
    # poder rastrear cuando dos contratos del mismo mes tienen plazos
    # distintos. También manda la letra del código de inventario.
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="catalogs",
        action="create_category",
        entity_type="category",
        entity_id=category_id,
        after={
            "name": body.name,
            "level": level,
            "code_letter": body.code_letter,
            "default_term_months": body.default_term_months,
            "arrears_window_months": body.arrears_window_months,
            "max_ltv_pct": str(body.max_ltv_pct) if body.max_ltv_pct is not None else None,
        },
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
    db: AsyncSession,
    *,
    company_id: UUID,
    category_id: UUID,
    body: CategoryUpdateIn,
    acting_user_id: UUID,
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
    # Con `before`: acá viven el plazo y la ventana de mora de los contratos
    # que se firmen a partir de ahora (ver `create_category`).
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="catalogs",
        action="update_category",
        entity_type="category",
        entity_id=category_id,
        before={
            campo: str(current._mapping[campo]) if current._mapping[campo] is not None else None
            for campo in fields
            if campo in current._mapping
        },
        after={k: str(v) if v is not None else None for k, v in fields.items()},
    )
    row = await repository.get_category(db, company_id=company_id, category_id=category_id)
    assert row is not None
    return _row_to_category(row)


async def create_supplier(
    db: AsyncSession, *, company_id: UUID, body: SupplierCreateIn, acting_user_id: UUID
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
    # La letra del proveedor va impresa en el código de cada lote que se le
    # compre, y es inmutable una vez emitido.
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="catalogs",
        action="create_supplier",
        entity_type="supplier",
        entity_id=supplier_id,
        after={"name": body.name, "code_letter": body.code_letter},
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
    db: AsyncSession,
    *,
    company_id: UUID,
    supplier_id: UUID,
    body: SupplierUpdateIn,
    acting_user_id: UUID,
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
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="catalogs",
        action="update_supplier",
        entity_type="supplier",
        entity_id=supplier_id,
        before={
            campo: str(current._mapping[campo]) if current._mapping[campo] is not None else None
            for campo in fields
            if campo in current._mapping
        },
        after={k: str(v) if v is not None else None for k, v in fields.items()},
    )
    row = await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id)
    assert row is not None
    return _row_to_supplier(row)


async def get_supplier_summary(
    db: AsyncSession, *, company_id: UUID, supplier_id: UUID
) -> SupplierSummaryOut:
    """Ficha del proveedor. El cliente ya tenía la suya desde el paso 4; el
    proveedor era el hermano pobre — un formulario de creación y nada más."""
    supplier = await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id)
    if supplier is None:
        raise NotFoundError("El proveedor no existe en esta empresa.")

    agg = await repository.supplier_summary(db, company_id=company_id, supplier_id=supplier_id)
    m = agg._mapping
    return SupplierSummaryOut(
        supplier_id=supplier_id,
        name=supplier._mapping["name"],
        code_letter=supplier._mapping["code_letter"],
        purchase_count=m["purchase_count"] or 0,
        total_purchased=m["total_purchased"],
        pending_count=m["pending_count"] or 0,
        pending_total=m["pending_total"],
        first_purchase_date=m["first_purchase_date"],
        last_purchase_date=m["last_purchase_date"],
        product_count=await repository.supplier_product_count(
            db, company_id=company_id, supplier_id=supplier_id
        ),
    )


async def list_supplier_purchases(
    db: AsyncSession, *, company_id: UUID, supplier_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[SupplierPurchaseOut]:
    if await repository.get_supplier(db, company_id=company_id, supplier_id=supplier_id) is None:
        raise NotFoundError("El proveedor no existe en esta empresa.")
    rows = await repository.supplier_purchases(
        db, company_id=company_id, supplier_id=supplier_id, cursor=cursor, limit=limit
    )
    page = make_page(rows, limit, lambda r: r._mapping["entry_id"])
    return CursorPage(
        items=[
            SupplierPurchaseOut(
                entry_id=r._mapping["entry_id"],
                number=r._mapping["number"],
                entry_date=r._mapping["entry_date"],
                supplier_invoice=r._mapping["supplier_invoice"],
                total_cost=r._mapping["total_cost"],
                item_count=r._mapping["item_count"] or 0,
                paid_at=r._mapping["paid_at"],
            )
            for r in page.items
        ],
        next_cursor=page.next_cursor,
    )
