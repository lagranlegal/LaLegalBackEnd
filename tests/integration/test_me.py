"""Integración de `GET /api/v1/me`: el front no puede saber qué permisos
tiene el usuario logueado sin esto (los endpoints de permisos por rol
exigen `identity.manage_roles`, que un Asesor no tiene). Devuelve
user+company+role+permissions+subscription+plan en una sola consulta.
Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine


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
async def me_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()
    codes = ("contracts.create", "contracts.view")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.company (id, name, logo_url, settings) "
                "values (:id, 'Empresa me-test', 'https://cdn.example.com/logo.png', "
                ' \'{"timezone": "America/Mexico_City"}\'::jsonb)'
            ),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Asesor')"),
            {"id": str(role_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code in :codes"
            ).bindparams(bindparam("codes", expanding=True)),
            {"role_id": str(role_id), "codes": list(codes)},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :role_id, 'Asesor Test', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"asesor-{user_id}@example.com",
            },
        )
        plan_id = (
            await session.execute(text("select id from public.plan where code = 'full'"))
        ).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan_id, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "plan_id": str(plan_id)},
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    yield {
        "company_id": company_id,
        "role_id": role_id,
        "user_id": user_id,
        "token": token,
        "codes": sorted(codes),
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


def test_me_without_token_is_401(client: TestClient) -> None:
    response = client.get("/api/v1/me")
    assert response.status_code == 401


def test_me_returns_user_company_role_permissions_subscription_plan(
    client: TestClient, me_tenant: dict
) -> None:
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {me_tenant['token']}"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["user"]["id"] == str(me_tenant["user_id"])
    assert body["user"]["full_name"] == "Asesor Test"

    assert body["company"]["id"] == str(me_tenant["company_id"])
    assert body["company"]["name"] == "Empresa me-test"
    assert body["company"]["timezone"] == "America/Mexico_City"
    assert body["company"]["logo_url"] == "https://cdn.example.com/logo.png"

    assert body["role"]["id"] == str(me_tenant["role_id"])
    assert body["role"]["name"] == "Asesor"

    # Exactamente el set del rol, ni más ni menos — es el mismo cache que
    # usa require_permission, así que esto es lo que el backend realmente
    # va a aceptar (no una lista aparte que se pueda desincronizar).
    assert body["permissions"] == me_tenant["codes"]
    assert "identity.manage_roles" not in body["permissions"]

    assert body["subscription"]["status"] == "active"
    assert body["plan"]["code"] == "full"
    assert body["plan"]["name"] == "Completo"


def test_patch_me_updates_own_name_and_photo(client: TestClient, me_tenant: dict) -> None:
    """`PATCH /me` (docs/PENDIENTES_BACKEND_INFRA.md #15): no había pantalla
    de perfil porque no había endpoint. Un usuario edita SU nombre y SU foto
    sin permisos de identidad — editarse a uno mismo no es gestionar usuarios.
    """
    headers = {"Authorization": f"Bearer {me_tenant['token']}"}

    resp = client.patch(
        "/api/v1/me",
        headers=headers,
        json={"full_name": "Asesor Renombrado", "photo_url": "company-files/perfil.jpg"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # La respuesta ya trae el valor nuevo, sin un segundo GET: el `MeOut` se
    # arma leyendo la fila, no el cache de 30s de `CurrentUser`.
    assert body["user"]["full_name"] == "Asesor Renombrado"
    assert body["user"]["photo_url"] == "company-files/perfil.jpg"

    # Y persiste.
    again = client.get("/api/v1/me", headers=headers).json()
    assert again["user"]["full_name"] == "Asesor Renombrado"

    # PATCH parcial: omitir un campo lo conserva.
    solo_foto = client.patch("/api/v1/me", headers=headers, json={"photo_url": None})
    assert solo_foto.status_code == 200
    assert solo_foto.json()["user"]["full_name"] == "Asesor Renombrado"
    # `null` explícito SÍ borra.
    assert solo_foto.json()["user"]["photo_url"] is None


def test_patch_me_cannot_change_role_or_status(client: TestClient, me_tenant: dict) -> None:
    """La razón por la que este endpoint puede vivir sin `require_permission`:
    el schema no admite `role_id` ni `status`. Si los admitiera, cualquiera se
    ascendería a admin desde su propio perfil, rodeando
    `identity.manage_users` por otra URL.
    """
    headers = {"Authorization": f"Bearer {me_tenant['token']}"}
    otro_rol = str(uuid4())

    resp = client.patch(
        "/api/v1/me",
        headers=headers,
        json={"full_name": "Intento", "role_id": otro_rol, "status": "active"},
    )
    assert resp.status_code == 200, resp.text
    # El nombre sí cambió; el rol NO — los campos de más se ignoran, no se
    # escriben.
    assert resp.json()["user"]["full_name"] == "Intento"
    assert resp.json()["role"]["id"] == str(me_tenant["role_id"])
    assert resp.json()["role"]["id"] != otro_rol


def test_patch_me_rejects_an_empty_name(client: TestClient, me_tenant: dict) -> None:
    headers = {"Authorization": f"Bearer {me_tenant['token']}"}
    assert client.patch("/api/v1/me", headers=headers, json={"full_name": ""}).status_code == 422


def test_patch_me_without_token_is_401(client: TestClient) -> None:
    assert client.patch("/api/v1/me", json={"full_name": "X"}).status_code == 401
