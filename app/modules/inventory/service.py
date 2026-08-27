from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.money import quantize
from app.common.pagination import CursorPage, make_page
from app.core.errors import AppError, ConflictError, NotFoundError
from app.modules.cashbox import integration as cashbox_integration
from app.modules.catalogs import repository as catalogs_repo
from app.modules.identity import repository as identity_repo
from app.modules.inventory import repository, rules, units
from app.modules.inventory.schemas import (
    EntryCreateIn,
    EntryOut,
    EntryPayIn,
    ExitCreateIn,
    ExitOut,
    ItemOut,
    ItemPublishIn,
    ItemUpdateIn,
    KardexLineOut,
    KardexOut,
    ProductOut,
    ProductPurchaseOut,
    ProductUpdateIn,
    TransformationCreateIn,
    TransformationOut,
    TransformationSummaryOut,
)
from app.modules.inventory.units import UNIT_ABBREVIATIONS
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
        source_transformation_id=m["source_transformation_id"],
        source_return_id=m["source_return_id"],
        cost=m["cost"],
        sale_price=m["sale_price"],
        quantity=m["quantity"],
        unit=m["unit"],
        unit_abbr=UNIT_ABBREVIATIONS.get(m["unit"], m["unit"]),
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
    unit: str = "unit",
) -> tuple[UUID, str]:
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
            # La unidad del producto EXISTENTE manda: cambiarla desde una
            # compra reinterpretaría todo su stock anterior sin avisar.
            return UUID(str(existing._mapping["id"])), str(existing._mapping["unit"])

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
        unit=unit,
    )
    return product_id, unit


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

    # "Otro" es un cajón de sastre y por eso exige explicarse. Los demás
    # orígenes ya dicen qué son en su propio nombre; este no dice nada, y sin
    # motivo no hay forma de saber después de dónde salió esa mercancía —
    # que es justamente lo que 00033 vino a arreglar.
    if body.origin_type == "other" and not (body.notes and body.notes.strip()):
        raise AppError(
            "Un ingreso de tipo 'Otro' necesita una nota que explique de dónde "
            "salió la mercancía. Si es lo que ya tenías al empezar, usa "
            "'Inventario inicial'; si sobró en un conteo, usa 'Sobrante de conteo'.",
            details={"field": "notes"},
        )

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
        # cajón abierto, pero pagar por transferencia no. `direction='out'`
        # descarta las cuentas por cobrar: a un proveedor no se le paga con
        # Sistecrédito.
        resolved = await cashbox_integration.resolve_account_for_movement(
            db,
            company_id=company_id,
            payment_method=body.payment_method,
            account_id=body.account_id,
            direction="out",
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
        product_id, unidad = await _resolve_product(
            db,
            company_id=company_id,
            name=line.name,
            cat1_id=line.cat1_id,
            cat2_id=line.cat2_id,
            cat3_id=line.cat3_id,
            description=line.description,
            unit=line.unit,
        )

        # Media cadena no existe. Si el producto se mide en unidades, una
        # cantidad fraccionaria es un error de digitación —una coma donde iba
        # un punto, típicamente— y registrarlo dejaría un stock imposible que
        # nadie va a notar hasta que el conteo físico no cuadre.
        if not units.is_valid_quantity(unidad, line.quantity):
            raise AppError(
                f"«{line.name}» se mide en {UNIT_ABBREVIATIONS.get(unidad, unidad)} y no admite "
                "cantidades fraccionarias.",
                details={"quantity": str(line.quantity), "unit": unidad},
            )
        lot_number = await repository.next_lot_number(
            db, company_id=company_id, product_id=product_id
        )

        # Las fotos que se suben en una compra son del PRODUCTO, no del lote
        # (00034): describen qué es la cosa, no esta compra en particular. Así
        # se toman una vez y todos los lotes las heredan — reponer deja de
        # obligar a re-fotografiar lo mismo, que era la queja concreta.
        #
        # El lote conserva su propia columna para lo que sí es suyo (una tara,
        # el estado de una pieza rematada) y se edita desde el diálogo del
        # lote; por eso acá se inserta vacío y no duplicado.
        if line.photos:
            await repository.update_product_fields(
                db,
                company_id=company_id,
                product_id=product_id,
                fields={"photos": line.photos},
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
            photos=[],
            created_by=registered_by,
            # La fecha del INGRESO, no la de hoy: una compra cargada con fecha
            # de la semana pasada tiene que decir que entró la semana pasada.
            entry_date=entry_date,
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

        # PUBLICACIÓN AUTOMÁTICA: si la línea ya trae todo lo que se necesita
        # para vender —precio y al menos una foto— el lote se publica en el
        # acto, emite su código y queda `available`.
        #
        # POR QUÉ: antes TODA compra nacía en borrador, sin importar qué tan
        # completa viniera, y había que volver artículo por artículo a
        # terminarla desde otra pantalla. El borrador dejaba de significar
        # "le falta algo" y pasaba a ser el estado normal — con el efecto de
        # que un artículo realmente incompleto se volvía invisible: no está en
        # la vitrina y nadie se entera.
        #
        # Ahora el borrador vuelve a ser la excepción, y significa lo que
        # debería: a esto le falta precio, o le falta foto.
        #
        # El precio puede venir en la línea o ya estar en el producto (reponer
        # algo que ya se vendía no debería obligar a redigitarlo).
        precio = line.sale_price
        if precio is None:
            producto = await repository.get_product(
                db, company_id=company_id, product_id=product_id
            )
            if producto is not None:
                precio = producto._mapping["sale_price"]

        # Ya no exige foto: desde 00034 solo las piezas ÚNICAS la necesitan, y
        # un ingreso nunca crea productos únicos (eso solo lo hace el remate).
        # Basta con el precio para que el lote nazca vendible.
        if precio is not None and precio > 0:
            await publish_item(
                db,
                company_id=company_id,
                item_id=item_id,
                body=ItemPublishIn(sale_price=precio),
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
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    supplier_id: UUID | None = None,
    origin_type: str | None = None,
    payment_status: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    q: str | None = None,
) -> CursorPage[EntryOut]:
    rows = await repository.list_entries(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        supplier_id=supplier_id,
        origin_type=origin_type,
        payment_status=payment_status,
        from_date=from_date,
        to_date=to_date,
        q=q.strip() or None if q else None,
    )
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
                details={"item_id": str(line.item_id), "available": str(item._mapping["quantity"])},
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
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    exit_type: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> CursorPage[ExitOut]:
    rows = await repository.list_exits(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        exit_type=exit_type,
        from_date=from_date,
        to_date=to_date,
    )
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
    ids: list[UUID] | None = None,
) -> CursorPage[ItemOut]:
    rows = await repository.list_items(
        db,
        company_id=company_id,
        cursor=cursor,
        # Una lista de ids concreta puede traer más artículos que el límite
        # por defecto (una venta de más de 50 líneas es rara, pero no
        # imposible) — nunca menos de lo que se pidió.
        limit=max(limit, len(ids)) if ids is not None else limit,
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
        ids=ids,
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
    elif m["source_transformation_id"] is not None:
        # `T` de transformado: lo produjimos acá fundiendo, despiezando o
        # armando (00037). No lo compramos ni lo rematamos — nació de otras
        # piezas que dejaron de existir.
        #
        # Hasta 00039 esto caía en la `P` de abajo, así que una etiqueta no
        # distinguía un lote de oro fundido de mercancía que ya estaba el día
        # que la compraventa empezó a usar el sistema. Dos cosas con costo,
        # origen y respaldo documental completamente distintos bajo la misma
        # letra: la etiqueta decía menos de lo que el sistema sabía.
        suffix_letter = "T"
    elif m["source_return_id"] is not None:
        # `D` de devuelto por cliente (00044): lo produjo el reingreso de una
        # devolución cuyo lote original ya no era reabrible (se transformó o
        # se dio de baja después de la venta). No lo compramos, no lo
        # rematamos y no lo produjimos transformando otra cosa — volvió.
        suffix_letter = "D"
    else:
        # Mercancía sin documento de origen externo NI proceso propio: el
        # inventario inicial de la empresa o un sobrante de conteo (00033).
        # Antes esto era un error duro, y con los tipos nuevos se volvió un
        # callejón sin salida: la mercancía que la compraventa ya tenía en la
        # vitrina al arrancar con el sistema entraba y quedaba atrapada en
        # borrador PARA SIEMPRE, sin código y sin poder venderse. O sea que el
        # tipo creado justamente para poder cargarla no servía para nada.
        #
        # `P` de "propio", con la misma lógica que la `R` de remate: la letra
        # dice de dónde salió la pieza.
        suffix_letter = "P"

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

    # LA FOTO SOLO ES OBLIGATORIA EN PIEZAS ÚNICAS (00034).
    #
    # Antes se exigía para todo artículo. La regla venía del spec original,
    # donde la frase estaba escrita pensando en el REMATE — y ahí sí tiene una
    # razón fuerte: la foto es evidencia de qué prenda dejó el cliente en
    # garantía, y en joyería el cliente no compra "una cadena", compra ESA
    # cadena. Un remate crea siempre un producto `is_unique`.
    #
    # Para mercancía fungible —cincuenta fundas iguales compradas por
    # docenas— era fricción sin beneficio: obligaba a fotografiar en cada
    # reposición algo que ya estaba fotografiado. `m["photos"]` son las fotos
    # EFECTIVAS (las del lote, o las del producto si el lote no tiene), así
    # que basta con que el producto esté fotografiado una vez.
    if product._mapping["is_unique"] and not list(m["photos"] or []):
        raise AppError(
            "Una pieza única necesita al menos una foto para publicarse: es lo que "
            "la identifica y, si viene de un remate, la evidencia de qué prenda era.",
            details={"product_id": str(product_id)},
        )

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
        direction="out",
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
        unit=m["unit"],
        unit_abbr=UNIT_ABBREVIATIONS.get(m["unit"], m["unit"]),
        min_cost=m["min_cost"],
        max_cost=m["max_cost"],
        photos=list(m["photos"] or []),
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
    cat1_id: UUID | None = None,
    cat2_id: UUID | None = None,
    cat3_id: UUID | None = None,
    supplier_id: UUID | None = None,
    in_stock: bool = False,
    active: bool | None = None,
) -> CursorPage[ProductOut]:
    rows = await repository.list_products(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        q=q.strip() or None if q else None,
        include_unique=include_unique,
        cat1_id=cat1_id,
        cat2_id=cat2_id,
        cat3_id=cat3_id,
        supplier_id=supplier_id,
        in_stock=in_stock,
        active=active,
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
    producto = await repository.get_product(db, company_id=company_id, product_id=product_id)
    if producto is None:
        raise NotFoundError("El producto no existe en esta empresa.")

    fields = body.model_dump(exclude_unset=True)

    # LA UNIDAD NO SE CAMBIA CON STOCK REGISTRADO. Doce unidades no son doce
    # gramos: cambiarla reinterpretaría todo lo que ya existe —lotes, ventas
    # pasadas, valorización— sin que nada lo advierta, y el inventario pasaría
    # a decir algo falso con total confianza.
    #
    # Es el mismo criterio que impide cambiar el TIPO de una cuenta (00024):
    # un dato que da sentido a los hechos ya registrados no se toca después.
    nueva_unidad = fields.get("unit")
    if nueva_unidad is not None and nueva_unidad != producto._mapping["unit"]:
        if await repository.product_has_lots(db, company_id=company_id, product_id=product_id):
            raise ConflictError(
                "No se puede cambiar la unidad de un producto que ya tiene lotes: "
                "reinterpretaría el stock y las ventas ya registradas. Crea un "
                "producto nuevo con la unidad correcta.",
                details={"unit_actual": producto._mapping["unit"], "unit_nueva": nueva_unidad},
            )
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


async def list_product_purchases(
    db: AsyncSession, *, company_id: UUID, product_id: UUID
) -> list[ProductPurchaseOut]:
    """Cómo se movió el costo de este producto y a quién se le ha comprado.

    La lista de productos ya insinuaba esto mostrando el RANGO de costos entre
    lotes (`min_cost`/`max_cost`), pero no dejaba abrirlo: se veía que el costo
    se movió y no por qué ni con quién.
    """
    if await repository.get_product(db, company_id=company_id, product_id=product_id) is None:
        raise NotFoundError("El producto no existe en esta empresa.")
    rows = await repository.product_purchases(db, company_id=company_id, product_id=product_id)
    return [
        ProductPurchaseOut(
            entry_id=r._mapping["entry_id"],
            entry_number=r._mapping["entry_number"],
            entry_date=r._mapping["entry_date"],
            supplier_id=r._mapping["supplier_id"],
            supplier_name=r._mapping["supplier_name"],
            quantity=r._mapping["quantity"],
            unit_cost=r._mapping["unit_cost"],
            total_cost=r._mapping["total_cost"],
            lot_code=r._mapping["lot_code"],
            paid_at=r._mapping["paid_at"],
        )
        for r in rows
    ]


async def create_transformation(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: TransformationCreateIn,
    registered_by: UUID,
    idempotency_key: str,
) -> TransformationOut:
    """Fundir, despiezar o armar: entran N artículos, salen M, y EL COSTO VIAJA.

    Lo que costó lo que entra es lo que cuesta lo que sale, más lo que cueste
    el proceso. Ni se pierde ni se inventa — y por eso el costo de las salidas
    no se digita en ninguna parte.

    Sin esta operación, fundir tres cadenas de 575.000 obligaba a darlas de
    baja como pérdida (castiga 575.000 contra resultados, como si se hubieran
    evaporado) y meter el oro como sobrante de conteo (inventa 575.000 de la
    nada). Dos errores que se compensan en el saldo y destrozan el estado de
    resultados.

    LA MERMA SE ABSORBE SOLA: si entran 34 g y salen 31,2, los 575.000 se
    reparten entre menos gramos y el costo por gramo sube. Es exactamente la
    verdad, y ese número es el que dice si fundir convenía.

    Reusa los caminos que ya existen —un egreso para lo consumido, un ingreso
    para lo producido— en vez de inventar uno paralelo. Así el stock se mueve
    con las mismas validaciones de siempre y la trazabilidad sobrevive:
    contrato → remate → artículo → transformación → lote de oro.
    """
    existing = await repository.find_transformation_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_transformation(
            db, company_id=company_id, transformation_id=existing._mapping["id"]
        )

    # Se valida ANTES de tocar el stock. Todo esto vive en una transacción y
    # revertiría igual, pero fallar temprano deja el error donde el usuario lo
    # puede leer sin ruido de por medio.
    if body.extra_cost > 0 and body.payment_method is None:
        raise AppError(
            "Si el proceso tuvo un costo, hay que decir de dónde salió esa plata: "
            "si no, el costo del inventario sube sin que nadie haya pagado nada.",
            details={"field": "payment_method"},
        )

    today = await platform_integration.get_company_today(db, company_id=company_id)
    transform_date = body.transform_date or today
    if transform_date > today:
        raise AppError(
            "`transform_date` no puede ser una fecha futura.",
            details={"transform_date": str(transform_date), "today": str(today)},
        )

    # --- Lo que se consume, y CUÁNTO COSTÓ ------------------------------
    consumidos: list[tuple[Row[Any], Decimal]] = []
    costo_consumido = Decimal("0")
    for entrada in body.inputs:
        item = await repository.get_item(db, company_id=company_id, item_id=entrada.item_id)
        if item is None:
            raise NotFoundError(
                "Un artículo a transformar no existe en esta empresa.",
                details={"item_id": str(entrada.item_id)},
            )
        m = item._mapping
        # Un BORRADOR también se funde, y de hecho es el caso más probable:
        # una prenda que nunca se molestaron en publicar porque ya sabían que
        # iba al crisol. Lo que no se puede transformar es lo que ya no está
        # —vendido o dado de baja—, porque su stock no existe.
        if m["status"] not in ("available", "draft"):
            raise AppError(
                "Solo se puede transformar un artículo que siga en inventario.",
                details={"item_id": str(entrada.item_id), "status": m["status"]},
            )
        if m["quantity"] < entrada.quantity:
            raise AppError(
                "No hay suficiente cantidad para transformar.",
                details={"item_id": str(entrada.item_id), "available": str(m["quantity"])},
            )
        if not units.is_valid_quantity(m["unit"], entrada.quantity):
            raise AppError(
                f"«{m['name']}» se mide en {UNIT_ABBREVIATIONS.get(m['unit'], m['unit'])} "
                "y no admite cantidades fraccionarias.",
                details={"quantity": str(entrada.quantity), "unit": m["unit"]},
            )
        # El costo del LOTE es por unidad, así que lo que viaja es la parte
        # proporcional a lo que se consume — transformar 2 de 5 unidades no
        # arrastra el costo de las cinco.
        costo_consumido += quantize(m["cost"] * entrada.quantity)
        consumidos.append((item, entrada.quantity))

    # Lo que cobra el tercero SE CAPITALIZA: es parte de producir el activo,
    # igual que el flete de una compra, no un gasto del período.
    costo_total = quantize(costo_consumido + body.extra_cost)

    # --- El egreso: lo consumido deja de existir ------------------------
    exit_id = uuid4()
    exit_number = await repository.next_counter(db, company_id=company_id, prefix="INV_EXIT")
    await repository.insert_exit(
        db,
        exit_id=exit_id,
        company_id=company_id,
        number=exit_number,
        exit_type="transformation",
        reason=body.reason,
        registered_by=registered_by,
    )
    for item, cantidad in consumidos:
        item_id = item._mapping["id"]
        restante = item._mapping["quantity"] - cantidad
        await repository.insert_exit_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            exit_id=exit_id,
            item_id=item_id,
            quantity=cantidad,
        )
        await repository.adjust_item_quantity(
            db,
            company_id=company_id,
            item_id=item_id,
            delta=-cantidad,
            new_status="written_off" if restante <= 0 else None,
        )

    # --- El ingreso: lo producido, con el costo heredado ----------------
    entry_id = uuid4()
    entry_number = await repository.next_counter(db, company_id=company_id, prefix="INV_ENTRY")
    await repository.insert_entry(
        db,
        entry_id=entry_id,
        company_id=company_id,
        number=entry_number,
        origin_type="transformation",
        supplier_id=None,
        supplier_invoice=None,
        contract_id=None,
        total_cost=costo_total,
        notes=body.notes,
        registered_by=registered_by,
        entry_date=transform_date,
    )

    # --- El documento, ANTES de los lotes que produce -------------------
    # Va acá y no al final (donde estaba) porque cada lote producido guarda
    # `source_transformation_id` (00039) y la llave foránea exige que la fila
    # exista. De paso el choque de `Idempotency-Key` revienta temprano, antes
    # de tocar stock — que es donde uno quiere que reviente.
    transformation_id = uuid4()
    number = await repository.next_counter(db, company_id=company_id, prefix="INV_TRANSFORM")
    await repository.insert_transformation(
        db,
        transformation_id=transformation_id,
        company_id=company_id,
        number=number,
        transform_date=transform_date,
        extra_cost=body.extra_cost,
        notes=body.notes,
        exit_id=exit_id,
        entry_id=entry_id,
        created_by=registered_by,
        idempotency_key=idempotency_key,
    )

    # El costo se reparte entre las salidas proporcional a su valor estimado —
    # el MISMO mecanismo con el que el remate reparte el saldo del contrato
    # entre las prendas. Sin estimaciones, en partes iguales.
    partes = rules.split_cost_by_appraisal(
        costo_total, [salida.estimated_value for salida in body.outputs]
    )

    for salida, parte in zip(body.outputs, partes, strict=True):
        await _validate_category_chain(
            db,
            company_id=company_id,
            cat1_id=salida.cat1_id,
            cat2_id=salida.cat2_id,
            cat3_id=salida.cat3_id,
        )
        product_id, unidad = await _resolve_product(
            db,
            company_id=company_id,
            name=salida.name,
            cat1_id=salida.cat1_id,
            cat2_id=salida.cat2_id,
            cat3_id=salida.cat3_id,
            description=salida.description,
            unit=salida.unit,
        )
        if not units.is_valid_quantity(unidad, salida.quantity):
            raise AppError(
                f"«{salida.name}» se mide en {UNIT_ABBREVIATIONS.get(unidad, unidad)} "
                "y no admite cantidades fraccionarias.",
                details={"quantity": str(salida.quantity), "unit": unidad},
            )
        if salida.photos:
            await repository.update_product_fields(
                db, company_id=company_id, product_id=product_id, fields={"photos": salida.photos}
            )

        lot_number = await repository.next_lot_number(
            db, company_id=company_id, product_id=product_id
        )
        item_id = uuid4()
        # El costo del LOTE es por unidad: la parte que le tocó dividida entre
        # lo que salió. Acá es donde la merma sube el costo unitario sin que
        # nadie tenga que calcular nada.
        costo_unitario = quantize(parte / salida.quantity) if salida.quantity > 0 else parte
        await repository.insert_item(
            db,
            item_id=item_id,
            company_id=company_id,
            product_id=product_id,
            lot_number=lot_number,
            origin="other",
            supplier_id=None,
            source_contract_id=None,
            # Lo que hace que este lote sepa de dónde salió — y, al publicarlo,
            # que su código lleve `T` y no la `P` genérica de "propio" (00039).
            source_transformation_id=transformation_id,
            cost=costo_unitario,
            quantity=salida.quantity,
            photos=[],
            created_by=registered_by,
            entry_date=transform_date,
        )
        await repository.insert_entry_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            entry_id=entry_id,
            item_id=item_id,
            quantity=salida.quantity,
            unit_cost=costo_unitario,
        )

        precio = salida.sale_price
        if precio is None:
            producto = await repository.get_product(
                db, company_id=company_id, product_id=product_id
            )
            if producto is not None:
                precio = producto._mapping["sale_price"]
        if precio is not None and precio > 0:
            await publish_item(
                db, company_id=company_id, item_id=item_id, body=ItemPublishIn(sale_price=precio)
            )

    # --- La plata del proceso, si la hubo -------------------------------
    if body.extra_cost > 0:
        assert body.payment_method is not None  # validado al entrar
        resolved = await cashbox_integration.resolve_account_for_movement(
            db,
            company_id=company_id,
            payment_method=body.payment_method,
            account_id=body.account_id,
            direction="out",
        )
        # Concepto `purchase` y no `expense`: se está comprando un SERVICIO
        # que se capitaliza en el inventario. Como gasto aparecería en el
        # estado de resultados del mes, y no es un gasto — es activo.
        await cashbox_integration.record_movement(
            db,
            session_id=resolved.session_id,
            company_id=company_id,
            module="store",
            direction="out",
            concept="purchase",
            amount=body.extra_cost,
            payment_method=body.payment_method,
            reference_type="inventory_entry",
            reference_id=entry_id,
            created_by=registered_by,
            notes=f"Costo del proceso: {body.reason}",
            account_id=resolved.account_id,
        )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=registered_by,
        module="inventory",
        action="create_transformation",
        entity_type="inventory_transformation",
        entity_id=transformation_id,
        after={
            "reason": body.reason,
            "consumidos": len(body.inputs),
            "producidos": len(body.outputs),
            "costo_total": str(costo_total),
        },
    )
    return await get_transformation(db, company_id=company_id, transformation_id=transformation_id)


