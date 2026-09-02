from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.money import quantize
from app.common.pagination import CursorPage, make_page
from app.core.errors import (
    AppError,
    CashSessionNotOpenError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app.core.security import CurrentUser, has_permission
from app.modules.accounts import integration as accounts_integration
from app.modules.cashbox import integration as cashbox_integration
from app.modules.customers import repository as customers_repo
from app.modules.identity import repository as identity_repo
from app.modules.inventory import repository as inventory_repo
from app.modules.inventory import units
from app.modules.inventory.units import UNIT_ABBREVIATIONS
from app.modules.platform import integration as platform_integration
from app.modules.sales import repository
from app.modules.sales.schemas import (
    CreditNoteOut,
    SaleCreateIn,
    SaleLineOut,
    SaleOut,
    SaleReturnCreateIn,
    SaleReturnLineOut,
    SaleReturnOut,
)


def _row_to_sale(
    row: Row[Any], lines: list[SaleLineOut], *, credit_note_redeemed_amount: Decimal | None = None
) -> SaleOut:
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
        account_id=m["account_id"],
        credit_note_redeemed_amount=credit_note_redeemed_amount,
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


async def _get_credit_note_redemption_amount(
    db: AsyncSession, *, company_id: UUID, sale_id: UUID
) -> Decimal | None:
    redemption = await repository.get_sale_credit_note_redemption(
        db, company_id=company_id, sale_id=sale_id
    )
    return Decimal(str(redemption._mapping["amount"])) if redemption is not None else None


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
        redeemed = await _get_credit_note_redemption_amount(
            db, company_id=company_id, sale_id=existing._mapping["id"]
        )
        return _row_to_sale(
            existing, [_row_to_line(r) for r in lines], credit_note_redeemed_amount=redeemed
        )

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
                details={"item_id": str(line.item_id), "available": str(m["quantity"])},
            )

        # Media cadena no se vende. Si el producto se mide en unidades, una
        # cantidad fraccionaria es un error de digitación, y acá cuesta más
        # caro que en una compra: descuenta stock imposible y cobra un total
        # que no corresponde a nada.
        if not units.is_valid_quantity(m["unit"], line.quantity):
            raise AppError(
                f"«{m['name']}» se mide en "
                f"{UNIT_ABBREVIATIONS.get(m['unit'], m['unit'])} y no admite "
                "cantidades fraccionarias.",
                details={"quantity": str(line.quantity), "unit": m["unit"]},
            )

        # `quantize` porque la cantidad ya puede tener decimales: 12,5 g a
        # 19.230 da 240.375,0 exacto, pero 0,333 kg a 1.000 daría 333,0 y
        # cualquier otra combinación puede arrastrar milésimas de peso. El
        # dinero se redondea a dos decimales ANTES de sumarse, nunca después
        # — si no, el total del recibo no cuadraría con la suma de sus líneas.
        subtotal = quantize(line.unit_price * line.quantity)
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

    # Redención de nota crédito (00043): reduce lo que hay que cobrar de
    # verdad, sin tocar `total` (el total de la venta sigue siendo el total
    # real de lo vendido — lo que cambia es CÓMO se paga, igual que elegir
    # una cuenta `settlement`).
    redeemed_amount = Decimal("0")
    credit_note_customer_id: UUID | None = None
    if body.credit_note_id is not None:
        credit_note = await repository.get_credit_note_for_update(
            db, company_id=company_id, credit_note_id=body.credit_note_id
        )
        if credit_note is None:
            raise NotFoundError("La nota crédito no existe en esta empresa.")
        credit_note_customer_id = credit_note._mapping["customer_id"]
        if body.customer_id is None or body.customer_id != credit_note_customer_id:
            raise AppError(
                "La nota crédito no es transferible: solo la puede redimir el cliente al "
                "que fue emitida.",
                details={"credit_note_id": str(body.credit_note_id)},
            )
        already_redeemed = await repository.sum_credit_note_redemptions(
            db, company_id=company_id, credit_note_id=body.credit_note_id
        )
        balance = Decimal(str(credit_note._mapping["amount"])) - already_redeemed
        redeemed_amount = (
            body.credit_note_amount if body.credit_note_amount is not None else min(balance, total)
        )
        if redeemed_amount <= 0 or redeemed_amount > balance:
            raise AppError(
                "La nota crédito no tiene saldo suficiente.",
                details={"balance": str(balance), "requested": str(redeemed_amount)},
            )
        if redeemed_amount > total:
            raise AppError("La nota crédito no puede superar el total de la venta.")

    cash_amount = total - redeemed_amount

    # La sesión la exige el TIPO DE CUENTA, no la venta: cobrar en efectivo
    # necesita el cajón abierto, pero una venta por Sistecrédito o
    # transferencia no pasa por él. La regla vive en el resolvedor, no acá.
    # Y si la nota crédito cubrió el total entero, no hay plata real de por
    # medio — mismo principio que ya aplica una venta 100% descontada.
    resolved = None
    if cash_amount > 0:
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
        account_id=resolved.account_id if resolved is not None else None,
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

    if body.credit_note_id is not None:
        await repository.insert_credit_note_redemption(
            db,
            redemption_id=uuid4(),
            company_id=company_id,
            credit_note_id=body.credit_note_id,
            sale_id=sale_id,
            amount=redeemed_amount,
            created_by=user.id,
        )
    if cash_amount > 0:
        assert resolved is not None
        await cashbox_integration.record_movement(
            db,
            session_id=resolved.session_id,
            company_id=company_id,
            module="store",
            direction="in",
            concept="sale",
            amount=cash_amount,
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
    redeemed = redeemed_amount if body.credit_note_id is not None else None
    return _row_to_sale(row, [_row_to_line(r) for r in lines], credit_note_redeemed_amount=redeemed)


async def get_sale(db: AsyncSession, *, company_id: UUID, sale_id: UUID) -> SaleOut:
    row = await repository.get_sale(db, company_id=company_id, sale_id=sale_id)
    if row is None:
        raise NotFoundError("La venta no existe en esta empresa.")
    lines = await repository.list_sale_lines(db, company_id=company_id, sale_id=sale_id)
    redeemed = await _get_credit_note_redemption_amount(db, company_id=company_id, sale_id=sale_id)
    return _row_to_sale(row, [_row_to_line(r) for r in lines], credit_note_redeemed_amount=redeemed)


async def list_sales(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    customer_id: UUID | None = None,
    status_filter: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
) -> CursorPage[SaleOut]:
    # El rango de fechas se interpreta en la zona de la EMPRESA (misma regla
    # que el resto de la app) — se resuelve acá y no en el repositorio para
    # no pedirla cuando no hay filtro de fecha.
    tz_name = (
        await platform_integration.get_company_timezone(db, company_id=company_id)
        if from_date is not None or to_date is not None
        else "UTC"
    )
    rows = await repository.list_sales(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        customer_id=customer_id,
        status_filter=status_filter,
        tz_name=tz_name,
        from_date=from_date,
        to_date=to_date,
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


# =========================================================================
# Devolución de cliente (00042) y nota crédito (00043).
#
# Distinta de `void_sale` a propósito (00033 ya lo dejó escrito): la venta
# OCURRIÓ, hubo ingreso, y ahora sale plata (o un compromiso de plata) días
# o semanas después. Por eso es parcial (una o varias líneas, cantidad
# parcial), no exige que la sesión de caja de la venta original siga
# abierta (puede estar en un cierre ya inmutable — el contra-movimiento cae
# en la sesión de HOY, mismo criterio que `pay_entry` para pagar una compra
# vieja), y separa "cómo se liquida" de "si la mercancía vuelve".
# =========================================================================


def _row_to_return_line(row: Row[Any]) -> SaleReturnLineOut:
    m = row._mapping
    return SaleReturnLineOut(
        id=m["id"],
        sale_line_id=m["sale_line_id"],
        item_id=m["item_id"],
        quantity=m["quantity"],
        unit_cost=m["unit_cost"],
        restock=m["restock"],
    )


async def create_return(
    db: AsyncSession,
    *,
    company_id: UUID,
    sale_id: UUID,
    body: SaleReturnCreateIn,
    user: CurrentUser,
    idempotency_key: str,
) -> SaleReturnOut:
    existing = await repository.find_return_by_idempotency_key(
        db, company_id=company_id, idempotency_key=idempotency_key
    )
    if existing is not None:
        return await get_return(db, company_id=company_id, return_id=existing._mapping["id"])

    sale = await repository.get_sale(db, company_id=company_id, sale_id=sale_id)
    if sale is None:
        raise NotFoundError("La venta no existe en esta empresa.")
    if sale._mapping["status"] != "completed":
        raise ConflictError("Solo se puede devolver una venta completada.")

    # El cliente se hereda de la venta si la tenía; si no (venta de
    # mostrador), hay que identificarlo ACÁ para poder emitir una nota
    # crédito. No se puede atribuir la devolución a un cliente distinto del
    # comprador — la nota crédito no es transferible.
    sale_customer_id = sale._mapping["customer_id"]
    if (
        body.customer_id is not None
        and sale_customer_id is not None
        and body.customer_id != sale_customer_id
    ):
        raise AppError("La devolución no puede atribuirse a un cliente distinto del que compró.")
    customer_id = body.customer_id or sale_customer_id
    if body.settlement_method == "credit_note" and customer_id is None:
        raise AppError("La nota crédito exige un cliente identificado.")
    if customer_id is not None:
        customer = await customers_repo.get_customer(
            db, company_id=company_id, customer_id=customer_id
        )
        if customer is None:
            raise NotFoundError("El cliente no existe en esta empresa.")

    today = await platform_integration.get_company_today(db, company_id=company_id)

    # --- Advertencia de plazo: ADVIERTE, no bloquea duro ----------------
    # No hay un plazo legal fijo en Colombia para devoluciones en tienda
    # física que justifique prohibirlo del todo — es política comercial de
    # cada empresa, saltable con permiso para el caso puntual que lo merece.
    days_since_sale = (today - sale._mapping["sold_at"].date()).days
    window = await platform_integration.get_return_window_days(db, company_id=company_id)
    past_window = window > 0 and days_since_sale > window
    if past_window and not await has_permission(
        db, user.role_id, "sales.return_override_time_limit"
    ):
        raise AppError(
            f"La venta fue hace {days_since_sale} días; el plazo configurado es de "
            f"{window}. Se necesita el permiso 'sales.return_override_time_limit' para "
            "registrar una devolución fuera de plazo.",
            code="RETURN_TIME_LIMIT_EXCEEDED",
            details={"days_since_sale": days_since_sale, "window_days": window},
        )

    # --- Efectivo sobre una venta `settlement` no liquidada: bloqueado --
    # Una cuenta settlement (Sistecrédito) es plata que el negocio todavía
    # NO ha recibido. Devolverla en efectivo sacaría dinero real que nunca
    # entró — la salida legítima ahí es la nota crédito, o liquidar la
    # cuenta primero.
    if body.settlement_method == "cash" and sale._mapping["account_id"] is not None:
        account_type = await accounts_integration.get_account_type(
            db, company_id=company_id, account_id=sale._mapping["account_id"]
        )
        if account_type == "settlement":
            pending = await accounts_integration.get_account_balance(
                db, company_id=company_id, account_id=sale._mapping["account_id"]
            )
            if pending > 0:
                raise AppError(
                    "Esta venta se cobró por una cuenta por cobrar (Sistecrédito) que "
                    "todavía tiene saldo pendiente de liquidar: devolver en efectivo "
                    "sacaría plata que el negocio nunca recibió. Usa nota crédito, o "
                    "liquida la cuenta primero.",
                    code="SALE_ACCOUNT_NOT_SETTLED",
                    details={
                        "account_id": str(sale._mapping["account_id"]),
                        "pending": str(pending),
                    },
                )

    # --- Cada línea: cuánto queda disponible para devolver --------------
    # Es lo que habilita la devolución PARCIAL: cada intento nuevo solo
    # puede tomar lo que no se haya devuelto ya, a diferencia de
    # `void_sale`, que es todo-o-nada.
    resolved_lines: list[tuple[Row[Any], Any]] = []
    for line in body.lines:
        sale_line = await repository.get_sale_line(
            db, company_id=company_id, sale_line_id=line.sale_line_id
        )
        if sale_line is None or sale_line._mapping["sale_id"] != sale_id:
            raise NotFoundError(
                "Una línea de la devolución no pertenece a esta venta.",
                details={"sale_line_id": str(line.sale_line_id)},
            )
        already_returned = await repository.sum_returned_quantity(
            db, company_id=company_id, sale_line_id=line.sale_line_id
        )
        available = sale_line._mapping["quantity"] - already_returned
        if line.quantity > available:
            raise AppError(
                "La cantidad a devolver supera lo disponible de esa línea.",
                details={"sale_line_id": str(line.sale_line_id), "available": str(available)},
            )
        resolved_lines.append((sale_line, line))

    return_id = uuid4()
    number = await repository.next_return_number(db, company_id=company_id)
    await repository.insert_sale_return(
        db,
        return_id=return_id,
        company_id=company_id,
        number=number,
        sale_id=sale_id,
        customer_id=customer_id,
        reason=body.reason,
        settlement_method=body.settlement_method,
        notes=body.notes,
        return_date=today,
        created_by=user.id,
        idempotency_key=idempotency_key,
    )

    for sale_line, line_in in resolved_lines:
        sale_line_m = sale_line._mapping
        result_item_id: UUID | None = None
        if line_in.restock:
            item = await inventory_repo.get_item(
                db, company_id=company_id, item_id=sale_line_m["item_id"]
            )
            assert item is not None
            if item._mapping["status"] in ("sold", "available"):
                # Camino A: el lote sigue intacto (nadie lo tocó desde la
                # venta) — se reabre el MISMO, exactamente como `void_sale`.
                await inventory_repo.adjust_item_quantity(
                    db,
                    company_id=company_id,
                    item_id=item._mapping["id"],
                    delta=line_in.quantity,
                    new_status="available" if item._mapping["status"] == "sold" else None,
                )
                result_item_id = item._mapping["id"]
            else:
                # Camino B: el lote ya no es reabrible (su remanente se
                # consumió en una transformación, se dio de baja, etc.
                # después de la venta). Reingresa como lote NUEVO, vía el
                # mecanismo real de `inventory_entry` — mismo patrón que los
                # `produced` de una transformación — al costo ya congelado
                # en la línea de venta, nunca recalculado.
                entry_id = uuid4()
                entry_number = await inventory_repo.next_counter(
                    db, company_id=company_id, prefix="INV_ENTRY"
                )
                await inventory_repo.insert_entry(
                    db,
                    entry_id=entry_id,
                    company_id=company_id,
                    number=entry_number,
                    origin_type="customer_return",
                    supplier_id=None,
                    supplier_invoice=None,
                    contract_id=None,
                    total_cost=quantize(sale_line_m["unit_cost"] * line_in.quantity),
                    notes=f"Reingreso por devolución de la venta #{sale._mapping['number']}",
                    registered_by=user.id,
                    entry_date=today,
                )
                new_item_id = uuid4()
                lot_number = await inventory_repo.next_lot_number(
                    db, company_id=company_id, product_id=item._mapping["product_id"]
                )
                await inventory_repo.insert_item(
                    db,
                    item_id=new_item_id,
                    company_id=company_id,
                    product_id=item._mapping["product_id"],
                    lot_number=lot_number,
                    origin="other",
                    supplier_id=None,
                    source_contract_id=None,
                    source_return_id=return_id,
                    cost=sale_line_m["unit_cost"],
                    quantity=line_in.quantity,
                    photos=[],
                    created_by=user.id,
                    entry_date=today,
                )
                await inventory_repo.insert_entry_line(
                    db,
                    line_id=uuid4(),
                    company_id=company_id,
                    entry_id=entry_id,
                    item_id=new_item_id,
                    quantity=line_in.quantity,
                    unit_cost=sale_line_m["unit_cost"],
                )
                result_item_id = new_item_id

        await repository.insert_sale_return_line(
            db,
            line_id=uuid4(),
            company_id=company_id,
            return_id=return_id,
            sale_line_id=line_in.sale_line_id,
            item_id=result_item_id,
            quantity=line_in.quantity,
            unit_cost=sale_line_m["unit_cost"],
            restock=line_in.restock,
        )

    total_amount = await repository.sum_sale_return_amount(
        db, company_id=company_id, return_id=return_id
    )

    if body.settlement_method == "cash":
        # `account_id=None`: cae en la cuenta `cash` default, que exige
        # sesión abierta — la de HOY, no la de la venta original.
        resolved = await cashbox_integration.resolve_account_for_movement(
            db,
            company_id=company_id,
            payment_method="cash",
            account_id=None,
            direction="out",
        )
        await cashbox_integration.record_movement(
            db,
            session_id=resolved.session_id,
            company_id=company_id,
            module="store",
            direction="out",
            concept="sale_return",
            amount=total_amount,
            payment_method="cash",
            reference_type="sale_return",
            reference_id=return_id,
            created_by=user.id,
            notes=f"Devolución de la venta #{sale._mapping['number']}",
            account_id=resolved.account_id,
        )
    else:
        assert customer_id is not None  # validado arriba
        credit_note_id = uuid4()
        credit_note_number = await repository.next_credit_note_number(db, company_id=company_id)
        await repository.insert_credit_note(
            db,
            credit_note_id=credit_note_id,
            company_id=company_id,
            number=credit_note_number,
            customer_id=customer_id,
            sale_return_id=return_id,
            amount=total_amount,
            notes=body.notes,
            created_by=user.id,
        )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=user.id,
        module="sales",
        action="create_return",
        entity_type="sale_return",
        entity_id=return_id,
        after={
            "sale_id": str(sale_id),
            "settlement_method": body.settlement_method,
            "total_amount": str(total_amount),
            "time_limit_warning": past_window,
        },
    )

    return await get_return(db, company_id=company_id, return_id=return_id)


async def get_return(db: AsyncSession, *, company_id: UUID, return_id: UUID) -> SaleReturnOut:
    row = await repository.get_sale_return(db, company_id=company_id, return_id=return_id)
    if row is None:
        raise NotFoundError("La devolución no existe en esta empresa.")
    m = row._mapping

    lines = await repository.list_sale_return_lines(db, company_id=company_id, return_id=return_id)
    total_amount = await repository.sum_sale_return_amount(
        db, company_id=company_id, return_id=return_id
    )
    credit_note = await repository.get_credit_note_by_return(
        db, company_id=company_id, return_id=return_id
    )
    credit_note_id = credit_note._mapping["id"] if credit_note is not None else None

    sale = await repository.get_sale(db, company_id=company_id, sale_id=m["sale_id"])
    assert sale is not None
    window = await platform_integration.get_return_window_days(db, company_id=company_id)
    days_since_sale = (m["return_date"] - sale._mapping["sold_at"].date()).days
    time_limit_warning = window > 0 and days_since_sale > window

    return SaleReturnOut(
        id=m["id"],
        number=m["number"],
        sale_id=m["sale_id"],
        customer_id=m["customer_id"],
        reason=m["reason"],
        settlement_method=m["settlement_method"],
        notes=m["notes"],
        return_date=m["return_date"],
        created_at=m["created_at"],
        lines=[_row_to_return_line(r) for r in lines],
        credit_note_id=credit_note_id,
        total_amount=total_amount,
        time_limit_warning=time_limit_warning,
    )


async def list_returns_for_sale(
    db: AsyncSession, *, company_id: UUID, sale_id: UUID
) -> list[SaleReturnOut]:
    rows = await repository.list_returns_for_sale(db, company_id=company_id, sale_id=sale_id)
    return [await get_return(db, company_id=company_id, return_id=r._mapping["id"]) for r in rows]


def _row_to_credit_note(row: Row[Any], *, redeemed_amount: Decimal) -> CreditNoteOut:
    m = row._mapping
    amount = Decimal(str(m["amount"]))
    return CreditNoteOut(
        id=m["id"],
        number=m["number"],
        customer_id=m["customer_id"],
        sale_return_id=m["sale_return_id"],
        amount=amount,
        redeemed_amount=redeemed_amount,
        balance=amount - redeemed_amount,
        notes=m["notes"],
        created_at=m["created_at"],
    )


async def get_credit_note(
    db: AsyncSession, *, company_id: UUID, credit_note_id: UUID
) -> CreditNoteOut:
    row = await repository.get_credit_note(db, company_id=company_id, credit_note_id=credit_note_id)
    if row is None:
        raise NotFoundError("La nota crédito no existe en esta empresa.")
    redeemed = await repository.sum_credit_note_redemptions(
        db, company_id=company_id, credit_note_id=credit_note_id
    )
    return _row_to_credit_note(row, redeemed_amount=redeemed)


async def list_credit_notes(
    db: AsyncSession,
    *,
    company_id: UUID,
    customer_id: UUID | None,
    cursor: UUID | None,
    limit: int,
) -> CursorPage[CreditNoteOut]:
    rows = await repository.list_credit_notes(
        db, company_id=company_id, customer_id=customer_id, cursor=cursor, limit=limit
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    items = [
        _row_to_credit_note(r, redeemed_amount=Decimal(str(r._mapping["redeemed_amount"])))
        for r in page.items
    ]
    return CursorPage(items=items, next_cursor=page.next_cursor)
