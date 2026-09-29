"""Todo id que llega en el body se busca en la empresa del usuario antes de
escribir. Las llaves foráneas del esquema son simples (`references X(id)`) y
Postgres las valida sin RLS, así que la pertenencia a la empresa la garantiza
el servicio: un id de otra empresa responde 404 `NOT_FOUND`, igual que uno
que no existe, y no se escribe nada.

Un test por endpoint y por campo. Cada caso arma un body válido en todo lo
demás, para que el 404 venga del id y no de otra regla.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

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


async def _empresa(private_pem: str, nombre: str) -> dict[str, Any]:
    """Empresa lista para operar: rol con todos los permisos, caja abierta,
    cuentas de efectivo y banco, cliente, cadena de categorías, proveedor,
    categoría de gasto y un artículo disponible."""
    ids = {
        k: uuid4()
        for k in (
            "company",
            "role",
            "user",
            "register",
            "cash_account",
            "bank_account",
            "settlement_account",
            "customer",
            "cat1",
            "cat2",
            "cat3",
            "supplier",
            "expense_category",
            "product",
            "item",
        )
    }
    p = {k: str(v) for k, v in ids.items()}
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text("insert into public.company (id, name) values (:company, :name)"),
            {**p, "name": nombre},
        )
        await s.execute(
            text("insert into public.role (id, company_id, name) values (:role, :company, 'Todo')"),
            p,
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role, id from public.permission"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:user, :company, :role, 'Usuario', :email, 'active')"
            ),
            {**p, "email": f"u-{p['user']}@example.com"},
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:company, :plan, 'active', current_date + 30)"
            ),
            {**p, "plan": str(plan_id)},
        )
        await s.execute(
            text("insert into public.cash_register (id, company_id) values (:register, :company)"),
            p,
        )
        await s.execute(
            text(
                "insert into public.account (id, company_id, name, type, is_default, "
                "opening_balance) values "
                "(:cash_account, :company, 'Caja', 'cash', true, 0), "
                "(:bank_account, :company, 'Banco', 'bank', false, 10000000), "
                "(:settlement_account, :company, 'Convenio', 'settlement', false, 0)"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.cash_session "
                "(company_id, register_id, opened_by, opening_balance, status) "
                "values (:company, :register, :user, 0, 'open')"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.cash_movement "
                "(company_id, account_id, module, concept, direction, amount, payment_method) "
                "values (:company, :cash_account, 'general', 'adjustment', 'in', 5000000, 'cash')"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.customer (id, company_id, full_name, doc_type, doc_number, "
                "phone) values (:customer, :company, 'Cliente', 'cc', :doc, '3000000000')"
            ),
            {**p, "doc": str(ids["customer"].int)[:10]},
        )
        await s.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, applies_to, "
                "default_term_months, arrears_window_months, max_ltv_pct) values "
                "(:cat1, :company, null, 1, 'Joyería', 'J', 'both', 4, 4, 80)"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, applies_to) values "
                "(:cat2, :company, :cat1, 2, 'Oro', 'O', 'both')"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, applies_to) values "
                "(:cat3, :company, :cat2, 3, 'Cadena', 'C', 'both')"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.supplier (id, company_id, name, code_letter) "
                "values (:supplier, :company, 'Proveedor', 'V')"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.expense_category (id, company_id, name) "
                "values (:expense_category, :company, 'Servicios')"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.product "
                "(id, company_id, code, name, cat1_id, cat2_id, cat3_id, sale_price) "
                "values (:product, :company, 'JOC0001', 'Cadena', :cat1, :cat2, :cat3, 500000)"
            ),
            p,
        )
        await s.execute(
            text(
                "insert into public.inventory_item "
                "(id, company_id, product_id, lot_number, code, origin, cost, quantity, status) "
                "values (:item, :company, :product, 1, 'JOC0001-01P', 'other', 300000, 5, "
                "'available')"
            ),
            p,
        )
    token = make_token(private_pem, sub=p["user"], company_id=p["company"], role_id=p["role"])
    return {**ids, "token": token}


@pytest_asyncio.fixture
async def empresas(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> tuple[dict[str, Any], dict[str, Any]]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    propia = await _empresa(private_pem, "Propia (ids del body)")
    otra = await _empresa(private_pem, "Otra (ids del body)")
    return propia, otra


def _h(empresa: dict[str, Any], idem: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {empresa['token']}"}
    if idem:
        headers["Idempotency-Key"] = str(uuid4())
    return headers


def _assert_404(response: Any) -> None:
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "NOT_FOUND", response.text


def _s(value: UUID) -> str:
    return str(value)


# --------------------------------------------------------------------- ventas


def _venta(a: dict[str, Any], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "payment_method": "cash",
        "lines": [{"item_id": _s(a["item"]), "quantity": "1", "unit_price": "500000.00"}],
    }
    body.update(over)
    return body


def test_venta_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/sales",
        headers=_h(a),
        json=_venta(a, payment_method="transfer", account_id=_s(b["bank_account"])),
    )
    _assert_404(r)


def test_venta_con_articulo_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    body = _venta(a)
    body["lines"][0]["item_id"] = _s(b["item"])
    _assert_404(client.post("/api/v1/sales", headers=_h(a), json=body))


def _vender(client: TestClient, empresa: dict[str, Any], **over: Any) -> dict[str, Any]:
    r = client.post("/api/v1/sales", headers=_h(empresa), json=_venta(empresa, **over))
    assert r.status_code == 201, r.text
    return r.json()


def test_venta_con_nota_credito_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    venta_b = _vender(client, b, customer_id=_s(b["customer"]))
    devolucion = client.post(
        f"/api/v1/sales/{venta_b['id']}/returns",
        headers=_h(b),
        json={
            "reason": "defect",
            "settlement_method": "credit_note",
            "lines": [{"sale_line_id": venta_b["lines"][0]["id"], "quantity": "1"}],
        },
    )
    assert devolucion.status_code == 201, devolucion.text
    nota_b = devolucion.json()["credit_note_id"]
    assert nota_b is not None

    r = client.post(
        "/api/v1/sales",
        headers=_h(a),
        json=_venta(
            a, customer_id=_s(a["customer"]), credit_note_id=nota_b, credit_note_amount="1000"
        ),
    )
    _assert_404(r)


def test_devolucion_con_linea_de_venta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    venta_a = _vender(client, a)
    venta_b = _vender(client, b)
    r = client.post(
        f"/api/v1/sales/{venta_a['id']}/returns",
        headers=_h(a),
        json={
            "reason": "defect",
            "settlement_method": "cash",
            "lines": [{"sale_line_id": venta_b["lines"][0]["id"], "quantity": "1"}],
        },
    )
    _assert_404(r)


def test_devolucion_con_cliente_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    venta_a = _vender(client, a)
    r = client.post(
        f"/api/v1/sales/{venta_a['id']}/returns",
        headers=_h(a),
        json={
            "reason": "defect",
            "settlement_method": "credit_note",
            "customer_id": _s(b["customer"]),
            "lines": [{"sale_line_id": venta_a["lines"][0]["id"], "quantity": "1"}],
        },
    )
    _assert_404(r)


# ------------------------------------------------------------------ contratos


def _contrato(a: dict[str, Any], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "customer_id": _s(a["customer"]),
        "principal": "1000000",
        "interest_rate_pct": "5",
        "appraisal_value": "3000000",
        "payment_method": "cash",
        "items": [{"category_id": _s(a["cat3"]), "description": "Cadena de oro"}],
    }
    body.update(over)
    return body


def test_contrato_con_cliente_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/contracts", headers=_h(a), json=_contrato(a, customer_id=_s(b["customer"]))
    )
    _assert_404(r)


def test_contrato_con_categoria_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    body = _contrato(a)
    body["items"][0]["category_id"] = _s(b["cat3"])
    _assert_404(client.post("/api/v1/contracts", headers=_h(a), json=body))


def test_contrato_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/contracts",
        headers=_h(a),
        json=_contrato(a, payment_method="transfer", account_id=_s(b["bank_account"])),
    )
    _assert_404(r)


def _importado(a: dict[str, Any], **over: Any) -> dict[str, Any]:
    start = date.today() - timedelta(days=60)
    body: dict[str, Any] = {
        "legacy_code": f"L-{uuid4().hex[:8]}",
        "customer_id": _s(a["customer"]),
        "principal": "1000000",
        "capital_balance": "1000000",
        "interest_rate_pct": "5",
        "term_months": 4,
        "arrears_window_months": 4,
        "start_date": start.isoformat(),
        "interest_paid_until": start.isoformat(),
        "items": [{"category_id": _s(a["cat3"]), "description": "Cadena de oro"}],
    }
    body.update(over)
    return body


def test_importar_contrato_con_cliente_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/contracts/import",
        headers=_h(a),
        json=_importado(a, customer_id=_s(b["customer"])),
    )
    _assert_404(r)


def test_importar_contrato_con_categoria_de_otra_empresa(
    client: TestClient, empresas: tuple
) -> None:
    a, b = empresas
    body = _importado(a)
    body["items"][0]["category_id"] = _s(b["cat3"])
    _assert_404(client.post("/api/v1/contracts/import", headers=_h(a), json=body))


def _crear_contrato(client: TestClient, a: dict[str, Any]) -> dict[str, Any]:
    r = client.post("/api/v1/contracts", headers=_h(a), json=_contrato(a))
    assert r.status_code == 201, r.text
    return r.json()


def test_abono_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    contrato = _crear_contrato(client, a)
    r = client.post(
        f"/api/v1/contracts/{contrato['id']}/payments",
        headers=_h(a),
        json={
            "months_covered": 0,
            "capital_amount": "100000",
            "payment_method": "transfer",
            "account_id": _s(b["bank_account"]),
        },
    )
    _assert_404(r)


def test_ampliar_prestamo_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    contrato = _crear_contrato(client, a)
    r = client.post(
        f"/api/v1/contracts/{contrato['id']}/extend-loan",
        headers=_h(a),
        json={
            "amount": "100000",
            "payment_method": "transfer",
            "account_id": _s(b["bank_account"]),
        },
    )
    _assert_404(r)


# ----------------------------------------------------------------- inventario


def _ingreso(a: dict[str, Any], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "origin_type": "purchase",
        "supplier_id": _s(a["supplier"]),
        "payment_method": "cash",
        "lines": [
            {
                "name": "Anillo",
                "cat1_id": _s(a["cat1"]),
                "cat2_id": _s(a["cat2"]),
                "cat3_id": _s(a["cat3"]),
                "unit_cost": "100000",
                "quantity": "1",
            }
        ],
    }
    body.update(over)
    return body


@pytest.mark.parametrize("campo", ["cat1_id", "cat2_id", "cat3_id"])
def test_ingreso_con_categoria_de_otra_empresa(
    client: TestClient, empresas: tuple, campo: str
) -> None:
    a, b = empresas
    body = _ingreso(a)
    body["lines"][0][campo] = _s(b[campo.removesuffix("_id")])
    _assert_404(client.post("/api/v1/inventory/entries", headers=_h(a), json=body))


def test_ingreso_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/inventory/entries",
        headers=_h(a),
        json=_ingreso(a, payment_method="transfer", account_id=_s(b["bank_account"])),
    )
    _assert_404(r)


def test_pagar_ingreso_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    creado = client.post(
        "/api/v1/inventory/entries", headers=_h(a), json=_ingreso(a, payment_method=None)
    )
    assert creado.status_code == 201, creado.text
    r = client.post(
        f"/api/v1/inventory/entries/{creado.json()['id']}/pay",
        headers=_h(a),
        json={"payment_method": "transfer", "account_id": _s(b["bank_account"])},
    )
    _assert_404(r)


def test_egreso_con_articulo_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/inventory/exits",
        headers=_h(a),
        json={
            "exit_type": "damage",
            "reason": "Se rompió",
            "lines": [{"item_id": _s(b["item"]), "quantity": "1"}],
        },
    )
    _assert_404(r)


def _transformacion(a: dict[str, Any]) -> dict[str, Any]:
    return {
        "reason": "Fundición",
        "inputs": [{"item_id": _s(a["item"]), "quantity": "1"}],
        "outputs": [
            {
                "name": "Lingote",
                "cat1_id": _s(a["cat1"]),
                "cat2_id": _s(a["cat2"]),
                "cat3_id": _s(a["cat3"]),
                "quantity": "1",
            }
        ],
    }


def test_transformacion_con_articulo_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    body = _transformacion(a)
    body["inputs"][0]["item_id"] = _s(b["item"])
    _assert_404(client.post("/api/v1/inventory/transformations", headers=_h(a), json=body))


@pytest.mark.parametrize("campo", ["cat1_id", "cat2_id", "cat3_id"])
def test_transformacion_con_categoria_de_otra_empresa(
    client: TestClient, empresas: tuple, campo: str
) -> None:
    a, b = empresas
    body = _transformacion(a)
    body["outputs"][0][campo] = _s(b[campo.removesuffix("_id")])
    _assert_404(client.post("/api/v1/inventory/transformations", headers=_h(a), json=body))


def test_transformacion_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    body = _transformacion(a)
    body.update(extra_cost="10000", payment_method="transfer", account_id=_s(b["bank_account"]))
    _assert_404(client.post("/api/v1/inventory/transformations", headers=_h(a), json=body))


# ------------------------------------------------------- caja, capital, cuentas


def _gasto(a: dict[str, Any], **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "category_id": _s(a["expense_category"]),
        "description": "Recibo de luz",
        "amount": "10000",
        "payment_method": "cash",
    }
    body.update(over)
    return body


def test_gasto_con_categoria_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/cashbox/expenses",
        headers=_h(a),
        json=_gasto(a, category_id=_s(b["expense_category"])),
    )
    _assert_404(r)


def test_gasto_con_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/cashbox/expenses",
        headers=_h(a),
        json=_gasto(a, payment_method="transfer", account_id=_s(b["bank_account"])),
    )
    _assert_404(r)


@pytest.mark.parametrize(
    ("ruta", "extra"),
    [("contributions", {}), ("withdrawals", {"notes": "Retiro de prueba"})],
)
def test_capital_con_cuenta_de_otra_empresa(
    client: TestClient, empresas: tuple, ruta: str, extra: dict[str, str]
) -> None:
    a, b = empresas
    r = client.post(
        f"/api/v1/capital/{ruta}",
        headers=_h(a),
        json={"account_id": _s(b["bank_account"]), "amount": "1000", **extra},
    )
    _assert_404(r)


@pytest.mark.parametrize("lado", ["from_account_id", "to_account_id"])
def test_traslado_con_cuenta_de_otra_empresa(
    client: TestClient, empresas: tuple, lado: str
) -> None:
    a, b = empresas
    body = {
        "from_account_id": _s(a["bank_account"]),
        "to_account_id": _s(a["cash_account"]),
        "amount": "1000",
    }
    body[lado] = _s(b["bank_account"])
    _assert_404(client.post("/api/v1/accounts/transfers", headers=_h(a), json=body))


def test_liquidacion_hacia_cuenta_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        f"/api/v1/accounts/{a['settlement_account']}/settle",
        headers=_h(a),
        json={
            "to_account_id": _s(b["bank_account"]),
            "amount_received": "900",
            "amount_settled": "1000",
        },
    )
    _assert_404(r)


# ------------------------------------------------------- catálogos e identidad


def test_categoria_con_padre_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/catalogs/categories",
        headers=_h(a, idem=False),
        json={"parent_id": _s(b["cat1"]), "name": "Plata", "code_letter": "P"},
    )
    _assert_404(r)


def test_invitar_con_rol_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/identity/invitations",
        headers=_h(a, idem=False),
        json={"email": "x@example.com", "full_name": "X", "role_id": _s(b["role"])},
    )
    _assert_404(r)


async def test_cambiar_rol_a_uno_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    otro_usuario = uuid4()
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :c, :r, 'Otro', :e, 'active')"
            ),
            {
                "id": str(otro_usuario),
                "c": str(a["company"]),
                "r": str(a["role"]),
                "e": f"o-{otro_usuario}@example.com",
            },
        )
    r = client.patch(
        f"/api/v1/identity/users/{otro_usuario}/role",
        headers=_h(a, idem=False),
        json={"role_id": _s(b["role"])},
    )
    _assert_404(r)


def test_clonar_rol_de_otra_empresa(client: TestClient, empresas: tuple) -> None:
    a, b = empresas
    r = client.post(
        "/api/v1/identity/roles",
        headers=_h(a, idem=False),
        json={"name": f"Clon {uuid4().hex[:6]}", "clone_from_role_id": _s(b["role"])},
    )
    _assert_404(r)


def test_la_empresa_de_referencia_opera_normalmente(client: TestClient, empresas: tuple) -> None:
    """Control: los mismos bodies con ids propios sí pasan."""
    a, _ = empresas
    assert client.post("/api/v1/sales", headers=_h(a), json=_venta(a)).status_code == 201
    assert client.post("/api/v1/contracts", headers=_h(a), json=_contrato(a)).status_code == 201
    assert (
        client.post("/api/v1/inventory/entries", headers=_h(a), json=_ingreso(a)).status_code == 201
    )
    assert client.post("/api/v1/cashbox/expenses", headers=_h(a), json=_gasto(a)).status_code in (
        200,
        201,
    )
