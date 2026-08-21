"""Integración de catalogs (paso 4): árbol de categorías (niveles, unicidad
entre hermanos incluyendo raíz), proveedores. Requiere Postgres real (se
salta si no hay)."""

from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text

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


def test_create_root_category(client: TestClient, tenant: dict) -> None:
    response = client.post(
        "/api/v1/catalogs/categories",
        headers=_headers(tenant["token"]),
        json={"name": "Joyería", "code_letter": "J"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["level"] == 1
    assert body["parent_id"] is None


def test_create_child_category_increments_level(client: TestClient, tenant: dict) -> None:
    parent = client.post(
        "/api/v1/catalogs/categories",
        headers=_headers(tenant["token"]),
        json={"name": "Joyería", "code_letter": "J"},
    ).json()

    child = client.post(
        "/api/v1/catalogs/categories",
        headers=_headers(tenant["token"]),
        json={"name": "Oro", "code_letter": "O", "parent_id": parent["id"]},
    )
    assert child.status_code == 201, child.text
    assert child.json()["level"] == 2
    assert child.json()["parent_id"] == parent["id"]


def test_category_tree_rejects_fourth_level(client: TestClient, tenant: dict) -> None:
    headers = _headers(tenant["token"])
    lvl1 = client.post(
        "/api/v1/catalogs/categories", headers=headers, json={"name": "L1", "code_letter": "A"}
    ).json()
    lvl2 = client.post(
        "/api/v1/catalogs/categories",
        headers=headers,
        json={"name": "L2", "code_letter": "B", "parent_id": lvl1["id"]},
    ).json()
    lvl3 = client.post(
        "/api/v1/catalogs/categories",
        headers=headers,
        json={"name": "L3", "code_letter": "C", "parent_id": lvl2["id"]},
    ).json()

    lvl4 = client.post(
        "/api/v1/catalogs/categories",
        headers=headers,
        json={"name": "L4", "code_letter": "D", "parent_id": lvl3["id"]},
    )
    assert lvl4.status_code == 400
    assert lvl4.json()["code"] == "BAD_REQUEST"


def test_root_categories_with_same_code_letter_is_conflict(
    client: TestClient, tenant: dict
) -> None:
    """Regresión: `unique(company_id, parent_id, code_letter)` en la migración
    no protege esto porque parent_id NULL nunca es igual a sí mismo para
    Postgres — la unicidad la valida el service (repository._sibling_value_exists).
    """
    headers = _headers(tenant["token"])
    first = client.post(
        "/api/v1/catalogs/categories", headers=headers, json={"name": "Joyería", "code_letter": "J"}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/catalogs/categories",
        headers=headers,
        json={"name": "Otra categoría", "code_letter": "J"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"


async def test_categories_readable_with_view_but_without_manage(
    client: TestClient, tenant: dict
) -> None:
    """Leer categorías necesita `catalogs.view`, NO `catalogs.manage` — lo
    necesitan contracts/inventory/sales para operar, y un asesor no puede
    crear un contrato sin elegir la categoría de la prenda.

    Antes de 00030 estos GET no exigían ningún permiso, lo que violaba la
    regla 3 de CLAUDE.md. El permiso nuevo conserva el acceso (la migración
    se lo otorga a todos los roles existentes) pero lo hace quitable a
    conciencia desde la matriz.
    """
    role_id = uuid4()
    user_id = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text(
                "insert into public.role (id, company_id, name) values (:id, :cid, 'SinPermisos')"
            ),
            {"id": str(role_id), "cid": str(tenant["company_id"])},
        )
        await session.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code = 'catalogs.view'"
            ),
            {"role_id": str(role_id)},
        )
        await session.execute(
            text(
                "insert into public.app_user "
                "(id, company_id, role_id, full_name, email, status) "
                "values (:id, :cid, :role_id, 'Sin Permisos', :email, 'active')"
            ),
            {
                "id": str(user_id),
                "cid": str(tenant["company_id"]),
                "role_id": str(role_id),
                "email": f"sinpermisos-{user_id}@example.com",
            },
        )

    from _jwt_helpers import make_token

    token = make_token(
        tenant["private_pem"],
        sub=str(user_id),
        company_id=str(tenant["company_id"]),
        role_id=str(role_id),
    )
    response = client.get("/api/v1/catalogs/categories", headers=_headers(token))
    assert response.status_code == 200

    # …pero crear sigue exigiendo `catalogs.manage`.
    crear = client.post(
        "/api/v1/catalogs/categories",
        headers=_headers(token),
        json={"name": "No debería crearse", "level": 1, "parent_id": None},
    )
    assert crear.status_code == 403

    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(
            text("delete from public.app_user where id = :id"), {"id": str(user_id)}
        )
        await session.execute(
            text("delete from public.role_permission where role_id = :id"), {"id": str(role_id)}
        )
        await session.execute(text("delete from public.role where id = :id"), {"id": str(role_id)})


def test_create_and_update_supplier(client: TestClient, tenant: dict) -> None:
    headers = _headers(tenant["token"])
    create_resp = client.post(
        "/api/v1/catalogs/suppliers",
        headers=headers,
        json={"name": "Proveedor Uno", "code_letter": "P"},
    )
    assert create_resp.status_code == 201, create_resp.text
    supplier = create_resp.json()

    update_resp = client.patch(
        f"/api/v1/catalogs/suppliers/{supplier['id']}",
        headers=headers,
        json={"phone": "3005551234"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["phone"] == "3005551234"


def test_supplier_duplicate_code_letter_is_conflict(client: TestClient, tenant: dict) -> None:
    headers = _headers(tenant["token"])
    first = client.post(
        "/api/v1/catalogs/suppliers", headers=headers, json={"name": "A", "code_letter": "X"}
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/catalogs/suppliers", headers=headers, json={"name": "B", "code_letter": "X"}
    )
    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"


def test_list_suppliers(client: TestClient, tenant: dict) -> None:
    headers = _headers(tenant["token"])
    created = client.post(
        "/api/v1/catalogs/suppliers",
        headers=headers,
        json={"name": "Proveedor Lista", "code_letter": str(uuid4())[:1].upper()},
    ).json()

    response = client.get("/api/v1/catalogs/suppliers", headers=headers)
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert created["id"] in ids
