"""Funciones de integración que otros módulos pueden llamar directamente
(CLAUDE.md regla 2: un módulo no importa el service de otro).

- `platform.service.create_company_defaults` usa `invite_user` para el primer
  admin de una empresa nueva.
- `notifications.dispatcher` usa `fresh_invitation_link` cuando el job tiene
  que reintentar el correo de una invitación (docs/NOTIFICACIONES.md §16).
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import get_settings
from app.modules.identity import auth_admin, repository
from app.modules.notifications import integration as notifications

#: Cómo le llegó (o le va a llegar) el enlace a la persona. Queda en el
#: `audit_log` y vuelve en la respuesta: es lo único que dice por dónde buscar
#: cuando alguien reporta «no me llegó».
#:
#: - `link`: lo entrega el admin a mano («Generar enlace»). No sale correo.
#: - `email`: correo de Prendo (Resend), con el enlace de la app (§16).
#: - `email_supabase`: correo de Supabase Auth, como antes de la fase 2. Solo
#:   cuando la plataforma no tiene con qué mandar el suyo.
InviteDelivery = Literal["link", "email", "email_supabase"]


@dataclass(frozen=True)
class InvitationEmail:
    """Lo que hace falta para mandar el correo YA, después del commit.

    `link` es una credencial: vive solo en memoria, de acá al `BackgroundTasks`.
    """

    delivery_id: UUID
    link: str


@dataclass(frozen=True)
class InvitationResult:
    user_id: UUID
    #: Solo en modo `link`: lo que el admin le pasa a la persona.
    admin_link: str | None
    delivery: InviteDelivery
    #: Solo en modo `email`: la entrega a mandar después del commit.
    email: InvitationEmail | None = None


def _choose_delivery(send_email: bool) -> InviteDelivery:
    """Se decide ANTES de llamar a Supabase, porque la llamada misma cambia:
    `/invite` manda el correo de Supabase, `/admin/generate_link` no manda nada.

    El correo propio exige las dos piezas: un proveedor (`RESEND_API_KEY`) y
    `FRONTEND_URL`, sin la cual no hay enlace a prueba de escáneres que armar
    (`auth_admin.invitation_email_link`). Si falta cualquiera, la invitación NO
    queda muda: vuelve al correo de Supabase de siempre, con sus límites
    conocidos (`INVITE_RATE_LIMITED`) — que es peor, pero es un correo.
    """
    if not send_email:
        return "link"
    if notifications.email_provider_configured() and get_settings().frontend_url:
        return "email"
    return "email_supabase"


async def invite_user(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    email: str,
    full_name: str,
    invited_by: UUID | None = None,
    send_email: bool = True,
) -> InvitationResult:
    delivery = _choose_delivery(send_email)
    invitation = await auth_admin.invite_user(
        email, full_name, send_email=delivery == "email_supabase"
    )
    user_id = invitation.user_id
    await repository.insert_app_user(
        db,
        user_id=user_id,
        company_id=company_id,
        role_id=role_id,
        full_name=full_name,
        email=email,
    )

    pending: InvitationEmail | None = None
    if delivery == "email":
        link = (
            auth_admin.invitation_email_link(invitation.hashed_token)
            if invitation.hashed_token
            else None
        )
        if link is None:
            # No debería pasar: `generate_link` siempre trae `hashed_token` y
            # `FRONTEND_URL` se comprobó arriba. Si pasa, el admin tiene que
            # enterarse de que el correo no va a salir, y lo más útil es darle
            # el enlace para entregarlo a mano en vez de dejar la invitación muda.
            delivery = "link"
        else:
            delivery_id = await notifications.record_user_invitation(
                db,
                company_id=company_id,
                user_id=user_id,
                email=email,
                invited_at=invitation.invited_at,
            )
            if delivery_id is not None:
                pending = InvitationEmail(delivery_id=delivery_id, link=link)

    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=invited_by,
        module="identity",
        action="invite_user",
        entity_type="app_user",
        entity_id=user_id,
        # Queda registrado CÓMO se entregó: un enlace copiado a mano no deja
        # rastro en ningún servidor de correo, así que el audit_log es el
        # único lugar donde consta que esa invitación existió y quién la hizo.
        # El enlace en sí NUNCA: el audit_log lo lee cualquiera con `audit.view`.
        after={"email": email, "role_id": str(role_id), "delivery": delivery},
    )
    return InvitationResult(
        user_id=user_id,
        admin_link=invitation.link if delivery == "link" else None,
        delivery=delivery,
        email=pending,
    )


@dataclass(frozen=True)
class FreshInvitationLink:
    link: str | None = None
    #: Si no hay enlace: ¿vale la pena reintentar más tarde?
    retryable: bool = False
    #: Si no hay enlace y no se reintenta: el estado final de la entrega.
    final_status: str | None = None
    error: str | None = None


async def fresh_invitation_link(
    *, user_id: UUID, email: str, full_name: str
) -> FreshInvitationLink:
    """Un enlace de invitación NUEVO para una cuenta que ya existe (§16).

    Lo pide el job cuando el correo inmediato no salió: el token de entonces no
    se guardó, y aunque se hubiera guardado ya estaría vencido
    (`otp_expiry`, 1 h por defecto en Supabase).

    Se regenera con `type=invite`, NO con `recovery`, aunque «Generar enlace»
    use `recovery` para rescatar a un invitado: verificado contra GoTrue que
    cada tipo invalida SOLO sus propios tokens anteriores. Si el job regenerara
    `recovery`, mataría el enlace que el admin quizá ya mandó por WhatsApp
    mientras el correo esperaba — y P2 no se toca (§2.6).
    """
    if not get_settings().frontend_url:
        return FreshInvitationLink(
            final_status="dead",
            error="Falta FRONTEND_URL: no hay enlace seguro que poner en el correo.",
        )
    try:
        # Antes de `generate_link`: con `type=invite` sobre una cuenta borrada
        # desde el panel, GoTrue no falla — crea OTRA cuenta, huérfana.
        if not await auth_admin.auth_user_exists(user_id):
            return FreshInvitationLink(
                final_status="dead",
                error="La cuenta de acceso ya no existe en Supabase Auth "
                "(AUTH_ACCOUNT_MISSING): hay que desactivar e invitar de nuevo.",
            )
        invitation = await auth_admin.invite_user(email, full_name, send_email=False)
    except auth_admin.EmailAlreadyRegisteredError:
        # GoTrue: 422 `email_exists` = la persona ya puso su contraseña (aunque
        # todavía no haya hecho ningún request que la pase a `active`).
        return FreshInvitationLink(
            final_status="suppressed",
            error="La persona ya activó su cuenta: la invitación no aplica.",
        )
    except auth_admin.InviteRateLimitedError:
        return FreshInvitationLink(retryable=True, error="Supabase: INVITE_RATE_LIMITED (429)")
    except auth_admin.AuthAdminError as exc:
        status = (exc.details or {}).get("status_code")
        return FreshInvitationLink(retryable=True, error=f"Supabase: AUTH_ADMIN_ERROR ({status})")

    if invitation.user_id != user_id:
        # Con la comprobación de arriba no debería pasar; si pasa, no se manda
        # un enlace que entra a OTRA cuenta.
        return FreshInvitationLink(
            final_status="dead",
            error="Supabase devolvió otra cuenta para ese correo: no se envía.",
        )
    link = (
        auth_admin.invitation_email_link(invitation.hashed_token)
        if invitation.hashed_token
        else None
    )
    if link is None:
        return FreshInvitationLink(
            retryable=True, error="Supabase no devolvió el token de la invitación."
        )
    return FreshInvitationLink(link=link)
