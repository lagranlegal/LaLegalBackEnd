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
        "sales.apply_discount",
        "inventory.view",
        "inventory.create",
        "reports.view",
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


# =========================================================================
# F21-31 — Anular una venta que ya tiene devoluciones.
#
# El defecto: `void_sale` reponía TODAS las líneas y emitía el
# contra-movimiento por el `total` entero, sin mirar si parte de la venta ya
# se había devuelto y liquidado. Anular una venta parcialmente devuelta
# duplicaba el stock de lo devuelto y le devolvía la plata al cliente dos
# veces.
#
# La decisión es RECHAZAR, no anular el remanente (ver el comentario largo
# en `service.void_sale`). Estos tests fijan las dos mitades: que el camino
# normal —anular una venta sin devoluciones— siga intacto, y que con
# devoluciones se rechace con su propio código.
# =========================================================================


async def _sale_snapshot(company_id, sale_id) -> tuple[str, int, int]:
    """Estado de la venta, cantidad del lote y cuántos contra-movimientos de
    anulación existen. Lo que el defecto tocaba."""
    async with AsyncSessionLocal() as session, session.begin():
        status = (
            await session.execute(
                text("select status from public.sale where id = :id"), {"id": str(sale_id)}
            )
        ).scalar_one()
        quantity = (
            await session.execute(
                text(
                    "select quantity from public.inventory_item "
                    "where company_id = :cid order by created_at limit 1"
                ),
                {"cid": str(company_id)},
            )
        ).scalar_one()
        voids = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement where company_id = :cid "
                    "and reference_type = 'sale' and direction = 'out'"
                ),
                {"cid": str(company_id)},
            )
        ).scalar_one()
    return status, quantity, voids


