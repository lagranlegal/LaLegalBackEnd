from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_SALE_COLUMNS = (
    "id, number, sold_at, customer_id, discount_amount, total, payment_method, status, "
    "void_reason, created_at, account_id"
)
_LINE_COLUMNS = "id, item_id, quantity, unit_price, unit_cost, subtotal"
_RETURN_COLUMNS = (
    "id, company_id, number, sale_id, customer_id, reason, settlement_method, notes, "
    "return_date, created_at"
)
_RETURN_LINE_COLUMNS = "id, sale_line_id, item_id, quantity, unit_cost, restock"
_CREDIT_NOTE_COLUMNS = "id, number, customer_id, sale_return_id, amount, notes, created_at"


async def next_number(db: AsyncSession, *, company_id: UUID) -> int:
    result = await db.execute(
        text("select public.next_counter(:company_id, 'SALE')"), {"company_id": str(company_id)}
    )
    return int(result.scalar_one())


async def find_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_SALE_COLUMNS} from public.sale "
            "where company_id = :company_id and idempotency_key = :idempotency_key"
        ),
        {"company_id": str(company_id), "idempotency_key": idempotency_key},
    )
    return result.first()


async def insert_sale(
    db: AsyncSession,
    *,
    sale_id: UUID,
    company_id: UUID,
    number: int,
    customer_id: UUID | None,
    sold_by: UUID,
    discount_amount: Decimal,
    discount_by: UUID | None,
    total: Decimal,
    payment_method: str,
    idempotency_key: str,
    account_id: UUID | None = None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.sale
                (id, company_id, number, customer_id, sold_by, discount_amount, discount_by,
                 total, payment_method, idempotency_key, account_id)
            values
                (:id, :company_id, :number, :customer_id, :sold_by, :discount_amount,
                 :discount_by, :total, :payment_method, :idempotency_key, :account_id)
            """
        ),
        {
            "id": str(sale_id),
            "company_id": str(company_id),
            "number": number,
            "customer_id": str(customer_id) if customer_id else None,
            "sold_by": str(sold_by),
            "discount_amount": discount_amount,
            "discount_by": str(discount_by) if discount_by else None,
            "total": total,
            "payment_method": payment_method,
            "idempotency_key": idempotency_key,
            "account_id": str(account_id) if account_id else None,
        },
    )


async def insert_sale_line(
    db: AsyncSession,
    *,
    line_id: UUID,
    company_id: UUID,
    sale_id: UUID,
    item_id: UUID,
    quantity: Decimal,
    unit_price: Decimal,
    unit_cost: Decimal,
    subtotal: Decimal,
) -> None:
    await db.execute(
        text(
            """
            insert into public.sale_line
                (id, company_id, sale_id, item_id, quantity, unit_price, unit_cost, subtotal)
            values
                (:id, :company_id, :sale_id, :item_id, :quantity, :unit_price, :unit_cost,
                 :subtotal)
            """
        ),
        {
            "id": str(line_id),
            "company_id": str(company_id),
            "sale_id": str(sale_id),
            "item_id": str(item_id),
            "quantity": quantity,
            "unit_price": unit_price,
            "unit_cost": unit_cost,
            "subtotal": subtotal,
        },
    )


async def get_sale(db: AsyncSession, *, company_id: UUID, sale_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_SALE_COLUMNS} from public.sale where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(sale_id)},
    )
    return result.first()


async def list_sale_lines(db: AsyncSession, *, company_id: UUID, sale_id: UUID) -> list[Row[Any]]:
    result = await db.execute(
        text(
            f"select {_LINE_COLUMNS} from public.sale_line "
            "where company_id = :company_id and sale_id = :sale_id"
        ),
        {"company_id": str(company_id), "sale_id": str(sale_id)},
    )
    return list(result.all())


async def get_sale_line(
    db: AsyncSession, *, company_id: UUID, sale_line_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_LINE_COLUMNS}, sale_id from public.sale_line "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(sale_line_id)},
    )
    return result.first()


async def list_sales(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    customer_id: UUID | None,
    status_filter: str | None,
    tz_name: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[Row[Any]]:
    query = f"select {_SALE_COLUMNS} from public.sale where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if customer_id is not None:
        query += " and customer_id = :customer_id"
        params["customer_id"] = str(customer_id)
    if status_filter:
        query += " and status = :status"
        params["status"] = status_filter
    # `sold_at` es timestamptz; el rango que manda el front son fechas del
    # calendario de la EMPRESA, no UTC — mismo criterio que ya usan los
    # reportes (`(sold_at at time zone :tz)::date`). Sin el `at time zone`,
    # una venta de las 7pm en Bogotá caería en el día siguiente.
    if from_date is not None:
        query += " and (sold_at at time zone :tz)::date >= :from_date"
        params["from_date"] = from_date
        params["tz"] = tz_name
    if to_date is not None:
        query += " and (sold_at at time zone :tz)::date <= :to_date"
        params["to_date"] = to_date
        params["tz"] = tz_name
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def void_sale(
    db: AsyncSession, *, company_id: UUID, sale_id: UUID, void_reason: str, voided_by: UUID
) -> None:
    await db.execute(
        text(
            """
            update public.sale set status = 'voided', void_reason = :reason, voided_by = :voided_by
            where company_id = :company_id and id = :id
            """
        ),
        {
            "company_id": str(company_id),
            "id": str(sale_id),
            "reason": void_reason,
            "voided_by": str(voided_by),
        },
    )


# =========================================================================
# Devolución de cliente (00042) y nota crédito (00043).
# =========================================================================


async def next_return_number(db: AsyncSession, *, company_id: UUID) -> int:
    result = await db.execute(
        text("select public.next_counter(:company_id, 'SALE_RETURN')"),
        {"company_id": str(company_id)},
    )
    return int(result.scalar_one())


async def find_return_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_RETURN_COLUMNS} from public.sale_return "
            "where company_id = :company_id and idempotency_key = :idempotency_key"
        ),
        {"company_id": str(company_id), "idempotency_key": idempotency_key},
    )
    return result.first()


async def insert_sale_return(
    db: AsyncSession,
    *,
    return_id: UUID,
    company_id: UUID,
    number: int,
    sale_id: UUID,
    customer_id: UUID | None,
    reason: str,
    settlement_method: str,
    notes: str | None,
    return_date: date,
    created_by: UUID | None,
    idempotency_key: str,
) -> None:
    await db.execute(
        text(
            """
            insert into public.sale_return
                (id, company_id, number, sale_id, customer_id, reason, settlement_method,
                 notes, return_date, created_by, idempotency_key)
            values
                (:id, :company_id, :number, :sale_id, :customer_id, :reason, :settlement_method,
                 :notes, :return_date, :created_by, :idempotency_key)
            """
        ),
        {
            "id": str(return_id),
            "company_id": str(company_id),
            "number": number,
            "sale_id": str(sale_id),
            "customer_id": str(customer_id) if customer_id else None,
            "reason": reason,
            "settlement_method": settlement_method,
            "notes": notes,
            "return_date": return_date,
            "created_by": str(created_by) if created_by else None,
            "idempotency_key": idempotency_key,
        },
    )


async def insert_sale_return_line(
    db: AsyncSession,
    *,
    line_id: UUID,
    company_id: UUID,
    return_id: UUID,
    sale_line_id: UUID,
    item_id: UUID | None,
    quantity: Decimal,
    unit_cost: Decimal,
    restock: bool,
) -> None:
    await db.execute(
        text(
            """
            insert into public.sale_return_line
                (id, company_id, return_id, sale_line_id, item_id, quantity, unit_cost, restock)
            values
                (:id, :company_id, :return_id, :sale_line_id, :item_id, :quantity, :unit_cost,
                 :restock)
            """
        ),
        {
            "id": str(line_id),
            "company_id": str(company_id),
            "return_id": str(return_id),
            "sale_line_id": str(sale_line_id),
            "item_id": str(item_id) if item_id else None,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "restock": restock,
        },
    )


async def get_sale_return(
    db: AsyncSession, *, company_id: UUID, return_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_RETURN_COLUMNS} from public.sale_return "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(return_id)},
    )
    return result.first()


async def list_sale_return_lines(
    db: AsyncSession, *, company_id: UUID, return_id: UUID
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            f"select {_RETURN_LINE_COLUMNS} from public.sale_return_line "
            "where company_id = :company_id and return_id = :return_id"
        ),
        {"company_id": str(company_id), "return_id": str(return_id)},
    )
    return list(result.all())


async def list_returns_for_sale(
    db: AsyncSession, *, company_id: UUID, sale_id: UUID
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            f"select {_RETURN_COLUMNS} from public.sale_return "
            "where company_id = :company_id and sale_id = :sale_id order by number"
        ),
        {"company_id": str(company_id), "sale_id": str(sale_id)},
    )
    return list(result.all())


async def sum_returned_quantity(
    db: AsyncSession, *, company_id: UUID, sale_line_id: UUID
) -> Decimal:
    """Cuánto de una línea de venta ya se devolvió en devoluciones anteriores
    — es lo que habilita la devolución PARCIAL: cada intento nuevo solo puede
    tomar lo que queda (`sale_line.quantity - esto`), nunca más.
    """
    result = await db.execute(
        text(
            "select coalesce(sum(quantity), 0) from public.sale_return_line "
            "where company_id = :company_id and sale_line_id = :sale_line_id"
        ),
        {"company_id": str(company_id), "sale_line_id": str(sale_line_id)},
    )
    return Decimal(str(result.scalar_one()))


async def sum_sale_return_amount(db: AsyncSession, *, company_id: UUID, return_id: UUID) -> Decimal:
    """El monto de una devolución se DERIVA de sus líneas × el precio de la
    línea de venta original — nunca se guarda una columna `total`, mismo
    principio que el saldo de una nota crédito o una cuenta por pagar.
    """
    result = await db.execute(
        text(
            """
            select coalesce(sum(round(srl.quantity * sl.unit_price, 2)), 0)
            from public.sale_return_line srl
            join public.sale_line sl on sl.id = srl.sale_line_id and sl.company_id = srl.company_id
            where srl.company_id = :company_id and srl.return_id = :return_id
            """
        ),
        {"company_id": str(company_id), "return_id": str(return_id)},
    )
    return Decimal(str(result.scalar_one()))


async def get_credit_note_by_return(
    db: AsyncSession, *, company_id: UUID, return_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_CREDIT_NOTE_COLUMNS} from public.credit_note "
            "where company_id = :company_id and sale_return_id = :return_id"
        ),
        {"company_id": str(company_id), "return_id": str(return_id)},
    )
    return result.first()


async def next_credit_note_number(db: AsyncSession, *, company_id: UUID) -> int:
    result = await db.execute(
        text("select public.next_counter(:company_id, 'CREDIT_NOTE')"),
        {"company_id": str(company_id)},
    )
    return int(result.scalar_one())


async def insert_credit_note(
    db: AsyncSession,
    *,
    credit_note_id: UUID,
    company_id: UUID,
    number: int,
    customer_id: UUID,
    sale_return_id: UUID,
    amount: Decimal,
    notes: str | None,
    created_by: UUID | None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.credit_note
                (id, company_id, number, customer_id, sale_return_id, amount, notes, created_by)
            values
                (:id, :company_id, :number, :customer_id, :sale_return_id, :amount, :notes,
                 :created_by)
            """
        ),
        {
            "id": str(credit_note_id),
            "company_id": str(company_id),
            "number": number,
            "customer_id": str(customer_id),
            "sale_return_id": str(sale_return_id),
            "amount": amount,
            "notes": notes,
            "created_by": str(created_by) if created_by else None,
        },
    )


