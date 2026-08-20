from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = "id, name, type, reference, is_default, active, created_at"


async def list_accounts(
    db: AsyncSession, *, company_id: UUID, include_inactive: bool = False
) -> list[Row[Any]]:
    """Cuentas con su saldo, calculado desde `cash_movement`.

    El saldo se DERIVA de los movimientos en vez de guardarse en una columna.
    Un saldo almacenado hay que mantenerlo sincronizado con cada operación, y
    en cuanto una falle o alguien inserte a mano queda mintiendo — el mismo
    problema de doble fuente de verdad que ya costó una corrección con el
    precio de los lotes. Derivarlo no puede desincronizarse.
    """
    query = f"""
        select {", ".join("a." + c for c in _COLUMNS.split(", "))},
          coalesce(
            sum(case when m.direction = 'in' then m.amount else -m.amount end),
            0::numeric(14, 2)
          ) as balance
        from public.account a
        left join public.cash_movement m
          on m.account_id = a.id and m.company_id = a.company_id
        where a.company_id = :company_id
    """
    params: dict[str, Any] = {"company_id": str(company_id)}
    if not include_inactive:
        query += " and a.active"
    query += " group by a.id order by a.type, a.name"
    result = await db.execute(text(query), params)
    return list(result.all())


async def get_account(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(f"select {_COLUMNS} from public.account where company_id = :cid and id = :id"),
        {"cid": str(company_id), "id": str(account_id)},
    )
    return result.first()


async def account_balance(db: AsyncSession, *, company_id: UUID, account_id: UUID) -> Decimal:
    result = await db.execute(
        text(
            """
            select coalesce(
              sum(case when direction = 'in' then amount else -amount end),
              0::numeric(14, 2)
            )
            from public.cash_movement
            where company_id = :cid and account_id = :aid
            """
        ),
        {"cid": str(company_id), "aid": str(account_id)},
    )
    return Decimal(str(result.scalar_one()))


async def insert_account(
    db: AsyncSession,
    *,
    account_id: UUID,
    company_id: UUID,
    name: str,
    account_type: str,
    reference: str | None,
    is_default: bool,
) -> None:
    await db.execute(
        text(
            """
            insert into public.account (id, company_id, name, type, reference, is_default)
            values (:id, :cid, :name, :type, :reference, :is_default)
            """
        ),
        {
            "id": str(account_id),
            "cid": str(company_id),
            "name": name,
            "type": account_type,
            "reference": reference,
            "is_default": is_default,
        },
    )


async def clear_default(db: AsyncSession, *, company_id: UUID, account_type: str) -> None:
    """Quita la marca de "por defecto" a la cuenta que la tenga de ese tipo.

    Hace falta porque hay un índice único parcial: sin limpiar primero, marcar
    una segunda cuenta como predeterminada violaría la restricción en vez de
    reemplazar a la anterior, que es lo que el usuario espera.
    """
    await db.execute(
        text(
            "update public.account set is_default = false "
            "where company_id = :cid and type = :type and is_default"
        ),
        {"cid": str(company_id), "type": account_type},
    )


async def update_account_fields(
    db: AsyncSession, *, company_id: UUID, account_id: UUID, fields: dict[str, Any]
) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "cid": str(company_id), "id": str(account_id)}
    await db.execute(
        text(f"update public.account set {assignments} where company_id = :cid and id = :id"),
        params,
    )
