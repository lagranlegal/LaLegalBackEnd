from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import AppError, ConflictError, NotFoundError
from app.modules.catalogs import repository as catalogs_repo
from app.modules.identity import repository as identity_repo
from app.modules.inventory import repository, rules
from app.modules.inventory.schemas import (
    EntryCreateIn,
    EntryOut,
    ExitCreateIn,
    ExitOut,
    ItemOut,
    ItemPublishIn,
    ItemUpdateIn,
)

_LEVEL_1, _LEVEL_2, _LEVEL_3 = 1, 2, 3


def _row_to_item(row: Row[Any]) -> ItemOut:
    m = row._mapping
    return ItemOut(
        id=m["id"],
        code=m["code"],
        name=m["name"],
        cat1_id=m["cat1_id"],
        cat2_id=m["cat2_id"],
        cat3_id=m["cat3_id"],
        description=m["description"],
        origin=m["origin"],
        supplier_id=m["supplier_id"],
        source_contract_id=m["source_contract_id"],
        cost=m["cost"],
        sale_price=m["sale_price"],
        quantity=m["quantity"],
        status=m["status"],
        photos=list(m["photos"] or []),
        entry_date=m["entry_date"],
        created_at=m["created_at"],
    )


def _row_to_entry(row: Row[Any], items: list[ItemOut]) -> EntryOut:
    m = row._mapping
    return EntryOut(
        id=m["id"],
        number=m["number"],
        origin_type=m["origin_type"],
        supplier_id=m["supplier_id"],
        supplier_invoice=m["supplier_invoice"],
        contract_id=m["contract_id"],
        total_cost=m["total_cost"],
        notes=m["notes"],
        created_at=m["created_at"],
        items=items,
    )


def _row_to_exit(row: Row[Any]) -> ExitOut:
    m = row._mapping
    return ExitOut(
        id=m["id"],
        number=m["number"],
        exit_type=m["exit_type"],
        reason=m["reason"],
        created_at=m["created_at"],
    )


async def _validate_category_chain(
    db: AsyncSession, *, company_id: UUID, cat1_id: UUID, cat2_id: UUID, cat3_id: UUID
) -> None:
    cat1 = await catalogs_repo.get_category(db, company_id=company_id, category_id=cat1_id)
    cat2 = await catalogs_repo.get_category(db, company_id=company_id, category_id=cat2_id)
    cat3 = await catalogs_repo.get_category(db, company_id=company_id, category_id=cat3_id)
    if cat1 is None or cat2 is None or cat3 is None:
        raise NotFoundError("Alguna de las categorías del artículo no existe en esta empresa.")
    if (
        cat1._mapping["level"] != _LEVEL_1
        or cat2._mapping["level"] != _LEVEL_2
        or cat3._mapping["level"] != _LEVEL_3
    ):
        raise AppError("cat1_id/cat2_id/cat3_id deben ser, en orden, niveles 1, 2 y 3.")
    if cat2._mapping["parent_id"] != cat1_id or cat3._mapping["parent_id"] != cat2_id:
        raise AppError("La cadena de categorías no forma una rama válida del árbol.")


async def create_entry(
    db: AsyncSession, *, company_id: UUID, body: EntryCreateIn, registered_by: UUID
) -> EntryOut:
    if body.origin_type == "purchase" and body.supplier_id is None:
        raise AppError("Un ingreso de compra requiere `supplier_id`.")

    total_cost = sum((line.unit_cost * line.quantity for line in body.lines), start=Decimal("0"))

    entry_id = uuid4()
    number = await repository.next_counter(db, company_id=company_id, prefix="INV_ENTRY")
    item_origin = "supplier" if body.origin_type == "purchase" else "other"

    # La entrada se inserta ANTES que sus líneas (FK inventory_entry_line ->
    # inventory_entry); total_cost ya está calculado arriba.
    await repository.insert_entry(
        db,
        entry_id=entry_id,
        company_id=company_id,
        number=number,
        origin_type=body.origin_type,
        supplier_id=body.supplier_id,
        supplier_invoice=body.supplier_invoice,
        contract_id=None,
        total_cost=total_cost,
        notes=body.notes,
        registered_by=registered_by,
    )

    item_ids: list[UUID] = []
    for line in body.lines:
        await _validate_category_chain(
            db,
            company_id=company_id,
            cat1_id=line.cat1_id,
            cat2_id=line.cat2_id,
            cat3_id=line.cat3_id,
        )
        item_id = uuid4()
        await repository.insert_item(
            db,
            item_id=item_id,
            company_id=company_id,
            name=line.name,
            cat1_id=line.cat1_id,
            cat2_id=line.cat2_id,
            cat3_id=line.cat3_id,
            description=line.description,
            origin=item_origin,
            supplier_id=body.supplier_id,
            source_contract_id=None,
            cost=line.unit_cost,
            quantity=line.quantity,
            photos=line.photos,
            created_by=registered_by,
        )
        await repository.insert_entry_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            entry_id=entry_id,
            item_id=item_id,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
        )
        item_ids.append(item_id)

    return await get_entry(db, company_id=company_id, entry_id=entry_id)


async def get_entry(db: AsyncSession, *, company_id: UUID, entry_id: UUID) -> EntryOut:
    row = await repository.get_entry(db, company_id=company_id, entry_id=entry_id)
    if row is None:
        raise NotFoundError("El ingreso no existe en esta empresa.")
    item_rows = await repository.list_items_for_entry(db, company_id=company_id, entry_id=entry_id)
    return _row_to_entry(row, [_row_to_item(r) for r in item_rows])


