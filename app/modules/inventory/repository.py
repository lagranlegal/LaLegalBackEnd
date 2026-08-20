import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_ITEM_COLUMNS = (
    "id, code, name, cat1_id, cat2_id, cat3_id, description, origin, supplier_id, "
    "source_contract_id, cost, sale_price, quantity, status, photos, entry_date, created_at"
)
_ENTRY_COLUMNS = (
    "id, number, origin_type, supplier_id, supplier_invoice, contract_id, total_cost, "
    "notes, payment_method, created_at"
)
_EXIT_COLUMNS = "id, number, exit_type, reason, created_at"


async def next_counter(db: AsyncSession, *, company_id: UUID, prefix: str) -> int:
    result = await db.execute(
        text("select public.next_counter(:company_id, :prefix)"),
        {"company_id": str(company_id), "prefix": prefix},
    )
    return int(result.scalar_one())


async def insert_item(
    db: AsyncSession,
    *,
    item_id: UUID,
    company_id: UUID,
    name: str,
    cat1_id: UUID,
    cat2_id: UUID,
    cat3_id: UUID,
    description: str | None,
    origin: str,
    supplier_id: UUID | None,
    source_contract_id: UUID | None,
    cost: Decimal,
    quantity: int,
    photos: list[str],
    created_by: UUID | None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.inventory_item
                (id, company_id, name, cat1_id, cat2_id, cat3_id, description, origin,
                 supplier_id, source_contract_id, cost, quantity, photos, created_by)
            values
                (:id, :company_id, :name, :cat1_id, :cat2_id, :cat3_id, :description, :origin,
                 :supplier_id, :source_contract_id, :cost, :quantity, cast(:photos as jsonb),
                 :created_by)
            """
        ),
        {
            "id": str(item_id),
            "company_id": str(company_id),
            "name": name,
            "cat1_id": str(cat1_id),
            "cat2_id": str(cat2_id),
            "cat3_id": str(cat3_id),
            "description": description,
            "origin": origin,
            "supplier_id": str(supplier_id) if supplier_id else None,
            "source_contract_id": str(source_contract_id) if source_contract_id else None,
            "cost": cost,
            "quantity": quantity,
            "photos": json.dumps(photos),
            "created_by": str(created_by) if created_by else None,
        },
    )


async def get_item(db: AsyncSession, *, company_id: UUID, item_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_ITEM_COLUMNS} from public.inventory_item "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(item_id)},
    )
    return result.first()


async def list_items(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    status_filter: str | None,
    q: str | None = None,
    cat1_id: UUID | None = None,
    cat2_id: UUID | None = None,
    cat3_id: UUID | None = None,
    supplier_id: UUID | None = None,
    origin: str | None = None,
) -> list[Row[Any]]:
    query = f"select {_ITEM_COLUMNS} from public.inventory_item where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if status_filter:
        query += " and status = :status"
        params["status"] = status_filter
    if q:
        # Código: prefijo case-insensitive. Es la búsqueda del mostrador — el
        # vendedor tiene el código impreso en la etiqueta de la vitrina
        # (`JAO0003R`) y lo tipea completo o casi. No necesita full-text, y sí
        # necesita tolerar minúsculas.
        #
        # Nombre: full-text en español (fragmentos, tildes, orden de palabras),
        # mismo criterio que `customer.full_name`.
        #
        # `code` es NULL mientras el artículo está en borrador (se emite al
        # publicar), y `like` sobre NULL da NULL, no false — por eso el
        # `coalesce`: sin él, buscar por nombre nunca encontraría un borrador.
        query += (
            " and (coalesce(code, '') ilike :code_prefix"
            " or to_tsvector('spanish', name) @@ plainto_tsquery('spanish', :q))"
        )
        params["q"] = q
        params["code_prefix"] = f"{q}%"
    for column, value in (
        ("cat1_id", cat1_id),
        ("cat2_id", cat2_id),
        ("cat3_id", cat3_id),
        ("supplier_id", supplier_id),
    ):
        if value is not None:
            query += f" and {column} = :{column}"
            params[column] = str(value)
    if origin:
        query += " and origin = :origin"
        params["origin"] = origin
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def update_item_fields(
    db: AsyncSession, *, company_id: UUID, item_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `ItemUpdateIn.model_dump(exclude_unset=True)` en
    service.py — claves fijas y conocidas, nunca texto de un usuario. `photos`
    necesita el cast a jsonb, así que se maneja aparte si viene incluida.
    """
    if not fields:
        return
    fields = dict(fields)
    assignment_parts = []
    params: dict[str, Any] = {"company_id": str(company_id), "id": str(item_id)}
    if "photos" in fields:
        assignment_parts.append("photos = cast(:photos as jsonb)")
        params["photos"] = json.dumps(fields.pop("photos"))
    for key, value in fields.items():
        assignment_parts.append(f"{key} = :{key}")
        params[key] = value
    await db.execute(
        text(
            f"update public.inventory_item set {', '.join(assignment_parts)} "
            "where company_id = :company_id and id = :id"
        ),
        params,
    )


async def code_exists(db: AsyncSession, *, company_id: UUID, code: str) -> bool:
    result = await db.execute(
        text("select 1 from public.inventory_item where company_id = :company_id and code = :code"),
        {"company_id": str(company_id), "code": code},
    )
    return result.first() is not None


async def publish_item(db: AsyncSession, *, company_id: UUID, item_id: UUID, code: str) -> None:
    await db.execute(
        text(
            "update public.inventory_item set code = :code, status = 'available' "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(item_id), "code": code},
    )


async def insert_entry(
    db: AsyncSession,
    *,
    entry_id: UUID,
    company_id: UUID,
    number: int,
    origin_type: str,
    supplier_id: UUID | None,
    supplier_invoice: str | None,
    contract_id: UUID | None,
    total_cost: Decimal,
    notes: str | None,
    registered_by: UUID | None,
    # Solo los ingresos origin_type='purchase' los llevan (00014 lo hace
    # cumplir con un CHECK): un remate no mueve caja ni necesita dedupe de
    # dinero — lo dispara `contracts.auction`, que ya es idempotente.
    payment_method: str | None = None,
    idempotency_key: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.inventory_entry
                (id, company_id, number, origin_type, supplier_id, supplier_invoice,
                 contract_id, total_cost, notes, registered_by, payment_method,
                 idempotency_key)
            values
                (:id, :company_id, :number, :origin_type, :supplier_id, :supplier_invoice,
                 :contract_id, :total_cost, :notes, :registered_by, :payment_method,
                 :idempotency_key)
            """
        ),
        {
            "id": str(entry_id),
            "company_id": str(company_id),
            "number": number,
            "origin_type": origin_type,
            "supplier_id": str(supplier_id) if supplier_id else None,
            "supplier_invoice": supplier_invoice,
            "contract_id": str(contract_id) if contract_id else None,
            "total_cost": total_cost,
            "notes": notes,
            "registered_by": str(registered_by) if registered_by else None,
            "payment_method": payment_method,
            "idempotency_key": idempotency_key,
        },
    )


async def find_entry_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    """Reintento de red del mismo ingreso: se devuelve el que ya existe en vez
    de crear un duplicado (mismo patrón que `sales.find_by_idempotency_key` y
    `contracts.find_contract_by_idempotency_key`).
    """
    result = await db.execute(
        text(
            f"select {_ENTRY_COLUMNS} from public.inventory_entry "
            "where company_id = :company_id and idempotency_key = :idempotency_key"
        ),
        {"company_id": str(company_id), "idempotency_key": idempotency_key},
    )
    return result.first()


async def insert_entry_line(
    db: AsyncSession,
    *,
    line_id: UUID,
    company_id: UUID,
    entry_id: UUID,
    item_id: UUID,
    quantity: int,
    unit_cost: Decimal,
) -> None:
    await db.execute(
        text(
            """
            insert into public.inventory_entry_line
                (id, company_id, entry_id, item_id, quantity, unit_cost)
            values
                (:id, :company_id, :entry_id, :item_id, :quantity, :unit_cost)
            """
        ),
        {
            "id": str(line_id),
            "company_id": str(company_id),
            "entry_id": str(entry_id),
            "item_id": str(item_id),
            "quantity": quantity,
            "unit_cost": unit_cost,
        },
    )


async def get_entry(db: AsyncSession, *, company_id: UUID, entry_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_ENTRY_COLUMNS} from public.inventory_entry "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(entry_id)},
    )
    return result.first()


async def list_entries(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = f"select {_ENTRY_COLUMNS} from public.inventory_entry where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def list_items_for_entry(
    db: AsyncSession, *, company_id: UUID, entry_id: UUID
) -> list[Row[Any]]:
    """Orden determinista: `created_at` SOLO empata acá, siempre. Todos los
    ítems de un ingreso se insertan en la misma transacción y `now()` en
    Postgres devuelve el instante de INICIO de la transacción — o sea el mismo
    valor para todas las filas (verificado: `count(distinct ts) = 1`). Con un
    `order by created_at` pelado el orden quedaba a merced del plan de
    ejecución, así que `POST /inventory/entries` podía devolver los artículos
    en cualquier orden entre dos llamadas idénticas. Se encontró por un test
    que empezó a fallar según qué otro test corriera antes.

    El desempate por `id` da estabilidad, no el orden en que el usuario
    escribió las líneas: `inventory_entry_line` no guarda su posición y el `id`
    es un UUID aleatorio. Para devolverlos en el orden capturado haría falta
    una columna de posición en la línea — anotado como pendiente, hoy ninguna
    pantalla depende de eso.
    """
    result = await db.execute(
        text(
            f"""
            select {_ITEM_COLUMNS} from public.inventory_item
            where company_id = :company_id and id in (
                select item_id from public.inventory_entry_line
                where company_id = :company_id and entry_id = :entry_id
            )
            order by created_at, id
            """
        ),
        {"company_id": str(company_id), "entry_id": str(entry_id)},
    )
    return list(result.all())


async def insert_exit(
    db: AsyncSession,
    *,
    exit_id: UUID,
    company_id: UUID,
    number: int,
    exit_type: str,
    reason: str,
    registered_by: UUID | None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.inventory_exit
                (id, company_id, number, exit_type, reason, registered_by)
            values
                (:id, :company_id, :number, :exit_type, :reason, :registered_by)
            """
        ),
        {
            "id": str(exit_id),
            "company_id": str(company_id),
            "number": number,
            "exit_type": exit_type,
            "reason": reason,
            "registered_by": str(registered_by) if registered_by else None,
        },
    )


