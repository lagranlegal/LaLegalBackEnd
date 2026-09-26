"""El despachador: toma las entregas `pending`/`failed` cuya hora llegó y las
manda (docs/NOTIFICACIONES.md §5, §6.3, §12.3).

Es el ÚNICO lugar donde se deciden la hora y el tope de contactos al cliente
(§14: "un punto de verdad"). Ningún productor de eventos los mira.

Orden de decisión por entrega, y el porqué del orden:

1. **Ventana de rezago** (§5.3) → `skipped_stale`. Primero, porque un aviso
   que ya no es noticia no debe consumir cupo ni esperar horario.
1-bis. **Base legal, baja y rebote del cliente** (§9.2-c, fase 3) →
   `suppressed`, con el mismo `service.customer_gate` que usó quien la
   planificó: lo que cambió en el medio (una baja por el enlace, una casilla
   desmarcada, un correo corregido) surte efecto antes de enviar. Va antes de
   los límites por la misma razón que el rezago. Acá también se arma el
   enlace de baja: sin él, un correo al cliente no sale (`dead`).
2. **Límites al cliente** (Ley 2300, §12.3), solo `audience='customer'`:
   fuera de horario → se corre al próximo momento hábil (sigue `pending`);
   tope semanal/diario alcanzado → `throttled`. El semanal es de cobranza:
   un comprobante (familia `transactional`) ni lo consume ni lo gasta, salvo
   `transactional_in_weekly_cap` (§18.1-1). La hora y el diario, para todos.
3. **Sin proveedor** → `skipped_no_provider`. El job NO falla: registra.
4. **Envío**, FUERA de toda transacción (§5.1). Éxito → `sent`; falla
   reintentable → `failed` con backoff +1 h / +6 h / +24 h, y al cuarto
   intento `dead`; falla permanente → `dead`.

`bounced`/`delivered` los escribirá el webhook de Resend (fase posterior): el
estado ya existe en la tabla para no necesitar migración ese día.

**La invitación de usuario (P1, §16) tiene un paso propio**, entre 3 y 4: su
enlace es una credencial que vence en minutos y NO se guarda en ninguna fila.
El envío inmediato (`dispatch_delivery`, después del commit) lo recibe en
memoria; el job, que llega horas después, le pide a Supabase uno nuevo para la
misma cuenta — antes de lo cual comprueba que la persona siga `invited` y que
su cuenta de acceso exista.
"""

import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tenant_time import DEFAULT_TIMEZONE, today_in
from app.core.db import AsyncSessionLocal
from app.core.settings import get_settings
from app.modules.identity import integration as identity_integration
from app.modules.notifications import (
    catalog,
    limits,
    preferences,
    providers,
    repository,
    service,
    templates,
    unsubscribe,
)
from app.modules.notifications.providers import EmailMessage, EmailProvider, SendResult

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


INVITATION = "user_invitation"


@dataclass(frozen=True)
class _Prepared:
    message: EmailMessage | None
    #: Si ya se decidió un estado final sin enviar (stale, throttled, …).
    final_status: str | None = None
    error: str | None = None
    reschedule_to: datetime | None = None
    #: Invitación sin enlace en memoria: hay que pedirle uno a Supabase, FUERA
    #: de la transacción de lectura (es una llamada HTTP).
    needs_invite_link: bool = False
    invitee_name: str | None = None
    #: Base legal del cliente con la que sale (§9.2-a): se guarda en la entrega
    #: al enviarla, porque es la de ESE día la que hay que poder mostrar.
    legal_basis: str | None = None


