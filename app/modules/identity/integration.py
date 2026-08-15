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
) -> UUID:
    user_id = await auth_admin.invite_user(email, full_name)
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
        after={"email": email, "role_id": str(role_id)},
    )
    return user_id
