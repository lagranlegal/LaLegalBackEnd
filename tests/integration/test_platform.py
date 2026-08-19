"""Integración de platform (paso 3): require_super_admin, create_company_defaults
end-to-end (roles semilla + caja + invitación del primer admin), suspender/
activar, extender suscripción. Requiere Postgres real (se salta si no hay).
"""

import uuid
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.modules.identity import auth_admin as identity_auth_admin


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


@pytest.fixture
def super_admin_token(monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]) -> str:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    return make_token(private_pem, sub=str(uuid4()), app_metadata={"platform_role": "super_admin"})


@pytest.fixture
def tenant_token(monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]) -> str:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    return make_token(private_pem, sub=str(uuid4()), company_id=str(uuid4()), role_id=str(uuid4()))


@pytest_asyncio.fixture
async def mocked_invite(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    invited_emails: list[str] = []

    async def _fake_invite(email: str, full_name: str) -> uuid.UUID:
        invited_emails.append(email)
        return uuid4()

    monkeypatch.setattr(identity_auth_admin, "invite_user", _fake_invite)
    return invited_emails


async def _cleanup_company(company_id: uuid.UUID) -> None:
    # audit_log es inmutable (trigger forbid_change) y no tiene FK hacia
    # company/role — se deja huérfano a propósito, no bloquea el resto del
    # cleanup.
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("delete from public.app_user where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text(
                "delete from public.role_permission where role_id in "
                "(select id from public.role where company_id = :id)"
            ),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.role where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text("delete from public.cash_register where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.subscription where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.company where id = :id"), {"id": str(company_id)}
        )


@pytest_asyncio.fixture
async def created_company(
    client: TestClient, mocked_invite: list[str], super_admin_token: str
) -> AsyncGenerator[dict, None]:
    response = client.post(
        "/api/v1/platform/companies",
        headers={"Authorization": f"Bearer {super_admin_token}"},
        json={
            "name": "Empresa integration-test",
            "plan_code": "full",
            "subscription_expires_at": "2099-01-01",
            "first_admin_email": "admin-integration-test@example.com",
            "first_admin_full_name": "Admin Integration Test",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    yield body
    await _cleanup_company(uuid.UUID(body["id"]))


def test_require_super_admin_rejects_no_token(client: TestClient) -> None:
    response = client.get("/api/v1/platform/companies")
    assert response.status_code == 401


def test_require_super_admin_rejects_tenant_token(client: TestClient, tenant_token: str) -> None:
    response = client.get(
        "/api/v1/platform/companies", headers={"Authorization": f"Bearer {tenant_token}"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_require_super_admin_accepts_platform_claim(
    client: TestClient, super_admin_token: str
) -> None:
    response = client.get(
        "/api/v1/platform/companies", headers={"Authorization": f"Bearer {super_admin_token}"}
    )
    assert response.status_code == 200
    assert "items" in response.json()


async def test_create_company_defaults_creates_seed_roles_and_cash_register(
    created_company: dict, mocked_invite: list[str]
) -> None:
    company_id = uuid.UUID(created_company["id"])
    assert created_company["status"] == "active"
    assert mocked_invite == ["admin-integration-test@example.com"]

    async with AsyncSessionLocal() as session, session.begin():
        roles = (
            await session.execute(
                text("select name, is_seed from public.role where company_id = :id order by name"),
                {"id": str(company_id)},
            )
        ).all()
        assert {(r[0], r[1]) for r in roles} == {
            ("Admin", True),
            ("Asesor", True),
            ("Bodega", True),
            ("Moderador", True),
        }

        admin_role_id = (
            await session.execute(
                text("select id from public.role where company_id = :id and name = 'Admin'"),
                {"id": str(company_id)},
            )
        ).scalar_one()
        admin_permission_count = (
            await session.execute(
                text("select count(*) from public.role_permission where role_id = :role_id"),
                {"role_id": str(admin_role_id)},
            )
        ).scalar_one()
        permission_catalog_count = (
            await session.execute(text("select count(*) from public.permission"))
        ).scalar_one()
        assert admin_permission_count == permission_catalog_count

        register_count = (
            await session.execute(
                text("select count(*) from public.cash_register where company_id = :id"),
                {"id": str(company_id)},
            )
        ).scalar_one()
        assert register_count == 1

        invited_user = (
            await session.execute(
                text("select status, role_id from public.app_user where company_id = :id"),
                {"id": str(company_id)},
            )
        ).first()
        assert invited_user is not None
        assert invited_user[0] == "invited"
        assert invited_user[1] == admin_role_id

        audit_action = (
            await session.execute(
                text(
                    "select action from public.audit_log "
                    "where company_id = :id and entity_type = 'company'"
                ),
                {"id": str(company_id)},
            )
        ).scalar_one()
        assert audit_action == "create_company"


def test_suspend_and_activate_company(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    suspend_resp = client.post(f"/api/v1/platform/companies/{company_id}/suspend", headers=headers)
    assert suspend_resp.status_code == 200
    assert suspend_resp.json()["status"] == "suspended"

    activate_resp = client.post(
        f"/api/v1/platform/companies/{company_id}/activate", headers=headers
    )
    assert activate_resp.status_code == 200
    assert activate_resp.json()["status"] == "active"


def test_created_company_includes_plan_and_subscription_expiry(created_company: dict) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #4/#14: el panel de plataforma
    necesita ver el plan y la fecha de expiración sin un segundo request."""
    assert created_company["plan_code"] == "full"
    assert created_company["plan_name"] == "Completo"
    assert created_company["subscription_expires_at"] == "2099-01-01"


def test_get_and_list_companies_include_plan_and_subscription(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    detail = client.get(f"/api/v1/platform/companies/{company_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["plan_code"] == "full"

    listing = client.get("/api/v1/platform/companies", headers=headers)
    assert listing.status_code == 200
    row = next(c for c in listing.json()["items"] if c["id"] == company_id)
    assert row["plan_code"] == "full"
    assert row["subscription_expires_at"] == "2099-01-01"


def test_list_plans_includes_modules(client: TestClient, super_admin_token: str) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #14: PlanOut no exponía `modules`
    aunque la columna ya existe con datos reales en `plan`."""
    response = client.get(
        "/api/v1/platform/plans", headers={"Authorization": f"Bearer {super_admin_token}"}
    )
    assert response.status_code == 200
    full_plan = next(p for p in response.json() if p["code"] == "full")
    assert full_plan["modules"] == {"pawn": True, "store": True}


def test_extend_subscription(
    client: TestClient, created_company: dict, super_admin_token: str
) -> None:
    headers = {"Authorization": f"Bearer {super_admin_token}"}
    company_id = created_company["id"]

    response = client.post(
        f"/api/v1/platform/companies/{company_id}/subscription/extend",
        headers=headers,
        json={"new_expires_at": "2099-12-31", "notes": "prueba de integración"},
    )
    assert response.status_code == 204
