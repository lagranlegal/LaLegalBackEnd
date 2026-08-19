from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

# LEFT JOIN (no inner): una empresa recién creada, suspendida sin
# suscripción activa, o con la suscripción ya vencida (job nocturno) sigue
# debiendo listarse — plan_code/plan_name/subscription_expires_at salen
# null en esos casos, no desaparece la fila.
_COMPANY_COLUMNS = """
    c.id, c.name, c.status, c.created_at,
    p.code as plan_code, p.name as plan_name, s.expires_at as subscription_expires_at
"""
_COMPANY_FROM = """
    from public.company c
    left join public.subscription s on s.company_id = c.id and s.status = 'active'
    left join public.plan p on p.id = s.plan_id
"""


async def get_company_timezone(db: AsyncSession, *, company_id: UUID) -> str:
    result = await db.execute(
        text(
            "select coalesce(settings->>'timezone', 'America/Bogota') "
            "from public.company where id = :id"
        ),
        {"id": str(company_id)},
    )
    return str(result.scalar_one())


async def get_plan_id_by_code(db: AsyncSession, *, code: str) -> UUID | None:
    result = await db.execute(
        text("select id from public.plan where code = :code and active"),
        {"code": code},
    )
    row = result.first()
    return row[0] if row else None


async def list_plans(db: AsyncSession) -> list[Row[Any]]:
    result = await db.execute(
        text("select id, name, code, price, modules, active from public.plan order by name")
    )
    return list(result.all())


async def insert_company(db: AsyncSession, *, company_id: UUID, name: str) -> None:
    await db.execute(
        text("insert into public.company (id, name) values (:id, :name)"),
        {"id": str(company_id), "name": name},
    )


async def get_company(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(f"select {_COMPANY_COLUMNS} {_COMPANY_FROM} where c.id = :id"),
        {"id": str(company_id)},
    )
    return result.first()


async def get_company_profile(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    """`id, name, logo_url, settings` — para `GET /me` (identity), que
    necesita más campos de los que trae `get_company`."""
    result = await db.execute(
        text("select id, name, logo_url, settings from public.company where id = :id"),
        {"id": str(company_id)},
    )
    return result.first()


async def list_companies(db: AsyncSession, *, cursor: UUID | None, limit: int) -> list[Row[Any]]:
    query = f"select {_COMPANY_COLUMNS} {_COMPANY_FROM}"
    params: dict[str, Any] = {"limit": limit + 1}
    if cursor is not None:
        query += " where c.id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by c.id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def set_company_status(db: AsyncSession, *, company_id: UUID, status: str) -> None:
    await db.execute(
        text("update public.company set status = :status where id = :id"),
        {"id": str(company_id), "status": status},
    )


async def insert_subscription(
    db: AsyncSession, *, company_id: UUID, plan_id: UUID, expires_at: date
) -> None:
    await db.execute(
        text(
            """
            insert into public.subscription (company_id, plan_id, status, expires_at)
            values (:company_id, :plan_id, 'active', :expires_at)
            """
        ),
        {"company_id": str(company_id), "plan_id": str(plan_id), "expires_at": expires_at},
    )


async def get_active_subscription(db: AsyncSession, *, company_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id, company_id, plan_id, status, expires_at
            from public.subscription
            where company_id = :company_id and status = 'active'
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.first()


async def get_active_subscription_with_plan(
    db: AsyncSession, *, company_id: UUID
) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select s.status, s.expires_at, p.code as plan_code, p.name as plan_name
            from public.subscription s
            join public.plan p on p.id = s.plan_id
            where s.company_id = :company_id and s.status = 'active'
            """
        ),
        {"company_id": str(company_id)},
    )
    return result.first()


async def extend_subscription(
    db: AsyncSession,
    *,
    subscription_id: UUID,
    new_expires_at: date,
    extended_by: UUID,
    notes: str | None,
) -> None:
    await db.execute(
        text(
            """
            update public.subscription
            set expires_at = :new_expires_at, extended_by = :extended_by, notes = :notes
            where id = :id
            """
        ),
        {
            "id": str(subscription_id),
            "new_expires_at": new_expires_at,
            "extended_by": str(extended_by),
            "notes": notes,
        },
    )


async def list_active_subscriptions(db: AsyncSession) -> list[Row[Any]]:
    """Suscripciones `active` de TODAS las empresas — candidatas a vencer
    (job nocturno). `expires_at` se compara contra el "hoy" de cada empresa,
    no acá: el llamador itera y decide por fila.
    """
    result = await db.execute(
        text("select id, company_id, expires_at from public.subscription where status = 'active'")
    )
    return list(result.all())


async def expire_subscription(db: AsyncSession, *, subscription_id: UUID) -> None:
    await db.execute(
        text("update public.subscription set status = 'expired' where id = :id"),
        {"id": str(subscription_id)},
    )


async def insert_cash_register(db: AsyncSession, *, company_id: UUID) -> None:
    await db.execute(
        text("insert into public.cash_register (company_id) values (:company_id)"),
        {"company_id": str(company_id)},
    )
