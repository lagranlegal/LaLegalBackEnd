from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_SALE_COLUMNS = (
    "id, number, sold_at, customer_id, discount_amount, total, payment_method, status, "
    "void_reason, created_at"
)
_LINE_COLUMNS = "id, item_id, quantity, unit_price, unit_cost, subtotal"


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
) -> None:
    await db.execute(
        text(
            """
            insert into public.sale
                (id, company_id, number, customer_id, sold_by, discount_amount, discount_by,
                 total, payment_method, idempotency_key)
            values
                (:id, :company_id, :number, :customer_id, :sold_by, :discount_amount,
                 :discount_by, :total, :payment_method, :idempotency_key)
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
        },
    )


async def insert_sale_line(
    db: AsyncSession,
    *,
    line_id: UUID,
    company_id: UUID,
    sale_id: UUID,
    item_id: UUID,
    quantity: int,
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


async def list_sales(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    customer_id: UUID | None,
    status_filter: str | None,
) -> list[Row[Any]]:
    query = f"select {_SALE_COLUMNS} from public.sale where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if customer_id is not None:
        query += " and customer_id = :customer_id"
        params["customer_id"] = str(customer_id)
    if status_filter:
        query += " and status = :status"
        params["status"] = status_filter
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
