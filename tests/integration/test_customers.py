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


# --------------------------------------------------------------------------
# El buscador filtra desde la TERCERA letra, no desde la palabra completa
# (11/09/2026, reportado por el cliente como "solo filtra desde la quinta")
# --------------------------------------------------------------------------
def test_el_nombre_se_encuentra_por_prefijo_no_por_palabra_completa(
    client: TestClient, tenant: dict
) -> None:
    """La causa real del "solo filtra desde la quinta letra".

    `plainto_tsquery` comparaba lexemas ENTEROS: "Mateo" encontraba a Mateo
    y "Mate" no encontraba nada. Como los nombres de pila suelen tener cinco
    o seis letras, en el mostrador se veía como un umbral de cinco.
    """
    creado = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(full_name="Mateo Jaramillo Restrepo", doc_number="1098765432"),
    ).json()

    def encuentra(q: str) -> bool:
        r = client.get("/api/v1/customers", headers=_headers(tenant["token"]), params={"q": q})
        assert r.status_code == 200, r.text
        return creado["id"] in [item["id"] for item in r.json()["items"]]

    assert encuentra("mat"), "tres letras del nombre: es lo que pidió el cliente"
    assert encuentra("jara"), "el apellido tampoco necesita estar completo"
    assert encuentra("restr"), "cualquiera de las tres palabras, no solo la primera"
    assert encuentra("jara mateo"), "el orden de las palabras no importa (full-text)"
    assert not encuentra("zzz"), "el filtro sigue filtrando"


def test_el_documento_se_encuentra_por_prefijo_corto(client: TestClient, tenant: dict) -> None:
    """El otro lado del mismo pedido: la cédula desde tres dígitos."""
    creado = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(full_name="Sin Coincidencia Textual", doc_number="4471234567"),
    ).json()

    r = client.get("/api/v1/customers", headers=_headers(tenant["token"]), params={"q": "447"})
    assert creado["id"] in [item["id"] for item in r.json()["items"]]


def test_una_busqueda_de_puro_signo_no_revienta(client: TestClient, tenant: dict) -> None:
    """`to_tsquery` es sintaxis: un `&` o un `(` sueltos son un SyntaxError
    de Postgres, o sea un 500 en el buscador. Con `plainto_tsquery` esto no
    podía pasar, así que es riesgo NUEVO del cambio."""
    for q in ("&", "(", ":*", "&|()", "de la", "  "):
        r = client.get("/api/v1/customers", headers=_headers(tenant["token"]), params={"q": q})
        assert r.status_code == 200, f"q={q!r} devolvió {r.status_code}: {r.text}"


def test_un_apellido_de_puras_stopwords_igual_encuentra(client: TestClient, tenant: dict) -> None:
    """Las stopwords del español —"de", "la", "los"— son lexemas VACÍOS:
    el full-text no puede verlos. Sin el `ilike` de respaldo, "De la Cruz" no
    se encontraría tecleando "de la"."""
    creado = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(full_name="Rosa De La Cruz", doc_number="7781234567"),
    ).json()

    r = client.get("/api/v1/customers", headers=_headers(tenant["token"]), params={"q": "de la"})
    assert r.status_code == 200, r.text
    assert creado["id"] in [item["id"] for item in r.json()["items"]]


def test_la_enie_no_hace_falta_para_encontrar_a_nadie(client: TestClient, tenant: dict) -> None:
    """El hallazgo real de 00056, y es lo contrario de lo que se había
    anotado: el stemmer de `spanish` YA normaliza las vocales acentuadas
    —"jose" encontraba a José y "gomez" a Gómez— pero deja la EÑE intacta.

    Medido sobre apellidos colombianos corrientes fallaban 8 de 11, y los 8
    por lo mismo. Nadie teclea la eñe al buscar: el teclado del celular la
    esconde.
    """
    creados = {}
    for i, nombre in enumerate(("Ana Muñoz Peña", "Luis Castaño Ordóñez", "Sara Zúñiga Acuña")):
        creados[nombre] = client.post(
            "/api/v1/customers",
            headers=_headers(tenant["token"]),
            json=_payload(full_name=nombre, doc_number=f"88{i}1234567"[:10]),
        ).json()["id"]

    def encuentra(q: str, nombre: str) -> bool:
        r = client.get("/api/v1/customers", headers=_headers(tenant["token"]), params={"q": q})
        assert r.status_code == 200, r.text
        return creados[nombre] in [item["id"] for item in r.json()["items"]]

    # Sin la eñe, que es como se teclea de verdad.
    assert encuentra("munoz", "Ana Muñoz Peña")
    assert encuentra("pena", "Ana Muñoz Peña")
    assert encuentra("castano", "Luis Castaño Ordóñez")
    assert encuentra("ordonez", "Luis Castaño Ordóñez")
    assert encuentra("zuniga", "Sara Zúñiga Acuña")
    assert encuentra("acuna", "Sara Zúñiga Acuña")

    # Y CON la eñe también: normalizar un solo lado rompería este caso, y es
    # el que nadie probaría porque "obviamente funciona".
    assert encuentra("muñoz", "Ana Muñoz Peña")
    assert encuentra("castaño", "Luis Castaño Ordóñez")

    # Desde tres letras, como el resto.
    assert encuentra("cas", "Luis Castaño Ordóñez")
    assert encuentra("zun", "Sara Zúñiga Acuña")

    # Y el filtro sigue filtrando: esto no es "encontrar todo".
    assert not encuentra("zzz", "Ana Muñoz Peña")


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
def test_customer_stores_both_sides_of_the_document(client: TestClient, tenant: dict) -> None:
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


def test_updating_the_photos_keeps_both_fields_in_sync(client: TestClient, tenant: dict) -> None:
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
