"""Integración de contracts (paso 5): desembolso con sesión de caja, abonos
(meses completos, capital solo al día, descuentos, idempotencia), estados,
ready-for-auction. Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from decimal import Decimal
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
async def contract_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa con: rol completo (incl. payments.apply_discount) + rol
    limitado (sin ese permiso), cliente, árbol de categorías de 3 niveles
    (nivel 3 con term=4/window=4 meses), y una caja SIN sesión abierta (los
    tests que necesitan cobrar/desembolsar la abren explícitamente).
    """
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    full_role_id = uuid4()
    limited_role_id = uuid4()
    full_user_id = uuid4()
    limited_user_id = uuid4()
    customer_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    register_id = uuid4()

    full_codes = (
        "contracts.view",
        "contracts.create",
        "contracts.edit",
        "contracts.auction",
        "payments.create",
        "payments.apply_discount",
        # 00051: ampliar el préstamo, y autorizar por encima del LTV. El rol
        # `limited` NO los tiene a propósito — es con el que se prueba que
        # sin permiso se bloquea.
        "contracts.extend_loan",
        "contracts.override_ltv",
    )
    # `limited` SÍ puede ampliar préstamos, pero NO tiene
    # `contracts.override_ltv`: es el rol con el que se prueba que pasarse del
    # cupo se bloquea, que es el caso real (el asesor no puede, el dueño sí).
    limited_codes = (
        "contracts.view",
        "contracts.create",
        "payments.create",
        "contracts.extend_loan",
    )

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa contracts-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, :name)"),
            [
                {"id": str(full_role_id), "cid": str(company_id), "name": "Full"},
                {"id": str(limited_role_id), "cid": str(company_id), "name": "Limited"},
            ],
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code in :codes"
            ).bindparams(bindparam("codes", expanding=True)),
            {"role_id": str(full_role_id), "codes": list(full_codes)},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code in :codes"
            ).bindparams(bindparam("codes", expanding=True)),
            {"role_id": str(limited_role_id), "codes": list(limited_codes)},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :role_id, 'Full User', :email, 'active')"
            ),
            {
                "id": str(full_user_id),
                "cid": str(company_id),
                "role_id": str(full_role_id),
                "email": f"full-{full_user_id}@example.com",
            },
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :role_id, 'Limited User', :email, 'active')"
            ),
            {
                "id": str(limited_user_id),
                "cid": str(company_id),
                "role_id": str(limited_role_id),
                "email": f"limited-{limited_user_id}@example.com",
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
        "customer_id": customer_id,
        "category_id": cat3,
        "register_id": register_id,
        "full_token": full_token,
        "limited_token": limited_token,
    }

    async def _try_delete(sql: str) -> None:
        # cash_movement y contract_payment son inmutables (forbid_change), y
        # eso a su vez puede dejar cash_session/cash_register/company sin
        # poder borrarse (FK) cuando el test disbursó/cobró de verdad — cada
        # delete corre en su propia transacción y si falla por eso, se
        # ignora (huérfano local a propósito, igual que audit_log).
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


async def _open_cash_session(*, company_id, register_id) -> None:
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.cash_session "
                "(company_id, register_id, opened_by, opening_balance) "
                "values (:cid, :rid, :cid, 0)"
            ),
            {"cid": str(company_id), "rid": str(register_id)},
        )


async def _backdate_interest_paid_until(*, company_id, contract_id, months: int) -> None:
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "update public.contract "
                "set interest_paid_until = interest_paid_until - make_interval(months => :months) "
                "where company_id = :cid and id = :id"
            ),
            {"months": months, "cid": str(company_id), "id": str(contract_id)},
        )


def _contract_payload(tenant: dict, **overrides: object) -> dict:
    base = {
        "customer_id": str(tenant["customer_id"]),
        "principal": "1000000.00",
        "interest_rate_pct": "5",
        "payment_method": "cash",
        "items": [{"category_id": str(tenant["category_id"]), "description": "Cadena de oro 10g"}],
    }
    base.update(overrides)
    return base


def test_create_contract_without_open_session_is_409(
    client: TestClient, contract_tenant: dict
) -> None:
    response = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CASH_SESSION_NOT_OPEN"


