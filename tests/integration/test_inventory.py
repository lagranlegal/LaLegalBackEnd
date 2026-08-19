"""Integración de inventory (paso 7): ingresos crean ítems en draft,
publicar exige foto+precio y emite código inmutable, egresos descuentan
stock. Requiere Postgres real (se salta si no hay)."""

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
async def inventory_tenant(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict, None]:
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    company_id = uuid4()
    role_id = uuid4()
    user_id = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    supplier_id = uuid4()
    codes = ("inventory.view", "inventory.create", "inventory.exit")

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("insert into public.company (id, name) values (:id, 'Empresa inventory-test')"),
            {"id": str(company_id)},
        )
        await session.execute(
            text("insert into public.role (id, company_id, name) values (:id, :cid, 'Bodega')"),
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
                "values (:id, :cid, :role_id, 'Bodega Test', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(company_id),
                "role_id": str(role_id),
                "email": f"bodega-{user_id}@example.com",
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
                "insert into public.supplier (id, company_id, name, code_letter) "
                "values (:id, :cid, 'Proveedor Uno', 'I')"
            ),
            {"id": str(supplier_id), "cid": str(company_id)},
        )

    token = make_token(
        private_pem, sub=str(user_id), company_id=str(company_id), role_id=str(role_id)
    )

    yield {
        "company_id": company_id,
        "cat1": cat1,
        "cat2": cat2,
        "cat3": cat3,
        "supplier_id": supplier_id,
        "token": token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    await _try_delete("delete from public.inventory_entry_line where company_id = :cid")
    await _try_delete("delete from public.inventory_exit_line where company_id = :cid")
    await _try_delete("delete from public.inventory_entry where company_id = :cid")
    await _try_delete("delete from public.inventory_exit where company_id = :cid")
    await _try_delete("delete from public.inventory_item where company_id = :cid")
    await _try_delete("delete from public.code_counter where company_id = :cid")
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


def _entry_payload(tenant: dict, **overrides: object) -> dict:
    base = {
        "origin_type": "purchase",
        "supplier_id": str(tenant["supplier_id"]),
        "lines": [
            {
                "name": "Cadena de oro 10g",
                "cat1_id": str(tenant["cat1"]),
                "cat2_id": str(tenant["cat2"]),
                "cat3_id": str(tenant["cat3"]),
                "unit_cost": "500000.00",
                "quantity": 1,
            }
        ],
    }
    base.update(overrides)
    return base


def test_create_entry_creates_draft_items(client: TestClient, inventory_tenant: dict) -> None:
    response = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(inventory_tenant["token"]),
        json=_entry_payload(inventory_tenant),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_cost"] == "500000.00"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["status"] == "draft"
    assert item["code"] is None
    assert item["cost"] == "500000.00"


def test_purchase_entry_without_supplier_is_rejected(
    client: TestClient, inventory_tenant: dict
) -> None:
    payload = _entry_payload(inventory_tenant)
    del payload["supplier_id"]
    response = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert response.status_code == 400


def test_publish_requires_photo(client: TestClient, inventory_tenant: dict) -> None:
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    ).json()
    item_id = entry["items"][0]["id"]

    without_photo = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=headers,
        json={"sale_price": "650000.00"},
    )
    assert without_photo.status_code == 400

    client.patch(
        f"/api/v1/inventory/items/{item_id}",
        headers=headers,
        json={"photos": ["https://example.com/foto.jpg"]},
    )
    published = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=headers,
        json={"sale_price": "650000.00"},
    )
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "available"
    assert body["code"] == "JOC0001I"


def test_cannot_edit_item_after_publish(client: TestClient, inventory_tenant: dict) -> None:
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=headers,
        json=_entry_payload(
            inventory_tenant,
            lines=[
                {
                    "name": "Cadena",
                    "cat1_id": str(inventory_tenant["cat1"]),
                    "cat2_id": str(inventory_tenant["cat2"]),
                    "cat3_id": str(inventory_tenant["cat3"]),
                    "unit_cost": "500000.00",
                    "quantity": 1,
                    "photos": ["https://example.com/foto.jpg"],
                }
            ],
        ),
    ).json()
    item_id = entry["items"][0]["id"]
    client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=headers,
        json={"sale_price": "650000.00"},
    )

    response = client.patch(
        f"/api/v1/inventory/items/{item_id}", headers=headers, json={"name": "Otro nombre"}
    )
    assert response.status_code == 409


