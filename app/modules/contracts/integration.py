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