async def test_create_contract_disburses_and_sets_snapshot(
    client: TestClient, contract_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )

    response = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["principal"] == "1000000.00"
    assert body["capital_balance"] == "1000000.00"
    assert body["term_months"] == 4
    assert body["arrears_window_months"] == 4
    assert body["status"] == "active"

    async with AsyncSessionLocal() as session, session.begin():
        movement = (
            await session.execute(
                text(
                    "select direction, concept, amount from public.cash_movement "
                    "where company_id = :cid and reference_type = 'contract' and reference_id = :id"
                ),
                {"cid": str(contract_tenant["company_id"]), "id": body["id"]},
            )
        ).first()
    assert movement is not None
    assert movement[0] == "out"
    assert movement[1] == "loan_disbursed"
    assert str(movement[2]) == "1000000.00"


def test_create_contract_without_idempotency_key_is_400(
    client: TestClient, contract_tenant: dict
) -> None:
    response = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"]),
        json=_contract_payload(contract_tenant),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


async def test_create_contract_idempotency_key_replays_same_contract_no_double_disbursement(
    client: TestClient, contract_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    key = str(uuid4())
    headers = _headers(contract_tenant["full_token"], idempotency_key=key)
    payload = _contract_payload(contract_tenant)

    first = client.post("/api/v1/contracts", headers=headers, json=payload)
    second = client.post("/api/v1/contracts", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]

    async with AsyncSessionLocal() as session, session.begin():
        contract_count = (
            await session.execute(
                text(
                    "select count(*) from public.contract "
                    "where company_id = :cid and idempotency_key = :key"
                ),
                {"cid": str(contract_tenant["company_id"]), "key": key},
            )
        ).scalar_one()
        movement_count = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement "
                    "where company_id = :cid and reference_type = 'contract' "
                    "and reference_id = :id"
                ),
                {"cid": str(contract_tenant["company_id"]), "id": first.json()["id"]},
            )
        ).scalar_one()
    assert contract_count == 1
    assert movement_count == 1


async def test_create_contract_rejects_mismatched_category_terms(
    client: TestClient, contract_tenant: dict
) -> None:
    company_id = contract_tenant["company_id"]
    tech1, tech2, tech3 = uuid4(), uuid4(), uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, null, 1, 'Tecnología', 'T')"
            ),
            {"id": str(tech1), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 2, 'Celulares', 'E')"
            ),
            {"id": str(tech2), "cid": str(company_id), "parent": str(tech1)},
        )
        await session.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, "
                " default_term_months, arrears_window_months) "
                "values (:id, :cid, :parent, 3, 'Smartphone', 'S', 1, 1)"
            ),
            {"id": str(tech3), "cid": str(company_id), "parent": str(tech2)},
        )

    response = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(
            contract_tenant,
            items=[
                {"category_id": str(contract_tenant["category_id"]), "description": "Cadena"},
                {"category_id": str(tech3), "description": "Celular"},
            ],
        ),
    )
    assert response.status_code == 400


async def test_payment_covers_owed_months_and_capital(
    client: TestClient, contract_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    headers = _headers(contract_tenant["full_token"])
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    ).json()
    await _backdate_interest_paid_until(
        company_id=contract_tenant["company_id"], contract_id=contract["id"], months=2
    )

    quote = client.get(f"/api/v1/contracts/{contract['id']}/payment-options", headers=headers)
    assert quote.status_code == 200
    quote_body = quote.json()
    assert quote_body["months_owed"] == 2
    assert quote_body["monthly_interest"] == "50000.00"
    assert len(quote_body["options"]) == 2
    assert quote_body["options"][0]["allows_capital"] is False
    assert quote_body["options"][1]["allows_capital"] is True

    payment_resp = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"months_covered": 2, "capital_amount": "200000.00", "payment_method": "cash"},
    )
    assert payment_resp.status_code == 201, payment_resp.text
    payment = payment_resp.json()
    assert payment["interest_amount"] == "100000.00"
    assert payment["capital_amount"] == "200000.00"
    assert payment["total"] == "300000.00"
    assert payment["new_capital_balance"] == "800000.00"

    updated = client.get(f"/api/v1/contracts/{contract['id']}", headers=headers).json()
    assert updated["capital_balance"] == "800000.00"
    assert updated["status"] == "active"


