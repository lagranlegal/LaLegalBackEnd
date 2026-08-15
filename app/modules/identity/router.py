from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, decode_cursor
from app.core.security import CurrentUser, get_tenant_db, require_permission
from app.modules.identity import service
from app.modules.identity.schemas import (
    InviteUserIn,
    PermissionOut,
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


@router.post("/invitations", response_model=UserOut, status_code=201)
async def invite_user(
    body: InviteUserIn,
    user: Annotated[CurrentUser, Depends(_manage_users)],
    db: Annotated[AsyncSession, Depends(get_tenant_db)],
) -> UserOut:
    return await service.invite_user(
        db,
        company_id=user.company_id,
        role_id=body.role_id,
        email=body.email,
        full_name=body.full_name,
        invited_by=user.id,
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