async def test_void_sin_devoluciones_sigue_reponiendo_todo(
    client: TestClient, returns_tenant: dict
) -> None:
    """El camino normal no se puede romper: sin devoluciones, anular repone
    el stock completo y emite su contra-movimiento."""
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant, quantity="2")

    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=_headers(returns_tenant["full_token"]),
        json={"reason": "error de digitación"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "voided"

    status, quantity, voids = await _sale_snapshot(returns_tenant["company_id"], sale["id"])
    assert status == "voided"
    assert quantity == 5  # 5 − 2 vendidas + 2 repuestas
    assert voids == 1


async def test_void_bloqueado_si_la_venta_tiene_una_devolucion_parcial(
    client: TestClient, returns_tenant: dict
) -> None:
    """El caso del defecto: 2 vendidas, 1 devuelta y reingresada.

    Con el código anterior la anulación pasaba (200), reponía las 2 líneas
    —dejando el lote en 6 sobre un stock inicial de 5— y sacaba de caja los
    1.000.000 enteros habiéndole pagado ya 500.000 al cliente.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant, quantity="2")
    devolucion = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
            "reason": "defect",
            "settlement_method": "cash",
        },
    )
    assert devolucion.status_code == 201, devolucion.text

    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=_headers(returns_tenant["full_token"]),
        json={"reason": "el dueño quiere borrarla"},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    # El CÓDIGO, no el status: es lo que el front escucha para decir qué hacer.
    assert body["code"] == "SALE_HAS_RETURNS"
    assert body["details"]["return_count"] == 1
    assert body["details"]["return_numbers"] == [devolucion.json()["number"]]
    assert body["details"]["return_ids"] == [devolucion.json()["id"]]
    # El mensaje nombra la acción que falta, no solo niega la intentada.
    assert "devolución" in body["message"]

    # Y nada se movió: ni el estado, ni el stock, ni la caja.
    status, quantity, voids = await _sale_snapshot(returns_tenant["company_id"], sale["id"])
    assert status == "completed"
    assert quantity == 4  # 5 − 2 vendidas + 1 devuelta
    assert voids == 0


async def test_void_bloqueado_si_la_venta_esta_totalmente_devuelta(
    client: TestClient, returns_tenant: dict
) -> None:
    """Devuelta al 100 % tampoco se anula: la nota crédito ya se emitió y
    puede estar redimida en otra venta."""
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    sale = _make_sale(client, returns_tenant, quantity="1")
    devolucion = client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": "1"}],
            "reason": "change_of_mind",
            "settlement_method": "credit_note",
        },
    )
    assert devolucion.status_code == 201, devolucion.text

    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=_headers(returns_tenant["full_token"]),
        json={"reason": "igual la quiero anular"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "SALE_HAS_RETURNS"
    assert response.json()["details"]["return_count"] == 1

    status, quantity, voids = await _sale_snapshot(returns_tenant["company_id"], sale["id"])
    assert status == "completed"
    assert quantity == 5  # 5 − 1 vendida + 1 devuelta
    assert voids == 0


# --- F21-36: una venta pagada con nota crédito no se anula ------------------
#
# El defecto: `void_sale` sacaba del cajón el `total` entero, incluida la
# parte que se pagó con una nota crédito y que nunca entró a la caja, y la
# redención quedaba en pie. Se RECHAZA, con el mismo molde que F21-31.


def _nota_credito_de(client: TestClient, tenant: dict) -> dict:
    """Vende 1 unidad a 500.000 y la devuelve en nota crédito: deja una nota
    de 500.000 a nombre del cliente y el lote otra vez en 5."""
    original = _make_sale(client, tenant)
    ret = client.post(
        f"/api/v1/sales/{original['id']}/returns",
        headers=_headers(tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": original["lines"][0]["id"], "quantity": "1"}],
            "reason": "other",
            "settlement_method": "credit_note",
        },
    )
    assert ret.status_code == 201, ret.text
    note = client.get(
        f"/api/v1/credit-notes/{ret.json()['credit_note_id']}",
        headers=_headers(tenant["full_token"]),
    )
    assert note.status_code == 200, note.text
    return note.json()


def _venta_con_nota(
    client: TestClient, tenant: dict, *, note_id: str, unit_price: str, note_amount: str
) -> dict:
    response = client.post(
        "/api/v1/sales",
        headers=_headers(tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(tenant["customer_id"]),
            "payment_method": "cash",
            "lines": [
                {"item_id": str(tenant["item_id"]), "quantity": "1", "unit_price": unit_price}
            ],
            "credit_note_id": note_id,
            "credit_note_amount": note_amount,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_void_bloqueado_si_la_venta_se_pago_en_parte_con_nota_credito(
    client: TestClient, returns_tenant: dict
) -> None:
    """El caso del defecto, con los números del hallazgo: venta de 800.000 =
    500.000 de nota + 300.000 en efectivo.

    Con el código anterior la anulación pasaba (200) y sacaba 800.000 del
    cajón habiendo entrado 300.000, con la nota todavía redimida.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    note = _nota_credito_de(client, returns_tenant)
    sale = _venta_con_nota(
        client,
        returns_tenant,
        note_id=note["id"],
        unit_price="800000.00",
        note_amount="500000.00",
    )
    assert sale["credit_note_redeemed_amount"] == "500000.00"

    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=_headers(returns_tenant["full_token"]),
        json={"reason": "error de digitación"},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    # El CÓDIGO, no el status: `CONFLICT` a secas es «ya está anulada».
    assert body["code"] == "SALE_PAID_WITH_CREDIT_NOTE"
    assert body["details"] == {
        "credit_note_id": note["id"],
        "credit_note_number": note["number"],
        "redeemed_amount": "500000.00",
    }
    # El mensaje nombra la nota y la salida, no solo niega.
    assert f"Nº {note['number']}" in body["message"]
    assert "devolución" in body["message"]

    # Y nada se movió: ni el estado, ni el stock, ni la caja, ni la nota.
    status, quantity, voids = await _sale_snapshot(returns_tenant["company_id"], sale["id"])
    assert status == "completed"
    assert quantity == 4  # 5 − 1 vendida con la nota
    assert voids == 0
    after = client.get(
        f"/api/v1/credit-notes/{note['id']}", headers=_headers(returns_tenant["full_token"])
    )
    assert after.json()["balance"] == "0.00"


async def test_void_bloqueado_si_la_nota_credito_cubrio_toda_la_venta(
    client: TestClient, returns_tenant: dict
) -> None:
    """El extremo del mismo defecto: la nota pagó todo, al cajón no entró
    nada, y anular habría sacado el total entero."""
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    note = _nota_credito_de(client, returns_tenant)
    sale = _venta_con_nota(
        client,
        returns_tenant,
        note_id=note["id"],
        unit_price="400000.00",
        note_amount="400000.00",
    )

    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=_headers(returns_tenant["full_token"]),
        json={"reason": "error de digitación"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "SALE_PAID_WITH_CREDIT_NOTE"
    assert response.json()["details"]["redeemed_amount"] == "400000.00"

    status, _, voids = await _sale_snapshot(returns_tenant["company_id"], sale["id"])
    assert status == "completed"
    assert voids == 0


async def test_void_de_una_venta_sin_nota_sigue_devolviendo_el_total(
    client: TestClient, returns_tenant: dict
) -> None:
    """La guarda mira la VENTA, no al cliente: el mismo cliente con una nota
    viva anula como siempre una venta que pagó sin ella, y el
    contra-movimiento sale por el total."""
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    note = _nota_credito_de(client, returns_tenant)
    assert note["balance"] == "500000.00"
    sale = _make_sale(client, returns_tenant)

    response = client.post(
        f"/api/v1/sales/{sale['id']}/void",
        headers=_headers(returns_tenant["full_token"]),
        json={"reason": "cobro doble"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "voided"

    async with AsyncSessionLocal() as session, session.begin():
        salida = (
            await session.execute(
                text(
                    "select amount from public.cash_movement where company_id = :cid "
                    "and reference_id = :sid and direction = 'out'"
                ),
                {"cid": str(returns_tenant["company_id"]), "sid": sale["id"]},
            )
        ).scalar_one()
    assert str(salida) == "500000.00"
    status, quantity, _ = await _sale_snapshot(returns_tenant["company_id"], sale["id"])
    assert status == "voided"
    assert quantity == 5  # 5 − 1 vendida + 1 repuesta


# --- F21-17: el listado de ventas trae lo devuelto -------------------------


def _list_sales_by_id(client: TestClient, tenant: dict) -> dict[str, dict]:
    response = client.get("/api/v1/sales?limit=200", headers=_headers(tenant["full_token"]))
    assert response.status_code == 200, response.text
    return {s["id"]: s for s in response.json()["items"]}


async def test_listado_de_ventas_trae_lo_devuelto_neto_del_descuento_prorrateado(
    client: TestClient, returns_tenant: dict
) -> None:
    """F21-17: el Excel de Ventas no tenía cómo mostrar devoluciones porque el
    listado no traía nada de ellas (`sale.status` sigue en `completed`).

    Venta de 2 × 500.000 con 100.000 de descuento (total 900.000). Se
    devuelve 1 unidad con nota crédito y la otra en efectivo: lo devuelto se
    mide con la MISMA expresión que `profit_summary` —bruto de la línea menos
    su parte del descuento por participación en el bruto—, así que cada
    unidad vale 450.000 y la venta totalmente devuelta suma 900.000 = su
    `total`. La devolución con nota crédito no emite `cash_movement`: por eso
    el dato no podía salir de la caja.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    con_descuento = client.post(
        "/api/v1/sales",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(returns_tenant["customer_id"]),
            "payment_method": "cash",
            "discount_amount": "100000.00",
            "discount_reason": "cliente frecuente",
            "lines": [
                {
                    "item_id": str(returns_tenant["item_id"]),
                    "quantity": "2",
                    "unit_price": "500000.00",
                }
            ],
        },
    )
    assert con_descuento.status_code == 201, con_descuento.text
    venta = con_descuento.json()
    assert venta["total"] == "900000.00"
    # Una venta recién creada no tiene devoluciones.
    assert venta["returned_amount"] == "0.00"
    sin_devolucion = _make_sale(client, returns_tenant)

    primera = client.post(
        f"/api/v1/sales/{venta['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": venta["lines"][0]["id"], "quantity": "1"}],
            "reason": "defect",
            "settlement_method": "credit_note",
        },
    )
    assert primera.status_code == 201, primera.text

    listado = _list_sales_by_id(client, returns_tenant)
    # Parcial: 500.000 − 50.000 de descuento prorrateado, no el bruto.
    assert listado[venta["id"]]["returned_amount"] == "450000.00"
    assert listado[sin_devolucion["id"]]["returned_amount"] == "0.00"
    # El estado NO cambia: la columna nueva es lo que deja ver la devolución.
    assert listado[venta["id"]]["status"] == "completed"

    segunda = client.post(
        f"/api/v1/sales/{venta['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": venta["lines"][0]["id"], "quantity": "1"}],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert segunda.status_code == 201, segunda.text

    listado = _list_sales_by_id(client, returns_tenant)
    # Dos devoluciones de la misma venta se suman; total devuelto = total.
    assert listado[venta["id"]]["returned_amount"] == "900000.00"
    # Y el detalle dice lo mismo que el listado.
    detalle = client.get(
        f"/api/v1/sales/{venta['id']}", headers=_headers(returns_tenant["full_token"])
    )
    assert detalle.status_code == 200, detalle.text
    assert detalle.json()["returned_amount"] == "900000.00"


async def test_listado_de_ventas_trae_la_nota_credito_redimida(
    client: TestClient, returns_tenant: dict
) -> None:
    """La columna «Nota crédito redimida» del Excel de Ventas salía SIEMPRE
    vacía: `list_sales` llamaba a `_row_to_sale` sin ese dato (default
    `None`), aunque `create_sale` y `get_sale` sí lo llenaban.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    original = _make_sale(client, returns_tenant)
    ret = client.post(
        f"/api/v1/sales/{original['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": original["lines"][0]["id"], "quantity": "1"}],
            "reason": "other",
            "settlement_method": "credit_note",
        },
    )
    assert ret.status_code == 201, ret.text
    redime = client.post(
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
            "credit_note_id": ret.json()["credit_note_id"],
            "credit_note_amount": "200000.00",
        },
    )
    assert redime.status_code == 201, redime.text

    listado = _list_sales_by_id(client, returns_tenant)
    assert listado[redime.json()["id"]]["credit_note_redeemed_amount"] == "200000.00"
    # `None` sigue significando «no se usó nota», distinto de 0.
    assert listado[original["id"]]["credit_note_redeemed_amount"] is None