async def get_credit_note_for_update(
    db: AsyncSession, *, company_id: UUID, credit_note_id: UUID
) -> Row[Any] | None:
    """`FOR UPDATE`: bloquea la fila para que dos ventas que intentan redimir
    la misma nota crédito a la vez no puedan sobregirarla — la segunda espera
    a que la primera termine su transacción y ve el saldo ya descontado.
    """
    result = await db.execute(
        text(
            f"select {_CREDIT_NOTE_COLUMNS} from public.credit_note "
            "where company_id = :company_id and id = :id for update"
        ),
        {"company_id": str(company_id), "id": str(credit_note_id)},
    )
    return result.first()


async def get_credit_note(
    db: AsyncSession, *, company_id: UUID, credit_note_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_CREDIT_NOTE_COLUMNS} from public.credit_note "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(credit_note_id)},
    )
    return result.first()


async def sum_credit_note_redemptions(
    db: AsyncSession, *, company_id: UUID, credit_note_id: UUID
) -> Decimal:
    result = await db.execute(
        text(
            "select coalesce(sum(amount), 0) from public.credit_note_redemption "
            "where company_id = :company_id and credit_note_id = :credit_note_id"
        ),
        {"company_id": str(company_id), "credit_note_id": str(credit_note_id)},
    )
    return Decimal(str(result.scalar_one()))


