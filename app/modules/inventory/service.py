from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import AppError, ConflictError, NotFoundError
from app.modules.cashbox import integration as cashbox_integration
from app.modules.catalogs import repository as catalogs_repo
from app.modules.identity import repository as identity_repo
from app.modules.inventory import repository, rules
from app.modules.inventory.schemas import (
    EntryCreateIn,
    EntryOut,
    EntryPayIn,
    ExitCreateIn,
    ExitOut,
    ItemOut,
    ItemPublishIn,
    ItemUpdateIn,
    ProductOut,
    ProductUpdateIn,
)
from app.modules.platform import integration as platform_integration

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
        product_id=m["product_id"],
        lot_number=m["lot_number"],
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
        payment_method=m["payment_method"],
        entry_date=m["entry_date"],
        paid_at=m["paid_at"],
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


async def _resolve_product(
    db: AsyncSession,
    *,
    company_id: UUID,
    name: str,
    cat1_id: UUID,
    cat2_id: UUID,
    cat3_id: UUID,
    description: str | None,
    is_unique: bool = False,
) -> UUID:
    """Devuelve el producto al que pertenece un lote nuevo, creándolo si es la
    primera vez que se compra.

    Reponer algo ya comprado NO crea un producto nuevo: cae en el existente y
    suma un lote. Eso es lo que hace que la lista agrupe, que el precio se
    cambie una sola vez y que se puedan comparar proveedores del mismo
    producto — los cuatro síntomas de la propuesta salen de acá.

    Las piezas de remate (`is_unique`) SIEMPRE crean producto propio: un
    anillo de un contrato no es "otro lote" de nada.
    """
    if not is_unique:
        existing = await repository.find_product(
            db,
            company_id=company_id,
            name=name,
            cat1_id=cat1_id,
            cat2_id=cat2_id,
            cat3_id=cat3_id,
        )
        if existing is not None:
            return UUID(str(existing._mapping["id"]))

    product_id = uuid4()
    await repository.insert_product(
        db,
        product_id=product_id,
        company_id=company_id,
        name=name,
        cat1_id=cat1_id,
        cat2_id=cat2_id,
        cat3_id=cat3_id,
        description=description,
        is_unique=is_unique,
    )
    return product_id


