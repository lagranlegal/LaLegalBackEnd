"""El despachador: toma las entregas `pending`/`failed` cuya hora llegó y las
manda (docs/NOTIFICACIONES.md §5, §6.3, §12.3).

Es el ÚNICO lugar donde se deciden la hora y el tope de contactos al cliente
(§14: "un punto de verdad"). Ningún productor de eventos los mira.

Orden de decisión por entrega, y el porqué del orden:

1. **Ventana de rezago** (§5.3) → `skipped_stale`. Primero, porque un aviso
   que ya no es noticia no debe consumir cupo ni esperar horario.
2. **Límites al cliente** (Ley 2300, §12.3), solo `audience='customer'`:
   fuera de horario → se corre al próximo momento hábil (sigue `pending`);
   tope semanal/diario alcanzado → `throttled`.
3. **Sin proveedor** → `skipped_no_provider`. El job NO falla: registra.
4. **Envío**, FUERA de toda transacción (§5.1). Éxito → `sent`; falla
   reintentable → `failed` con backoff +1 h / +6 h / +24 h, y al cuarto
   intento `dead`; falla permanente → `dead`.

`bounced`/`delivered` los escribirá el webhook de Resend (fase posterior): el
estado ya existe en la tabla para no necesitar migración ese día.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common.tenant_time import DEFAULT_TIMEZONE, today_in
from app.core.db import AsyncSessionLocal
from app.core.settings import get_settings
from app.modules.notifications import limits, preferences, repository, service, templates
from app.modules.notifications.providers import EmailMessage, EmailProvider

logger = logging.getLogger(__name__)

#: §6.3: 3 reintentos, a la +1 h, +6 h y +24 h. Al cuarto intento fallido, `dead`.
RETRY_BACKOFF = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))
MAX_ATTEMPTS = len(RETRY_BACKOFF) + 1
STUCK_SENDING_AFTER = timedelta(hours=1)


@dataclass
class DispatchStats:
    claimed: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    rescheduled: int = 0

    def bump(self, status: str) -> None:
        self.by_status[status] = self.by_status.get(status, 0) + 1


def _zone(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


@dataclass(frozen=True)
class _Prepared:
    message: EmailMessage | None
    #: Si ya se decidió un estado final sin enviar (stale, throttled, …).
    final_status: str | None = None
    error: str | None = None
    reschedule_to: datetime | None = None


async def _prepare(delivery: Any, *, now: datetime) -> _Prepared:
    """Todo lo que se decide leyendo la base, en una transacción corta."""
    d = delivery._mapping
    async with AsyncSessionLocal() as db, db.begin():
        event = await repository.get_event(db, event_id=d["event_id"])
        company = await repository.get_company(db, company_id=d["company_id"])
        if event is None or company is None:
            return _Prepared(None, "dead", "El evento o la empresa ya no existen.")
        e = event._mapping
        c = company._mapping
        settings = c["settings"] or {}
        tz_name = settings.get("timezone") or DEFAULT_TIMEZONE
        prefs = preferences.parse(settings)
        today = today_in(tz_name, now=now)

        if service.is_stale(
            target_date=e["target_date"], today=today, stale_after_days=prefs.stale_after_days
        ):
            return _Prepared(None, "skipped_stale")

        # Si la empresa apagó el aviso (o todos) después de planificarlo, lo
        # pendiente no sale: apagar tiene que surtir efecto ya, no mañana.
        if not prefs.event_enabled(e["event_type"]):
            return _Prepared(None, "suppressed", "El aviso está apagado para la empresa.")

        if e["audience"] == "customer":
            contact_limits = prefs.customer_contact_limits
            local_now = now.astimezone(_zone(tz_name))
            next_ok = limits.next_allowed_moment(local_now, contact_limits)
            if next_ok > local_now:
                return _Prepared(None, reschedule_to=next_ok.astimezone(UTC))
            sent_week = await repository.count_sent_to(
                db, company_id=c["id"], to_address=d["to_address"], since=now - timedelta(days=7)
            )
            sent_day = await repository.count_sent_to(
                db, company_id=c["id"], to_address=d["to_address"], since=now - timedelta(days=1)
            )
            if limits.exceeds_cap(
                sent_last_day=sent_day, sent_last_week=sent_week, limits=contact_limits
            ):
                return _Prepared(None, "throttled", "Tope de contactos al cliente alcanzado.")

        payload: dict[str, Any] = dict(e["payload"] or {})
        if e["audience"] == "customer" and e["customer_id"] is not None:
            customer = await repository.get_customer_contact(
                db, company_id=c["id"], customer_id=e["customer_id"]
            )
            # Solo el nombre de pila, y se resuelve al enviar: el payload
            # guardado no lleva datos personales (§9.1).
            if customer is not None:
                payload["first_name"] = customer._mapping["full_name"]

        documents = settings.get("documents") or {}
        branding = templates.Branding(
            company_name=c["name"],
            contact_email=c["contact_email"],
            contact_phone=c["contact_phone"],
            footer_note=documents.get("footer_note"),
        )
        try:
            rendered = templates.render(e["event_type"], payload, branding)
        except (KeyError, ValueError) as exc:
            return _Prepared(None, "dead", f"No se pudo redactar: {exc}")

    return _Prepared(
        EmailMessage(
            from_header=templates.from_header(
                rendered.from_name, get_settings().notifications_from_address
            ),
            to=d["to_address"],
            subject=rendered.subject,
            html=rendered.html,
            text=rendered.text,
            reply_to=rendered.reply_to,
            idempotency_key=f"delivery-{d['id']}",
        )
    )


async def _finish(delivery_id: UUID, **fields: Any) -> None:
    async with AsyncSessionLocal() as db, db.begin():
        await repository.update_delivery(db, delivery_id=delivery_id, **fields)


async def _dispatch_one(
    delivery: Any, *, provider: EmailProvider, now: datetime, stats: DispatchStats
) -> None:
    d = delivery._mapping
    prepared = await _prepare(delivery, now=now)

    if prepared.reschedule_to is not None:
        await _finish(d["id"], status="pending", scheduled_at=prepared.reschedule_to)
        stats.rescheduled += 1
        stats.bump("pending")
        return
    if prepared.final_status is not None or prepared.message is None:
        status = prepared.final_status or "dead"
        await _finish(d["id"], status=status, last_error=prepared.error)
        stats.bump(status)
        return

    # Fuera de toda transacción (§5.1): un proveedor lento no retiene nada.
    result = await provider.send(prepared.message)

    if result.not_configured:
        await _finish(d["id"], status="skipped_no_provider", last_error=result.error)
        stats.bump("skipped_no_provider")
        return
    attempts = d["attempts"] + 1
    if result.ok:
        await _finish(
            d["id"],
            status="sent",
            attempts=attempts,
            provider_id=result.provider_id,
            sent_at=now,
        )
        stats.bump("sent")
        return
    if result.retryable and attempts < MAX_ATTEMPTS:
        await _finish(
            d["id"],
            status="failed",
            attempts=attempts,
            last_error=result.error,
            scheduled_at=now + RETRY_BACKOFF[attempts - 1],
        )
        stats.bump("failed")
        return
    await _finish(d["id"], status="dead", attempts=attempts, last_error=result.error)
    stats.bump("dead")


async def dispatch_due(
    *,
    provider: EmailProvider,
    now: datetime | None = None,
    batch_size: int = 200,
    only_company_ids: list[UUID] | None = None,
) -> DispatchStats:
    """`only_company_ids` existe para los tests (aislar de la base local)."""
    now = now or datetime.now(UTC)
    stats = DispatchStats()
    async with AsyncSessionLocal() as db, db.begin():
        await repository.release_stuck_sending(db, older_than=now - STUCK_SENDING_AFTER)

    while True:
        async with AsyncSessionLocal() as db, db.begin():
            claimed = await repository.claim_due_deliveries(
                db, now=now, limit=batch_size, only=only_company_ids
            )
        if not claimed:
            break
        stats.claimed += len(claimed)
        for delivery in claimed:
            try:
                await _dispatch_one(delivery, provider=provider, now=now, stats=stats)
            except Exception as exc:
                # Una entrega rota no detiene a las demás ni tumba el job.
                logger.exception("entrega_fallo: delivery_id=%s", delivery._mapping["id"])
                attempts = delivery._mapping["attempts"] + 1
                status = "failed" if attempts < MAX_ATTEMPTS else "dead"
                await _finish(
                    delivery._mapping["id"],
                    status=status,
                    attempts=attempts,
                    last_error=f"error interno: {type(exc).__name__}",
                    scheduled_at=now + RETRY_BACKOFF[min(attempts, len(RETRY_BACKOFF)) - 1],
                )
                stats.bump(status)
        if len(claimed) < batch_size:
            break
    return stats
