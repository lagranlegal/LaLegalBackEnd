"""Base legal del correo del cliente, su captura en el mostrador y la baja por
enlace (docs/NOTIFICACIONES.md §9.2, fase 3 — §17).

Tres cosas, y un test por cada promesa:

- **La base se escribe, no se deduce** (§9.2-a): `consent` solo cuando alguien
  dijo que sí, en el mostrador; `contract` cuando nace un contrato vivo y el
  cliente tiene correo.
- **La baja gana sobre todo**, y se registra con fecha.
- **La baja NO se ejecuta con un GET.** Los escáneres de correo y las vistas
  previas abren los enlaces solos (03/09/2026). El GET solo muestra; la baja
  es un POST. Hay un test que abre el enlace muchas veces y verifica que el
  cliente siga suscrito.
"""

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.db import AsyncSessionLocal, engine
from app.core.settings import get_settings
from app.modules.notifications import unsubscribe


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


@pytest.fixture(autouse=True)
def _link_config(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "secreto-de-prueba-de-los-enlaces-de-baja")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(**overrides: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "full_name": "Juana Pérez",
        "doc_type": "cc",
        "doc_number": str(uuid4().int)[:10],
        "phone": "3001234567",
    }
    base.update(overrides)
    return base


async def _row(sql: str, params: dict[str, Any]) -> Any:
    async with AsyncSessionLocal() as s:
        return (await s.execute(text(sql), params)).first()


async def _exec(sql: str, params: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(text(sql), params)


async def _live_contract(company_id: UUID, customer_id: UUID, status: str = "active") -> None:
    number = (
        await _row(
            "select coalesce(max(number), 0) + 1 as n from public.contract where company_id = :cid",
            {"cid": str(company_id)},
        )
    ).n
    await _exec(
        """
        insert into public.contract
            (company_id, number, customer_id, principal, capital_balance, interest_rate_pct,
             term_months, arrears_window_months, start_date, due_date, interest_paid_until,
             status)
        values (:cid, :n, :cust, 1000000, 1000000, 5, 4, 4, current_date,
                current_date + 120, current_date, cast(:st as contract_status))
        """,
        {"cid": str(company_id), "n": number, "cust": str(customer_id), "st": status},
    )


@pytest_asyncio.fixture
async def cleanup_contracts(tenant: dict) -> Any:
    yield
    await _exec(
        "delete from public.contract where company_id = :cid", {"cid": str(tenant["company_id"])}
    )


# ------------------------------------------------ la casilla del mostrador ----


def test_a_new_customer_has_no_basis(client: TestClient, tenant: dict) -> None:
    """Dar el correo no es autorizar nada: sin casilla y sin contrato, ninguna
    base. Es la fila que protege el caso "anotó el correo por anotarlo"."""
    body = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com"),
    ).json()
    assert body["email_basis"] is None
    assert body["email_consent_at"] is None
    assert body["email_consent_source"] is None
    assert body["email_opt_out_at"] is None
    assert body["email_invalid_at"] is None


async def test_ticking_the_box_records_express_consent(client: TestClient, tenant: dict) -> None:
    response = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com", email_consent=True),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email_basis"] == "consent"
    assert body["email_consent_source"] == "counter"
    assert body["email_consent_at"] is not None
    assert body["email_basis_at"] == body["email_consent_at"]

    audit = await _row(
        "select after from public.audit_log where entity_id = :id and action = 'create_customer'",
        {"id": body["id"]},
    )
    assert audit.after["email_basis"] == "consent"


async def test_unticking_falls_back_to_contract_if_there_is_a_live_one(
    client: TestClient, tenant: dict, cleanup_contracts: None
) -> None:
    """Retirar la autorización expresa no borra la relación contractual: el
    cliente sigue recibiendo lo de SU contrato (§9.2-f). Y la fecha de la
    autorización se va con ella: queda en `audit_log`, no colgando de otra
    base."""
    created = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com", email_consent=True),
    ).json()
    await _live_contract(tenant["company_id"], UUID(created["id"]))

    body = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email_consent": False},
    ).json()
    assert body["email_basis"] == "contract"
    assert body["email_consent_at"] is None
    assert body["email_consent_source"] is None

    audit = await _row(
        "select before, after from public.audit_log where entity_id = :id "
        "and action = 'update_customer' order by created_at desc limit 1",
        {"id": created["id"]},
    )
    assert audit.before["email_basis"] == "consent"
    assert audit.after["email_basis"] == "contract"


