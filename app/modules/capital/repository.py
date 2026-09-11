"""SQL del patrimonio del dueño: aportes y retiros (`00054`).

El historial sale por `(movement_date, id) desc`, no por `id`: acá el orden
ES la función. *"Un listado ordenado por un id aleatorio no está ordenado"* —
`order by id` sobre UUID pagina bien y por eso nadie lo nota, pero el orden
que produce no significa nada, y un histórico de plata desordenado no se
puede leer. El `id` va en la llave para desempatar los del mismo día.

Y la fecha es la del DOCUMENTO, no `created_at`: el dueño puede registrar el
lunes el aporte que hizo el viernes, y ese aporte pertenece al viernes.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "m.id, m.number, m.direction, m.kind, m.account_id, m.amount, "
    "m.movement_date, m.notes, m.created_at, a.name as account_name"
)


async def next_number(db: AsyncSession, *, company_id: UUID) -> int:
    """Consecutivo por empresa vía `next_counter()` (atómico, ya en 00001) —
    el mismo mecanismo de contratos, ventas y traslados.

    Aportes y retiros COMPARTEN el consecutivo a propósito: son el mismo
    documento en dos sentidos, y dos series paralelas obligarían a decir
    "aporte #4" y "retiro #4" en la misma pantalla.
    """
    result = await db.execute(
        text("select public.next_counter(:cid, 'CAPITAL_MOVEMENT')"),
        {"cid": str(company_id)},
    )
    return int(result.scalar_one())


async def find_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id from public.capital_movement "
            "where company_id = :cid and idempotency_key = :key"
        ),
        {"cid": str(company_id), "key": idempotency_key},
    )
    return result.first()


async def insert_movement(
    db: AsyncSession,
    *,
    movement_id: UUID,
    company_id: UUID,
    number: int,
    direction: str,
    kind: str | None,
    account_id: UUID,
    amount: Decimal,
    movement_date: date,
    notes: str | None,
    created_by: UUID | None,
    idempotency_key: str,
) -> None:
    await db.execute(
        text(
            """
            insert into public.capital_movement
                (id, company_id, number, direction, kind, account_id, amount,
                 movement_date, notes, created_by, idempotency_key)
            values
                (:id, :cid, :number, :direction, :kind, :account_id, :amount,
                 :mdate, :notes, :created_by, :key)
            """
        ),
        {
            "id": str(movement_id),
            "cid": str(company_id),
            "number": number,
            "direction": direction,
            "kind": kind,
            "account_id": str(account_id),
            "amount": amount,
            "mdate": movement_date,
            "notes": notes,
            "created_by": str(created_by) if created_by else None,
            "key": idempotency_key,
        },
    )


async def get_movement(db: AsyncSession, *, company_id: UUID, movement_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"""
            select {_COLUMNS}
            from public.capital_movement m
            join public.account a on a.id = m.account_id
            where m.company_id = :cid and m.id = :id
            """
        ),
        {"cid": str(company_id), "id": str(movement_id)},
    )
    return result.first()


async def list_movements(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: tuple[date, UUID] | None,
    limit: int,
    direction: str | None,
) -> list[Row[Any]]:
    # El cursor se agrega al WHERE solo si viene, nunca como
    # `(:cursor is null or ...)`: así escrito, asyncpg no puede inferir el
    # tipo del parámetro y Postgres responde `could not determine data type`
    # — el endpoint devolvía 500 SIEMPRE. Ya pasó en `list_transfers`.
    query = f"""
        select {_COLUMNS}
        from public.capital_movement m
        join public.account a on a.id = m.account_id
        where m.company_id = :cid
    """
    params: dict[str, Any] = {"cid": str(company_id), "limit": limit + 1}
    if direction is not None:
        query += " and m.direction = :direction"
        params["direction"] = direction
    if cursor is not None:
        query += " and (m.movement_date, m.id) < (:cursor_date, :cursor_id)"
        params["cursor_date"] = cursor[0]
        params["cursor_id"] = str(cursor[1])
    query += " order by m.movement_date desc, m.id desc limit :limit"

    result = await db.execute(text(query), params)
    return list(result.all())


async def totals_in_period(
    db: AsyncSession, *, company_id: UUID, from_date: date, to_date: date
) -> Row[Any]:
    """Aportes y retiros del período, por `movement_date`.

    Por la FECHA DEL DOCUMENTO y no por `created_at`: el dueño puede
    registrar el lunes el aporte que hizo el viernes, y ese aporte pertenece
    al viernes. Es el mismo criterio de `account_transfer.transfer_date`.
    """
    result = await db.execute(
        text(
            """
            select
              coalesce(sum(amount) filter (where direction = 'contribution'), 0) as contributions,
              coalesce(sum(amount) filter (where direction = 'withdrawal'), 0)   as withdrawals
            from public.capital_movement
            where company_id = :cid and movement_date between :from_date and :to_date
            """
        ),
        {"cid": str(company_id), "from_date": from_date, "to_date": to_date},
    )
    return result.one()


async def loan_portfolio(db: AsyncSession, *, company_id: UUID) -> Decimal:
    """Capital prestado y todavía no recuperado.

    Es plata DEL NEGOCIO que no está en ninguna cuenta — y en una compraventa
    suele ser la mayor parte. Sin esto, "cuánto capital tiene la empresa" se
    respondería con el saldo del cajón, que es una fracción.

    Solo los estados VIVOS. `superseded` se excluye o el capital de una
    cadena de recargos se contaría una vez por eslabón; `paid` y `auctioned`
    ya no deben nada.
    """
    result = await db.execute(
        text(
            """
            select coalesce(sum(capital_balance), 0)
            from public.contract
            where company_id = :cid
              and status in ('active', 'in_arrears', 'in_extension')
            """
        ),
        {"cid": str(company_id)},
    )
    return Decimal(str(result.scalar_one()))


async def inventory_at_cost(db: AsyncSession, *, company_id: UUID) -> Decimal:
    """Inventario disponible valorado AL COSTO, nunca al precio de venta.

    Contar la utilidad antes de venderla es el error clásico, y acá importa
    el doble: este número alimenta el aviso de "cuánto se puede retirar".

    Mismo criterio que `reports.inventory_valuation`: solo `available` (un
    borrador no se puede vender y un dado de baja ya no existe), y el costo
    sale del LOTE — identificación específica, nunca promediado.
    """
    result = await db.execute(
        text(
            """
            select coalesce(sum(i.cost * i.quantity), 0)
            from public.inventory_item i
            where i.company_id = :cid and i.status = 'available'
            """
        ),
        {"cid": str(company_id)},
    )
    return Decimal(str(result.scalar_one()))
