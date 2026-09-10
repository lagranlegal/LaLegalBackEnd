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
    # TODOS los tipos se calculan igual: `opening_balance` de la cuenta más
    # sus propios movimientos. Es la definición de saldo de un libro mayor y
    # no puede desincronizarse.
    #
    # Hasta 00048 una cuenta `cash` era la excepción: su saldo salía de la
    # SESIÓN de caja abierta (su `opening_balance` digitado a mano más los
    # movimientos de esa sesión). Tres cosas rotas por el mismo error:
    #
    #   · Sin sesión abierta el cajón reportaba 0.00 — la plata dejaba de
    #     existir entre el cierre de la noche y la apertura de la mañana.
    #   · TODAS las cuentas de efectivo de una empresa reportaban el MISMO
    #     saldo, porque todas leían la única sesión. Con tres cajones daban
    #     los tres el mismo número.
    #   · El saldo dependía de un número escrito a mano cada mañana que nada
    #     comparaba contra el cierre anterior — el único dato de la
    #     aplicación que aparecía sin documento.
    #
    # La 00048 convirtió esa historia en movimientos (`adjustment`), así que
    # el saldo derivado arranca donde tiene que arrancar. Lo que el turno
    # necesita —cuánto DEBERÍA haber en el cajón al cerrar hoy— sigue siendo
    # asunto de `cashbox._expected_cash`, que es otra pregunta.
    query = f"""
        select {", ".join("a." + c for c in _COLUMNS.split(", "))},
          a.opening_balance + coalesce(
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
    # El cursor se agrega al WHERE solo si viene, igual que en el resto de
    # los repositorios (p. ej. `sales.list_sales`). Estuvo escrito como
    # `(:cursor is null or t.id > :cursor)`, y así asyncpg no podía inferir
    # el tipo del parámetro —aparece primero en `is null`, sin contexto— y
    # Postgres respondía `could not determine data type of parameter $2`:
    # el endpoint devolvía 500 SIEMPRE, con o sin cursor, desde 00032.
    query = """
        select t.id, t.number, t.amount, t.transfer_date, t.notes, t.created_at,
               t.from_account_id, t.to_account_id,
               fa.name as from_account_name, ta.name as to_account_name
        from public.account_transfer t
        join public.account fa on fa.id = t.from_account_id
        join public.account ta on ta.id = t.to_account_id
        where t.company_id = :cid
    """
    params: dict[str, Any] = {"cid": str(company_id), "limit": limit + 1}
    if cursor is not None:
        query += " and t.id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by t.id limit :limit"

    result = await db.execute(text(query), params)
    return list(result.all())


async def next_transfer_number(db: AsyncSession, *, company_id: UUID) -> int:
    """Consecutivo por empresa vía `next_counter()` (atómico, ya en 00001) —
    mismo mecanismo que usan los ingresos de inventario y los contratos."""
    result = await db.execute(
        text("select public.next_counter(:cid, 'ACCOUNT_TRANSFER')"),
        {"cid": str(company_id)},
    )
    return int(result.scalar_one())


async def balance_before(
    db: AsyncSession, *, company_id: UUID, account_id: UUID, from_date: date, tz_name: str
) -> Decimal:
    """Saldo de la cuenta ANTES del rango — el punto de partida del extracto.

    Es `opening_balance` más todo lo movido hasta el día anterior. Sin esto el
    extracto arrancaría en cero y ninguna línea cuadraría contra el banco:
    conciliar es justamente comparar saldos, no movimientos sueltos.

    SOLO tiene sentido en `bank` y `settlement`. En una cuenta de EFECTIVO el
    acumulado histórico no es un saldo: la base del cajón se vuelve a declarar
    en cada apertura de caja y no es un movimiento, así que sumar todo daría
    un número sin significado —y negativo, porque los préstamos desembolsados
    superan lo cobrado—. El efectivo se verifica contando, en el arqueo.
    """
    result = await db.execute(
        text(
            """
            select
              (select opening_balance from public.account
                where company_id = :cid and id = :aid)
              + coalesce(sum(case when m.direction = 'in' then m.amount else -m.amount end), 0)
            from public.cash_movement m
            where m.company_id = :cid
              and m.account_id = :aid
              and (m.created_at at time zone :tz)::date < :from_date
            """
        ),
        {"cid": str(company_id), "aid": str(account_id), "tz": tz_name, "from_date": from_date},
    )
    return Decimal(str(result.scalar_one() or 0))


async def account_movements(
    db: AsyncSession,
    *,
    company_id: UUID,
    account_id: UUID,
    from_date: date,
    to_date: date,
    tz_name: str,
) -> list[Row[Any]]:
    """Movimientos de una cuenta en el rango, del más viejo al más nuevo.

    Ese orden y no el inverso: un extracto se lee hacia abajo acumulando, como
    el del banco. Invertirlo obligaría a leer el saldo al revés.
    """
    result = await db.execute(
        text(
            """
            select id, created_at, module, concept, direction, amount,
                   payment_method, notes, reference_type, reference_id
            from public.cash_movement
            where company_id = :cid
              and account_id = :aid
              and (created_at at time zone :tz)::date between :from_date and :to_date
            order by created_at, id
            """
        ),
        {
            "cid": str(company_id),
            "aid": str(account_id),
            "tz": tz_name,
            "from_date": from_date,
            "to_date": to_date,
        },
    )
    return list(result.all())