async def list_entries(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[EntryOut]:
    rows = await repository.list_entries(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    out = []
    for row in page.items:
        item_rows = await repository.list_items_for_entry(
            db, company_id=company_id, entry_id=row._mapping["id"]
        )
        out.append(_row_to_entry(row, [_row_to_item(r) for r in item_rows]))
    return CursorPage(items=out, next_cursor=page.next_cursor)


async def create_exit(
    db: AsyncSession, *, company_id: UUID, body: ExitCreateIn, registered_by: UUID
) -> ExitOut:
    items = []
    for line in body.lines:
        item = await repository.get_item(db, company_id=company_id, item_id=line.item_id)
        if item is None:
            raise NotFoundError(
                "Un artículo del egreso no existe en esta empresa.",
                details={"item_id": str(line.item_id)},
            )
        if item._mapping["quantity"] < line.quantity:
            raise AppError(
                "No hay suficiente cantidad disponible para el egreso.",
                details={"item_id": str(line.item_id), "available": item._mapping["quantity"]},
            )
        items.append((item, line.quantity))

    exit_id = uuid4()
    number = await repository.next_counter(db, company_id=company_id, prefix="INV_EXIT")
    await repository.insert_exit(
        db,
        exit_id=exit_id,
        company_id=company_id,
        number=number,
        exit_type=body.exit_type,
        reason=body.reason,
        registered_by=registered_by,
    )
    for item, quantity in items:
        item_id = item._mapping["id"]
        remaining = item._mapping["quantity"] - quantity
        await repository.insert_exit_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            exit_id=exit_id,
            item_id=item_id,
            quantity=quantity,
        )
        await repository.adjust_item_quantity(
            db,
            company_id=company_id,
            item_id=item_id,
            delta=-quantity,
            new_status="written_off" if remaining <= 0 else None,
        )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=registered_by,
        module="inventory",
        action="create_exit",
        entity_type="inventory_exit",
        entity_id=exit_id,
        after={"exit_type": body.exit_type, "reason": body.reason},
    )

    row = await repository.get_exit(db, company_id=company_id, exit_id=exit_id)
    assert row is not None
    return _row_to_exit(row)


async def list_exits(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[ExitOut]:
    rows = await repository.list_exits(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_exit(r) for r in page.items], next_cursor=page.next_cursor)


async def list_items(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    status_filter: str | None,
) -> CursorPage[ItemOut]:
    rows = await repository.list_items(
        db, company_id=company_id, cursor=cursor, limit=limit, status_filter=status_filter
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_item(r) for r in page.items], next_cursor=page.next_cursor)


async def get_item(db: AsyncSession, *, company_id: UUID, item_id: UUID) -> ItemOut:
    row = await repository.get_item(db, company_id=company_id, item_id=item_id)
    if row is None:
        raise NotFoundError("El artículo no existe en esta empresa.")
    return _row_to_item(row)


async def update_item(
    db: AsyncSession, *, company_id: UUID, item_id: UUID, body: ItemUpdateIn
) -> ItemOut:
    row = await repository.get_item(db, company_id=company_id, item_id=item_id)
    if row is None:
        raise NotFoundError("El artículo no existe en esta empresa.")
    if row._mapping["status"] != "draft":
        raise ConflictError("Solo se puede editar un artículo mientras está en borrador.")
    fields = body.model_dump(exclude_unset=True)
    if fields:
        await repository.update_item_fields(
            db, company_id=company_id, item_id=item_id, fields=fields
        )
    return await get_item(db, company_id=company_id, item_id=item_id)


async def publish_item(
    db: AsyncSession, *, company_id: UUID, item_id: UUID, body: ItemPublishIn
) -> ItemOut:
    row = await repository.get_item(db, company_id=company_id, item_id=item_id)
    if row is None:
        raise NotFoundError("El artículo no existe en esta empresa.")
    m = row._mapping
    if m["status"] != "draft":
        raise ConflictError("El artículo ya fue publicado.")
    photos = list(m["photos"] or [])
    if not photos:
        raise AppError("El artículo necesita al menos una foto para publicarse.")

    await repository.update_item_fields(
        db, company_id=company_id, item_id=item_id, fields={"sale_price": body.sale_price}
    )

    letters = await repository.get_category_chain_letters(
        db, company_id=company_id, cat1_id=m["cat1_id"], cat2_id=m["cat2_id"], cat3_id=m["cat3_id"]
    )
    if letters is None:
        raise AppError("No se pudo resolver la letra de código de la categoría del artículo.")
    cat1_letter, cat2_letter, cat3_letter = letters

    if m["origin"] == "auction":
        suffix_letter = "R"
    elif m["supplier_id"] is not None:
        supplier = await catalogs_repo.get_supplier(
            db, company_id=company_id, supplier_id=m["supplier_id"]
        )
        if supplier is None:
            raise AppError("El proveedor del artículo ya no existe; no se puede emitir el código.")
        suffix_letter = supplier._mapping["code_letter"]
    else:
        raise AppError(
            "No se puede emitir el código: el artículo no tiene proveedor y no es de remate."
        )

    prefix = f"{cat1_letter}{cat2_letter}{cat3_letter}"
    consecutive = await repository.next_counter(db, company_id=company_id, prefix=prefix)
    code = rules.build_code(
        cat1_letter=cat1_letter,
        cat2_letter=cat2_letter,
        cat3_letter=cat3_letter,
        consecutive=consecutive,
        suffix_letter=suffix_letter,
    )

    await repository.publish_item(db, company_id=company_id, item_id=item_id, code=code)
    return await get_item(db, company_id=company_id, item_id=item_id)