def test_unticking_without_contract_leaves_no_basis(client: TestClient, tenant: dict) -> None:
    created = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com", email_consent=True),
    ).json()
    body = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email_consent": False},
    ).json()
    assert body["email_basis"] is None
    assert body["email_basis_at"] is None


def test_ticking_again_keeps_the_original_date(client: TestClient, tenant: dict) -> None:
    """Reenviar el formulario con la casilla marcada no es una autorización
    nueva: la fecha que sirve de prueba es la primera."""
    created = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com", email_consent=True),
    ).json()
    again = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email_consent": True, "phone": "3009999999"},
    ).json()
    assert again["email_consent_at"] == created["email_consent_at"]


async def test_adding_an_email_to_a_customer_with_a_live_contract_sets_contract_basis(
    client: TestClient, tenant: dict, cleanup_contracts: None
) -> None:
    """§1c: el correo casi nunca está el día del contrato; se pide después.
    Si la base solo se escribiera al crear el contrato, el cliente que da el
    correo una semana después quedaría sin base para siempre."""
    created = client.post(
        "/api/v1/customers", headers=_headers(tenant["token"]), json=_payload()
    ).json()
    await _live_contract(tenant["company_id"], UUID(created["id"]))

    body = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana@example.com"},
    ).json()
    assert body["email_basis"] == "contract"
    assert body["email_basis_at"] is not None


async def test_a_paid_contract_is_not_a_basis(
    client: TestClient, tenant: dict, cleanup_contracts: None
) -> None:
    created = client.post(
        "/api/v1/customers", headers=_headers(tenant["token"]), json=_payload()
    ).json()
    await _live_contract(tenant["company_id"], UUID(created["id"]), status="paid")
    body = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana@example.com"},
    ).json()
    assert body["email_basis"] is None


async def test_changing_the_email_clears_the_bounce_mark(client: TestClient, tenant: dict) -> None:
    """`email_invalid_at` habla de la dirección que rebotó, no de la persona."""
    created = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com"),
    ).json()
    await _exec(
        "update public.customer set email_invalid_at = now() where id = :id",
        {"id": created["id"]},
    )
    same = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana@example.com", "phone": "3001111111"},
    ).json()
    assert same["email_invalid_at"] is not None
    changed = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana.perez@example.com"},
    ).json()
    assert changed["email_invalid_at"] is None


def test_counter_can_register_and_undo_an_opt_out(client: TestClient, tenant: dict) -> None:
    """La persona también pide la baja en persona, y también se arrepiente en
    persona. Es un dato de ella, así que lo registra quien la atiende."""
    created = client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana@example.com", email_consent=True),
    ).json()
    out = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email_opt_out": True},
    ).json()
    assert out["email_opt_out_at"] is not None
    # La baja no borra la base: la tapa. Si vuelve, vuelve con lo que tenía.
    assert out["email_basis"] == "consent"

    back = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email_opt_out": False},
    ).json()
    assert back["email_opt_out_at"] is None


# ------------------------------------- correos viejos que no pasan EmailStr ----


async def test_an_old_invalid_email_does_not_block_editing_the_customer(
    client: TestClient, tenant: dict
) -> None:
    """Se valida al ESCRIBIR, no hacia atrás (F21-19). Un correo guardado antes
    de la validación no puede impedir corregir el teléfono: el formulario
    reenvía el correo tal como está, y si el backend lo rechazara, la ficha
    quedaría congelada hasta que alguien adivine qué campo arreglar."""
    created = client.post(
        "/api/v1/customers", headers=_headers(tenant["token"]), json=_payload()
    ).json()
    await _exec(
        "update public.customer set email = 'juana@gmial,com' where id = :id",
        {"id": created["id"]},
    )

    same = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana@gmial,com", "phone": "3007777777"},
    )
    assert same.status_code == 200, same.text
    assert same.json()["phone"] == "3007777777"
    assert same.json()["email"] == "juana@gmial,com"

    # Cambiarlo por OTRO inválido sí se rechaza, con el mismo contrato de
    # siempre: VALIDATION_ERROR y el campo en `loc`.
    other = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana@gmail,com"},
    )
    assert other.status_code == 422, other.text
    body = other.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert any("email" in e["loc"] for e in body["details"]["errors"]), body["details"]

    fixed = client.patch(
        f"/api/v1/customers/{created['id']}",
        headers=_headers(tenant["token"]),
        json={"email": "juana@gmail.com"},
    )
    assert fixed.status_code == 200, fixed.text


