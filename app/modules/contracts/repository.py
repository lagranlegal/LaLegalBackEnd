import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.search import MIN_SEARCH_CHARS, name_clauses
from app.modules.contracts import rules

_CONTRACT_COLUMNS = (
    "id, number, legacy_code, customer_id, principal, capital_balance, appraisal_value, "
    "interest_rate_pct, term_months, arrears_window_months, extension_months, start_date, "
    "due_date, interest_paid_until, status, extension_ends_at, ltv_warning, notes, "
    "signed_photo_url, created_at, extension_window_days, extension_interest_policy, "
    "parent_contract_id, root_contract_id, extended_on, extension_amount"
)
_ITEM_COLUMNS = (
    "id, category_id, description, weight_grams, serial_imei, item_appraisal, status, photos, "
    "inventory_item_id"
)
_PAYMENT_COLUMNS = (
    "id, receipt_number, paid_at, months_covered, interest_amount, capital_amount, "
    "discount_amount, discount_reason, payment_method, total, new_capital_balance, "
    "new_interest_paid_until, created_at"
)


async def next_number(db: AsyncSession, *, company_id: UUID) -> int:
    result = await db.execute(
        text("select public.next_counter(:company_id, 'CONTRACT')"), {"company_id": str(company_id)}
    )
    return int(result.scalar_one())


async def next_receipt_number(db: AsyncSession, *, company_id: UUID) -> int:
    result = await db.execute(
        text("select public.next_counter(:company_id, 'RECEIPT')"), {"company_id": str(company_id)}
    )
    return int(result.scalar_one())


