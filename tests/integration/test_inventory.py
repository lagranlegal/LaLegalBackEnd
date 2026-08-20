"""Integración de inventory (paso 7): ingresos crean ítems en draft,
publicar exige foto+precio y emite código inmutable, egresos descuentan
stock, y la compra a proveedor sale por caja (concepto `purchase`).
Requiere Postgres real (se salta si no hay)."""

from collections.abc import AsyncGenerator
from datetime import date, timedelta
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


def _headers(token: str) -> dict[str, str]:
    # `POST /entries` exige Idempotency-Key desde 00014 (una compra es una
    # operación de dinero). Cada llamada lleva una key nueva salvo que el test
    # quiera probar el reintento a propósito.
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}


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
    register_id = uuid4()
    session_id = uuid4()
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
        # Caja abierta: desde 00014 una compra a proveedor la exige (entrega
        # plata, igual que una venta o un abono). Los tests de ingreso 'other'
        # y de egreso no dependen de ella.
        await session.execute(
            text(
                "insert into public.cash_register (id, company_id, name) "
                "values (:id, :cid, 'Caja principal')"
            ),
            {"id": str(register_id), "cid": str(company_id)},
        )
        await session.execute(
            text(
                "insert into public.cash_session "
                "(id, company_id, register_id, opened_by, opening_balance, status) "
                "values (:id, :cid, :rid, :uid, 1000000.00, 'open')"
            ),
            {
                "id": str(session_id),
                "cid": str(company_id),
                "rid": str(register_id),
                "uid": str(user_id),
            },
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
        "register_id": register_id,
        "session_id": session_id,
        "token": token,
    }

    async def _try_delete(sql: str) -> None:
        try:
            async with AsyncSessionLocal() as session, session.begin():
                await session.execute(text(sql), {"cid": str(company_id)})
        except Exception:
            pass

    # cash_movement -> cash_session -> cash_register, y el movimiento
    # referencia el inventory_entry: se borra antes que ambos.
    await _try_delete("delete from public.cash_movement where company_id = :cid")
    await _try_delete("delete from public.cash_session where company_id = :cid")
    await _try_delete("delete from public.cash_register where company_id = :cid")
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
        "payment_method": "cash",
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


async def _close_session(tenant: dict) -> None:
    """Cierra la sesión del fixture con SQL directo — el objetivo es probar el
    comportamiento sin caja abierta, no el flujo de cierre."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.cash_session set status = 'closed' where id = :sid"),
            {"sid": str(tenant["session_id"])},
        )


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


@pytest.mark.asyncio
async def test_purchase_records_cash_movement(client: TestClient, inventory_tenant: dict) -> None:
    """El hueco que arregla 00014: la plata entregada al proveedor tiene que
    salir por caja. Sin esto `expected_cash` ignoraba la compra y el cierre
    descuadraba por el monto exacto de la mercancía comprada.
    """
    response = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(inventory_tenant["token"]),
        json=_entry_payload(inventory_tenant),
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["payment_method"] == "cash"

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "select module, direction, concept, amount, payment_method, session_id "
                    "from public.cash_movement "
                    "where company_id = :cid and reference_type = 'inventory_entry' "
                    "and reference_id = :eid"
                ),
                {"cid": str(inventory_tenant["company_id"]), "eid": entry["id"]},
            )
        ).one()

    assert row.module == "store"
    assert row.direction == "out"
    assert row.concept == "purchase"
    assert row.amount == Decimal("500000.00")
    assert row.payment_method == "cash"
    # Cae en la sesión abierta de la empresa, no en una cualquiera.
    assert row.session_id == inventory_tenant["session_id"]


def test_only_a_purchase_can_carry_a_payment_method(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Reemplaza a `test_purchase_without_payment_method_is_rejected`: desde
    00020 una compra SÍ puede nacer sin medio de pago (queda pendiente). Lo que
    sigue sin tener sentido es lo inverso — un ingreso que no es compra con
    medio de pago sería un remate o un ajuste con egreso de caja, que nadie
    sabría interpretar en el acta."""
    payload = _entry_payload(inventory_tenant, origin_type="other")
    del payload["supplier_id"]
    response = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert response.status_code == 400


