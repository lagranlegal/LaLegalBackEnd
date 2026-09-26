"""Paso del job nocturno que decide los recordatorios al cliente R1–R4
(docs/NOTIFICACIONES.md §2.2, §2.3, §5.2, §5.3, §6.1, §20).

Va DESPUÉS de `recompute_all_statuses` (R2 y R3 se leen del estado que ese
paso acaba de persistir) y ANTES del despachador (que manda lo que este paso
crea). Como el resumen: una transacción por empresa, y la falla de una se
registra y no tumba el job.

**Qué decide y qué no.** Este paso decide QUÉ hecho hay que avisar y a quién,
y lo registra con `service.record_event` — que decide la base legal, el
apagado y el rezago, igual que para todo lo demás. La hora hábil y el tope de
la Ley 2300 NO se miran acá: son del despachador, en un solo lugar (§14).

**Tres decisiones que el código tomó sobre el diseño** (detalle en §20):

1. **Un evento por (cliente, día, tipo)**, con todos los contratos adentro
   (§2.3). Por eso la llave es `<tipo>:<customer_id>:<día objetivo>` y no la
   de §6.1 por contrato: una llave por contrato hace imposible juntar dos
   contratos en un correo. La propiedad que §6.1 buscaba —la llave cambia
   cuando el ancla cambia— se conserva, porque el día objetivo de R2 y R3 se
   DERIVA del ancla (`contracts.integration`).
2. **El día del vencimiento es UN aviso.** `months_owed` pasa de 0 a 1 el
   mismo día en que vence la cuota, así que ese día el contrato entra en mora
   (o en prórroga, con ventana 1). Si el evento de estado está encendido, él
   lleva el contrato; si no, lo lleva R1 «vence hoy». Es `choose_event` de
   las fases 4 y 6 (§18.1-3) aplicado a los recordatorios. **De fábrica ya
   no pasa** —R1 sale solo 3 días antes desde el 25/09/2026—, pero el 0 sigue
   siendo configurable por empresa, y ahí el choque vuelve.
3. **La ventana de búsqueda es de 7 días hacia atrás**, re-evaluada cada
   noche; la `dedupe_key` hace que re-evaluar sea gratis (§6.2). Si el job
   estuvo caído, lo que cayó dentro de los 7 días se registra y el rezago
   (§5.3) decide si todavía es noticia (`pending`) o ya no (`skipped_stale`):
   el rastro de la caída queda en la base. Lo anterior a 7 días no se registra.
"""

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tenant_time import DEFAULT_TIMEZONE, today_in
from app.core.db import AsyncSessionLocal
from app.modules.contracts import integration as contracts_integration
from app.modules.contracts.integration import ReminderContract
from app.modules.notifications import preferences, repository, service
from app.modules.notifications.preferences import ReminderSchedule

logger = logging.getLogger(__name__)

INSTALLMENT_DUE_SOON = "installment_due_soon"  # R1
INSTALLMENT_OVERDUE = "installment_overdue"  # R2
EXTENSION_STARTED = "extension_started"  # R3
EXTENSION_ENDING_SOON = "extension_ending_soon"  # R4

#: El prefijo de la `dedupe_key` de cada uno (§6.1, con la forma de §20.3-1).
KEY_PREFIX = {
    INSTALLMENT_DUE_SOON: "due_soon",
    INSTALLMENT_OVERDUE: "arrears",
    EXTENSION_STARTED: "extension",
    EXTENSION_ENDING_SOON: "extension_ending",
}

#: Igual que el resumen (`digest.MAX_LOOKBACK_DAYS`): más atrás no se busca.
MAX_LOOKBACK_DAYS = 7


def reminder_key(event_type: str, customer_id: UUID, target_date: date) -> str:
    """La FECHA OBJETIVO, nunca la de corrida (§6.1): correr dos veces la misma
    noche, o tres días tarde, da la misma llave; el mes siguiente, otra."""
    return f"{KEY_PREFIX[event_type]}:{customer_id}:{target_date.isoformat()}"


@dataclass(frozen=True)
class PlannedReminder:
    event_type: str
    customer_id: UUID
    #: El día en que el aviso tenía que salir. Es la fecha de la ventana de
    #: rezago (`notification_event.target_date`, §5.3).
    target_date: date
    contracts: tuple[dict[str, Any], ...]
    contract_ids: tuple[UUID, ...]

    @property
    def dedupe_key(self) -> str:
        return reminder_key(self.event_type, self.customer_id, self.target_date)

    def payload(self) -> dict[str, Any]:
        """Lo MÍNIMO para redactar (§9.1): número, fechas y montos. Ni prenda,
        ni cédula; el nombre de pila se resuelve al enviar."""
        return {"contracts": [dict(c) for c in self.contracts]}


def _row(c: ReminderContract, event_type: str) -> dict[str, Any]:
    row: dict[str, Any] = {"number": c.number}
    if event_type == INSTALLMENT_DUE_SOON:
        row["due_date"] = c.next_due_date.isoformat()
        row["amount"] = str(c.monthly_interest)
    elif event_type == INSTALLMENT_OVERDUE:
        assert c.arrears_entered_on is not None
        row["due_date"] = c.arrears_entered_on.isoformat()
        row["amount"] = str(max(c.amount_to_catch_up, c.monthly_interest))
    else:
        assert c.extension_ends_at is not None
        row["extension_ends_at"] = c.extension_ends_at.isoformat()
        row["amount"] = str(max(c.amount_to_catch_up, c.monthly_interest))
    # §9.1: en los recordatorios agrupados, el saldo por contrato.
    row["capital_balance"] = str(c.capital_balance)
    return row


