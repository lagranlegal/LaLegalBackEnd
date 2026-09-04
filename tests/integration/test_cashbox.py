"""Integración de cashbox (paso 6): apertura/cierre con desglose, sin
tolerancia de diferencias, reapertura auditada, gastos. Requiere Postgres
real (se salta si no hay)."""

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
async def cashbox_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()
    register_id = uuid4()
    codes = ("cashbox.view", "cashbox.open_close", "cashbox.reopen", "cashbox.expense")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa cashbox-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Cajero')"),
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
                "values (:id, :cid, :role_id, 'Cajero Test', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"cajero-{user_id}@example.com",
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
        await session.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    yield {"company_id": company_id, "register_id": register_id, "user_id": user_id, "token": token}

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
    await _try_delete("delete from public.cash_session where company_id = :cid")
    await _try_delete("delete from public.cash_register where company_id = :cid")
    await _try_delete("delete from public.company where id = :cid")


def test_open_session_success(client: TestClient, cashbox_tenant: dict) -> None:
    response = client.post(
        "/api/v1/cashbox/sessions/open",
        headers=_headers(cashbox_tenant["token"]),
        json={"opening_balance": "100000.00"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "open"
    assert body["opening_balance"] == "100000.00"


def test_open_session_twice_is_conflict(client: TestClient, cashbox_tenant: dict) -> None:
    headers = _headers(cashbox_tenant["token"])
    first = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    )
    assert second.status_code == 409
    assert second.json()["code"] == "CASH_SESSION_ALREADY_OPEN"


def test_get_current_session_404_when_none_open(client: TestClient, cashbox_tenant: dict) -> None:
    """Sin caja abierta: 404 **con el código de dominio**, no con `NOT_FOUND`.

    El código es la parte que importa y es la que faltaba acá. El front
    traduce `CASH_SESSION_NOT_OPEN` a "Caja cerrada — no se pueden registrar
    operaciones de dinero" con su botón para abrirla; cualquier otro código
    cae en "No se pudo consultar el estado de la caja", que se lee como una
    falla del sistema.

    Este test solo miraba el status, así que el endpoint pudo devolver
    `NOT_FOUND` durante meses sin que nadie lo notara: una empresa estuvo
    once días sin poder crear un contrato porque nunca supo que lo que
    faltaba era abrir la caja.
    """
    response = client.get(
        "/api/v1/cashbox/sessions/current", headers=_headers(cashbox_tenant["token"])
    )
    assert response.status_code == 404
    assert response.json()["code"] == "CASH_SESSION_NOT_OPEN"


def test_close_session_with_no_movements_matches_opening_balance(
    client: TestClient, cashbox_tenant: dict
) -> None:
    headers = _headers(cashbox_tenant["token"])
    opened = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "50000.00"}
    ).json()

    response = client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "50000.00"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "closed"
    assert body["expected_cash"] == "50000.00"
    assert body["difference"] == "0.00"


def test_close_session_with_difference_requires_reason(
    client: TestClient, cashbox_tenant: dict
) -> None:
    headers = _headers(cashbox_tenant["token"])
    opened = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "50000.00"}
    ).json()

    without_reason = client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "49000.00"},
    )
    assert without_reason.status_code == 400

    with_reason = client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "49000.00", "difference_reason": "faltante sin explicar aún"},
    )
    assert with_reason.status_code == 200, with_reason.text
    assert with_reason.json()["difference"] == "-1000.00"


async def test_cannot_open_same_day_after_close(client: TestClient, cashbox_tenant: dict) -> None:
    headers = _headers(cashbox_tenant["token"])
    opened = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    ).json()
    client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "0.00"},
    )

    reopen_attempt = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    )
    assert reopen_attempt.status_code == 409
    assert reopen_attempt.json()["code"] == "CASH_SESSION_ALREADY_CLOSED_TODAY"