async def _prepare(
    delivery: Any, *, now: datetime, secrets: dict[str, str] | None = None
) -> _Prepared:
    """Todo lo que se decide leyendo la base, en una transacción corta.

    `secrets` es lo que se renderiza pero NUNCA se guarda: hoy, el enlace de la
    invitación. Se mezcla al payload solo en memoria."""
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

        payload: dict[str, Any] = dict(e["payload"] or {})
        legal_basis: str | None = None
        # Cabeceras del correo. Solo las lleva el correo al CLIENTE (§17-bis):
        # el resumen y las alertas van a usuarios de la empresa, que no se
        # «dan de baja» de un enlace sino que se apagan en Configuración (y
        # un clic de Gmail que les apagara el aviso de un faltante de caja
        # sería una pérdida, no un favor); la invitación es un correo único
        # pedido por un admin, no una lista. `List-Unsubscribe` en cualquiera
        # de ellos prometería una salida que no existe.
        mail_headers: dict[str, str] = {}
        if e["audience"] == "customer":
            customer = (
                await repository.get_customer_contact(
                    db, company_id=c["id"], customer_id=e["customer_id"]
                )
                if e["customer_id"] is not None
                else None
            )
            # §9.2-c, OTRA VEZ al enviar: la base, la baja y el rebote se
            # vuelven a mirar. Lo que cambió desde que se planificó (una baja
            # por el enlace, una casilla desmarcada) surte efecto YA.
            gate = service.customer_gate(customer, catalog.get(e["event_type"]).purpose)
            if gate.status != "ok":
                return _Prepared(
                    None,
                    "suppressed",
                    gate.reason or "El cliente ya no tiene correo registrado.",
                )
            if (gate.email or "").lower() != (d["to_address"] or "").strip().lower():
                # La entrega guarda la dirección del día que se planificó. Si
                # el mostrador la corrigió, la vieja puede ser de otra persona
                # (§9.3) y la nueva no es la que se decidió: ninguna.
                return _Prepared(
                    None,
                    "suppressed",
                    "El correo del cliente cambió después de planificar el aviso.",
                )
            legal_basis = gate.basis
            assert customer is not None
            # Solo el nombre de pila, y se resuelve al enviar: el payload
            # guardado no lleva datos personales (§9.1).
            payload["first_name"] = customer._mapping["full_name"]
            # §9.2-e: todo correo al cliente lleva salida. Se arma al enviar
            # y no se guarda: es derivable, y guardarlo sería guardar una
            # credencial (pequeña, pero credencial) en una tabla exportable.
            try:
                payload["unsubscribe_url"] = unsubscribe.unsubscribe_link(
                    company_id=c["id"], customer_id=e["customer_id"]
                )
                # RFC 8058: la baja de un clic de Gmail/Yahoo. Sin URL pública
                # del backend vuelve `{}` y el correo sale igual — la salida
                # obligatoria es el enlace del cuerpo, esto mejora la entrega.
                mail_headers = unsubscribe.list_unsubscribe_headers(
                    company_id=c["id"], customer_id=e["customer_id"]
                )
            except unsubscribe.LinkNotConfigured as exc:
                return _Prepared(
                    None, "dead", f"Sin enlace de baja no sale un correo al cliente: {exc}"
                )

        if e["audience"] == "customer":
            contact_limits = prefs.customer_contact_limits
            local_now = now.astimezone(_zone(tz_name))
            next_ok = limits.next_allowed_moment(local_now, contact_limits)
            if next_ok > local_now:
                return _Prepared(None, reschedule_to=next_ok.astimezone(UTC))
            # §18.1-1: el tope semanal es de cobranza. Un comprobante no lo
            # consume ni lo gasta; el diario (§3) cuenta todo.
            weekly_cobranza_only = not contact_limits.transactional_in_weekly_cap
            sent_week = await repository.count_sent_to(
                db,
                company_id=c["id"],
                to_address=d["to_address"],
                since=now - timedelta(days=7),
                exclude_transactional=weekly_cobranza_only,
            )
            sent_day = await repository.count_sent_to(
                db, company_id=c["id"], to_address=d["to_address"], since=now - timedelta(days=1)
            )
            if limits.exceeds_cap(
                sent_last_day=sent_day,
                sent_last_week=sent_week,
                limits=contact_limits,
                transactional=catalog.get(e["event_type"]).family == "transactional",
            ):
                return _Prepared(None, "throttled", "Tope de contactos al cliente alcanzado.")

        if e["event_type"] == INVITATION:
            user = (
                await repository.get_app_user(
                    db, company_id=c["id"], user_id=d["recipient_user_id"]
                )
                if d["recipient_user_id"] is not None
                else None
            )
            if user is None or user._mapping["status"] != "invited":
                # Mientras el correo esperaba, la persona entró por otro camino
                # («Generar enlace») o la desactivaron. Ya no aplica; y pedir
                # un enlace nuevo sería tocar su cuenta sin motivo.
                return _Prepared(
                    None,
                    "suppressed",
                    "La persona ya activó su cuenta o fue desactivada: la invitación no aplica.",
                )
            payload["invitee_name"] = user._mapping["full_name"]
            link = (secrets or {}).get("invite_link")
            if not link:
                return _Prepared(
                    None, needs_invite_link=True, invitee_name=user._mapping["full_name"]
                )
            payload["invite_link"] = link

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
            headers=mail_headers,
        ),
        legal_basis=legal_basis,
    )


