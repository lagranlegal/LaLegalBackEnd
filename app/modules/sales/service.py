from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import (
    AppError,
    CashSessionNotOpenError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import CurrentUser, has_permission
from app.modules.cashbox import integration as cashbox_integration
from app.modules.identity import repository as identity_repo
from app.modules.inventory import repository as inventory_repo
from app.modules.sales import repository
from app.modules.sales.schemas import SaleCreateIn, SaleLineOut, SaleOut


def _row_to_sale(row: Row[Any], lines: list[SaleLineOut]) -> SaleOut:
    m = row._mapping
    return SaleOut(
        id=m["id"],
        number=m["number"],
        sold_at=m["sold_at"],
        customer_id=m["customer_id"],
        discount_amount=m["discount_amount"],
        total=m["total"],
        payment_method=m["payment_method"],
        status=m["status"],
        void_reason=m["void_reason"],
        created_at=m["created_at"],
        lines=lines,
    )


def _row_to_line(row: Row[Any]) -> SaleLineOut:
    m = row._mapping
    return SaleLineOut(
        id=m["id"],
        item_id=m["item_id"],
        quantity=m["quantity"],
        unit_price=m["unit_price"],
        unit_cost=m["unit_cost"],
        subtotal=m["subtotal"],
    )


async def create_sale(
    db: AsyncSession,
    *,
    company_id: UUID,
    body: SaleCreateIn,
    user: CurrentUser,
    idempotency_key: str,
) -> SaleOut:
    existing = await repository.find_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        lines = await repository.list_sale_lines(
            db, company_id=company_id, sale_id=existing._mapping["id"]
        )
        return _row_to_sale(existing, [_row_to_line(r) for r in lines])

    items = []
    subtotal_sum = Decimal("0")
    for line in body.lines:
        item = await inventory_repo.get_item(db, company_id=company_id, item_id=line.item_id)
        if item is None:
            raise NotFoundError(
                "Un artículo de la venta no existe en esta empresa.",
                details={"item_id": str(line.item_id)},
            )
        m = item._mapping
        if m["status"] != "available":
            raise AppError(
                "El artículo no está disponible para la venta.",
                details={"item_id": str(line.item_id), "status": m["status"]},
            )
        if m["quantity"] < line.quantity:
            raise AppError(
                "No hay suficiente cantidad disponible.",
                details={"item_id": str(line.item_id), "available": m["quantity"]},
            )
        subtotal = line.unit_price * line.quantity
        subtotal_sum += subtotal
        # El costo se toma del artículo ACÁ, en el momento de vender, y se
        # congela en la línea (00019). No se lee al consultar: el costo de una
        # venta es un hecho histórico y un reporte de un período ya cerrado no
        # debe moverse si alguien corrige el costo del artículo después.
        items.append((line, subtotal, m["cost"]))

    discount_amount = body.discount_amount or Decimal("0")
    if discount_amount > 0:
        if not body.discount_reason:
            raise AppError("El descuento requiere un motivo.")
        if not await has_permission(db, user.role_id, "sales.apply_discount"):
            raise PermissionDeniedError("Falta el permiso 'sales.apply_discount'.")
        if discount_amount > subtotal_sum:
            raise AppError("El descuento no puede superar el total de la venta.")

    total = subtotal_sum - discount_amount
    if total < 0:
        raise AppError("El total de la venta no puede ser negativo.")

    # La sesión la exige el TIPO DE CUENTA, no la venta: cobrar en efectivo
    # necesita el cajón abierto, pero una venta por Sistecrédito o
    # transferencia no pasa por él. La regla vive en el resolvedor, no acá.
    resolved = await cashbox_integration.resolve_account_for_movement(
        db,
        company_id=company_id,
        payment_method=body.payment_method,
        account_id=body.account_id,
    )

    sale_id = uuid4()
    number = await repository.next_number(db, company_id=company_id)
    await repository.insert_sale(
        db,
        sale_id=sale_id,
        company_id=company_id,
        number=number,
        customer_id=body.customer_id,
        sold_by=user.id,
        discount_amount=discount_amount,
        discount_by=user.id if discount_amount > 0 else None,
        total=total,
        payment_method=body.payment_method,
        idempotency_key=idempotency_key,
    )
    for line, subtotal, unit_cost in items:
        await repository.insert_sale_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            sale_id=sale_id,
            item_id=line.item_id,
            quantity=line.quantity,
            unit_price=line.unit_price,
            unit_cost=unit_cost,
            subtotal=subtotal,
        )
        item = await inventory_repo.get_item(db, company_id=company_id, item_id=line.item_id)
        assert item is not None
        remaining = item._mapping["quantity"] - line.quantity
        await inventory_repo.adjust_item_quantity(
            db,
            company_id=company_id,
            item_id=line.item_id,
            delta=-line.quantity,
            new_status="sold" if remaining <= 0 else None,
        )

    await cashbox_integration.record_movement(
        db,
        session_id=resolved.session_id,
        company_id=company_id,
        module="store",
        direction="in",
        concept="sale",
        amount=total,
        payment_method=body.payment_method,
        reference_type="sale",
        reference_id=sale_id,
        created_by=user.id,
        account_id=resolved.account_id,
    )
    if discount_amount > 0:
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=user.id,
            module="sales",
            action="apply_sale_discount",
            entity_type="sale",
            entity_id=sale_id,
            after={
                "discount_amount": str(discount_amount),
                "discount_reason": body.discount_reason,
            },
        )

    row = await repository.get_sale(db, company_id=company_id, sale_id=sale_id)
    assert row is not None
    lines = await repository.list_sale_lines(db, company_id=company_id, sale_id=sale_id)
    return _row_to_sale(row, [_row_to_line(r) for r in lines])


