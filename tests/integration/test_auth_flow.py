"""End-to-end de get_current_user + require_permission contra Postgres real.

Requiere Postgres local (`supabase start` + `supabase db reset`, con el
catálogo de permisos del seed). Se salta si no hay conexión disponible.
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.core.errors import register_exception_handlers
from app.core.security import CurrentUser, require_permission


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


class _FakeSigningKey:
    def __init__(self, key: object) -> None:
        self.key = key


class _FakeJwkClient:
    def __init__(self, public_key: object) -> None:
        self._public_key = public_key

    def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._public_key)


def _make_token(private_pem: str, *, sub: str, company_id: str, role_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "company_id": company_id,
        "role_id": role_id,
    }
    return jwt.encode(payload, private_pem, algorithm="RS256")


@pytest_asyncio.fixture
async def tenant_fixture() -> AsyncGenerator[dict[str, uuid.UUID], None]:
    company_id = uuid.uuid4()
    role_with_perm = uuid.uuid4()
    role_without_perm = uuid.uuid4()
    user_with_perm = uuid.uuid4()
    user_without_perm = uuid.uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, :name)"),
            {"id": str(company_id), "name": "Empresa auth-flow (test)"},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :company_id, :name)"),
            [
                {"id": str(role_with_perm), "company_id": str(company_id), "name": "ConPermiso"},
                {
                    "id": str(role_without_perm),
                    "company_id": str(company_id),
                    "name": "SinPermiso",
                },
            ],
        )
        await session.execute(
            text(
                """
                insert into public.role_permission (role_id, permission_id)
                select :role_id, id from public.permission where code = 'contracts.view'
                """
            ),
            {"role_id": str(role_with_perm)},
        )
        await session.execute(
            text(
                """
                insert into public.app_user (id, company_id, role_id, full_name, email, status)
                values (:id, :company_id, :role_id, :full_name, :email, 'active')
                """
            ),
            [
                {
                    "id": str(user_with_perm),
                    "company_id": str(company_id),
                    "role_id": str(role_with_perm),
                    "full_name": "Con Permiso",
                    "email": f"con-permiso-{user_with_perm}@test.local",
                },
                {
                    "id": str(user_without_perm),
                    "company_id": str(company_id),
                    "role_id": str(role_without_perm),
                    "full_name": "Sin Permiso",
                    "email": f"sin-permiso-{user_without_perm}@test.local",
                },
            ],
        )
        await session.execute(
            text(
                """
                insert into public.plan (id, name, code, active)
                values (:id, :name, :code, true)
                on conflict (code) do nothing
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "name": f"Plan test {company_id}",
                "code": f"test-{company_id}",
            },
        )
        plan_id = (
            await session.execute(
                text("select id from public.plan where code = :code"),
                {"code": f"test-{company_id}"},
            )
        ).scalar_one()
        await session.execute(
            text(
                """
                insert into public.subscription (company_id, plan_id, status, expires_at)
                values (:company_id, :plan_id, 'active', current_date + 30)
                """
            ),
            {"company_id": str(company_id), "plan_id": str(plan_id)},
        )

    yield {
        "company_id": company_id,
        "role_with_perm": role_with_perm,
        "role_without_perm": role_without_perm,
        "user_with_perm": user_with_perm,
        "user_without_perm": user_without_perm,
    }

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("delete from public.subscription where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.plan where code = :code"), {"code": f"test-{company_id}"}
        )
        await session.execute(
            text("delete from public.app_user where company_id = :id"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("delete from public.role where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text("delete from public.company where id = :id"), {"id": str(company_id)}
        )


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/dummy")
    async def dummy(
        user: Annotated[CurrentUser, Depends(require_permission("contracts.view"))],
    ) -> dict[str, str]:
        return {"user_id": str(user.id)}

    return app


def test_no_token_is_401() -> None:
    with TestClient(_build_app()) as client:
        response = client.get("/dummy")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_valid_token_without_permission_is_403(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
    tenant_fixture: dict[str, uuid.UUID],
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    token = _make_token(
        private_pem,
        sub=str(tenant_fixture["user_without_perm"]),
        company_id=str(tenant_fixture["company_id"]),
        role_id=str(tenant_fixture["role_without_perm"]),
    )

    with TestClient(_build_app()) as client:
        response = client.get("/dummy", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_valid_token_with_permission_is_200(
    monkeypatch: pytest.MonkeyPatch,
    rsa_keypair: tuple[str, object],
    tenant_fixture: dict[str, uuid.UUID],
) -> None:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: _FakeJwkClient(public_key))

    token = _make_token(
        private_pem,
        sub=str(tenant_fixture["user_with_perm"]),
        company_id=str(tenant_fixture["company_id"]),
        role_id=str(tenant_fixture["role_with_perm"]),
    )

    with TestClient(_build_app()) as client:
        response = client.get("/dummy", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"user_id": str(tenant_fixture["user_with_perm"])}


async def _hook_claims(user_id: uuid.UUID) -> dict[str, object]:
    """Corre el Custom Access Token Hook como lo hace Supabase Auth y
    devuelve los claims resultantes."""
    async with AsyncSessionLocal() as session, session.begin():
        result = await session.execute(
            # `cast(... as jsonb)` y no `::jsonb`: SQLAlchemy interpreta el
            # segundo `:` de `::` como el inicio de un parámetro con nombre.
            text("select public.custom_access_token_hook(cast(:event as jsonb))"),
            {"event": f'{{"user_id": "{user_id}", "claims": {{}}}}'},
        )
        return dict(result.scalar_one()["claims"])


@pytest.mark.asyncio
async def test_hook_emite_claims_para_un_invitado(
    tenant_fixture: dict[str, uuid.UUID],
) -> None:
    """Un invitado que acaba de poner su contraseña DEBE recibir claims.

    Sin esto se forma un bloqueo mutuo (migración 00028): el hook no emite
    claims hasta que el usuario sea `active`, `get_verified_claims` rechaza
    con 401 todo token sin claims, y el único código que activa al usuario
    vive detrás de esa validación. Resultado: ningún invitado podía entrar
    jamás, y el mensaje que veía ("usuario o empresa inactivos") apuntaba al
    lugar equivocado.
    """
    invitado = uuid.uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                """
                insert into public.app_user (id, company_id, role_id, full_name, email, status)
                values (:id, :company_id, :role_id, 'Recién Invitado', :email, 'invited')
                """
            ),
            {
                "id": str(invitado),
                "company_id": str(tenant_fixture["company_id"]),
                "role_id": str(tenant_fixture["role_with_perm"]),
                "email": f"invitado-{invitado}@test.local",
            },
        )

    claims = await _hook_claims(invitado)
    assert claims.get("company_id") == str(tenant_fixture["company_id"])
    assert claims.get("role_id") == str(tenant_fixture["role_with_perm"])


@pytest.mark.asyncio
async def test_hook_no_emite_claims_para_un_usuario_desactivado(
    tenant_fixture: dict[str, uuid.UUID],
) -> None:
    """`inactive` es el estado que SÍ debe cortar el acceso — es lo que hace
    el admin al desactivar a alguien. La condición del hook enumera los
    estados permitidos justamente para que esto no se afloje al agregar uno
    nuevo."""
    desactivado = uuid.uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                """
                insert into public.app_user (id, company_id, role_id, full_name, email, status)
                values (:id, :company_id, :role_id, 'Desactivado', :email, 'inactive')
                """
            ),
            {
                "id": str(desactivado),
                "company_id": str(tenant_fixture["company_id"]),
                "role_id": str(tenant_fixture["role_with_perm"]),
                "email": f"inactivo-{desactivado}@test.local",
            },
        )

    assert await _hook_claims(desactivado) == {}


@pytest.mark.asyncio
async def test_hook_no_emite_claims_si_la_empresa_esta_suspendida(
    tenant_fixture: dict[str, uuid.UUID],
) -> None:
    """Suspender la empresa corta a TODOS sus usuarios, invitados incluidos:
    es la palanca comercial de la plataforma y no puede depender del estado
    individual de cada quien."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.company set status = 'suspended' where id = :id"),
            {"id": str(tenant_fixture["company_id"])},
        )

    assert await _hook_claims(tenant_fixture["user_with_perm"]) == {}

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.company set status = 'active' where id = :id"),
            {"id": str(tenant_fixture["company_id"])},
        )
