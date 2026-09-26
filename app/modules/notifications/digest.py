"""Tercer paso del job nocturno: el resumen a la empresa (docs/NOTIFICACIONES.md
§2.4, §5.2, §12.2-2).

Corre DESPUÉS de `recompute_all_statuses`: lee el estado de los contratos que
ese paso acaba de persistir. Invertirlos manda "entró en mora" con un día de
retraso.

**El período.** Cada corrida reporta lo que pasó desde la corrida anterior:
`after` es el día de la última corrida registrada (o ayer, la primera vez; y
nunca más de 7 días atrás). El movimiento cubre los días completos
`[after, hoy-1]`; los cambios de estado, `(after, hoy]`. Así un día que el job
no corrió no se pierde, y un día no se reporta dos veces.

**Diario vs. semanal (§12.2-2).** El diario sale SOLO si hubo actividad o
alertas. El semanal sale siempre, el lunes (o en la primera corrida de la
semana si el lunes no hubo): prueba que el sistema vive sin entrenar a la gente
a archivar. El día que sale el semanal, el diario va adentro y no se manda
aparte — dos correos el mismo día con lo mismo son uno de más.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tenant_time import DEFAULT_TIMEZONE, today_in
from app.core.db import AsyncSessionLocal
from app.modules.contracts import integration as contracts_integration
from app.modules.notifications import catalog, preferences, repository, service
from app.modules.notifications.preferences import NotificationPrefs
from app.modules.reports import integration as reports_integration

logger = logging.getLogger(__name__)

#: E8 (§2.4): avisos de vencimiento de la suscripción, en días antes.
SUBSCRIPTION_MILESTONES = (15, 7, 1)
MAX_LOOKBACK_DAYS = 7
_LIST_CAP = 30


@dataclass
class DigestRunStats:
    companies: int = 0
    daily_sent: int = 0
    daily_empty: int = 0
    weekly: int = 0
    already_done: int = 0
    customer_events: int = 0
    errors: int = 0
    deliveries: dict[str, int] = field(default_factory=dict)

    def add(self, counts: dict[str, int]) -> None:
        for k, v in counts.items():
            self.deliveries[k] = self.deliveries.get(k, 0) + v


def daily_key(company_id: UUID, day: date) -> str:
    return f"digest:{company_id}:{day.isoformat()}"


def weekly_key(company_id: UUID, week_start: date) -> str:
    return f"weekly_digest:{company_id}:{week_start.isoformat()}"


def auction_ready_key(contract_id: UUID, extension_ends_at: date) -> str:
    """§2.2-a: anclada al ancla del contrato, como todas las de estado (§6.1)."""
    return f"auction_ready:{contract_id}:{extension_ends_at.isoformat()}"


def subscription_milestone_crossed(*, expires_at: date, after: date, today: date) -> int | None:
    """El hito de E8 (15/7/1) que se cruzó en `(after, today]`, o None.

    Por cruce y no por igualdad: si el job no corrió justo el día 7, el aviso
    sale en la siguiente corrida en vez de perderse. Si se cruzaron varios, gana
    el más urgente.
    """
    crossed = [
        m for m in SUBSCRIPTION_MILESTONES if after < expires_at - timedelta(days=m) <= today
    ]
    return min(crossed) if crossed else None


def _above(amount: Decimal, threshold: Decimal) -> bool:
    return abs(amount) > threshold


async def _sections(
    db: AsyncSession,
    *,
    company_id: UUID,
    tz: str,
    today: date,
    after: date,
    prefs: NotificationPrefs,
    expires_at: date | None,
    weekly: bool,
) -> tuple[dict[str, Any], bool, bool, list[contracts_integration.ReadyForAuction]]:
    """Arma el payload. Devuelve (payload, hay_alertas, hay_actividad, listos)."""
    act_from = today - timedelta(days=7) if weekly else after
    act_to = today - timedelta(days=1)
    if act_from > act_to:
        act_from = act_to

    ready = await contracts_integration.list_ready_for_auction(
        db, company_id=company_id, today=today
    )
    ready_rows = [
        {
            "number": r.number,
            "extension_ends_at": r.extension_ends_at.isoformat(),
            "new": r.extension_ends_at >= after,
        }
        for r in ready
    ]
    new_ready = sum(1 for r in ready_rows if r["new"])
    # Los nuevos primero: son la noticia; los viejos, el recordatorio.
    ready_rows.sort(key=lambda r: (not r["new"], r["extension_ends_at"]))

    arrears, extension = await contracts_integration.list_state_entries(
        db, company_id=company_id, after=after, until=today
    )

    unclosed = await repository.unclosed_sessions(db, company_id=company_id, today=today)
    new_unclosed = [s for s in unclosed if s._mapping["session_date"] >= after]

    diffs = await repository.cash_differences(
        db, company_id=company_id, tz=tz, date_from=act_from, date_to=act_to
    )
    discount_rows = await repository.discounts(
        db, company_id=company_id, tz=tz, date_from=act_from, date_to=act_to
    )
    activity = await repository.activity_totals(
        db, company_id=company_id, tz=tz, date_from=act_from, date_to=act_to
    )
    dead = await repository.dead_deliveries_count(
        db, company_id=company_id, tz=tz, date_from=act_from, date_to=act_to
    )

    subscription: dict[str, Any] | None = None
    milestone = None
    if expires_at is not None:
        milestone = subscription_milestone_crossed(expires_at=expires_at, after=after, today=today)
        days_left = (expires_at - today).days
        if milestone is not None or (weekly and 0 <= days_left <= max(SUBSCRIPTION_MILESTONES)):
            subscription = {"expires_at": expires_at.isoformat(), "days_left": days_left}

    payload: dict[str, Any] = {
        "kind": "weekly" if weekly else "daily",
        "day": today.isoformat(),
        "period": {"from": act_from.isoformat(), "to": act_to.isoformat()},
        "activity": activity,
        "ready_for_auction": {
            "total": len(ready_rows),
            "new": new_ready,
            "contracts": ready_rows[:_LIST_CAP],
        },
        "entered_arrears": [
            {"number": e.number, "since": e.entered_on.isoformat()} for e in arrears[:_LIST_CAP]
        ],
        "entered_arrears_total": len(arrears),
        "entered_extension": [
            {
                "number": e.number,
                "extension_ends_at": e.extension_ends_at.isoformat()
                if e.extension_ends_at
                else None,
            }
            for e in extension[:_LIST_CAP]
            if e.extension_ends_at
        ],
        "entered_extension_total": len(extension),
        "unclosed_cash": [
            {"session_date": s._mapping["session_date"].isoformat()} for s in unclosed
        ],
        "cash_differences": [
            {
                "session_date": d._mapping["session_date"].isoformat(),
                "difference": str(d._mapping["difference"]),
                "reason": d._mapping["difference_reason"],
                "above_threshold": _above(
                    Decimal(d._mapping["difference"]), prefs.cash_difference_threshold
                ),
            }
            for d in diffs
        ],
        "discounts": [
            {
                "kind": d._mapping["kind"],
                "number": d._mapping["number"],
                "amount": str(d._mapping["amount"]),
                "above_threshold": prefs.above_discount_threshold(Decimal(d._mapping["amount"])),
            }
            for d in discount_rows
        ],
        "subscription": subscription,
        "dead_deliveries": dead,
    }
    if weekly:
        payload["stale_inventory"] = await reports_integration.get_stale_inventory_summary(
            db, company_id=company_id
        )
        payload["payables"] = await reports_integration.get_payables_summary(
            db, company_id=company_id
        )

    has_alerts = bool(
        new_ready
        or arrears
        or extension
        or new_unclosed
        or diffs
        or discount_rows
        or milestone is not None
        or dead
    )
    has_activity = bool(
        activity["contracts_created"]
        or activity["payments"]
        or activity["sales"]
        or activity["sales_voided"]
    )
    return payload, has_alerts, has_activity, ready


async def build_company_digest(
    db: AsyncSession, *, company: Row[Any], now: datetime, stats: DigestRunStats
) -> None:
    m = company._mapping
    company_id: UUID = m["id"]
    settings = m["settings"] or {}
    tz = settings.get("timezone") or DEFAULT_TIMEZONE
    today = today_in(tz, now=now)
    prefs = preferences.parse(settings)

    if await repository.event_exists(
        db, company_id=company_id, dedupe_key=daily_key(company_id, today)
    ):
        stats.already_done += 1
        return

    previous = await repository.last_event_day(
        db, company_id=company_id, event_types=[catalog.DAILY_DIGEST, catalog.WEEKLY_DIGEST]
    )
    floor = today - timedelta(days=MAX_LOOKBACK_DAYS)
    after = max(previous, floor) if previous is not None else today - timedelta(days=1)

    week_start = today - timedelta(days=today.weekday())
    weekly_due = not await repository.event_exists(
        db, company_id=company_id, dedupe_key=weekly_key(company_id, week_start)
    )

    payload, has_alerts, has_activity, ready = await _sections(
        db,
        company_id=company_id,
        tz=tz,
        today=today,
        after=after,
        prefs=prefs,
        expires_at=m["subscription_expires_at"],
        weekly=weekly_due,
    )

    if weekly_due:
        outcome = await service.record_event(
            db,
            company_id=company_id,
            event_type=catalog.WEEKLY_DIGEST,
            dedupe_key=weekly_key(company_id, week_start),
            occurred_on=today,
            today=today,
            prefs=prefs,
            payload=payload,
            entity_type="company",
            entity_id=company_id,
            target_date=today,
        )
        stats.weekly += 1
        stats.add(outcome.deliveries)
        daily_payload: dict[str, Any] = {"day": today.isoformat(), "folded_into_weekly": True}
        daily_deliver = False
    else:
        daily_payload = payload
        daily_deliver = has_alerts or has_activity
        daily_payload["has_alerts"] = has_alerts
        daily_payload["has_activity"] = has_activity

    # El diario se registra SIEMPRE, salga o no: es el latido del job (§5.3)
    # y la marca de hasta dónde llegó el período de la próxima corrida.
    outcome = await service.record_event(
        db,
        company_id=company_id,
        event_type=catalog.DAILY_DIGEST,
        dedupe_key=daily_key(company_id, today),
        occurred_on=today,
        today=today,
        prefs=prefs,
        payload=daily_payload,
        entity_type="company",
        entity_id=company_id,
        target_date=today,
        deliver=daily_deliver,
    )
    stats.add(outcome.deliveries)
    if not weekly_due:
        if daily_deliver:
            stats.daily_sent += 1
        else:
            stats.daily_empty += 1

    # R5 al cliente (§2.2-a): el MISMO recorrido de E1, un destinatario más. El
    # evento se registra siempre; si está apagado (default) no nace entrega.
    for r in ready:
        customer_outcome = await service.record_event(
            db,
            company_id=company_id,
            event_type=catalog.AUCTION_READY_CUSTOMER,
            dedupe_key=auction_ready_key(r.contract_id, r.extension_ends_at),
            occurred_on=today,
            today=today,
            prefs=prefs,
            payload={
                "contract_number": r.number,
                "extension_ends_at": r.extension_ends_at.isoformat(),
            },
            customer_id=r.customer_id,
            entity_type="contract",
            entity_id=r.contract_id,
            # Se volvió "listo" el día siguiente al fin de la prórroga.
            target_date=r.extension_ends_at + timedelta(days=1),
        )
        if customer_outcome.created:
            stats.customer_events += 1
            stats.add(customer_outcome.deliveries)


async def build_all_digests(
    *, now: datetime | None = None, only_company_ids: list[UUID] | None = None
) -> DigestRunStats:
    """Una transacción por empresa: la falla de una no revierte las demás, y el
    aviso nunca tumba el job (el principio del documento: la consecuencia no
    puede hacer fallar lo que la originó).

    `only_company_ids` existe para los tests: aísla la corrida de las demás
    empresas de la base local."""
    now = now or datetime.now(UTC)
    stats = DigestRunStats()
    async with AsyncSessionLocal() as db:
        companies = await repository.list_digest_companies(db, only=only_company_ids)
    for company in companies:
        stats.companies += 1
        try:
            async with AsyncSessionLocal() as db, db.begin():
                await build_company_digest(db, company=company, now=now, stats=stats)
        except Exception:
            stats.errors += 1
            logger.exception("resumen_empresa_fallo: company_id=%s", company._mapping["id"])
    return stats
