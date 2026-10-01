"""Integración de reports (paso 8): dashboard de KPIs (contratos por
estado + cartera, ventas de hoy/mes, inventario disponible, sesión de caja
actual) e histórico de cierres. Todo se cruza contra datos creados vía las
APIs de contracts/inventory/sales/cashbox ya probadas en pasos anteriores.
Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from _dates import hoy_empresa, mediodia_empresa
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.common.tenant_time import previous_month_to_date_bounds
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
        # El estado de resultados resta los descuentos de interés igual que los
        # de venta, así que este tenant tiene que poder otorgarlos para probarlo.
        "payments.apply_discount",
        "cashbox.view",
        # Desde 00031 el histórico de cierres exige su propio permiso, y
        # `GET /reports/closings` lo pide ADEMÁS de `reports.view`: es el mismo
        # dato que `GET /cashbox/sessions`, así que dejarlo colgando solo de
        # `reports.view` habría dejado una puerta de atrás al control.
        "cashbox.view_history",
        "cashbox.open_close",
        # El estado de resultados resta gastos reales, así que el tenant de
        # reportes tiene que poder crearlos.
        "cashbox.expense",
        "inventory.create",
        "inventory.view",
        "sales.create",
        "sales.view",
        # F21-12: el estado de resultados resta las devoluciones del período,
        # así que este tenant tiene que poder registrarlas — y otorgar el
        # descuento de venta cuyo prorrateo se prueba.
        "sales.return",
        # 45 días después de la venta la devolución queda fuera del plazo por
        # defecto (30 días): el camino real de negocio es el override.
        "sales.return_override_time_limit",
        "sales.apply_discount",
        "reports.view",
        "audit.view",
        # F4-06: lo prestado del período se prueba con un recargo y un
        # contrato importado, que no son desembolsos nuevos.
        "contracts.import",
        "contracts.extend_loan",
        # Fase 7: `capital/position` repite la valoración del inventario y
        # ahora los pasivos, así que se cruza contra los reportes.
        "capital.view",
        # Fase 7: mermas, comisiones de convenio, remates y descuentos por
        # precio llegan al estado de resultados, así que se generan acá.
        "inventory.exit",
        "contracts.auction",
        "accounts.view",
        "accounts.manage",
        "accounts.settle",
        # F7-05: el flujo de ventas de caja descuenta las anuladas.
        "sales.void",
        # F7-16: pagar una compra a crédito mueve «Pagos de compras».
        "inventory.pay_purchase",
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

    await _try_delete("delete from public.sale_return_line where company_id = :cid")
    await _try_delete("delete from public.sale_return where company_id = :cid")
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

    # `/closings-breakdown`: la misma información de `/cashbox/sessions/{id}/report`
    # (docs/PENDIENTES_FRONTEND.md #11 — antes el front pedía ese endpoint una
    # vez POR SESIÓN del rango para armar Reportes), pero sumada sobre el
    # rango completo en una sola consulta. Sin from_date/to_date: trae todo.
    session_report = client.get(
        f"/api/v1/cashbox/sessions/{session_id}/report", headers=headers
    ).json()
    breakdown = client.get("/api/v1/reports/closings-breakdown", headers=headers)
    assert breakdown.status_code == 200, breakdown.text
    breakdown_lines = breakdown.json()["lines"]
    # Toda línea del desglose por rango trae la fecha de SU sesión — acá solo
    # hay una, así que deben coincidir en fecha con el cierre de arriba.
    assert all(line["session_date"] == closed_entry["session_date"] for line in breakdown_lines)
    for session_line in session_report["lines"]:
        match = next(
            (
                b
                for b in breakdown_lines
                if b["module"] == session_line["module"]
                and b["concept"] == session_line["concept"]
                and b["payment_method"] == session_line["payment_method"]
                and b["account_id"] == session_line["account_id"]
            ),
            None,
        )
        assert match is not None, (
            f"línea de la sesión no encontrada en el desglose por rango: {session_line}"
        )
        assert match["total"] == session_line["total"]

    audit = client.get(
        "/api/v1/audit-log", headers=headers, params={"module": "cashbox", "entity_id": session_id}
    )
    assert audit.status_code == 200, audit.text
    audit_actions = [a["action"] for a in audit.json()["items"]]
    assert "close_session" in audit_actions


def test_desglose_incluye_lo_cobrado_por_banco_con_la_caja_cerrada(
    client: TestClient, reports_tenant: dict
) -> None:
    """F21-35: una venta por transferencia hecha con la caja CERRADA entra al
    desglose, en su día; el ajuste del arqueo del cajón sigue afuera.

    Antes, `closings_breakdown` hacía INNER JOIN con `cash_session`, así que
    un movimiento contra una cuenta `bank` entraba SOLO si por casualidad
    había un turno abierto cuando se registró (`resolve_account_for_movement`
    le cuelga la sesión abierta si existe, y `NULL` si no). La misma venta por
    transferencia contaba en «Ventas» a las 10 a. m. y desaparecía del reporte
    para siempre a las 7 p. m., después del cierre. Medido en dev el 25/09:
    12 movimientos `bank` ($6.512.222) adentro por coincidencia, 2 ($5.060.000)
    afuera por la misma coincidencia.
    """
    headers = _headers(reports_tenant["token"])
    # Se cuenta al abrir con 500.000 sobre un cajón en 0: eso emite un
    # `adjustment` de apertura con `session_id = NULL`, contra la cuenta `cash`.
    opened = client.post(
        "/api/v1/cashbox/sessions/open",
        headers=headers,
        json={"counted_cash": "500000.00", "difference_reason": "base del día"},
    )
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["id"]
    item_id = _ingresar_uno(client, reports_tenant, unit_cost="100000.00", unit_price="250000.00")

    expected = client.get(f"/api/v1/cashbox/sessions/{session_id}/report", headers=headers).json()[
        "expected_cash"
    ]
    # Cierre con faltante: otro `adjustment` sin sesión, el del arqueo.
    close = client.post(
        f"/api/v1/cashbox/sessions/{session_id}/close",
        headers=headers,
        json={
            "counted_cash": str(Decimal(expected) - Decimal("7000.00")),
            "difference_reason": "faltante",
        },
    )
    assert close.status_code == 200, close.text
    session_date = close.json()["session_date"]

    # Caja cerrada. La transferencia no la necesita (la exige el TIPO de
    # cuenta), así que la venta pasa y su movimiento nace sin sesión.
    sale = client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "transfer",
            "lines": [{"item_id": item_id, "quantity": "1", "unit_price": "250000.00"}],
        },
    )
    assert sale.status_code == 201, sale.text

    def _lines(**params: str) -> list[dict]:
        r = client.get("/api/v1/reports/closings-breakdown", headers=headers, params=params)
        assert r.status_code == 200, r.text
        return list(r.json()["lines"])

    lines = _lines()
    bank_sales = [x for x in lines if x["concept"] == "sale" and x["account_type"] == "bank"]
    assert len(bank_sales) == 1, lines
    assert bank_sales[0]["total"] == "250000.00"
    # Su día es el de la EMPRESA en que se registró — que acá coincide con el
    # del turno que ya cerró.
    assert bank_sales[0]["session_date"] == session_date

    # Los dos ajustes del cajón (apertura y arqueo) siguen afuera: son el
    # arqueo, y F21-14 los reporta aparte desde el acta. Sumarlos acá los
    # contaría dos veces en la misma pantalla.
    assert not [x for x in lines if x["concept"] == "adjustment"], lines

    # El rango filtra por ese mismo día, no por el turno.
    assert any(
        x["concept"] == "sale" and x["account_type"] == "bank"
        for x in _lines(from_date=session_date, to_date=session_date)
    )
    ayer = (date.fromisoformat(session_date) - timedelta(days=1)).isoformat()
    assert _lines(to_date=ayer) == []


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

    today = hoy_empresa().isoformat()
    body = _profit(client, reports_tenant["token"], today, today)

    assert body["sale_count"] == 2
    assert Decimal(body["units_sold"]) == 2
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
    assert inverted.status_code == 422
    assert inverted.json()["code"] == "INVALID_DATE_RANGE"

    huge = client.get(
        "/api/v1/reports/profit",
        headers=headers,
        params={"from_date": "2020-01-01", "to_date": "2026-01-01"},
    )
    assert huge.status_code == 422
    assert huge.json()["code"] == "DATE_RANGE_TOO_LONG"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/reports/profit",
        "/api/v1/reports/pawn-performance",
        "/api/v1/reports/income-statement",
    ],
)
def test_rango_invertido_es_422_con_codigo_en_todos_los_reportes(
    client: TestClient, reports_tenant: dict, path: str
) -> None:
    """F7-14 (auditoría fase 7, 28/09/2026): `income-statement` —y por él
    `capital/position`— aceptaba `from=2026-09-28, to=2026-01-01` y respondía
    200 con todo en cero: un «no hubo nada» falso. `/profit` y
    `/pawn-performance` sí lo rechazaban, pero con el 400 genérico. Ahora los
    tres responden lo mismo: 422 con un código que el front distingue.

    El tope de 366 días NO se extiende al estado de resultados: `capital/
    position` lo pide «desde siempre» y es una sola consulta agregada."""
    headers = {"Authorization": f"Bearer {reports_tenant['token']}"}
    inverted = client.get(
        path, headers=headers, params={"from_date": "2026-09-28", "to_date": "2026-01-01"}
    )
    assert inverted.status_code == 422, inverted.text
    assert inverted.json()["code"] == "INVALID_DATE_RANGE"


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

    today = hoy_empresa().isoformat()
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

    today = hoy_empresa().isoformat()
    body = _pawn(client, reports_tenant["token"], today, today)
    assert float(body["interest_collected"]) == 50000.0


@pytest.mark.asyncio
async def test_lo_prestado_es_lo_que_salio_de_caja_en_el_periodo(
    client: TestClient, reports_tenant: dict
) -> None:
    """F4-06 (B-02, B-03): `capital_disbursed` es lo que salió de caja por
    préstamos en el período. Un recargo aporta solo su delta, el día del
    recargo; un contrato importado no aporta nada. `contracts_opened` cuenta
    solo los préstamos nuevos."""
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "5000000.00"}
    )
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.category set max_ltv_pct = 70 where company_id = :cid"),
            {"cid": str(reports_tenant["company_id"])},
        )
    item = {"category_id": str(reports_tenant["category_id"]), "description": "Cadena"}
    nativo = client.post(
        "/api/v1/contracts",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(reports_tenant["customer_id"]),
            "principal": "1000000.00",
            "appraisal_value": "2000000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [item],
        },
    )
    assert nativo.status_code == 201, nativo.text
    recargo = client.post(
        f"/api/v1/contracts/{nativo.json()['id']}/extend-loan",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={"amount": "300000.00", "payment_method": "cash"},
    )
    assert recargo.status_code == 201, recargo.text
    assert recargo.json()["principal"] == "1300000.00"

    today = hoy_empresa()
    importado = client.post(
        "/api/v1/contracts/import",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "legacy_code": f"LEGACY-{uuid4()}",
            "customer_id": str(reports_tenant["customer_id"]),
            "principal": "400000.00",
            "capital_balance": "400000.00",
            "interest_rate_pct": "5",
            "term_months": 4,
            "arrears_window_months": 4,
            "extension_months": 1,
            "start_date": today.isoformat(),
            "interest_paid_until": today.isoformat(),
            "items": [item],
        },
    )
    assert importado.status_code == 201, importado.text

    body = _pawn(client, reports_tenant["token"], today.isoformat(), today.isoformat())
    assert body["capital_disbursed"] == "1300000.00"
    assert body["contracts_opened"] == 1

    estado = client.get(
        "/api/v1/reports/income-statement",
        headers=headers,
        params={"from_date": today.isoformat(), "to_date": today.isoformat()},
    )
    assert estado.status_code == 200, estado.text
    assert estado.json()["capital_disbursed"] == "1300000.00"


def test_pawn_performance_empty_period_has_null_yield(
    client: TestClient, reports_tenant: dict
) -> None:
    """Sin cartera abierta el rendimiento es `null`, no 0: un 0% afirmaría
    "presté y no rindió", distinto de "no hay capital contra el cual medir"."""
    body = _pawn(client, reports_tenant["token"], "2020-01-01", "2020-01-31")
    assert float(body["interest_collected"]) == 0.0
    assert body["contracts_opened"] == 0
    assert body["yield_on_current_portfolio_pct"] is None


def test_income_statement_subtracts_the_cost_of_goods_sold(
    client: TestClient, reports_tenant: dict
) -> None:
    """El estado de resultados resta el COSTO DE VENTAS. Ese era el bug.

    La "utilidad operativa" de `/reportes` calculaba `ingresos − gastos` y
    nunca restaba lo que costó la mercancía: una cadena vendida en 500.000 que
    costó 300.000 contaba como 500.000 de utilidad. Y en la misma pantalla
    convivía con "Utilidad bruta de tienda", que sí lo restaba — dos cifras
    contradiciéndose.
    """
    headers = _headers(reports_tenant["token"])
    # Sin conteo: desde la fase 7 un conteo de apertura distinto del efectivo
    # derivado es un descuadre y entra al resultado (F7-03).
    client.post("/api/v1/cashbox/sessions/open", headers=headers, json={})

    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "purchase",
            "supplier_id": str(reports_tenant["supplier_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "name": "Cadena del estado de resultados",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "300000.00",
                    "photos": ["http://example.com/x.jpg"],
                    "sale_price": "500000.00",
                }
            ],
        },
    ).json()
    item_id = entry["items"][0]["id"]

    venta = client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [{"item_id": item_id, "quantity": "1", "unit_price": "500000.00"}],
        },
    )
    assert venta.status_code == 201, venta.text

    # Un gasto real del período.
    categoria = client.post(
        "/api/v1/cashbox/expense-categories",
        headers=headers,
        json={"name": f"Arriendo {uuid4().hex[:6]}"},
    ).json()
    client.post(
        "/api/v1/cashbox/expenses",
        headers=headers,
        json={
            "category_id": categoria["id"],
            "description": "Arriendo del local",
            "amount": "80000.00",
            "payment_method": "cash",
        },
    )

    hoy = hoy_empresa().isoformat()
    r = client.get(
        "/api/v1/reports/income-statement",
        headers={"Authorization": f"Bearer {reports_tenant['token']}"},
        params={"from_date": hoy, "to_date": hoy},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert Decimal(body["sales_revenue"]) == Decimal("500000.00")
    assert Decimal(body["cost_of_goods_sold"]) == Decimal("300000.00")
    # 500.000 − 300.000 = 200.000. El número viejo habría dicho 500.000.
    assert Decimal(body["gross_profit"]) == Decimal("200000.00")
    assert Decimal(body["operating_expenses"]) == Decimal("80000.00")
    # 200.000 − 80.000 = 120.000. ESTE es "cuánto ganó el negocio".
    assert Decimal(body["operating_profit"]) == Decimal("120000.00")
    assert Decimal(body["margin_pct"]) == Decimal("24.00")


def test_income_statement_keeps_capital_and_purchases_out_of_the_result(
    client: TestClient, reports_tenant: dict
) -> None:
    """Prestar no es gasto, cobrar no es ganancia, comprar no es gasto.

    Los tres principios que este proyecto ya pagó caro. Van fuera del
    resultado y se devuelven aparte —no escondidos— para que nadie los busque
    en otra pantalla y concluya que faltan.
    """
    headers = _headers(reports_tenant["token"])
    # Sin conteo: desde la fase 7 un conteo de apertura distinto del efectivo
    # derivado es un descuadre y entra al resultado (F7-03).
    client.post("/api/v1/cashbox/sessions/open", headers=headers, json={})

    # Una compra de mercancía: sale plata, pero NO es gasto.
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "purchase",
            "supplier_id": str(reports_tenant["supplier_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "name": "Mercancía que no es gasto",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "700000.00",
                }
            ],
        },
    )

    hoy = hoy_empresa().isoformat()
    body = client.get(
        "/api/v1/reports/income-statement",
        headers={"Authorization": f"Bearer {reports_tenant['token']}"},
        params={"from_date": hoy, "to_date": hoy},
    ).json()

    # La compra aparece, pero FUERA del resultado.
    assert Decimal(body["inventory_purchased"]) == Decimal("700000.00")
    assert Decimal(body["operating_expenses"]) == Decimal("0.00")
    # Sin ventas no hay costo de ventas: esos 700.000 son inventario, no gasto.
    assert Decimal(body["cost_of_goods_sold"]) == Decimal("0.00")
    assert Decimal(body["operating_profit"]) == Decimal("0.00")
    # Y sin ingresos el margen es `null`, no 0% — "no vendí" no es "vendí sin
    # ganar".
    assert body["margin_pct"] is None


def test_monthly_series_includes_empty_months_and_uses_document_dates(
    client: TestClient, reports_tenant: dict
) -> None:
    """`GET /reports/series` (docs/PENDIENTES_BACKEND_INFRA.md §7).

    Dos cosas que la gráfica necesita y que es fácil romper:
    1. Los meses SIN actividad vienen en cero, no faltan. Un hueco haría que
       la línea uniera dos meses no consecutivos y mostrara una tendencia que
       nunca existió.
    2. El ingreso sale de los DOCUMENTOS (venta/abono), no del desglose de
       caja — así incluye lo de hoy, con la sesión todavía abierta.
    """
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
                    "name": "Cadena de la serie",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "300000.00",
                    "photos": ["http://example.com/x.jpg"],
                    "sale_price": "500000.00",
                }
            ],
        },
    ).json()
    client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": entry["items"][0]["id"], "quantity": "1", "unit_price": "500000.00"}
            ],
        },
    )

    resp = client.get("/api/v1/reports/series", headers=headers, params={"months": 6})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["months"] == 6
    # Seis meses, ninguno omitido, en orden cronológico.
    assert len(body["points"]) == 6
    months = [p["month"] for p in body["points"]]
    assert months == sorted(months)

    # La venta de hoy (sesión de caja todavía ABIERTA) ya cuenta: el ingreso
    # sale del documento, no del cierre.
    assert Decimal(body["points"][-1]["sales_revenue"]) >= Decimal("500000.00")

    # Los meses anteriores no tienen actividad de este tenant, pero vienen.
    for punto in body["points"][:-1]:
        assert Decimal(punto["sales_revenue"]) == Decimal("0.00")
        assert Decimal(punto["interest_revenue"]) == Decimal("0.00")


def test_monthly_series_rejects_an_out_of_range_months_value(
    client: TestClient, reports_tenant: dict
) -> None:
    """`months` acotado: sin tope, alguien pide 500 meses y la consulta arma
    una serie que nadie va a graficar."""
    headers = _headers(reports_tenant["token"])
    assert (
        client.get("/api/v1/reports/series", headers=headers, params={"months": 0}).status_code
        == 422
    )
    assert (
        client.get("/api/v1/reports/series", headers=headers, params={"months": 37}).status_code
        == 422
    )


@pytest.mark.asyncio
async def test_interest_discount_lowers_revenue_like_a_sale_discount(
    client: TestClient, reports_tenant: dict
) -> None:
    """Un descuento de interés BAJA el ingreso, igual que el de una venta.

    Hasta el 09/09/2026 el estado de resultados restaba el descuento de las
    ventas (`gross_revenue - discounts`) pero **no** el de los intereses, así
    que la utilidad se sobreestimaba por todo lo que la compraventa hubiera
    perdonado. Y `GET /reports/series` arrastraba la misma definición, así que
    la gráfica de doce meses tenía el mismo sesgo.

    Un descuento sobre el interés es plata que se decidió no cobrar —una rebaja
    del ingreso—, y da lo mismo que sea sobre una venta o sobre un interés: los
    dos ingresos del mismo estado de resultados no pueden seguir criterios
    distintos.
    """
    token = reports_tenant["token"]
    headers = _headers(token)
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "5000000.00"}
    )

    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(token, idempotency_key=str(uuid4())),
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

    # 50.000 de interés, 10.000 perdonados → entran 40.000.
    payment = client.post(
        f"/api/v1/contracts/{contract.json()['id']}/payments",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "months_covered": 1,
            "payment_method": "cash",
            "discount_amount": "10000.00",
            "discount_reason": "acuerdo con el cliente",
        },
    )
    assert payment.status_code == 201, payment.text
    assert Decimal(payment.json()["total"]) == Decimal("40000.00")

    today = hoy_empresa().isoformat()
    estado = client.get(
        "/api/v1/reports/income-statement",
        headers={"Authorization": f"Bearer {token}"},
        params={"from_date": today, "to_date": today},
    )
    assert estado.status_code == 200, estado.text
    e = estado.json()

    # El ingreso por intereses es el NETO, no el facturado.
    assert Decimal(e["interest_revenue"]) == Decimal("40000.00")
    # El descuento se sigue informando aparte, para poder verlo.
    assert Decimal(e["interest_discounts"]) == Decimal("10000.00")
    # Y no se cuela dos veces: no es un gasto operativo.
    assert Decimal(e["total_revenue"]) == Decimal(e["sales_revenue"]) + Decimal("40000.00")

    serie = client.get(
        "/api/v1/reports/series",
        headers={"Authorization": f"Bearer {token}"},
        params={"months": 1},
    )
    assert serie.status_code == 200, serie.text
    punto = serie.json()["points"][-1]
    # La serie usa la MISMA definición que el estado de resultados, no una tercera.
    assert Decimal(punto["interest_revenue"]) == Decimal("40000.00")


# =========================================================================
# F21-12 · La devolución es CONTRA-INGRESO del período en que se devolvió.
#
# Antes de esto, `profit_summary` filtraba `status = 'completed'` y una
# devolución NUNCA cambia el status (el único `update sale set status` del
# código es a `'voided'`). Resultado: el ingreso devuelto seguía contado, su
# costo seguía dentro del costo de ventas, y la mercancía reingresada volvía
# a sumar en la valorización — el mismo activo contado DOS VECES.
#
# La decisión: una devolución es un DOCUMENTO (`sale_return`), igual que
# `sale`, `contract_payment` y `expense`, y el estado de resultados sale de
# los documentos. Se lee, no se borra la venta. Tres razones:
#   1. Es la doctrina que el módulo ya aplica.
#   2. Cambiar `sale.status` sacaría la venta ENTERA del resultado por una
#      devolución PARCIAL, y reescribiría un mes ya cerrado (F21-15).
#   3. `sale_return.return_date` existe: el contra-ingreso cae en su propio
#      período y el mes de la venta no se mueve.
# =========================================================================


def _return_sale(
    client: TestClient, token: str, sale_id: str, lines: list[dict], *, restock: bool = True
) -> dict:
    r = client.post(
        f"/api/v1/sales/{sale_id}/returns",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "reason": "defect",
            "settlement_method": "cash",
            "lines": [{**line, "restock": restock} for line in lines],
        },
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def _ingresar_uno(client: TestClient, tenant: dict, *, unit_cost: str, unit_price: str) -> str:
    """Ingresa UN artículo con precio y devuelve su `item_id`."""
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "purchase",
            "supplier_id": str(tenant["supplier_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "name": f"Pieza {unit_cost}",
                    "cat1_id": str(tenant["cat1_id"]),
                    "cat2_id": str(tenant["cat2_id"]),
                    "cat3_id": str(tenant["cat3_id"]),
                    "unit_cost": unit_cost,
                    "photos": ["http://example.com/x.jpg"],
                    "sale_price": unit_price,
                }
            ],
        },
    ).json()
    return str(entry["items"][0]["id"])


def _vender_uno(
    client: TestClient,
    tenant: dict,
    item_id: str,
    *,
    unit_price: str,
    discount: str | None = None,
) -> dict:
    payload: dict = {
        "payment_method": "cash",
        "lines": [{"item_id": item_id, "quantity": "1", "unit_price": unit_price}],
    }
    if discount is not None:
        payload["discount_amount"] = discount
        payload["discount_reason"] = "Prueba de prorrateo"
    sale = client.post(
        "/api/v1/sales",
        headers=_headers(tenant["token"], idempotency_key=str(uuid4())),
        json=payload,
    )
    assert sale.status_code == 201, sale.text
    return dict(sale.json())


def _sell_one(client: TestClient, tenant: dict, *, unit_cost: str, unit_price: str) -> dict:
    item_id = _ingresar_uno(client, tenant, unit_cost=unit_cost, unit_price=unit_price)
    return _vender_uno(client, tenant, item_id, unit_price=unit_price)


def test_devolucion_total_saca_el_ingreso_y_su_costo_sin_tocar_el_inventario(
    client: TestClient, reports_tenant: dict
) -> None:
    """Devolución TOTAL el mismo día: el ingreso vuelve a cero, el costo
    también, y —lo importante— la valorización del inventario queda EXACTAMENTE
    donde estaba antes de vender.

    Ese último assert es el que prueba que el doble conteo se cerró por el
    lado del COSTO y no por el del activo. El artículo devuelto está otra vez
    en `available` y vuelve a valorizarse: eso es correcto, volvió a ser
    inventario de verdad. Lo que estaba mal era que su costo siguiera dentro
    de `cost_of_goods_sold` al mismo tiempo. Quien "arregle" también la
    valorización estaría restando dos veces.
    """
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "2000000.00"}
    )
    today = hoy_empresa().isoformat()

    item_id = _ingresar_uno(client, reports_tenant, unit_cost="300000.00", unit_price="500000.00")
    # Foto del activo CON el artículo adentro y todavía sin vender: es contra
    # este número que la valorización tiene que volver después de la devolución.
    valorizacion_inicial = client.get("/api/v1/reports/inventory-valuation", headers=headers).json()
    assert Decimal(valorizacion_inicial["cost_value"]) == Decimal("300000.00")

    sale = _vender_uno(client, reports_tenant, item_id, unit_price="500000.00")

    vendido = _profit(client, reports_tenant["token"], today, today)
    assert Decimal(vendido["gross_revenue"]) == Decimal("500000.00")
    assert Decimal(vendido["cost_of_goods_sold"]) == Decimal("300000.00")
    assert Decimal(vendido["sales_returns"]) == Decimal("0.00")

    _return_sale(
        client,
        reports_tenant["token"],
        sale["id"],
        [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
    )

    devuelto = _profit(client, reports_tenant["token"], today, today)

    # La venta SIGUE siendo una venta del período: no se borra ni se anula.
    assert devuelto["sale_count"] == 1
    assert Decimal(devuelto["gross_revenue"]) == Decimal("500000.00")
    # Y la devolución la contrapesa, con su propio número visible.
    assert devuelto["return_count"] == 1
    assert Decimal(devuelto["sales_returns"]) == Decimal("500000.00")
    assert Decimal(devuelto["net_revenue"]) == Decimal("0.00")
    # El costo sale del costo de ventas: la mercancía volvió.
    assert Decimal(devuelto["returns_cost"]) == Decimal("300000.00")
    assert Decimal(devuelto["cost_of_goods_sold"]) == Decimal("0.00")
    assert Decimal(devuelto["gross_profit"]) == Decimal("0.00")

    # El activo NO se cuenta dos veces: la valorización vuelve a lo que era
    # antes de vender, ni más ni menos.
    valorizacion_final = client.get("/api/v1/reports/inventory-valuation", headers=headers).json()
    assert Decimal(valorizacion_final["cost_value"]) == Decimal(valorizacion_inicial["cost_value"])


def test_devolucion_parcial_prorratea_el_descuento_de_la_cabecera(
    client: TestClient, reports_tenant: dict
) -> None:
    """El descuento vive en la CABECERA de la venta, así que una devolución
    parcial solo puede llevarse su parte proporcional.

    La venta: cadena de 900.000 (costo 100.000) + anillo de 100.000 (costo
    20.000) = 1.000.000 bruto, con 100.000 de descuento. Se devuelve SOLO el
    anillo.

    El prorrateo es por PARTICIPACIÓN EN EL BRUTO, no por unidades: el anillo
    es el 10% del bruto, así que se lleva 10.000 de descuento y el
    contra-ingreso es 100.000 − 10.000 = **90.000**. Prorrateado por unidades
    serían 50.000 (mitad de los artículos) y se restaría MÁS ingreso del que
    entró por ese anillo.
    """
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "2000000.00"}
    )
    today = hoy_empresa().isoformat()

    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "purchase",
            "supplier_id": str(reports_tenant["supplier_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "name": "Cadena cara",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "100000.00",
                    "photos": ["http://example.com/c.jpg"],
                    "sale_price": "900000.00",
                },
                {
                    "name": "Anillo barato",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit_cost": "20000.00",
                    "photos": ["http://example.com/d.jpg"],
                    "sale_price": "100000.00",
                },
            ],
        },
    ).json()
    items = {i["cost"]: i for i in entry["items"]}
    cadena, anillo = items["100000.00"], items["20000.00"]

    sale = client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "discount_amount": "100000.00",
            "discount_reason": "Cliente frecuente",
            "lines": [
                {"item_id": cadena["id"], "quantity": "1", "unit_price": "900000.00"},
                {"item_id": anillo["id"], "quantity": "1", "unit_price": "100000.00"},
            ],
        },
    )
    assert sale.status_code == 201, sale.text
    sale_body = sale.json()
    linea_anillo = next(line for line in sale_body["lines"] if line["item_id"] == anillo["id"])

    _return_sale(
        client,
        reports_tenant["token"],
        sale_body["id"],
        [{"sale_line_id": linea_anillo["id"], "quantity": "1"}],
    )

    body = _profit(client, reports_tenant["token"], today, today)

    assert Decimal(body["gross_revenue"]) == Decimal("1000000.00")
    assert Decimal(body["discounts"]) == Decimal("100000.00")
    # 100.000 de bruto devuelto − 10.000 de descuento prorrateado (10% del
    # bruto de la venta). NO 100.000 (sin prorratear) ni 50.000 (por unidades).
    assert Decimal(body["sales_returns"]) == Decimal("90000.00")
    # 1.000.000 − 100.000 − 90.000
    assert Decimal(body["net_revenue"]) == Decimal("810000.00")
    # 120.000 de costo − 20.000 del anillo devuelto
    assert Decimal(body["returns_cost"]) == Decimal("20000.00")
    assert Decimal(body["cost_of_goods_sold"]) == Decimal("100000.00")
    assert Decimal(body["gross_profit"]) == Decimal("710000.00")

    # La venta sigue ENTERA en el período: una devolución parcial no la saca.
    # (Si esto se hubiera resuelto cambiando `sale.status`, `sale_count` sería
    # 0 y los 900.000 de la cadena habrían desaparecido del resultado.)
    assert body["sale_count"] == 1
    assert Decimal(body["units_sold"]) == 2


async def test_devolucion_de_otro_mes_no_reescribe_el_mes_de_la_venta(
    client: TestClient, reports_tenant: dict
) -> None:
    """El punto de `return_date`: el contra-ingreso cae en el período de la
    DEVOLUCIÓN, no en el de la venta.

    La venta se antedata 45 días (mes anterior) y la devolución se registra
    hoy. El mes de la venta tiene que quedar EXACTAMENTE igual —es un mes ya
    cerrado, y un reporte que cambia hacia atrás es el defecto F21-15— y el
    mes de hoy es el que se lleva la devolución.
    """
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "2000000.00"}
    )
    hoy = hoy_empresa()
    entonces = hoy - timedelta(days=45)

    sale = _sell_one(client, reports_tenant, unit_cost="300000.00", unit_price="500000.00")

    # Antedatar la venta. `sale` no es inmutable (la anulación la actualiza),
    # y es la única forma de tener una venta de otro mes sin esperar un mes.
    # La devolución NO se puede mover: `sale_return` sí es inmutable
    # (`forbid_change`), que es justamente por qué su fecha es confiable.
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.sale set sold_at = :cuando where id = :sid"),
            {"cuando": mediodia_empresa(entonces), "sid": sale["id"]},
        )

    _return_sale(
        client,
        reports_tenant["token"],
        sale["id"],
        [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
    )

    # --- El mes de la VENTA: intacto -------------------------------------
    viejo = _profit(client, reports_tenant["token"], entonces.isoformat(), entonces.isoformat())
    assert viejo["sale_count"] == 1
    assert Decimal(viejo["gross_revenue"]) == Decimal("500000.00")
    assert Decimal(viejo["cost_of_goods_sold"]) == Decimal("300000.00")
    assert Decimal(viejo["gross_profit"]) == Decimal("200000.00")
    # La devolución de HOY no toca ese día.
    assert viejo["return_count"] == 0
    assert Decimal(viejo["sales_returns"]) == Decimal("0.00")

    # --- El mes de la DEVOLUCIÓN: se lleva el contra-ingreso --------------
    nuevo = _profit(client, reports_tenant["token"], hoy.isoformat(), hoy.isoformat())
    assert nuevo["sale_count"] == 0
    assert Decimal(nuevo["gross_revenue"]) == Decimal("0.00")
    assert nuevo["return_count"] == 1
    assert Decimal(nuevo["sales_returns"]) == Decimal("500000.00")
    assert Decimal(nuevo["net_revenue"]) == Decimal("-500000.00")
    # El costo del período queda NEGATIVO, y eso es correcto: la mercancía
    # entró al inventario este mes sin haberse vendido este mes.
    assert Decimal(nuevo["cost_of_goods_sold"]) == Decimal("-300000.00")
    assert Decimal(nuevo["gross_profit"]) == Decimal("-200000.00")


def test_estado_de_resultados_muestra_las_devoluciones_en_linea_propia(
    client: TestClient, reports_tenant: dict
) -> None:
    """«Devoluciones» tiene LÍNEA PROPIA, no se resta en silencio de «Ventas».

    Un número que baja sin explicación es lo que hace que nadie confíe en un
    reporte: si «Ventas» pasara de 500.000 a 0 sin decir por qué, el dueño
    creería que el sistema perdió la venta. Con la línea aparte se ve el hecho
    del negocio —hubo una venta Y hubo una devolución— y el total cuadra.

    `/reports/series` usa la MISMA definición y la expone con el mismo nombre
    (`sales_returns`), para no crear una tercera semántica de ingreso.
    """
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "2000000.00"}
    )
    today = hoy_empresa().isoformat()

    sale = _sell_one(client, reports_tenant, unit_cost="300000.00", unit_price="500000.00")
    _return_sale(
        client,
        reports_tenant["token"],
        sale["id"],
        [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
    )

    r = client.get(
        "/api/v1/reports/income-statement",
        headers=headers,
        params={"from_date": today, "to_date": today},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # «Ventas» se queda como estaba: la venta ocurrió.
    assert Decimal(body["sales_revenue"]) == Decimal("500000.00")
    # Y la devolución baja por su propia línea.
    assert Decimal(body["sales_returns"]) == Decimal("500000.00")
    # `sales_revenue − sales_returns + interest_revenue`
    assert Decimal(body["total_revenue"]) == Decimal(body["interest_revenue"])
    # El costo de ventas ya viene neto: cierra el doble conteo.
    assert Decimal(body["cost_of_goods_sold"]) == Decimal("0.00")

    # La serie mensual expone lo mismo con el mismo nombre.
    serie = client.get("/api/v1/reports/series", headers=headers, params={"months": 3}).json()
    mes_actual = serie["points"][-1]
    assert Decimal(mes_actual["sales_revenue"]) == Decimal("500000.00")
    assert Decimal(mes_actual["sales_returns"]) == Decimal("500000.00")


# --------------------------------------------------------------------------
# F6-02 (27/09/2026): las cantidades de los reportes son Decimal — se vende
# por gramos.
# --------------------------------------------------------------------------
def test_reportes_con_cantidades_fraccionarias(client: TestClient, reports_tenant: dict) -> None:
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "5000000.00"}
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
                    "name": "Oro por gramo",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit": "gram",
                    "quantity": "2.5",
                    "unit_cost": "200000.00",
                    "sale_price": "300000.00",
                    "photos": ["http://example.com/oro.jpg"],
                }
            ],
        },
    )
    assert entry.status_code == 201, entry.text
    item_id = entry.json()["items"][0]["id"]
    venta = client.post(
        "/api/v1/sales",
        headers=_headers(reports_tenant["token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [{"item_id": item_id, "quantity": "1.1", "unit_price": "300000.00"}],
        },
    )
    assert venta.status_code == 201, venta.text

    today = hoy_empresa().isoformat()
    utilidad = _profit(client, reports_tenant["token"], today, today)
    assert Decimal(utilidad["units_sold"]) == Decimal("1.1")
    assert utilidad["gross_revenue"] == "330000.00"

    valor = client.get("/api/v1/reports/inventory-valuation", headers=headers)
    assert valor.status_code == 200, valor.text
    assert Decimal(valor.json()["units"]) == Decimal("1.4")
    assert valor.json()["cost_value"] == "280000.00"


# --------------------------------------------------------------------------
# F6-04 / B-08 (27/09/2026): una devolución sin reingreso no descuenta su
# costo del costo de ventas.
# --------------------------------------------------------------------------
def test_devolucion_sin_reingreso_deja_su_costo_en_el_costo_de_ventas(
    client: TestClient, reports_tenant: dict
) -> None:
    headers = _headers(reports_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "2000000.00"}
    )
    today = hoy_empresa().isoformat()
    venta = _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="900000.00")
    _return_sale(
        client,
        reports_tenant["token"],
        venta["id"],
        [{"sale_line_id": venta["lines"][0]["id"], "quantity": "1"}],
        restock=False,
    )

    utilidad = _profit(client, reports_tenant["token"], today, today)
    assert utilidad["net_revenue"] == "0.00"
    assert Decimal(utilidad["returns_cost"]) == 0
    assert utilidad["cost_of_goods_sold"] == "100000.00"
    assert utilidad["gross_profit"] == "-100000.00"

    estado = client.get(
        "/api/v1/reports/income-statement",
        headers=headers,
        params={"from_date": today, "to_date": today},
    )
    assert estado.status_code == 200, estado.text
    assert estado.json()["cost_of_goods_sold"] == "100000.00"
    assert estado.json()["gross_profit"] == "-100000.00"


# --------------------------------------------------------------------------
# F7-09 / F7-15 (auditoría fase 7, 28/09/2026): el dinero sale SIEMPRE con
# dos decimales. El dashboard y `capital/position` respondían "2317208.20100"
# —`sum(cost * quantity)` sin redondear, con cantidades de tres decimales— y
# las sumas vacías salían "0" en vez de "0.00".
# --------------------------------------------------------------------------
def test_el_dinero_de_los_reportes_sale_con_dos_decimales(
    client: TestClient, reports_tenant: dict
) -> None:
    token = reports_tenant["token"]
    read = {"Authorization": f"Bearer {token}"}
    hoy = hoy_empresa().isoformat()

    # Empresa vacía: los ceros son "0.00", no "0".
    dash = client.get("/api/v1/reports/dashboard", headers=read).json()
    assert dash["contracts"]["capital_outstanding"] == "0.00"
    assert dash["sales"]["today_total"] == "0.00"
    assert dash["sales"]["month_total"] == "0.00"
    assert dash["inventory"]["available_value"] == "0.00"
    estado = client.get(
        "/api/v1/reports/income-statement",
        headers=read,
        params={"from_date": hoy, "to_date": hoy},
    ).json()
    for campo in ("sales_revenue", "interest_revenue", "total_revenue", "operating_profit"):
        assert estado[campo] == "0.00", (campo, estado[campo])
    empeno = client.get(
        "/api/v1/reports/pawn-performance",
        headers=read,
        params={"from_date": hoy, "to_date": hoy},
    ).json()
    assert empeno["interest_collected"] == "0.00"
    assert empeno["capital_disbursed"] == "0.00"

    # 0,333 g a 1.001 = 333,333: el lote vale 333,33.
    client.post(
        "/api/v1/cashbox/sessions/open", headers=_headers(token), json={"opening_balance": "0.00"}
    )
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "origin_type": "initial_stock",
            "lines": [
                {
                    "name": "Hilo por gramo",
                    "cat1_id": str(reports_tenant["cat1_id"]),
                    "cat2_id": str(reports_tenant["cat2_id"]),
                    "cat3_id": str(reports_tenant["cat3_id"]),
                    "unit": "gram",
                    "quantity": "0.333",
                    "unit_cost": "1001.00",
                    "sale_price": "2000.00",
                    "photos": ["http://example.com/hilo.jpg"],
                }
            ],
        },
    )
    assert entry.status_code == 201, entry.text

    dash = client.get("/api/v1/reports/dashboard", headers=read).json()
    assert dash["inventory"]["available_value"] == "333.33"
    posicion = client.get(
        "/api/v1/capital/position", headers=read, params={"from_date": hoy, "to_date": hoy}
    )
    assert posicion.status_code == 200, posicion.text
    assert posicion.json()["inventory_at_cost"] == "333.33"
    valor = client.get("/api/v1/reports/inventory-valuation", headers=read).json()
    assert valor["cost_value"] == "333.33", "las tres pantallas dicen lo mismo"


# --------------------------------------------------------------------------
# Fase 7 (auditoría 28/09/2026): lo que no pasaba por el resultado. El cuadre
# patrimonial dejaba un residuo de 32.999,991 que se explicaba entero por
# mermas, la comisión del convenio, el faltante de arqueo y el interés
# capitalizado en el remate. Cada uno, con su línea.
# --------------------------------------------------------------------------
def _estado(client: TestClient, token: str) -> dict:
    hoy = hoy_empresa().isoformat()
    r = client.get(
        "/api/v1/reports/income-statement",
        headers={"Authorization": f"Bearer {token}"},
        params={"from_date": hoy, "to_date": hoy},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _stock_inicial(
    client: TestClient, tenant: dict, *, name: str, unit_cost: str, quantity: str, unit: str
) -> str:
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(tenant["token"], idempotency_key=str(uuid4())),
        json={
            "origin_type": "initial_stock",
            "lines": [
                {
                    "name": name,
                    "cat1_id": str(tenant["cat1_id"]),
                    "cat2_id": str(tenant["cat2_id"]),
                    "cat3_id": str(tenant["cat3_id"]),
                    "unit": unit,
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "sale_price": unit_cost,
                    "photos": ["http://example.com/x.jpg"],
                }
            ],
        },
    )
    assert entry.status_code == 201, entry.text
    return str(entry.json()["items"][0]["id"])


def _egreso(client: TestClient, token: str, item_id: str, exit_type: str, qty: str) -> None:
    r = client.post(
        "/api/v1/inventory/exits",
        headers=_headers(token),
        json={
            "exit_type": exit_type,
            "reason": f"prueba {exit_type}",
            "lines": [{"item_id": item_id, "quantity": qty}],
        },
    )
    assert r.status_code == 201, r.text


def test_F7_01_las_mermas_y_bajas_restan_del_resultado_al_costo(
    client: TestClient, reports_tenant: dict
) -> None:
    """Reproducción de F7-01: merma de 0,5 g de oro (75.000 al costo) y un
    cargador dañado (20.000). La valorización bajaba 95.000 y el estado de
    resultados no lo mostraba en ninguna parte."""
    token = reports_tenant["token"]
    oro = _stock_inicial(
        client,
        reports_tenant,
        name="Oro granel",
        unit_cost="150000.00",
        quantity="10.5",
        unit="gram",
    )
    cargador = _stock_inicial(
        client, reports_tenant, name="Cargador", unit_cost="20000.00", quantity="10", unit="unit"
    )
    antes = _estado(client, token)
    assert antes["inventory_shrinkage"] == "0.00"

    _egreso(client, token, oro, "loss", "0.5")
    _egreso(client, token, cargador, "damage", "1")
    # Devolver al proveedor NO es una pérdida: sale del inventario contra una
    # deuda o un reembolso, no contra el resultado.
    _egreso(client, token, cargador, "supplier_return", "2")

    estado = _estado(client, token)
    assert estado["inventory_shrinkage"] == "95000.00"
    assert Decimal(estado["operating_profit"]) == Decimal(antes["operating_profit"]) - Decimal(
        "95000.00"
    )


async def test_F7_02_la_comision_del_convenio_es_gasto_del_dia_de_la_liquidacion(
    client: TestClient, reports_tenant: dict
) -> None:
    """Reproducción de F7-02 (B-10): liquidación de 1.300.000 con 1.235.000
    recibidos. Los 65.000 solo estaban en `audit_log.after.commission`."""
    token = reports_tenant["token"]
    client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json={})
    cuenta = client.post(
        "/api/v1/accounts",
        headers=_headers(token),
        json={"name": f"Sistecrédito {uuid4().hex[:6]}", "type": "settlement"},
    )
    assert cuenta.status_code == 201, cuenta.text
    sistecredito = cuenta.json()["id"]
    banco_resp = client.post(
        "/api/v1/accounts",
        headers=_headers(token),
        json={"name": f"Banco {uuid4().hex[:6]}", "type": "bank"},
    )
    assert banco_resp.status_code == 201, banco_resp.text
    banco = banco_resp.json()["id"]

    # Lo que Sistecrédito debe: 1.400.000 de ventas simuladas.
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.cash_movement "
                "(company_id, module, direction, concept, reference_type, reference_id, "
                " amount, payment_method, account_id) "
                "values (:cid, 'store', 'in', 'sale', 'sale', :ref, 1400000, 'other', :aid)"
            ),
            {"cid": str(reports_tenant["company_id"]), "ref": str(uuid4()), "aid": sistecredito},
        )
    antes = _estado(client, token)
    liquidacion = client.post(
        f"/api/v1/accounts/{sistecredito}/settle",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "to_account_id": banco,
            "amount_settled": "1300000.00",
            "amount_received": "1235000.00",
        },
    )
    assert liquidacion.status_code == 200, liquidacion.text
    estado = _estado(client, token)
    assert estado["settlement_commissions"] == "65000.00"
    assert Decimal(estado["operating_profit"]) == Decimal(antes["operating_profit"]) - Decimal(
        "65000.00"
    )

    # Una liquidación ANTERIOR a 00061 no tiene documento: se reconstruye de
    # su par de movimientos (mismo `created_at`, misma transacción).
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.cash_movement "
                "(company_id, module, direction, concept, reference_type, reference_id, "
                " amount, payment_method, account_id) values "
                "(:cid, 'store', 'out', 'settlement_out', 'settlement', :aid, 100000, "
                " 'other', :aid), "
                "(:cid, 'store', 'in', 'settlement_in', 'settlement', :aid, 90000, "
                " 'transfer', :banco)"
            ),
            {"cid": str(reports_tenant["company_id"]), "aid": sistecredito, "banco": banco},
        )
    assert _estado(client, token)["settlement_commissions"] == "75000.00"


def test_F7_03_los_descuadres_de_arqueo_entran_al_resultado(
    client: TestClient, reports_tenant: dict
) -> None:
    """Reproducción de F7-03: conteo de apertura +50.000 sobre un cajón de 0
    y faltante de cierre de 7.000. Se veían en `closings.difference` y nunca
    en la utilidad."""
    token = reports_tenant["token"]
    abierta = client.post(
        "/api/v1/cashbox/sessions/open",
        headers=_headers(token),
        json={"counted_cash": "50000.00", "difference_reason": "fondo encontrado"},
    )
    assert abierta.status_code == 201, abierta.text
    antes_de_cerrar = _estado(client, token)
    assert antes_de_cerrar["cash_differences"] == "50000.00"

    cerrada = client.post(
        f"/api/v1/cashbox/sessions/{abierta.json()['id']}/close",
        headers=_headers(token),
        json={"counted_cash": "43000.00", "difference_reason": "faltó un billete"},
    )
    assert cerrada.status_code == 200, cerrada.text
    estado = _estado(client, token)
    assert estado["cash_differences"] == "43000.00", "sobrante suma, faltante resta"
    assert Decimal(estado["operating_profit"]) == Decimal(
        antes_de_cerrar["operating_profit"]
    ) - Decimal("7000.00")


async def test_F7_04_el_interes_capitalizado_en_el_remate_no_es_costo_de_ventas(
    client: TestClient, reports_tenant: dict
) -> None:
    """Reproducción de F7-04: un contrato de 800.000 rematado con meses de
    interés adeudados queda en inventario a costo = capital + interés. Al
    venderlo, el costo de ventas cargaba el interés como si fuera costo, y la
    utilidad salía corta exactamente en ese interés — que nunca llegaba al
    resultado por ningún otro lado.

    Ahora la base de costo es el CAPITAL, el interés realizado se informa
    aparte y la devolución con reingreso lo deshace entero."""
    token = reports_tenant["token"]
    client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json={})
    contrato = client.post(
        "/api/v1/contracts",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "customer_id": str(reports_tenant["customer_id"]),
            "principal": "800000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [
                {
                    "category_id": str(reports_tenant["category_id"]),
                    "description": "Reloj",
                    "photos": ["http://example.com/reloj.jpg"],
                }
            ],
        },
    )
    assert contrato.status_code == 201, contrato.text
    cid = contrato.json()["id"]
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "update public.contract set interest_paid_until = interest_paid_until "
                "- make_interval(months => 8) where company_id = :cid and id = :id"
            ),
            {"cid": str(reports_tenant["company_id"]), "id": cid},
        )
    client.get(f"/api/v1/contracts/{cid}", headers=_headers(token))
    remate = client.post(
        f"/api/v1/contracts/{cid}/auction", headers=_headers(token, idempotency_key=str(uuid4()))
    )
    assert remate.status_code == 200, remate.text
    item_id = remate.json()["items"][0]["inventory_item_id"]
    async with AsyncSessionLocal() as s:
        costo, interes = (
            await s.execute(
                text("select cost, capitalized_interest from public.inventory_item where id = :i"),
                {"i": item_id},
            )
        ).one()
    assert interes > 0
    assert costo - interes == Decimal("800000.00"), "el resto del costo es el capital"

    publicado = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=_headers(token),
        json={"sale_price": "1300000.00"},
    )
    assert publicado.status_code == 200, publicado.text
    venta = _vender_uno(client, reports_tenant, item_id, unit_price="1300000.00")

    hoy = hoy_empresa().isoformat()
    utilidad = _profit(client, token, hoy, hoy)
    assert utilidad["cost_of_goods_sold"] == "800000.00"
    assert utilidad["auction_interest_realized"] == f"{interes:.2f}"
    assert utilidad["gross_profit"] == "500000.00", "1.300.000 vendidos sobre 800.000 prestados"
    estado = _estado(client, token)
    assert estado["cost_of_goods_sold"] == "800000.00"
    assert estado["auction_interest_realized"] == f"{interes:.2f}"

    # Devuelta con reingreso: el costo sale entero y el interés se deshace.
    _return_sale(
        client, token, venta["id"], [{"sale_line_id": venta["lines"][0]["id"], "quantity": "1"}]
    )
    utilidad = _profit(client, token, hoy, hoy)
    assert utilidad["cost_of_goods_sold"] == "0.00"
    assert utilidad["auction_interest_realized"] == "0.00"
    assert utilidad["gross_profit"] == "0.00"


def test_F7_08_vender_bajo_el_precio_publicado_figura_como_descuento(
    client: TestClient, reports_tenant: dict
) -> None:
    """Reproducción de F7-08: S3 se vendió a 400.000 contra 450.000
    publicados. `/profit.discounts` decía 55.000 (solo cabecera) y el
    descuento efectivo del día fue 105.000."""
    token = reports_tenant["token"]
    client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json={})
    anillo = _ingresar_uno(client, reports_tenant, unit_cost="300000.00", unit_price="450000.00")
    rebajado = client.post(
        "/api/v1/sales",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "discount_reason": "cliente frecuente",
            "lines": [{"item_id": anillo, "quantity": "1", "unit_price": "400000.00"}],
        },
    )
    assert rebajado.status_code == 201, rebajado.text
    celular = _ingresar_uno(client, reports_tenant, unit_cost="600000.00", unit_price="800000.00")
    _vender_uno(client, reports_tenant, celular, unit_price="800000.00", discount="55000.00")

    hoy = hoy_empresa().isoformat()
    utilidad = _profit(client, token, hoy, hoy)
    assert utilidad["discounts"] == "55000.00", "la cabecera no cambia de significado"
    assert utilidad["price_discounts"] == "50000.00"
    assert utilidad["total_discounts"] == "105000.00"
    # El neto no cambia: el subtotal ya venía rebajado.
    assert utilidad["net_revenue"] == "1145000.00"
    assert _estado(client, token)["sales_discounts"] == "105000.00"


def test_F7_05_07_ventas_netas_en_el_dashboard_y_flujo_de_caja_sin_anuladas(
    client: TestClient, reports_tenant: dict
) -> None:
    """F7-07: «Ventas de hoy» sumaba `sale.total` bruto de devoluciones
    (5.120.250 con 1.383.333,33 devueltos). F7-05: el KPI de Reportes, armado
    desde el desglose de caja, sumaba `sale/in` y nunca restaba la anulación
    (`sale/out`) ni la devolución en efectivo (`sale_return/out`).

    Venta A 500.000; venta B 200.000 anulada; venta C 300.000 devuelta en
    efectivo. Ventas netas del día: 500.000."""
    token = reports_tenant["token"]
    abierta = client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json={})
    _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="500000.00")
    b = _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="200000.00")
    anulada = client.post(
        f"/api/v1/sales/{b['id']}/void",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={"reason": "error de digitación"},
    )
    assert anulada.status_code == 200, anulada.text
    c = _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="300000.00")
    _return_sale(client, token, c["id"], [{"sale_line_id": c["lines"][0]["id"], "quantity": "1"}])

    ventas = client.get("/api/v1/reports/dashboard", headers=_headers(token)).json()["sales"]
    assert ventas["today_gross"] == "800000.00", "las anuladas nunca cuentan"
    assert ventas["today_returns"] == "300000.00"
    assert ventas["today_total"] == "500000.00"
    assert ventas["month_total"] == "500000.00"
    assert ventas["month_returns"] == "300000.00"
    estado = _estado(client, token)
    assert Decimal(estado["sales_revenue"]) - Decimal(estado["sales_returns"]) == Decimal(
        ventas["today_total"]
    ), "la misma cifra que el estado de resultados"

    esperado = client.get(
        f"/api/v1/cashbox/sessions/{abierta.json()['id']}/report", headers=_headers(token)
    ).json()["expected_cash"]
    cerrada = client.post(
        f"/api/v1/cashbox/sessions/{abierta.json()['id']}/close",
        headers=_headers(token),
        json={"counted_cash": esperado},
    )
    assert cerrada.status_code == 200, cerrada.text
    hoy = hoy_empresa().isoformat()
    flujo = client.get(
        "/api/v1/reports/closings-breakdown",
        headers=_headers(token),
        params={"from_date": hoy, "to_date": hoy},
    ).json()["sales_flow"]
    assert flujo["kind"] == "cash_flow"
    assert flujo["sales_in"] == "1000000.00"
    assert flujo["voided_out"] == "200000.00"
    assert flujo["returns_out"] == "300000.00"
    assert flujo["net_sales_flow"] == "500000.00"


async def test_F7_06_rendimiento_del_empeno_sobre_el_interes_neto(
    client: TestClient, reports_tenant: dict
) -> None:
    """F7-06: la tarjeta de empeño decía 250.000 (bruto) y el KPI 240.000
    (neto del descuento de 10.000). La respuesta ahora trae el neto —la misma
    cifra que `income-statement.interest_revenue`— y el rendimiento sobre él."""
    token = reports_tenant["token"]
    hoy = hoy_empresa().isoformat()
    empeno = _pawn(client, token, hoy, hoy)
    estado = _estado(client, token)
    assert empeno["interest_revenue"] == estado["interest_revenue"]
    assert Decimal(empeno["interest_revenue"]) == Decimal(empeno["interest_collected"]) - Decimal(
        empeno["interest_discounts"]
    )
    assert "net_yield_on_current_portfolio_pct" in empeno


def _compra(client: TestClient, tenant: dict, *, costo: str, pago: str | None) -> dict:
    body: dict = {
        "origin_type": "purchase",
        "supplier_id": str(tenant["supplier_id"]),
        "lines": [
            {
                "name": f"Compra {uuid4().hex[:6]}",
                "cat1_id": str(tenant["cat1_id"]),
                "cat2_id": str(tenant["cat2_id"]),
                "cat3_id": str(tenant["cat3_id"]),
                "unit_cost": costo,
                "photos": ["http://example.com/x.jpg"],
                "sale_price": costo,
            }
        ],
    }
    if pago is not None:
        body["payment_method"] = pago
    r = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(tenant["token"], idempotency_key=str(uuid4())),
        json=body,
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_F7_16_compras_causadas_y_pagos_de_compras_por_separado(
    client: TestClient, reports_tenant: dict
) -> None:
    """F7-16: la pantalla decía «Compras a proveedor» 4.600.666,67 (Σ
    `purchase/out` de caja: por fecha de PAGO, con el costo de proceso de una
    transformación) y el estado de resultados 4.575.666,67
    (`inventory_purchased`: por `entry_date`, a crédito incluido). Son dos
    preguntas distintas con el mismo nombre; ahora las dos cifras salen del
    backend, cada una con su rótulo."""
    token = reports_tenant["token"]
    client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json={})
    _compra(client, reports_tenant, costo="100000.00", pago="cash")
    credito = _compra(client, reports_tenant, costo="50000.00", pago=None)
    estado = _estado(client, token)
    assert estado["inventory_purchased"] == "150000.00", "causado: incluye el crédito"
    assert estado["inventory_purchases_paid"] == "100000.00", "pagado: solo lo que salió"
    assert estado["transformation_costs_paid"] == "0.00"

    pagada = client.post(
        f"/api/v1/inventory/entries/{credito['id']}/pay",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={"payment_method": "cash"},
    )
    assert pagada.status_code == 200, pagada.text
    assert _estado(client, token)["inventory_purchases_paid"] == "150000.00"


def test_F7_13_la_posicion_resta_pasivos_y_da_el_patrimonio_neto(
    client: TestClient, reports_tenant: dict
) -> None:
    """F7-13: `total_capital` sumaba activos y nunca restaba lo que se debe:
    en la reproducción, 200.000 a proveedores y 1.000.000 en una nota
    crédito por redimir."""
    token = reports_tenant["token"]
    client.post("/api/v1/cashbox/sessions/open", headers=_headers(token), json={})
    _compra(client, reports_tenant, costo="200000.00", pago=None)
    venta = _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="300000.00")
    devolucion = client.post(
        f"/api/v1/sales/{venta['id']}/returns",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "reason": "defect",
            "settlement_method": "credit_note",
            "customer_id": str(reports_tenant["customer_id"]),
            "lines": [{"sale_line_id": venta["lines"][0]["id"], "quantity": "1", "restock": True}],
        },
    )
    assert devolucion.status_code == 201, devolucion.text

    hoy = hoy_empresa().isoformat()
    p = client.get(
        "/api/v1/capital/position",
        headers=_headers(token),
        params={"from_date": hoy, "to_date": hoy},
    ).json()
    assert p["accounts_payable"] == "200000.00"
    assert p["credit_notes_outstanding"] == "300000.00"
    assert p["total_liabilities"] == "500000.00"
    assert Decimal(p["net_worth"]) == Decimal(p["total_capital"]) - Decimal("500000.00")


# ---- Dashboard del Admin (rediseño P2, 30/09/2026): mes en curso contra el
# MISMO TRAMO del mes anterior (01/10/2026; antes, el mes anterior completo),
# con las mismas fuentes que el estado de resultados.


def _estado_rango(client: TestClient, token: str, frm: date, to: date) -> dict:
    r = client.get(
        "/api/v1/reports/income-statement",
        headers={"Authorization": f"Bearer {token}"},
        params={"from_date": frm.isoformat(), "to_date": to.isoformat()},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def _contrato(client: TestClient, tenant: dict, principal: str) -> str:
    r = client.post(
        "/api/v1/contracts",
        headers=_headers(tenant["token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(tenant["customer_id"]),
            "principal": principal,
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [
                {
                    "category_id": str(tenant["category_id"]),
                    "description": "Cadena",
                    "photos": ["http://example.com/c.jpg"],
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _retroceder_ancla(tenant: dict, contract_id: str, meses: int) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "update public.contract set interest_paid_until = interest_paid_until "
                "- make_interval(months => :m) where company_id = :cid and id = :id"
            ),
            {"m": meses, "cid": str(tenant["company_id"]), "id": contract_id},
        )


@pytest.mark.asyncio
async def test_dashboard_compara_el_mes_con_el_mismo_tramo_del_anterior(
    client: TestClient, reports_tenant: dict
) -> None:
    token = reports_tenant["token"]
    cid = str(reports_tenant["company_id"])
    hoy = hoy_empresa()
    primero = hoy.replace(day=1)
    # El día 1 del mes anterior cae en el tramo comparable sea cual sea hoy.
    inicio_anterior, fin_tramo = previous_month_to_date_bounds(hoy)
    client.post(
        "/api/v1/cashbox/sessions/open",
        headers=_headers(token),
        json={"opening_balance": "5000000.00"},
    )

    # Este mes: un abono de 1 mes (50.000) con 10.000 de descuento → 40.000.
    pagado = _contrato(client, reports_tenant, "1000000.00")
    await _retroceder_ancla(reports_tenant, pagado, 1)
    abono = client.post(
        f"/api/v1/contracts/{pagado}/payments",
        headers=_headers(token, idempotency_key=str(uuid4())),
        json={
            "months_covered": 1,
            "payment_method": "cash",
            "discount_amount": "10000.00",
            "discount_reason": "Cliente frecuente",
        },
    )
    assert abono.status_code == 201, abono.text

    # Este mes: un remate de verdad.
    rematado = _contrato(client, reports_tenant, "300000.00")
    await _retroceder_ancla(reports_tenant, rematado, 8)
    client.get(f"/api/v1/contracts/{rematado}", headers=_headers(token))
    remate = client.post(
        f"/api/v1/contracts/{rematado}/auction",
        headers=_headers(token, idempotency_key=str(uuid4())),
    )
    assert remate.status_code == 200, remate.text

    # Mes anterior: un abono (30.000 − 5.000 de descuento), un remate y una
    # venta. `contract_payment` es inmutable, así que el abono viejo se
    # INSERTA con su fecha; el remate viejo es su documento, el ingreso de
    # inventario con origen `auction`; la venta se antedata.
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.contract_payment (company_id, contract_id, receipt_number, "
                "paid_at, months_covered, interest_amount, discount_amount, discount_reason, "
                "payment_method, total, new_capital_balance, new_interest_paid_until, "
                "idempotency_key) values (:cid, :ct, 900001, :cuando, 1, 30000, 5000, "
                "'Prueba', 'cash', 25000, 1000000, :ipu, :key)"
            ),
            {
                "cid": cid,
                "ct": pagado,
                "cuando": mediodia_empresa(inicio_anterior),
                "ipu": inicio_anterior,
                "key": str(uuid4()),
            },
        )
        await s.execute(
            text(
                "insert into public.inventory_entry (company_id, number, origin_type, "
                "contract_id, total_cost, created_at) "
                "values (:cid, 900001, 'auction', :ct, 1, :cuando)"
            ),
            {"cid": cid, "ct": pagado, "cuando": mediodia_empresa(inicio_anterior)},
        )
    venta_vieja = _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="450000.00")
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text("update public.sale set sold_at = :cuando where id = :sid"),
            {"cuando": mediodia_empresa(inicio_anterior), "sid": venta_vieja["id"]},
        )

    r = client.get("/api/v1/reports/dashboard", headers=_headers(token))
    assert r.status_code == 200, r.text
    body = r.json()
    contratos, ventas = body["contracts"], body["sales"]

    este_mes = _estado_rango(client, token, primero, hoy)
    mes_anterior = _estado_rango(client, token, inicio_anterior, fin_tramo)
    assert contratos["interest_collected_month"] == "40000.00"
    assert contratos["interest_collected_month"] == este_mes["interest_revenue"]
    assert contratos["interest_collected_prev_month"] == "25000.00"
    assert contratos["interest_collected_prev_month"] == mes_anterior["interest_revenue"]
    assert contratos["auctioned_this_month"] == 1
    assert ventas["month_total_prev"] == "450000.00"
    assert Decimal(ventas["month_total_prev"]) == Decimal(mes_anterior["sales_revenue"]) - Decimal(
        mes_anterior["sales_returns"]
    )
    assert ventas["month_total"] == "0.00"
    # Los campos de antes siguen ahí.
    assert contratos["auctioned_count"] == 1
    assert "ready_for_auction_count" in contratos and "today_total" in ventas


def _abono_viejo(tenant: dict, contract_id: str, recibo: int, dia: date, interes: str) -> dict:
    """Un abono de 1 mes con fecha `dia` (`contract_payment` es inmutable: se
    INSERTA con su fecha, como en el test de arriba)."""
    return {
        "cid": str(tenant["company_id"]),
        "ct": contract_id,
        "recibo": recibo,
        "cuando": mediodia_empresa(dia),
        "interes": Decimal(interes),
        "ipu": dia,
        "key": str(uuid4()),
    }


@pytest.mark.asyncio
async def test_dashboard_el_tramo_anterior_corta_en_el_mismo_dia(
    client: TestClient, reports_tenant: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Hoy» fijo (el día de la empresa se reemplaza solo para el dashboard):
    con hoy = 10/03, una venta y un abono del 05/02 cuentan y los del 25/02
    NO; con hoy = 31/03 el tramo llega al 28/02 y cuentan los dos; con hoy =
    01/03 el tramo es solo el 01/02 y no cuenta ninguno. Fechas de 2026 lejos
    de las que crea el test vía API (hoy real), que no caen en ningún tramo."""
    from app.modules.platform import integration as platform_integration

    token = reports_tenant["token"]
    client.post(
        "/api/v1/cashbox/sessions/open",
        headers=_headers(token),
        json={"opening_balance": "5000000.00"},
    )
    contrato = _contrato(client, reports_tenant, "1000000.00")
    dentro, fuera = date(2026, 2, 5), date(2026, 2, 25)
    async with AsyncSessionLocal() as s, s.begin():
        for params in (
            _abono_viejo(reports_tenant, contrato, 910001, dentro, "30000"),
            _abono_viejo(reports_tenant, contrato, 910002, fuera, "70000"),
        ):
            await s.execute(
                text(
                    "insert into public.contract_payment (company_id, contract_id, "
                    "receipt_number, paid_at, months_covered, interest_amount, discount_amount, "
                    "payment_method, total, new_capital_balance, new_interest_paid_until, "
                    "idempotency_key) values (:cid, :ct, :recibo, :cuando, 1, :interes, 0, "
                    "'cash', :interes, 1000000, :ipu, :key)"
                ),
                params,
            )
    for dia, precio in ((dentro, "450000.00"), (fuera, "300000.00")):
        venta = _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price=precio)
        async with AsyncSessionLocal() as s, s.begin():
            await s.execute(
                text("update public.sale set sold_at = :cuando where id = :sid"),
                {"cuando": mediodia_empresa(dia), "sid": venta["id"]},
            )

    def _dashboard_el(hoy: date) -> dict:
        async def _hoy_fijo(_db: object, *, company_id: object) -> date:
            return hoy

        with monkeypatch.context() as m:
            m.setattr(platform_integration, "get_company_today", _hoy_fijo)
            r = client.get("/api/v1/reports/dashboard", headers=_headers(token))
        assert r.status_code == 200, r.text
        assert r.json()["as_of"] == hoy.isoformat()
        return dict(r.json())

    casos = (
        (date(2026, 3, 10), date(2026, 2, 10), "30000.00", "450000.00"),
        (date(2026, 3, 31), date(2026, 2, 28), "100000.00", "750000.00"),
        (date(2026, 3, 1), date(2026, 2, 1), "0.00", "0.00"),
    )
    for hoy, fin_tramo, interes, ventas in casos:
        body = _dashboard_el(hoy)
        assert body["contracts"]["interest_collected_prev_month"] == interes, hoy
        assert body["sales"]["month_total_prev"] == ventas, hoy
        # La misma cifra que el estado de resultados para ese tramo.
        estado = _estado_rango(client, token, date(2026, 2, 1), fin_tramo)
        assert body["contracts"]["interest_collected_prev_month"] == estado["interest_revenue"]
        assert Decimal(body["sales"]["month_total_prev"]) == Decimal(
            estado["sales_revenue"]
        ) - Decimal(estado["sales_returns"])
        # Y el mes «en curso» (marzo de 2026) no tiene nada.
        assert body["sales"]["month_total"] == "0.00"