async def get_sale(db: AsyncSession, *, company_id: UUID, sale_id: UUID) -> SaleOut:
    row = await repository.get_sale(db, company_id=company_id, sale_id=sale_id)
    if row is None:
        raise NotFoundError("La venta no existe en esta empresa.")
    lines = await repository.list_sale_lines(db, company_id=company_id, sale_id=sale_id)
    return _row_to_sale(row, [_row_to_line(r) for r in lines])


async def list_sales(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    customer_id: UUID | None = None,
    status_filter: str | None = None,
) -> CursorPage[SaleOut]:
    rows = await repository.list_sales(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        customer_id=customer_id,
        status_filter=status_filter,
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    out = []
    for row in page.items:
        lines = await repository.list_sale_lines(
            db, company_id=company_id, sale_id=row._mapping["id"]
        )
        out.append(_row_to_sale(row, [_row_to_line(r) for r in lines]))
    return CursorPage(items=out, next_cursor=page.next_cursor)


async def void_sale(
    db: AsyncSession, *, company_id: UUID, sale_id: UUID, reason: str, actor_id: UUID
) -> SaleOut:
    row = await repository.get_sale(db, company_id=company_id, sale_id=sale_id)
    if row is None:
        raise NotFoundError("La venta no existe en esta empresa.")
    if row._mapping["status"] != "completed":
        raise ConflictError("La venta ya está anulada.")

    session = await cashbox_integration.get_open_session(db, company_id=company_id)
    if session is None:
        raise CashSessionNotOpenError("No hay una sesión de caja abierta para anular la venta.")

    lines = await repository.list_sale_lines(db, company_id=company_id, sale_id=sale_id)
    for line in lines:
        m = line._mapping
        item = await inventory_repo.get_item(db, company_id=company_id, item_id=m["item_id"])
        assert item is not None
        await inventory_repo.adjust_item_quantity(
            db,
            company_id=company_id,
            item_id=m["item_id"],
            delta=m["quantity"],
            new_status="available" if item._mapping["status"] == "sold" else None,
        )

    await repository.void_sale(
        db, company_id=company_id, sale_id=sale_id, void_reason=reason, voided_by=actor_id
    )
    if row._mapping["total"] > 0:
        # cash_movement.amount exige > 0 — una venta 100% descontada no tuvo
        # efectivo real de por medio, así que anularla tampoco genera un
        # contra-movimiento (no hay nada que devolver).
        await cashbox_integration.record_movement(
            db,
            session_id=session._mapping["id"],
            company_id=company_id,
            module="store",
            direction="out",
            concept="sale",
            amount=row._mapping["total"],
            payment_method=row._mapping["payment_method"],
            reference_type="sale",
            reference_id=sale_id,
            created_by=actor_id,
            notes="Anulación de venta",
        )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="sales",
        action="void_sale",
        entity_type="sale",
        entity_id=sale_id,
        before={"status": "completed"},
        after={"status": "voided", "reason": reason},
    )

    return await get_sale(db, company_id=company_id, sale_id=sale_id)
