"""Validación de entrada: un valor inválido responde 422/409 con envelope y
`code`, nunca un 500 en texto plano (auditoría 27/09/2026: F3-04, F3-05,
F3-06, F4-12, F5-04, F5-05).

Dos capas, y cada test dice cuál ejerce:
- Pydantic (`PositiveMoney`, `Quantity`, `Reason`, `no_null`, rangos): el
  valor no llega a la base.
- El handler de `IntegrityError` (`app/core/errors.py`): lo que solo la base
  puede ver, como un nombre repetido.
"""

from collections.abc import AsyncGenerator
from uuid import uuid4

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


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


@pytest_asyncio.fixture
async def todo(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa con un rol que tiene TODOS los permisos: aquí se prueba la
    forma de los datos, no quién puede hacer qué."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    company_id, role_id, user_id = uuid4(), uuid4(), uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa validacion')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Todo')"),
            {"id": str(role_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :rid, id from public.permission"
            ),
            {"rid": str(role_id)},
        )
        await session.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :rid, 'Todo', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "rid": str(role_id),
                "email": f"todo-{user_id}@example.com",
            },
        )
        plan_id = (await session.execute(text("select id from public.plan limit 1"))).scalar_one()
        await session.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :pid, 'active', current_date + 30)"
            ),
            {"cid": str(company_id), "pid": str(plan_id)},
        )
    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )
    yield {"company_id": company_id, "token": token}

    for sql in (
        "delete from public.account where company_id = :cid",
        "delete from public.app_user where company_id = :cid",
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)",
        "delete from public.role where company_id = :cid",
        "delete from public.subscription where company_id = :cid",
        "delete from public.company where id = :cid",
    ):
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass


def _es_validacion(r, campo: str | None = None) -> None:  # type: ignore[no-untyped-def]
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "VALIDATION_ERROR"
    if campo is not None:
        assert any(campo in e["loc"] for e in r.json()["details"]["errors"]), r.text


# ------------------------------------------------------------------ dinero ----
@pytest.mark.parametrize("monto", ["0", "0.001", "10.555", "-1"])
def test_montos_que_mueven_plata_exigen_positivo_con_centavos(
    client: TestClient, todo: dict, monto: str
) -> None:
    """F5-04 / F4-12: 0 o más de dos decimales es 422 —ni un 500 del CHECK
    ni un redondeo callado de 10,555 a 10,56."""
    cuenta = str(uuid4())
    casos = [
        (
            "/api/v1/cashbox/expenses",
            {
                "category_id": cuenta,
                "description": "Papelería",
                "amount": monto,
                "payment_method": "cash",
            },
        ),
        ("/api/v1/capital/contributions", {"account_id": cuenta, "amount": monto}),
        (
            "/api/v1/capital/withdrawals",
            {"account_id": cuenta, "amount": monto, "notes": "retiro"},
        ),
        (
            "/api/v1/accounts/transfers",
            {"from_account_id": cuenta, "to_account_id": str(uuid4()), "amount": monto},
        ),
        (
            f"/api/v1/accounts/{cuenta}/settle",
            {"to_account_id": str(uuid4()), "amount_received": monto, "amount_settled": monto},
        ),
        (
            "/api/v1/contracts",
            {
                "customer_id": str(uuid4()),
                "principal": monto,
                "interest_rate_pct": "5",
                "payment_method": "cash",
                "items": [{"category_id": str(uuid4()), "description": "Cadena"}],
            },
        ),
        (
            f"/api/v1/contracts/{uuid4()}/extend-loan",
            {"amount": monto, "payment_method": "cash"},
        ),
    ]
    for url, cuerpo in casos:
        _es_validacion(client.post(url, headers=_h(todo["token"]), json=cuerpo))


def test_cantidad_con_mas_de_tres_decimales_es_422(client: TestClient, todo: dict) -> None:
    r = client.post(
        "/api/v1/sales",
        headers=_h(todo["token"]),
        json={
            "payment_method": "cash",
            "lines": [{"item_id": str(uuid4()), "quantity": "1.0001", "unit_price": "10.00"}],
        },
    )
    _es_validacion(r, "quantity")


