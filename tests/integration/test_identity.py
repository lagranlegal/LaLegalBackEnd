"""Integración de identity (paso 3): invitaciones, roles, matriz de permisos,
salvaguardas de último admin, activación automática invited->active en el
primer login. Requiere Postgres real (se salta si no hay).
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


@pytest_asyncio.fixture
async def mocked_invite(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    invited_emails: list[str] = []

    async def _fake_invite(email: str, full_name: str) -> uuid.UUID:
        invited_emails.append(email)
        return uuid4()

    monkeypatch.setattr(identity_auth_admin, "invite_user", _fake_invite)
    return invited_emails


@pytest_asyncio.fixture
async def tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa con un rol Admin (todos los permisos) + 1 usuario activo, y un
    rol Bodega (sin permisos de identity) para probar reasignaciones.
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    admin_role_id = uuid4()
    basic_role_id = uuid4()
    admin_user_id = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, :name)"),
            {"id": str(company_id), "name": "Empresa identity-test"},
        )
        await session.execute(
            text(
                "insert into public.role (id, company_id, name, is_seed) "
                "values (:id, :company_id, :name, true)"
            ),
            [
                {"id": str(admin_role_id), "company_id": str(company_id), "name": "Admin"},
                {"id": str(basic_role_id), "company_id": str(company_id), "name": "Bodega"},
            ],
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission"
            ),
            {"role_id": str(admin_role_id)},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code = 'inventory.view'"
            ),
            {"role_id": str(basic_role_id)},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Admin Test', :email, 'active')"
            ),
            {
                "id": str(admin_user_id),
                "company_id": str(company_id),
                "role_id": str(admin_role_id),
                "email": f"admin-{admin_user_id}@example.com",
            },
        )
        plan_id = (await session.execute(text("select id from public.plan limit 1"))).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:company_id, :plan_id, 'active', current_date + 30)"
            ),
            {"company_id": str(company_id), "plan_id": str(plan_id)},
        )

    admin_token = make_token(
        private_pem,
        sub=str(admin_user_id),
        company_id=str(company_id),
        role_id=str(admin_role_id),
    )

    yield {
        "company_id": company_id,
        "admin_role_id": admin_role_id,
        "basic_role_id": basic_role_id,
        "admin_user_id": admin_user_id,
        "admin_token": admin_token,
        "private_pem": private_pem,
    }

    # audit_log es inmutable (trigger forbid_change) y no tiene FK hacia
    # company/role — se deja huérfano a propósito, no bloquea el cleanup.
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
            text("delete from public.subscription where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.company where id = :id"), {"id": str(company_id)}
        )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_invite_user(client: TestClient, tenant: dict, mocked_invite: list[str]) -> None:
    response = client.post(
        "/api/v1/identity/invitations",
        headers=_headers(tenant["admin_token"]),
        json={
            "email": "nuevo@example.com",
            "full_name": "Nuevo Usuario",
            "role_id": str(tenant["basic_role_id"]),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "invited"
    assert body["role_id"] == str(tenant["basic_role_id"])
    assert mocked_invite == ["nuevo@example.com"]


def test_list_users_includes_admin(client: TestClient, tenant: dict) -> None:
    response = client.get("/api/v1/identity/users", headers=_headers(tenant["admin_token"]))
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert str(tenant["admin_user_id"]) in ids


def test_deactivate_last_admin_is_blocked(client: TestClient, tenant: dict) -> None:
    response = client.post(
        f"/api/v1/identity/users/{tenant['admin_user_id']}/deactivate",
        headers=_headers(tenant["admin_token"]),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "LAST_ADMIN_SAFEGUARD"


def test_reassign_last_admin_away_is_blocked(client: TestClient, tenant: dict) -> None:
    response = client.patch(
        f"/api/v1/identity/users/{tenant['admin_user_id']}/role",
        headers=_headers(tenant["admin_token"]),
        json={"role_id": str(tenant["basic_role_id"])},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "LAST_ADMIN_SAFEGUARD"


def test_remove_admin_permission_from_only_admin_role_is_blocked(
    client: TestClient, tenant: dict
) -> None:
    get_resp = client.get(
        f"/api/v1/identity/roles/{tenant['admin_role_id']}/permissions",
        headers=_headers(tenant["admin_token"]),
    )
    assert get_resp.status_code == 200
    codes = [c for c in get_resp.json() if c != "identity.manage_roles"]

    put_resp = client.put(
        f"/api/v1/identity/roles/{tenant['admin_role_id']}/permissions",
        headers=_headers(tenant["admin_token"]),
        json={"permission_codes": codes},
    )
    assert put_resp.status_code == 409
    assert put_resp.json()["code"] == "LAST_ADMIN_SAFEGUARD"


def test_create_and_clone_role(client: TestClient, tenant: dict) -> None:
    response = client.post(
        "/api/v1/identity/roles",
        headers=_headers(tenant["admin_token"]),
        json={
            "name": "Bodega clonado",
            "clone_from_role_id": str(tenant["basic_role_id"]),
        },
    )
    assert response.status_code == 201, response.text
    new_role_id = response.json()["id"]

    perms_resp = client.get(
        f"/api/v1/identity/roles/{new_role_id}/permissions",
        headers=_headers(tenant["admin_token"]),
    )
    assert perms_resp.status_code == 200
    assert perms_resp.json() == ["inventory.view"]


async def test_invited_user_activates_on_first_login(
    client: TestClient,
    tenant: dict,
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
) -> None:
    private_pem = tenant["private_pem"]
    invited_user_id = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :company_id, :role_id, 'Invitado Test', :email, 'invited')"
            ),
            {
                "id": str(invited_user_id),
                "company_id": str(tenant["company_id"]),
                "role_id": str(tenant["admin_role_id"]),
                "email": f"invitado-{invited_user_id}@example.com",
            },
        )

    token = make_token(
        private_pem,
        sub=str(invited_user_id),
        company_id=str(tenant["company_id"]),
        role_id=str(tenant["admin_role_id"]),
    )
    response = client.get("/api/v1/identity/users", headers=_headers(token))
    assert response.status_code == 200

    async with AsyncSessionLocal() as session, session.begin():
        status_after = (
            await session.execute(
                text("select status from public.app_user where id = :id"),
                {"id": str(invited_user_id)},
            )
        ).scalar_one()
    assert status_after == "active"
