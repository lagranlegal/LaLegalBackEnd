"""Test RLS del esqueleto (CLAUDE.md paso 2): tenant A nunca ve datos de tenant B.

Requiere Postgres local corriendo (`supabase start`). Se salta automáticamente
si no hay conexión disponible, en vez de fallar el suite completo.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.db import AsyncSessionLocal, apply_tenant_claims, engine


async def _postgres_available() -> bool:
    try:
        async with engine.connect():
            return True
    except Exception:
        return False


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _require_postgres() -> None:
    if not await _postgres_available():
        pytest.skip("Postgres local no disponible: correr `supabase start` primero.")


@pytest_asyncio.fixture
async def two_companies() -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID], None]:
    company_a, company_b = uuid.uuid4(), uuid.uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        # Conectado como el rol de DATABASE_URL (postgres/superusuario en local):
        # bypassea RLS, así que este seed no necesita claims de tenant.
        await session.execute(
            text("insert into public.company (id, name) values (:id, :name)"),
            [
                {"id": str(company_a), "name": "Empresa A (test)"},
                {"id": str(company_b), "name": "Empresa B (test)"},
            ],
        )

    yield company_a, company_b

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("delete from public.company where id = :id"),
            [{"id": str(company_a)}, {"id": str(company_b)}],
        )


async def _company_ids_visible_as(company_id: uuid.UUID) -> list[uuid.UUID]:
    async with AsyncSessionLocal() as session, session.begin():
        await apply_tenant_claims(
            session, {"sub": str(uuid.uuid4()), "company_id": str(company_id)}
        )
        rows = await session.execute(text("select id from public.company"))
        return [row[0] for row in rows]


async def test_tenant_only_sees_own_company(
    two_companies: tuple[uuid.UUID, uuid.UUID],
) -> None:
    company_a, company_b = two_companies

    assert await _company_ids_visible_as(company_a) == [company_a]
    assert await _company_ids_visible_as(company_b) == [company_b]


async def test_tenant_without_claims_sees_nothing() -> None:
    async with AsyncSessionLocal() as session, session.begin():
        await apply_tenant_claims(session, {"sub": str(uuid.uuid4())})
        rows = await session.execute(text("select id from public.company"))
        assert rows.all() == []


async def test_document_template_isolated_between_tenants(
    two_companies: tuple[uuid.UUID, uuid.UUID],
) -> None:
    company_a, _ = two_companies
    template_id = uuid.uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        # Bypass de RLS (rol superusuario local) para el seed, igual que el
        # resto de este archivo.
        await session.execute(
            text(
                "insert into public.document_template (id, company_id, document_type, name, body) "
                "values (:id, :cid, 'contract', 'Plantilla A', '{}'::jsonb)"
            ),
            {"id": str(template_id), "cid": str(company_a)},
        )

    try:
        ids_as_a = await _document_template_ids_visible_as(company_a)
        ids_as_b = await _document_template_ids_visible_as(two_companies[1])
        assert ids_as_a == [template_id]
        assert ids_as_b == []
    finally:
        # Sin esto, el teardown de `two_companies` (DELETE FROM company)
        # falla por la FK de document_template.company_id — mismo criterio
        # que ya siguen los demás archivos de test con tablas hijas.
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("delete from public.document_template where id = :id"),
                {"id": str(template_id)},
            )


async def _document_template_ids_visible_as(company_id: uuid.UUID) -> list[uuid.UUID]:
    async with AsyncSessionLocal() as session, session.begin():
        await apply_tenant_claims(
            session, {"sub": str(uuid.uuid4()), "company_id": str(company_id)}
        )
        rows = await session.execute(text("select id from public.document_template"))
        return [row[0] for row in rows]


async def test_notification_tables_isolated_between_tenants(
    two_companies: tuple[uuid.UUID, uuid.UUID],
) -> None:
    """00058: `notification_event` y `notification_delivery` llevan la política
    `tenant_isolation` de siempre. Una entrega trae la dirección de correo de
    un cliente: que otra empresa la vea sería una fuga de datos personales."""
    company_a, company_b = two_companies
    event_id, delivery_id = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.notification_event "
                "(id, company_id, event_type, audience, payload, dedupe_key, occurred_on) "
                "values (:id, :cid, 'company_daily_digest', 'company', '{}'::jsonb, "
                "'rls-test', '2030-09-02')"
            ),
            {"id": str(event_id), "cid": str(company_a)},
        )
        await session.execute(
            text(
                "insert into public.notification_delivery "
                "(id, company_id, event_id, to_address, status) "
                "values (:id, :cid, :eid, 'a@example.com', 'pending')"
            ),
            {"id": str(delivery_id), "cid": str(company_a), "eid": str(event_id)},
        )

    async def _visible(company_id: uuid.UUID, table: str) -> list[uuid.UUID]:
        async with AsyncSessionLocal() as session, session.begin():
            await apply_tenant_claims(
                session, {"sub": str(uuid.uuid4()), "company_id": str(company_id)}
            )
            rows = await session.execute(text(f"select id from public.{table}"))
            return [row[0] for row in rows]

    try:
        assert await _visible(company_a, "notification_event") == [event_id]
        assert await _visible(company_a, "notification_delivery") == [delivery_id]
        assert await _visible(company_b, "notification_event") == []
        assert await _visible(company_b, "notification_delivery") == []
        # Y B tampoco puede escribir filas a nombre de A.
        with pytest.raises(Exception, match="row-level security"):
            async with AsyncSessionLocal() as session, session.begin():
                await apply_tenant_claims(
                    session, {"sub": str(uuid.uuid4()), "company_id": str(company_b)}
                )
                await session.execute(
                    text(
                        "insert into public.notification_event "
                        "(company_id, event_type, audience, payload, dedupe_key, occurred_on) "
                        "values (:cid, 'company_daily_digest', 'company', '{}'::jsonb, "
                        "'rls-test-b', '2030-09-02')"
                    ),
                    {"cid": str(company_a)},
                )
    finally:
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text("delete from public.notification_delivery where id = :id"),
                {"id": str(delivery_id)},
            )
            await session.execute(
                text("delete from public.notification_event where id = :id"),
                {"id": str(event_id)},
            )
