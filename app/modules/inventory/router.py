from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.idempotency import require_idempotency_key
from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.inventory import service
from app.modules.inventory.schemas import (
    EntryCreateIn,
    EntryOut,
    EntryPayIn,
    ExitCreateIn,
    ExitOut,
    ItemOut,
    ItemPublishIn,
    ItemUpdateIn,
    KardexOut,
    ProductOut,
    ProductPurchaseOut,
    ProductUpdateIn,
    TransformationCreateIn,
    TransformationOut,
    TransformationSummaryOut,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

_view = require_permission("inventory.view")
_create = require_permission("inventory.create")
_exit_perm = require_permission("inventory.exit")
# Transformar DESTRUYE inventario de forma irreversible —de una barra de oro
# no salen las tres cadenas otra vez— así que va aparte de `create` y de
# `exit`, mismo criterio que `accounts.transfer` e `inventory.pay_purchase`.
_transform = require_permission("inventory.transform")
# Pagarle a un proveedor NO es administrar inventario: la mercancía ya entró,
# lo que cambia es el efectivo y la deuda. Va aparte de `inventory.create`
# (00035) por el mismo criterio que separó `accounts.settle` y
# `accounts.transfer` — una acción que mueve plata lleva su propio permiso,
# aunque viva en la pantalla de otro módulo.
_pay_purchase = require_permission("inventory.pay_purchase")


@router.post("/entries", response_model=EntryOut, status_code=201)
async def create_entry(
    body: EntryCreateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> EntryOut:
    return await service.create_entry(
        db,
        company_id=user.company_id,
        body=body,
        registered_by=user.id,
        idempotency_key=idempotency_key,
    )


@router.post("/entries/{entry_id}/pay", response_model=EntryOut)
async def pay_entry(
    entry_id: UUID,
    body: EntryPayIn,
    user: Annotated[CurrentUser, Depends(_pay_purchase)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> EntryOut:
    """Salda una compra registrada como pendiente de pago.

    El egreso cae en la sesión de caja abierta de HOY, no en la fecha de la
    compra: una sesión cerrada es inmutable y meterle un movimiento
    invalidaría un acta ya cuadrada. Una compra puede tener `entry_date` de la
    semana pasada y su pago aparecer en el cierre de hoy — la mercancía entró
    entonces, la plata sale ahora.
    """
    return await service.pay_entry(
        db, company_id=user.company_id, entry_id=entry_id, body=body, registered_by=user.id
    )


@router.get("/entries", response_model=CursorPage[EntryOut])
async def list_entries(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    supplier_id: Annotated[UUID | None, Query()] = None,
    origin_type: Annotated[
        str | None, Query(description="purchase | initial_stock | adjustment_in | other | auction")
    ] = None,
    payment_status: Annotated[
        str | None,
        Query(description="pending (compras por pagar) | paid"),
    ] = None,
    from_date: Annotated[date | None, Query(description="Sobre `entry_date`, inclusivo.")] = None,
    to_date: Annotated[date | None, Query(description="Sobre `entry_date`, inclusivo.")] = None,
    q: Annotated[
        str | None, Query(description="Número del ingreso o factura del proveedor.")
    ] = None,
) -> CursorPage[EntryOut]:
    """`payment_status=pending` responde "¿qué compras tengo por pagar?".

    El dato estaba en cada fila desde 00020 —y hasta con índice parcial— pero
    ninguna consulta lo ofrecía, así que la pregunta no tenía respuesta en la
    app aunque la respuesta estuviera guardada.
    """
    return await service.list_entries(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        supplier_id=supplier_id,
        origin_type=origin_type,
        payment_status=payment_status,
        from_date=from_date,
        to_date=to_date,
        q=q,
    )


@router.get("/entries/{entry_id}", response_model=EntryOut)
async def get_entry(
    entry_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> EntryOut:
    return await service.get_entry(db, company_id=user.company_id, entry_id=entry_id)


@router.post("/exits", response_model=ExitOut, status_code=201)
async def create_exit(
    body: ExitCreateIn,
    user: Annotated[CurrentUser, Depends(_exit_perm)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ExitOut:
    return await service.create_exit(
        db, company_id=user.company_id, body=body, registered_by=user.id
    )


@router.get("/exits", response_model=CursorPage[ExitOut])
async def list_exits(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    exit_type: Annotated[
        str | None,
        Query(description="adjustment | damage | loss | supplier_return | internal_use"),
    ] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> CursorPage[ExitOut]:
    return await service.list_exits(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        exit_type=exit_type,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/items", response_model=CursorPage[ItemOut])
async def list_items(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    q: Annotated[
        str | None,
        Query(description="Código (prefijo, sin mayúsculas) o nombre (full-text español)."),
    ] = None,
    cat1_id: Annotated[UUID | None, Query()] = None,
    cat2_id: Annotated[UUID | None, Query()] = None,
    cat3_id: Annotated[UUID | None, Query()] = None,
    supplier_id: Annotated[UUID | None, Query()] = None,
    origin: Annotated[str | None, Query(description="supplier | auction | other")] = None,
) -> CursorPage[ItemOut]:
    return await service.list_items(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        status_filter=status,
        q=q,
        cat1_id=cat1_id,
        cat2_id=cat2_id,
        cat3_id=cat3_id,
        supplier_id=supplier_id,
        origin=origin,
    )


@router.get("/items/{item_id}", response_model=ItemOut)
async def get_item(
    item_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ItemOut:
    return await service.get_item(db, company_id=user.company_id, item_id=item_id)


@router.patch("/items/{item_id}", response_model=ItemOut)
async def update_item(
    item_id: UUID,
    body: ItemUpdateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ItemOut:
    return await service.update_item(db, company_id=user.company_id, item_id=item_id, body=body)


@router.post("/items/{item_id}/publish", response_model=ItemOut)
async def publish_item(
    item_id: UUID,
    body: ItemPublishIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ItemOut:
    return await service.publish_item(db, company_id=user.company_id, item_id=item_id, body=body)


# ---- Productos (00021) --------------------------------------------------


@router.get("/products", response_model=CursorPage[ProductOut])
async def list_products(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    q: Annotated[
        str | None, Query(description="SKU (prefijo) o nombre (full-text español).")
    ] = None,
    include_unique: Annotated[
        bool, Query(description="Incluir piezas de remate, que son productos de un solo lote.")
    ] = False,
    cat1_id: Annotated[UUID | None, Query()] = None,
    cat2_id: Annotated[UUID | None, Query()] = None,
    cat3_id: Annotated[UUID | None, Query()] = None,
    supplier_id: Annotated[
        UUID | None, Query(description="Productos con al menos un lote de ese proveedor.")
    ] = None,
    in_stock: Annotated[bool, Query(description="Solo lo que tiene unidades disponibles.")] = False,
    active: Annotated[bool | None, Query()] = None,
) -> CursorPage[ProductOut]:
    """Inventario agrupado por producto, con el resumen de sus lotes.

    Es la vista que responde "¿cuántas tengo para vender?" sin que el usuario
    tenga que sumar lotes mentalmente. El detalle por lote —con su costo y su
    proveedor— sale de `GET /products/{id}/lots`.
    """
    return await service.list_products(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        q=q,
        include_unique=include_unique,
        cat1_id=cat1_id,
        cat2_id=cat2_id,
        cat3_id=cat3_id,
        supplier_id=supplier_id,
        in_stock=in_stock,
        active=active,
    )


@router.get("/products/{product_id}/lots", response_model=list[ItemOut])
async def list_product_lots(
    product_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[ItemOut]:
    """Lotes de un producto, del más antiguo al más nuevo — que es el orden en
    que conviene venderlos (FIFO)."""
    return await service.list_product_lots(db, company_id=user.company_id, product_id=product_id)


@router.patch("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: UUID,
    body: ProductUpdateIn,
    user: Annotated[CurrentUser, Depends(_create)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> ProductOut:
    """Cambiar el precio acá lo cambia para TODOS los lotes de una vez — antes
    había que editar cada lote por separado, con el riesgo real de dejar uno
    barato por olvido. Las ventas ya hechas no se ven afectadas.
    """
    return await service.update_product(
        db, company_id=user.company_id, product_id=product_id, body=body
    )


@router.get("/products/{product_id}/kardex", response_model=KardexOut)
async def get_product_kardex(
    product_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    from_date: Annotated[
        date | None, Query(description="Inclusivo. Por defecto, desde el primer movimiento.")
    ] = None,
    to_date: Annotated[date | None, Query(description="Inclusivo. Por defecto, hoy.")] = None,
) -> KardexOut:
    """**Kardex**: el libro auxiliar de inventario de un producto — su historia
    completa en una sola línea de tiempo, con saldo de unidades y de costo
    corriendo.

    El dato existía; la pregunta no. Los movimientos viven en **tres tablas de
    líneas** (`inventory_entry_line`, `inventory_exit_line`, `sale_line`) que
    se consultan **hacia adelante**: dado un ingreso, qué artículos trajo.
    *"¿Qué pasó con este producto?"* es la dirección contraria, y no la
    respondía nadie.

    Reúne cuatro clases de movimiento, y **una de ellas no existe como fila**:
    anular una venta repone el stock pero no escribe ninguna línea inversa
    —solo cambia el estado de la venta—, así que se sintetiza. Sin eso el
    kardex mostraría una salida que nunca vuelve y su saldo no cuadraría contra
    el stock real.

    **La valoración es POR LOTE, nunca promediada** (identificación específica,
    NIIF). Dos lotes del mismo producto comprados a precios distintos salen
    cada uno con el suyo — por eso `running_value` **no** se puede derivar de
    `running_quantity`: es la suma de lo que costó lo que queda.

    Sin `from_date` devuelve la historia entera. Es a propósito y es lo
    contrario del extracto de una cuenta, que arranca en los últimos 30 días:
    ahí se busca conciliar el mes, acá se busca de dónde salió el saldo. El
    saldo se acumula **desde el primer movimiento**; lo anterior al rango se
    comprime en `opening_quantity`/`opening_value`.
    """
    return await service.get_product_kardex(
        db,
        company_id=user.company_id,
        product_id=product_id,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/products/{product_id}/purchases", response_model=list[ProductPurchaseOut])
async def list_product_purchases(
    product_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[ProductPurchaseOut]:
    """Historial de compras de este producto: cuándo, a quién y a cuánto.

    Responde "¿cómo se movió el costo?" y "¿a quién conviene comprarle?". La
    lista de productos ya insinuaba esto con el RANGO de costos entre lotes,
    pero no dejaba abrirlo: se veía que el costo se movió y no por qué.
    """
    return await service.list_product_purchases(
        db, company_id=user.company_id, product_id=product_id
    )


@router.post("/transformations", response_model=TransformationOut, status_code=201)
async def create_transformation(
    body: TransformationCreateIn,
    user: Annotated[CurrentUser, Depends(_transform)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> TransformationOut:
    """Fundir, despiezar o armar: entran N artículos, salen M y **el costo viaja**.

    Una sola operación para lo que en la práctica son varios usos —fundir
    prendas rematadas en oro, despiezar un equipo dañado, armar un combo— y
    lo que pase DESPUÉS con lo que sale es inventario común y corriente.

    **El costo no se digita.** Lo que costó lo que entra es lo que cuesta lo
    que sale, más `extra_cost` (lo que cobró el fundidor o el técnico, que se
    **capitaliza**: es parte de producir el activo, no un gasto del mes).

    **La merma se absorbe sola:** si entran 34 g de prendas y salen 31,2 g de
    oro, el mismo costo se reparte entre menos gramos y el costo unitario
    sube. Ese número es el que dice si la operación convenía.

    Genera un egreso (`transformation`) por lo consumido y un ingreso
    (`transformation`) por lo producido, vinculados por el documento — así el
    stock se mueve por los caminos de siempre y la trazabilidad sobrevive:
    contrato → remate → artículo → transformación → lote nuevo.

    Es **irreversible**: de una barra de oro no salen las tres cadenas otra vez.
    """
    return await service.create_transformation(
        db,
        company_id=user.company_id,
        body=body,
        registered_by=user.id,
        idempotency_key=idempotency_key,
    )


@router.get("/transformations", response_model=CursorPage[TransformationSummaryOut])
async def list_transformations(
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> CursorPage[TransformationSummaryOut]:
    """Historial de transformaciones — de la más reciente a la más vieja.

    Fundir es la única operación donde **desaparece mercancía identificada y
    aparece otra distinta**. Una venta deja comprobante y un remate deja
    contrato; hasta acá, fundir no dejaba nada que se pudiera consultar, así
    que la pregunta *"¿de dónde salieron estos gramos de oro?"* no tenía
    respuesta dentro de la aplicación.

    Importa por tres razones que no son técnicas:

    · **Legal** — ese oro puede venir de la prenda de un cliente. Ante un
      reclamo, la cadena tiene que poder recorrerse hacia atrás.
    · **Contable** — el costo de lo producido salió de repartir el de lo
      consumido. Un costo sin forma de auditar su origen es un número sin
      respaldo, y es el que determina la utilidad de la venta.
    · **Operativa** — entraron 34 g de prendas y salieron 31,2 g de oro. Esa
      merma es información, y sin historial se perdía.

    Basta `inventory.view`: es leer, no transformar.
    """
    return await service.list_transformations(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/transformations/{transformation_id}", response_model=TransformationOut)
async def get_transformation(
    transformation_id: UUID,
    user: Annotated[CurrentUser, Depends(_view)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> TransformationOut:
    return await service.get_transformation(
        db, company_id=user.company_id, transformation_id=transformation_id
    )