def test_entry_requires_idempotency_key(client: TestClient, inventory_tenant: dict) -> None:
    """CLAUDE.md regla 4 — antes de 00014 un doble click duplicaba el ingreso,
    el stock y el costo, sin DELETE con el cual deshacerlo."""
    response = client.post(
        "/api/v1/inventory/entries",
        headers={"Authorization": f"Bearer {inventory_tenant['token']}"},
        json=_entry_payload(inventory_tenant),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "IDEMPOTENCY_KEY_REQUIRED"


@pytest.mark.asyncio
async def test_repeated_idempotency_key_does_not_duplicate_entry(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El doble click devuelve el MISMO ingreso, no uno nuevo — y sobre todo
    no saca la plata de la caja dos veces."""
    headers = _headers(inventory_tenant["token"])  # misma key en los dos POST
    first = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    )
    assert first.status_code == 201, first.text
    second = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["number"] == first.json()["number"]

    async with AsyncSessionLocal() as session:
        movements = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement "
                    "where company_id = :cid and concept = 'purchase'"
                ),
                {"cid": str(inventory_tenant["company_id"])},
            )
        ).scalar_one()
        items = (
            await session.execute(
                text("select count(*) from public.inventory_item where company_id = :cid"),
                {"cid": str(inventory_tenant["company_id"])},
            )
        ).scalar_one()
    assert movements == 1
    assert items == 1


@pytest.mark.asyncio
async def test_purchase_without_open_session_is_rejected(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Misma regla que ya tenían ventas y abonos: sin caja abierta no hay
    operación de dinero. Un ingreso de compra ahora cuenta como tal."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.cash_session set status = 'closed' where id = :sid"),
            {"sid": str(inventory_tenant["session_id"])},
        )

    response = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(inventory_tenant["token"]),
        json=_entry_payload(inventory_tenant),
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CASH_SESSION_NOT_OPEN"


@pytest.mark.asyncio
async def test_non_purchase_entry_does_not_touch_cashbox(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Un ingreso 'other' (ajuste, sobrante) no entrega plata a nadie: no
    exige caja abierta ni genera movimiento — el mismo criterio por el que un
    remate tampoco lo hace (ahí el capital ya salió como préstamo)."""
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.cash_session set status = 'closed' where id = :sid"),
            {"sid": str(inventory_tenant["session_id"])},
        )

    payload = _entry_payload(inventory_tenant, origin_type="other")
    del payload["supplier_id"]
    del payload["payment_method"]
    response = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert response.status_code == 201, response.text
    assert response.json()["payment_method"] is None

    async with AsyncSessionLocal() as session:
        count = (
            await session.execute(
                text(
                    "select count(*) from public.cash_movement "
                    "where company_id = :cid and reference_type = 'inventory_entry'"
                ),
                {"cid": str(inventory_tenant["company_id"])},
            )
        ).scalar_one()
    assert count == 0


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
    # Formato nuevo desde 00021: `{SKU}-{lote}{proveedor}`. El SKU (`JOC0001`)
    # identifica el PRODUCTO y se comparte entre todos sus lotes; el sufijo
    # dice qué lote es y a quién se le compró. El esquema anterior
    # (`JOC0001I`) no perdía nada de eso — simplemente no podía expresar a qué
    # producto pertenecía la pieza, que era el problema.
    assert body["code"] == "JOC0001-01I"
    assert body["lot_number"] == 1
    assert body["product_id"] is not None


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


# ---- Búsqueda y filtros de artículos (docs/PENDIENTES_BACKEND_INFRA.md #2 del
# lado de inventario: el mostrador busca por el código impreso en la etiqueta).


def _entry_with(tenant: dict, name: str, **line_overrides: object) -> dict:
    return _entry_payload(
        tenant,
        lines=[
            {
                "name": name,
                "cat1_id": str(tenant["cat1"]),
                "cat2_id": str(tenant["cat2"]),
                "cat3_id": str(tenant["cat3"]),
                "unit_cost": "500000.00",
                "quantity": 1,
                **line_overrides,
            }
        ],
    )


def _search(client: TestClient, token: str, **params: object) -> list[dict]:
    response = client.get(
        "/api/v1/inventory/items",
        headers={"Authorization": f"Bearer {token}"},
        params=params,
    )
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def test_search_items_by_name_fulltext(client: TestClient, inventory_tenant: dict) -> None:
    token = inventory_tenant["token"]
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena de oro 18k"),
    )
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Anillo de plata"),
    )

    # Fragmento suelto y sin tilde: el full-text en español lo resuelve.
    names = [i["name"] for i in _search(client, token, q="cadena")]
    assert names == ["Cadena de oro 18k"]

    assert [i["name"] for i in _search(client, token, q="anillo")] == ["Anillo de plata"]