def test_la_franja_de_caja_cuadra_con_venta_compra_y_gasto_en_efectivo(
    client: TestClient, reports_tenant: dict
) -> None:
    """`GET /cashbox/sessions/current` (franja de caja) con operación real:
    compra en efectivo (sale del cajón), venta en efectivo (entra) y gasto en
    efectivo (sale). Vive acá porque este tenant ya puede comprar y vender.
    El esperado en vivo es el que el cierre exige contar."""
    token = reports_tenant["token"]
    client.post(
        "/api/v1/cashbox/sessions/open",
        headers=_headers(token),
        json={"opening_balance": "1000000.00"},
    )
    _sell_one(client, reports_tenant, unit_cost="100000.00", unit_price="450000.00")
    categoria = client.post(
        "/api/v1/cashbox/expense-categories", headers=_headers(token), json={"name": "Aseo"}
    ).json()
    gasto = client.post(
        "/api/v1/cashbox/expenses",
        headers=_headers(token),
        json={
            "category_id": categoria["id"],
            "description": "Escoba",
            "amount": "20000.00",
            "payment_method": "cash",
        },
    )
    assert gasto.status_code == 201, gasto.text

    actual = client.get("/api/v1/cashbox/sessions/current", headers=_headers(token)).json()
    # 1.000.000 − 100.000 (compra) + 450.000 (venta) − 20.000 (gasto)
    assert actual["expected_cash"] == "1330000.00"
    assert actual["opened_by_name"] == "Full User"
    acta = client.get(
        f"/api/v1/cashbox/sessions/{actual['id']}/report", headers=_headers(token)
    ).json()
    assert actual["expected_cash"] == acta["expected_cash"]
    cierre = client.post(
        f"/api/v1/cashbox/sessions/{actual['id']}/close",
        headers=_headers(token),
        json={"counted_cash": actual["expected_cash"]},
    )
    assert cierre.status_code == 200, cierre.text
    assert cierre.json()["difference"] == "0.00"
