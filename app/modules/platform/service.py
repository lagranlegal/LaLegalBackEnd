from datetime import date
from decimal import Decimal
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
from app.modules.platform.schemas import CompanyOut, PlanOut, SubscriptionEventOut

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
    "sales.view",
    # Leer categorías es indispensable para crear un contrato: el asesor
    # elige la categoría de la prenda. Sin esto no puede trabajar.
    "catalogs.view",
    "cashbox.view",
    # Un asesor que cobra necesita ver a qué cuenta está mandando la plata,
    # aunque no pueda administrar el catálogo ni liquidar convenios.
    "accounts.view",
}
_BODEGA_CODES = {
    "inventory.view",
    "inventory.create",
    "catalogs.manage",
    "catalogs.view",
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
    # Coherente con las dos exclusiones de arriba: si un Moderador no
    # configura la empresa, tampoco administra el catálogo de cuentas; y si
    # no abre ni cierra la caja, tampoco liquida convenios (mueve plata).
    "accounts.manage",
    "accounts.settle",
    # Misma regla para trasladar (00032): sacar el efectivo del cajón y
    # consignarlo mueve plata igual que liquidar. Quien no abre ni cierra la
    # caja tampoco decide cuánto sale de ella.
    "accounts.transfer",
    # Y para pagarle a proveedores (00035), por lo mismo. Un Moderador
    # tampoco tiene `inventory.create`, así que no habría podido de todos
    # modos — dejarlo explícito evita que se cuele si mañana cambia esa
    # exclusión.
    "inventory.pay_purchase",
    # Transformar destruye inventario de forma irreversible (00037). Un
    # Moderador ya no hace egresos; fundir es más definitivo todavía.
    "inventory.transform",
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
    return CompanyOut(
        id=m["id"],
        name=m["name"],
        status=m["status"],
        created_at=m["created_at"],
        plan_code=m["plan_code"],
        plan_name=m["plan_name"],
        subscription_expires_at=m["subscription_expires_at"],
    )


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
    await repository.insert_default_accounts(db, company_id=company_id)

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
    # Primer evento del historial comercial: sin él, una empresa que nunca
    # renovó tendría el historial vacío y no se distinguiría de una cuyos
    # eventos se perdieron.
    subscription = await repository.get_active_subscription(db, company_id=company_id)
    await repository.insert_subscription_event(
        db,
        company_id=company_id,
        subscription_id=subscription._mapping["id"] if subscription else None,
        event_type="created",
        new_expires_at=subscription_expires_at,
        created_by=None,
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
    # Además del audit_log: cortar o devolver el acceso a una empresa es un
    # hecho de la relación comercial, y el audit_log es tenant-scoped por RLS
    # (el super-admin no puede leerlo de otra empresa). Sin fechas porque
    # suspender no mueve el vencimiento — el historial distingue así "renovó
    # hasta X" de "le cortaron el acceso".
    subscription = await repository.get_active_subscription(db, company_id=company_id)
    await repository.insert_subscription_event(
        db,
        company_id=company_id,
        subscription_id=subscription._mapping["id"] if subscription else None,
        event_type="suspended" if status == "suspended" else "activated",
        created_by=actor_id,
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
    amount: Decimal | None = None,
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
    # El audit_log solo guarda `expires_at`, así que las `notes` de cada
    # extensión —el campo donde el super-admin anota cómo pagó el cliente— se
    # perdían: la fila de `subscription` las sobrescribe y el audit no las
    # copia. Acá quedan, junto al monto.
    await repository.insert_subscription_event(
        db,
        company_id=company_id,
        subscription_id=subscription._mapping["id"],
        event_type="extended",
        previous_expires_at=before_expires_at,
        new_expires_at=new_expires_at,
        amount=amount,
        notes=notes,
        created_by=actor_id,
    )


async def list_subscription_events(
    db: AsyncSession, *, company_id: UUID, cursor: UUID | None, limit: int
) -> CursorPage[SubscriptionEventOut]:
    if await repository.get_company(db, company_id=company_id) is None:
        raise NotFoundError("La empresa no existe.")
    rows = await repository.list_subscription_events(
        db, company_id=company_id, cursor=cursor, limit=limit
    )
    page = make_page(rows, limit, lambda r: r._mapping["id"])
    return CursorPage(
        items=[
            SubscriptionEventOut(
                id=r._mapping["id"],
                event_type=r._mapping["event_type"],
                previous_expires_at=r._mapping["previous_expires_at"],
                new_expires_at=r._mapping["new_expires_at"],
                amount=r._mapping["amount"],
                notes=r._mapping["notes"],
                created_by=r._mapping["created_by"],
                created_at=r._mapping["created_at"],
            )
            for r in page.items
        ],
        next_cursor=page.next_cursor,
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
            # El vencimiento automático también es parte del historial: sin
            # esto, el panel mostraría una empresa cortada sin ninguna línea
            # que explique cuándo ni por qué dejó de estar vigente.
            await repository.insert_subscription_event(
                db,
                company_id=m["company_id"],
                subscription_id=m["id"],
                event_type="expired",
                previous_expires_at=m["expires_at"],
                created_by=None,
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
            modules=r._mapping["modules"],
            active=r._mapping["active"],
        )
        for r in rows
    ]
