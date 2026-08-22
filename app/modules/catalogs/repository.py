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


async def supplier_summary(db: AsyncSession, *, company_id: UUID, supplier_id: UUID) -> Row[Any]:
    """Agregados de un proveedor: qué se le compró y qué se le debe.

    `origin_type = 'purchase'` en los totales de compra: un inventario inicial
    que conserve el proveedor original no es una compra que se le haya hecho,
    y contarla inflaría lo que se le ha comprado de verdad.
    """
    result = await db.execute(
        text(
            """
            select
              count(*)                                        as purchase_count,
              coalesce(sum(e.total_cost), 0)                   as total_purchased,
              count(*) filter (where e.paid_at is null)        as pending_count,
              coalesce(sum(e.total_cost)
                filter (where e.paid_at is null), 0)           as pending_total,
              min(e.entry_date)                                as first_purchase_date,
              max(e.entry_date)                                as last_purchase_date
            from public.inventory_entry e
            where e.company_id = :cid
              and e.supplier_id = :sid
              and e.origin_type = 'purchase'
            """
        ),
        {"cid": str(company_id), "sid": str(supplier_id)},
    )
    row = result.first()
    assert row is not None  # los agregados siempre devuelven una fila
    return row


async def supplier_product_count(db: AsyncSession, *, company_id: UUID, supplier_id: UUID) -> int:
    """Productos DISTINTOS comprados a este proveedor. Va aparte del resto de
    agregados porque se cuenta sobre lotes, no sobre ingresos: un solo ingreso
    puede traer varios productos."""
    result = await db.execute(
        text(
            "select count(distinct i.product_id) from public.inventory_item i "
            "where i.company_id = :cid and i.supplier_id = :sid"
        ),
        {"cid": str(company_id), "sid": str(supplier_id)},
    )
    return int(result.scalar_one() or 0)


async def supplier_purchases(
    db: AsyncSession, *, company_id: UUID, supplier_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = """
        select
          e.id as entry_id, e.number, e.entry_date, e.supplier_invoice,
          e.total_cost, e.paid_at,
          (select count(*) from public.inventory_entry_line l
             where l.entry_id = e.id and l.company_id = e.company_id) as item_count
        from public.inventory_entry e
        where e.company_id = :cid and e.supplier_id = :sid
          and e.origin_type = 'purchase'
    """
    params: dict[str, Any] = {"cid": str(company_id), "sid": str(supplier_id), "limit": limit + 1}
    if cursor is not None:
        query += " and e.id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by e.id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def resolve_category_params(
    db: AsyncSession, *, company_id: UUID, category_id: UUID
) -> Row[Any] | None:
    """Plazo, ventana de mora y LTV de una categoría, HEREDADOS del árbol.

    Toma el valor de la categoría misma y, si está vacío, sube por
    `parent_id` hasta encontrar el ancestro más cercano que lo tenga. Cada
    campo se resuelve por separado: una hoja puede heredar el plazo de su
    abuelo y traer su propio LTV.

    POR QUÉ EXISTE: hasta ahora el contrato leía estos tres valores SOLO de la
    categoría de nivel 3, así que los mismos campos en los niveles 1 y 2 eran
    configuración muerta — se pedían en el formulario y nada los leía. Peor:
    si a UNA hoja se le olvidaba el plazo, crear un contrato con esa prenda
    fallaba con "la categoría no tiene plazo configurado". Con treinta hojas,
    era cuestión de tiempo.

    Heredando, "toda la joyería en oro va a 4 meses" se configura una vez en
    `Oro` en vez de repetirse en cada hoja — que es lo que hace que tener un
    árbol de tres niveles valga la pena— y esa clase de falla desaparece.

    No hizo falta migración: los campos ya existían en los tres niveles, solo
    que nadie leía los de arriba.

    Los contratos ya creados no se ven afectados: el contrato congela estos
    valores en su propio SNAPSHOT al nacer (CLAUDE.md), así que cambiar el
    árbol nunca reescribe un contrato vivo.
    """
    result = await db.execute(
        text(
            """
            with recursive cadena as (
              select id, parent_id, default_term_months, arrears_window_months,
                     max_ltv_pct, 0 as profundidad
              from public.category
              where company_id = :cid and id = :id
              union all
              select c.id, c.parent_id, c.default_term_months, c.arrears_window_months,
                     c.max_ltv_pct, cadena.profundidad + 1
              from public.category c
              join cadena on c.id = cadena.parent_id
              where c.company_id = :cid
            )
            select
              (array_agg(default_term_months order by profundidad)
                 filter (where default_term_months is not null))[1] as default_term_months,
              (array_agg(arrears_window_months order by profundidad)
                 filter (where arrears_window_months is not null))[1] as arrears_window_months,
              (array_agg(max_ltv_pct order by profundidad)
                 filter (where max_ltv_pct is not null))[1] as max_ltv_pct
            from cadena
            """
        ),
        {"cid": str(company_id), "id": str(category_id)},
    )
    return result.first()