async def test_update_item_can_correct_category_while_draft(
    client: TestClient, inventory_tenant: dict
) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #17: un artículo de remate hereda
    la categoría de la prenda del contrato, que puede no ser la correcta
    para vender en tienda — debe poder corregirse mientras sigue en draft."""
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    ).json()
    item_id = entry["items"][0]["id"]

    # Segunda rama de categorías nivel 1->2->3 para mover el artículo.
    company_id = inventory_tenant["company_id"]
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
                "insert into public.category (id, company_id, parent_id, level, name, code_letter) "
                "values (:id, :cid, :parent, 3, 'Smartphone', 'S')"
            ),
            {"id": str(tech3), "cid": str(company_id), "parent": str(tech2)},
        )

    partial = client.patch(
        f"/api/v1/inventory/items/{item_id}",
        headers=headers,
        json={"cat1_id": str(tech1)},
    )
    assert partial.status_code == 400

    response = client.patch(
        f"/api/v1/inventory/items/{item_id}",
        headers=headers,
        json={"cat1_id": str(tech1), "cat2_id": str(tech2), "cat3_id": str(tech3)},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cat1_id"] == str(tech1)
    assert body["cat2_id"] == str(tech2)
    assert body["cat3_id"] == str(tech3)

    published = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=headers,
        json={"sale_price": "650000.00"},
    )
    assert published.status_code == 400  # sin foto todavía, la categoría no lo evita

    client.patch(
        f"/api/v1/inventory/items/{item_id}",
        headers=headers,
        json={"photos": ["https://example.com/foto.jpg"]},
    )
    republished = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=headers,
        json={"sale_price": "650000.00"},
    )
    assert republished.status_code == 200, republished.text
    assert republished.json()["code"].startswith("TES")
    # Limpieza: inventory_tenant borra categorías por company_id+level en su
    # teardown (después de borrar inventory_item, que ya referencia estas
    # categorías) — no hace falta borrar tech1/tech2/tech3 acá.


def test_exit_reduces_stock_and_writes_off_at_zero(
    client: TestClient, inventory_tenant: dict
) -> None:
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=headers,
        json=_entry_payload(
            inventory_tenant,
            lines=[
                {
                    "name": "Cadena",
                    "cat1_id": str(inventory_tenant["cat1"]),
                    "cat2_id": str(inventory_tenant["cat2"]),
                    "cat3_id": str(inventory_tenant["cat3"]),
                    "unit_cost": "500000.00",
                    "quantity": 2,
                }
            ],
        ),
    ).json()
    item_id = entry["items"][0]["id"]

    exit_resp = client.post(
        "/api/v1/inventory/exits",
        headers=headers,
        json={
            "exit_type": "damage",
            "reason": "se dañó en bodega",
            "lines": [{"item_id": item_id, "quantity": 2}],
        },
    )
    assert exit_resp.status_code == 201, exit_resp.text

    item = client.get(f"/api/v1/inventory/items/{item_id}", headers=headers).json()
    assert item["quantity"] == 0
    assert item["status"] == "written_off"

    exits_list = client.get("/api/v1/inventory/exits", headers=headers)
    assert exits_list.status_code == 200
    assert len(exits_list.json()["items"]) == 1


def test_exit_insufficient_stock_is_rejected(client: TestClient, inventory_tenant: dict) -> None:
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    ).json()
    item_id = entry["items"][0]["id"]

    response = client.post(
        "/api/v1/inventory/exits",
        headers=headers,
        json={
            "exit_type": "adjustment",
            "reason": "ajuste de conteo",
            "lines": [{"item_id": item_id, "quantity": 5}],
        },
    )
    assert response.status_code == 400
