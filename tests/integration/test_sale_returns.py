"""Integración de devolución de cliente (00042-00045): camino A (reabre el
mismo lote) vs. camino B (lote nuevo con letra `D`), nota crédito emitida y
redimida, bloqueo de efectivo sobre una venta `settlement` sin liquidar,
devolución parcial, plazo configurable (advierte, no bloquea con permiso), y
`restock=false`. Requiere Postgres real (se salta si no hay)."""

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
async def returns_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    full_role_id = uuid4()
    override_role_id = uuid4()
    full_user_id = uuid4()
    override_user_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    product_id = uuid4()
    item_id = uuid4()
    register_id = uuid4()
    customer_id = uuid4()

    full_codes = (
        "sales.view",
        "sales.create",
        "sales.void",
        "sales.return",
        "inventory.view",
        "inventory.create",
    )
    # Solo este rol puede saltarse el plazo de devolución.
    override_codes = (*full_codes, "sales.return_override_time_limit")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa returns-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, :name)"),
            [
                {"id": str(full_role_id), "cid": str(company_id), "name": "Full"},
                {"id": str(override_role_id), "cid": str(company_id), "name": "Override"},
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
            {"role_id": str(override_role_id), "codes": list(override_codes)},
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
                "values (:id, :cid, :role_id, 'Override User', :email, 'active')"
            ),
            {
                "id": str(override_user_id),
                "cid": str(company_id),
                "role_id": str(override_role_id),
                "email": f"override-{override_user_id}@example.com",
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
                "insert into public.product "
                "(id, company_id, code, name, cat1_id, cat2_id, cat3_id, sale_price) "
                "values (:id, :cid, 'JOC0001', 'Cadena de oro', :cat1, :cat2, :cat3, 500000)"
            ),
            {
                "id": str(product_id),
                "cid": str(company_id),
                "cat1": str(cat1),
                "cat2": str(cat2),
                "cat3": str(cat3),
            },
        )
        await session.execute(
            text(
                "insert into public.inventory_item "
                "(id, company_id, product_id, lot_number, code, origin, cost, quantity, status) "
                "values (:id, :cid, :pid, 1, 'JOC0001-01I', 'other', 300000, 5, 'available')"
            ),
            {"id": str(item_id), "cid": str(company_id), "pid": str(product_id)},
        )
        await session.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.customer "
                "(id, company_id, full_name, doc_type, doc_number, phone) "
                "values (:id, :cid, 'Cliente Devolución', 'cc', :doc, '3000000001')"
            ),
            {"id": str(customer_id), "cid": str(company_id), "doc": "999888777"},
        )

    full_token = make_token(
        private_pem, sub=str(full_user_id), company_id=str(company_id), role_id=str(full_role_id)
    )
    override_token = make_token(
        private_pem,
        sub=str(override_user_id),
        company_id=str(company_id),
        role_id=str(override_role_id),
    )

    yield {
        "company_id": company_id,
        "product_id": product_id,
        "item_id": item_id,
        "register_id": register_id,
        "customer_id": customer_id,
        "full_token": full_token,
        "override_token": override_token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.credit_note_redemption where company_id = :cid")
    await _try_delete("delete from public.credit_note where company_id = :cid")
    await _try_delete("delete from public.sale_return_line where company_id = :cid")
    await _try_delete("delete from public.sale_return where company_id = :cid")
    await _try_delete("delete from public.sale_line where company_id = :cid")
    await _try_delete("delete from public.sale where company_id = :cid")
    await _try_delete("delete from public.inventory_entry_line where company_id = :cid")
    await _try_delete("delete from public.inventory_entry where company_id = :cid")
    await _try_delete("delete from public.cash_movement where company_id = :cid")
    await _try_delete("delete from public.account where company_id = :cid")
    await _try_delete("delete from public.customer where company_id = :cid")
    await _try_delete("delete from public.inventory_item where company_id = :cid")
    await _try_delete("delete from public.product where company_id = :cid")
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
                "(company_id, register_id, opened_by, opening_balance, status) "
                "values (:cid, :rid, :cid, 0, 'open')"
            ),
            {"cid": str(company_id), "rid": str(register_id)},
        )


def _make_sale(client: TestClient, tenant: dict, *, quantity: str = "1") -> dict:
    return client.post(
        "/api/v1/sales",
        headers=_headers(tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(tenant["customer_id"]),
            "payment_method": "cash",
            "lines": [
                {"item_id": str(tenant["item_id"]), "quantity": quantity, "unit_price": "500000.00"}
            ],
        },
    ).json()