# ----------------------------------------------------------------- motivos ----
@pytest.mark.parametrize("motivo", ["", "   "])
def test_un_motivo_vacio_o_de_espacios_es_422(client: TestClient, todo: dict, motivo: str) -> None:
    """F5-05: reabrir la caja, anular una venta, egresar mercancía y dar un
    descuento exigen un motivo con contenido."""
    casos = [
        (f"/api/v1/cashbox/sessions/{uuid4()}/reopen", {"reason": motivo}, "reason"),
        (f"/api/v1/sales/{uuid4()}/void", {"reason": motivo}, "reason"),
        (
            "/api/v1/inventory/exits",
            {
                "exit_type": "loss",
                "reason": motivo,
                "lines": [{"item_id": str(uuid4()), "quantity": "1"}],
            },
            "reason",
        ),
        (
            "/api/v1/sales",
            {
                "payment_method": "cash",
                "lines": [{"item_id": str(uuid4()), "quantity": "1", "unit_price": "10.00"}],
                "discount_amount": "1.00",
                "discount_reason": motivo,
            },
            "discount_reason",
        ),
        (
            f"/api/v1/contracts/{uuid4()}/payments",
            {
                "months_covered": 1,
                "payment_method": "cash",
                "discount_amount": "1.00",
                "discount_reason": motivo,
            },
            "discount_reason",
        ),
    ]
    for url, cuerpo, campo in casos:
        _es_validacion(client.post(url, headers=_h(todo["token"]), json=cuerpo), campo)


# ------------------------------------------------------ null en NOT NULL ----
def test_null_explicito_en_un_campo_obligatorio_es_422(client: TestClient, todo: dict) -> None:
    """F3-04: en un PATCH omitir el campo lo conserva; mandarlo `null` en
    una columna NOT NULL es 422 con el campo en `loc`."""
    token = todo["token"]
    casos = [
        ("/api/v1/me", {"full_name": None}, "full_name"),
        ("/api/v1/company/settings", {"name": None}, "name"),
        (f"/api/v1/customers/{uuid4()}", {"full_name": None}, "full_name"),
        (f"/api/v1/customers/{uuid4()}", {"phone": None}, "phone"),
        (f"/api/v1/catalogs/categories/{uuid4()}", {"name": None}, "name"),
    ]
    for url, cuerpo, campo in casos:
        _es_validacion(client.patch(url, headers=_h(token), json=cuerpo), campo)

    # Lo que SÍ admite null sigue admitiéndolo: borrar la foto del perfil.
    assert (
        client.patch("/api/v1/me", headers=_h(token), json={"photo_url": None}).status_code == 200
    )


# -------------------------------------------------------------- categoría ----
@pytest.mark.parametrize(
    "cuerpo",
    [
        {"max_ltv_pct": "1000"},
        {"max_ltv_pct": "-5"},
        {"max_ltv_pct": "0"},
        {"default_term_months": 0},
        {"default_term_months": -1},
        {"arrears_window_months": 0},
    ],
)
def test_parametros_de_categoria_fuera_de_rango_son_422(
    client: TestClient, todo: dict, cuerpo: dict
) -> None:
    """F3-06: LTV en (0, 100] y plazos ≥ 1. `null` sigue siendo "hereda"."""
    campo = next(iter(cuerpo))
    r = client.patch(
        f"/api/v1/catalogs/categories/{uuid4()}", headers=_h(todo["token"]), json=cuerpo
    )
    _es_validacion(r, campo)


