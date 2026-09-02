from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_current_user, get_tenant_db, require_permission
from app.modules.identity import service
from app.modules.identity.schemas import (
    InvitedUserOut,
    InviteUserIn,
    MeOut,
    MeUpdateIn,
    PermissionOut,
    RecoveryLinkOut,
    RoleCreateIn,
    RoleOut,
    RolePermissionsIn,
    RoleRenameIn,
    UpdateUserRoleIn,
    UserOut,
)

router = APIRouter(prefix="/api/v1/identity", tags=["identity"])

_manage_users = require_permission("identity.manage_users")
_manage_roles = require_permission("identity.manage_roles")

# Prefijo propio (no /identity): `GET /me` es de cualquier usuario logueado,
# sin depender de un permiso específico — es lo que el front usa para saber
# qué permisos tiene, así que no puede exigir uno él mismo.
router_me = APIRouter(prefix="/api/v1", tags=["me"])


@router_me.get("/me", response_model=MeOut)
async def get_me(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MeOut:
    return await service.get_me(db, user=user)


@router_me.patch("/me", response_model=MeOut)
async def update_me(
    body: MeUpdateIn,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> MeOut:
    """El usuario edita su propio perfil: nombre y foto.

    Sin `require_permission` a propósito, igual que `GET /me`: editarse a uno
    mismo no es gestionar usuarios. Lo que impide que esto sea un agujero es
    el schema — `MeUpdateIn` no acepta `role_id` ni `status`, así que no hay
    forma de ascenderse desde acá (eso sigue exigiendo
    `identity.manage_users` en `PATCH /identity/users/{id}/role`).

    Devuelve el `MeOut` completo y ya actualizado: el front rehidrata su
    estado con la misma respuesta, sin un segundo `GET /me`.
    """
    return await service.update_me(db, user=user, body=body)


@router.get("/users", response_model=CursorPage[UserOut])
async def list_users(
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> CursorPage[UserOut]:
    return await service.list_users(
        db,
        company_id=user.company_id,
        cursor=decode_cursor(cursor) if cursor else None,
        limit=limit,
    )


@router.post("/invitations", response_model=InvitedUserOut, status_code=201)
async def invite_user(
    body: InviteUserIn,
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> InvitedUserOut:
    return await service.invite_user(
        db,
        company_id=user.company_id,
        role_id=body.role_id,
        email=body.email,
        full_name=body.full_name,
        invited_by=user.id,
        send_email=body.send_email,
    )


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: UUID,
    body: UpdateUserRoleIn,
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> UserOut:
    return await service.update_user_role(
        db,
        company_id=user.company_id,
        user_id=user_id,
        new_role_id=body.role_id,
        acting_user_id=user.id,
    )


@router.post("/users/{user_id}/deactivate", status_code=204)
async def deactivate_user(
    user_id: UUID,
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    await service.deactivate_user(
        db, company_id=user.company_id, user_id=user_id, acting_user_id=user.id
    )


@router.post("/users/{user_id}/reactivate", status_code=204)
async def reactivate_user(
    user_id: UUID,
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> None:
    await service.reactivate_user(
        db, company_id=user.company_id, user_id=user_id, acting_user_id=user.id
    )


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    user: Annotated[CurrentUser, Depends(_manage_roles)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[RoleOut]:
    return await service.list_roles(db, company_id=user.company_id)


@router.post("/roles", response_model=RoleOut, status_code=201)
async def create_role(
    body: RoleCreateIn,
    user: Annotated[CurrentUser, Depends(_manage_roles)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> RoleOut:
    return await service.create_role(
        db,
        company_id=user.company_id,
        name=body.name,
        description=body.description,
        clone_from_role_id=body.clone_from_role_id,
        acting_user_id=user.id,
    )


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def rename_role(
    role_id: UUID,
    body: RoleRenameIn,
    user: Annotated[CurrentUser, Depends(_manage_roles)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> RoleOut:
    return await service.rename_role(
        db,
        company_id=user.company_id,
        role_id=role_id,
        name=body.name,
        description=body.description,
        acting_user_id=user.id,
    )


@router.get("/roles/{role_id}/permissions", response_model=list[str])
async def get_role_permissions(
    role_id: UUID,
    user: Annotated[CurrentUser, Depends(_manage_roles)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[str]:
    return await service.get_role_permissions(db, company_id=user.company_id, role_id=role_id)


@router.put("/roles/{role_id}/permissions", response_model=list[str])
async def update_role_permissions(
    role_id: UUID,
    body: RolePermissionsIn,
    user: Annotated[CurrentUser, Depends(_manage_roles)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[str]:
    return await service.update_role_permissions(
        db,
        company_id=user.company_id,
        role_id=role_id,
        codes=body.permission_codes,
        acting_user_id=user.id,
    )


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    user: Annotated[CurrentUser, Depends(_manage_roles)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> list[PermissionOut]:
    return await service.list_permissions(db)


@router.post("/users/{user_id}/recovery-link", response_model=RecoveryLinkOut)
async def generate_recovery_link(
    user_id: UUID,
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> RecoveryLinkOut:
    """Enlace para que un usuario vuelva a poner su contraseña, SIN mandar correo.

    Es el equivalente del "Generar enlace" de la invitación, para el otro caso:
    a alguien se le olvidó la contraseña. Antes eso solo se resolvía por correo,
    y con el SMTP incluido de Supabase —limitado a unos pocos envíos por hora—
    un olvido podía dejar a esa persona afuera sin que nadie pudiera ayudarla.

    **Es una credencial de un solo uso**: quien la tenga puede cambiar esa
    contraseña y entrar como esa persona. Por eso exige `identity.manage_users`,
    queda auditado quién lo generó y para quién, y el enlace no se escribe en
    ningún log.
    """
    return await service.generate_recovery_link(
        db, company_id=user.company_id, user_id=user_id, acting_user_id=user.id
    )