async def test_capital_before_interest_caught_up_is_rejected(
    client: TestClient, contract_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    ).json()
    await _backdate_interest_paid_until(
        company_id=contract_tenant["company_id"], contract_id=contract["id"], months=2
    )

    response = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"months_covered": 1, "capital_amount": "50000.00", "payment_method": "cash"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "PAYMENT_PARTIAL_INTEREST_REJECTED"


async def test_payment_idempotency_key_replays_same_payment(
    client: TestClient, contract_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    headers = _headers(contract_tenant["full_token"])
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    ).json()
    await _backdate_interest_paid_until(
        company_id=contract_tenant["company_id"], contract_id=contract["id"], months=1
    )

    key = str(uuid4())
    body = {"months_covered": 1, "payment_method": "cash"}
    first = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["full_token"], idempotency_key=key),
        json=body,
    )
    second = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["full_token"], idempotency_key=key),
        json=body,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    updated = client.get(f"/api/v1/contracts/{contract['id']}", headers=headers).json()
    # Solo se descontó una vez el interés (el contrato queda "active" con
    # saldo intacto porque el pago fue solo de interés, no de capital) —
    # verificamos que no se duplicó consultando los abonos.
    payments = client.get(f"/api/v1/contracts/{contract['id']}/payments", headers=headers).json()
    assert len(payments["items"]) == 1
    assert updated["status"] == "active"


async def test_discount_requires_permission(client: TestClient, contract_tenant: dict) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    ).json()
    await _backdate_interest_paid_until(
        company_id=contract_tenant["company_id"], contract_id=contract["id"], months=1
    )

    denied = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["limited_token"], idempotency_key=str(uuid4())),
        json={
            "months_covered": 1,
            "payment_method": "cash",
            "discount_amount": "10000.00",
            "discount_reason": "cliente frecuente",
        },
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "months_covered": 1,
            "payment_method": "cash",
            "discount_amount": "10000.00",
            "discount_reason": "cliente frecuente",
        },
    )
    assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["discount_amount"] == "10000.00"
    assert body["total"] == "40000.00"  # 50000 interés - 10000 descuento

    async with AsyncSessionLocal() as session, session.begin():
        audit = (
            await session.execute(
                text(
                    "select action from public.audit_log "
                    "where company_id = :cid and action = 'apply_payment_discount'"
                ),
                {"cid": str(contract_tenant["company_id"])},
            )
        ).first()
    assert audit is not None


async def test_ready_for_auction_lists_after_extension_triggered(
    client: TestClient, contract_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    headers = _headers(contract_tenant["full_token"])
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    ).json()
    # ventana=4 meses + 1 mes de prórroga; nos vamos 8 meses atrás para que
    # la prórroga ya esté vencida.
    await _backdate_interest_paid_until(
        company_id=contract_tenant["company_id"], contract_id=contract["id"], months=8
    )

    # forzar el recompute-on-read
    refreshed = client.get(f"/api/v1/contracts/{contract['id']}", headers=headers).json()
    assert refreshed["status"] == "in_extension"

    listing = client.get("/api/v1/contracts/ready-for-auction", headers=headers)
    assert listing.status_code == 200
    ids = [c["id"] for c in listing.json()]
    assert contract["id"] in ids


