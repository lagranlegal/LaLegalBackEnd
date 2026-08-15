"""Integración de audit (paso 8): consulta de auditoría inmutable, filtros
por módulo/entidad, deny-by-default sin el permiso `audit.view`. El
happy-path cruzado con otros módulos ya se cubre en test_reports.py.
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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def audit_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    full_role_id = uuid4()
    limited_role_id = uuid4()
    full_user_id = uuid4()
    limited_user_id = uuid4()
    register_id = uuid4()
    expense_category_id = uuid4()

    full_codes = ("cashbox.open_close", "cashbox.expense", "audit.view")
    limited_codes = ("cashbox.open_close", "cashbox.expense")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa audit-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, :name)"),
            [
                {"id": str(full_role_id), "cid": str(company_id), "name": "Full"},
                {"id": str(limited_role_id), "cid": str(company_id), "name": "Limited"},
            ],
        )
        for role_id, codes in ((full_role_id, full_codes), (limited_role_id, limited_codes)):
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
                "values (:id, :cid, :role_id, 'User', :email, 'active')"
            ),
            [
                {
                    "id": str(full_user_id),
                    "cid": str(company_id),
                    "role_id": str(full_role_id),
                    "email": f"full-{full_user_id}@example.com",
                },
                {
                    "id": str(limited_user_id),
                    "cid": str(company_id),
                    "role_id": str(limited_role_id),
                    "email": f"limited-{limited_user_id}@example.com",
                },
            ],
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
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.expense_category (id, company_id, name) "
                "values (:id, :cid, 'Servicios')"
            ),
            {"id": str(expense_category_id), "cid": str(company_id)},
        )

    full_token = make_token(
        private_pem, sub=str(full_user_id), company_id=str(company_id), role_id=str(full_role_id)
    )
    limited_token = make_token(
        private_pem,
        sub=str(limited_user_id),
        company_id=str(company_id),
        role_id=str(limited_role_id),
    )

    yield {
        "company_id": company_id,
        "expense_category_id": expense_category_id,
        "full_token": full_token,
        "limited_token": limited_token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.expense where company_id = :cid")
    await _try_delete("delete from public.expense_category where company_id = :cid")
    await _try_delete("delete from public.app_user where company_id = :cid")
    await _try_delete(
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)"
    )
    await _try_delete("delete from public.role where company_id = :cid")
    await _try_delete("delete from public.subscription where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


def _open_session_and_add_expense(client: TestClient, tenant: dict) -> str:
    headers = _headers(tenant["full_token"])
    open_response = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    )
    assert open_response.status_code == 201, open_response.text
    session_id = open_response.json()["id"]

    expense = client.post(
        "/api/v1/cashbox/expenses",
        headers=headers,
        json={
            "category_id": str(tenant["expense_category_id"]),
            "description": "Aseo",
            "amount": "20000.00",
            "payment_method": "cash",
        },
    )
    assert expense.status_code == 201, expense.text
    return str(session_id)


def test_audit_log_without_permission_is_403(client: TestClient, audit_tenant: dict) -> None:
    _open_session_and_add_expense(client, audit_tenant)
    response = client.get("/api/v1/audit-log", headers=_headers(audit_tenant["limited_token"]))
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_audit_log_lists_and_filters_expense_entry(client: TestClient, audit_tenant: dict) -> None:
    _open_session_and_add_expense(client, audit_tenant)
    headers = _headers(audit_tenant["full_token"])

    all_entries = client.get("/api/v1/audit-log", headers=headers)
    assert all_entries.status_code == 200, all_entries.text
    actions = [e["action"] for e in all_entries.json()["items"]]
    assert "create_expense" in actions

    filtered = client.get("/api/v1/audit-log", headers=headers, params={"entity_type": "expense"})
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) >= 1
    assert all(e["entity_type"] == "expense" for e in filtered.json()["items"])

    unrelated = client.get(
        "/api/v1/audit-log", headers=headers, params={"entity_type": "cash_session"}
    )
    assert unrelated.status_code == 200
    assert all(e["entity_type"] == "cash_session" for e in unrelated.json()["items"])
    assert "create_expense" not in [e["action"] for e in unrelated.json()["items"]]