async def _finish(delivery_id: UUID, **fields: Any) -> None:
    async with AsyncSessionLocal() as db, db.begin():
        await repository.update_delivery(db, delivery_id=delivery_id, **fields)


async def _fresh_invite_link(delivery: Any, *, invitee_name: str) -> tuple[str | None, _Prepared]:
    """Pide a Supabase un enlace NUEVO para la invitación (§16). Fuera de toda
    transacción. Devuelve (enlace, desenlace si no hay enlace)."""
    d = delivery._mapping
    fresh = await identity_integration.fresh_invitation_link(
        user_id=d["recipient_user_id"], email=d["to_address"], full_name=invitee_name
    )
    if fresh.link is not None:
        return fresh.link, _Prepared(None)
    if fresh.retryable:
        # Supabase caído o limitando (429): se trata como una falla de envío
        # reintentable, con el mismo contador y el mismo backoff.
        return None, _Prepared(None, final_status="failed", error=fresh.error)
    return None, _Prepared(None, final_status=fresh.final_status or "dead", error=fresh.error)


async def _record_result(
    d: Any,
    result: SendResult,
    *,
    now: datetime,
    stats: DispatchStats,
    legal_basis: str | None = None,
) -> None:
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
            legal_basis=legal_basis,
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


async def _dispatch_one(
    delivery: Any,
    *,
    provider: EmailProvider,
    now: datetime,
    stats: DispatchStats,
    secrets: dict[str, str] | None = None,
) -> None:
    d = delivery._mapping
    prepared = await _prepare(delivery, now=now, secrets=secrets)

    regenerated = False
    if prepared.needs_invite_link:
        if provider.name == providers.NullProvider.name:
            # Sin proveedor no se le pide nada a Supabase: regenerar mataría el
            # enlace anterior para no mandar ninguno.
            await _finish(
                d["id"],
                status="skipped_no_provider",
                last_error="No hay proveedor de correo configurado (RESEND_API_KEY vacía).",
            )
            stats.bump("skipped_no_provider")
            return
        link, outcome = await _fresh_invite_link(delivery, invitee_name=prepared.invitee_name or "")
        if link is None:
            if outcome.final_status == "failed":
                await _record_result(
                    d,
                    SendResult(ok=False, retryable=True, error=outcome.error),
                    now=now,
                    stats=stats,
                )
            else:
                status = outcome.final_status or "dead"
                await _finish(d["id"], status=status, last_error=outcome.error)
                stats.bump(status)
            return
        regenerated = True
        prepared = await _prepare(
            delivery, now=now, secrets={**(secrets or {}), "invite_link": link}
        )

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

    message = prepared.message
    if regenerated:
        # Cada intento con enlace regenerado lleva OTRO token, o sea otro cuerpo.
        # Resend responde 409 `invalid_idempotent_request` si una llave se reusa
        # con otro payload (resend.com/docs, «Idempotency keys»), y eso mandaría
        # la invitación a `dead`. La llave es entonces por intento. El costo,
        # dicho: si un envío anterior sí salió pero el proceso murió antes de
        # registrarlo, la persona recibe dos correos; el último es el que sirve
        # (regenerar mata el token anterior — verificado contra GoTrue).
        message = replace(message, idempotency_key=f"delivery-{d['id']}-a{d['attempts'] + 1}")

    # Fuera de toda transacción (§5.1): un proveedor lento no retiene nada.
    result = await provider.send(message)
    await _record_result(d, result, now=now, stats=stats, legal_basis=prepared.legal_basis)


