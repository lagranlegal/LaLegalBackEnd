import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

# Desde 00022 el nombre, la categoría, la descripción y el precio viven en
# `product`: el lote solo guarda lo que es propio de ESA compra. `ItemOut`
# conserva su forma —sigue exponiendo esos campos— pero salen del JOIN, así
# que ningún consumidor tuvo que cambiar por la contracción.
_ITEM_COLUMNS = (
    "i.id, i.code, p.name, p.cat1_id, p.cat2_id, p.cat3_id, p.description, "
    "i.origin, i.supplier_id, i.source_contract_id, i.cost, p.sale_price, "
    "i.quantity, i.status, i.photos, i.entry_date, i.product_id, i.lot_number, "
    "i.created_at"
)
# Los filtros de categoría apuntan a `product` (ahí viven ahora); el de
# proveedor sigue en el lote, que es de quien se compró ESA vez.
_ITEM_FILTER_TABLE = {"cat1_id": "p", "cat2_id": "p", "cat3_id": "p", "supplier_id": "i"}
_ITEM_FROM = (
    "from public.inventory_item i "
    "join public.product p on p.id = i.product_id and p.company_id = i.company_id"
)
_ENTRY_COLUMNS = (
    "id, number, origin_type, supplier_id, supplier_invoice, contract_id, total_cost, "
    "notes, payment_method, entry_date, paid_at, created_at"
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
    product_id: UUID,
    lot_number: int,
    origin: str,
    supplier_id: UUID | None,
    source_contract_id: UUID | None,
    cost: Decimal,
    quantity: int,
    photos: list[str],
    created_by: UUID | None,
    entry_date: date | None = None,
) -> None:
    """Un lote. Desde 00022 no lleva nombre ni categoría ni precio: eso es del
    producto, y por eso `product_id` es obligatorio al insertar — un lote sin
    producto no tendría cómo llamarse.

    `entry_date` viene del INGRESO. Sin esto el lote se quedaba con el
    `current_date` por defecto de 00006, así que una compra registrada con
    fecha de la semana pasada guardaba esa fecha en el ingreso y "hoy" en cada
    uno de sus lotes. La ficha del lote mostraba una fecha de entrada falsa, y
    cualquier reporte que midiera antigüedad de inventario —cuánto lleva algo
    sin venderse— contaba desde el día de la digitación en vez del día en que
    la mercancía llegó. 00020 agregó la fecha al ingreso y nunca la propagó.
    """
    await db.execute(
        text(
            """
            insert into public.inventory_item
                (id, company_id, product_id, lot_number, origin,
                 supplier_id, source_contract_id, cost, quantity, photos, created_by,
                 entry_date)
            values
                (:id, :company_id, :product_id, :lot_number, :origin,
                 :supplier_id, :source_contract_id, :cost, :quantity, cast(:photos as jsonb),
                 :created_by, coalesce(:entry_date, current_date))
            """
        ),
        {
            "id": str(item_id),
            "company_id": str(company_id),
            "product_id": str(product_id),
            "lot_number": lot_number,
            "origin": origin,
            "supplier_id": str(supplier_id) if supplier_id else None,
            "source_contract_id": str(source_contract_id) if source_contract_id else None,
            "cost": cost,
            "quantity": quantity,
            "photos": json.dumps(photos),
            "created_by": str(created_by) if created_by else None,
            "entry_date": entry_date,
        },
    )


