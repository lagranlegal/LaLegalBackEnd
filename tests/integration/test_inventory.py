"""Integración de inventory (paso 7): ingresos crean ítems en draft,
publicar exige foto+precio y emite código inmutable, egresos descuentan
stock, y la compra a proveedor sale por caja (concepto `purchase`).
Requiere Postgres real (se salta si no hay)."""

import asyncio
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
    codes = (
        "inventory.view",
        "inventory.create",
        "inventory.exit",
        # Los reportes de inventario (valorización, sin rotación) y el de
        # cuentas por pagar viven en `reports` pero se prueban acá, donde está
        # la mercancía que los alimenta.
        "reports.view",
        # La ficha del proveedor vive en `catalogs` por la misma razón: sus
        # números salen de las compras, que se crean acá.
        "catalogs.view",
        # Desde 00035 pagar una compra pendiente exige su propio permiso:
        # mueve plata, no inventario.
        "inventory.pay_purchase",
        # 00037: fundir, despiezar, armar.
        "inventory.transform",
        # El KARDEX se prueba acá porque es del inventario, pero necesita
        # vender y anular: la anulación es el único movimiento de stock que no
        # existe como fila en ninguna tabla y hay que sintetizarlo.
        "sales.create",
        "sales.void",
    )

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
    """Un ingreso que no es compra no entrega plata a nadie: no exige caja
    abierta ni genera movimiento — el mismo criterio por el que un remate
    tampoco lo hace (ahí el capital ya salió como préstamo).

    Se usa `initial_stock` (00033) y no `other`: la mercancía que ya estaba en
    la vitrina al arrancar con el sistema es justo el caso que antes había que
    disfrazar de "otro" o —peor— de compra falsa, que le habría sacado a la
    caja una plata que nunca salió.
    """
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("update public.cash_session set status = 'closed' where id = :sid"),
            {"sid": str(inventory_tenant["session_id"])},
        )

    payload = _entry_payload(inventory_tenant, origin_type="initial_stock")
    del payload["supplier_id"]
    del payload["payment_method"]
    response = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert response.status_code == 201, response.text
    assert response.json()["payment_method"] is None
    assert response.json()["origin_type"] == "initial_stock"

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


def test_publish_does_not_require_a_photo_for_regular_merchandise(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Mercancía fungible se publica SIN foto (00034).

    Antes se exigía para todo artículo. La regla venía del spec original,
    donde la frase estaba escrita pensando en el REMATE — y ahí se conserva
    (ver `test_auction_unique_piece_still_requires_a_photo`). Para cincuenta
    fundas de celular iguales compradas por docenas era fricción sin
    beneficio: obligaba a fotografiar en cada reposición algo ya fotografiado.
    """
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    ).json()
    item_id = entry["items"][0]["id"]

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


async def test_correcting_the_category_now_belongs_to_the_product(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Reemplaza a `test_update_item_can_correct_category_while_draft`.

    Desde 00022 la categoría es del PRODUCTO, no del lote: dos lotes de la
    misma cadena no pueden estar en categorías distintas — si lo estuvieran,
    no serían el mismo producto. Así que `PATCH /items/{id}` ya no la acepta
    (solo fotos) y corregirla es una edición del producto, que aplica a todos
    sus lotes de una vez.
    """
    token = inventory_tenant["token"]
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_payload(inventory_tenant),
    ).json()
    item = entry["items"][0]

    # El ítem solo acepta fotos: lo demás se ignora, no se escribe.
    solo_fotos = client.patch(
        f"/api/v1/inventory/items/{item['id']}",
        headers=_headers(token),
        json={"photos": ["https://example.com/f.jpg"]},
    )
    assert solo_fotos.status_code == 200, solo_fotos.text
    assert solo_fotos.json()["photos"] == ["https://example.com/f.jpg"]

    # El nombre se corrige en el producto y aplica a todos sus lotes.
    renombrado = client.patch(
        f"/api/v1/inventory/products/{item['product_id']}",
        headers=_headers(token),
        json={"name": "Cadena corregida"},
    )
    assert renombrado.status_code == 200, renombrado.text
    assert renombrado.json()["name"] == "Cadena corregida"

    releido = client.get(f"/api/v1/inventory/items/{item['id']}", headers=_headers(token)).json()
    assert releido["name"] == "Cadena corregida"


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
    assert Decimal(item["quantity"]) == 0
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


def _products(client: TestClient, token: str, **params: object) -> list[dict]:
    r = client.get("/api/v1/inventory/products", headers=_headers(token), params=params)
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def test_products_list_groups_lots_and_sums_available(
    client: TestClient, inventory_tenant: dict
) -> None:
    """La vista que resuelve el síntoma original: dos compras de lo mismo son
    UN producto con dos lotes, y el vendedor ve el total sin sumar a mano."""
    token = inventory_tenant["token"]
    # Con precio y foto en la línea, el lote nace publicado — no hay que
    # volver a entrar a cada uno. El segundo hereda el precio del producto,
    # así que ni siquiera hace falta repetirlo.
    for costo in ("100000.00", "150000.00"):
        entry = client.post(
            "/api/v1/inventory/entries",
            headers=_headers(token),
            json=_entry_with(
                inventory_tenant,
                "Cadena agrupable",
                unit_cost=costo,
                quantity=3,
                photos=["https://x/f.jpg"],
                sale_price="300000.00",
            ),
        ).json()
        assert entry["items"][0]["status"] == "available"

    productos = _products(client, token, q="cadena")
    assert len(productos) == 1
    p = productos[0]
    assert p["lot_count"] == 2
    assert Decimal(p["available_quantity"]) == 6
    # El rango de costos es informativo: los costos NO se promedian.
    assert p["min_cost"] == "100000.00"
    assert p["max_cost"] == "150000.00"


