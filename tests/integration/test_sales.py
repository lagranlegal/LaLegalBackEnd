"""Integración de sales (paso 7): venta descuenta stock y genera
cash_movement, requiere sesión de caja abierta, idempotencia, descuento con
permiso condicional, anulación repone stock + contra-movimiento. Requiere
Postgres real (se salta si no hay)."""

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
async def sales_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    full_role_id = uuid4()
    limited_role_id = uuid4()
    full_user_id = uuid4()
    limited_user_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    item_id = uuid4()
    register_id = uuid4()

    full_codes = ("sales.create", "sales.void", "sales.apply_discount")
    limited_codes = ("sales.create",)

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa sales-test')"),
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
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 3, 'Cadena', 'C')"
            ),
            {"id": str(cat3), "cid": str(company_id), "parent": str(cat2)},
        )
        await session.execute(
            text(
                "insert into public.inventory_item "
                "(id, company_id, code, name, cat1_id, cat2_id, cat3_id, origin, cost, "
                " sale_price, quantity, status) "
                "values (:id, :cid, 'JOC0001I', 'Cadena de oro', :cat1, :cat2, :cat3, 'other', "
                " 300000, 500000, 3, 'available')"
            ),
            {
                "id": str(item_id),
                "cid": str(company_id),
                "cat1": str(cat1),
                "cat2": str(cat2),
                "cat3": str(cat3),
            },
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
        "item_id": item_id,
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

    await _try_delete("delete from public.sale_line where company_id = :cid")
    await _try_delete("delete from public.sale where company_id = :cid")
    await _try_delete("delete from public.inventory_item where company_id = :cid")
    await _try_delete("delete from public.code_counter where company_id = :cid")
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


def test_sale_without_open_session_is_409(client: TestClient, sales_tenant: dict) -> None:
    response = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": str(sales_tenant["item_id"]), "quantity": 1, "unit_price": "500000.00"}
            ],
        },
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CASH_SESSION_NOT_OPEN"


async def test_create_sale_reduces_stock_and_records_movement(
    client: TestClient, sales_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=sales_tenant["company_id"], register_id=sales_tenant["register_id"]
    )
    response = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": str(sales_tenant["item_id"]), "quantity": 1, "unit_price": "500000.00"}
            ],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total"] == "500000.00"

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity, status from public.inventory_item where id = :id"),
                {"id": str(sales_tenant["item_id"])},
            )
        ).first()
        movement = (
            await session.execute(
                text(
                    "select direction, concept, amount from public.cash_movement "
                    "where company_id = :cid and reference_type = 'sale'"
                ),
                {"cid": str(sales_tenant["company_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 2
    assert item[1] == "available"
    assert movement is not None
    assert movement[0] == "in"
    assert str(movement[2]) == "500000.00"


async def test_sale_reduces_to_zero_marks_sold(client: TestClient, sales_tenant: dict) -> None:
    await _open_cash_session(
        company_id=sales_tenant["company_id"], register_id=sales_tenant["register_id"]
    )
    response = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": str(sales_tenant["item_id"]), "quantity": 3, "unit_price": "500000.00"}
            ],
        },
    )
    assert response.status_code == 201, response.text

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity, status from public.inventory_item where id = :id"),
                {"id": str(sales_tenant["item_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 0
    assert item[1] == "sold"


def test_sale_insufficient_stock_is_rejected(client: TestClient, sales_tenant: dict) -> None:
    # El chequeo de stock corre ANTES que el de sesión de caja abierta, así
    # que esto falla con 400 aunque no haya sesión abierta en este test.
    response = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": str(sales_tenant["item_id"]), "quantity": 99, "unit_price": "500000.00"}
            ],
        },
    )
    assert response.status_code == 400


async def test_sale_idempotency_key_replays(client: TestClient, sales_tenant: dict) -> None:
    await _open_cash_session(
        company_id=sales_tenant["company_id"], register_id=sales_tenant["register_id"]
    )
    key = str(uuid4())
    body = {
        "payment_method": "cash",
        "lines": [
            {"item_id": str(sales_tenant["item_id"]), "quantity": 1, "unit_price": "500000.00"}
        ],
    }
    first = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=key),
        json=body,
    )
    second = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=key),
        json=body,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity from public.inventory_item where id = :id"),
                {"id": str(sales_tenant["item_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 2  # solo se descontó una vez


async def test_sale_discount_requires_permission(client: TestClient, sales_tenant: dict) -> None:
    await _open_cash_session(
        company_id=sales_tenant["company_id"], register_id=sales_tenant["register_id"]
    )
    body = {
        "payment_method": "cash",
        "lines": [
            {"item_id": str(sales_tenant["item_id"]), "quantity": 1, "unit_price": "500000.00"}
        ],
        "discount_amount": "50000.00",
        "discount_reason": "cliente frecuente",
    }
    denied = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["limited_token"], idempotency_key=str(uuid4())),
        json=body,
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/api/v1/sales",
        headers=_headers(sales_tenant["full_token"], idempotency_key=str(uuid4())),
        json=body,
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["total"] == "450000.00"


async def test_void_sale_restores_stock_and_blocks_double_void(
    client: TestClient, sales_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=sales_tenant["company_id"], register_id=sales_tenant["register_id"]
    )
    headers = _headers(sales_tenant["full_token"], idempotency_key=str(uuid4()))
    sale = client.post(
        "/api/v1/sales",
        headers=headers,
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": str(sales_tenant["item_id"]), "quantity": 2, "unit_price": "500000.00"}
            ],
        },
    ).json()

    void_headers = _headers(sales_tenant["full_token"])
    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=void_headers,
        json={"reason": "cliente se arrepintió"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "voided"

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity, status from public.inventory_item where id = :id"),
                {"id": str(sales_tenant["item_id"])},
            )
        ).first()
        out_movement = (
            await session.execute(
                text(
                    "select direction from public.cash_movement "
                    "where company_id = :cid and reference_type = 'sale' and direction = 'out'"
                ),
                {"cid": str(sales_tenant["company_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 3  # repuesto por completo
    assert item[1] == "available"
    assert out_movement is not None

    second_void = client.post(
        f"/api/v1/sales/{sale['id']}/void", headers=void_headers, json={"reason": "otra vez"}
    )
    assert second_void.status_code == 409
