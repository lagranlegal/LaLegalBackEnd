"""Integración de contracts (paso 5): desembolso con sesión de caja, abonos
(meses completos, capital solo al día, descuentos, idempotencia), estados,
ready-for-auction. Requiere Postgres real (se salta si no hay)."""

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
    )
    limited_codes = ("contracts.view", "contracts.create", "payments.create")

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
