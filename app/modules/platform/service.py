from datetime import date
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.pagination import CursorPage, make_page
from app.core.errors import NotFoundError
from app.modules.identity import integration as identity_integration
from app.modules.identity import repository as identity_repo
from app.modules.platform import integration as platform_integration
from app.modules.platform import repository
from app.modules.platform.schemas import CompanyOut, PlanOut

# Matriz de roles semilla — literal del comentario de seed.sql (referencia
# para create_company_defaults; el admin de cada empresa puede editarla
# después vía identity.update_role_permissions).
_ASESOR_CODES = {
    "contracts.view",
    "contracts.create",
    "payments.create",
    "customers.view",
    "customers.create",
    "inventory.view",
    "sales.create",
    "cashbox.view",
}
_BODEGA_CODES = {
    "inventory.view",
    "inventory.create",
    "catalogs.manage",
    "customers.view",
}
_MODERADOR_EXCLUDED_CODES = {
    "inventory.create",
    "inventory.exit",
    "identity.manage_users",
    "identity.manage_roles",
    "cashbox.open_close",
    "cashbox.reopen",
    "payments.apply_discount",
    "sales.apply_discount",
    "audit.view",
    "company.configure",
    "contracts.import",
}


def build_seed_role_permissions(all_codes: set[str]) -> dict[str, set[str]]:
    return {
        "Admin": set(all_codes),
        "Moderador": all_codes - _MODERADOR_EXCLUDED_CODES,
        "Asesor": _ASESOR_CODES & all_codes,
        "Bodega": _BODEGA_CODES & all_codes,
    }


def _row_to_company(row: Row[Any]) -> CompanyOut:
    m = row._mapping
    return CompanyOut(id=m["id"], name=m["name"], status=m["status"], created_at=m["created_at"])


async def create_company_defaults(
    db: AsyncSession,
    *,
    name: str,
    plan_code: str,
    subscription_expires_at: date,
    first_admin_email: str,
    first_admin_full_name: str,
) -> CompanyOut:
    plan_id = await repository.get_plan_id_by_code(db, code=plan_code)
    if plan_id is None:
        raise NotFoundError("El plan indicado no existe o está inactivo.")

    company_id = uuid4()
    await repository.insert_company(db, company_id=company_id, name=name)
    await repository.insert_subscription(
        db, company_id=company_id, plan_id=plan_id, expires_at=subscription_expires_at
    )
    await repository.insert_cash_register(db, company_id=company_id)

    all_codes = {row._mapping["code"] for row in await identity_repo.list_permissions(db)}
    seed_matrix = build_seed_role_permissions(all_codes)
    admin_role_id: UUID | None = None
    for role_name, codes in seed_matrix.items():
        role_id = uuid4()
        await identity_repo.insert_role(
            db,
            role_id=role_id,
            company_id=company_id,
            name=role_name,
            description=None,
            is_seed=True,
        )
        await identity_repo.set_role_permissions(db, role_id=role_id, codes=sorted(codes))
        if role_name == "Admin":
            admin_role_id = role_id
    assert admin_role_id is not None

    await identity_integration.invite_user(
        db,
        company_id=company_id,
        role_id=admin_role_id,
        email=first_admin_email,
        full_name=first_admin_full_name,
        invited_by=None,
    )

    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=None,
        module="platform",
        action="create_company",
        entity_type="company",
        entity_id=company_id,
        after={"name": name, "plan_code": plan_code},
    )

    row = await repository.get_company(db, company_id=company_id)
    assert row is not None
    return _row_to_company(row)


async def list_companies(
    db: AsyncSession, *, cursor: UUID | None, limit: int
) -> CursorPage[CompanyOut]:
    rows = await repository.list_companies(db, cursor=cursor, limit=limit)
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(items=[_row_to_company(r) for r in page.items], next_cursor=page.next_cursor)


async def get_company(db: AsyncSession, *, company_id: UUID) -> CompanyOut:
    row = await repository.get_company(db, company_id=company_id)
    if row is None:
        raise NotFoundError("La empresa no existe.")
    return _row_to_company(row)


async def _set_company_status(
    db: AsyncSession, *, company_id: UUID, status: str, actor_id: UUID | None
) -> CompanyOut:
    current = await repository.get_company(db, company_id=company_id)
    if current is None:
        raise NotFoundError("La empresa no existe.")

    await repository.set_company_status(db, company_id=company_id, status=status)
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="platform",
        action="set_company_status",
        entity_type="company",
        entity_id=company_id,
        before={"status": current._mapping["status"]},
        after={"status": status},
    )
    row = await repository.get_company(db, company_id=company_id)
    assert row is not None
    return _row_to_company(row)


async def suspend_company(
    db: AsyncSession, *, company_id: UUID, actor_id: UUID | None
) -> CompanyOut:
    return await _set_company_status(
        db, company_id=company_id, status="suspended", actor_id=actor_id
    )


async def activate_company(
    db: AsyncSession, *, company_id: UUID, actor_id: UUID | None
) -> CompanyOut:
    return await _set_company_status(db, company_id=company_id, status="active", actor_id=actor_id)


async def extend_subscription(
    db: AsyncSession,
    *,
    company_id: UUID,
    new_expires_at: date,
    notes: str | None,
    actor_id: UUID,
) -> None:
    company = await repository.get_company(db, company_id=company_id)
    if company is None:
        raise NotFoundError("La empresa no existe.")
    subscription = await repository.get_active_subscription(db, company_id=company_id)
    if subscription is None:
        raise NotFoundError("La empresa no tiene una suscripción activa.")

    before_expires_at = subscription._mapping["expires_at"]
    await repository.extend_subscription(
        db,
        subscription_id=subscription._mapping["id"],
        new_expires_at=new_expires_at,
        extended_by=actor_id,
        notes=notes,
    )
    await identity_repo.insert_audit_log(
        db,
        company_id=company_id,
        user_id=actor_id,
        module="platform",
        action="extend_subscription",
        entity_type="subscription",
        entity_id=subscription._mapping["id"],
        before={"expires_at": str(before_expires_at)},
        after={"expires_at": str(new_expires_at)},
    )


async def expire_overdue_subscriptions(db: AsyncSession) -> int:
    """Job nocturno (CLAUDE.md): marca `expired` las suscripciones cuyo
    `expires_at` ya pasó — bloquea acceso (`get_current_user` rechaza con
    `SUBSCRIPTION_EXPIRED` en cuanto el `status` deja de ser `active`).
    Compara contra el "hoy" de CADA empresa (§10 ARCHITECTURE.md), no un
    corte único en UTC. Corre con sesión de bypass (`get_db`, no
    tenant-scoped): necesita ver todas las empresas.
    """
    rows = await repository.list_active_subscriptions(db)
    expired = 0
    for row in rows:
        m = row._mapping
        today = await platform_integration.get_company_today(db, company_id=m["company_id"])
        if m["expires_at"] < today:
            await repository.expire_subscription(db, subscription_id=m["id"])
            await identity_repo.insert_audit_log(
                db,
                company_id=m["company_id"],
                user_id=None,
                module="platform",
                action="expire_subscription",
                entity_type="subscription",
                entity_id=m["id"],
                before={"status": "active", "expires_at": str(m["expires_at"])},
                after={"status": "expired"},
            )
            expired += 1
    return expired


async def list_plans(db: AsyncSession) -> list[PlanOut]:
    rows = await repository.list_plans(db)
    return [
        PlanOut(
            id=r._mapping["id"],
            name=r._mapping["name"],
            code=r._mapping["code"],
            price=r._mapping["price"],
            active=r._mapping["active"],
        )
        for r in rows
    ]
