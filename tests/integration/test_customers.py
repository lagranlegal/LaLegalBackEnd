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


def test_list_customers_search_matches_doc_number(client: TestClient, tenant: dict) -> None:
    """docs/PENDIENTES_BACKEND_INFRA.md #1: en el mostrador se tipea la
    cédula, no el nombre — `?q=` debe encontrar por documento también."""
    created = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(full_name="Ana Gómez", doc_number="900123456"),
    ).json()

    exact = client.get(
        "/api/v1/customers", headers=_headers(tenant["token"]), params={"q": "900123456"}
    )
    assert exact.status_code == 200
    assert created["id"] in [item["id"] for item in exact.json()["items"]]

    prefix = client.get(
        "/api/v1/customers", headers=_headers(tenant["token"]), params={"q": "900123"}
    )
    assert created["id"] in [item["id"] for item in prefix.json()["items"]]

    by_name_still_works = client.get(
        "/api/v1/customers", headers=_headers(tenant["token"]), params={"q": "Gómez"}
    )
    assert created["id"] in [item["id"] for item in by_name_still_works.json()["items"]]

    no_match = client.get(
        "/api/v1/customers", headers=_headers(tenant["token"]), params={"q": "999999999"}
    )
    assert created["id"] not in [item["id"] for item in no_match.json()["items"]]


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


# --------------------------------------------------------------------------
# Un documento tiene dos caras (00050)
# --------------------------------------------------------------------------
def test_customer_stores_both_sides_of_the_document(
    client: TestClient, tenant: dict
) -> None:
    """`doc_photo_url` aceptaba UNA foto y una cédula tiene frente y reverso.

    El orden es la semántica: `doc_photos[0]` es el frente. No hacen falta
    dos columnas con nombre — es el mismo patrón que `contract_item.photos`.
    """
    frente, reverso = "co/customers/x/frente.webp", "co/customers/x/reverso.webp"
    creado = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(doc_photos=[frente, reverso]),
    )
    assert creado.status_code == 201, creado.text
    assert creado.json()["doc_photos"] == [frente, reverso]
    # El campo deprecado sale sincronizado con el frente: durante la
    # transición un bundle viejo del front sigue mostrando la foto.
    assert creado.json()["doc_photo_url"] == frente


def test_the_deprecated_single_photo_still_works(client: TestClient, tenant: dict) -> None:
    """Un bundle viejo del front manda `doc_photo_url` y no puede perder la
    foto: entre que sale el backend y sale el front hay una ventana real."""
    unica = "co/customers/y/cedula.webp"
    creado = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(doc_photo_url=unica),
    )
    assert creado.status_code == 201, creado.text
    # Se interpreta como lo que siempre fue: la única foto, o sea el frente.
    assert creado.json()["doc_photos"] == [unica]
    assert creado.json()["doc_photo_url"] == unica


def test_updating_the_photos_keeps_both_fields_in_sync(
    client: TestClient, tenant: dict
) -> None:
    """Escribir una sin la otra las dejaría contradiciéndose, que es el modo
    exacto en que una migración de expandir/contraer se rompe."""
    creado = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(doc_photos=["a.webp"]),
    )
    customer_id = creado.json()["id"]

    actualizado = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=_headers(tenant["token"]),
        json={"doc_photos": ["nuevo-frente.webp", "nuevo-reverso.webp"]},
    )
    assert actualizado.status_code == 200, actualizado.text
    assert actualizado.json()["doc_photos"] == ["nuevo-frente.webp", "nuevo-reverso.webp"]
    assert actualizado.json()["doc_photo_url"] == "nuevo-frente.webp"

    # Y borrarlas todas deja el campo deprecado en null, no en la foto vieja.
    vaciado = client.patch(
        f"/api/v1/customers/{customer_id}",
        headers=_headers(tenant["token"]),
        json={"doc_photos": []},
    )
    assert vaciado.json()["doc_photos"] == []
    assert vaciado.json()["doc_photo_url"] is None


def test_a_customer_without_photos_is_valid(client: TestClient, tenant: dict) -> None:
    """No todo cliente llega con la cédula a la mano."""
    creado = client.post("/api/v1/customers", headers=_headers(tenant["token"]), json=_payload())
    assert creado.status_code == 201, creado.text
    assert creado.json()["doc_photos"] == []
    assert creado.json()["doc_photo_url"] is None
