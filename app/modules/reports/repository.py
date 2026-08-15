from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_CLOSING_COLUMNS = (
    "id, session_date, opening_balance, expected_cash, counted_cash, difference, "
    "difference_reason, closed_by, closed_at"
)


async def contract_kpis(db: AsyncSession, *, company_id: UUID, today: date) -> Row[Any]:
    result = await db.execute(
        text(
            """
            select
              count(*) filter (where status = 'active') as active_count,
              count(*) filter (where status = 'in_arrears') as in_arrears_count,
              count(*) filter (where status = 'in_extension') as in_extension_count,
              count(*) filter (
                where status = 'in_extension' and extension_ends_at < :today
              ) as ready_for_auction_count,
              count(*) filter (where status = 'auctioned') as auctioned_count,
              coalesce(
                sum(capital_balance) filter (
                  where status in ('active', 'in_arrears', 'in_extension')
                ),
                0
              ) as capital_outstanding
            from public.contract
            where company_id = :company_id
            """
        ),
        {"company_id": str(company_id), "today": today},
    )
    return result.one()


async def sales_kpis(db: AsyncSession, *, company_id: UUID, tz_name: str, today: date) -> Row[Any]:
    result = await db.execute(
        text(
            """
            select
              coalesce(
                sum(total) filter (where (sold_at at time zone :tz)::date = :today), 0
              ) as today_total,
              count(*) filter (where (sold_at at time zone :tz)::date = :today) as today_count,
              coalesce(
                sum(total) filter (
                  where date_trunc('month', sold_at at time zone :tz)
                        = date_trunc('month', :today)
                ),
                0
              ) as month_total
            from public.sale
            where company_id = :company_id and status = 'completed'
            """
        ),
        {"company_id": str(company_id), "tz": tz_name, "today": today},
    )
    return result.one()


async def inventory_kpis(db: AsyncSession, *, company_id: UUID) -> Row[Any]:
    result = await db.execute(
        text(
            """
            select
              count(*) filter (where status = 'available') as available_count,
              coalesce(
                sum(cost * quantity) filter (where status = 'available'), 0
              ) as available_value,
              count(*) filter (where status = 'draft') as draft_count
            from public.inventory_item
            where company_id = :company_id
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.one()


async def current_open_session(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id, opened_at, opening_balance
            from public.cash_session
            where company_id = :company_id and status = 'open'
            order by opened_at desc
            limit 1
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.first()


async def list_closings(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    from_date: date | None,
    to_date: date | None,
) -> list[Row[Any]]:
    query = (
        f"select {_CLOSING_COLUMNS} from public.cash_session "
        "where company_id = :company_id and status = 'closed'"
    )
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if from_date is not None:
        query += " and session_date >= :from_date"
        params["from_date"] = from_date
    if to_date is not None:
        query += " and session_date <= :to_date"
        params["to_date"] = to_date
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())
