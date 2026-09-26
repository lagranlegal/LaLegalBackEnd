"""Lo que otros módulos pueden preguntarle a `contracts` (CLAUDE.md regla 2 —
nunca importar `contracts.service` desde otro módulo, solo esto).

Hoy lo pregunta `notifications`, para el resumen a la empresa
(docs/NOTIFICACIONES.md §2.4). Las dos respuestas reusan lo que ya existe:

- **E1, listos para remate:** el MISMO predicado de
  `GET /contracts/ready-for-auction` (`repository.list_ready_for_auction`),
  no una consulta nueva. "Listo para remate" no es un `status`: es
  `in_extension` con `extension_ends_at` ya pasado, y escribirlo dos veces es
  cómo dos pantallas terminan contando distinto.
- **E2, entraron en mora / en prórroga:** el día de entrada se DERIVA con
  `rules.add_months` desde el ancla del contrato, igual que lo hace
  `rules.compute_status`. No se usa el delta que escribe
  `recompute_all_statuses`: ese no ve los cambios que ya persistió el
  recálculo al abrir un contrato (`get_contract`), así que un contrato que
  alguien miró en el día desaparecería del resumen.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.money import quantize
from app.modules.contracts import repository, rules


@dataclass(frozen=True)
class ReadyForAuction:
    contract_id: UUID
    number: int
    customer_id: UUID
    extension_ends_at: date
    capital_balance: Decimal


@dataclass(frozen=True)
class StateEntry:
    contract_id: UUID
    number: int
    customer_id: UUID
    #: El día en que el contrato entró al estado (derivado del ancla).
    entered_on: date
    extension_ends_at: date | None


async def list_ready_for_auction(
    db: AsyncSession, *, company_id: UUID, today: date
) -> list[ReadyForAuction]:
    rows = await repository.list_ready_for_auction(db, company_id=company_id, today=today)
    return [
        ReadyForAuction(
            contract_id=r._mapping["id"],
            number=r._mapping["number"],
            customer_id=r._mapping["customer_id"],
            extension_ends_at=r._mapping["extension_ends_at"],
            capital_balance=r._mapping["capital_balance"],
        )
        for r in rows
    ]


def _entered_on(m: Any) -> date:
    if m["status"] == "in_arrears":
        # `months_owed` pasa de 0 a 1 exactamente ese día (`rules.months_between`).
        return rules.add_months(m["interest_paid_until"], 1)
    # `compute_status`: la prórroga se dispara al cumplir la ventana de mora.
    return rules.add_months(m["interest_paid_until"], m["arrears_window_months"])


async def list_state_entries(
    db: AsyncSession, *, company_id: UUID, after: date, until: date
) -> tuple[list[StateEntry], list[StateEntry]]:
    """Contratos que entraron en mora y en prórroga en `(after, until]`.

    Lee el estado PERSISTIDO — por eso el paso del job que lo llama va después
    de `recompute_all_statuses` (§5.2).
    """
    result = await db.execute(
        text(
            """
            select id, number, customer_id, status, interest_paid_until,
                   arrears_window_months, extension_ends_at
            from public.contract
            where company_id = :company_id and status in ('in_arrears', 'in_extension')
            order by number
            """
        ),
        {"company_id": str(company_id)},
    )
    arrears: list[StateEntry] = []
    extension: list[StateEntry] = []
    for row in result.all():
        m = row._mapping
        entered = _entered_on(m)
        if not (after < entered <= until):
            continue
        entry = StateEntry(
            contract_id=m["id"],
            number=m["number"],
            customer_id=m["customer_id"],
            entered_on=entered,
            extension_ends_at=m["extension_ends_at"],
        )
        (arrears if m["status"] == "in_arrears" else extension).append(entry)
    return arrears, extension


async def has_live_contract(db: AsyncSession, *, company_id: UUID, customer_id: UUID) -> bool:
    """¿El cliente tiene al menos un contrato NO terminal? Es la condición de
    la base legal `contract` del correo (docs/NOTIFICACIONES.md §9.2-a): la
    pregunta `customers` al registrar un correo nuevo. Mismo predicado que el
    backfill de `00059`."""
    result = await db.execute(
        text(
            """
            select exists (
              select 1 from public.contract
              where company_id = :company_id and customer_id = :customer_id
                and status::text <> all(:terminal)
            )
            """
        ),
        {
            "company_id": str(company_id),
            "customer_id": str(customer_id),
            "terminal": sorted(rules.TERMINAL_STATUSES),
        },
    )
    return bool(result.scalar_one())


@dataclass(frozen=True)
class ReminderContract:
    """Lo que los recordatorios al cliente (R1–R4, docs/NOTIFICACIONES.md §2.2,
    §20) necesitan de un contrato vivo. Toda fecha y todo monto sale de
    `rules`, acá adentro: `notifications` no calcula una fecha de cuota ni un
    interés, los recibe hechos. Dos formas de calcular la misma fecha terminan
    divergiendo (§2.2), y este proyecto ya lo pagó dos veces con el día de la
    empresa."""

    contract_id: UUID
    number: int
    customer_id: UUID
    status: str
    arrears_window_months: int
    #: `rules.add_months(interest_paid_until, 1)`: la próxima cuota. Es la
    #: ÚNICA forma permitida de calcularla (§2.2).
    next_due_date: date
    #: El día en que entró en mora (solo `in_arrears`): el mismo `_entered_on`
    #: del resumen (§15.2-1). Coincide con `next_due_date`: `months_owed` pasa
    #: de 0 a 1 el mismo día del vencimiento.
    arrears_entered_on: date | None
    #: El día en que entró en prórroga (solo `in_extension`), y solo si es
    #: coherente con el `extension_ends_at` persistido. Si el ancla se movió
    #: con la prórroga en curso (un abono que no alcanza a sacarla de ahí), el
    #: día derivado ya no es el de entrada, y un segundo «entró en prórroga»
    #: sobre la misma prórroga sería falso: `None`.
    extension_entered_on: date | None
    extension_ends_at: date | None
    capital_balance: Decimal
    #: Interés de UN mes (`rules.monthly_interest`): la cuota.
    monthly_interest: Decimal
    #: Meses adeudados HOY (`rules.months_between`), y lo que cuesta ponerse
    #: al día: `monthly_interest × months_owed`.
    months_owed: int
    amount_to_catch_up: Decimal


async def list_reminder_contracts(
    db: AsyncSession, *, company_id: UUID, today: date
) -> list[ReminderContract]:
    """Contratos NO terminales de la empresa, con sus fechas y montos ya
    derivados. Lee el estado PERSISTIDO: el paso del job que lo llama va
    después de `recompute_all_statuses` (§5.2)."""
    result = await db.execute(
        text(
            """
            select id, number, customer_id, status::text as status, interest_paid_until,
                   arrears_window_months, extension_months, extension_ends_at,
                   capital_balance, interest_rate_pct
            from public.contract
            where company_id = :company_id and status::text <> all(:terminal)
            order by number
            """
        ),
        {"company_id": str(company_id), "terminal": sorted(rules.TERMINAL_STATUSES)},
    )
    out: list[ReminderContract] = []
    for row in result.all():
        m = row._mapping
        ipu: date = m["interest_paid_until"]
        monthly = rules.monthly_interest(m["interest_rate_pct"], m["capital_balance"])
        owed = rules.months_between(ipu, today)
        arrears_on = _entered_on(m) if m["status"] == "in_arrears" else None
        extension_on: date | None = None
        if m["status"] == "in_extension":
            derived = _entered_on(m)
            if (
                m["extension_ends_at"] is not None
                and rules.add_months(derived, m["extension_months"]) == m["extension_ends_at"]
            ):
                extension_on = derived
        out.append(
            ReminderContract(
                contract_id=m["id"],
                number=m["number"],
                customer_id=m["customer_id"],
                status=m["status"],
                arrears_window_months=m["arrears_window_months"],
                next_due_date=rules.add_months(ipu, 1),
                arrears_entered_on=arrears_on,
                extension_entered_on=extension_on,
                extension_ends_at=m["extension_ends_at"],
                capital_balance=m["capital_balance"],
                monthly_interest=monthly,
                months_owed=owed,
                amount_to_catch_up=quantize(monthly * owed),
            )
        )
    return out