async def get_transformation(
    db: AsyncSession, *, company_id: UUID, transformation_id: UUID
) -> TransformationOut:
    row = await repository.get_transformation(
        db, company_id=company_id, transformation_id=transformation_id
    )
    if row is None:
        raise NotFoundError("La transformación no existe en esta empresa.")
    m = row._mapping

    consumidos = await repository.list_items_for_exit(
        db, company_id=company_id, exit_id=m["exit_id"]
    )
    producidos = await repository.list_items_for_entry(
        db, company_id=company_id, entry_id=m["entry_id"]
    )
    entrada = await repository.get_entry(db, company_id=company_id, entry_id=m["entry_id"])

    return TransformationOut(
        id=m["id"],
        number=m["number"],
        transform_date=m["transform_date"],
        extra_cost=m["extra_cost"],
        notes=m["notes"],
        created_at=m["created_at"],
        total_cost=entrada._mapping["total_cost"] if entrada is not None else Decimal("0"),
        consumed=[_row_to_item(r) for r in consumidos],
        produced=[_row_to_item(r) for r in producidos],
    )


async def get_product_kardex(
    db: AsyncSession,
    *,
    company_id: UUID,
    product_id: UUID,
    from_date: date | None = None,
    to_date: date | None = None,
) -> KardexOut:
    """Kardex del producto: su historia completa con saldo corriendo.

    El saldo se acumula **desde el principio de los tiempos**, no desde
    `from_date`: un kardex que arrancara en cero cada vez que se cambia el
    filtro no sería un kardex, sería una lista de movimientos. Lo anterior al
    rango se comprime en `opening_quantity`/`opening_value` y lo de adentro se
    muestra línea por línea.
    """
    producto = await repository.get_product(db, company_id=company_id, product_id=product_id)
    if producto is None:
        raise NotFoundError("El producto no existe en esta empresa.")

    today = await platform_integration.get_company_today(db, company_id=company_id)
    tz = await platform_integration.get_company_timezone(db, company_id=company_id)
    hasta = to_date or today
    # Por defecto la historia ENTERA. Un kardex recortado a los últimos 30 días
    # por omisión escondería justo lo que se va a buscar: de dónde salió el
    # saldo. Es lo contrario al extracto de una cuenta, que sí arranca en los
    # últimos 30 días porque ahí lo que se busca es conciliar el mes.
    desde = from_date or date.min

    rows = await repository.get_product_kardex(
        db, company_id=company_id, product_id=product_id, tz=tz, to_date=hasta
    )

    cantidad = Decimal("0")
    valor = Decimal("0")
    entradas = Decimal("0")
    salidas = Decimal("0")
    apertura_cantidad = Decimal("0")
    apertura_valor = Decimal("0")
    lineas: list[KardexLineOut] = []

    for row in rows:
        m = row._mapping
        cantidad += m["cantidad_in"] - m["cantidad_out"]
        valor = quantize(valor + (m["cantidad_in"] - m["cantidad_out"]) * m["costo_unitario"])
        if m["fecha"] < desde:
            # Anterior al rango: se comprime en el saldo inicial y no se
            # muestra, pero SÍ cuenta — es de donde sale ese saldo.
            apertura_cantidad = cantidad
            apertura_valor = valor
            continue
        entradas += m["cantidad_in"]
        salidas += m["cantidad_out"]
        lineas.append(
            KardexLineOut(
                date=m["fecha"],
                kind=m["tipo"],
                kind_detail=m["subtipo"],
                reference_id=m["ref_id"],
                reference_number=m["ref_number"],
                detail=m["detalle"],
                item_id=m["item_id"],
                item_code=m["item_code"],
                lot_number=m["lot_number"],
                quantity_in=m["cantidad_in"],
                quantity_out=m["cantidad_out"],
                unit_cost=m["costo_unitario"],
                running_quantity=cantidad,
                running_value=valor,
            )
        )

    p = producto._mapping
    return KardexOut(
        product_id=product_id,
        name=p["name"],
        unit=p["unit"],
        unit_abbr=UNIT_ABBREVIATIONS.get(p["unit"], p["unit"]),
        # Se devuelve el rango EFECTIVO, no el pedido: sin `from_date` el
        # kardex arranca en el primer movimiento, y decir `0001-01-01` sería
        # una fecha que no significa nada para quien la lee.
        from_date=lineas[0].date if lineas else hasta,
        to_date=hasta,
        opening_quantity=apertura_cantidad,
        opening_value=apertura_valor,
        total_in=entradas,
        total_out=salidas,
        closing_quantity=cantidad,
        closing_value=valor,
        lines=lineas,
    )


async def list_transformations(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    from_date: date | None = None,
    to_date: date | None = None,
) -> CursorPage[TransformationSummaryOut]:
    rows = await repository.list_transformations(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(
        items=[
            TransformationSummaryOut(
                id=r._mapping["id"],
                number=r._mapping["number"],
                transform_date=r._mapping["transform_date"],
                reason=r._mapping["reason"],
                notes=r._mapping["notes"],
                extra_cost=r._mapping["extra_cost"],
                total_cost=r._mapping["total_cost"],
                input_count=r._mapping["input_count"],
                output_count=r._mapping["output_count"],
                input_names=r._mapping["input_names"],
                output_names=r._mapping["output_names"],
                created_by_name=r._mapping["created_by_name"],
                created_at=r._mapping["created_at"],
            )
            for r in page.items
        ],
        next_cursor=page.next_cursor,
    )
