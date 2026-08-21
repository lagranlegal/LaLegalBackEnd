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
    ProductOut,
    ProductUpdateIn,
)

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])

_view = require_permission("inventory.view")
_create = require_permission("inventory.create")
_exit_perm = require_permission("inventory.exit")


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
    user: Annotated[CurrentUser, Depends(_create)],
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