def test_search_items_by_code_prefix_case_insensitive(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El caso real del mostrador: el vendedor lee el código de la etiqueta."""
    token = inventory_tenant["token"]
    headers = _headers(token)
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=headers,
        json=_entry_with(inventory_tenant, "Cadena publicable", photos=["https://x/f.jpg"]),
    ).json()
    published = client.post(
        f"/api/v1/inventory/items/{entry['items'][0]['id']}/publish",
        headers=headers,
        json={"sale_price": "900000.00"},
    ).json()
    code = published["code"]
    assert code

    assert [i["id"] for i in _search(client, token, q=code)] == [published["id"]]
    assert [i["id"] for i in _search(client, token, q=code.lower())] == [published["id"]]
    # Prefijo parcial, como cuando se tipea a medias.
    assert published["id"] in [i["id"] for i in _search(client, token, q=code[:4])]


def test_search_finds_drafts_by_name_even_though_code_is_null(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Regresión: `code` es NULL hasta que se publica, y `like` sobre NULL da
    NULL (no false). Sin el `coalesce` del repositorio, la condición completa
    se anulaba y un borrador NUNCA aparecía al buscar por nombre."""
    token = inventory_tenant["token"]
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Reloj sin publicar"),
    )

    found = _search(client, token, q="reloj")
    assert len(found) == 1
    assert found[0]["code"] is None
    assert found[0]["status"] == "draft"


def test_blank_query_does_not_filter_everything_out(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Un `?q=` con solo espacios (al borrar el texto del buscador) tiene que
    comportarse como sin filtro, no como una búsqueda que no matchea nada."""
    token = inventory_tenant["token"]
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Pulsera"),
    )

    assert len(_search(client, token, q="   ")) == 1
    assert len(_search(client, token)) == 1


def test_filter_items_by_category_and_supplier(client: TestClient, inventory_tenant: dict) -> None:
    token = inventory_tenant["token"]
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena filtrable"),
    )

    assert len(_search(client, token, cat3_id=str(inventory_tenant["cat3"]))) == 1
    assert len(_search(client, token, supplier_id=str(inventory_tenant["supplier_id"]))) == 1
    assert len(_search(client, token, origin="supplier")) == 1
    # Un origen que no tiene ningún artículo de esta empresa.
    assert len(_search(client, token, origin="auction")) == 0
    assert len(_search(client, token, cat3_id=str(uuid4()))) == 0


def test_search_combines_with_status_filter(client: TestClient, inventory_tenant: dict) -> None:
    token = inventory_tenant["token"]
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena en borrador"),
    )

    assert len(_search(client, token, q="cadena", status="draft")) == 1
    assert len(_search(client, token, q="cadena", status="available")) == 0


# ---- Compra a crédito y fecha real de entrada (pedido del cliente: el admin
# carga facturas de días anteriores, o de noche con la caja ya cerrada).


@pytest.mark.asyncio
async def test_purchase_without_payment_method_is_pending_and_needs_no_session(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El caso de las 11 de la noche: sin caja abierta la compra igual se
    registra, pendiente de pago. Antes esto era imposible — se exigía sesión."""
    token = inventory_tenant["token"]
    await _close_session(inventory_tenant)

    payload = _entry_payload(inventory_tenant)
    del payload["payment_method"]
    response = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["payment_method"] is None
    assert body["paid_at"] is None


def test_purchase_accepts_a_past_entry_date(client: TestClient, inventory_tenant: dict) -> None:
    """La mercancía entró ayer aunque se digite hoy. `entry_date` es lo que
    importa para inventario y costo; el pago es otro hecho."""
    token = inventory_tenant["token"]
    ayer = (date.today() - timedelta(days=3)).isoformat()

    payload = _entry_payload(inventory_tenant, entry_date=ayer)
    del payload["payment_method"]
    response = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload)

    assert response.status_code == 201, response.text
    assert response.json()["entry_date"] == ayer


