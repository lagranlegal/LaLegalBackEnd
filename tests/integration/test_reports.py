"""Integración de reports (paso 8): dashboard de KPIs (contratos por
estado + cartera, ventas de hoy/mes, inventario disponible, sesión de caja
actual) e histórico de cierres. Todo se cruza contra datos creados vía las
APIs de contracts/inventory/sales/cashbox ya probadas en pasos anteriores.
Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from datetime import date
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
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
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
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "purchase",
            "supplier_id": str(reports_tenant["supplier_id"]),
            "payment_method": "cash",
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
    # Se identifican por su COSTO, no por su posición en la lista: el orden en
    # que vuelven los ítems de un ingreso no es parte del contrato de la API
    # (todos comparten `created_at` — se insertan en la misma transacción).
    # Antes este test asumía el orden y fallaba o pasaba según qué otro test
    # hubiera corrido antes.
    items = {item["cost"]: item for item in entry.json()["items"]}
    assert len(items) == 2
    cheap, expensive = items["100000.00"], items["150000.00"]

    for item, price in ((cheap, "200000.00"), (expensive, "300000.00")):
        publish = client.post(
            f"/api/v1/inventory/items/{item['id']}/publish",
            headers=headers,
            json={"sale_price": price},
        )
        assert publish.status_code == 200, publish.text

    # Se vende el barato (costo 100.000) → queda disponible el de 150.000.
    sale = client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [{"item_id": cheap["id"], "quantity": 1, "unit_price": "200000.00"}],
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


# ---- Utilidad bruta / costo de ventas (docs/PENDIENTES_BACKEND_INFRA.md #24.1:
# `inventory_item.cost` y `sale_line.unit_price` existían pero nada los cruzaba,
# así que "¿cuánto gané con lo que vendí?" no tenía respuesta).


def _profit(client: TestClient, token: str, frm: str, to: str) -> dict:
    r = client.get(
        "/api/v1/reports/profit",
        headers={"Authorization": f"Bearer {token}"},
        params={"from_date": frm, "to_date": to},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_profit_summary_crosses_cost_against_price(
    client: TestClient, reports_tenant: dict
) -> None:
    """Costo 100.000 + 150.000, vendidos a 200.000 y 300.000 → utilidad
    250.000 sobre ingreso 500.000 = 50% de margen."""
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "500000.00"}
    )

    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "purchase",
            "supplier_id": str(reports_tenant["supplier_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "name": "Anillo barato",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "100000.00",
                    "photos": ["http://example.com/a.jpg"],
                },
                {
                    "name": "Anillo caro",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "150000.00",
                    "photos": ["http://example.com/b.jpg"],
                },
            ],
        },
    ).json()

    items = {i["cost"]: i for i in entry["items"]}
    for cost, price in (("100000.00", "200000.00"), ("150000.00", "300000.00")):
        item = items[cost]
        client.post(
            f"/api/v1/inventory/items/{item['id']}/publish",
            headers=headers,
            json={"sale_price": price},
        )
        sale = client.post(
            "/api/v1/sales",
            headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
            json={
                "payment_method": "cash",
                "lines": [{"item_id": item["id"], "quantity": 1, "unit_price": price}],
            },
        )
        assert sale.status_code == 201, sale.text
        # El costo queda CONGELADO en la línea, no se lee del artículo después.
        assert sale.json()["lines"][0]["unit_cost"] == cost

    today = date.today().isoformat()
    body = _profit(client, reports_tenant["token"], today, today)

    assert body["sale_count"] == 2
    assert body["units_sold"] == 2
    assert float(body["gross_revenue"]) == 500000.0
    assert float(body["cost_of_goods_sold"]) == 250000.0
    assert float(body["gross_profit"]) == 250000.0
    assert float(body["margin_pct"]) == 50.0


def test_profit_summary_is_empty_outside_the_range(
    client: TestClient, reports_tenant: dict
) -> None:
    """Margen `null` y no 0 cuando no hubo ventas: 0% afirma "vendí sin ganar",
    que es distinto de "no hay datos"."""
    body = _profit(client, reports_tenant["token"], "2020-01-01", "2020-01-31")
    assert body["sale_count"] == 0
    assert float(body["gross_profit"]) == 0.0
    assert body["margin_pct"] is None


def test_profit_summary_rejects_inverted_and_huge_ranges(
    client: TestClient, reports_tenant: dict
) -> None:
    headers = {"Authorization": f"Bearer {reports_tenant['token']}"}
    inverted = client.get(
        "/api/v1/reports/profit",
        headers=headers,
        params={"from_date": "2026-08-10", "to_date": "2026-08-01"},
    )
    assert inverted.status_code == 400

    huge = client.get(
        "/api/v1/reports/profit",
        headers=headers,
        params={"from_date": "2020-01-01", "to_date": "2026-01-01"},
    )
    assert huge.status_code == 400


# ---- Rentabilidad del empeño (docs/PENDIENTES_BACKEND_INFRA.md #24.1, parte
# que quedó abierta tras el costo de ventas: el empeño no tiene costo de
# ventas, su rentabilidad son los intereses sobre el capital prestado).


async def _owe_one_month(contract_id: str) -> None:
    """Un contrato recién creado debe 0 meses, así que no admite abono de
    interés. Se retrocede `interest_paid_until` un mes y un día para que deba
    exactamente uno: el límite EXACTO de un mes cuenta como 0 adeudados
    (comportamiento confirmado del backend, ver PENDIENTES #10)."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "update public.contract "
                "set interest_paid_until = current_date - interval '1 month 1 day' "
                "where id = :id"
            ),
            {"id": contract_id},
        )