async def insert_exit_line(
    db: AsyncSession,
    *,
    line_id: UUID,
    company_id: UUID,
    exit_id: UUID,
    item_id: UUID,
    quantity: int,
) -> None:
    await db.execute(
        text(
            """
            insert into public.inventory_exit_line (id, company_id, exit_id, item_id, quantity)
            values (:id, :company_id, :exit_id, :item_id, :quantity)
            """
        ),
        {
            "id": str(line_id),
            "company_id": str(company_id),
            "exit_id": str(exit_id),
            "item_id": str(item_id),
            "quantity": quantity,
        },
    )


async def get_exit(db: AsyncSession, *, company_id: UUID, exit_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_EXIT_COLUMNS} from public.inventory_exit "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(exit_id)},
    )
    return result.first()


async def list_exits(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = f"select {_EXIT_COLUMNS} from public.inventory_exit where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def adjust_item_quantity(
    db: AsyncSession, *, company_id: UUID, item_id: UUID, delta: int, new_status: str | None
) -> None:
    query = "update public.inventory_item set quantity = quantity + :delta"
    params: dict[str, Any] = {"company_id": str(company_id), "id": str(item_id), "delta": delta}
    if new_status is not None:
        query += ", status = :status"
        params["status"] = new_status
    query += " where company_id = :company_id and id = :id"
    await db.execute(text(query), params)


async def get_category_chain_letters(
    db: AsyncSession, *, company_id: UUID, cat1_id: UUID, cat2_id: UUID, cat3_id: UUID
) -> tuple[str, str, str] | None:
    result = await db.execute(
        text(
            """
            select
              (select code_letter from public.category where id = :cat1 and company_id = :cid),
              (select code_letter from public.category where id = :cat2 and company_id = :cid),
              (select code_letter from public.category where id = :cat3 and company_id = :cid)
            """
        ),
        {"cid": str(company_id), "cat1": str(cat1_id), "cat2": str(cat2_id), "cat3": str(cat3_id)},
    )
    row = result.first()
    if row is None or None in row:
        return None
    return (row[0], row[1], row[2])