def test_purchase_rejects_a_future_entry_date(client: TestClient, inventory_tenant: dict) -> None:
    payload = _entry_payload(
        inventory_tenant, entry_date=(date.today() + timedelta(days=1)).isoformat()
    )
    del payload["payment_method"]
    response = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_paying_a_pending_purchase_moves_cash_today(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El punto central del diseño: la compra puede ser de la semana pasada,
    pero su egreso cae en la sesión de HOY. Una sesión cerrada es inmutable, así
    que no hay forma —ni debería haberla— de afectar la caja de aquel día."""
    token = inventory_tenant["token"]
    payload = _entry_payload(
        inventory_tenant, entry_date=(date.today() - timedelta(days=5)).isoformat()
    )
    del payload["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload).json()

    paid = client.post(
        f"/api/v1/inventory/entries/{entry['id']}/pay",
        headers=_headers(token),
        json={"payment_method": "transfer"},
    )
    assert paid.status_code == 200, paid.text
    body = paid.json()
    assert body["payment_method"] == "transfer"
    assert body["paid_at"] is not None
    # La fecha de la mercancía NO se toca al pagar.
    assert body["entry_date"] == payload["entry_date"]

    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                text(
                    "select concept, direction, amount, payment_method, session_id "
                    "from public.cash_movement "
                    "where company_id = :cid and reference_id = :eid"
                ),
                {"cid": str(inventory_tenant["company_id"]), "eid": entry["id"]},
            )
        ).one()
    assert row.concept == "purchase"
    assert row.direction == "out"
    assert row.payment_method == "transfer"
    # Cae en la sesión abierta de hoy, no en ninguna del pasado.
    assert row.session_id == inventory_tenant["session_id"]


def test_paying_twice_is_rejected(client: TestClient, inventory_tenant: dict) -> None:
    token = inventory_tenant["token"]
    payload = _entry_payload(inventory_tenant)
    del payload["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload).json()

    first = client.post(
        f"/api/v1/inventory/entries/{entry['id']}/pay",
        headers=_headers(token),
        json={"payment_method": "cash"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/v1/inventory/entries/{entry['id']}/pay",
        headers=_headers(token),
        json={"payment_method": "cash"},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_paying_without_open_session_is_rejected(
    client: TestClient, inventory_tenant: dict
) -> None:
    token = inventory_tenant["token"]
    payload = _entry_payload(inventory_tenant)
    del payload["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload).json()

    await _close_session(inventory_tenant)
    response = client.post(
        f"/api/v1/inventory/entries/{entry['id']}/pay",
        headers=_headers(token),
        json={"payment_method": "cash"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CASH_SESSION_NOT_OPEN"


# ---- Producto + lote (00021): reponer cae en el MISMO producto ----------


def _publish(client: TestClient, token: str, item_id: str, price: str) -> dict:
    r = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=_headers(token),
        json={"sale_price": price},
    )
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_restocking_the_same_product_reuses_it_and_adds_a_lot(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El corazón de 00021: comprar dos veces lo mismo NO crea dos productos.
    Cae en el mismo y suma un lote — de ahí sale que la lista agrupe, que el
    precio se cambie una vez y que se puedan comparar proveedores."""
    token = inventory_tenant["token"]

    primera = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena repetida", photos=["https://x/1.jpg"]),
    ).json()
    segunda = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena repetida", photos=["https://x/2.jpg"]),
    ).json()

    lote1, lote2 = primera["items"][0], segunda["items"][0]

    # Mismo producto, lotes consecutivos.
    assert lote1["product_id"] == lote2["product_id"]
    assert lote1["lot_number"] == 1
    assert lote2["lot_number"] == 2

    # Y los códigos comparten el SKU: es lo que hace visible en la etiqueta
    # que son el mismo producto.
    code1 = _publish(client, token, lote1["id"], "900000.00")["code"]
    code2 = _publish(client, token, lote2["id"], "950000.00")["code"]
    assert code1.split("-")[0] == code2.split("-")[0]
    assert code1.endswith("-01I")
    assert code2.endswith("-02I")


def test_product_match_ignores_case_and_spacing(client: TestClient, inventory_tenant: dict) -> None:
    """El nombre lo escribe una persona: "Cadena de oro" y "cadena de oro "
    no son productos distintos. Tratarlos así dispersaría el catálogo y
    rompería la agrupación justo en el caso más común."""
    token = inventory_tenant["token"]
    a = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena de Oro"),
    ).json()
    b = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "  cadena de oro  "),
    ).json()

    assert a["items"][0]["product_id"] == b["items"][0]["product_id"]


def test_a_different_name_creates_a_different_product(
    client: TestClient, inventory_tenant: dict
) -> None:
    token = inventory_tenant["token"]
    a = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena de oro"),
    ).json()
    b = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Anillo de oro"),
    ).json()

    assert a["items"][0]["product_id"] != b["items"][0]["product_id"]
