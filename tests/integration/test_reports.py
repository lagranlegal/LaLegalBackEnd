"""Integración de reports (paso 8): dashboard de KPIs (contratos por
estado + cartera, ventas de hoy/mes, inventario disponible, sesión de caja
actual) e histórico de cierres. Todo se cruza contra datos creados vía las
APIs de contracts/inventory/sales/cashbox ya probadas en pasos anteriores.
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


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


@pytest_asyncio.fixture
async def reports_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()
    customer_id = uuid4()
    supplier_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    register_id = uuid4()
    codes = (
        "contracts.create",
        "contracts.view",
        "payments.create",
        "cashbox.view",
        "cashbox.open_close",
        "inventory.create",
        "sales.create",
        "reports.view",
        "audit.view",
    )

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa reports-test')"),
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
                "insert into public.supplier (id, company_id, name, code_letter) "
                "values (:id, :cid, 'Proveedor Test', 'P')"
            ),
            {"id": str(supplier_id), "cid": str(company_id)},
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

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    yield {
        "company_id": company_id,
        "customer_id": customer_id,
        "category_id": cat3,
        "cat1_id": cat1,
        "cat2_id": cat2,
        "cat3_id": cat3,
        "supplier_id": supplier_id,
        "register_id": register_id,
        "token": token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.sale_line where company_id = :cid")
    await _try_delete("delete from public.sale where company_id = :cid")
    await _try_delete("delete from public.inventory_entry_line where company_id = :cid")
    await _try_delete("delete from public.inventory_entry where company_id = :cid")
    await _try_delete("delete from public.inventory_item where company_id = :cid")
    await _try_delete("delete from public.contract_item where company_id = :cid")
    await _try_delete("delete from public.contract where company_id = :cid")
    await _try_delete("delete from public.code_counter where company_id = :cid")
    await _try_delete("delete from public.customer where company_id = :cid")
    await _try_delete("delete from public.supplier where company_id = :cid")
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
    await _try_delete("delete from public.company where id = :cid")


def test_dashboard_and_closing_history(client: TestClient, reports_tenant: dict) -> None:
    headers = _headers(reports_tenant["token"])

    # Base amplia: el contrato desembolsa 1.000.000 en efectivo al firmar
    # (préstamo = salida de caja), así que la base debe cubrirlo para que
    # `expected_cash` no quede negativo al cerrar.
    open_response = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "2000000.00"}
    )
    assert open_response.status_code == 201, open_response.text
    session_id = open_response.json()["id"]

    contract = client.post(
        "/api/v1/contracts",
        headers=headers,
        json={
            "customer_id": str(reports_tenant["customer_id"]),
            "principal": "1000000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [{"category_id": str(reports_tenant["category_id"]), "description": "Cadena"}],
        },
    )
    assert contract.status_code == 201, contract.text

    entry = client.post(
        "/api/v1/inventory/entries",
        headers=headers,
        json={
            "origin_type": "purchase",
            "supplier_id": str(reports_tenant["supplier_id"]),
            "lines": [
                {
                    "name": "Anillo A",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "100000.00",
                    "photos": ["http://example.com/a.jpg"],
                },
                {
                    "name": "Anillo B",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "150000.00",
                    "photos": ["http://example.com/b.jpg"],
                },
            ],
        },
    )
    assert entry.status_code == 201, entry.text
    items = entry.json()["items"]
    assert len(items) == 2

    for item, price in zip(items, ("200000.00", "300000.00"), strict=True):
        publish = client.post(
            f"/api/v1/inventory/items/{item['id']}/publish",
            headers=headers,
            json={"sale_price": price},
        )
        assert publish.status_code == 200, publish.text

    sale = client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [{"item_id": items[0]["id"], "quantity": 1, "unit_price": "200000.00"}],
        },
    )
    assert sale.status_code == 201, sale.text

    dashboard = client.get("/api/v1/reports/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()

    assert body["contracts"]["active_count"] >= 1
    assert float(body["contracts"]["capital_outstanding"]) >= 1_000_000.0
    assert body["inventory"]["available_count"] == 1
    assert float(body["inventory"]["available_value"]) == pytest.approx(150000.0)
    assert body["sales"]["today_count"] >= 1
    assert float(body["sales"]["today_total"]) >= 200000.0
    assert body["cashbox"]["session_open"] is True
    assert body["cashbox"]["session_id"] == session_id

    report = client.get(f"/api/v1/cashbox/sessions/{session_id}/report", headers=headers)
    assert report.status_code == 200, report.text
    expected_cash = report.json()["expected_cash"]

    close = client.post(
        f"/api/v1/cashbox/sessions/{session_id}/close",
        headers=headers,
        json={"counted_cash": expected_cash},
    )
    assert close.status_code == 200, close.text

    dashboard_after_close = client.get("/api/v1/reports/dashboard", headers=headers)
    assert dashboard_after_close.json()["cashbox"]["session_open"] is False

    closings = client.get("/api/v1/reports/closings", headers=headers)
    assert closings.status_code == 200, closings.text
    closing_ids = [c["session_id"] for c in closings.json()["items"]]
    assert session_id in closing_ids
    closed_entry = next(c for c in closings.json()["items"] if c["session_id"] == session_id)
    assert closed_entry["difference"] == "0.00"

    audit = client.get(
        "/api/v1/audit-log", headers=headers, params={"module": "cashbox", "entity_id": session_id}
    )
    assert audit.status_code == 200, audit.text
    audit_actions = [a["action"] for a in audit.json()["items"]]
    assert "close_session" in audit_actions
