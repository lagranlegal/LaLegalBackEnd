"""Reglas del módulo de avisos: registrar un hecho y decidir sus entregas, y
leer/cambiar las preferencias de la empresa.

**Un aviso es la consecuencia de un hecho que ya quedó registrado, nunca un
hecho nuevo** (docs/NOTIFICACIONES.md). De ahí `record_event`: escribe el
evento SIEMPRE —aunque esté apagado, aunque no haya por dónde avisar— y decide
cuántas entregas nacen y en qué estado. Lo que NO decide acá es la hora ni el
tope de contactos: eso es del despachador, en un solo lugar (§14).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_time_page
from app.core.errors import AppError, NotFoundError
from app.core.settings import get_settings
from app.modules.identity import repository as identity_repo
from app.modules.notifications import catalog, preferences, repository
from app.modules.notifications.preferences import NotificationPrefs
from app.modules.notifications.schemas import (
    ContactLimitsOut,
    DeliveryOut,
    DigestRecipientOut,
    EventTypeSettingOut,
    NotificationSettingsOut,
    NotificationSettingsUpdateIn,
    ThresholdsOut,
)

#: Qué permiso hace destinatario a un usuario, por familia de evento (§4.3).
_RECIPIENT_PERMISSION = {
    "digest": "notifications.receive_digest",
    "alert": "notifications.receive_alerts",
}


@dataclass(frozen=True)
class RecordOutcome:
    #: `False` = la llave ya existía: el hecho ya estaba registrado (§6.2).
    created: bool
    event_id: UUID | None
    deliveries: dict[str, int]
    #: Las entregas que nacieron `pending`: las que un productor transaccional
    #: puede mandar ya, después del commit (§5.1), sin esperar al job.
    pending_ids: tuple[UUID, ...] = ()


def is_stale(*, target_date: date | None, today: date, stale_after_days: int) -> bool:
    """§5.3: un aviso cuya fecha objetivo quedó más de N días atrás ya no es
    noticia. Sin fecha objetivo, el aviso no caduca."""
    return target_date is not None and (today - target_date).days > stale_after_days


async def record_event(
    db: AsyncSession,
    *,
    company_id: UUID,
    event_type: str,
    dedupe_key: str,
    occurred_on: date,
    today: date,
    prefs: NotificationPrefs,
    payload: dict[str, Any] | None = None,
    customer_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    target_date: date | None = None,
    deliver: bool = True,
    recipient_email: str | None = None,
    recipient_user_id: UUID | None = None,
) -> RecordOutcome:
    """Registra el hecho y planifica sus entregas en la MISMA transacción.

    `deliver=False` registra el hecho sin entregas: es el resumen diario vacío
    (§12.2-2) o el que ya va dentro del semanal. Queda la fila —y con ella el
    latido de "¿corrió anoche?" (§5.3)— pero no sale correo.

    `recipient_email`/`recipient_user_id` solo para `audience='platform'`: ahí
    el destinatario no sale de un permiso ni de un cliente, lo trae el
    productor (la invitación sabe a quién invitó).
    """
    et = catalog.get(event_type)
    event_id = await repository.insert_event(
        db,
        company_id=company_id,
        event_type=event_type,
        audience=et.audience,
        dedupe_key=dedupe_key,
        occurred_on=occurred_on,
        payload=payload or {},
        customer_id=customer_id,
        entity_type=entity_type,
        entity_id=entity_id,
        target_date=target_date,
    )
    if event_id is None:
        return RecordOutcome(created=False, event_id=None, deliveries={})

    # §4.3: apagado = el evento existe, la entrega no se crea.
    if not deliver or not prefs.event_enabled(event_type):
        return RecordOutcome(created=True, event_id=event_id, deliveries={})

    counts: dict[str, int] = {}
    pending: list[UUID] = []

    async def _add(to: str | None, status: str, user_id: UUID | None, error: str | None) -> None:
        delivery_id = await repository.insert_delivery(
            db,
            company_id=company_id,
            event_id=event_id,
            to_address=to,
            recipient_user_id=user_id,
            status=status,
            last_error=error,
        )
        counts[status] = counts.get(status, 0) + 1
        if delivery_id is not None and status == "pending":
            pending.append(delivery_id)

    stale = is_stale(target_date=target_date, today=today, stale_after_days=prefs.stale_after_days)

    if et.audience == "company":
        permission = _RECIPIENT_PERMISSION.get(et.family)
        if permission != "notifications.receive_digest":
            # Las alertas (fase 7) todavía no tienen productor: nada que planificar.
            return RecordOutcome(created=True, event_id=event_id, deliveries={})
        for user in await repository.list_digest_recipients(db, company_id=company_id):
            m = user._mapping
            await _add(m["email"], "skipped_stale" if stale else "pending", m["id"], None)
        return RecordOutcome(created=True, event_id=event_id, deliveries=counts)

    if et.audience == "customer":
        contact = (
            await repository.get_customer_contact(
                db, company_id=company_id, customer_id=customer_id
            )
            if customer_id
            else None
        )
        email = (contact._mapping["email"] or "").strip() if contact else ""
        if not email:
            # §1: el caso NORMAL. Se registra, no se omite.
            await _add(None, "unroutable", None, None)
        elif not catalog.basis_allows(et.purpose, None):
            # §9.2-c: sin base legal registrada no sale nada. `customer.email_basis`
            # llega en la fase 3; hasta entonces todo cliente está en este caso.
            await _add(
                email,
                "suppressed",
                None,
                "El cliente no tiene base legal registrada para esta finalidad.",
            )
        elif stale:
            await _add(email, "skipped_stale", None, None)
        else:
            await _add(email, "pending", None, None)
        return RecordOutcome(created=True, event_id=event_id, deliveries=counts)

    # audience='platform' (P1, §16): un destinatario, el que trae el productor.
    # Sin rezago (no tiene fecha objetivo), sin límites de la Ley 2300 (no es un
    # deudor) y sin base legal que cruzar: es la cuenta que esa persona va a usar.
    if not recipient_email:
        return RecordOutcome(created=True, event_id=event_id, deliveries={})
    await _add(recipient_email, "pending", recipient_user_id, None)
    return RecordOutcome(
        created=True, event_id=event_id, deliveries=counts, pending_ids=tuple(pending)
    )


# ------------------------------------------------------------ preferencias ----


def _limits_out(prefs: NotificationPrefs) -> ContactLimitsOut:
    d = prefs.customer_contact_limits.as_dict()
    return ContactLimitsOut(
        enabled=d["enabled"],
        max_per_week=d["max_per_week"],
        max_per_day=d["max_per_day"],
        weekday_hours=tuple(d["weekday_hours"]),
        saturday_hours=tuple(d["saturday_hours"]),
        sundays_and_holidays=d["sundays_and_holidays"],
    )


async def _settings_out(
    db: AsyncSession, *, company_id: UUID, prefs: NotificationPrefs
) -> NotificationSettingsOut:
    recipients = await repository.list_digest_recipients(db, company_id=company_id)
    return NotificationSettingsOut(
        enabled=prefs.enabled,
        provider_configured=bool(get_settings().resend_api_key),
        events=[
            EventTypeSettingOut(
                code=et.code,
                audience=et.audience,
                purpose=et.purpose,
                family=et.family,
                description=et.description,
                default_enabled=et.default_enabled,
                enabled=prefs.event_setting(et.code),
                overridden=et.code in prefs.events,
                effective=prefs.event_enabled(et.code),
            )
            for et in catalog.EVENT_TYPES.values()
        ],
        thresholds=ThresholdsOut(
            discount_amount=prefs.discount_threshold,
            cash_difference_amount=prefs.cash_difference_threshold,
        ),
        customer_contact_limits=_limits_out(prefs),
        stale_after_days=prefs.stale_after_days,
        digest_recipients=[
            DigestRecipientOut(
                user_id=r._mapping["id"],
                full_name=r._mapping["full_name"],
                email=r._mapping["email"],
            )
            for r in recipients
        ],
    )


async def _load_prefs(db: AsyncSession, *, company_id: UUID) -> tuple[Row[Any], NotificationPrefs]:
    row = await repository.get_company(db, company_id=company_id)
    if row is None:
        raise NotFoundError("La empresa no existe.")
    return row, preferences.parse(row._mapping["settings"])


async def get_settings_for_company(
    db: AsyncSession, *, company_id: UUID
) -> NotificationSettingsOut:
    _, prefs = await _load_prefs(db, company_id=company_id)
    return await _settings_out(db, company_id=company_id, prefs=prefs)


def _validate_event_codes(events: dict[str, bool | None]) -> None:
    unknown = sorted(code for code in events if code not in catalog.EVENT_TYPES)
    if unknown:
        raise AppError(
            "Hay eventos que no existen en el catálogo.",
            details={"unknown": unknown},
            code="NOTIFICATION_EVENT_UNKNOWN",
        )
    platform = sorted(code for code in events if catalog.get(code).audience == "platform")
    if platform:
        # Los correos de la plataforma (invitación) no son de la empresa: la
        # contraparte es Prendo (§8), así que no se apagan desde un inquilino.
        raise AppError(
            "Los avisos de la plataforma no se configuran por empresa.",
            details={"events": platform},
            code="NOTIFICATION_EVENT_NOT_CONFIGURABLE",
        )


async def update_settings_for_company(
    db: AsyncSession, *, company_id: UUID, body: NotificationSettingsUpdateIn, actor_id: UUID
) -> NotificationSettingsOut:
    _, before = await _load_prefs(db, company_id=company_id)
    stored_before = preferences.to_settings(before)
    data = dict(stored_before)

    if body.enabled is not None:
        data["enabled"] = body.enabled
    if body.events is not None:
        _validate_event_codes(body.events)
        events = dict(before.events)
        for code, value in body.events.items():
            if value is None:
                events.pop(code, None)
            else:
                events[code] = value
        data["events"] = events
    if body.thresholds is not None:
        thresholds = dict(data["thresholds"])
        for key, value in body.thresholds.model_dump(exclude_none=True).items():
            thresholds[key] = str(value)
        data["thresholds"] = thresholds
    if body.customer_contact_limits is not None:
        limits = dict(data["customer_contact_limits"])
        for key, value in body.customer_contact_limits.model_dump(exclude_none=True).items():
            limits[key] = list(value) if isinstance(value, tuple) else value
        data["customer_contact_limits"] = limits
    if body.stale_after_days is not None:
        data["stale_after_days"] = body.stale_after_days

    after = preferences.parse({"notifications": data})
    stored_after = preferences.to_settings(after)
    if stored_after != stored_before:
        await repository.update_notification_settings(db, company_id=company_id, value=stored_after)
        # §7: encender o apagar los avisos es un cambio de política con
        # consecuencias hacia afuera — se audita con el antes y el después, que
        # acá son pocos datos y son justo lo que alguien va a preguntar.
        changed = sorted(k for k in stored_after if stored_after[k] != stored_before.get(k))
        await identity_repo.insert_audit_log(
            db,
            company_id=company_id,
            user_id=actor_id,
            module="notifications",
            action="update_settings",
            entity_type="company",
            entity_id=company_id,
            before={k: stored_before.get(k) for k in changed},
            after={"changed_fields": changed, **{k: stored_after[k] for k in changed}},
        )
    return await _settings_out(db, company_id=company_id, prefs=after)


# ------------------------------------------------------------------ entregas ----


def _row_to_delivery(row: Row[Any]) -> DeliveryOut:
    m = row._mapping
    return DeliveryOut(
        id=m["id"],
        event_id=m["event_id"],
        event_type=m["event_type"],
        audience=m["audience"],
        occurred_on=m["occurred_on"],
        channel=m["channel"],
        to_address=m["to_address"],
        recipient_user_id=m["recipient_user_id"],
        status=m["status"],
        attempts=m["attempts"],
        last_error=m["last_error"],
        provider_id=m["provider_id"],
        scheduled_at=m["scheduled_at"],
        sent_at=m["sent_at"],
        created_at=m["created_at"],
        updated_at=m["updated_at"],
    )


async def list_deliveries(
    db: AsyncSession,
    *,
    company_id: UUID,
    cursor: Any,
    limit: int,
    status: str | None,
    event_type: str | None,
) -> CursorPage[DeliveryOut]:
    rows = await repository.list_deliveries(
        db,
        company_id=company_id,
        cursor=cursor,
        limit=limit,
        status=status,
        event_type=event_type,
    )
    page = make_time_page(rows, limit, lambda r: (r._mapping["created_at"], r._mapping["id"]))
    return CursorPage(items=[_row_to_delivery(r) for r in page.items], next_cursor=page.next_cursor)