async def test_return_path_a_reopens_same_lot_and_appears_in_kardex(
    client: TestClient, returns_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant)
    sale_line_id = sale["lines"][0]["id"]

    response = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
            "reason": "change_of_mind",
            "settlement_method": "cash",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_amount"] == "500000.00"
    assert body["lines"][0]["item_id"] == str(returns_tenant["item_id"])
    assert body["time_limit_warning"] is False

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity, status from public.inventory_item where id = :id"),
                {"id": str(returns_tenant["item_id"])},
            )
        ).first()
        out_movement = (
            await session.execute(
                text(
                    "select direction, amount from public.cash_movement "
                    "where company_id = :cid and reference_type = 'sale_return'"
                ),
                {"cid": str(returns_tenant["company_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 5  # repuesto: quedaban 4 tras vender 1, más 1 devuelto
    assert item[1] == "available"
    assert out_movement is not None
    assert out_movement[0] == "out"
    assert str(out_movement[1]) == "500000.00"

    kardex = client.get(
        f"/api/v1/inventory/products/{returns_tenant['product_id']}/kardex",
        headers=_headers(returns_tenant["full_token"]),
    )
    assert kardex.status_code == 200, kardex.text
    kinds = [line["kind"] for line in kardex.json()["lines"]]
    assert "sale_return" in kinds


async def test_return_path_b_creates_new_lot_when_original_is_gone(
    client: TestClient, returns_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant)
    sale_line_id = sale["lines"][0]["id"]

    # Simula que el remanente del lote se consumió en otro lado DESPUÉS de la
    # venta (una transformación, un ajuste): el lote original ya no puede
    # reabsorber la cantidad devuelta.
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.inventory_item set status = 'written_off' where id = :id"),
            {"id": str(returns_tenant["item_id"])},
        )

    response = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
            "reason": "defect",
            "settlement_method": "cash",
        },
    )
    assert response.status_code == 201, response.text
    new_item_id = response.json()["lines"][0]["item_id"]
    assert new_item_id != str(returns_tenant["item_id"])

    async with AsyncSessionLocal() as session, session.begin():
        new_item = (
            await session.execute(
                text(
                    "select status, source_return_id, cost, quantity "
                    "from public.inventory_item where id = :id"
                ),
                {"id": new_item_id},
            )
        ).first()
    assert new_item is not None
    assert new_item[0] == "draft"
    assert str(new_item[1]) == response.json()["id"]
    assert Decimal(str(new_item[2])) == Decimal("300000.00")  # unit_cost congelado
    assert Decimal(str(new_item[3])) == Decimal("1")

    publish = client.post(
        f"/api/v1/inventory/items/{new_item_id}/publish",
        headers=_headers(returns_tenant["full_token"]),
        json={"sale_price": "500000.00"},
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["code"].endswith("D")


async def test_return_partial_quantity_enforces_available(
    client: TestClient, returns_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant, quantity="5")
    sale_line_id = sale["lines"][0]["id"]

    first = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "2"}],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert first.status_code == 201, first.text

    too_much = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "4"}],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert too_much.status_code == 400, too_much.text
    assert too_much.json()["details"]["available"] == "3.000"

    rest = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "3"}],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert rest.status_code == 201, rest.text


async def test_return_without_restock_does_not_touch_inventory(
    client: TestClient, returns_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant)
    sale_line_id = sale["lines"][0]["id"]

    response = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "1", "restock": False}],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["lines"][0]["item_id"] is None

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity from public.inventory_item where id = :id"),
                {"id": str(returns_tenant["item_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 4  # quedaron 4 tras vender 1; la devolución NO repuso


async def test_return_idempotency_key_replays(client: TestClient, returns_tenant: dict) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant)
    sale_line_id = sale["lines"][0]["id"]
    key = str(uuid4())
    body = {
        "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
        "reason": "other",
        "settlement_method": "cash",
    }
    first = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], key),
        json=body,
    )
    second = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], key),
        json=body,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    async with AsyncSessionLocal() as session, session.begin():
        item = (
            await session.execute(
                text("select quantity from public.inventory_item where id = :id"),
                {"id": str(returns_tenant["item_id"])},
            )
        ).first()
    assert item is not None
    assert item[0] == 5  # solo se repuso una vez (4 tras vender + 1 devuelta)