async def test_reopen_session_is_audited(client: TestClient, cashbox_tenant: dict) -> None:
    headers = _headers(cashbox_tenant["token"])
    opened = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    ).json()
    client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "0.00"},
    )

    response = client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/reopen",
        headers=headers,
        json={"reason": "faltó registrar un gasto"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "open"

    async with AsyncSessionLocal() as session, session.begin():
        audit = (
            await session.execute(
                text(
                    "select action from public.audit_log "
                    "where company_id = :cid and action = 'reopen_session'"
                ),
                {"cid": str(cashbox_tenant["company_id"])},
            )
        ).first()
    assert audit is not None


def test_expense_without_open_session_is_409(client: TestClient, cashbox_tenant: dict) -> None:
    headers = _headers(cashbox_tenant["token"])
    category = client.post(
        "/api/v1/cashbox/expense-categories", headers=headers, json={"name": "Servicios"}
    ).json()

    response = client.post(
        "/api/v1/cashbox/expenses",
        headers=headers,
        json={
            "category_id": category["id"],
            "description": "Internet",
            "amount": "50000.00",
            "payment_method": "cash",
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CASH_SESSION_NOT_OPEN"


def test_expense_reduces_expected_cash_and_shows_in_report(
    client: TestClient, cashbox_tenant: dict
) -> None:
    headers = _headers(cashbox_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "100000.00"}
    )
    current = client.get("/api/v1/cashbox/sessions/current", headers=headers).json()
    category = client.post(
        "/api/v1/cashbox/expense-categories", headers=headers, json={"name": "Aseo"}
    ).json()

    expense = client.post(
        "/api/v1/cashbox/expenses",
        headers=headers,
        json={
            "category_id": category["id"],
            "description": "Productos de aseo",
            "amount": "20000.00",
            "payment_method": "cash",
        },
    )
    assert expense.status_code == 201, expense.text

    report = client.get(f"/api/v1/cashbox/sessions/{current['id']}/report", headers=headers).json()
    assert report["expected_cash"] == "80000.00"
    expense_lines = [line for line in report["lines"] if line["concept"] == "expense"]
    assert len(expense_lines) == 1
    assert expense_lines[0]["total"] == "20000.00"
    assert expense_lines[0]["direction"] == "out"


def test_expense_paid_from_a_bank_account_does_not_touch_expected_cash(
    client: TestClient, cashbox_tenant: dict
) -> None:
    """Un gasto pagado por transferencia no sale del cajón.

    Antes de 00027 el esperado se calculaba por `payment_method`, así que
    esta plata se restaba del cajón y el arqueo salía descuadrado buscando
    unos billetes que nunca estuvieron ahí. La autoridad es el TIPO DE
    CUENTA: la transferencia salió del banco, el cajón no se enteró.
    """
    headers = _headers(cashbox_tenant["token"])
    client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "100000.00"}
    )
    current = client.get("/api/v1/cashbox/sessions/current", headers=headers).json()
    category = client.post(
        "/api/v1/cashbox/expense-categories", headers=headers, json={"name": "Arriendo"}
    ).json()

    expense = client.post(
        "/api/v1/cashbox/expenses",
        headers=headers,
        json={
            "category_id": category["id"],
            "description": "Arriendo del local",
            "amount": "30000.00",
            "payment_method": "transfer",
        },
    )
    assert expense.status_code == 201, expense.text

    report = client.get(f"/api/v1/cashbox/sessions/{current['id']}/report", headers=headers).json()
    assert report["expected_cash"] == "100000.00"

    # Sigue apareciendo en el acta —el gasto existe y hay que rendirlo—,
    # pero identificado contra la cuenta de la que salió.
    lines = [line for line in report["lines"] if line["concept"] == "expense"]
    assert len(lines) == 1
    assert lines[0]["account_type"] == "bank"
    assert lines[0]["account_name"] == "Transferencias"
    assert lines[0]["total"] == "30000.00"


def test_duplicate_expense_category_name_is_conflict(
    client: TestClient, cashbox_tenant: dict
) -> None:
    headers = _headers(cashbox_tenant["token"])
    first = client.post(
        "/api/v1/cashbox/expense-categories", headers=headers, json={"name": "Papelería"}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/cashbox/expense-categories", headers=headers, json={"name": "Papelería"}
    )
    assert second.status_code == 409


