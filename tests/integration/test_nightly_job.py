"""Integración del job nocturno (`app/jobs/nightly.py`, CLAUDE.md): recalcula
estados de contratos (`contracts.service.recompute_all_statuses`) y marca
suscripciones vencidas (`platform.service.expire_overdue_subscriptions`),
cruzando TODAS las empresas con una sesión de bypass — no una tenant-scoped.
Requiere Postgres real (se salta si no hay)."""

import uuid
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.jobs import nightly
from app.modules.contracts import service as contracts_service
from app.modules.identity import auth_admin as identity_auth_admin
from app.modules.platform import service as platform_service


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


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


@pytest_asyncio.fixture
async def recompute_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Contrato vigente con `interest_paid_until` corrido 2 meses atrás
    (ventana de mora de la categoría = 4) directamente en la BD — el
    estado persistido queda `active` hasta que algo lo recalcule; ni la API
    de creación ni este fixture llaman a `GET /contracts/{id}` (que
    recalcularía on-read y taparía si el job en sí funciona)."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()
    customer_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    register_id = uuid4()
    codes = ("contracts.create", "contracts.view")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa nightly-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Full')"),
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
                "values (:id, :cid, :role_id, 'Full User', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"full-{user_id}@example.com",
            },
        )
        plan_id = (await session.execute(text("select id from public.plan limit 1"))).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan_id, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "plan_id": plan_id},
        )
        await session.execute(
            text(
                "insert into public.customer "
                "(id, company_id, full_name, doc_type, doc_number, phone) "
                "values (:id, :cid, 'Cliente Test', 'cc', :doc, '3000000000')"
            ),
            {"id": str(customer_id), "cid": str(company_id), "doc": str(uuid4().int)[:10]},
        )
        await session.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, null, 1, 'Joyería', 'J')"
            ),
            {"id": str(cat1), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 2, 'Oro', 'O')"
            ),
            {"id": str(cat2), "cid": str(company_id), "parent": str(cat1)},
        )
        await session.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, "
                " default_term_months, arrears_window_months) "
                "values (:id, :cid, :parent, 3, 'Cadena', 'C', 4, 4)"
            ),
            {"id": str(cat3), "cid": str(company_id), "parent": str(cat2)},
        )
        await session.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.cash_session "
                "(company_id, register_id, opened_by, opening_balance) "
                "values (:cid, :rid, :cid, 2000000)"
            ),
            {"cid": str(company_id), "rid": str(register_id)},
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    yield {
        "company_id": company_id,
        "customer_id": customer_id,
        "category_id": cat3,
        "token": token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.contract_item where company_id = :cid")
    await _try_delete("delete from public.contract where company_id = :cid")
    await _try_delete("delete from public.code_counter where company_id = :cid")
    await _try_delete("delete from public.customer where company_id = :cid")
    await _try_delete("delete from public.category where company_id = :cid and level = 3")
    await _try_delete("delete from public.category where company_id = :cid and level = 2")
    await _try_delete("delete from public.category where company_id = :cid and level = 1")
    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.cash_session where company_id = :cid")
    await _try_delete("delete from public.cash_register where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


async def _read_contract_status(*, company_id: uuid.UUID, contract_id: str) -> str:
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text("select status from public.contract where company_id = :cid and id = :id"),
                {"cid": str(company_id), "id": contract_id},
            )
        ).first()
        assert row is not None
        return str(row[0])