async def create_entry(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: EntryCreateIn,
    registered_by: UUID,
    idempotency_key: str,
) -> EntryOut:
    # Reintento del mismo ingreso: devuelve el que ya existe sin duplicar
    # stock ni volver a sacar plata de la caja.
    existing = await repository.find_entry_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_entry(db, company_id=company_id, entry_id=existing._mapping["id"])

    is_purchase = body.origin_type == "purchase"
    if is_purchase and body.supplier_id is None:
        raise AppError("Un ingreso de compra requiere `supplier_id`.")
    if not is_purchase and body.payment_method is not None:
        raise AppError("Solo un ingreso de compra puede llevar `payment_method`.")

    # La mercancía no puede haber entrado en el futuro. Sí puede haber entrado
    # ayer: ese es justamente el caso que esta separación viene a resolver.
    today = await platform_integration.get_company_today(db, company_id=company_id)
    entry_date = body.entry_date or today
    if entry_date > today:
        raise AppError(
            "`entry_date` no puede ser una fecha futura.",
            details={"entry_date": str(entry_date), "today": str(today)},
        )

    total_cost = sum((line.unit_cost * line.quantity for line in body.lines), start=Decimal("0"))

    # Solo se exige caja abierta si la compra se PAGA en el acto. Si nace
    # pendiente (sin `payment_method`), no toca caja: así se pueden cargar
    # facturas de días anteriores o de noche con la caja cerrada, que era
    # imposible antes. El pago se registra después con `pay_entry`.
    pay_now = is_purchase and body.payment_method is not None
    resolved = None
    if pay_now:
        # `pay_now` ya garantiza que hay medio de pago; el assert se lo dice al
        # verificador de tipos, que no puede deducirlo de la variable booleana.
        assert body.payment_method is not None
        # La sesión la exige el tipo de cuenta: pagar en efectivo necesita el
        # cajón abierto, pero pagar por transferencia no.
        resolved = await cashbox_integration.resolve_account_for_movement(
            db,
            company_id=company_id,
            payment_method=body.payment_method,
            account_id=body.account_id,
        )

    entry_id = uuid4()
    number = await repository.next_counter(db, company_id=company_id, prefix="INV_ENTRY")
    item_origin = "supplier" if is_purchase else "other"

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
        payment_method=body.payment_method if is_purchase else None,
        idempotency_key=idempotency_key,
        entry_date=entry_date,
        paid_at_now=pay_now,
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
        # El producto se resuelve ANTES del lote: desde 00022 un lote sin
        # producto no tendría ni nombre ni categoría. Si ya se compró algo
        # igual, cae en ese producto y suma un lote.
        product_id = await _resolve_product(
            db,
            company_id=company_id,
            name=line.name,
            cat1_id=line.cat1_id,
            cat2_id=line.cat2_id,
            cat3_id=line.cat3_id,
            description=line.description,
        )
        lot_number = await repository.next_lot_number(
            db, company_id=company_id, product_id=product_id
        )

        item_id = uuid4()
        await repository.insert_item(
            db,
            item_id=item_id,
            company_id=company_id,
            product_id=product_id,
            lot_number=lot_number,
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

    # El movimiento de caja va en la MISMA transacción que el ingreso y sus
    # líneas (CLAUDE.md regla 4: "una operación de negocio = UNA transacción").
    # Concepto `purchase`, que el enum `cash_concept` ya contemplaba desde
    # 00007 y hasta ahora nunca se emitía — ese era el hueco que hacía
    # descuadrar el cierre todos los días que se compraba mercancía.
    if pay_now and resolved is not None and body.payment_method is not None:
        await cashbox_integration.record_movement(
            db,
            session_id=resolved.session_id,
            company_id=company_id,
            module="store",
            direction="out",
            concept="purchase",
            amount=total_cost,
            payment_method=body.payment_method,
            reference_type="inventory_entry",
            reference_id=entry_id,
            created_by=registered_by,
            account_id=resolved.account_id,
        )

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
    q: str | None = None,
    cat1_id: UUID | None = None,
    cat2_id: UUID | None = None,
    cat3_id: UUID | None = None,
    supplier_id: UUID | None = None,
    origin: str | None = None,
) -> CursorPage[ItemOut]:
    rows = await repository.list_items(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        status_filter=status_filter,
        # Se normaliza acá y no en el repositorio: un `?q=` con solo espacios
        # llega como string no vacío y armaría un `plainto_tsquery('')` que no
        # matchea nada — el usuario vería "sin resultados" al borrar el texto.
        q=q.strip() or None if q else None,
        cat1_id=cat1_id,
        cat2_id=cat2_id,
        cat3_id=cat3_id,
        supplier_id=supplier_id,
        origin=origin,
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
    """Solo fotos. El nombre, la descripción, la categoría y el precio se
    editan en el PRODUCTO (`PATCH /products/{id}`) desde 00022: son atributos
    de qué es el artículo, no de esta compra puntual, y editarlos por lote
    permitía que dos lotes del mismo producto divergieran.
    """
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

    # El precio va SOLO al producto (más abajo). Desde 00022 el lote ya no
    # tiene columna de precio: el dato existe una sola vez.
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

    # SKU del producto: se emite al publicar su PRIMER lote, no al crearlo.
    # Así un producto que nació en un borrador descartado no quema un
    # consecutivo — misma razón por la que antes el código de la pieza se
    # emitía al publicar y no al ingresar.
    product_id = m["product_id"]
    if product_id is None:
        raise AppError("El artículo no está asociado a un producto; no se puede emitir el código.")
    product = await repository.get_product(db, company_id=company_id, product_id=product_id)
    if product is None:
        raise AppError("El producto del artículo no existe en esta empresa.")

    product_code = product._mapping["code"]
    if product_code is None:
        prefix = f"{cat1_letter}{cat2_letter}{cat3_letter}"
        consecutive = await repository.next_counter(db, company_id=company_id, prefix=prefix)
        product_code = rules.build_product_code(
            cat1_letter=cat1_letter,
            cat2_letter=cat2_letter,
            cat3_letter=cat3_letter,
            consecutive=consecutive,
        )
        await repository.set_product_code(
            db, company_id=company_id, product_id=product_id, code=product_code
        )

    # El precio va al producto: aplica a todos sus lotes de una vez, y desde
    # 00022 es el único lugar donde vive.
    await repository.set_product_price(
        db, company_id=company_id, product_id=product_id, sale_price=body.sale_price
    )

    code = rules.build_lot_code(
        product_code=product_code,
        lot_number=m["lot_number"] or 1,
        suffix_letter=suffix_letter,
    )

    await repository.publish_item(db, company_id=company_id, item_id=item_id, code=code)
    return await get_item(db, company_id=company_id, item_id=item_id)


async def pay_entry(
    db: AsyncSession,
    *,
    company_id: UUID,
    entry_id: UUID,
    body: EntryPayIn,
    registered_by: UUID,
) -> EntryOut:
    """Salda una compra que quedó pendiente de pago.

    El egreso de caja cae en la sesión abierta de HOY, no en la fecha de la
    compra: una sesión cerrada es inmutable (00007) y meterle un movimiento
    invalidaría un acta ya cuadrada e impresa. Por eso la compra puede tener
    `entry_date` de la semana pasada y su pago aparecer en el cierre de hoy —
    es lo correcto: la mercancía entró entonces, la plata sale ahora.
    """
    row = await repository.get_entry(db, company_id=company_id, entry_id=entry_id)
    if row is None:
        raise NotFoundError("El ingreso no existe en esta empresa.")
    m = row._mapping
    if m["origin_type"] != "purchase":
        raise AppError("Solo un ingreso de compra puede tener un pago asociado.")
    if m["paid_at"] is not None:
        raise ConflictError("Esta compra ya fue pagada.")

    resolved = await cashbox_integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method=body.payment_method,
        account_id=body.account_id,
    )

    await repository.mark_entry_paid(
        db, company_id=company_id, entry_id=entry_id, payment_method=body.payment_method
    )
    await cashbox_integration.record_movement(
        db,
        session_id=resolved.session_id,
        company_id=company_id,
        module="store",
        direction="out",
        concept="purchase",
        amount=m["total_cost"],
        payment_method=body.payment_method,
        reference_type="inventory_entry",
        reference_id=entry_id,
        created_by=registered_by,
        account_id=resolved.account_id,
    )
    return await get_entry(db, company_id=company_id, entry_id=entry_id)


