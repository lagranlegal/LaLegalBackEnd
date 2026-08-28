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