async def test_category_params_are_inherited_from_ancestors(
    client: TestClient, contract_tenant: dict
) -> None:
    """El plazo y la ventana se heredan del árbol de categorías.

    Antes se leían SOLO de la hoja, así que los mismos campos en los niveles 1
    y 2 eran configuración muerta —el formulario los pedía y nada los leía— y
    olvidar el plazo en UNA hoja rompía la creación de contratos con esa
    prenda con un error que no decía qué hacer. Con treinta hojas era cuestión
    de tiempo.

    Configurar "toda la joyería en oro va a 4 meses" una sola vez en el padre
    es lo que hace que tener un árbol de tres niveles valga la pena.
    """
    company_id = contract_tenant["company_id"]
    cat1, cat2 = uuid4(), uuid4()
    hoja = uuid4()

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, "
                " default_term_months, arrears_window_months, max_ltv_pct) "
                "values (:id, :cid, null, 1, 'Herencia N1', 'H', 9, 9, 50)"
            ),
            {"id": str(cat1), "cid": str(company_id)},
        )
        # El nivel 2 define plazo y ventana propios; NO define LTV.
        await session.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter, "
                " default_term_months, arrears_window_months) "
                "values (:id, :cid, :parent, 2, 'Herencia N2', 'E', 4, 4)"
            ),
            {"id": str(cat2), "cid": str(company_id), "parent": str(cat1)},
        )
        # La hoja no define NADA: hereda plazo/ventana del nivel 2 y LTV del 1.
        await session.execute(
            text(
                "insert into public.category "
                "(id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 3, 'Herencia hoja', 'J')"
            ),
            {"id": str(hoja), "cid": str(company_id), "parent": str(cat2)},
        )

    await _open_cash_session(company_id=company_id, register_id=contract_tenant["register_id"])

    headers = _headers(contract_tenant["full_token"], idempotency_key=str(uuid4()))
    response = client.post(
        "/api/v1/contracts",
        headers=headers,
        json={
            "customer_id": str(contract_tenant["customer_id"]),
            "principal": "1000000.00",
            "appraisal_value": "1500000.00",
            "interest_rate_pct": "5",
            "payment_method": "cash",
            "items": [{"category_id": str(hoja), "description": "Prenda que hereda"}],
        },
    )
    assert response.status_code == 201, response.text
    contrato = response.json()

    # Plazo y ventana vienen del nivel 2, el más cercano que los define.
    assert contrato["term_months"] == 4
    assert contrato["arrears_window_months"] == 4
    # Y el LTV del nivel 1, porque el 2 no lo define: cada campo se resuelve
    # por separado, no en bloque.
    assert contrato["ltv_warning"] is True, "1.000.000 sobre 1.500.000 es 66%, supera el 50% del N1"


async def test_list_contracts_filters_by_customer_id(
    client: TestClient, contract_tenant: dict
) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #2: GET /contracts no tenía filtro
    por cliente — la ficha de cliente traía la página de 200 más grande y
    filtraba client-side, con el hueco documentado de perder contratos más
    allá de esa ventana."""
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    other_customer_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.customer "
                "(id, company_id, full_name, doc_type, doc_number, phone) "
                "values (:id, :cid, 'Otro Cliente', 'cc', :doc, '3000000001')"
            ),
            {
                "id": str(other_customer_id),
                "cid": str(contract_tenant["company_id"]),
                "doc": str(uuid4().int)[:10],
            },
        )

    headers = _headers(contract_tenant["full_token"], idempotency_key=str(uuid4()))
    mine = client.post(
        "/api/v1/contracts", headers=headers, json=_contract_payload(contract_tenant)
    )
    assert mine.status_code == 201, mine.text

    other_headers = _headers(contract_tenant["full_token"], idempotency_key=str(uuid4()))
    other = client.post(
        "/api/v1/contracts",
        headers=other_headers,
        json=_contract_payload(contract_tenant, customer_id=str(other_customer_id)),
    )
    assert other.status_code == 201, other.text

    response = client.get(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"]),
        params={"customer_id": str(contract_tenant["customer_id"])},
    )
    assert response.status_code == 200
    ids = [c["id"] for c in response.json()["items"]]
    assert mine.json()["id"] in ids
    assert other.json()["id"] not in ids


async def test_list_contracts_q_searches_number_and_customer(
    client: TestClient, contract_tenant: dict
) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #2: `GET /contracts` no tenía `?q=`
    — el buscador de la UI era un parche client-side de 200 registros que
    nunca encontraba nada por nombre de cliente."""
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    other_customer_id = uuid4()
    other_doc = str(uuid4().int)[:10]
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.customer "
                "(id, company_id, full_name, doc_type, doc_number, phone) "
                "values (:id, :cid, 'Roberto Gomez Bolaños', 'cc', :doc, '3000000002')"
            ),
            {
                "id": str(other_customer_id),
                "cid": str(contract_tenant["company_id"]),
                "doc": other_doc,
            },
        )

    mine = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    )
    assert mine.status_code == 201, mine.text

    other = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant, customer_id=str(other_customer_id)),
    )
    assert other.status_code == 201, other.text

    headers = _headers(contract_tenant["full_token"])

    # Por número del contrato de "other".
    by_number = client.get(
        "/api/v1/contracts", headers=headers, params={"q": str(other.json()["number"])}
    )
    assert by_number.status_code == 200
    ids = [c["id"] for c in by_number.json()["items"]]
    assert other.json()["id"] in ids
    assert mine.json()["id"] not in ids

    # Por nombre del cliente (full-text, un fragmento) — encuentra "other",
    # no "mine" (cuyo cliente es "Cliente Test").
    by_name = client.get("/api/v1/contracts", headers=headers, params={"q": "Gomez"})
    assert by_name.status_code == 200
    ids = [c["id"] for c in by_name.json()["items"]]
    assert other.json()["id"] in ids
    assert mine.json()["id"] not in ids

    # Por documento del cliente (prefijo).
    by_doc = client.get("/api/v1/contracts", headers=headers, params={"q": other_doc[:6]})
    assert by_doc.status_code == 200
    ids = [c["id"] for c in by_doc.json()["items"]]
    assert other.json()["id"] in ids
    assert mine.json()["id"] not in ids