async def test_return_past_time_limit_needs_override_permission(
    client: TestClient, returns_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant)
    sale_line_id = sale["lines"][0]["id"]

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.sale set sold_at = now() - interval '45 days' where id = :id"),
            {"id": sale["id"]},
        )

    body = {
        "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
        "reason": "other",
        "settlement_method": "cash",
    }
    blocked = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json=body,
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["code"] == "RETURN_TIME_LIMIT_EXCEEDED"

    allowed = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["override_token"], idempotency_key=str(uuid4())),
        json=body,
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["time_limit_warning"] is True


async def test_credit_note_issued_and_redeemed_across_two_sales(
    client: TestClient, returns_tenant: dict
) -> None:
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant)
    sale_line_id = sale["lines"][0]["id"]

    ret = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
            "reason": "other",
            "settlement_method": "credit_note",
        },
    )
    assert ret.status_code == 201, ret.text
    credit_note_id = ret.json()["credit_note_id"]
    assert credit_note_id is not None

    # Emitir NO mueve caja.
    async with AsyncSessionLocal() as session, session.begin():
        moved = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement "
                    "where company_id = :cid and reference_type = 'sale_return'"
                ),
                {"cid": str(returns_tenant["company_id"])},
            )
        ).scalar_one()
    assert moved == 0

    note = client.get(
        f"/api/v1/credit-notes/{credit_note_id}", headers=_headers(returns_tenant["full_token"])
    )
    assert note.status_code == 200
    assert note.json()["amount"] == "500000.00"
    assert note.json()["balance"] == "500000.00"

    # Redimir parcialmente en una venta nueva de 300.000: 200.000 quedan de
    # saldo y solo 300.000-200.000=200.000... redimimos 200.000, cobrando 100.000.
    partial = client.post(
        "/api/v1/sales",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(returns_tenant["customer_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "item_id": str(returns_tenant["item_id"]),
                    "quantity": "1",
                    "unit_price": "300000.00",
                }
            ],
            "credit_note_id": credit_note_id,
            "credit_note_amount": "200000.00",
        },
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["credit_note_redeemed_amount"] == "200000.00"

    async with AsyncSessionLocal() as session, session.begin():
        in_movement = (
            await session.execute(
                text(
                    "select amount from public.cash_movement "
                    "where company_id = :cid and reference_id = :sid"
                ),
                {"cid": str(returns_tenant["company_id"]), "sid": partial.json()["id"]},
            )
        ).first()
    assert in_movement is not None
    assert str(in_movement[0]) == "100000.00"  # 300.000 - 200.000 de nota

    note_after = client.get(
        f"/api/v1/credit-notes/{credit_note_id}", headers=_headers(returns_tenant["full_token"])
    )
    assert note_after.json()["balance"] == "300000.00"

    # Redimir el resto del saldo (300.000) en una segunda venta.
    final = client.post(
        "/api/v1/sales",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(returns_tenant["customer_id"]),
            "payment_method": "cash",
            "lines": [
                {
                    "item_id": str(returns_tenant["item_id"]),
                    "quantity": "1",
                    "unit_price": "300000.00",
                }
            ],
            "credit_note_id": credit_note_id,
        },
    )
    assert final.status_code == 201, final.text
    assert final.json()["credit_note_redeemed_amount"] == "300000.00"

    note_final = client.get(
        f"/api/v1/credit-notes/{credit_note_id}", headers=_headers(returns_tenant["full_token"])
    )
    assert note_final.json()["balance"] == "0.00"


async def test_cash_return_blocked_when_settlement_account_not_settled(
    client: TestClient, returns_tenant: dict
) -> None:
    account_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.account (id, company_id, name, type) "
                "values (:id, :cid, 'Sistecrédito', 'settlement')"
            ),
            {"id": str(account_id), "cid": str(returns_tenant["company_id"])},
        )

    # Venta por Sistecrédito: entra como cuenta por cobrar, sin efectivo real.
    sale = client.post(
        "/api/v1/sales",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(returns_tenant["customer_id"]),
            "payment_method": "other",
            "account_id": str(account_id),
            "lines": [
                {
                    "item_id": str(returns_tenant["item_id"]),
                    "quantity": "1",
                    "unit_price": "500000.00",
                }
            ],
        },
    ).json()
    sale_line_id = sale["lines"][0]["id"]

    blocked = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert blocked.status_code == 400, blocked.text
    assert blocked.json()["code"] == "SALE_ACCOUNT_NOT_SETTLED"

    # Nota crédito sí es válida: no hace falta que haya entrado plata real.
    allowed = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale_line_id, "quantity": "1"}],
            "reason": "other",
            "settlement_method": "credit_note",
        },
    )
    assert allowed.status_code == 201, allowed.text