async def insert_contract(
    db: AsyncSession,
    *,
    contract_id: UUID,
    company_id: UUID,
    number: int,
    legacy_code: str | None,
    customer_id: UUID,
    principal: Decimal,
    capital_balance: Decimal,
    appraisal_value: Decimal | None,
    interest_rate_pct: Decimal,
    term_months: int,
    arrears_window_months: int,
    extension_months: int,
    start_date: date,
    due_date: date,
    interest_paid_until: date,
    ltv_warning: bool,
    notes: str | None,
    signed_photo_url: str | None,
    created_by: UUID,
    idempotency_key: str,
    # 00051 — ampliar préstamo. Con default para no tocar a quien ya llamaba
    # a esta función: un contrato normal nace con la política de su empresa
    # y sin cadena.
    #
    # `keep_anchor` desde 00053: al ampliar, el sucesor conserva la fecha del
    # contrato ORIGINAL, así que la fecha de cobro del cliente no se mueve.
    # El default vive acá Y en la columna: el INSERT manda el valor explícito,
    # así que cambiar solo el de la columna no habría cambiado nada.
    extension_window_days: int = 28,
    extension_interest_policy: str = "keep_anchor",
    parent_contract_id: UUID | None = None,
    root_contract_id: UUID | None = None,
    # 00053 — la trazabilidad del recargo. NULL en todo contrato que no nació
    # de uno; `extended_on is not null` responde "¿es un sucesor?".
    extended_on: date | None = None,
    extension_amount: Decimal | None = None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.contract
                (id, company_id, number, legacy_code, customer_id, principal, capital_balance,
                 appraisal_value, interest_rate_pct, term_months, arrears_window_months,
                 extension_months, start_date, due_date, interest_paid_until, ltv_warning, notes,
                 signed_photo_url, created_by, idempotency_key,
                 extension_window_days, extension_interest_policy,
                 parent_contract_id, root_contract_id, extended_on, extension_amount)
            values
                (:id, :company_id, :number, :legacy_code, :customer_id, :principal,
                 :capital_balance, :appraisal_value, :interest_rate_pct, :term_months,
                 :arrears_window_months, :extension_months, :start_date, :due_date,
                 :interest_paid_until, :ltv_warning, :notes, :signed_photo_url, :created_by,
                 :idempotency_key, :extension_window_days, :extension_interest_policy,
                 :parent_contract_id, :root_contract_id, :extended_on, :extension_amount)
            """
        ),
        {
            "id": str(contract_id),
            "company_id": str(company_id),
            "number": number,
            "legacy_code": legacy_code,
            "customer_id": str(customer_id),
            "principal": principal,
            "capital_balance": capital_balance,
            "appraisal_value": appraisal_value,
            "interest_rate_pct": interest_rate_pct,
            "term_months": term_months,
            "arrears_window_months": arrears_window_months,
            "extension_months": extension_months,
            "start_date": start_date,
            "due_date": due_date,
            "interest_paid_until": interest_paid_until,
            "ltv_warning": ltv_warning,
            "notes": notes,
            "signed_photo_url": signed_photo_url,
            "extension_window_days": extension_window_days,
            "extension_interest_policy": extension_interest_policy,
            "parent_contract_id": str(parent_contract_id) if parent_contract_id else None,
            "root_contract_id": str(root_contract_id) if root_contract_id else None,
            "extended_on": extended_on,
            "extension_amount": extension_amount,
            "created_by": str(created_by),
            "idempotency_key": idempotency_key,
        },
    )


async def find_contract_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id from public.contract "
            "where company_id = :company_id and idempotency_key = :idempotency_key"
        ),
        {"company_id": str(company_id), "idempotency_key": idempotency_key},
    )
    return result.first()


async def find_contract_by_legacy_code(
    db: AsyncSession, *, company_id: UUID, legacy_code: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            "select id from public.contract "
            "where company_id = :company_id and legacy_code = :legacy_code"
        ),
        {"company_id": str(company_id), "legacy_code": legacy_code},
    )
    return result.first()


async def insert_contract_item(
    db: AsyncSession,
    *,
    item_id: UUID,
    company_id: UUID,
    contract_id: UUID,
    category_id: UUID,
    description: str,
    weight_grams: Decimal | None,
    serial_imei: str | None,
    item_appraisal: Decimal | None,
    photos: list[str],
) -> None:
    await db.execute(
        text(
            """
            insert into public.contract_item
                (id, company_id, contract_id, category_id, description, weight_grams,
                 serial_imei, item_appraisal, photos)
            values
                (:id, :company_id, :contract_id, :category_id, :description, :weight_grams,
                 :serial_imei, :item_appraisal, cast(:photos as jsonb))
            """
        ),
        {
            "id": str(item_id),
            "company_id": str(company_id),
            "contract_id": str(contract_id),
            "category_id": str(category_id),
            "description": description,
            "weight_grams": weight_grams,
            "serial_imei": serial_imei,
            "item_appraisal": item_appraisal,
            "photos": _to_json_array(photos),
        },
    )


def _to_json_array(values: list[str]) -> str:
    return json.dumps(values)


async def get_contract(db: AsyncSession, *, company_id: UUID, contract_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_CONTRACT_COLUMNS} from public.contract "
            "where company_id = :company_id and id = :id"
        ),
        {"company_id": str(company_id), "id": str(contract_id)},
    )
    return result.first()


async def get_contract_for_update(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> Row[Any] | None:
    """`FOR UPDATE`: toda operación que MODIFICA un contrato lo lee por acá.

    Auditoría 27/09/2026, F4-01/F4-02: abonar, ampliar y rematar leían la
    fila sin bloquear, calculaban en Python y escribían valores ABSOLUTOS
    (`set capital_balance = :x`). Dos abonos simultáneos de 100.000 sobre un
    saldo de 500.000 dejaban 400.000 con 200.000 en la caja; dos recargos
    dejaban dos sucesores vivos del mismo padre. `next_receipt_number`
    serializaba las dos requests, pero la segunda ya traía la foto vieja.

    Con el bloqueo la segunda espera a que la primera confirme y, en READ
    COMMITTED, relee la fila ya actualizada — así valida contra el estado
    real (el mes ya pagado, el padre ya `superseded`). Mismo patrón que
    `sales.repository.get_sale_for_update`.
    """
    result = await db.execute(
        text(
            f"select {_CONTRACT_COLUMNS} from public.contract "
            "where company_id = :company_id and id = :id for update"
        ),
        {"company_id": str(company_id), "id": str(contract_id)},
    )
    return result.first()


async def mark_item_auctioned(
    db: AsyncSession, *, company_id: UUID, contract_item_id: UUID, inventory_item_id: UUID
) -> None:
    await db.execute(
        text(
            """
            update public.contract_item
            set status = 'auctioned', inventory_item_id = :inventory_item_id
            where company_id = :company_id and id = :id
            """
        ),
        {
            "company_id": str(company_id),
            "id": str(contract_item_id),
            "inventory_item_id": str(inventory_item_id),
        },
    )


async def list_contract_items(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> list[Row[Any]]:
    result = await db.execute(
        text(
            f"select {_ITEM_COLUMNS} from public.contract_item "
            "where company_id = :company_id and contract_id = :contract_id "
            "order by created_at"
        ),
        {"company_id": str(company_id), "contract_id": str(contract_id)},
    )
    return list(result.all())


async def mark_items_returned(db: AsyncSession, *, company_id: UUID, contract_id: UUID) -> None:
    """CLAUDE.md: al pagar `paid`, los artículos se devuelven TODOS juntos."""
    await db.execute(
        text(
            """
            update public.contract_item set status = 'returned'
            where company_id = :company_id and contract_id = :contract_id
            """
        ),
        {"company_id": str(company_id), "contract_id": str(contract_id)},
    )


async def mark_items_transferred(db: AsyncSession, *, company_id: UUID, contract_id: UUID) -> None:
    """Al ampliar el préstamo (00051) las prendas pasan al contrato sucesor.

    `transferred` y no `returned`: al cliente no se le devolvió nada — las
    mismas prendas siguen en custodia, respaldando el contrato nuevo. Si
    dijeran `returned`, el historial afirmaría que salieron de la bóveda.
    """
    await db.execute(
        text(
            """
            update public.contract_item set status = 'transferred'
            where company_id = :company_id and contract_id = :contract_id
            """
        ),
        {"company_id": str(company_id), "contract_id": str(contract_id)},
    )


async def find_successor_contract(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> Row[Any] | None:
    """El contrato que SUCEDE a este, o `None` si no fue ampliado.

    La columna que enlaza sucesor → padre es `parent_contract_id`, NO
    `root_contract_id` (que es la raíz de la cadena y en un sucesor apunta al
    abuelo) — el mismo error que costó rehacer la consulta forense de F21-10.

    Devuelve solo lo que hace falta para NOMBRAR al sucesor en un mensaje de
    error: quien intenta abonar sobre un contrato reemplazado necesita saber
    sobre cuál abonar. Se pide el más reciente por si la invariante de "un
    solo hijo por padre" se rompiera (bifurcación de cadena, hoy en cero):
    ante dos hijos, el último es el que carga la deuda viva.
    """
    result = await db.execute(
        text(
            "select id, number from public.contract "
            "where company_id = :company_id and parent_contract_id = :parent_id "
            "order by created_at desc limit 1"
        ),
        {"company_id": str(company_id), "parent_id": str(contract_id)},
    )
    return result.first()


async def list_chain(db: AsyncSession, *, company_id: UUID, contract_id: UUID) -> list[Row[Any]]:
    """Todos los contratos de la cadena a la que pertenece `contract_id`, de
    la raíz al último.

    Se arma por `root_contract_id` (que todo sucesor tiene apuntando al
    PRIMERO) y no recorriendo `parent_contract_id` hacia atrás: una consulta
    en vez de una por eslabón. Para un contrato que nunca se amplió devuelve
    solo a él. El orden es por `created_at` —cada sucesor nace después de su
    padre, en la misma transacción que lo cierra— con `number` de desempate.
    """
    result = await db.execute(
        text(
            f"""
            with raiz as (
              select coalesce(root_contract_id, id) as id
              from public.contract
              where company_id = :cid and id = :id
            )
            select {_CONTRACT_COLUMNS}
            from public.contract c
            where c.company_id = :cid
              and (c.id = (select id from raiz) or c.root_contract_id = (select id from raiz))
            order by c.created_at, c.number
            """
        ),
        {"cid": str(company_id), "id": str(contract_id)},
    )
    return list(result.all())


async def get_root_start_date(db: AsyncSession, *, company_id: UUID, contract_id: UUID) -> date:
    """`start_date` de la RAÍZ de la cadena — el ancla de la ventana de
    recargo. Para un contrato sin cadena es su propia fecha."""
    result = await db.execute(
        text(
            """
            select c.start_date
            from public.contract c
            where c.company_id = :cid
              and c.id = coalesce(
                    (select root_contract_id from public.contract
                     where company_id = :cid and id = :id),
                    :id)
            """
        ),
        {"cid": str(company_id), "id": str(contract_id)},
    )
    return date.fromisoformat(str(result.scalar_one()))


_IS_TERMINAL = "c.status::text = any(:terminal)"

#: La LLAVE de cada orden de `GET /contracts`: dirección única y las
#: expresiones en orden de prioridad. El cursor es la llave de la última fila
#: y la página siguiente es la comparación de filas `(k0, k1, …) > (…)` (o
#: `<` si es descendente) — por eso cada orden tiene UNA sola dirección, y lo
#: que va al revés dentro de un orden ascendente va negado (`-c.number`).
#: La última posición siempre es `c.id`: el número ya es único por empresa,
#: pero el id hace la llave única por construcción, sin depender de eso.
#: El tipo de cada posición (`bool|date|int|text|uuid`) es para leer el
#: cursor de vuelta (`service.list_contracts`).
#:
#: - `next_due_asc` («lo más urgente primero», el default): los vivos antes
#:   que los terminales; entre los vivos, el `interest_paid_until` más viejo
#:   primero —la próxima cuota es ese ancla + 1 mes, así que es el mismo
#:   orden que «próximo vencimiento primero» y pone arriba a quien más meses
#:   debe—; entre los terminales, el número más alto primero (la fecha no
#:   dice nada en un contrato cerrado: van todos con la misma constante).
#: - `customer_asc`: nombre sin tildes ni mayúsculas (Álvaro junto a Alberto,
#:   no después de la Z), y del mismo cliente el contrato más nuevo primero.
CONTRACT_SORTS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "next_due_asc": (
        "asc",
        (
            (f"({_IS_TERMINAL})", "bool"),
            (
                f"(case when {_IS_TERMINAL} then date '1900-01-01' else c.interest_paid_until end)",
                "date",
            ),
            (f"(case when {_IS_TERMINAL} then -c.number else c.number end)", "int"),
            ("c.id", "uuid"),
        ),
    ),
    "number_desc": ("desc", (("c.number", "int"), ("c.id", "uuid"))),
    "number_asc": ("asc", (("c.number", "int"), ("c.id", "uuid"))),
    "customer_asc": (
        "asc",
        (
            ("lower(public.f_unaccent(cu.full_name))", "text"),
            ("(-c.number)", "int"),
            ("c.id", "uuid"),
        ),
    ),
}


async def list_contracts(
    db: AsyncSession,
    *,
    company_id: UUID,
    sort: str,
    after: list[Any] | None,
    limit: int,
    status_filter: str | None,
    customer_id: UUID | None = None,
    q: str | None = None,
) -> list[Row[Any]]:
    """Una página del listado en el orden `sort`, empezando DESPUÉS de la
    llave `after` (la de la última fila de la página anterior, ya con sus
    tipos). Cada fila trae su llave en `sort_k0…sort_kN`."""
    direction, keys = CONTRACT_SORTS[sort]
    # El cliente viaja en la MISMA consulta (issue #10 del front): cada ítem
    # del listado trae `customer_name`/`customer_document`, y `q` busca por
    # ellos. JOIN interno: `customer_id` es NOT NULL con FK, y la policy de
    # `customer` es la misma de aislamiento por empresa que la de `contract`
    # (no exige `customers.view`), así que el JOIN nunca descarta un
    # contrato visible. Hasta el 01/10/2026 era LEFT "por si acaso" y el
    # nombre no salía: la pantalla tenía que pedir cada cliente aparte.
    columns = ", ".join(f"c.{col.strip()}" for col in _CONTRACT_COLUMNS.split(","))
    key_columns = "".join(f", {expr} as sort_k{i}" for i, (expr, _) in enumerate(keys))
    query = (
        f"select {columns}, cu.full_name as customer_name, "
        f"cu.doc_number as customer_document{key_columns} "
        "from public.contract c "
        "join public.customer cu on cu.id = c.customer_id and cu.company_id = c.company_id "
        "where c.company_id = :company_id"
    )
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if _IS_TERMINAL in " ".join(expr for expr, _ in keys):
        params["terminal"] = sorted(rules.TERMINAL_STATUSES)
    if status_filter:
        query += " and c.status = :status"
        params["status"] = status_filter
    if customer_id is not None:
        query += " and c.customer_id = :customer_id"
        params["customer_id"] = str(customer_id)
    if q:
        # Número: prefijo sobre el texto (se tipea completo o casi completo).
        # legacy_code: prefijo, sin distinguir mayúsculas — se imprimía o se
        # heredaba del sistema anterior con cualquier capitalización. Cliente:
        # mismo criterio que `customers.list_customers` (nombre por prefijo
        # full-text, documento por prefijo) — es la misma pregunta ("¿quién
        # es?") hecha desde el lado del contrato en vez del cliente.
        #
        # EL PISO VA POR CLÁUSULA, no sobre la consulta entera. El número de
        # contrato se sigue encontrando desde la primera tecla (los
        # consecutivos son 1, 17, 213…); el nombre y el documento esperan a
        # los tres caracteres de `MIN_SEARCH_CHARS`.
        #
        # Por qué el documento tiene piso: buscar "5" hacía match por prefijo
        # contra el documento de CUALQUIER cliente que empezara por 5, y un
        # contrato ajeno aparecía como si fuera el buscado. El piso bajó de 5
        # a 3 el 11/09/2026 a pedido del cliente. El solape con un número de
        # contrato de 3-4 dígitos vuelve a ser posible, pero acotado: son dos
        # cláusulas de un OR, así que el contrato buscado NUNCA desaparece —
        # a lo sumo aparece acompañado.
        clauses = [
            "c.number::text like :q_prefix",
            "c.legacy_code ilike :q_prefix",
        ]
        if len(q) >= MIN_SEARCH_CHARS:
            name_sql, name_params = name_clauses("cu.full_name", q, prefix="name")
            clauses.extend(name_sql)
            clauses.append("cu.doc_number like :q_prefix")
            params.update(name_params)
        query += " and (" + " or ".join(clauses) + ")"
        params["q_prefix"] = f"{q}%"
    if after is not None:
        exprs = ", ".join(expr for expr, _ in keys)
        marks = ", ".join(f":after_{i}" for i in range(len(keys)))
        query += f" and ({exprs}) {'>' if direction == 'asc' else '<'} ({marks})"
        params.update({f"after_{i}": value for i, value in enumerate(after)})
    order = ", ".join(f"{expr} {direction}" for expr, _ in keys)
    query += f" order by {order} limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def list_ready_for_auction(
    db: AsyncSession, *, company_id: UUID, today: date
) -> list[Row[Any]]:
    # `:today` viene de `platform.integration.get_company_today` (zona
    # horaria de la empresa) — nunca `current_date` de Postgres (UTC), para
    # no repetir el bug de huso horario que encontramos en cashbox.
    result = await db.execute(
        text(
            f"""
            select {_CONTRACT_COLUMNS} from public.contract
            where company_id = :company_id and status = 'in_extension'
              and extension_ends_at < :today
            order by extension_ends_at
            """
        ),
        {"company_id": str(company_id), "today": today},
    )
    return list(result.all())


async def list_attention_candidates(
    db: AsyncSession, *, company_id: UUID, today: date
) -> list[Row[Any]]:
    """Contratos NO terminales que deben al menos un mes, con el nombre del
    cliente, para «Para hoy» (`service.get_attention`). Una sola consulta: el
    motivo y los montos los decide `rules.attention_for` fila por fila.

    El filtro `interest_paid_until < :today` es un SUPERCONJUNTO barato de
    «debe al menos un mes» (`ancla + 1 mes <= hoy`): la aritmética de meses
    vive en `rules`, no se repite en SQL. Lee el estado persistido solo para
    descartar terminales; el efectivo lo recalcula la regla.
    """
    result = await db.execute(
        text(
            """
            select c.id, c.number, c.customer_id, cu.full_name as customer_name,
                   c.status::text as status, c.interest_paid_until, c.arrears_window_months,
                   c.extension_months, c.extension_ends_at, c.capital_balance,
                   c.interest_rate_pct, c.start_date
            from public.contract c
            join public.customer cu on cu.id = c.customer_id
            where c.company_id = :company_id and c.status::text <> all(:terminal)
              and c.interest_paid_until < :today
            """
        ),
        {
            "company_id": str(company_id),
            "terminal": sorted(rules.TERMINAL_STATUSES),
            "today": today,
        },
    )
    return list(result.all())


async def update_contract_fields(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `ContractUpdateIn.model_dump(exclude_unset=True)` en
    service.py — claves fijas y conocidas, nunca texto de un usuario.
    """
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "company_id": str(company_id), "id": str(contract_id)}
    await db.execute(
        text(
            f"update public.contract set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )


async def update_contract_status(
    db: AsyncSession,
    *,
    company_id: UUID,
    contract_id: UUID,
    status: str,
    extension_ends_at: date | None,
) -> bool:
    """Nunca saca a un contrato de un estado TERMINAL (`paid`, `auctioned`,
    `superseded`): el `where` lo excluye y devuelve si tocó la fila.

    F4-02: pasar el padre a `superseded` no tenía condición de estado, así
    que un recargo que corría junto a un pago total "resucitaba" y cerraba
    un contrato que ya estaba `paid`. Con el `FOR UPDATE` la carrera ya no
    llega acá; el `where` es la segunda llave, en la base, para que ningún
    camino futuro que se olvide del bloqueo pueda pisar un estado final.
    """
    result = await db.execute(
        text(
            """
            update public.contract set status = :status, extension_ends_at = :extension_ends_at
            where company_id = :company_id and id = :id
              and status not in ('paid', 'auctioned', 'superseded')
            """
        ),
        {
            "company_id": str(company_id),
            "id": str(contract_id),
            "status": status,
            "extension_ends_at": extension_ends_at,
        },
    )
    return bool(getattr(result, "rowcount", 0))


async def apply_payment_to_contract(
    db: AsyncSession,
    *,
    company_id: UUID,
    contract_id: UUID,
    new_capital_balance: Decimal,
    new_interest_paid_until: date,
    status: str,
    extension_ends_at: date | None,
) -> None:
    await db.execute(
        text(
            """
            update public.contract
            set capital_balance = :capital_balance,
                interest_paid_until = :interest_paid_until,
                status = :status,
                extension_ends_at = :extension_ends_at
            where company_id = :company_id and id = :id
            """
        ),
        {
            "company_id": str(company_id),
            "id": str(contract_id),
            "capital_balance": new_capital_balance,
            "interest_paid_until": new_interest_paid_until,
            "status": status,
            "extension_ends_at": extension_ends_at,
        },
    )


async def find_payment_by_idempotency_key(
    db: AsyncSession, *, company_id: UUID, idempotency_key: str
) -> Row[Any] | None:
    result = await db.execute(
        text(
            f"select {_PAYMENT_COLUMNS} from public.contract_payment "
            "where company_id = :company_id and idempotency_key = :idempotency_key"
        ),
        {"company_id": str(company_id), "idempotency_key": idempotency_key},
    )
    return result.first()


async def insert_payment(
    db: AsyncSession,
    *,
    payment_id: UUID,
    company_id: UUID,
    contract_id: UUID,
    receipt_number: int,
    months_covered: int,
    interest_amount: Decimal,
    capital_amount: Decimal,
    discount_amount: Decimal,
    discount_reason: str | None,
    discount_by: UUID | None,
    payment_method: str,
    total: Decimal,
    new_capital_balance: Decimal,
    new_interest_paid_until: date,
    idempotency_key: str,
    registered_by: UUID,
) -> None:
    await db.execute(
        text(
            """
            insert into public.contract_payment
                (id, company_id, contract_id, receipt_number, months_covered, interest_amount,
                 capital_amount, discount_amount, discount_reason, discount_by, payment_method,
                 total, new_capital_balance, new_interest_paid_until, idempotency_key,
                 registered_by)
            values
                (:id, :company_id, :contract_id, :receipt_number, :months_covered,
                 :interest_amount, :capital_amount, :discount_amount, :discount_reason,
                 :discount_by, :payment_method, :total, :new_capital_balance,
                 :new_interest_paid_until, :idempotency_key, :registered_by)
            """
        ),
        {
            "id": str(payment_id),
            "company_id": str(company_id),
            "contract_id": str(contract_id),
            "receipt_number": receipt_number,
            "months_covered": months_covered,
            "interest_amount": interest_amount,
            "capital_amount": capital_amount,
            "discount_amount": discount_amount,
            "discount_reason": discount_reason,
            "discount_by": str(discount_by) if discount_by else None,
            "payment_method": payment_method,
            "total": total,
            "new_capital_balance": new_capital_balance,
            "new_interest_paid_until": new_interest_paid_until,
            "idempotency_key": idempotency_key,
            "registered_by": str(registered_by),
        },
    )


async def list_payments(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = (
        f"select {_PAYMENT_COLUMNS} from public.contract_payment "
        "where company_id = :company_id and contract_id = :contract_id"
    )
    params: dict[str, Any] = {
        "company_id": str(company_id),
        "contract_id": str(contract_id),
        "limit": limit + 1,
    }
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def get_settlement_payment(
    db: AsyncSession, *, company_id: UUID, contract_id: UUID
) -> Row[Any] | None:
    """El abono que saldó el contrato — el único con `new_capital_balance=0`.
    Para paz y salvo: la fecha de cancelación SE DERIVA de acá, nunca se
    guarda aparte (no hay columna `paid_at`/`settled_at` en `contract`
    mismo) — mismo principio "los saldos se derivan" de todo el proyecto.
    Como `status='paid'` bloquea nuevos abonos, es inequívoco cuál fue.
    """
    result = await db.execute(
        text(
            "select paid_at, receipt_number from public.contract_payment "
            "where company_id = :company_id and contract_id = :contract_id "
            "and new_capital_balance = 0 "
            "order by paid_at desc limit 1"
        ),
        {"company_id": str(company_id), "contract_id": str(contract_id)},
    )
    return result.first()


async def list_active_contracts_for_recompute(db: AsyncSession) -> list[Row[Any]]:
    """Todos los contratos no terminales de TODAS las empresas — para el job
    nocturno (`recompute_all_statuses`). Corre con la sesión de bypass
    (`get_db`), no una tenant-scoped: necesita ver todas las empresas.

    El filtro sale de `rules.TERMINAL_STATUSES`, NO de una lista escrita a
    mano acá: esa lista se desincronizó de la constante cuando `superseded`
    entró en 00051 y el job estuvo once días recalculando contratos ya
    reemplazados (QA_AUDITORIA §F21-10). Se lee en cada llamada —no se copia
    al importar— para que agregar un estado terminal a la constante alcance.
    """
    stmt = text(
        f"""
        select company_id, {_CONTRACT_COLUMNS} from public.contract
        where status not in :terminal_statuses
        """
    ).bindparams(bindparam("terminal_statuses", expanding=True))
    result = await db.execute(stmt, {"terminal_statuses": sorted(rules.TERMINAL_STATUSES)})
    return list(result.all())
