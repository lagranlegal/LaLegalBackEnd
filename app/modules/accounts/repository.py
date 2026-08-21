from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = "id, name, type, reference, is_default, active, opening_balance, created_at"


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
    # El saldo se calcula distinto según el tipo, porque los tipos SON
    # distintos:
    #
    #   cash        lo que debería haber EN EL CAJÓN ahora mismo: la base con
    #               la que se abrió la sesión más los movimientos de esa
    #               sesión. Sumar el histórico completo daría un número sin
    #               sentido —y negativo, porque los préstamos desembolsados
    #               superan lo cobrado— ya que la base de apertura NO es un
    #               movimiento. Sin sesión abierta el cajón está cuadrado y
    #               cerrado, así que no hay saldo vivo que reportar.
    #
    #   bank y      arrancan en cero y todo lo que entra o sale queda como
    #   settlement  movimiento, así que el acumulado histórico SÍ es el saldo.
    #               En una `settlement` ese saldo es lo que te DEBEN.
    query = f"""
        with sesion_abierta as (
          select id, opening_balance from public.cash_session
          where company_id = :company_id and status = 'open'
          limit 1
        )
        select {", ".join("a." + c for c in _COLUMNS.split(", "))},
          case
            when a.type = 'cash' then
              coalesce((select opening_balance from sesion_abierta), 0::numeric(14, 2))
              + coalesce(sum(
                  case when m.session_id = (select id from sesion_abierta)
                       then case when m.direction = 'in' then m.amount else -m.amount end
                  end
                ), 0::numeric(14, 2))
            else
              a.opening_balance + coalesce(
                sum(case when m.direction = 'in' then m.amount else -m.amount end),
                0::numeric(14, 2)
              )
          end as balance
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
    """Saldo de UNA cuenta, con el mismo criterio por tipo que `list_accounts`.

    Delega en esa consulta en vez de tener la suya: dos formas de calcular el
    mismo saldo terminan divergiendo, y eso fue exactamente este bug —
    `list_accounts` ya sumaba el `opening_balance` y esta función no, así que
    una cuenta recién creada reportaba 0 mientras el listado la mostraba bien.
    """
    rows = await list_accounts(db, company_id=company_id, include_inactive=True)
    for row in rows:
        if row._mapping["id"] == account_id:
            return Decimal(str(row._mapping["balance"]))
    return Decimal("0.00")


async def insert_account(
    db: AsyncSession,
    *,
    account_id: UUID,
    company_id: UUID,
    name: str,
    account_type: str,
    reference: str | None,
    is_default: bool,
    opening_balance: Decimal,
) -> None:
    await db.execute(
        text(
            """
            insert into public.account
              (id, company_id, name, type, reference, is_default, opening_balance)
            values (:id, :cid, :name, :type, :reference, :is_default, :opening)
            """
        ),
        {
            "id": str(account_id),
            "cid": str(company_id),
            "name": name,
            "type": account_type,
            "reference": reference,
            "is_default": is_default,
            "opening": opening_balance,
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


async def find_transfer_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id from public.account_transfer "
            "where company_id = :cid and idempotency_key = :key"
        ),
        {"cid": str(company_id), "key": idempotency_key},
    )
    return result.first()


async def insert_transfer(
    db: AsyncSession,
    *,
    transfer_id: UUID,
    company_id: UUID,
    number: int,
    from_account_id: UUID,
    to_account_id: UUID,
    amount: Decimal,
    transfer_date: date,
    notes: str | None,
    created_by: UUID | None,
    idempotency_key: str,
) -> None:
    await db.execute(
        text(
            """
            insert into public.account_transfer
                (id, company_id, number, from_account_id, to_account_id, amount,
                 transfer_date, notes, created_by, idempotency_key)
            values
                (:id, :cid, :number, :from_id, :to_id, :amount,
                 :tdate, :notes, :created_by, :key)
            """
        ),
        {
            "id": str(transfer_id),
            "cid": str(company_id),
            "number": number,
            "from_id": str(from_account_id),
            "to_id": str(to_account_id),
            "amount": amount,
            "tdate": transfer_date,
            "notes": notes,
            "created_by": str(created_by) if created_by else None,
            "key": idempotency_key,
        },
    )


async def get_transfer(db: AsyncSession, *, company_id: UUID, transfer_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select t.id, t.number, t.amount, t.transfer_date, t.notes, t.created_at,
                   t.from_account_id, t.to_account_id,
                   fa.name as from_account_name, ta.name as to_account_name
            from public.account_transfer t
            join public.account fa on fa.id = t.from_account_id
            join public.account ta on ta.id = t.to_account_id
            where t.company_id = :cid and t.id = :id
            """
        ),
        {"cid": str(company_id), "id": str(transfer_id)},
    )
    return result.first()


async def list_transfers(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            """
            select t.id, t.number, t.amount, t.transfer_date, t.notes, t.created_at,
                   t.from_account_id, t.to_account_id,
                   fa.name as from_account_name, ta.name as to_account_name
            from public.account_transfer t
            join public.account fa on fa.id = t.from_account_id
            join public.account ta on ta.id = t.to_account_id
            where t.company_id = :cid and (:cursor is null or t.id > :cursor)
            order by t.id
            limit :limit
            """
        ),
        {"cid": str(company_id), "cursor": str(cursor) if cursor else None, "limit": limit + 1},
    )
    return list(result.all())


async def next_transfer_number(db: AsyncSession, *, company_id: UUID) -> int:
    """Consecutivo por empresa vía `next_counter()` (atómico, ya en 00001) —
    mismo mecanismo que usan los ingresos de inventario y los contratos."""
    result = await db.execute(
        text("select public.next_counter(:cid, 'ACCOUNT_TRANSFER')"),
        {"cid": str(company_id)},
    )
    return int(result.scalar_one())