async def test_settlement_info_requires_paid_status_and_matches_the_payoff_payment(
    client: TestClient, contract_tenant: dict
) -> None:
    """Para el documento de paz y salvo: `settled_at` se deriva del abono
    que saldó el contrato, nunca una columna guardada aparte."""
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    headers = _headers(contract_tenant["full_token"])
    contract = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),
    ).json()

    not_yet_paid = client.get(f"/api/v1/contracts/{contract['id']}/settlement", headers=headers)
    assert not_yet_paid.status_code == 404

    quote = client.get(
        f"/api/v1/contracts/{contract['id']}/payment-options", headers=headers
    ).json()
    assert quote["months_owed"] == 0, "contrato recién creado: nada adeudado todavía"

    payoff = client.post(
        f"/api/v1/contracts/{contract['id']}/payments",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"months_covered": 0, "capital_amount": "1000000.00", "payment_method": "cash"},
    )
    assert payoff.status_code == 201, payoff.text
    assert payoff.json()["new_capital_balance"] == "0.00"

    updated = client.get(f"/api/v1/contracts/{contract['id']}", headers=headers).json()
    assert updated["status"] == "paid"

    settlement = client.get(f"/api/v1/contracts/{contract['id']}/settlement", headers=headers)
    assert settlement.status_code == 200, settlement.text
    body = settlement.json()
    assert body["receipt_number"] == payoff.json()["receipt_number"]
    assert body["settled_at"] == payoff.json()["paid_at"]


# ==========================================================================
# Ampliar el préstamo — "recargo" (00051, docs/RECARGOS.md)
# ==========================================================================
async def _set_ltv(*, company_id, category_id, pct: int) -> None:
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "update public.category set max_ltv_pct = :pct "
                "where id = :id and company_id = :cid"
            ),
            {"pct": pct, "id": str(category_id), "cid": str(company_id)},
        )


async def _contrato_ampliable(client: TestClient, tenant: dict, **overrides: object) -> dict:
    """Un contrato con tasación y LTV, listo para ampliar: 1.000.000 prestados
    sobre una prenda de 2.000.000 al 70% → 400.000 de cupo."""
    await _open_cash_session(company_id=tenant["company_id"], register_id=tenant["register_id"])
    await _set_ltv(company_id=tenant["company_id"], category_id=tenant["category_id"], pct=70)
    response = client.post(
        "/api/v1/contracts",
        headers=_headers(tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(tenant, appraisal_value="2000000.00", **overrides),
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def test_el_cupo_es_el_sobrante_de_la_tasacion(
    client: TestClient, contract_tenant: dict
) -> None:
    contrato = await _contrato_ampliable(client, contract_tenant)
    cupo = client.get(
        f"/api/v1/contracts/{contrato['id']}/extension-options",
        headers=_headers(contract_tenant["full_token"]),
    )
    assert cupo.status_code == 200, cupo.text
    assert cupo.json()["ceiling"] == "1400000.00"
    assert cupo.json()["available"] == "400000.00"
    assert cupo.json()["is_open"] is True
    assert cupo.json()["blocked_reason"] is None


async def test_ampliar_sucede_el_contrato_en_vez_de_modificarlo(
    client: TestClient, contract_tenant: dict
) -> None:
    """El corazón del diseño: no se toca el capital del contrato firmado — se
    cierra y nace otro, porque el papel que el cliente firmó dice un capital
    y si cambia ya no describe la deuda."""
    viejo = await _contrato_ampliable(client, contract_tenant)

    nuevo = client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "400000.00", "payment_method": "cash"},
    )
    assert nuevo.status_code == 201, nuevo.text
    n = nuevo.json()

    # Es OTRO contrato, con su número.
    assert n["id"] != viejo["id"]
    assert n["number"] != viejo["number"]
    assert n["capital_balance"] == "1400000.00"
    # Nace SIN foto firmada: hay que imprimirlo y firmarlo. Es su razón de ser.
    assert n["signed_photo_url"] is None
    # La cadena queda visible en los dos sentidos.
    assert n["parent_contract_id"] == viejo["id"]
    assert n["root_contract_id"] == viejo["id"]
    # Tasa y plazo se COPIAN: ampliar no renegocia lo pactado.
    assert n["interest_rate_pct"] == viejo["interest_rate_pct"]
    assert n["term_months"] == viejo["term_months"]

    cerrado = client.get(
        f"/api/v1/contracts/{viejo['id']}", headers=_headers(contract_tenant["full_token"])
    )
    assert cerrado.json()["status"] == "superseded"
    # Las prendas siguen en custodia, no se le devolvieron a nadie.
    assert all(i["status"] == "transferred" for i in cerrado.json()["items"])
    assert len(nuevo.json()["items"]) == len(viejo["items"])