# ---------------------------------------------------- el enlace de baja ----


def _customer_with_consent(client: TestClient, tenant: dict) -> dict[str, Any]:
    return client.post(
        "/api/v1/customers",
        headers=_headers(tenant["token"]),
        json=_payload(email="juana.perez@example.com", email_consent=True),
    ).json()


def _token(tenant: dict, customer_id: str) -> str:
    return unsubscribe.make_token(company_id=tenant["company_id"], customer_id=UUID(customer_id))


async def test_opening_the_link_does_not_unsubscribe(client: TestClient, tenant: dict) -> None:
    """LA regla de esta fase. Un escáner de correo o una vista previa de
    WhatsApp hace GET sobre el enlace apenas llega — varias veces, y sin
    cookies. Si el GET diera de baja, el cliente quedaría fuera sin haber
    abierto el correo (pasó el 03/09/2026 con un token de un solo uso)."""
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])

    for _ in range(3):
        response = client.get(f"/api/v1/public/unsubscribe/{token}")
        assert response.status_code == 200, response.text
    body = response.json()
    assert body["company_name"] == "Empresa tenant-test"
    assert body["email_hint"] == "j•••@example.com"
    assert body["unsubscribed_at"] is None

    row = await _row(
        "select email_opt_out_at from public.customer where id = :id", {"id": customer["id"]}
    )
    assert row.email_opt_out_at is None
    audit = await _row(
        "select count(*) as n from public.audit_log where entity_id = :id "
        "and action = 'email_opt_out'",
        {"id": customer["id"]},
    )
    assert audit.n == 0


async def test_the_post_unsubscribes_and_is_idempotent(client: TestClient, tenant: dict) -> None:
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])

    first = client.post(f"/api/v1/public/unsubscribe/{token}")
    assert first.status_code == 200, first.text
    assert first.json()["unsubscribed_at"] is not None

    second = client.post(f"/api/v1/public/unsubscribe/{token}")
    assert second.status_code == 200
    # Idempotente: la fecha que queda es la primera, y no hay un segundo
    # registro de algo que ya había pasado.
    assert second.json()["unsubscribed_at"] == first.json()["unsubscribed_at"]

    after_get = client.get(f"/api/v1/public/unsubscribe/{token}").json()
    assert after_get["unsubscribed_at"] == first.json()["unsubscribed_at"]

    row = await _row(
        "select email_opt_out_at, email_basis from public.customer where id = :id",
        {"id": customer["id"]},
    )
    assert row.email_opt_out_at is not None
    assert row.email_basis == "consent"  # la baja tapa la base, no la borra

    audits = await _row(
        "select count(*) as n, min(user_id::text) as uid, "
        "min(after->>'source') as source from public.audit_log "
        "where entity_id = :id and action = 'email_opt_out'",
        {"id": customer["id"]},
    )
    assert audits.n == 1
    assert audits.uid is None  # la pidió el titular, no un usuario
    assert audits.source == "link"


def test_a_forged_or_unknown_link_is_rejected_with_its_code(
    client: TestClient, tenant: dict
) -> None:
    customer = _customer_with_consent(client, tenant)
    good = _token(tenant, customer["id"])
    body, sig = good.split(".")
    forged = unsubscribe.make_token(company_id=tenant["company_id"], customer_id=uuid4())
    other_company = unsubscribe.make_token(company_id=uuid4(), customer_id=UUID(customer["id"]))

    for token in (f"{body}.{sig[::-1]}", "basura", forged, other_company):
        for method in ("GET", "POST"):
            response = client.request(method, f"/api/v1/public/unsubscribe/{token}")
            assert response.status_code == 404, (method, token, response.text)
            assert response.json()["code"] == "UNSUBSCRIBE_LINK_INVALID"


def test_without_secret_no_link_is_valid(
    client: TestClient, tenant: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "")
    get_settings.cache_clear()
    response = client.post(f"/api/v1/public/unsubscribe/{token}")
    assert response.status_code == 404
    assert response.json()["code"] == "UNSUBSCRIBE_LINK_INVALID"