async def test_recompute_all_statuses_moves_active_contract_into_arrears(
    client: TestClient, recompute_tenant: dict
) -> None:
    headers = _headers(recompute_tenant["token"], idempotency_key=str(uuid4()))
    created = client.post(
        "/api/v1/contracts",
        headers=headers,
        json={
            "customer_id": str(recompute_tenant["customer_id"]),
            "principal": "1000000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [
                {"category_id": str(recompute_tenant["category_id"]), "description": "Cadena"}
            ],
        },
    )
    assert created.status_code == 201, created.text
    contract_id = created.json()["id"]
    assert created.json()["status"] == "active"

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "update public.contract "
                "set interest_paid_until = interest_paid_until - interval '2 months' "
                "where company_id = :cid and id = :id"
            ),
            {"cid": str(recompute_tenant["company_id"]), "id": contract_id},
        )

    assert (
        await _read_contract_status(
            company_id=recompute_tenant["company_id"], contract_id=contract_id
        )
        == "active"
    )

    async with AsyncSessionLocal() as db, db.begin():
        updated = await contracts_service.recompute_all_statuses(db)
    assert updated >= 1

    assert (
        await _read_contract_status(
            company_id=recompute_tenant["company_id"], contract_id=contract_id
        )
        == "in_arrears"
    )


@pytest.fixture
def super_admin_token(monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]) -> str:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    return make_token(private_pem, sub=str(uuid4()), app_metadata={"platform_role": "super_admin"})


@pytest_asyncio.fixture
async def mocked_invite(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    async def _fake_invite(
        email: str, full_name: str, *, send_email: bool = True
    ) -> identity_auth_admin.Invitation:
        return identity_auth_admin.Invitation(
            user_id=uuid4(), link=None if send_email else "https://supabase.test/verify?token=fake"
        )

    monkeypatch.setattr(identity_auth_admin, "invite_user", _fake_invite)
    return []


@pytest_asyncio.fixture
async def overdue_company(
    client: TestClient, mocked_invite: list[str], super_admin_token: str
) -> AsyncGenerator[dict, None]:
    response = client.post(
        "/api/v1/platform/companies",
        headers=_headers(super_admin_token),
        json={
            "name": "Empresa nightly-overdue-test",
            "plan_code": "full",
            "subscription_expires_at": "2020-01-01",
            "first_admin_email": "admin-nightly-test@example.com",
            "first_admin_full_name": "Admin Nightly Test",
        },
    )
    assert response.status_code == 201, response.text
    company_id = uuid.UUID(response.json()["id"])

    async with AsyncSessionLocal() as session:
        admin_row = (
            await session.execute(
                text(
                    "select au.id, au.role_id from public.app_user au "
                    "join public.role r on r.id = au.role_id "
                    "where au.company_id = :cid and r.name = 'Admin'"
                ),
                {"cid": str(company_id)},
            )
        ).first()
        assert admin_row is not None

    yield {"company_id": company_id, "admin_user_id": admin_row[0], "admin_role_id": admin_row[1]}

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
    await _try_delete("delete from public.cash_register where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


async def test_expire_overdue_subscriptions_blocks_access(
    client: TestClient, overdue_company: dict, rsa_keypair: tuple[str, object]
) -> None:
    private_pem, _ = rsa_keypair
    company_id = overdue_company["company_id"]

    async with AsyncSessionLocal() as db, db.begin():
        expired_count = await platform_service.expire_overdue_subscriptions(db)
    assert expired_count >= 1

    async with AsyncSessionLocal() as session:
        subscription = (
            await session.execute(
                text("select status from public.subscription where company_id = :cid"),
                {"cid": str(company_id)},
            )
        ).first()
        assert subscription is not None
        assert subscription[0] == "expired"

        audit_row = (
            await session.execute(
                text(
                    "select action from public.audit_log "
                    "where company_id = :cid and action = 'expire_subscription'"
                ),
                {"cid": str(company_id)},
            )
        ).first()
        assert audit_row is not None

    admin_token = make_token(
        private_pem,
        sub=str(overdue_company["admin_user_id"]),
        company_id=str(company_id),
        role_id=str(overdue_company["admin_role_id"]),
    )
    response = client.get("/api/v1/cashbox/expense-categories", headers=_headers(admin_token))
    assert response.status_code == 402
    assert response.json()["code"] == "SUBSCRIPTION_EXPIRED"


async def test_nightly_run_completes_without_error(recompute_tenant: dict) -> None:
    await nightly.run()