# --- F21-33: la devolución liquida lo PAGADO, no el bruto -------------------


def _make_discounted_sale(
    client: TestClient, tenant: dict, *, quantity: str, unit_price: str, discount: str
) -> dict:
    response = client.post(
        "/api/v1/sales",
        headers=_headers(tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "customer_id": str(tenant["customer_id"]),
            "payment_method": "cash",
            "discount_amount": discount,
            "discount_reason": "cliente frecuente",
            "lines": [
                {"item_id": str(tenant["item_id"]), "quantity": quantity, "unit_price": unit_price}
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _return(
    client: TestClient, tenant: dict, sale: dict, *, quantity: str, settlement: str = "cash"
):
    return client.post(
        f"/api/v1/sales/{sale['id']}/returns",
        headers=_headers(tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [{"sale_line_id": sale["lines"][0]["id"], "quantity": quantity}],
            "reason": "other",
            "settlement_method": settlement,
        },
    )


async def _return_settlements(company_id, return_id: str) -> tuple[str | None, str | None, str]:
    """(egreso de caja, nota crédito, `total_amount` auditado) de UNA devolución."""
    async with AsyncSessionLocal() as session, session.begin():
        cash = (
            await session.execute(
                text(
                    "select amount from public.cash_movement where company_id = :cid "
                    "and reference_type = 'sale_return' and reference_id = :rid"
                ),
                {"cid": str(company_id), "rid": return_id},
            )
        ).scalar_one_or_none()
        note = (
            await session.execute(
                text(
                    "select amount from public.credit_note where company_id = :cid "
                    "and sale_return_id = :rid"
                ),
                {"cid": str(company_id), "rid": return_id},
            )
        ).scalar_one_or_none()
        audited = (
            await session.execute(
                text(
                    "select after->>'total_amount' from public.audit_log where company_id = :cid "
                    "and action = 'create_return' and entity_id = :rid"
                ),
                {"cid": str(company_id), "rid": return_id},
            )
        ).scalar_one()
    return (
        str(cash) if cash is not None else None,
        str(note) if note is not None else None,
        audited,
    )


async def test_devolucion_total_de_venta_con_descuento_liquida_lo_pagado(
    client: TestClient, returns_tenant: dict
) -> None:
    """F21-33: venta de 900.000 (2 × 500.000 − 100.000 de descuento) devuelta
    completa. Liquidaba 1.000.000 —el bruto—: 100.000 salían del cajón (o
    quedaban como nota crédito redimible) sin haber entrado nunca. Ahora el
    cliente recibe lo que pagó, en efectivo y en nota crédito, y la
    liquidación, la auditoría, la respuesta y «Devuelto» son el mismo número.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    for settlement in ("cash", "credit_note"):
        venta = _make_discounted_sale(
            client, returns_tenant, quantity="2", unit_price="500000.00", discount="100000.00"
        )
        assert venta["total"] == "900000.00"

        ret = _return(client, returns_tenant, venta, quantity="2", settlement=settlement)
        assert ret.status_code == 201, ret.text
        assert ret.json()["total_amount"] == "900000.00"

        cash, note, audited = await _return_settlements(
            returns_tenant["company_id"], ret.json()["id"]
        )
        assert (cash if settlement == "cash" else note) == "900000.00"
        assert audited == "900000.00"

        # El detalle de la devolución (recibo) y el de la venta coinciden.
        listado = client.get(
            f"/api/v1/sales/{venta['id']}/returns", headers=_headers(returns_tenant["full_token"])
        )
        assert listado.status_code == 200, listado.text
        assert [r["total_amount"] for r in listado.json()] == ["900000.00"]
        detalle = client.get(
            f"/api/v1/sales/{venta['id']}", headers=_headers(returns_tenant["full_token"])
        )
        assert detalle.json()["returned_amount"] == "900000.00"


async def test_devoluciones_parciales_con_redondeo_cierran_exacto_en_el_total(
    client: TestClient, returns_tenant: dict
) -> None:
    """F21-33, el caso del redondeo: 3 × 333.333,33 (bruto 999.999,99) con
    100.000 de descuento → total 899.999,99. El descuento por unidad es
    33.333,333…, que redondeado POR LÍNEA da 33.333,33 cada vez: tres
    devoluciones de 300.000,00 sumarían 900.000,00 — UN centavo más de lo
    que el cliente pagó.

    La regla: cada devolución liquida la diferencia entre lo devuelto
    ACUMULADO después de ella y antes de ella, redondeando el acumulado. La
    suma telescopa, así que nunca supera lo pagado y la que agota la venta
    se lleva el residuo: 300.000,00 + 299.999,99 + 300.000,00 = 899.999,99.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    venta = _make_discounted_sale(
        client, returns_tenant, quantity="3", unit_price="333333.33", discount="100000.00"
    )
    assert venta["total"] == "899999.99"

    liquidado: list[Decimal] = []
    for esperado in ("300000.00", "299999.99", "300000.00"):
        ret = _return(client, returns_tenant, venta, quantity="1")
        assert ret.status_code == 201, ret.text
        assert ret.json()["total_amount"] == esperado
        cash, _, _ = await _return_settlements(returns_tenant["company_id"], ret.json()["id"])
        assert cash == esperado
        liquidado.append(Decimal(esperado))
        # En NINGÚN punto lo liquidado supera lo pagado.
        assert sum(liquidado) <= Decimal(venta["total"])

    assert sum(liquidado) == Decimal("899999.99")
    detalle = client.get(
        f"/api/v1/sales/{venta['id']}", headers=_headers(returns_tenant["full_token"])
    )
    assert detalle.json()["returned_amount"] == "899999.99"
    # Y releer las devoluciones no cambia lo que ya se liquidó.
    releidas = client.get(
        f"/api/v1/sales/{venta['id']}/returns", headers=_headers(returns_tenant["full_token"])
    )
    assert [r["total_amount"] for r in releidas.json()] == ["300000.00", "299999.99", "300000.00"]

    # El contra-ingreso del Estado de resultados es el MISMO número: la venta
    # entró y salió entera el mismo día, así que el ingreso neto queda en 0.
    hoy = releidas.json()[0]["return_date"]
    profit = client.get(
        "/api/v1/reports/profit",
        params={"from_date": hoy, "to_date": hoy},
        headers=_headers(returns_tenant["full_token"]),
    )
    assert profit.status_code == 200, profit.text
    assert profit.json()["sales_returns"] == "899999.99"
    assert Decimal(profit.json()["net_revenue"]) == 0
    series = client.get(
        "/api/v1/reports/series",
        params={"months": 1},
        headers=_headers(returns_tenant["full_token"]),
    )
    assert series.status_code == 200, series.text
    assert Decimal(series.json()["points"][-1]["sales_returns"]) == Decimal("899999.99")


async def test_una_devolucion_no_puede_repetir_la_linea_para_pasarse_de_lo_vendido(
    client: TestClient, returns_tenant: dict
) -> None:
    """F21-33, visto al revisar la validación de cantidad: cada línea del
    cuerpo se comparaba contra lo devuelto EN LA BASE, sin sumar las otras
    líneas de la misma petición. Repitiendo la línea se devolvía (y se
    liquidaba) el doble de lo vendido.
    """
    await _open_cash_session(
        company_id=returns_tenant["company_id"], register_id=returns_tenant["register_id"]
    )
    venta = _make_sale(client, returns_tenant)
    line_id = venta["lines"][0]["id"]
    ret = client.post(
        f"/api/v1/sales/{venta['id']}/returns",
        headers=_headers(returns_tenant["full_token"], idempotency_key=str(uuid4())),
        json={
            "lines": [
                {"sale_line_id": line_id, "quantity": "1"},
                {"sale_line_id": line_id, "quantity": "1"},
            ],
            "reason": "other",
            "settlement_method": "cash",
        },
    )
    assert ret.status_code == 400, ret.text
    # Lo que le queda a la REPETICIÓN, ya descontada la primera.
    assert ret.json()["details"]["available"] == "0.000"