async def test_a_la_caja_sale_SOLO_el_delta(client: TestClient, contract_tenant: dict) -> None:
    """El capital viejo ya salió el día del contrato original. Volver a
    moverlo lo contaría dos veces en `/reports/pawn-performance`."""
    viejo = await _contrato_ampliable(client, contract_tenant)
    nuevo = client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "400000.00", "payment_method": "cash"},
    )
    assert nuevo.status_code == 201, nuevo.text

    async with AsyncSessionLocal() as session:
        total = (
            await session.execute(
                text(
                    "select coalesce(sum(amount), 0) from public.cash_movement "
                    "where company_id = :cid and concept = 'loan_disbursed'"
                ),
                {"cid": str(contract_tenant["company_id"])},
            )
        ).scalar_one()
    # 1.000.000 del contrato original + 400.000 del recargo. NO 2.400.000.
    assert Decimal(str(total)) == Decimal("1400000.00")


async def test_pasarse_del_cupo_sin_permiso_se_bloquea(
    client: TestClient, contract_tenant: dict
) -> None:
    """El rol `limited` SÍ puede ampliar, pero no tiene
    `contracts.override_ltv` — que es el caso real: el asesor no puede
    autorizar la excepción, el dueño sí.

    Y comprueba las dos mitades: dentro del cupo pasa, por encima se bloquea.
    Sin la primera mitad el test podría estar pasando porque le falta el
    permiso del endpoint, no por el LTV."""
    contrato = await _contrato_ampliable(client, contract_tenant)

    dentro = client.post(
        f"/api/v1/contracts/{contrato['id']}/extend-loan",
        headers=_headers(contract_tenant["limited_token"], idempotency_key=str(uuid4())),
        json={"amount": "400000.00", "payment_method": "cash"},
    )
    assert dentro.status_code == 201, dentro.text

    # Ese sucesor ya no tiene cupo (1.400.000 de saldo contra un techo de
    # 1.400.000), así que cualquier monto se pasa.
    respuesta = client.post(
        f"/api/v1/contracts/{dentro.json()['id']}/extend-loan",
        headers=_headers(contract_tenant["limited_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    assert respuesta.status_code == 403, respuesta.text
    assert respuesta.json()["code"] == "PERMISSION_DENIED"
    assert respuesta.json()["details"]["permission"] == "contracts.override_ltv"


async def test_pasarse_del_cupo_CON_permiso_advierte_y_deja_pasar(
    client: TestClient, contract_tenant: dict
) -> None:
    """Quien tiene `contracts.override_ltv` autoriza la excepción, y el
    contrato queda marcado — la advertencia no se pierde."""
    contrato = await _contrato_ampliable(client, contract_tenant)
    nuevo = client.post(
        f"/api/v1/contracts/{contrato['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "900000.00", "payment_method": "cash"},
    )
    assert nuevo.status_code == 201, nuevo.text
    assert nuevo.json()["ltv_warning"] is True
    assert nuevo.json()["capital_balance"] == "1900000.00"


async def test_no_se_puede_ampliar_con_intereses_adeudados(
    client: TestClient, contract_tenant: dict
) -> None:
    """El interés vencido NUNCA se suma al capital nuevo: capitalizar interés
    es anatocismo y volvería el saldo imposible de auditar contra los
    recibos."""
    contrato = await _contrato_ampliable(client, contract_tenant)
    await _backdate_interest_paid_until(
        company_id=contract_tenant["company_id"], contract_id=contrato["id"], months=2
    )
    respuesta = client.post(
        f"/api/v1/contracts/{contrato['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["code"] == "CONTRACT_INTEREST_OVERDUE"


async def test_fuera_de_la_ventana_no_se_puede_ampliar(
    client: TestClient, contract_tenant: dict
) -> None:
    contrato = await _contrato_ampliable(client, contract_tenant, extension_window_days=0)
    assert contrato["extension_window_days"] == 0

    cupo = client.get(
        f"/api/v1/contracts/{contrato['id']}/extension-options",
        headers=_headers(contract_tenant["full_token"]),
    )
    assert cupo.json()["window_ends_on"] is None
    assert cupo.json()["blocked_reason"] == "EXTENSION_WINDOW_CLOSED"

    respuesta = client.post(
        f"/api/v1/contracts/{contrato['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["code"] == "EXTENSION_WINDOW_CLOSED"


async def test_sin_tasacion_no_se_puede_ampliar(
    client: TestClient, contract_tenant: dict
) -> None:
    """Prestar sin techo es prestar a ciegas, y el mensaje dice cómo
    arreglarlo."""
    await _open_cash_session(
        company_id=contract_tenant["company_id"], register_id=contract_tenant["register_id"]
    )
    await _set_ltv(
        company_id=contract_tenant["company_id"],
        category_id=contract_tenant["category_id"],
        pct=70,
    )
    creado = client.post(
        "/api/v1/contracts",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_contract_payload(contract_tenant),  # sin appraisal_value
    )
    respuesta = client.post(
        f"/api/v1/contracts/{creado.json()['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["code"] == "CONTRACT_WITHOUT_APPRAISAL"


async def test_un_contrato_ya_ampliado_no_se_puede_volver_a_ampliar(
    client: TestClient, contract_tenant: dict
) -> None:
    viejo = await _contrato_ampliable(client, contract_tenant)
    client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    repetido = client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    assert repetido.status_code == 400, repetido.text
    assert repetido.json()["code"] == "CONTRACT_CLOSED"


async def test_la_cadena_conserva_la_raiz_al_encadenar_recargos(
    client: TestClient, contract_tenant: dict
) -> None:
    """El anti-abuso: el SEGUNDO recargo sigue midiendo su ventana desde el
    contrato original, no desde el sucesor. Sin esto, un recargo de $1 el
    último día reiniciaría el reloj para siempre."""
    raiz = await _contrato_ampliable(client, contract_tenant)
    segundo = client.post(
        f"/api/v1/contracts/{raiz['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    ).json()
    tercero = client.post(
        f"/api/v1/contracts/{segundo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    ).json()

    assert segundo["root_contract_id"] == raiz["id"]
    assert tercero["root_contract_id"] == raiz["id"]      # la RAÍZ, no el segundo
    assert tercero["parent_contract_id"] == segundo["id"]  # el padre sí avanza
    assert tercero["capital_balance"] == "1200000.00"


async def test_reintentar_con_la_misma_clave_devuelve_el_mismo_sucesor(
    client: TestClient, contract_tenant: dict
) -> None:
    """Es una operación de dinero: un reintento de red no puede desembolsar
    dos veces."""
    viejo = await _contrato_ampliable(client, contract_tenant)
    clave = str(uuid4())
    body = {"amount": "400000.00", "payment_method": "cash"}
    uno = client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=clave),
        json=body,
    )
    dos = client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=clave),
        json=body,
    )
    assert uno.json()["id"] == dos.json()["id"]


async def test_un_contrato_ampliado_no_genera_paz_y_salvo(
    client: TestClient, contract_tenant: dict
) -> None:
    """El cliente sigue debiendo, solo que en otro documento."""
    viejo = await _contrato_ampliable(client, contract_tenant)
    client.post(
        f"/api/v1/contracts/{viejo['id']}/extend-loan",
        headers=_headers(contract_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"amount": "100000.00", "payment_method": "cash"},
    )
    paz = client.get(
        f"/api/v1/contracts/{viejo['id']}/settlement",
        headers=_headers(contract_tenant["full_token"]),
    )
    assert paz.status_code == 404, paz.text