async def insert_credit_note_redemption(
    db: AsyncSession,
    *,
    redemption_id: UUID,
    company_id: UUID,
    credit_note_id: UUID,
    sale_id: UUID,
    amount: Decimal,
    created_by: UUID | None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.credit_note_redemption
                (id, company_id, credit_note_id, sale_id, amount, created_by)
            values
                (:id, :company_id, :credit_note_id, :sale_id, :amount, :created_by)
            """
        ),
        {
            "id": str(redemption_id),
            "company_id": str(company_id),
            "credit_note_id": str(credit_note_id),
            "sale_id": str(sale_id),
            "amount": amount,
            "created_by": str(created_by) if created_by else None,
        },
    )


async def get_sale_credit_note_redemption(
    db: AsyncSession, *, company_id: UUID, sale_id: UUID
) -> Row[Any] | None:
    """Una venta redime a lo sumo una nota crédito (`SaleCreateIn.credit_note_id`
    es singular) — la primera fila alcanza.
    """
    result = await db.execute(
        text(
            "select credit_note_id, amount from public.credit_note_redemption "
            "where company_id = :company_id and sale_id = :sale_id limit 1"
        ),
        {"company_id": str(company_id), "sale_id": str(sale_id)},
    )
    return result.first()


async def list_credit_notes(
    db: AsyncSession,
    *,
    company_id: UUID,
    customer_id: UUID | None,
    cursor: UUID | None,
    limit: int,
) -> list[Row[Any]]:
    query = """
        select
            cn.id, cn.number, cn.customer_id, cn.sale_return_id, cn.amount, cn.notes,
            cn.created_at, coalesce(r.redeemed, 0) as redeemed_amount
        from public.credit_note cn
        left join (
            select credit_note_id, sum(amount) as redeemed
            from public.credit_note_redemption
            group by credit_note_id
        ) r on r.credit_note_id = cn.id
        where cn.company_id = :company_id
    """
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if customer_id is not None:
        query += " and cn.customer_id = :customer_id"
        params["customer_id"] = str(customer_id)
    if cursor is not None:
        query += " and cn.id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by cn.id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())