async def _fail_internal(
    delivery: Any, exc: Exception, *, now: datetime, stats: DispatchStats
) -> None:
    """Una entrega rota no detiene a las demás ni tumba el job."""
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
                await _fail_internal(delivery, exc, now=now, stats=stats)
        if len(claimed) < batch_size:
            break
    return stats


async def dispatch_delivery(
    delivery_id: UUID,
    *,
    secrets: dict[str, str] | None = None,
    provider: EmailProvider | None = None,
    now: datetime | None = None,
) -> str | None:
    """Manda YA una entrega recién creada: el paso 2 de §5.1, para correr en un
    `BackgroundTasks` DESPUÉS del commit de la operación que la creó.

    **La garantía la da el job, esto solo da la velocidad.** Si la máquina se
    apaga a mitad (dev tiene `min_machines_running=0`) o el proveedor falla, la
    entrega queda `pending`/`failed` y el barrido de la noche la retoma. Por eso
    nunca levanta: una excepción acá no tiene a quién llegar — la respuesta ya
    salió.

    `secrets` viaja solo en memoria (hoy, el enlace de la invitación). Devuelve
    el estado en que quedó la entrega, o None si ya la había tomado otro.
    """
    now = now or datetime.now(UTC)
    stats = DispatchStats()
    delivery = None
    try:
        async with AsyncSessionLocal() as db, db.begin():
            delivery = await repository.claim_delivery(db, delivery_id=delivery_id)
        if delivery is None:
            return None
        await _dispatch_one(
            delivery,
            provider=provider or providers.get_default_provider(),
            now=now,
            stats=stats,
            secrets=secrets,
        )
    except Exception as exc:
        if delivery is None:
            logger.exception("envio_inmediato_fallo: delivery_id=%s", delivery_id)
            return None
        try:
            await _fail_internal(delivery, exc, now=now, stats=stats)
        except Exception:
            # Ni siquiera se pudo registrar: queda `sending` y el job la
            # devuelve a `failed` pasada una hora (`release_stuck_sending`).
            logger.exception("envio_inmediato_sin_registro: delivery_id=%s", delivery_id)
            return None
    return next(iter(stats.by_status), None)


async def send_after_commit(
    db: AsyncSession,
    background: BackgroundTasks,
    *delivery_ids: UUID | None,
    secrets: dict[str, str] | None = None,
) -> None:
    """Commit EXPLÍCITO de la operación y, después, el envío en segundo plano
    (§5.1 paso 2; docs/NOTIFICACIONES.md §16).

    El commit no es redundante con la dependencia: en FastAPI 0.141 la salida
    de una dependencia con `yield` (el `session.begin()` de `get_db`, que es
    quien commitea) corre DESPUÉS de las tareas de fondo — las dos viven en el
    mismo `AsyncExitStack` del request, y la respuesta ejecuta sus
    `background` adentro. Sin esto, `dispatch_delivery` busca desde otra
    conexión una entrega que todavía no existe para nadie más, no manda nada,
    y el correo espera al job de la noche. Lo cazó
    `test_invitation_goes_out_through_our_mail_right_after_commit`.

    Llamarlo al FINAL del endpoint: commitear no parte la operación porque ya
    se escribió todo; lo único que queda es serializar la respuesta.

    Acepta varias entregas (fase 7: una alerta a la empresa es una entrega por
    destinatario, y la misma operación puede traer además el aviso al
    cliente): UN commit y una tarea por entrega. Los `None` se ignoran, y sin
    ninguna entrega no commitea — eso lo hace la dependencia, como siempre.
    """
    ids = [d for d in delivery_ids if d is not None]
    if not ids:
        return
    await db.commit()
    for delivery_id in ids:
        background.add_task(dispatch_delivery, delivery_id, secrets=secrets)
