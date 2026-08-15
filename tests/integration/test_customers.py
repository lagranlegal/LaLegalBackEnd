"""Integración de customers (paso 4): CRUD + duplicado de documento. Requiere
Postgres real (se salta si no hay)."""

from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.core.db import engine


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


def _payload(**overrides: object) -> dict:
    base = {
        "full_name": "Juan Pérez",
        "doc_type": "cc",
        "doc_number": str(uuid4().int)[:10],
        "phone": "3001234567",
    }
    base.update(overrides)
    return base


def test_create_and_get_customer(client: TestClient, tenant: dict) -> None:
    response = client.post("/api/v1/customers", headers=_headers(tenant["token"]), json=_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["full_name"] == "Juan Pérez"
    assert body["status"] == "active"

    get_resp = client.get(f"/api/v1/customers/{body['id']}", headers=_headers(tenant["token"]))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


def test_create_duplicate_doc_is_conflict(client: TestClient, tenant: dict) -> None:
    payload = _payload()
    first = client.post("/api/v1/customers", headers=_headers(tenant["token"]), json=payload)
    assert first.status_code == 201

    second = client.post("/api/v1/customers", headers=_headers(tenant["token"]), json=payload)
    assert second.status_code == 409
    assert second.json()["code"] == "CONFLICT"


def test_list_customers_includes_created(client: TestClient, tenant: dict) -> None:
    created = client.post(
        "/api/v1/customers", headers=_headers(tenant["token"]), json=_payload()
    ).json()

    response = client.get("/api/v1/customers", headers=_headers(tenant["token"]))
    assert response.status_code == 200
    ids = [item["id"] for item in response.json()["items"]]
    assert created["id"] in ids


def test_get_customer_not_found(client: TestClient, tenant: dict) -> None:
    response = client.get(f"/api/v1/customers/{uuid4()}", headers=_headers(tenant["token"]))
    assert response.status_code == 404


def test_update_customer(client: TestClient, tenant: dict) -> None:
    created = client.post(
        "/api/v1/customers", headers=_headers(tenant["token"]), json=_payload()
    ).json()

    response = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"phone": "3009999999", "notes": "cliente frecuente"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "3009999999"
    assert body["notes"] == "cliente frecuente"
    assert body["full_name"] == "Juan Pérez"