def _state_event_on_due_day(c: ReminderContract) -> str:
    """El evento de estado que nace el día del vencimiento: mora, o prórroga
    directa si la ventana de mora es de un mes (tecnología)."""
    return INSTALLMENT_OVERDUE if c.arrears_window_months > 1 else EXTENSION_STARTED


def plan_reminders(
    contracts: Sequence[ReminderContract],
    *,
    today: date,
    schedule: ReminderSchedule,
    lookback_days: int,
    event_enabled: Callable[[str], bool],
) -> list[PlannedReminder]:
    """Puro: qué eventos de recordatorio corresponden a los días
    `[today - lookback_days, today]`. Ordenados por día, tipo y cliente."""
    first = today - timedelta(days=lookback_days)
    groups: dict[tuple[str, UUID, date], list[ReminderContract]] = {}

    def add(event_type: str, c: ReminderContract, day: date) -> None:
        if first <= day <= today:
            groups.setdefault((event_type, c.customer_id, day), []).append(c)

    for c in contracts:
        # R1: la próxima cuota, N días antes (N = 0 es el día del vencimiento:
        # no viene de fábrica, pero una empresa lo puede configurar).
        for days_before in schedule.installment_days_before:
            day = c.next_due_date - timedelta(days=days_before)
            if days_before == 0 and event_enabled(_state_event_on_due_day(c)):
                continue  # ese día el aviso lo lleva el evento de estado
            add(INSTALLMENT_DUE_SOON, c, day)
        # R2: el día en que entró en mora.
        if c.status == "in_arrears" and c.arrears_entered_on is not None:
            add(INSTALLMENT_OVERDUE, c, c.arrears_entered_on)
        if c.status == "in_extension":
            # R3: el día en que entró en prórroga.
            if c.extension_entered_on is not None:
                add(EXTENSION_STARTED, c, c.extension_entered_on)
            # R4: N días antes de que la prórroga venza.
            if c.extension_ends_at is not None:
                for days_before in schedule.extension_days_before:
                    add(EXTENSION_ENDING_SOON, c, c.extension_ends_at - timedelta(days=days_before))

    planned = []
    for (event_type, customer_id, day), members in groups.items():
        members = sorted(members, key=lambda m: m.number)
        planned.append(
            PlannedReminder(
                event_type=event_type,
                customer_id=customer_id,
                target_date=day,
                contracts=tuple(_row(m, event_type) for m in members),
                contract_ids=tuple(m.contract_id for m in members),
            )
        )
    planned.sort(key=lambda p: (p.target_date, p.event_type, str(p.customer_id)))
    return planned


@dataclass
class ReminderRunStats:
    companies: int = 0
    #: Eventos NUEVOS (los que ya existían —otra corrida la misma noche— no cuentan).
    events: int = 0
    errors: int = 0
    deliveries: dict[str, int] = field(default_factory=dict)

    def add(self, counts: dict[str, int]) -> None:
        for k, v in counts.items():
            self.deliveries[k] = self.deliveries.get(k, 0) + v


async def build_company_reminders(
    db: AsyncSession, *, company: Row[Any], now: datetime, stats: ReminderRunStats
) -> None:
    m = company._mapping
    company_id: UUID = m["id"]
    settings = m["settings"] or {}
    today = today_in(settings.get("timezone") or DEFAULT_TIMEZONE, now=now)
    prefs = preferences.parse(settings)
    contracts = await contracts_integration.list_reminder_contracts(
        db, company_id=company_id, today=today
    )
    planned = plan_reminders(
        contracts,
        today=today,
        schedule=prefs.reminders,
        # Tiene que mirar más atrás que el rezago: si no, un job caído no
        # dejaría ni el `skipped_stale` que dice que estuvo caído.
        lookback_days=max(MAX_LOOKBACK_DAYS, prefs.stale_after_days + 1),
        event_enabled=prefs.event_enabled,
    )
    for p in planned:
        outcome = await service.record_event(
            db,
            company_id=company_id,
            event_type=p.event_type,
            dedupe_key=p.dedupe_key,
            occurred_on=today,
            today=today,
            prefs=prefs,
            payload=p.payload(),
            customer_id=p.customer_id,
            entity_type="customer",
            entity_id=p.customer_id,
            target_date=p.target_date,
        )
        if outcome.created:
            stats.events += 1
            stats.add(outcome.deliveries)


async def build_all_reminders(
    *, now: datetime | None = None, only_company_ids: list[UUID] | None = None
) -> ReminderRunStats:
    """Las mismas empresas que el resumen: activas y con suscripción vigente.

    `only_company_ids` existe para los tests: aísla la corrida de las demás
    empresas de la base local."""
    now = now or datetime.now(UTC)
    stats = ReminderRunStats()
    async with AsyncSessionLocal() as db:
        companies = await repository.list_digest_companies(db, only=only_company_ids)
    for company in companies:
        stats.companies += 1
        try:
            async with AsyncSessionLocal() as db, db.begin():
                await build_company_reminders(db, company=company, now=now, stats=stats)
        except Exception:
            stats.errors += 1
            logger.exception("recordatorios_empresa_fallo: company_id=%s", company._mapping["id"])
    return stats
