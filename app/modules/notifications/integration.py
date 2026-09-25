"""Funciones de integración de `notifications` para otros módulos
(CLAUDE.md regla 2: un módulo no importa el service de otro).

Las usan `identity` para la invitación de usuario (P1, docs/NOTIFICACIONES.md
§16) y, desde las fases 4 y 6 (§18), `contracts` y `sales` para los avisos
transaccionales al cliente (C1–C7). En los dos casos el aviso se registra
DENTRO de la transacción del documento, y el envío inmediato no está acá sino
en `dispatcher.send_after_commit`, que el router llama al FINAL del endpoint.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tenant_time import DEFAULT_TIMEZONE, today_in
from app.modules.notifications import preferences, providers, repository, service
from app.modules.notifications.preferences import NotificationPrefs

USER_INVITATION = "user_invitation"


def email_provider_configured() -> bool:
    """¿La plataforma tiene con qué mandar correo? (`RESEND_API_KEY`).

    Se decide ANTES de pedirle nada a Supabase: si no hay proveedor, la
    invitación tiene que salir por el correo de Supabase de siempre, y eso se
    pide en la misma llamada que crea la cuenta (`/invite` en vez de
    `/admin/generate_link`). Descubrirlo después dejaría una cuenta creada con
    un enlace que nadie va a recibir.
    """
    return providers.get_default_provider().name != providers.NullProvider.name


def invitation_dedupe_key(user_id: UUID, invited_at: str | None) -> str:
    """§6.1: la llave se construye con lo que hace única a la invitación.

    El usuario solo NO alcanza: invitar otra vez a la misma persona (hoy lo
    bloquea `USER_ALREADY_INVITED`, pero un «reenviar invitación» es la
    evolución obvia) es un hecho NUEVO, y una llave `invitation:<usuario>` se
    lo tragaría en silencio por el `on conflict do nothing`. `invited_at` lo
    pone GoTrue en cada invitación (respuesta real de `generate_link`), así que
    la misma invitación da la misma llave y la siguiente da otra.
    """
    return f"invitation:{user_id}:{invited_at}" if invited_at else f"invitation:{user_id}"


async def record_user_invitation(
    db: AsyncSession,
    *,
    company_id: UUID,
    user_id: UUID,
    email: str,
    invited_at: str | None,
) -> UUID | None:
    """Registra la invitación y su entrega `pending`, en la transacción de quien
    llama. Devuelve el id de la entrega para mandarla ya, después del commit;
    None si esa misma invitación ya estaba registrada.

    El payload va VACÍO a propósito: el nombre de la persona se lee de
    `app_user` al enviar, y el enlace —una credencial que vence en minutos—
    nunca se guarda (§16).
    """
    company = await repository.get_company(db, company_id=company_id)
    settings = (company._mapping["settings"] if company else None) or {}
    today = today_in(settings.get("timezone") or DEFAULT_TIMEZONE)
    outcome = await service.record_event(
        db,
        company_id=company_id,
        event_type=USER_INVITATION,
        dedupe_key=invitation_dedupe_key(user_id, invited_at),
        occurred_on=today,
        today=today,
        # Las preferencias de la empresa no deciden nada acá (`event_enabled`
        # ignora el interruptor para la plataforma); se pasan las de defecto
        # para no leer de más.
        prefs=NotificationPrefs(),
        payload={},
        entity_type="app_user",
        entity_id=user_id,
        recipient_email=email,
        recipient_user_id=user_id,
    )
    return outcome.pending_ids[0] if outcome.pending_ids else None


# ------------------------------------------ avisos transaccionales al cliente ----


def choose_event(prefs: NotificationPrefs, preferred: str, instead_of: str | None) -> str:
    """Un hecho, un aviso (§18.1-3): cuando un mismo documento cabe en dos
    eventos —el abono que salda el contrato es un abono (C2) Y un paz y salvo
    (C3); la devolución liquidada en nota es una devolución (C7) Y una nota
    crédito (C5)—, sale UNO: el más específico, que además carga los datos del
    otro.

    Salvo que la empresa lo haya apagado y dejado encendido el general: apagar
    el paz y salvo no puede dejar al último abono sin su comprobante. Con los
    dos apagados se registra el específico, que es el hecho que pasó."""
    if instead_of is None:
        return preferred
    if not prefs.event_enabled(preferred) and prefs.event_enabled(instead_of):
        return instead_of
    return preferred


async def record_customer_notice(
    db: AsyncSession,
    *,
    company_id: UUID,
    customer_id: UUID | None,
    event_type: str,
    dedupe_key: str,
    entity_type: str,
    entity_id: UUID,
    payload: dict[str, Any],
    instead_of: str | None = None,
) -> UUID | None:
    """Registra un aviso transaccional al cliente EN LA TRANSACCIÓN de quien
    llama, y devuelve la entrega que nació `pending` —para mandarla ya, después
    del commit, con `dispatcher.send_after_commit`— o None.

    Se llama al FINAL de la operación, después del documento, la caja y la
    auditoría: si algo de eso falla, el aviso ni se escribe; y si falla algo
    después, se revierte con todo lo demás (§5.1).

    - **Sin cliente no hay evento** (§2.1: una venta de mostrador no tiene a
      quién avisarle, y eso no es un hueco). Con cliente sin correo sí: el
      evento y una entrega `unroutable` (§1).
    - **La llave es el documento** (§6.1) y la pone quien llama: un reintento
      con el mismo `Idempotency-Key` no llega acá (el servicio devuelve el
      documento que ya existía), y si llegara, `on conflict do nothing`.
    - **`payload`: montos, números y fechas del documento, nunca la prenda ni
      los artículos** (§9.1). Los montos van como texto, tal como los guardó
      el documento: la plantilla formatea, no calcula.
    - `instead_of`: ver `choose_event`.
    """
    if customer_id is None:
        return None
    company = await repository.get_company(db, company_id=company_id)
    settings = (company._mapping["settings"] if company else None) or {}
    prefs = preferences.parse(settings)
    today = today_in(settings.get("timezone") or DEFAULT_TIMEZONE)
    outcome = await service.record_event(
        db,
        company_id=company_id,
        event_type=choose_event(prefs, event_type, instead_of),
        dedupe_key=dedupe_key,
        occurred_on=today,
        today=today,
        prefs=prefs,
        payload=payload,
        customer_id=customer_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return outcome.pending_ids[0] if outcome.pending_ids else None
