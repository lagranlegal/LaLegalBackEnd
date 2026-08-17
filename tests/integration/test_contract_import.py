"""Integración de import de contratos pre-existentes
(docs/MIGRACION_CONTRATOS.md): sin sesión de caja, sin cash_movement,
legacy_code único, idempotencia, permiso dedicado, y que un contrato
importado se comporte igual que uno nativo desde el segundo después del
import (abono, remate). Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.modules.contracts.rules import add_months


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
async def import_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    """Empresa con: rol completo (incl. contracts.import) + rol limitado
    (sin ese permiso), cliente, árbol de categorías de 3 niveles, y una caja
    SIN sesión abierta (el import no la necesita; los tests que sí cobran
    después la abren explícitamente)."""
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
        "contracts.import",
        "contracts.auction",
        "payments.create",
    )
    limited_codes = ("contracts.view", "contracts.create", "payments.create")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa import-test')"),
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
                "(id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 3, 'Cadena', 'C')"
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


def _import_payload(tenant: dict, **overrides: object) -> dict:
    today = date.today()
    base = {
        "legacy_code": f"LEGACY-{uuid4()}",
        "customer_id": str(tenant["customer_id"]),
        "principal": "1000000.00",
        "capital_balance": "1000000.00",
        "interest_rate_pct": "5",
        "term_months": 4,
        "arrears_window_months": 4,
        "extension_months": 1,
        "start_date": today.isoformat(),
        "interest_paid_until": today.isoformat(),
        "items": [{"category_id": str(tenant["category_id"]), "description": "Cadena de oro 10g"}],
        "notes": "Migrado del sistema anterior",
    }
    base.update(overrides)
    return base


def test_import_without_cash_session_is_201(client: TestClient, import_tenant: dict) -> None:
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["legacy_code"].startswith("LEGACY-")
    assert body["capital_balance"] == "1000000.00"
    assert body["status"] == "active"


async def test_import_creates_no_cash_movement(client: TestClient, import_tenant: dict) -> None:
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant),
    )
    assert response.status_code == 201, response.text
    contract_id = response.json()["id"]

    async with AsyncSessionLocal() as session, session.begin():
        count = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement "
                    "where company_id = :cid and reference_id = :id"
                ),
                {"cid": str(import_tenant["company_id"]), "id": contract_id},
            )
        ).scalar_one()
    assert count == 0


def test_import_without_idempotency_key_is_400(client: TestClient, import_tenant: dict) -> None:
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"]),
        json=_import_payload(import_tenant),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_import_without_permission_is_403(client: TestClient, import_tenant: dict) -> None:
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["limited_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant),
    )
    assert response.status_code == 403


def test_import_idempotency_key_replays_same_contract(
    client: TestClient, import_tenant: dict
) -> None:
    key = str(uuid4())
    headers = _headers(import_tenant["full_token"], idempotency_key=key)
    payload = _import_payload(import_tenant)

    first = client.post("/api/v1/contracts/import", headers=headers, json=payload)
    second = client.post("/api/v1/contracts/import", headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]


def test_import_duplicate_legacy_code_is_409(client: TestClient, import_tenant: dict) -> None:
    legacy_code = f"LEGACY-{uuid4()}"
    first = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant, legacy_code=legacy_code),
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant, legacy_code=legacy_code),
    )
    assert second.status_code == 409
    assert second.json()["code"] == "CONTRACT_LEGACY_CODE_EXISTS"


def test_import_capital_exceeds_principal_is_422(client: TestClient, import_tenant: dict) -> None:
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant, principal="500000.00", capital_balance="600000.00"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "IMPORT_CAPITAL_EXCEEDS_PRINCIPAL"


def test_import_zero_capital_balance_is_422(client: TestClient, import_tenant: dict) -> None:
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(import_tenant, capital_balance="0.00"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "IMPORT_CAPITAL_EXCEEDS_PRINCIPAL"


def test_import_misaligned_dates_is_422(client: TestClient, import_tenant: dict) -> None:
    today = date.today()
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(
            import_tenant,
            start_date=add_months(today, -3).isoformat(),
            # 45 días después de start_date: no cae en un mes completo
            interest_paid_until=(add_months(today, -3) + timedelta(days=45)).isoformat(),
        ),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "IMPORT_DATES_MISALIGNED"


def test_import_start_date_in_future_is_400(client: TestClient, import_tenant: dict) -> None:
    today = date.today()
    future = add_months(today, 1)
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(
            import_tenant, start_date=future.isoformat(), interest_paid_until=future.isoformat()
        ),
    )
    assert response.status_code == 400


def test_import_derives_in_arrears_status(client: TestClient, import_tenant: dict) -> None:
    today = date.today()
    start_date = add_months(today, -5)
    interest_paid_until = add_months(start_date, 3)  # today - 2 meses -> 2 meses adeudados

    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(
            import_tenant,
            start_date=start_date.isoformat(),
            interest_paid_until=interest_paid_until.isoformat(),
            arrears_window_months=4,
        ),
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "in_arrears"


def test_import_payment_options_quotes_against_expected_owed_months(
    client: TestClient, import_tenant: dict
) -> None:
    today = date.today()
    start_date = add_months(today, -5)
    interest_paid_until = add_months(start_date, 3)  # 2 meses adeudados

    headers = _headers(import_tenant["full_token"])
    imported = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(
            import_tenant,
            start_date=start_date.isoformat(),
            interest_paid_until=interest_paid_until.isoformat(),
            capital_balance="1000000.00",
            arrears_window_months=4,
        ),
    ).json()

    quote = client.get(f"/api/v1/contracts/{imported['id']}/payment-options", headers=headers)
    assert quote.status_code == 200
    quote_body = quote.json()
    assert quote_body["months_owed"] == 2
    assert quote_body["monthly_interest"] == "50000.00"


async def test_normal_payment_on_imported_contract_updates_balance(
    client: TestClient, import_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=import_tenant["company_id"], register_id=import_tenant["register_id"]
    )
    today = date.today()
    start_date = add_months(today, -5)
    interest_paid_until = add_months(start_date, 3)  # 2 meses adeudados

    headers = _headers(import_tenant["full_token"])
    imported = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(
            import_tenant,
            start_date=start_date.isoformat(),
            interest_paid_until=interest_paid_until.isoformat(),
            capital_balance="1000000.00",
            arrears_window_months=4,
        ),
    ).json()

    payment_resp = client.post(
        f"/api/v1/contracts/{imported['id']}/payments",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json={"months_covered": 2, "capital_amount": "200000.00", "payment_method": "cash"},
    )
    assert payment_resp.status_code == 201, payment_resp.text
    payment = payment_resp.json()
    assert payment["capital_amount"] == "200000.00"
    assert payment["new_capital_balance"] == "800000.00"

    updated = client.get(f"/api/v1/contracts/{imported['id']}", headers=headers).json()
    assert updated["capital_balance"] == "800000.00"
    assert updated["status"] == "active"

    async with AsyncSessionLocal() as session, session.begin():
        movement_count = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement "
                    "where company_id = :cid and reference_type = 'contract_payment'"
                ),
                {"cid": str(import_tenant["company_id"])},
            )
        ).scalar_one()
    assert movement_count >= 1


def test_import_ready_for_auction_and_auction_of_expired_extension(
    client: TestClient, import_tenant: dict
) -> None:
    today = date.today()
    # interest_paid_until + 4 (ventana) + 1 (prórroga) = 5 meses antes de
    # hoy ya deja la prórroga vencida; nos vamos 6 meses atrás de margen.
    interest_paid_until = add_months(today, -6)
    headers = _headers(import_tenant["full_token"])

    imported = client.post(
        "/api/v1/contracts/import",
        headers=_headers(import_tenant["full_token"], idempotency_key=str(uuid4())),
        json=_import_payload(
            import_tenant,
            start_date=interest_paid_until.isoformat(),
            interest_paid_until=interest_paid_until.isoformat(),
            arrears_window_months=4,
            extension_months=1,
        ),
    ).json()
    assert imported["status"] == "in_extension"

    listing = client.get("/api/v1/contracts/ready-for-auction", headers=headers)
    ids = [c["id"] for c in listing.json()]
    assert imported["id"] in ids

    response = client.post(f"/api/v1/contracts/{imported['id']}/auction", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "auctioned"
