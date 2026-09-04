import json
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession


async def find_user_by_email(db: AsyncSession, *, company_id: UUID, email: str) -> Row[Any] | None:
    """El usuario de ESTA empresa con ese correo, si ya existe.

    Sirve para responder "ya está invitado" antes de tocar Supabase Auth, en
    vez de dejar que reviente el índice único de `app_user` y salga un 500.
    """
    result = await db.execute(
        text(
            """
            select id, full_name, email, role_id, status, created_at
            from public.app_user
            where company_id = :company_id and lower(email) = lower(:email)
            """
        ),
        {"company_id": str(company_id), "email": email},
    )
    return result.first()


async def insert_app_user(
    db: AsyncSession,
    *,
    user_id: UUID,
    company_id: UUID,
    role_id: UUID,
    full_name: str,
    email: str,
) -> None:
    await db.execute(
        text(
            """
            insert into public.app_user (id, company_id, role_id, full_name, email, status)
            values (:user_id, :company_id, :role_id, :full_name, :email, 'invited')
            """
        ),
        {
            "user_id": str(user_id),
            "company_id": str(company_id),
            "role_id": str(role_id),
            "full_name": full_name,
            "email": email,
        },
    )


async def list_users(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> list[Row[Any]]:
    query = """
        select id, full_name, email, role_id, status, created_at
        from public.app_user
        where company_id = :company_id
    """
    params: dict[str, Any] = {"company_id": str(company_id), "limit": limit + 1}
    if cursor is not None:
        query += " and id > :cursor"
        params["cursor"] = str(cursor)
    query += " order by id limit :limit"
    result = await db.execute(text(query), params)
    return list(result.all())


async def get_user(db: AsyncSession, *, company_id: UUID, user_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id, full_name, email, photo_url, role_id, status, created_at
            from public.app_user
            where company_id = :company_id and id = :user_id
            """
        ),
        {"company_id": str(company_id), "user_id": str(user_id)},
    )
    return result.first()


async def update_user_role(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, role_id: UUID
) -> None:
    await db.execute(
        text(
            """
            update public.app_user set role_id = :role_id
            where company_id = :company_id and id = :user_id
            """
        ),
        {"company_id": str(company_id), "user_id": str(user_id), "role_id": str(role_id)},
    )


async def set_user_status(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, status: str
) -> None:
    await db.execute(
        text(
            """
            update public.app_user set status = :status
            where company_id = :company_id and id = :user_id
            """
        ),
        {"company_id": str(company_id), "user_id": str(user_id), "status": status},
    )


async def count_active_admins(
    db: AsyncSession, *, company_id: UUID, exclude_user_id: UUID | None = None
) -> int:
    query = """
        select count(*) from public.app_user au
        join public.role r on r.id = au.role_id and r.active
        join public.role_permission rp on rp.role_id = r.id
        join public.permission p on p.id = rp.permission_id and p.code = 'identity.manage_roles'
        where au.company_id = :company_id and au.status = 'active'
    """
    params: dict[str, Any] = {"company_id": str(company_id)}
    if exclude_user_id is not None:
        query += " and au.id != :exclude_user_id"
        params["exclude_user_id"] = str(exclude_user_id)
    result = await db.execute(text(query), params)
    return int(result.scalar_one())


async def count_other_active_admins(
    db: AsyncSession, *, company_id: UUID, excluding_role_id: UUID
) -> int:
    result = await db.execute(
        text(
            """
            select count(*) from public.app_user au
            join public.role r on r.id = au.role_id and r.active
            join public.role_permission rp on rp.role_id = r.id
            join public.permission p
                 on p.id = rp.permission_id and p.code = 'identity.manage_roles'
            where au.company_id = :company_id
              and au.status = 'active'
              and r.id != :excluding_role_id
            """
        ),
        {"company_id": str(company_id), "excluding_role_id": str(excluding_role_id)},
    )
    return int(result.scalar_one())


async def list_roles(db: AsyncSession, *, company_id: UUID) -> list[Row[Any]]:
    result = await db.execute(
        text(
            """
            select r.id, r.name, r.description, r.is_seed, r.active,
                   (select count(*) from public.role_permission rp
                    where rp.role_id = r.id) as permission_count
            from public.role r
            where r.company_id = :company_id
            order by r.name
            """
        ),
        {"company_id": str(company_id)},
    )
    return list(result.all())


async def get_role(db: AsyncSession, *, company_id: UUID, role_id: UUID) -> Row[Any] | None:
    result = await db.execute(
        text(
            """
            select id, name, description, is_seed, active
            from public.role
            where company_id = :company_id and id = :role_id
            """
        ),
        {"company_id": str(company_id), "role_id": str(role_id)},
    )
    return result.first()


async def insert_role(
    db: AsyncSession,
    *,
    role_id: UUID,
    company_id: UUID,
    name: str,
    description: str | None,
    is_seed: bool = False,
) -> None:
    await db.execute(
        text(
            """
            insert into public.role (id, company_id, name, description, is_seed)
            values (:role_id, :company_id, :name, :description, :is_seed)
            """
        ),
        {
            "role_id": str(role_id),
            "company_id": str(company_id),
            "name": name,
            "description": description,
            "is_seed": is_seed,
        },
    )


async def update_role_name(
    db: AsyncSession, *, company_id: UUID, role_id: UUID, name: str, description: str | None
) -> None:
    await db.execute(
        text(
            """
            update public.role set name = :name, description = :description
            where company_id = :company_id and id = :role_id
            """
        ),
        {
            "company_id": str(company_id),
            "role_id": str(role_id),
            "name": name,
            "description": description,
        },
    )


async def role_permission_codes(db: AsyncSession, *, role_id: UUID) -> list[str]:
    result = await db.execute(
        text(
            """
            select p.code from public.role_permission rp
            join public.permission p on p.id = rp.permission_id
            where rp.role_id = :role_id
            order by p.code
            """
        ),
        {"role_id": str(role_id)},
    )
    return [row[0] for row in result]


async def copy_role_permissions(
    db: AsyncSession, *, source_role_id: UUID, target_role_id: UUID
) -> None:
    await db.execute(
        text(
            """
            insert into public.role_permission (role_id, permission_id)
            select :target_role_id, permission_id
            from public.role_permission
            where role_id = :source_role_id
            """
        ),
        {"target_role_id": str(target_role_id), "source_role_id": str(source_role_id)},
    )


async def set_role_permissions(db: AsyncSession, *, role_id: UUID, codes: list[str]) -> None:
    await db.execute(
        text("delete from public.role_permission where role_id = :role_id"),
        {"role_id": str(role_id)},
    )
    if not codes:
        return
    stmt = text(
        """
        insert into public.role_permission (role_id, permission_id)
        select :role_id, id from public.permission where code in :codes
        """
    ).bindparams(bindparam("codes", expanding=True))
    await db.execute(stmt, {"role_id": str(role_id), "codes": codes})


async def list_permissions(db: AsyncSession) -> list[Row[Any]]:
    result = await db.execute(
        text(
            """
            select id, code, module, action, is_special, description
            from public.permission
            order by code
            """
        )
    )
    return list(result.all())


async def insert_audit_log(
    db: AsyncSession,
    *,
    company_id: UUID,
    user_id: UUID | None,
    module: str,
    action: str,
    entity_type: str,
    entity_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        text(
            """
            insert into public.audit_log
                (company_id, user_id, module, action, entity_type, entity_id, before, after)
            values
                (:company_id, :user_id, :module, :action, :entity_type, :entity_id,
                 cast(:before as jsonb), cast(:after as jsonb))
            """
        ),
        {
            "company_id": str(company_id),
            "user_id": str(user_id) if user_id else None,
            "module": module,
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id) if entity_id else None,
            "before": json.dumps(before) if before is not None else None,
            "after": json.dumps(after) if after is not None else None,
        },
    )


async def update_me(
    db: AsyncSession, *, company_id: UUID, user_id: UUID, fields: dict[str, Any]
) -> None:
    """`fields` viene de `MeUpdateIn.model_dump(exclude_unset=True)` en
    service.py — las claves son nombres de columna fijos y conocidos
    (`full_name`, `photo_url`), nunca texto del usuario, así que interpolarlas
    es seguro. Mismo patrón que `customers.update_customer`.

    El `where` lleva `company_id` Y `id`: un usuario solo se edita a sí mismo,
    y el filtro por empresa es la misma defensa en profundidad que el resto
    del repositorio (además de RLS).
    """
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = {**fields, "company_id": str(company_id), "id": str(user_id)}
    await db.execute(
        text(
            f"update public.app_user set {assignments} where company_id = :company_id and id = :id"
        ),
        params,
    )