async def test_cashbox_view_covers_today_but_not_the_history(
    client: TestClient, cashbox_tenant: dict
) -> None:
    """`cashbox.view` alcanza para el turno de hoy; el histórico va aparte.

    El fixture da `cashbox.view` y NO `cashbox.view_history`, que es
    exactamente el rol que 00031 vino a hacer posible: quien maneja la caja
    opera y cierra su día, pero no revisa los cierres de días anteriores ni
    los descuadres de turnos ajenos.
    """
    headers = _headers(cashbox_tenant["token"])
    opened = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    ).json()

    # La sesión de hoy: se ve y su acta también. Sin esto no podría cerrarla.
    assert (
        client.get(f"/api/v1/cashbox/sessions/{opened['id']}", headers=headers).status_code == 200
    )
    assert (
        client.get(f"/api/v1/cashbox/sessions/{opened['id']}/report", headers=headers).status_code
        == 200
    )
    client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "0.00"},
    )
    # Cerrada pero todavía de HOY: sigue siendo su turno, tiene que poder
    # imprimir el acta que acaba de firmar.
    assert (
        client.get(f"/api/v1/cashbox/sessions/{opened['id']}", headers=headers).status_code == 200
    )

    # El LISTADO es histórico por definición — la de hoy sale por /current.
    listado = client.get("/api/v1/cashbox/sessions", headers=headers)
    assert listado.status_code == 403
    assert listado.json()["code"] == "PERMISSION_DENIED"

    # Y la puerta de atrás: el mismo dato desde el módulo de reportes.
    closings = client.get("/api/v1/reports/closings", headers=headers)
    assert closings.status_code == 403

    # Se envejece la sesión un día: deja de ser "hoy" y pasa a ser histórico.
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "update public.cash_session set session_date = session_date - 1 "
                "where id = :id and company_id = :cid"
            ),
            {"id": opened["id"], "cid": str(cashbox_tenant["company_id"])},
        )

    ajena = client.get(f"/api/v1/cashbox/sessions/{opened['id']}", headers=headers)
    assert ajena.status_code == 403
    assert ajena.json()["details"]["permission"] == "cashbox.view_history"
    assert (
        client.get(f"/api/v1/cashbox/sessions/{opened['id']}/report", headers=headers).status_code
        == 403
    )


def test_today_session_is_readable_without_history_permission(
    client: TestClient, cashbox_tenant: dict
) -> None:
    """ "¿Ya cerré hoy?" se responde con `cashbox.view`, no con el histórico.

    El front lo deducía de `GET /reports/closings`, que desde 00031 exige
    `cashbox.view_history`. Sin este endpoint, un cajero habría necesitado ver
    los cierres de todo el negocio para saber si ya había cerrado su propio
    turno — el permiso nuevo habría roto su pantalla en vez de acotarla.
    """
    headers = _headers(cashbox_tenant["token"])

    # Sin caja abierta hoy: 404, no 403. La distinción importa — "todavía no
    # abriste" no es "no tienes permiso".
    vacia = client.get("/api/v1/cashbox/sessions/today", headers=headers)
    assert vacia.status_code == 404

    opened = client.post(
        "/api/v1/cashbox/sessions/open", headers=headers, json={"opening_balance": "0.00"}
    ).json()
    abierta = client.get("/api/v1/cashbox/sessions/today", headers=headers)
    assert abierta.status_code == 200
    assert abierta.json()["id"] == opened["id"]
    assert abierta.json()["status"] == "open"

    client.post(
        f"/api/v1/cashbox/sessions/{opened['id']}/close",
        headers=headers,
        json={"counted_cash": "0.00"},
    )
    # Y CERRADA sigue saliendo: es justo el caso que habilita "Reabrir".
    cerrada = client.get("/api/v1/cashbox/sessions/today", headers=headers)
    assert cerrada.status_code == 200
    assert cerrada.json()["status"] == "closed"
    assert cerrada.json()["id"] == opened["id"]
