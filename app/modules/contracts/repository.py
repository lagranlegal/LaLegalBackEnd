import json
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

_CONTRACT_COLUMNS = (
    "id, number, legacy_code, customer_id, principal, capital_balance, appraisal_value, "
    "interest_rate_pct, term_months, arrears_window_months, extension_months, start_date, "
    "due_date, interest_paid_until, status, extension_ends_at, ltv_warning, notes, "
    "signed_photo_url, created_at"
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
) -> None:
    await db.execute(
        text(
            """
            insert into public.contract
                (id, company_id, number, legacy_code, customer_id, principal, capital_balance,
                 appraisal_value, interest_rate_pct, term_months, arrears_window_months,
                 extension_months, start_date, due_date, interest_paid_until, ltv_warning, notes,
                 signed_photo_url, created_by, idempotency_key)
            values
                (:id, :company_id, :number, :legacy_code, :customer_id, :principal,
                 :capital_balance, :appraisal_value, :interest_rate_pct, :term_months,
                 :arrears_window_months, :extension_months, :start_date, :due_date,
                 :interest_paid_until, :ltv_warning, :notes, :signed_photo_url, :created_by,
                 :idempotency_key)
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


async def list_contracts(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: UUID | None,
    limit: int,
    status_filter: str | None,
    customer_id: UUID | None = None,
    q: str | None = None,
) -> list[Row[Any]]:
    # `q` necesita el cliente (nombre/documento) que `contract` no tiene —
    # LEFT JOIN incondicional en vez de armar dos formas de query distintas
    # según si `q` viene o no; `customer_id` es NOT NULL así que en la
    # práctica siempre resuelve, LEFT por si acaso.
    columns = ", ".join(f"c.{col.strip()}" for col in _CONTRACT_COLUMNS.split(","))
    query = (
        f"select {columns} from public.contract c "
        "left join public.customer cu on cu.id = c.customer_id "
        "where c.company_id = :company_id"
    )
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
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
        # mismo criterio que `customers.list_customers` (nombre full-text,
        # documento por prefijo) — es la misma pregunta ("¿quién es?") hecha
        # desde el lado del contrato en vez del cliente.
        #
        # El documento se busca SOLO con 5+ caracteres: los números de
        # contrato son cortos (1, 2, 17…) y las cédulas tienen 8-10 dígitos,
        # así que buscar "5" hacía match por prefijo contra el documento de
        # CUALQUIER cliente que empezara por 5 — un contrato ajeno aparecía
        # como si fuera el buscado. Con 5+ caracteres la consulta ya no puede
        # confundirse con un número de contrato.
        clauses = [
            "c.number::text like :q_prefix",
            "c.legacy_code ilike :q_prefix",
            "to_tsvector('spanish', cu.full_name) @@ plainto_tsquery('spanish', :q)",
        ]
        if len(q) >= 5:
            clauses.append("cu.doc_number like :q_prefix")
        query += " and (" + " or ".join(clauses) + ")"
        params["q"] = q
        params["q_prefix"] = f"{q}%"
    if cursor is not None:
        query += " and c.id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by c.id limit :limit"
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
) -> None:
    await db.execute(
        text(
            """
            update public.contract set status = :status, extension_ends_at = :extension_ends_at
            where company_id = :company_id and id = :id
            """
        ),
        {
            "company_id": str(company_id),
            "id": str(contract_id),
            "status": status,
            "extension_ends_at": extension_ends_at,
        },
    )


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
    """
    result = await db.execute(
        text(
            f"""
            select company_id, {_CONTRACT_COLUMNS} from public.contract
            where status not in ('paid', 'auctioned')
            """
        )
    )
    return list(result.all())
