"""Funciones de integración de `notifications` para otros módulos
(CLAUDE.md regla 2: un módulo no importa el service de otro).

Hoy las usa `identity` para la invitación de usuario (P1, docs/NOTIFICACIONES.md
§16): saber si hay por dónde mandarla, y registrarla DENTRO de la transacción
de la invitación. El envío inmediato no está acá sino en
`dispatcher.dispatch_delivery`, que corre después del commit.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.tenant_time import DEFAULT_TIMEZONE, today_in
from app.modules.notifications import providers, repository, service
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