def test_the_public_endpoints_need_no_session(client: TestClient, tenant: dict) -> None:
    """Quien abre el enlace no es usuario de Prendo: no tiene sesión ni la va
    a tener. Y no le mostramos más que lo necesario para reconocerse."""
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])
    body = client.get(f"/api/v1/public/unsubscribe/{token}").json()
    assert set(body) == {"company_name", "email_hint", "unsubscribed_at"}


# ------------------------------- baja de un clic y límite de tasa (§17-bis) ----


async def test_the_one_click_post_from_the_mail_provider_unsubscribes(
    client: TestClient, tenant: dict
) -> None:
    """RFC 8058 §3.2: el servidor de Gmail/Yahoo hace POST a la URI de
    `List-Unsubscribe` con el cuerpo `List-Unsubscribe=One-Click`, sin cookies
    ni sesión, y espera la baja hecha — sin página intermedia."""
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])

    response = client.post(
        f"/api/v1/public/unsubscribe/{token}",
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["unsubscribed_at"] is not None
    row = await _row(
        "select email_opt_out_at from public.customer where id = :id", {"id": customer["id"]}
    )
    assert row.email_opt_out_at is not None


async def test_a_browser_opening_the_api_link_goes_to_the_page_without_unsubscribing(
    client: TestClient, tenant: dict
) -> None:
    """Un cliente de correo que no sabe hacer el POST abre la URI de la
    cabecera en el navegador. Ve la página de baja (que pregunta), no un JSON
    — y abrirla sigue sin dar de baja."""
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])

    response = client.get(
        f"/api/v1/public/unsubscribe/{token}",
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"https://app.example.com/baja/{token}"
    # El `fetch` de la página manda `*/*`: ese sigue recibiendo el JSON.
    assert client.get(f"/api/v1/public/unsubscribe/{token}").json()["unsubscribed_at"] is None
    row = await _row(
        "select email_opt_out_at from public.customer where id = :id", {"id": customer["id"]}
    )
    assert row.email_opt_out_at is None


def test_the_same_link_hammered_gets_rate_limited(client: TestClient, tenant: dict) -> None:
    """10 pedidos por token cada 10 minutos, GET y POST juntos. El 11 recibe
    429 con su código y `Retry-After`. Una persona real hace 2 o 3."""
    customer = _customer_with_consent(client, tenant)
    token = _token(tenant, customer["id"])
    for i in range(10):
        method = "POST" if i % 2 else "GET"
        assert client.request(method, f"/api/v1/public/unsubscribe/{token}").status_code == 200

    blocked = client.post(f"/api/v1/public/unsubscribe/{token}")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body["code"] == "RATE_LIMITED"
    assert 0 < body["details"]["retry_after_seconds"] <= 600
    assert blocked.headers["Retry-After"] == str(body["details"]["retry_after_seconds"])

    # Otro enlace, desde la misma IP, no paga por este.
    other = _customer_with_consent(client, tenant)
    other_token = _token(tenant, other["id"])
    assert client.get(f"/api/v1/public/unsubscribe/{other_token}").status_code == 200


def test_one_ip_sweeping_tokens_gets_rate_limited(client: TestClient, tenant: dict) -> None:
    """60 por minuto por IP. Cada token basura es distinto, así que el límite
    por token no los ve: los corta el de la IP. Detrás de Fly la IP es la de
    `Fly-Client-IP`, no la del proxy."""
    for i in range(60):
        response = client.get(
            f"/api/v1/public/unsubscribe/basura{i}", headers={"Fly-Client-IP": "203.0.113.7"}
        )
        assert response.json()["code"] == "UNSUBSCRIBE_LINK_INVALID"
    blocked = client.get(
        "/api/v1/public/unsubscribe/basura-61", headers={"Fly-Client-IP": "203.0.113.7"}
    )
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "RATE_LIMITED"
    # Otra persona (otra IP real detrás del mismo proxy) no queda bloqueada.
    other = client.get(
        "/api/v1/public/unsubscribe/basura-x", headers={"Fly-Client-IP": "198.51.100.2"}
    )
    assert other.json()["code"] == "UNSUBSCRIBE_LINK_INVALID"