def _row_to_product(row: Row[Any]) -> ProductOut:
    m = row._mapping
    return ProductOut(
        id=m["id"],
        code=m["code"],
        name=m["name"],
        cat1_id=m["cat1_id"],
        cat2_id=m["cat2_id"],
        cat3_id=m["cat3_id"],
        description=m["description"],
        sale_price=m["sale_price"],
        is_unique=m["is_unique"],
        active=m["active"],
        lot_count=m["lot_count"],
        available_quantity=m["available_quantity"],
        min_cost=m["min_cost"],
        max_cost=m["max_cost"],
        created_at=m["created_at"],
    )


async def list_products(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    q: str | None = None,
    include_unique: bool = False,
) -> CursorPage[ProductOut]:
    rows = await repository.list_products(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        q=q.strip() or None if q else None,
        include_unique=include_unique,
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_product(r) for r in page.items], next_cursor=page.next_cursor)


async def list_product_lots(
    db: AsyncSession, *, company_id: UUID, product_id: UUID
) -> list[ItemOut]:
    if await repository.get_product(db, company_id=company_id, product_id=product_id) is None:
        raise NotFoundError("El producto no existe en esta empresa.")
    rows = await repository.list_lots_for_product(db, company_id=company_id, product_id=product_id)
    return [_row_to_item(r) for r in rows]


async def update_product(
    db: AsyncSession, *, company_id: UUID, product_id: UUID, body: ProductUpdateIn
) -> ProductOut:
    """Cambiar el precio acá lo cambia para TODOS los lotes de una vez — que
    es el comportamiento correcto: el cliente no sabe qué lote le tocó, y dos
    piezas idénticas a precios distintos en la misma vitrina no son una
    estrategia sino un descuido.

    Las ventas ya hechas NO se ven afectadas: `sale_line` congela su propio
    `unit_price` al vender, igual que el costo.
    """
    if await repository.get_product(db, company_id=company_id, product_id=product_id) is None:
        raise NotFoundError("El producto no existe en esta empresa.")

    fields = body.model_dump(exclude_unset=True)
    await repository.update_product_fields(
        db, company_id=company_id, product_id=product_id, fields=fields
    )

    # Ya NO hay que propagar el precio a los lotes: desde 00022 el dato existe
    # una sola vez, en `product`. Esa propagación existió durante la fase 2 y
    # se fue con la columna duplicada — que era justamente el punto de
    # contraer.

    rows = await repository.list_products(
        db, company_id=company_id, cursor=None, limit=1000, include_unique=True
    )
    for row in rows:
        if row._mapping["id"] == product_id:
            return _row_to_product(row)
    raise NotFoundError("El producto no existe en esta empresa.")
