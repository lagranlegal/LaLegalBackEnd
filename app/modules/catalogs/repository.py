from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_CATEGORY_COLUMNS = (
    "id, parent_id, level, name, code_letter, applies_to, "
    "default_term_months, arrears_window_months, max_ltv_pct, active"
)
_SUPPLIER_COLUMNS = (
    "id, name, doc_type, doc_number, phone, email, address, code_letter, notes, active"
)


async def get_category(db: AsyncSession, *, company_id: UUID, category_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_CATEGORY_COLUMNS} from public.category "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(category_id)},
    )
    return result.first()


async def get_ancestor_chain(
    db: AsyncSession, *, company_id: UUID, level3_category_id: UUID
) -> tuple[UUID, UUID, UUID] | None:
    """Devuelve (cat1_id, cat2_id, cat3_id) subiendo por `parent_id` desde una
    categoría nivel 3 — la usa `inventory.integration` porque `contract_item`
    solo guarda la categoría nivel 3, no la cadena completa.
    """
    cat3 = await get_category(db, company_id=company_id, category_id=level3_category_id)
    if cat3 is None or cat3._mapping["level"] != 3 or cat3._mapping["parent_id"] is None:
        return None
    cat2_id = cat3._mapping["parent_id"]
    cat2 = await get_category(db, company_id=company_id, category_id=cat2_id)
    if cat2 is None or cat2._mapping["parent_id"] is None:
        return None
    cat1_id = cat2._mapping["parent_id"]
    return (cat1_id, cat2_id, level3_category_id)


async def list_categories(db: AsyncSession, *, company_id: UUID) -> list[Row[Any]]:
    result = await db.execute(
        text(
            f"select {_CATEGORY_COLUMNS} from public.category "
            "where company_id = :company_id order by level, name"
        ),
        {"company_id": str(company_id)},
    )
    return list(result.all())


async def _sibling_value_exists(
    db: AsyncSession,
    *,
    company_id: UUID,
    parent_id: UUID | None,
    column: str,
    value: str,
    exclude_id: UUID | None,
) -> bool:
    """`parent_id IS NULL` no matchea consigo mismo en un `UNIQUE` de Postgres,
    así que la unicidad entre hermanos raíz (parent_id NULL) hay que
    garantizarla acá, no en el constraint de la migración.
    """
    query = f"select 1 from public.category where company_id = :company_id and {column} = :value"
    params: dict[str, Any] = {"company_id": str(company_id), "value": value}
    if parent_id is None:
        query += " and parent_id is null"
    else:
        query += " and parent_id = :parent_id"
        params["parent_id"] = str(parent_id)
    if exclude_id is not None:
        query += " and id != :exclude_id"
        params["exclude_id"] = str(exclude_id)
    result = await db.execute(text(query), params)
    return result.first() is not None


async def sibling_code_letter_exists(
    db: AsyncSession,
    *,
    company_id: UUID,
    parent_id: UUID | None,
    code_letter: str,
    exclude_id: UUID | None = None,
) -> bool:
    return await _sibling_value_exists(
        db,
        company_id=company_id,
        parent_id=parent_id,
        column="code_letter",
        value=code_letter,
        exclude_id=exclude_id,
    )


async def sibling_name_exists(
    db: AsyncSession,
    *,
    company_id: UUID,
    parent_id: UUID | None,
    name: str,
    exclude_id: UUID | None = None,
) -> bool:
    return await _sibling_value_exists(
        db,
        company_id=company_id,
        parent_id=parent_id,
        column="name",
        value=name,
        exclude_id=exclude_id,
    )


async def insert_category(
    db: AsyncSession,
    *,
    category_id: UUID,
    company_id: UUID,
    parent_id: UUID | None,
    level: int,
    name: str,
    code_letter: str,
    applies_to: str,
    default_term_months: int | None,
    arrears_window_months: int | None,
    max_ltv_pct: Any,
) -> None:
    await db.execute(
        text(
            """
            insert into public.category
                (id, company_id, parent_id, level, name, code_letter, applies_to,
                 default_term_months, arrears_window_months, max_ltv_pct)
            values
                (:id, :company_id, :parent_id, :level, :name, :code_letter, :applies_to,
                 :default_term_months, :arrears_window_months, :max_ltv_pct)
            """
        ),
        {
            "id": str(category_id),
            "company_id": str(company_id),
            "parent_id": str(parent_id) if parent_id else None,
            "level": level,
            "name": name,
            "code_letter": code_letter,
            "applies_to": applies_to,
            "default_term_months": default_term_months,
            "arrears_window_months": arrears_window_months,
            "max_ltv_pct": max_ltv_pct,
        },
    )


async def update_category(
    db: AsyncSession, *, company_id: UUID, category_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `CategoryUpdateIn.model_dump(exclude_unset=True)` en
    service.py — claves fijas y conocidas, nunca texto de un usuario.
    """
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "company_id": str(company_id), "id": str(category_id)}
    await db.execute(
        text(
            f"update public.category set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )


async def get_supplier(db: AsyncSession, *, company_id: UUID, supplier_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_SUPPLIER_COLUMNS} from public.supplier "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(supplier_id)},
    )
    return result.first()


async def list_suppliers(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = f"select {_SUPPLIER_COLUMNS} from public.supplier where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def code_letter_in_use(
    db: AsyncSession, *, company_id: UUID, code_letter: str, exclude_id: UUID | None = None
) -> bool:
    query = (
        "select 1 from public.supplier "
        "where company_id = :company_id and code_letter = :code_letter"
    )
    params: dict[str, Any] = {"company_id": str(company_id), "code_letter": code_letter}
    if exclude_id is not None:
        query += " and id != :exclude_id"
        params["exclude_id"] = str(exclude_id)
    result = await db.execute(text(query), params)
    return result.first() is not None


async def insert_supplier(
    db: AsyncSession,
    *,
    supplier_id: UUID,
    company_id: UUID,
    name: str,
    doc_type: str | None,
    doc_number: str | None,
    phone: str | None,
    email: str | None,
    address: str | None,
    code_letter: str,
    notes: str | None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.supplier
                (id, company_id, name, doc_type, doc_number, phone, email, address,
                 code_letter, notes)
            values
                (:id, :company_id, :name, :doc_type, :doc_number, :phone, :email, :address,
                 :code_letter, :notes)
            """
        ),
        {
            "id": str(supplier_id),
            "company_id": str(company_id),
            "name": name,
            "doc_type": doc_type,
            "doc_number": doc_number,
            "phone": phone,
            "email": email,
            "address": address,
            "code_letter": code_letter,
            "notes": notes,
        },
    )


async def update_supplier(
    db: AsyncSession, *, company_id: UUID, supplier_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `SupplierUpdateIn.model_dump(exclude_unset=True)` en
    service.py — claves fijas y conocidas, nunca texto de un usuario.
    """
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "company_id": str(company_id), "id": str(supplier_id)}
    await db.execute(
        text(
            f"update public.supplier set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )
