from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.security import CurrentUser
from app.core.security import get_role_permissions as get_cached_role_permissions
from app.modules.identity import integration, repository
from app.modules.identity.schemas import (
    MeCompanyOut,
    MeOut,
    MePlanOut,
    MeRoleOut,
    MeSubscriptionOut,
    MeUserOut,
    PermissionOut,
    RoleOut,
    UserOut,
)
from app.modules.platform import repository as platform_repo

_ADMIN_PERMISSION = "identity.manage_roles"


def _row_to_user(row: Row[Any]) -> UserOut:
    m = row._mapping
    return UserOut(
        id=m["id"],
        full_name=m["full_name"],
        email=m["email"],
        role_id=m["role_id"],
        status=m["status"],
        created_at=m["created_at"],
    )


def _row_to_role(row: Row[Any]) -> RoleOut:
    m = row._mapping
    return RoleOut(
        id=m["id"],
        name=m["name"],
        description=m["description"],
        is_seed=m["is_seed"],
        active=m["active"],
    )


async def list_users(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[UserOut]:
    rows = await repository.list_users(db, company_id=company_id, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_user(r) for r in page.items], next_cursor=page.next_cursor)


async def invite_user(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    email: str,
    full_name: str,
    invited_by: UUID,
) -> UserOut:
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol indicado no existe en esta empresa.")

    user_id = await integration.invite_user(
        db,
        company_id=company_id,
        role_id=role_id,
        email=email,
        full_name=full_name,
        invited_by=invited_by,
    )
    row = await repository.get_user(db, company_id=company_id, user_id=user_id)
    assert row is not None
    return _row_to_user(row)


async def _role_has_admin_permission(db: AsyncSession, role_id: UUID) -> bool:
    codes = await repository.role_permission_codes(db, role_id=role_id)
    return _ADMIN_PERMISSION in codes


async def update_user_role(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, new_role_id: UUID, acting_user_id: UUID
) -> UserOut:
    user = await repository.get_user(db, company_id=company_id, user_id=user_id)
    if user is None:
        raise NotFoundError("El usuario no existe en esta empresa.")
    new_role = await repository.get_role(db, company_id=company_id, role_id=new_role_id)
    if new_role is None:
        raise NotFoundError("El rol indicado no existe en esta empresa.")

    old_role_id = user._mapping["role_id"]
    if old_role_id != new_role_id and await _role_has_admin_permission(db, old_role_id):
        if not await _role_has_admin_permission(db, new_role_id):
            remaining = await repository.count_active_admins(
                db, company_id=company_id, exclude_user_id=user_id
            )
            if remaining == 0:
                raise ConflictError(
                    "No se puede quitar el último administrador activo de la empresa.",
                    code="LAST_ADMIN_SAFEGUARD",
                )

    await repository.update_user_role(
        db, company_id=company_id, user_id=user_id, role_id=new_role_id
    )
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="update_user_role",
        entity_type="app_user",
        entity_id=user_id,
        before={"role_id": str(old_role_id)},
        after={"role_id": str(new_role_id)},
    )
    row = await repository.get_user(db, company_id=company_id, user_id=user_id)
    assert row is not None
    return _row_to_user(row)


async def _set_user_active_status(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, active: bool, acting_user_id: UUID
) -> None:
    user = await repository.get_user(db, company_id=company_id, user_id=user_id)
    if user is None:
        raise NotFoundError("El usuario no existe en esta empresa.")

    if not active and await _role_has_admin_permission(db, user._mapping["role_id"]):
        remaining = await repository.count_active_admins(
            db, company_id=company_id, exclude_user_id=user_id
        )
        if remaining == 0:
            raise ConflictError(
                "No se puede inactivar al último administrador activo de la empresa.",
                code="LAST_ADMIN_SAFEGUARD",
            )

    new_status = "active" if active else "inactive"
    await repository.set_user_status(db, company_id=company_id, user_id=user_id, status=new_status)
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="reactivate_user" if active else "deactivate_user",
        entity_type="app_user",
        entity_id=user_id,
        before={"status": user._mapping["status"]},
        after={"status": new_status},
    )


async def deactivate_user(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, acting_user_id: UUID
) -> None:
    await _set_user_active_status(
        db, company_id=company_id, user_id=user_id, active=False, acting_user_id=acting_user_id
    )


async def reactivate_user(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, acting_user_id: UUID
) -> None:
    await _set_user_active_status(
        db, company_id=company_id, user_id=user_id, active=True, acting_user_id=acting_user_id
    )


async def list_roles(db: AsyncSession, *, company_id: UUID) -> list[RoleOut]:
    rows = await repository.list_roles(db, company_id=company_id)
    return [_row_to_role(r) for r in rows]


async def create_role(
    db: AsyncSession,
    *,
    company_id: UUID,
    name: str,
    description: str | None,
    clone_from_role_id: UUID | None,
    acting_user_id: UUID,
) -> RoleOut:
    if clone_from_role_id is not None:
        source = await repository.get_role(db, company_id=company_id, role_id=clone_from_role_id)
        if source is None:
            raise NotFoundError("El rol a clonar no existe en esta empresa.")

    role_id = uuid4()
    await repository.insert_role(
        db, role_id=role_id, company_id=company_id, name=name, description=description
    )
    if clone_from_role_id is not None:
        await repository.copy_role_permissions(
            db, source_role_id=clone_from_role_id, target_role_id=role_id
        )
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="create_role",
        entity_type="role",
        entity_id=role_id,
        after={"name": name, "clone_from_role_id": str(clone_from_role_id or "")},
    )
    row = await repository.get_role(db, company_id=company_id, role_id=role_id)
    assert row is not None
    return _row_to_role(row)


async def rename_role(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    name: str,
    description: str | None,
    acting_user_id: UUID,
) -> RoleOut:
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol no existe en esta empresa.")
    await repository.update_role_name(
        db, company_id=company_id, role_id=role_id, name=name, description=description
    )
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="rename_role",
        entity_type="role",
        entity_id=role_id,
        before={"name": role._mapping["name"]},
        after={"name": name},
    )
    row = await repository.get_role(db, company_id=company_id, role_id=role_id)
    assert row is not None
    return _row_to_role(row)


async def get_role_permissions(db: AsyncSession, *, company_id: UUID, role_id: UUID) -> list[str]:
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol no existe en esta empresa.")
    return await repository.role_permission_codes(db, role_id=role_id)


async def update_role_permissions(
    db: AsyncSession,
    *,
    company_id: UUID,
    role_id: UUID,
    codes: list[str],
    acting_user_id: UUID,
) -> list[str]:
    role = await repository.get_role(db, company_id=company_id, role_id=role_id)
    if role is None:
        raise NotFoundError("El rol no existe en esta empresa.")

    catalog = {row._mapping["code"] for row in await repository.list_permissions(db)}
    unknown = set(codes) - catalog
    if unknown:
        raise AppError(
            "Hay códigos de permiso que no existen en el catálogo.",
            details={"unknown_codes": sorted(unknown)},
        )

    before_codes = await repository.role_permission_codes(db, role_id=role_id)
    if _ADMIN_PERMISSION in before_codes and _ADMIN_PERMISSION not in codes:
        remaining = await repository.count_other_active_admins(
            db, company_id=company_id, excluding_role_id=role_id
        )
        if remaining == 0:
            raise ConflictError(
                "No se puede quitar 'identity.manage_roles' del último rol con administradores.",
                code="LAST_ADMIN_SAFEGUARD",
            )

    await repository.set_role_permissions(db, role_id=role_id, codes=codes)
    await repository.insert_audit_log(
        db,
        company_id=company_id,
        user_id=acting_user_id,
        module="identity",
        action="update_role_permissions",
        entity_type="role",
        entity_id=role_id,
        before={"permission_codes": sorted(before_codes)},
        after={"permission_codes": sorted(codes)},
    )
    return await repository.role_permission_codes(db, role_id=role_id)


async def list_permissions(db: AsyncSession) -> list[PermissionOut]:
    rows = await repository.list_permissions(db)
    return [
        PermissionOut(
            id=r._mapping["id"],
            code=r._mapping["code"],
            module=r._mapping["module"],
            action=r._mapping["action"],
            is_special=r._mapping["is_special"],
            description=r._mapping["description"],
        )
        for r in rows
    ]


async def get_me(db: AsyncSession, *, user: CurrentUser) -> MeOut:
    """El front no puede saber qué puede hacer el usuario logueado sin esto:
    `GET /identity/roles/{id}/permissions` exige `identity.manage_roles`, que
    un Asesor no tiene. Devuelve exactamente el mismo set de permisos
    (mismo cache TTL 60s) que `require_permission` va a aceptar o rechazar.
    """
    role_row = await repository.get_role(db, company_id=user.company_id, role_id=user.role_id)
    if role_row is None:
        raise NotFoundError("El rol del usuario no existe en esta empresa.")

    company_row = await platform_repo.get_company_profile(db, company_id=user.company_id)
    if company_row is None:
        raise NotFoundError("La empresa no existe.")

    subscription_row = await platform_repo.get_active_subscription_with_plan(
        db, company_id=user.company_id
    )
    if subscription_row is None:
        raise NotFoundError("La empresa no tiene una suscripción activa.")

    permissions = await get_cached_role_permissions(db, user.role_id)

    cm = company_row._mapping
    sm = subscription_row._mapping
    return MeOut(
        user=MeUserOut(id=user.id, full_name=user.full_name, email=user.email),
        company=MeCompanyOut(
            id=cm["id"],
            name=cm["name"],
            timezone=(cm["settings"] or {}).get("timezone", "America/Bogota"),
            logo_url=cm["logo_url"],
        ),
        role=MeRoleOut(id=role_row._mapping["id"], name=role_row._mapping["name"]),
        permissions=permissions,
        subscription=MeSubscriptionOut(status=sm["status"], expires_at=sm["expires_at"]),
        plan=MePlanOut(code=sm["plan_code"], name=sm["plan_name"]),
    )