def test_updating_the_price_applies_to_every_lot(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El problema concreto que se venía arrastrando: antes había que entrar a
    cada lote y cambiar su precio, con el riesgo de dejar uno barato por
    olvido. Ahora es una sola acción."""
    token = inventory_tenant["token"]
    entry_a = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena con precio", photos=["https://x/a.jpg"]),
    ).json()
    entry_b = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena con precio", photos=["https://x/b.jpg"]),
    ).json()
    _publish(client, token, entry_a["items"][0]["id"], "200000.00")
    _publish(client, token, entry_b["items"][0]["id"], "200000.00")

    product_id = entry_a["items"][0]["product_id"]
    assert entry_b["items"][0]["product_id"] == product_id

    subida = client.patch(
        f"/api/v1/inventory/products/{product_id}",
        headers=_headers(token),
        json={"sale_price": "250000.00"},
    )
    assert subida.status_code == 200, subida.text
    assert subida.json()["sale_price"] == "250000.00"

    # Un solo PATCH y el producto entero quedó al precio nuevo.
    productos = _products(client, token, q="cadena con precio")
    assert productos[0]["sale_price"] == "250000.00"
    assert productos[0]["lot_count"] == 2


def test_product_lots_are_listed_oldest_first(client: TestClient, inventory_tenant: dict) -> None:
    """Orden FIFO: el lote más antiguo primero, que es el que conviene vender
    antes para que no envejezca el inventario."""
    token = inventory_tenant["token"]
    for _ in range(2):
        client.post(
            "/api/v1/inventory/entries",
            headers=_headers(token),
            json=_entry_with(inventory_tenant, "Cadena FIFO"),
        )
    product_id = _products(client, token, q="fifo")[0]["id"]

    r = client.get(f"/api/v1/inventory/products/{product_id}/lots", headers=_headers(token))
    assert r.status_code == 200, r.text
    lotes = r.json()
    assert [lote["lot_number"] for lote in lotes] == [1, 2]


def test_unique_products_are_hidden_from_the_grouped_list(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Las piezas de remate son productos de un solo lote: si aparecieran,
    llenarían la lista de grupos de uno sin aportar nada."""
    token = inventory_tenant["token"]
    todos = _products(client, token, include_unique=True)
    agrupables = _products(client, token)
    assert all(not p["is_unique"] for p in agrupables)
    assert len(todos) >= len(agrupables)


def test_changing_the_product_price_reaches_the_lots_that_the_pos_reads(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Regresión de un bug real introducido al mover el precio al producto: el
    POS arma la venta con `inventory_item.sale_price`, así que si el PATCH del
    producto no propagaba a los lotes, cambiar el precio NO cambiaba lo que se
    cobraba en caja. Doble fuente de verdad = bug de dinero.

    Esta sincronización existe solo mientras dure la fase 2; la fase 3 elimina
    la columna duplicada y con ella la necesidad.
    """
    token = inventory_tenant["token"]
    entry = client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena sincronizada", photos=["https://x/s.jpg"]),
    ).json()
    item_id = entry["items"][0]["id"]
    _publish(client, token, item_id, "200000.00")

    product_id = entry["items"][0]["product_id"]
    client.patch(
        f"/api/v1/inventory/products/{product_id}",
        headers=_headers(token),
        json={"sale_price": "260000.00"},
    )

    # Lo que el POS va a leer y cobrar.
    item = client.get(f"/api/v1/inventory/items/{item_id}", headers=_headers(token)).json()
    assert item["sale_price"] == "260000.00"


def test_other_entry_requires_a_reason(client: TestClient, inventory_tenant: dict) -> None:
    """ "Otro" es un cajón de sastre, así que tiene que explicarse.

    Los demás orígenes dicen qué son en su propio nombre; este no dice nada.
    Sin motivo no hay forma de saber después de dónde salió esa mercancía —
    que es exactamente el problema que 00033 vino a cerrar.
    """
    headers = _headers(inventory_tenant["token"])
    payload = _entry_payload(inventory_tenant, origin_type="other")
    del payload["supplier_id"]
    del payload["payment_method"]

    sin_motivo = client.post("/api/v1/inventory/entries", headers=headers, json=payload)
    assert sin_motivo.status_code == 400, sin_motivo.text
    assert sin_motivo.json()["details"]["field"] == "notes"

    payload["notes"] = "Mercancía recibida en dación de pago de un tercero"
    con_motivo = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert con_motivo.status_code == 201, con_motivo.text


def test_adjustment_in_registers_a_counting_surplus(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El inventario físico ya puede SUBIR, no solo bajar.

    Existía el egreso por ajuste, así que un conteo que encontraba de menos se
    podía registrar y uno que encontraba de más no. El sistema quedaba
    mintiendo a sabiendas sobre una diferencia que alguien ya había visto.
    """
    headers = _headers(inventory_tenant["token"])
    payload = _entry_payload(inventory_tenant, origin_type="adjustment_in")
    del payload["supplier_id"]
    del payload["payment_method"]

    response = client.post("/api/v1/inventory/entries", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["origin_type"] == "adjustment_in"
    # No mueve plata: un sobrante aparece, no se compra.
    assert response.json()["payment_method"] is None


def test_loss_exit_is_distinct_from_damage(client: TestClient, inventory_tenant: dict) -> None:
    """Pérdida/hurto es su propio tipo: un daño es mercancía que existe y ya
    no sirve; una pérdida es mercancía que no está."""
    headers = _headers(inventory_tenant["token"])
    entry = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    ).json()
    item_id = entry["items"][0]["id"]

    response = client.post(
        "/api/v1/inventory/exits",
        headers=_headers(inventory_tenant["token"]),
        json={
            "exit_type": "loss",
            "reason": "Faltante detectado en conteo, se puso la denuncia",
            "lines": [{"item_id": item_id, "quantity": 1}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["exit_type"] == "loss"


def test_initial_stock_can_actually_be_published(
    client: TestClient, inventory_tenant: dict
) -> None:
    """La mercancía inicial tiene que poder llegar a la vitrina.

    Bug encontrado justo después de crear el tipo `initial_stock` (00033): al
    publicar, el código se arma con la letra del proveedor (o `R` si es
    remate), y un ingreso sin proveedor no tenía ninguna de las dos — así que
    lanzaba 400 y la mercancía quedaba atrapada en borrador PARA SIEMPRE. El
    tipo creado para cargar lo que la compraventa ya tenía en la vitrina no
    servía para ponerlo en la vitrina.

    Ahora cae en `P` de "propio", con la misma lógica que la `R` de remate:
    la letra dice de dónde salió la pieza.
    """
    headers = _headers(inventory_tenant["token"])
    payload = _entry_payload(inventory_tenant, origin_type="initial_stock")
    del payload["supplier_id"]
    del payload["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=headers, json=payload).json()
    item_id = entry["items"][0]["id"]

    client.patch(
        f"/api/v1/inventory/items/{item_id}",
        headers=_headers(inventory_tenant["token"]),
        json={"photos": ["inventario-inicial.jpg"]},
    )
    published = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=_headers(inventory_tenant["token"]),
        json={"sale_price": "50000.00"},
    )
    assert published.status_code == 200, published.text
    body = published.json()
    assert body["status"] == "available"
    assert body["code"].endswith("P"), body["code"]


def test_initial_stock_keeps_the_supplier_letter_when_it_is_known(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Si se sabe a quién se le compró originalmente, esa letra manda.

    `P` es el respaldo para cuando no hay proveedor, no un reemplazo: cargar
    el inventario inicial sabiendo su origen no debería perder esa
    trazabilidad.
    """
    headers = _headers(inventory_tenant["token"])
    payload = _entry_payload(inventory_tenant, origin_type="initial_stock")
    del payload["payment_method"]  # no toca caja, pero sí conserva proveedor
    entry = client.post("/api/v1/inventory/entries", headers=headers, json=payload).json()
    item_id = entry["items"][0]["id"]

    client.patch(
        f"/api/v1/inventory/items/{item_id}",
        headers=_headers(inventory_tenant["token"]),
        json={"photos": ["x.jpg"]},
    )
    published = client.post(
        f"/api/v1/inventory/items/{item_id}/publish",
        headers=_headers(inventory_tenant["token"]),
        json={"sale_price": "50000.00"},
    )
    assert published.status_code == 200, published.text
    # 'I' es la letra del proveedor del fixture.
    assert published.json()["code"].endswith("I"), published.json()["code"]


def test_entry_with_price_and_photo_publishes_on_the_spot(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Una compra completa nace vendible, no en borrador.

    Antes TODA compra nacía en borrador sin importar qué tan completa viniera,
    y había que volver artículo por artículo desde otra pantalla a ponerle
    precio y foto. El borrador dejaba de significar "le falta algo" y pasaba a
    ser el estado normal — con el efecto de que un artículo REALMENTE
    incompleto se volvía invisible: no está en la vitrina y nadie se entera.
    """
    headers = _headers(inventory_tenant["token"])
    payload = _entry_payload(inventory_tenant)
    payload["lines"][0]["sale_price"] = "150000.00"
    payload["lines"][0]["photos"] = ["cadena.jpg"]

    entry = client.post("/api/v1/inventory/entries", headers=headers, json=payload)
    assert entry.status_code == 201, entry.text
    item = entry.json()["items"][0]

    assert item["status"] == "available", "con precio y foto no hay nada que esperar"
    assert item["code"] is not None, "publicar emite el código"
    assert item["sale_price"] == "150000.00"


def test_what_makes_an_entry_line_publishable(client: TestClient, inventory_tenant: dict) -> None:
    """Lo único que decide es el PRECIO (00034).

    Antes hacían falta precio y foto. La foto dejó de ser obligatoria para
    mercancía fungible, así que ahora el borrador significa exactamente una
    cosa: no se sabe en cuánto se vende. Y eso sí tiene que bloquear —
    publicar con un precio inventado sería peor que esperar.
    """
    headers = _headers(inventory_tenant["token"])

    sin_precio = client.post(
        "/api/v1/inventory/entries", headers=headers, json=_entry_payload(inventory_tenant)
    ).json()
    assert sin_precio["items"][0]["status"] == "draft"
    assert sin_precio["items"][0]["code"] is None

    solo_foto = _entry_payload(inventory_tenant)
    solo_foto["lines"][0]["photos"] = ["x.jpg"]
    solo_foto["lines"][0]["name"] = "Solo foto sin precio"
    r = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=solo_foto
    ).json()
    assert r["items"][0]["status"] == "draft", "una foto no dice en cuánto se vende"

    solo_precio = _entry_payload(inventory_tenant)
    solo_precio["lines"][0]["sale_price"] = "90000.00"
    solo_precio["lines"][0]["name"] = "Solo precio sin foto"
    r2 = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=solo_precio
    ).json()
    assert r2["items"][0]["status"] == "available", "con precio ya es vendible, foto o no"


def test_entry_photos_belong_to_the_product_and_are_inherited(
    client: TestClient, inventory_tenant: dict
) -> None:
    """La foto se toma UNA vez y la heredan todos los lotes (00034).

    Era la queja concreta: reponer obligaba a re-fotografiar lo mismo, porque
    las fotos vivían en el lote mientras el nombre, la categoría y el precio
    ya habían subido al producto en 00022.
    """
    token = inventory_tenant["token"]
    primera = _entry_with(
        inventory_tenant, "Cadena fotografiada", photos=["catalogo.jpg"], sale_price="120000.00"
    )
    r1 = client.post("/api/v1/inventory/entries", headers=_headers(token), json=primera).json()
    assert r1["items"][0]["photos"] == ["catalogo.jpg"]

    # Reposición SIN fotos: hereda las del producto.
    segunda = _entry_with(inventory_tenant, "Cadena fotografiada", unit_cost="70000.00")
    r2 = client.post("/api/v1/inventory/entries", headers=_headers(token), json=segunda).json()
    lote_nuevo = r2["items"][0]
    assert lote_nuevo["photos"] == ["catalogo.jpg"], "no hay que volver a fotografiar"
    assert lote_nuevo["status"] == "available"

    productos = _products(client, token, q="fotografiada")
    assert productos[0]["photos"] == ["catalogo.jpg"], "la foto vive en el producto"


def test_restock_inherits_the_price_already_set_on_the_product(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Reponer no obliga a redigitar el precio.

    El precio es del PRODUCTO, así que si ya se le puso una vez, el lote nuevo
    lo hereda y se publica solo con traer la foto. Volver a pedirlo sería
    pedir un dato que el sistema ya tiene, con el riesgo real de que alguien
    escriba otro y deje dos lotes del mismo producto a precios distintos en la
    misma vitrina.
    """
    headers = _headers(inventory_tenant["token"])
    primera = _entry_payload(inventory_tenant)
    primera["lines"][0]["name"] = "Cadena que se repone"
    primera["lines"][0]["sale_price"] = "200000.00"
    primera["lines"][0]["photos"] = ["a.jpg"]
    r1 = client.post("/api/v1/inventory/entries", headers=headers, json=primera).json()
    assert r1["items"][0]["status"] == "available"

    # Segunda compra del MISMO producto: sin precio, solo foto.
    segunda = _entry_payload(inventory_tenant)
    segunda["lines"][0]["name"] = "Cadena que se repone"
    segunda["lines"][0]["photos"] = ["b.jpg"]
    segunda["lines"][0]["unit_cost"] = "70000.00"  # costo distinto, precio igual
    r2 = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=segunda
    ).json()
    item = r2["items"][0]

    assert item["status"] == "available", "hereda el precio del producto y se publica"
    assert item["sale_price"] == "200000.00"
    # Y el costo NO se promedia: cada lote conserva el suyo (NIIF).
    assert item["cost"] == "70000.00"


def test_entries_filter_by_pending_payment(client: TestClient, inventory_tenant: dict) -> None:
    """ "¿Qué compras tengo por pagar?" — la pregunta que no tenía respuesta.

    El dato vivía en cada fila desde 00020 y hasta tenía índice parcial, pero
    ninguna consulta lo ofrecía: había que abrir los ingresos uno por uno.
    """
    token = inventory_tenant["token"]
    pagada = _entry_payload(inventory_tenant)  # trae payment_method: se paga ya
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=pagada)

    pendiente = _entry_payload(inventory_tenant)
    del pendiente["payment_method"]
    creada = client.post(
        "/api/v1/inventory/entries", headers=_headers(token), json=pendiente
    ).json()

    por_pagar = client.get(
        "/api/v1/inventory/entries",
        headers={"Authorization": f"Bearer {token}"},
        params={"payment_status": "pending"},
    ).json()["items"]
    ids = {e["id"] for e in por_pagar}
    assert creada["id"] in ids
    assert all(e["paid_at"] is None and e["origin_type"] == "purchase" for e in por_pagar)

    pagadas = client.get(
        "/api/v1/inventory/entries",
        headers={"Authorization": f"Bearer {token}"},
        params={"payment_status": "paid"},
    ).json()["items"]
    assert creada["id"] not in {e["id"] for e in pagadas}
    assert all(e["paid_at"] is not None for e in pagadas)


def test_entries_filter_by_supplier_and_origin(client: TestClient, inventory_tenant: dict) -> None:
    token = inventory_tenant["token"]
    inicial = _entry_payload(inventory_tenant, origin_type="initial_stock")
    del inicial["payment_method"]
    del inicial["supplier_id"]
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=inicial)
    client.post(
        "/api/v1/inventory/entries", headers=_headers(token), json=_entry_payload(inventory_tenant)
    )

    solo_inicial = client.get(
        "/api/v1/inventory/entries",
        headers={"Authorization": f"Bearer {token}"},
        params={"origin_type": "initial_stock"},
    ).json()["items"]
    assert solo_inicial
    assert all(e["origin_type"] == "initial_stock" for e in solo_inicial)

    del_proveedor = client.get(
        "/api/v1/inventory/entries",
        headers={"Authorization": f"Bearer {token}"},
        params={"supplier_id": str(inventory_tenant["supplier_id"])},
    ).json()["items"]
    assert del_proveedor
    assert all(e["supplier_id"] == str(inventory_tenant["supplier_id"]) for e in del_proveedor)


def test_products_filter_by_category_and_stock(client: TestClient, inventory_tenant: dict) -> None:
    """La pestaña principal del inventario no tenía más filtro que el texto."""
    token = inventory_tenant["token"]
    payload = _entry_with(
        inventory_tenant, "Cadena filtrable", photos=["f.jpg"], sale_price="80000.00"
    )
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload)
    # Un producto sin publicar: existe pero no tiene unidades disponibles.
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena sin publicar"),
    )

    def _get(**params: object) -> list[dict]:
        r = client.get(
            "/api/v1/inventory/products",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
        assert r.status_code == 200, r.text
        return list(r.json()["items"])

    por_categoria = _get(cat3_id=str(inventory_tenant["cat3"]))
    assert por_categoria
    assert all(p["cat3_id"] == str(inventory_tenant["cat3"]) for p in por_categoria)

    # Categoría que no existe en la rama: no debe traer nada.
    assert _get(cat1_id=str(inventory_tenant["cat3"])) == []

    con_stock = _get(in_stock=True)
    assert all(Decimal(p["available_quantity"]) > 0 for p in con_stock)
    assert "Cadena sin publicar" not in {p["name"] for p in con_stock}

    por_proveedor = _get(supplier_id=str(inventory_tenant["supplier_id"]))
    assert por_proveedor


def test_exits_filter_by_type(client: TestClient, inventory_tenant: dict) -> None:
    token = inventory_tenant["token"]
    entry = client.post(
        "/api/v1/inventory/entries", headers=_headers(token), json=_entry_payload(inventory_tenant)
    ).json()
    item_id = entry["items"][0]["id"]
    client.post(
        "/api/v1/inventory/exits",
        headers=_headers(token),
        json={
            "exit_type": "loss",
            "reason": "Faltante en conteo",
            "lines": [{"item_id": item_id, "quantity": 1}],
        },
    )

    perdidas = client.get(
        "/api/v1/inventory/exits",
        headers={"Authorization": f"Bearer {token}"},
        params={"exit_type": "loss"},
    ).json()["items"]
    assert perdidas
    assert all(e["exit_type"] == "loss" for e in perdidas)

    danos = client.get(
        "/api/v1/inventory/exits",
        headers={"Authorization": f"Bearer {token}"},
        params={"exit_type": "damage"},
    ).json()["items"]
    assert all(e["exit_type"] == "damage" for e in danos)


def test_payables_report_groups_by_supplier_with_aging(
    client: TestClient, inventory_tenant: dict
) -> None:
    """ "¿Cuánto debo, a quién, y desde hace cuánto?" — el primer reporte que
    pediría un contador, y que no existía aunque cada compra ya supiera si
    estaba pagada."""
    token = inventory_tenant["token"]
    hoy = date.today()

    reciente = _entry_payload(inventory_tenant)
    del reciente["payment_method"]
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=reciente)

    vieja = _entry_payload(inventory_tenant)
    del vieja["payment_method"]
    vieja["entry_date"] = str(hoy - timedelta(days=75))
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=vieja)

    # Una PAGADA no debe aparecer: ya no se debe.
    client.post(
        "/api/v1/inventory/entries", headers=_headers(token), json=_entry_payload(inventory_tenant)
    )

    r = client.get("/api/v1/reports/payables", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["entry_count"] == 2, "solo las pendientes"
    assert Decimal(body["days_over_60"]) > 0, "la de hace 75 días cae en +60"
    assert Decimal(body["days_0_30"]) > 0, "la de hoy cae en 0-30"
    # Los tramos tienen que sumar EXACTAMENTE el total: un peso que no cae en
    # ningún tramo es un peso que el reporte esconde.
    tramos = (
        Decimal(body["days_0_30"]) + Decimal(body["days_31_60"]) + Decimal(body["days_over_60"])
    )
    assert tramos == Decimal(body["total"])

    proveedor = body["by_supplier"][0]
    assert proveedor["supplier_id"] == str(inventory_tenant["supplier_id"])
    assert proveedor["oldest_entry_date"] == str(hoy - timedelta(days=75))


def test_inventory_valuation_counts_only_available(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El activo más grande del negocio, valorado AL COSTO.

    Solo cuenta lo disponible: un borrador no se puede vender —y ni siquiera
    tiene precio— así que incluirlo inflaría el activo con mercancía que
    todavía no lo es.
    """
    token = inventory_tenant["token"]
    publicado = _entry_with(
        inventory_tenant,
        "Cadena valorable",
        unit_cost="100000.00",
        quantity=2,
        photos=["v.jpg"],
        sale_price="180000.00",
    )
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=publicado)
    client.post(
        "/api/v1/inventory/entries",
        headers=_headers(token),
        json=_entry_with(inventory_tenant, "Cadena en borrador", unit_cost="999999.00"),
    )

    r = client.get(
        "/api/v1/reports/inventory-valuation", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert Decimal(body["cost_value"]) == Decimal("200000.00"), "2 × 100.000, sin el borrador"
    assert Decimal(body["retail_value"]) == Decimal("360000.00"), "2 × 180.000"
    # La utilidad potencial es la diferencia — lo que se ganaría vendiendo todo
    # hoy. NO forma parte del valor del inventario.
    assert Decimal(body["potential_profit"]) == Decimal("160000.00")
    assert body["units"] == 2
    assert body["by_category"], "desglosado por categoría de primer nivel"


def test_item_inherits_the_entry_date_of_its_purchase(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El lote hereda la fecha del INGRESO, no la de hoy.

    Bug encontrado construyendo el reporte de mercancía sin rotación: 00020
    agregó `entry_date` al ingreso y nunca lo propagó al lote, que se quedaba
    con el `current_date` por defecto de 00006. Una compra cargada con fecha
    de la semana pasada guardaba esa fecha en el ingreso y "hoy" en cada uno
    de sus lotes — así que la ficha del lote mostraba una fecha falsa y
    cualquier medida de antigüedad de inventario contaba desde el día de la
    digitación en vez del día en que la mercancía llegó.
    """
    token = inventory_tenant["token"]
    hace_un_mes = str(date.today() - timedelta(days=30))
    payload = _entry_payload(inventory_tenant)
    del payload["payment_method"]
    payload["entry_date"] = hace_un_mes

    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload).json()
    assert entry["entry_date"] == hace_un_mes
    assert entry["items"][0]["entry_date"] == hace_un_mes, "el lote entró cuando entró la mercancía"


def test_stale_inventory_uses_the_oldest_lot(client: TestClient, inventory_tenant: dict) -> None:
    """Se mide sobre el lote más ANTIGUO todavía disponible.

    Si algo entró hace un año y se repuso ayer, lo congelado es la pieza
    vieja — usar la fecha del lote nuevo la escondería justo cuando más
    importa verla.
    """
    token = inventory_tenant["token"]
    viejo = _entry_with(inventory_tenant, "Cadena dormida", photos=["d.jpg"], sale_price="90000.00")
    viejo["entry_date"] = str(date.today() - timedelta(days=200))
    del viejo["payment_method"]
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=viejo)

    # Reposición de HOY del MISMO producto.
    nuevo = _entry_with(inventory_tenant, "Cadena dormida", photos=["e.jpg"])
    del nuevo["payment_method"]
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=nuevo)

    r = client.get(
        "/api/v1/reports/stale-inventory",
        headers={"Authorization": f"Bearer {token}"},
        params={"threshold_days": 90},
    )
    assert r.status_code == 200, r.text
    dormidos = {p["product_name"]: p for p in r.json()["items"]}
    assert "Cadena dormida" in dormidos, "la reposición de hoy no debe esconder la pieza vieja"
    assert dormidos["Cadena dormida"]["days_in_stock"] >= 200


def test_product_purchase_history_compares_suppliers_and_costs(
    client: TestClient, inventory_tenant: dict
) -> None:
    """ "¿Cómo se movió el costo?" y "¿a quién le compro más barato?".

    La lista de productos ya insinuaba esto mostrando el rango de costos entre
    lotes, pero no dejaba abrirlo: se veía que el costo se movió y no por qué.
    """
    token = inventory_tenant["token"]
    for costo in ("100000.00", "130000.00"):
        client.post(
            "/api/v1/inventory/entries",
            headers=_headers(token),
            json=_entry_with(inventory_tenant, "Cadena con historia", unit_cost=costo),
        )

    productos = _products(client, token, q="historia")
    assert productos
    product_id = productos[0]["id"]

    r = client.get(
        f"/api/v1/inventory/products/{product_id}/purchases",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    compras = r.json()
    assert len(compras) == 2
    assert {c["unit_cost"] for c in compras} == {"100000.00", "130000.00"}
    assert all(c["supplier_name"] == "Proveedor Uno" for c in compras)


def test_supplier_summary_and_purchase_history(client: TestClient, inventory_tenant: dict) -> None:
    """La ficha del proveedor: qué le compré y cuánto le debo.

    El CLIENTE tiene su ficha con historial cruzado desde el paso 4; el
    proveedor tenía un formulario de creación y nada más, así que "¿cuánto le
    he comprado?" no tenía respuesta aunque el dato estuviera completo.
    """
    token = inventory_tenant["token"]
    supplier_id = str(inventory_tenant["supplier_id"])

    pagada = _entry_with(inventory_tenant, "Cadena pagada", unit_cost="200000.00")
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=pagada)

    pendiente = _entry_with(inventory_tenant, "Cadena a crédito", unit_cost="300000.00")
    del pendiente["payment_method"]
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=pendiente)

    r = client.get(
        f"/api/v1/catalogs/suppliers/{supplier_id}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    ficha = r.json()

    assert ficha["purchase_count"] == 2
    assert Decimal(ficha["total_purchased"]) == Decimal("500000.00")
    # Lo pendiente es un subconjunto de lo comprado, no otra cosa.
    assert ficha["pending_count"] == 1
    assert Decimal(ficha["pending_total"]) == Decimal("300000.00")
    assert ficha["product_count"] == 2, "dos productos distintos"
    assert ficha["last_purchase_date"] is not None

    compras = client.get(
        f"/api/v1/catalogs/suppliers/{supplier_id}/purchases",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert compras.status_code == 200, compras.text
    items = compras.json()["items"]
    assert len(items) == 2
    assert {i["item_count"] for i in items} == {1}
    # Una pagada y una no: es lo que distingue la deuda del histórico.
    assert sorted(i["paid_at"] is None for i in items) == [False, True]


def test_paying_a_purchase_needs_its_own_permission(
    client: TestClient, inventory_tenant: dict, rsa_keypair: tuple[str, object]
) -> None:
    """Pagarle a un proveedor no es administrar el inventario (00035).

    Antes exigía `inventory.create`, o sea que quien registra mercancía podía
    además sacar plata de la caja para pagarla. Son dos hechos distintos y
    separados en el tiempo —la mercancía ENTRA, la factura SE PAGA— y el
    sistema ya los distingue por dentro (`entry_date` vs `paid_at`).
    """
    token = inventory_tenant["token"]
    pendiente = _entry_payload(inventory_tenant)
    del pendiente["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=pendiente).json()

    # Un rol con `inventory.create` pero SIN el permiso nuevo no puede pagar.
    private_pem, _ = rsa_keypair
    bodega_role, bodega_user = uuid4(), uuid4()
    company_id = inventory_tenant["company_id"]

    async def _crear_rol_bodega() -> None:
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(
                text(
                    "insert into public.role (id, company_id, name) "
                    "values (:id, :cid, 'Solo bodega')"
                ),
                {"id": str(bodega_role), "cid": str(company_id)},
            )
            await session.execute(
                text(
                    "insert into public.role_permission (role_id, permission_id) "
                    "select :rid, id from public.permission "
                    "where code in ('inventory.view', 'inventory.create')"
                ),
                {"rid": str(bodega_role)},
            )
            await session.execute(
                text(
                    "insert into public.app_user "
                    "(id, company_id, role_id, full_name, email, status) "
                    "values (:id, :cid, :rid, 'Solo Bodega', :email, 'active')"
                ),
                {
                    "id": str(bodega_user),
                    "cid": str(company_id),
                    "rid": str(bodega_role),
                    "email": f"bodega-only-{bodega_user}@example.com",
                },
            )

    asyncio.run(_crear_rol_bodega())
    bodega_token = make_token(
        private_pem, sub=str(bodega_user), company_id=str(company_id), role_id=str(bodega_role)
    )

    rechazado = client.post(
        f"/api/v1/inventory/entries/{entry['id']}/pay",
        headers=_headers(bodega_token),
        json={"payment_method": "cash"},
    )
    assert rechazado.status_code == 403, rechazado.text
    assert rechazado.json()["details"]["permission"] == "inventory.pay_purchase"

    # Y el rol que sí lo tiene, paga.
    ok = client.post(
        f"/api/v1/inventory/entries/{entry['id']}/pay",
        headers=_headers(token),
        json={"payment_method": "cash"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["paid_at"] is not None


def test_a_product_measured_in_grams_accepts_fractional_stock(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Vender por peso, que era imposible hasta 00036.

    `quantity` era `int` en las cuatro tablas del flujo de mercancía, así que
    12,5 g no se podía ni registrar. Salió diseñando la fundición, pero no es
    una función de oro: ninguna compraventa podía vender NADA por peso ni por
    medida.
    """
    token = inventory_tenant["token"]
    payload = _entry_with(
        inventory_tenant,
        "Oro 18k",
        unit="gram",
        quantity="31.200",
        unit_cost="19230.00",
        sale_price="24000.00",
        photos=["oro.jpg"],
    )
    del payload["payment_method"]

    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload)
    assert entry.status_code == 201, entry.text
    lote = entry.json()["items"][0]

    assert Decimal(lote["quantity"]) == Decimal("31.200")
    assert lote["unit"] == "gram"
    # La abreviatura la manda el backend para que front, comprobantes y
    # reportes digan todos lo mismo: si cada uno tradujera por su cuenta,
    # "12,5 g" y "12,5 gr" acabarían conviviendo en la misma venta.
    assert lote["unit_abbr"] == "g"

    productos = _products(client, token, q="Oro 18k")
    assert Decimal(productos[0]["available_quantity"]) == Decimal("31.200")
    assert productos[0]["unit_abbr"] == "g"


def test_a_product_measured_in_units_rejects_fractions(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Media cadena no existe.

    En un producto contable una cantidad fraccionaria es un error de
    digitación —una coma donde iba un punto— y registrarlo dejaría un stock
    imposible que nadie nota hasta que el conteo físico no cuadre.
    """
    token = inventory_tenant["token"]
    payload = _entry_with(inventory_tenant, "Cadena contable", quantity="1.5")
    del payload["payment_method"]

    rechazado = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload)
    assert rechazado.status_code == 400, rechazado.text
    assert "fraccionarias" in rechazado.json()["message"]

    # Y con cantidad entera pasa sin problema.
    payload["lines"][0]["quantity"] = "2"
    ok = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=payload
    )
    assert ok.status_code == 201, ok.text


def test_the_unit_cannot_change_once_there_is_stock(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Doce unidades no son doce gramos.

    Cambiar la unidad de un producto con lotes reinterpretaría todo lo ya
    registrado —stock, ventas pasadas, valorización— sin que nada lo
    advierta. Mismo criterio que impide cambiar el TIPO de una cuenta: un dato
    que da sentido a los hechos ya guardados no se toca después.
    """
    token = inventory_tenant["token"]
    payload = _entry_with(inventory_tenant, "Producto con unidad")
    del payload["payment_method"]
    client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload)

    producto = _products(client, token, q="unidad")[0]
    rechazado = client.patch(
        f"/api/v1/inventory/products/{producto['id']}",
        headers=_headers(token),
        json={"unit": "gram"},
    )
    assert rechazado.status_code == 409, rechazado.text
    assert "ya tiene lotes" in rechazado.json()["message"]


def test_restocking_keeps_the_unit_of_the_existing_product(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Reponer no puede cambiar la unidad por descuido.

    Si una compra nueva pudiera imponer su unidad, bastaría con dejar el
    selector en su valor por defecto para reinterpretar en silencio el stock
    anterior del producto.
    """
    token = inventory_tenant["token"]
    primera = _entry_with(inventory_tenant, "Cable por metro", unit="meter", quantity="10.5")
    del primera["payment_method"]
    r1 = client.post("/api/v1/inventory/entries", headers=_headers(token), json=primera).json()
    assert r1["items"][0]["unit"] == "meter"

    # Segunda compra del MISMO producto, con la unidad por defecto.
    segunda = _entry_with(inventory_tenant, "Cable por metro", quantity="4.25")
    del segunda["payment_method"]
    r2 = client.post(
        "/api/v1/inventory/entries", headers=_headers(inventory_tenant["token"]), json=segunda
    )
    assert r2.status_code == 201, r2.text
    # Conserva "meter" — y por eso acepta 4,25, que en "unit" habría sido
    # rechazado.
    assert r2.json()["items"][0]["unit"] == "meter"
    assert Decimal(r2.json()["items"][0]["quantity"]) == Decimal("4.25")


def test_melting_moves_the_cost_and_the_waste_raises_it(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Fundir: EL COSTO VIAJA, y la merma sube el costo por gramo.

    Sin esta operación había que dar de baja las prendas como pérdida
    —castigando su costo contra resultados, como si se hubieran evaporado— y
    meter el oro como sobrante de conteo, inventando ese costo de la nada. Dos
    errores que se compensan en el saldo y destrozan el estado de resultados.
    """
    token = inventory_tenant["token"]

    # Tres prendas que costaron 575.000 en total.
    consumidos = []
    for nombre, costo in (("Anillo", "180000.00"), ("Cadena", "300000.00"), ("Dije", "95000.00")):
        payload = _entry_with(
            inventory_tenant, nombre, unit_cost=costo, sale_price="900000.00", photos=["p.jpg"]
        )
        del payload["payment_method"]
        entry = client.post(
            "/api/v1/inventory/entries", headers=_headers(token), json=payload
        ).json()
        consumidos.append(entry["items"][0]["id"])

    fundicion = client.post(
        "/api/v1/inventory/transformations",
        headers=_headers(token),
        json={
            "reason": "Fundición de prendas rematadas sin rotación",
            # Lo que cobra el fundidor: se CAPITALIZA, no es gasto del mes.
            "extra_cost": "25000.00",
            "payment_method": "cash",
            "inputs": [{"item_id": i, "quantity": "1"} for i in consumidos],
            "outputs": [
                {
                    "name": "Oro 18k",
                    "cat1_id": str(inventory_tenant["cat1"]),
                    "cat2_id": str(inventory_tenant["cat2"]),
                    "cat3_id": str(inventory_tenant["cat3"]),
                    # Entraron 34 g de prendas y salen 31,2: la diferencia es
                    # soldadura, impurezas, pérdida del proceso.
                    "quantity": "31.200",
                    "unit": "gram",
                    "sale_price": "24000.00",
                }
            ],
        },
    )
    assert fundicion.status_code == 201, fundicion.text
    cuerpo = fundicion.json()

    # 575.000 de prendas + 25.000 del fundidor = 600.000 que VIAJAN.
    assert Decimal(cuerpo["total_cost"]) == Decimal("600000.00")
    assert len(cuerpo["consumed"]) == 3
    assert len(cuerpo["produced"]) == 1

    oro = cuerpo["produced"][0]
    assert Decimal(oro["quantity"]) == Decimal("31.200")
    assert oro["unit"] == "gram"
    # 600.000 / 31,2 = 19.230,77 por gramo. Ese es EL número: contra el precio
    # del oro del día se sabe si fundir convenía.
    assert Decimal(oro["cost"]) == Decimal("19230.77")
    # Y con precio, nace vendible.
    assert oro["status"] == "available"

    # El oro SABE de dónde salió (00039). Sin este puntero la única forma de
    # llegar a la fundición desde el lote era item -> línea de ingreso ->
    # ingreso -> transformación: cuatro saltos, ninguno expuesto por la API.
    assert oro["source_transformation_id"] == cuerpo["id"]
    # Y por eso su código lleva `T` de transformado y no la `P` genérica de
    # "propio", que mezclaba oro fundido con mercancía del inventario inicial.
    assert oro["code"].endswith("T"), oro["code"]

    # Las prendas dejaron de existir — pero NO como pérdida.
    for item_id in consumidos:
        consumido = client.get(
            f"/api/v1/inventory/items/{item_id}", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert consumido["status"] == "written_off"
        assert Decimal(consumido["quantity"]) == 0
        # El código NO se toca: es inmutable, y esa pieza existió. Borrarlo
        # borraría la historia.
        assert consumido["code"] is not None

    # --- El historial: "¿de dónde salió este oro?" ----------------------
    historial = client.get("/api/v1/inventory/transformations", headers=_headers(token))
    assert historial.status_code == 200, historial.text
    filas = historial.json()["items"]
    assert len(filas) == 1
    fila = filas[0]
    assert fila["id"] == cuerpo["id"]
    assert fila["reason"] == "Fundición de prendas rematadas sin rotación"
    assert fila["input_count"] == 3
    assert fila["output_count"] == 1
    assert Decimal(fila["total_cost"]) == Decimal("600000.00")
    assert Decimal(fila["extra_cost"]) == Decimal("25000.00")
    # Se lee de corrido sin abrir el detalle — que es el punto de la lista.
    assert "Oro 18k" in fila["output_names"]
    for prenda in ("Anillo", "Cadena", "Dije"):
        assert prenda in fila["input_names"]


def test_transformation_splits_the_cost_across_several_outputs(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Despiezar: un equipo entra, varias partes salen.

    El costo se reparte proporcional al valor estimado de cada parte — el
    MISMO mecanismo con que el remate reparte el saldo del contrato entre las
    prendas. Repartirlo en partes iguales habría hecho que una carcasa
    "costara" lo mismo que una pantalla.
    """
    token = inventory_tenant["token"]
    payload = _entry_with(inventory_tenant, "Equipo para despiece", unit_cost="400000.00")
    del payload["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload).json()

    def _salida(nombre: str, valor: str) -> dict:
        return {
            "name": nombre,
            "cat1_id": str(inventory_tenant["cat1"]),
            "cat2_id": str(inventory_tenant["cat2"]),
            "cat3_id": str(inventory_tenant["cat3"]),
            "quantity": "1",
            "estimated_value": valor,
        }

    despiece = client.post(
        "/api/v1/inventory/transformations",
        headers=_headers(token),
        json={
            "reason": "Despiece de equipo dañado",
            "inputs": [{"item_id": entry["items"][0]["id"], "quantity": "1"}],
            "outputs": [_salida("Pantalla", "300000"), _salida("Carcasa", "100000")],
        },
    )
    assert despiece.status_code == 201, despiece.text
    partes = {p["name"]: Decimal(p["cost"]) for p in despiece.json()["produced"]}

    # 75% / 25% de 400.000 — y la suma es exactamente el costo original: nada
    # se pierde ni se inventa por el camino.
    assert partes["Pantalla"] == Decimal("300000.00")
    assert partes["Carcasa"] == Decimal("100000.00")
    assert sum(partes.values()) == Decimal("400000.00")


def test_transformation_with_a_process_cost_needs_to_say_who_paid(
    client: TestClient, inventory_tenant: dict
) -> None:
    """Si el proceso costó, esa plata salió de algún lado.

    Sin medio de pago, el costo del inventario subiría 25.000 sin que nadie
    hubiera pagado nada — plata inventada, que es justo lo que esta operación
    existe para evitar.
    """
    token = inventory_tenant["token"]
    payload = _entry_with(inventory_tenant, "Prenda a fundir sin pago")
    del payload["payment_method"]
    entry = client.post("/api/v1/inventory/entries", headers=_headers(token), json=payload).json()

    rechazado = client.post(
        "/api/v1/inventory/transformations",
        headers=_headers(token),
        json={
            "reason": "Fundición sin decir quién pagó",
            "extra_cost": "25000.00",
            "inputs": [{"item_id": entry["items"][0]["id"], "quantity": "1"}],
            "outputs": [
                {
                    "name": "Oro sin pago",
                    "cat1_id": str(inventory_tenant["cat1"]),
                    "cat2_id": str(inventory_tenant["cat2"]),
                    "cat3_id": str(inventory_tenant["cat3"]),
                    "quantity": "5",
                    "unit": "gram",
                }
            ],
        },
    )
    assert rechazado.status_code == 400, rechazado.text
    assert rechazado.json()["details"]["field"] == "payment_method"


def test_kardex_cuadra_con_el_stock_real_incluida_la_anulacion(
    client: TestClient, inventory_tenant: dict
) -> None:
    """El kardex es el libro auxiliar del inventario: su saldo final TIENE que
    ser el stock real, o no sirve para nada.

    La prueba de fuego es la **anulación de una venta**. Anular repone el
    stock pero NO escribe una línea inversa —solo cambia el estado de la
    venta— así que ese movimiento existe en el stock y en ninguna tabla. Si el
    kardex no lo sintetiza, muestra una salida que nunca vuelve y su saldo
    queda por debajo del real para siempre.
    """
    token = inventory_tenant["token"]

    # Dos lotes del MISMO producto a costos distintos: es lo que hace que el
    # saldo de costo no se pueda derivar de las unidades.
    for costo in ("100000.00", "160000.00"):
        payload = _entry_with(
            inventory_tenant, "Cadena plata", unit_cost=costo, quantity=2, sale_price="250000.00"
        )
        del payload["payment_method"]
        entrada = client.post(
            "/api/v1/inventory/entries", headers=_headers(token), json=payload
        ).json()
        assert entrada["items"][0]["status"] == "available"
        primer_lote = entrada["items"][0]

    product_id = primer_lote["product_id"]

    # 4 unidades: 2 a 100.000 + 2 a 160.000 = 520.000
    kardex = client.get(
        f"/api/v1/inventory/products/{product_id}/kardex", headers=_headers(token)
    )
    assert kardex.status_code == 200, kardex.text
    cuerpo = kardex.json()
    assert Decimal(cuerpo["closing_quantity"]) == Decimal("4")
    assert Decimal(cuerpo["closing_value"]) == Decimal("520000.00")
    assert len(cuerpo["lines"]) == 2

    # Vender una unidad del lote CARO.
    venta = client.post(
        "/api/v1/sales",
        headers=_headers(token),
        json={
            "payment_method": "cash",
            "lines": [
                {"item_id": primer_lote["id"], "quantity": "1", "unit_price": "250000.00"}
            ],
        },
    )
    assert venta.status_code == 201, venta.text

    cuerpo = client.get(
        f"/api/v1/inventory/products/{product_id}/kardex", headers=_headers(token)
    ).json()
    assert Decimal(cuerpo["closing_quantity"]) == Decimal("3")
    # Sale al costo de SU lote (160.000), no a un promedio (130.000). Si se
    # promediara, acá diría 390.000.
    assert Decimal(cuerpo["closing_value"]) == Decimal("360000.00")
    assert cuerpo["lines"][-1]["kind"] == "sale"

    # Anular: el stock vuelve, y el kardex tiene que decirlo.
    anulacion = client.post(
        f"/api/v1/sales/{venta.json()['id']}/void",
        headers=_headers(token),
        json={"reason": "El cliente se arrepintió"},
    )
    assert anulacion.status_code == 200, anulacion.text

    cuerpo = client.get(
        f"/api/v1/inventory/products/{product_id}/kardex", headers=_headers(token)
    ).json()
    ultima = cuerpo["lines"][-1]
    assert ultima["kind"] == "sale_void"
    assert Decimal(ultima["quantity_in"]) == Decimal("1")
    assert ultima["detail"] == "El cliente se arrepintió"
    # Y el saldo volvió exactamente a donde estaba.
    assert Decimal(cuerpo["closing_quantity"]) == Decimal("4")
    assert Decimal(cuerpo["closing_value"]) == Decimal("520000.00")

    # El saldo del kardex ES el stock real: la comprobación que justifica todo
    # lo demás. Se compara contra la suma de los lotes, que es la otra forma
    # —independiente— de responder cuánto hay.
    lotes = client.get(
        f"/api/v1/inventory/products/{product_id}/lots", headers=_headers(token)
    ).json()
    stock_real = sum(Decimal(lote["quantity"]) for lote in lotes)
    assert stock_real == Decimal(cuerpo["closing_quantity"])
    costo_real = sum(Decimal(lote["quantity"]) * Decimal(lote["cost"]) for lote in lotes)
    assert costo_real == Decimal(cuerpo["closing_value"])
