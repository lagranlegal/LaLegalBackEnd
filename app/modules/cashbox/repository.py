from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_COLUMNS = (
    "id, register_id, session_date, opened_by, opened_at, opening_balance, expected_cash, "
    "counted_cash, difference, difference_reason, closed_by, closed_at, status"
)
_EXPENSE_COLUMNS = (
    "id, session_id, module, category_id, description, amount, payment_method, "
    "receipt_url, created_at"
)


async def get_active_register(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id from public.cash_register where company_id = :company_id and active "
            "order by created_at limit 1"
        ),
        {"company_id": str(company_id)},
    )
    return result.first()


async def session_exists_for_date(
    db: AsyncSession, *, register_id: UUID, session_date: date
) -> bool:
    result = await db.execute(
        text(
            "select 1 from public.cash_session "
            "where register_id = :register_id and session_date = :session_date"
        ),
        {"register_id": str(register_id), "session_date": session_date},
    )
    return result.first() is not None


async def get_open_session_for_register(db: AsyncSession, *, register_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id from public.cash_session "
            "where register_id = :register_id and status = 'open'"
        ),
        {"register_id": str(register_id)},
    )
    return result.first()


async def insert_session(
    db: AsyncSession,
    *,
    session_id: UUID,
    company_id: UUID,
    register_id: UUID,
    opened_by: UUID,
    opening_balance: Decimal,
    session_date: date,
) -> None:
    # `session_date` se pasa explícito (en vez de dejar el default
    # `current_date` de la columna) para que use la MISMA fecha que el
    # pre-check de service.py (`date.today()`, reloj de este proceso) — si
    # se dejara el default de Postgres, un desfase de huso horario entre el
    # backend y la BD podría hacer que el pre-check no viera lo que el
    # INSERT sí ve, y una violación de constraint cruda se cuela sin el
    # mensaje amigable.
    await db.execute(
        text(
            """
            insert into public.cash_session
                (id, company_id, register_id, opened_by, opening_balance, session_date)
            values
                (:id, :company_id, :register_id, :opened_by, :opening_balance, :session_date)
            """
        ),
        {
            "id": str(session_id),
            "company_id": str(company_id),
            "register_id": str(register_id),
            "opened_by": str(opened_by),
            "opening_balance": opening_balance,
            "session_date": session_date,
        },
    )


async def get_session(db: AsyncSession, *, company_id: UUID, session_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_SESSION_COLUMNS} from public.cash_session "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(session_id)},
    )
    return result.first()


async def list_sessions(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = f"select {_SESSION_COLUMNS} from public.cash_session where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def movement_breakdown(
    db: AsyncSession, *, company_id: UUID, session_id: UUID
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            """
            select module, direction, concept, payment_method, sum(amount) as total
            from public.cash_movement
            where company_id = :company_id and session_id = :session_id
            group by module, direction, concept, payment_method
            order by module, direction, concept, payment_method
            """
        ),
        {"company_id": str(company_id), "session_id": str(session_id)},
    )
    return list(result.all())


async def close_session(
    db: AsyncSession,
    *,
    company_id: UUID,
    session_id: UUID,
    expected_cash: Decimal,
    counted_cash: Decimal,
    difference: Decimal,
    difference_reason: str | None,
    closed_by: UUID,
) -> None:
    await db.execute(
        text(
            """
            update public.cash_session
            set status = 'closed', expected_cash = :expected_cash, counted_cash = :counted_cash,
                difference = :difference, difference_reason = :difference_reason,
                closed_by = :closed_by, closed_at = now()
            where company_id = :company_id and id = :id
            """
        ),
        {
            "company_id": str(company_id),
            "id": str(session_id),
            "expected_cash": expected_cash,
            "counted_cash": counted_cash,
            "difference": difference,
            "difference_reason": difference_reason,
            "closed_by": str(closed_by),
        },
    )


async def reopen_session(db: AsyncSession, *, company_id: UUID, session_id: UUID) -> None:
    await db.execute(
        text(
            """
            update public.cash_session
            set status = 'open', closed_by = null, closed_at = null,
                expected_cash = null, counted_cash = null, difference = null,
                difference_reason = null
            where company_id = :company_id and id = :id
            """
        ),
        {"company_id": str(company_id), "id": str(session_id)},
    )


async def category_name_exists(
    db: AsyncSession, *, company_id: UUID, name: str, exclude_id: UUID | None = None
) -> bool:
    query = "select 1 from public.expense_category where company_id = :company_id and name = :name"
    params: dict[str, Any] = {"company_id": str(company_id), "name": name}
    if exclude_id is not None:
        query += " and id != :exclude_id"
        params["exclude_id"] = str(exclude_id)
    result = await db.execute(text(query), params)
    return result.first() is not None


async def insert_expense_category(
    db: AsyncSession, *, category_id: UUID, company_id: UUID, name: str
) -> None:
    await db.execute(
        text(
            "insert into public.expense_category (id, company_id, name) values (:id, :cid, :name)"
        ),
        {"id": str(category_id), "cid": str(company_id), "name": name},
    )


async def get_expense_category(
    db: AsyncSession, *, company_id: UUID, category_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id, name, active from public.expense_category "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(category_id)},
    )
    return result.first()


async def list_expense_categories(db: AsyncSession, *, company_id: UUID) -> list[Row[Any]]:
    result = await db.execute(
        text(
            "select id, name, active from public.expense_category "
            "where company_id = :company_id order by name"
        ),
        {"company_id": str(company_id)},
    )
    return list(result.all())


async def insert_expense(
    db: AsyncSession,
    *,
    expense_id: UUID,
    company_id: UUID,
    session_id: UUID,
    module: str,
    category_id: UUID,
    description: str,
    amount: Decimal,
    payment_method: str,
    receipt_url: str | None,
    registered_by: UUID,
) -> None:
    await db.execute(
        text(
            """
            insert into public.expense
                (id, company_id, session_id, module, category_id, description, amount,
                 payment_method, receipt_url, registered_by)
            values
                (:id, :company_id, :session_id, :module, :category_id, :description, :amount,
                 :payment_method, :receipt_url, :registered_by)
            """
        ),
        {
            "id": str(expense_id),
            "company_id": str(company_id),
            "session_id": str(session_id),
            "module": module,
            "category_id": str(category_id),
            "description": description,
            "amount": amount,
            "payment_method": payment_method,
            "receipt_url": receipt_url,
            "registered_by": str(registered_by),
        },
    )


async def get_expense(db: AsyncSession, *, company_id: UUID, expense_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_EXPENSE_COLUMNS} from public.expense "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(expense_id)},
    )
    return result.first()


async def list_expenses(
    db: AsyncSession,
    *,
    company_id: UUID,
    session_id: UUID | None,
    cursor: UUID | None,
    limit: int,
) -> list[Row[Any]]:
    query = f"select {_EXPENSE_COLUMNS} from public.expense where company_id = :company_id"
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if session_id is not None:
        query += " and session_id = :session_id"
        params["session_id"] = str(session_id)
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())
