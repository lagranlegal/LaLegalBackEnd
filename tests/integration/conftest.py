from collections.abc import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal
from app.main import app


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    # `with` es obligatorio: sin el context manager, el lifespan del ASGI app
    # no corre limpio y las escrituras hechas dentro de un request pueden no
    # llegar a persistirse de verdad contra Postgres remoto (Supavisor en
    # modo transacción) una vez el proceso de test termina — confirmado
    # reproduciéndolo manualmente al depurar el paso 3.
    with TestClient(app) as c:
        yield c


@pytest_asyncio.fixture
async def tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa + 1 rol con customers.view/create y catalogs.view/manage + 1 usuario
    activo. Fixture genérica para módulos que no necesitan la matriz completa
    de identity (ver tests/integration/test_identity.py para esa).
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, :name)"),
            {"id": str(company_id), "name": "Empresa tenant-test"},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Tester')"),
            {"id": str(role_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission "
                "where code in ('customers.view', 'customers.create', "
                "'catalogs.view', 'catalogs.manage')"
            ),
            {"role_id": str(role_id)},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :role_id, 'Tester', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"tester-{user_id}@example.com",
            },
        )
        plan_id = (await session.execute(text("select id from public.plan limit 1"))).scalar_one()
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
        "private_pem": private_pem,
    }

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
            text("delete from public.category where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text("delete from public.supplier where company_id = :id"), {"id": str(company_id)}
        )
        await session.execute(
            text("delete from public.customer where company_id = :id"), {"id": str(company_id)}
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