async def get_item(db: AsyncSession, *, company_id: UUID, item_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_ITEM_COLUMNS} {_ITEM_FROM} where i.company_id = :company_id and i.id = :id"
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
    query = f"select {_ITEM_COLUMNS} {_ITEM_FROM} where i.company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if status_filter:
        query += " and i.status = :status"
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
            " and (coalesce(i.code, '') ilike :code_prefix"
            " or to_tsvector('spanish', p.name) @@ plainto_tsquery('spanish', :q))"
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
            query += f" and {_ITEM_FILTER_TABLE[column]}.{column} = :{column}"
            params[column] = str(value)
    if origin:
        query += " and i.origin = :origin"
        params["origin"] = origin
    if cursor is not None:
        query += " and i.id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by i.id limit :limit"
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
    entry_date: date | None = None,
    paid_at_now: bool = False,
) -> None:
    await db.execute(
        text(
            """
            insert into public.inventory_entry
                (id, company_id, number, origin_type, supplier_id, supplier_invoice,
                 contract_id, total_cost, notes, registered_by, payment_method,
                 idempotency_key, entry_date, paid_at)
            values
                (:id, :company_id, :number, :origin_type, :supplier_id, :supplier_invoice,
                 :contract_id, :total_cost, :notes, :registered_by, :payment_method,
                 :idempotency_key, coalesce(:entry_date, current_date),
                 case when :paid_at_now then now() else null end)
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
            "entry_date": entry_date,
            "paid_at_now": paid_at_now,
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
) -> list[Row[Any]]:
    """Ingresos, filtrables.

    `payment_status='pending'` es el filtro que faltaba y el que más se usa:
    responde "¿qué compras tengo por pagar?". El dato estaba en cada fila
    desde 00020 —y hasta hay un índice parcial para él— pero ninguna consulta
    lo ofrecía, así que la pregunta no tenía respuesta en la app.
    """
    query = f"select {_ENTRY_COLUMNS} from public.inventory_entry where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if supplier_id is not None:
        query += " and supplier_id = :supplier_id"
        params["supplier_id"] = str(supplier_id)
    if origin_type:
        query += " and origin_type = :origin_type"
        params["origin_type"] = origin_type
    if payment_status == "pending":
        # Solo una COMPRA puede estar pendiente de pago: los demás orígenes no
        # entregan plata a nadie, así que "sin pagar" no significa nada en
        # ellos y contarlos inflaría la deuda con proveedores.
        query += " and origin_type = 'purchase' and paid_at is null"
    elif payment_status == "paid":
        query += " and paid_at is not null"
    if from_date is not None:
        query += " and entry_date >= :from_date"
        params["from_date"] = from_date
    if to_date is not None:
        query += " and entry_date <= :to_date"
        params["to_date"] = to_date
    if q:
        # Número del ingreso o factura del proveedor — las dos formas en que
        # alguien busca un ingreso concreto con un papel en la mano.
        query += " and (coalesce(supplier_invoice, '') ilike :q_like or number::text = :q_exact)"
        params["q_like"] = f"%{q}%"
        params["q_exact"] = q
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
            select {_ITEM_COLUMNS} {_ITEM_FROM}
            where i.company_id = :company_id and i.id in (
                select item_id from public.inventory_entry_line
                where company_id = :company_id and entry_id = :entry_id
            )
            order by i.created_at, i.id
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
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    exit_type: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Row[Any]]:
    query = f"select {_EXIT_COLUMNS} from public.inventory_exit where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if exit_type:
        query += " and exit_type = :exit_type"
        params["exit_type"] = exit_type
    # `inventory_exit` no tiene fecha propia: se registra en el momento, así
    # que el filtro va sobre `created_at` acotado al día completo.
    if from_date is not None:
        query += " and created_at >= :from_date"
        params["from_date"] = from_date
    if to_date is not None:
        query += " and created_at < (:to_date::date + 1)"
        params["to_date"] = to_date
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


async def mark_entry_paid(
    db: AsyncSession, *, company_id: UUID, entry_id: UUID, payment_method: str
) -> None:
    """Salda una compra pendiente. El `paid_at` es AHORA, no la fecha de la
    compra: el movimiento de caja cae en la sesión abierta de hoy, que es lo
    único posible — una sesión cerrada es inmutable.
    """
    await db.execute(
        text(
            """
            update public.inventory_entry
            set payment_method = :payment_method, paid_at = now()
            where company_id = :company_id and id = :id
            """
        ),
        {"company_id": str(company_id), "id": str(entry_id), "payment_method": payment_method},
    )


# ---- Productos (00021) --------------------------------------------------

_PRODUCT_COLUMNS = (
    "id, code, name, cat1_id, cat2_id, cat3_id, description, sale_price, is_unique, "
    "active, created_at"
)


async def find_product(
    db: AsyncSession,
    *,
    company_id: UUID,
    name: str,
    cat1_id: UUID,
    cat2_id: UUID,
    cat3_id: UUID,
) -> Row[Any] | None:
    """Busca el producto por lo que lo define comercialmente: nombre +
    categoría. Case-insensitive y sin espacios de sobra, porque el nombre lo
    escribe una persona y "Cadena de oro" vs "cadena de oro " no son productos
    distintos — tratarlos así es justo lo que dispersaría el catálogo.

    Excluye los `is_unique` (piezas de remate): dos anillos rematados con el
    mismo nombre son piezas distintas y nunca deben unificarse.
    """
    result = await db.execute(
        text(
            f"""
            select {_PRODUCT_COLUMNS} from public.product
            where company_id = :company_id
              and not is_unique
              and lower(btrim(name)) = lower(btrim(:name))
              and cat1_id = :cat1_id and cat2_id = :cat2_id and cat3_id = :cat3_id
            """
        ),
        {
            "company_id": str(company_id),
            "name": name,
            "cat1_id": str(cat1_id),
            "cat2_id": str(cat2_id),
            "cat3_id": str(cat3_id),
        },
    )
    return result.first()


async def get_product(db: AsyncSession, *, company_id: UUID, product_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_PRODUCT_COLUMNS} from public.product "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(product_id)},
    )
    return result.first()


async def insert_product(
    db: AsyncSession,
    *,
    product_id: UUID,
    company_id: UUID,
    name: str,
    cat1_id: UUID,
    cat2_id: UUID,
    cat3_id: UUID,
    description: str | None,
    is_unique: bool = False,
) -> None:
    """El producto nace SIN código: el SKU se emite al publicar su primer
    lote, igual que antes se emitía el código de la pieza. Así un producto
    creado en un borrador que después se descarta no quema un consecutivo.
    """
    await db.execute(
        text(
            """
            insert into public.product
                (id, company_id, name, cat1_id, cat2_id, cat3_id, description, is_unique)
            values
                (:id, :company_id, :name, :cat1_id, :cat2_id, :cat3_id, :description, :is_unique)
            """
        ),
        {
            "id": str(product_id),
            "company_id": str(company_id),
            "name": name,
            "cat1_id": str(cat1_id),
            "cat2_id": str(cat2_id),
            "cat3_id": str(cat3_id),
            "description": description,
            "is_unique": is_unique,
        },
    )


async def set_product_code(
    db: AsyncSession, *, company_id: UUID, product_id: UUID, code: str
) -> None:
    await db.execute(
        text("update public.product set code = :code where company_id = :cid and id = :id"),
        {"cid": str(company_id), "id": str(product_id), "code": code},
    )


async def set_product_price(
    db: AsyncSession, *, company_id: UUID, product_id: UUID, sale_price: Decimal
) -> None:
    """Precio a nivel de PRODUCTO: aplica a todos sus lotes de una vez. Las
    ventas ya hechas no se ven afectadas — `sale_line` congela su propio
    `unit_price` al vender.
    """
    await db.execute(
        text("update public.product set sale_price = :price where company_id = :cid and id = :id"),
        {"cid": str(company_id), "id": str(product_id), "price": sale_price},
    )


async def next_lot_number(db: AsyncSession, *, company_id: UUID, product_id: UUID) -> int:
    """Consecutivo del lote DENTRO del producto. `coalesce(max)+1` y no un
    contador aparte: los lotes de un producto son pocos y la fila del producto
    ya está bloqueada por la transacción que lo está usando.
    """
    result = await db.execute(
        text(
            "select coalesce(max(lot_number), 0) + 1 from public.inventory_item "
            "where company_id = :cid and product_id = :pid"
        ),
        {"cid": str(company_id), "pid": str(product_id)},
    )
    return int(result.scalar_one())


async def set_item_product(
    db: AsyncSession, *, company_id: UUID, item_id: UUID, product_id: UUID, lot_number: int
) -> None:
    await db.execute(
        text(
            "update public.inventory_item set product_id = :pid, lot_number = :lot "
            "where company_id = :cid and id = :id"
        ),
        {
            "cid": str(company_id),
            "id": str(item_id),
            "pid": str(product_id),
            "lot": lot_number,
        },
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
) -> list[Row[Any]]:
    """Productos con los agregados de sus lotes — alimenta la vista agrupada.

    `available_quantity` cuenta SOLO los lotes disponibles: es el número que
    el vendedor necesita ("¿cuántas tengo para vender?"). `lot_count` y el
    rango de costos cuentan todos los lotes vivos, porque sirven para leer
    compras, no ventas.

    Los `is_unique` (piezas de remate) se excluyen por defecto: cada una es su
    propio producto de un solo lote y llenarían la lista de grupos de uno.
    """
    query = """
        select
          p.id, p.code, p.name, p.cat1_id, p.cat2_id, p.cat3_id, p.description,
          p.sale_price, p.is_unique, p.active, p.created_at,
          coalesce(count(i.id) filter (where i.status <> 'written_off'), 0) as lot_count,
          coalesce(sum(i.quantity) filter (where i.status = 'available'), 0)
            as available_quantity,
          min(i.cost) filter (where i.status <> 'written_off') as min_cost,
          max(i.cost) filter (where i.status <> 'written_off') as max_cost
        from public.product p
        left join public.inventory_item i
          on i.product_id = p.id and i.company_id = p.company_id
        where p.company_id = :company_id
    """
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if not include_unique:
        query += " and not p.is_unique"
    # La categoría es del PRODUCTO, así que se filtra por su columna directa y
    # no por la de sus lotes — un producto sin lotes vivos sigue teniendo
    # categoría y debe poder encontrarse.
    for campo, valor in (("cat1_id", cat1_id), ("cat2_id", cat2_id), ("cat3_id", cat3_id)):
        if valor is not None:
            query += f" and p.{campo} = :{campo}"
            params[campo] = str(valor)
    if supplier_id is not None:
        # Productos de los que ALGÚN lote se le compró a ese proveedor. Va
        # como EXISTS y no como join para no multiplicar filas antes del
        # group by, que falsearía los agregados de lotes.
        query += (
            " and exists (select 1 from public.inventory_item li"
            " where li.product_id = p.id and li.company_id = p.company_id"
            " and li.supplier_id = :supplier_id)"
        )
        params["supplier_id"] = str(supplier_id)
    if active is not None:
        query += " and p.active = :active"
        params["active"] = active
    if q:
        query += (
            " and (coalesce(p.code, '') ilike :code_prefix"
            " or to_tsvector('spanish', p.name) @@ plainto_tsquery('spanish', :q))"
        )
        params["q"] = q
        params["code_prefix"] = f"{q}%"
    if cursor is not None:
        query += " and p.id > :cursor"
        params["cursor"] = str(cursor)
    query += " group by p.id"
    if in_stock:
        # Va en HAVING y no en WHERE porque depende del agregado: "tengo algo
        # para vender" es una propiedad de la suma de sus lotes, no de una fila.
        query += " having coalesce(sum(i.quantity) filter (where i.status = 'available'), 0) > 0"
    query += " order by p.id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def list_lots_for_product(
    db: AsyncSession, *, company_id: UUID, product_id: UUID
) -> list[Row[Any]]:
    """Lotes de un producto, del más antiguo al más nuevo — ese es el orden en
    que conviene venderlos (FIFO) y por tanto el orden en que leerlos.
    """
    result = await db.execute(
        text(
            f"""
            select {_ITEM_COLUMNS} {_ITEM_FROM}
            where i.company_id = :company_id and i.product_id = :product_id
            order by i.lot_number, i.entry_date, i.id
            """
        ),
        {"company_id": str(company_id), "product_id": str(product_id)},
    )
    return list(result.all())


async def update_product_fields(
    db: AsyncSession, *, company_id: UUID, product_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `ProductUpdateIn.model_dump(exclude_unset=True)` —
    claves fijas y conocidas, nunca texto del usuario como nombre de columna.
    """
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "company_id": str(company_id), "id": str(product_id)}
    await db.execute(
        text(
            f"update public.product set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )


async def product_purchases(
    db: AsyncSession, *, company_id: UUID, product_id: UUID
) -> list[Row[Any]]:
    """Historial de compras de un producto, de la más reciente a la más vieja.

    Sale de `inventory_entry_line` y no de `inventory_item`: la línea guarda el
    `unit_cost` de ESA compra, que es el dato que interesa comparar. Se listan
    todos los orígenes —no solo `purchase`— porque un inventario inicial o un
    sobrante también explican de dónde salió el stock; el `supplier_name` en
    `null` los distingue.
    """
    result = await db.execute(
        text(
            """
            select
              e.id as entry_id, e.number as entry_number, e.entry_date,
              e.supplier_id, s.name as supplier_name, e.paid_at,
              l.quantity, l.unit_cost,
              (l.unit_cost * l.quantity) as total_cost,
              i.code as lot_code
            from public.inventory_entry_line l
            join public.inventory_entry e
              on e.id = l.entry_id and e.company_id = l.company_id
            join public.inventory_item i
              on i.id = l.item_id and i.company_id = l.company_id
            left join public.supplier s
              on s.id = e.supplier_id and s.company_id = e.company_id
            where l.company_id = :cid and i.product_id = :pid
            order by e.entry_date desc, e.number desc
            """
        ),
        {"cid": str(company_id), "pid": str(product_id)},
    )
    return list(result.all())