# ---------------------------------------------------- nombres repetidos ----
def test_nombre_de_rol_repetido_es_409(client: TestClient, todo: dict) -> None:
    """F3-05: el UNIQUE(company_id, name) de `role` responde 409
    `ROLE_NAME_TAKEN`, al crear y al renombrar."""
    token = todo["token"]
    primero = client.post("/api/v1/identity/roles", headers=_h(token), json={"name": "Cajeros"})
    assert primero.status_code == 201, primero.text
    otro = client.post("/api/v1/identity/roles", headers=_h(token), json={"name": "Vitrina"})
    assert otro.status_code == 201, otro.text

    repetido = client.post("/api/v1/identity/roles", headers=_h(token), json={"name": "Cajeros"})
    assert repetido.status_code == 409, repetido.text
    assert repetido.json()["code"] == "ROLE_NAME_TAKEN"

    renombrado = client.patch(
        f"/api/v1/identity/roles/{otro.json()['id']}", headers=_h(token), json={"name": "Cajeros"}
    )
    assert renombrado.status_code == 409, renombrado.text
    assert renombrado.json()["code"] == "ROLE_NAME_TAKEN"


def test_nombre_de_cuenta_repetido_es_409(client: TestClient, todo: dict) -> None:
    """F5-04: el UNIQUE(company_id, name) de `account` responde 409
    `ACCOUNT_NAME_TAKEN`."""
    token = todo["token"]
    cuerpo = {"name": "Bancolombia", "type": "bank"}
    primero = client.post("/api/v1/accounts", headers=_h(token), json=cuerpo)
    assert primero.status_code == 201, primero.text
    repetido = client.post("/api/v1/accounts", headers=_h(token), json=cuerpo)
    assert repetido.status_code == 409, repetido.text
    assert repetido.json()["code"] == "ACCOUNT_NAME_TAKEN"
    assert repetido.json()["details"]["constraint"] == "account_company_id_name_key"


# ------------------------------------------- el handler, con errores reales ----
def _app_que_viola(sql_setup: str, sql_viola: str) -> TestClient:
    """Una app mínima con los handlers del proyecto y una ruta que provoca
    en Postgres la violación pedida. La excepción es la de asyncpg de verdad,
    no una armada a mano: lo que se prueba es cómo el handler la lee."""
    from fastapi import FastAPI

    from app.core.errors import register_exception_handlers

    mini = FastAPI()
    register_exception_handlers(mini)

    @mini.post("/viola")
    async def viola() -> None:
        async with AsyncSessionLocal() as session, session.begin():
            # asyncpg no admite varias sentencias en una: se separan acá.
            for sentencia in sql_setup.split(";"):
                await session.execute(text(sentencia))
            await session.execute(text(sql_viola))

    return TestClient(mini, raise_server_exceptions=False)


def test_el_handler_traduce_check_not_null_unique_y_fuera_de_rango() -> None:
    check = _app_que_viola(
        "create temp table t_chk (monto numeric check (monto > 0)) on commit drop",
        "insert into t_chk values (0)",
    ).post("/viola")
    assert check.status_code == 422, check.text
    assert check.json()["code"] == "VALIDATION_ERROR"
    assert check.json()["details"]["errors"][0]["ctx"]["constraint"] == "t_chk_monto_check"

    nulo = _app_que_viola(
        "create temp table t_nn (nombre text not null) on commit drop",
        "insert into t_nn values (null)",
    ).post("/viola")
    assert nulo.status_code == 422, nulo.text
    assert nulo.json()["details"]["errors"][0]["loc"] == ["body", "nombre"]

    nombrado = _app_que_viola(
        "create temp table t_uq (n text, constraint role_company_id_name_key unique (n)) "
        "on commit drop; insert into t_uq values ('Admin')",
        "insert into t_uq values ('Admin')",
    ).post("/viola")
    assert nombrado.status_code == 409, nombrado.text
    assert nombrado.json()["code"] == "ROLE_NAME_TAKEN"

    generico = _app_que_viola(
        "create temp table t_uq2 (n text unique) on commit drop; insert into t_uq2 values ('x')",
        "insert into t_uq2 values ('x')",
    ).post("/viola")
    assert generico.status_code == 409, generico.text
    assert generico.json()["code"] == "CONFLICT"

    rango = _app_que_viola("select 1", "select 1000::numeric(5,2)").post("/viola")
    assert rango.status_code == 422, rango.text
    assert rango.json()["code"] == "VALIDATION_ERROR"
