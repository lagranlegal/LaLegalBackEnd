"""Funciones de integración que otros módulos pueden llamar directamente
(CLAUDE.md regla 2: un módulo no importa el service de otro).

`platform.service.create_company_defaults` usa `invite_user` para el primer
admin de una empresa nueva.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity import auth_admin, repository


async def invite_user(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    email: str,
    full_name: str,
    invited_by: UUID | None = None,
    send_email: bool = True,
) -> tuple[UUID, str | None]:
    invitation = await auth_admin.invite_user(email, full_name, send_email=send_email)
    user_id = invitation.user_id
    await repository.insert_app_user(
        db,
        user_id=user_id,
        company_id=company_id,
        role_id=role_id,
        full_name=full_name,
        email=email,
    )
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
        after={
            "email": email,
            "role_id": str(role_id),
            "delivery": "email" if send_email else "link",
        },
    )
    return user_id, invitation.link