def _pawn(client: TestClient, token: str, frm: str, to: str) -> dict:
    r = client.get(
        "/api/v1/reports/pawn-performance",
        headers={"Authorization": f"Bearer {token}"},
        params={"from_date": frm, "to_date": to},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


@pytest.mark.asyncio
async def test_pawn_performance_reports_interest_over_portfolio(
    client: TestClient, reports_tenant: dict
) -> None:
    """Préstamo de 1.000.000 al 5%: un abono de 1 mes cobra 50.000 de interés
    y 200.000 a capital → cartera 800.000 y rendimiento 50.000/800.000 = 6.25%.
    """
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "5000000.00"}
    )

    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(reports_tenant["customer_id"]),
            "principal": "1000000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [{"category_id": str(reports_tenant["category_id"]), "description": "Cadena"}],
        },
    )
    assert contract.status_code == 201, contract.text
    await _owe_one_month(contract.json()["id"])

    payment = client.post(
        f"/api/v1/contracts/{contract.json()['id']}/payments",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={"months_covered": 1, "capital_amount": "200000.00", "payment_method": "cash"},
    )
    assert payment.status_code == 201, payment.text

    today = date.today().isoformat()
    body = _pawn(client, reports_tenant["token"], today, today)

    assert float(body["interest_collected"]) == 50000.0
    assert float(body["capital_recovered"]) == 200000.0
    assert float(body["capital_disbursed"]) == 1000000.0
    assert float(body["capital_outstanding"]) == 800000.0
    assert body["payment_count"] == 1
    assert body["contracts_opened"] == 1
    assert body["open_contracts"] == 1
    assert float(body["yield_on_current_portfolio_pct"]) == 6.25


@pytest.mark.asyncio
async def test_pawn_interest_comes_from_documents_not_closed_cash_sessions(
    client: TestClient, reports_tenant: dict
) -> None:
    """El motivo de leer `contract_payment` y no el desglose de caja: ese solo
    cubre sesiones CERRADAS, así que un abono de hoy —con la caja todavía
    abierta— no aparecería. Acá la sesión nunca se cierra y el interés se
    reporta igual."""
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "5000000.00"}
    )
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(reports_tenant["customer_id"]),
            "principal": "500000.00",
            "interest_rate_pct": "10",
            "payment_method": "cash",
            "items": [{"category_id": str(reports_tenant["category_id"]), "description": "Anillo"}],
        },
    ).json()
    await _owe_one_month(contract["id"])
    paid = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={"months_covered": 1, "payment_method": "cash"},
    )
    assert paid.status_code == 201, paid.text

    today = date.today().isoformat()
    body = _pawn(client, reports_tenant["token"], today, today)
    assert float(body["interest_collected"]) == 50000.0


def test_pawn_performance_empty_period_has_null_yield(
    client: TestClient, reports_tenant: dict
) -> None:
    """Sin cartera abierta el rendimiento es `null`, no 0: un 0% afirmaría
    "presté y no rindió", distinto de "no hay capital contra el cual medir"."""
    body = _pawn(client, reports_tenant["token"], "2020-01-01", "2020-01-31")
    assert float(body["interest_collected"]) == 0.0
    assert body["contracts_opened"] == 0
    assert body["yield_on_current_portfolio_pct"] is None
