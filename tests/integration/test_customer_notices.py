"""Los avisos transaccionales al cliente (docs/NOTIFICACIONES.md §2.1, §18):
cada operación GENERA su aviso — fases 4 (C2, C3) y 6 (C1, C4, C5, C6, C7).

Contra Postgres real y contra la API real: los contratos, abonos, ventas y
devoluciones de estos tests se crean por los mismos endpoints que usa el front,
así que el payload del aviso sale de documentos de verdad, no de un dict escrito
a mano. El correo lo recibe un `RecordingProvider`: **nada sale a la red.**

Las cinco promesas, probadas para CADA disparo (parametrizadas por escenario):

1. Empresa y evento encendidos ⇒ exactamente UNA entrega, y sale.
2. Apagado ⇒ el hecho queda registrado (§4.3) pero nada sale.
3. La operación falla después de registrar el aviso ⇒ se revierte con ella:
   ni documento ni aviso (§5.1, «si el abono se revierte, el aviso también»).
4. Un reintento con el mismo `Idempotency-Key` ⇒ un solo evento, una sola
   entrega, un solo correo.
5. Cliente sin correo ⇒ la entrega queda `unroutable`, nunca una ausencia (§1).

Y las decisiones de §18, cada una con su test: el paz y salvo REEMPLAZA al
comprobante del mismo abono; la nota crédito reemplaza al aviso de devolución;
el contrato importado no avisa; el monto de una devolución es el NETO del
documento; y el tope semanal de la Ley 2300 no se come un comprobante.

**El reloj del despachador está fijo** en un martes hábil a las 10:00 de
Bogotá: el envío inmediato respeta la ventana horaria (§18.2-1), y sin esto
estos tests fallarían de noche.
"""

import json
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.core.settings import get_settings
from app.modules.notifications import dispatcher, providers
from app.modules.notifications import service as notifications_service
from app.modules.notifications.providers import RecordingProvider

#: Martes 3 de septiembre de 2030, 10:00 en Bogotá: día hábil, dentro de la
#: ventana de la Ley 2300 y sin festivo.
TUESDAY_10AM = datetime(2030, 9, 3, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
FRONT = "https://app.example.com"


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


async def _rows(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async with AsyncSessionLocal() as s:
        return list((await s.execute(text(sql), params or {})).all())


async def _exec(sql: str, params: dict[str, Any] | None = None) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(text(sql), params or {})


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


# ------------------------------------------------------------------ fixtures ----


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> RecordingProvider:
    recording = RecordingProvider()
    monkeypatch.setattr(providers, "get_default_provider", lambda: recording)
    return recording


@pytest.fixture(autouse=True)
def _fixed_clock_and_links(monkeypatch: pytest.MonkeyPatch) -> Any:
    """El envío inmediato con el reloj fijo, y lo que hace falta para armar el
    enlace de baja (sin él, un correo al cliente queda `dead`, §17.2-9)."""
    monkeypatch.setenv("FRONTEND_URL", FRONT)
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "secreto-de-prueba-de-los-enlaces-de-baja")
    get_settings.cache_clear()
    real = dispatcher.dispatch_delivery

    async def at_fixed_time(delivery_id: UUID, **kwargs: Any) -> str | None:
        return await real(delivery_id, now=TUESDAY_10AM, **kwargs)

    monkeypatch.setattr(dispatcher, "dispatch_delivery", at_fixed_time)
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def shop(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict[str, Any], None]:
    """Empresa con todo lo necesario para empeñar y vender: un rol con TODOS los
    permisos, dos clientes (con correo y autorización expresa, y sin correo),
    el árbol de categorías con plazo y LTV, un lote disponible y la caja ABIERTA.
    Los avisos nacen apagados, como en producción: cada test enciende lo suyo."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    cid, role_id, user_id = uuid4(), uuid4(), uuid4()
    with_mail, without_mail = uuid4(), uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    product_id, item_id, register_id = uuid4(), uuid4(), uuid4()
    p = {"cid": str(cid)}

    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.company (id, name, contact_email, contact_phone) "
                "values (:cid, 'Compraventa Recibos', 'contacto@recibos.example', '3001112233')"
            ),
            p,
        )
        await s.execute(
            text("insert into public.role (id, company_id, name) values (:r, :cid, 'Admin')"),
            {**p, "r": str(role_id)},
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :r, id from public.permission"
            ),
            {"r": str(role_id)},
        )
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:u, :cid, :r, 'Dueña', :e, 'active')"
            ),
            {**p, "u": str(user_id), "r": str(role_id), "e": f"duena-{user_id}@example.com"},
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan, 'active', current_date + 30)"
            ),
            {**p, "plan": str(plan_id)},
        )
        # Con correo y autorización expresa en el mostrador (§9.2-f): la base
        # que no depende de tener un contrato vivo, así sirve también en ventas.
        await s.execute(
            text(
                "insert into public.customer (id, company_id, full_name, doc_type, doc_number, "
                " phone, email, email_basis, email_basis_at, email_consent_at, "
                " email_consent_source) "
                "values (:id, :cid, 'Juana María Pérez', 'cc', :doc, '3000000001', "
                " 'juana@example.com', 'consent', now(), now(), 'counter')"
            ),
            {**p, "id": str(with_mail), "doc": str(uuid4().int)[:10]},
        )
        # §1: el caso NORMAL. Celular sí, correo no.
        await s.execute(
            text(
                "insert into public.customer (id, company_id, full_name, doc_type, doc_number, "
                " phone) values (:id, :cid, 'Pedro Sin Correo', 'cc', :doc, '3000000002')"
            ),
            {**p, "id": str(without_mail), "doc": str(uuid4().int)[:10]},
        )
        await s.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, "
                " code_letter) values (:id, :cid, null, 1, 'Joyería', 'J')"
            ),
            {**p, "id": str(cat1)},
        )
        await s.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, "
                " code_letter) values (:id, :cid, :parent, 2, 'Oro', 'O')"
            ),
            {**p, "id": str(cat2), "parent": str(cat1)},
        )
        await s.execute(
            text(
                "insert into public.category (id, company_id, parent_id, level, name, "
                " code_letter, default_term_months, arrears_window_months, max_ltv_pct) "
                "values (:id, :cid, :parent, 3, 'Cadena', 'C', 4, 4, 70)"
            ),
            {**p, "id": str(cat3), "parent": str(cat2)},
        )
        await s.execute(
            text(
                "insert into public.product "
                "(id, company_id, code, name, cat1_id, cat2_id, cat3_id, sale_price) "
                "values (:id, :cid, 'JOC0001', 'Cadena de oro', :c1, :c2, :c3, 500000)"
            ),
            {**p, "id": str(product_id), "c1": str(cat1), "c2": str(cat2), "c3": str(cat3)},
        )
        await s.execute(
            text(
                "insert into public.inventory_item "
                "(id, company_id, product_id, lot_number, code, origin, cost, quantity, status) "
                "values (:id, :cid, :pid, 1, 'JOC0001-01I', 'other', 300000, 20, 'available')"
            ),
            {**p, "id": str(item_id), "pid": str(product_id)},
        )
        await s.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {**p, "id": str(register_id)},
        )
        await s.execute(
            text(
                "insert into public.cash_session "
                "(company_id, register_id, opened_by, opening_balance, status) "
                "values (:cid, :rid, :cid, 0, 'open')"
            ),
            {**p, "rid": str(register_id)},
        )

    token = make_token(private_pem, sub=str(user_id), company_id=str(cid), role_id=str(role_id))
    yield {
        "company_id": cid,
        "token": token,
        "with_mail": with_mail,
        "without_mail": without_mail,
        "category_id": cat3,
        "item_id": item_id,
    }

    async def _try(sql: str) -> None:
        # Documentos de dinero inmutables (`forbid_change`): lo que no se puede
        # borrar queda huérfano en local, igual que en los otros tests.
        try:
            async with AsyncSessionLocal() as s, s.begin():
                await s.execute(text(sql), p)
        except Exception:
            pass

    for sql in (
        "delete from public.notification_delivery where company_id = :cid",
        "delete from public.notification_event where company_id = :cid",
        "delete from public.credit_note_redemption where company_id = :cid",
        "delete from public.credit_note where company_id = :cid",
        "delete from public.sale_return_line where company_id = :cid",
        "delete from public.sale_return where company_id = :cid",
        "delete from public.sale_line where company_id = :cid",
        "delete from public.sale where company_id = :cid",
        "delete from public.cash_movement where company_id = :cid",
        "delete from public.contract_item where company_id = :cid",
        "delete from public.contract where company_id = :cid",
        "delete from public.inventory_item where company_id = :cid",
        "delete from public.product where company_id = :cid",
        "delete from public.code_counter where company_id = :cid",
        "delete from public.customer where company_id = :cid",
        "delete from public.category where company_id = :cid and level = 3",
        "delete from public.category where company_id = :cid and level = 2",
        "delete from public.category where company_id = :cid and level = 1",
        "delete from public.app_user where company_id = :cid",
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)",
        "delete from public.role where company_id = :cid",
        "delete from public.subscription where company_id = :cid",
        "delete from public.account where company_id = :cid",
        "delete from public.cash_session where company_id = :cid",
        "delete from public.cash_register where company_id = :cid",
        "delete from public.company where id = :cid",
    ):
        await _try(sql)


async def _enable(company_id: UUID, *events: str, limits: dict[str, Any] | None = None) -> None:
    """Enciende la empresa y SOLO los eventos pedidos (el resto, como nacen)."""
    notifications: dict[str, Any] = {"enabled": True, "events": {e: True for e in events}}
    if limits is not None:
        notifications["customer_contact_limits"] = limits
    await _exec(
        "update public.company set settings = jsonb_set(coalesce(settings, '{}'::jsonb), "
        "'{notifications}', cast(:n as jsonb)) where id = :cid",
        {"cid": str(company_id), "n": json.dumps(notifications)},
    )


async def _events(company_id: UUID) -> list[Any]:
    return await _rows(
        "select id, event_type, dedupe_key, customer_id, entity_type, entity_id, payload "
        "from public.notification_event where company_id = :cid and audience = 'customer' "
        "order by created_at",
        {"cid": str(company_id)},
    )


async def _deliveries(company_id: UUID) -> list[Any]:
    return await _rows(
        "select d.id, d.status, d.to_address, d.legal_basis, e.event_type, e.dedupe_key "
        "from public.notification_delivery d join public.notification_event e "
        "  on e.id = d.event_id "
        "where d.company_id = :cid and e.audience = 'customer' order by d.created_at",
        {"cid": str(company_id)},
    )


# ----------------------------------------------------------------- operaciones ----


def _contract(client: TestClient, shop: dict[str, Any], customer: UUID, **extra: Any) -> Any:
    body = {
        "customer_id": str(customer),
        "principal": "1000000.00",
        "interest_rate_pct": "5",
        "appraisal_value": "2000000.00",
        "payment_method": "cash",
        "items": [{"category_id": str(shop["category_id"]), "description": "Cadena de oro 10g"}],
        **extra,
    }
    return client.post(
        "/api/v1/contracts", headers=_headers(shop["token"], str(uuid4())), json=body
    )


def _sale(client: TestClient, shop: dict[str, Any], customer: UUID | None, **extra: Any) -> Any:
    body: dict[str, Any] = {
        "customer_id": str(customer) if customer else None,
        "payment_method": "cash",
        "lines": [{"item_id": str(shop["item_id"]), "quantity": "2", "unit_price": "500000.00"}],
        **extra,
    }
    return client.post("/api/v1/sales", headers=_headers(shop["token"], str(uuid4())), json=body)


@dataclass(frozen=True)
class Scenario:
    """Un disparo: qué evento produce, cómo se prepara (lo que NO es el
    disparo) y el disparo en sí, con su `Idempotency-Key`."""

    event_type: str
    #: Prepara lo previo (un contrato para abonar, una venta para anular…).
    setup: Callable[[TestClient, dict[str, Any], UUID], dict[str, Any]]
    #: El disparo. Recibe la llave de idempotencia (o None si el endpoint no la usa).
    act: Callable[[TestClient, dict[str, Any], dict[str, Any], str], Any]
    #: La `dedupe_key` exacta, construida con el documento (§6.1).
    dedupe_key: Callable[[dict[str, Any], dict[str, Any]], str]
    #: Status HTTP del éxito.
    ok: int = 201
    #: Cómo responde el endpoint a un reintento: 201/200 = misma respuesta
    #: (idempotente por llave), 409 = no admite repetirse.
    retry_status: int | None = None


def _nothing(client: TestClient, shop: dict[str, Any], customer: UUID) -> dict[str, Any]:
    return {"customer": customer}


def _with_contract(client: TestClient, shop: dict[str, Any], customer: UUID) -> dict[str, Any]:
    response = _contract(client, shop, customer)
    assert response.status_code == 201, response.text
    return {"customer": customer, "contract": response.json()}


def _with_sale(client: TestClient, shop: dict[str, Any], customer: UUID) -> dict[str, Any]:
    response = _sale(client, shop, customer)
    assert response.status_code == 201, response.text
    return {"customer": customer, "sale": response.json()}


def _pay(capital: str) -> Callable[[TestClient, dict[str, Any], dict[str, Any], str], Any]:
    def act(client: TestClient, shop: dict[str, Any], ctx: dict[str, Any], key: str) -> Any:
        return client.post(
            f"/api/v1/contracts/{ctx['contract']['id']}/payments",
            headers=_headers(shop["token"], key),
            json={"months_covered": 0, "capital_amount": capital, "payment_method": "cash"},
        )

    return act


def _return(method: str) -> Callable[[TestClient, dict[str, Any], dict[str, Any], str], Any]:
    def act(client: TestClient, shop: dict[str, Any], ctx: dict[str, Any], key: str) -> Any:
        return client.post(
            f"/api/v1/sales/{ctx['sale']['id']}/returns",
            headers=_headers(shop["token"], key),
            json={
                "lines": [{"sale_line_id": ctx["sale"]["lines"][0]["id"], "quantity": "1"}],
                "reason": "change_of_mind",
                "settlement_method": method,
            },
        )

    return act


SCENARIOS: dict[str, Scenario] = {
    "C1": Scenario(
        "contract_created",
        _nothing,
        lambda c, s, ctx, key: c.post(
            "/api/v1/contracts",
            headers=_headers(s["token"], key),
            json={
                "customer_id": str(ctx["customer"]),
                "principal": "1000000.00",
                "interest_rate_pct": "5",
                "payment_method": "cash",
                "items": [
                    {"category_id": str(s["category_id"]), "description": "Cadena de oro 10g"}
                ],
            },
        ),
        lambda ctx, body: f"contract:{body['id']}",
    ),
    "C2": Scenario(
        "payment_registered",
        _with_contract,
        _pay("200000.00"),
        lambda ctx, body: f"payment:{body['id']}",
    ),
    "C3": Scenario(
        "contract_paid_off",
        _with_contract,
        _pay("1000000.00"),
        lambda ctx, body: f"payment:{body['id']}",
    ),
    "C4": Scenario(
        "loan_extended",
        _with_contract,
        lambda c, s, ctx, key: c.post(
            f"/api/v1/contracts/{ctx['contract']['id']}/extend-loan",
            headers=_headers(s["token"], key),
            json={"amount": "300000.00", "payment_method": "cash"},
        ),
        lambda ctx, body: f"extend:{body['id']}",
    ),
    "C5": Scenario(
        "credit_note_issued",
        _with_sale,
        _return("credit_note"),
        lambda ctx, body: f"return:{body['id']}",
    ),
    "C6": Scenario(
        "sale_receipt",
        _nothing,
        lambda c, s, ctx, key: c.post(
            "/api/v1/sales",
            headers=_headers(s["token"], key),
            json={
                "customer_id": str(ctx["customer"]),
                "payment_method": "cash",
                "lines": [
                    {"item_id": str(s["item_id"]), "quantity": "1", "unit_price": "500000.00"}
                ],
            },
        ),
        lambda ctx, body: f"sale:{body['id']}",
    ),
    "C7-anulación": Scenario(
        "sale_reversed",
        _with_sale,
        lambda c, s, ctx, key: c.post(
            f"/api/v1/sales/{ctx['sale']['id']}/void",
            headers=_headers(s["token"]),
            json={"reason": "Error de digitación"},
        ),
        lambda ctx, body: f"sale_void:{body['id']}",
        ok=200,
        retry_status=409,
    ),
    "C7-devolución": Scenario(
        "sale_reversed",
        _with_sale,
        _return("cash"),
        lambda ctx, body: f"return:{body['id']}",
    ),
}

_IDS = list(SCENARIOS)


def _run(
    client: TestClient, shop: dict[str, Any], sc: Scenario, customer: UUID
) -> tuple[dict[str, Any], Any]:
    ctx = sc.setup(client, shop, customer)
    return ctx, sc.act(client, shop, ctx, str(uuid4()))


# ------------------------------------------------ las cinco promesas, por disparo ----


@pytest.mark.parametrize("name", _IDS)
async def test_on_it_produces_exactly_one_delivery_and_it_goes_out(
    name: str, client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    sc = SCENARIOS[name]
    await _enable(shop["company_id"], sc.event_type)
    ctx, response = _run(client, shop, sc, shop["with_mail"])
    assert response.status_code == sc.ok, response.text

    [delivery] = await _deliveries(shop["company_id"])
    d = delivery._mapping
    assert d["event_type"] == sc.event_type
    assert d["dedupe_key"] == sc.dedupe_key(ctx, response.json())
    assert d["status"] == "sent"
    assert d["to_address"] == "juana@example.com"
    assert d["legal_basis"] == "consent"
    [message] = outbox.outbox
    assert message.to == "juana@example.com"
    assert message.subject.startswith("Compraventa Recibos · ")
    # §9.1: la prenda y los artículos NO van, ni la cédula.
    for body in (message.text, message.html, message.subject):
        assert "Cadena" not in body
        assert "JOC0001" not in body
    assert f"{FRONT}/baja/" in message.text


@pytest.mark.parametrize("name", _IDS)
async def test_off_the_fact_is_recorded_but_nothing_goes_out(
    name: str, client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Como nace en producción: el interruptor de la empresa apagado. §4.3: el
    hecho se registra igual (es el latido y el insumo del agregado), pero sin
    entregas."""
    sc = SCENARIOS[name]
    ctx, response = _run(client, shop, sc, shop["with_mail"])
    assert response.status_code == sc.ok, response.text
    events = [e for e in await _events(shop["company_id"]) if e.event_type == sc.event_type]
    assert [e.dedupe_key for e in events] == [sc.dedupe_key(ctx, response.json())]
    assert await _deliveries(shop["company_id"]) == []
    assert outbox.outbox == []


@pytest.mark.parametrize("name", _IDS)
async def test_the_company_on_but_the_event_off_sends_nothing(
    name: str, client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    sc = SCENARIOS[name]
    await _enable(shop["company_id"])  # la empresa sí, el evento no (nace apagado)
    _, response = _run(client, shop, sc, shop["with_mail"])
    assert response.status_code == sc.ok, response.text
    assert await _deliveries(shop["company_id"]) == []
    assert outbox.outbox == []


@pytest.mark.parametrize("name", _IDS)
async def test_if_the_operation_fails_after_recording_the_notice_both_roll_back(
    name: str,
    client: TestClient,
    shop: dict[str, Any],
    outbox: RecordingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El aviso va DENTRO de la transacción del documento (§5.1). Se fuerza una
    falla justo DESPUÉS de registrarlo: si el aviso viviera en otra
    transacción, quedaría un aviso de un abono que no existe."""
    sc = SCENARIOS[name]
    await _enable(shop["company_id"], sc.event_type)
    ctx = sc.setup(client, shop, shop["with_mail"])
    before = len(await _events(shop["company_id"]))
    real = notifications_service.record_event
    recorded: list[str] = []

    async def record_then_fail(*args: Any, **kwargs: Any) -> Any:
        await real(*args, **kwargs)
        recorded.append(kwargs["event_type"])
        raise RuntimeError("falla después de registrar el aviso")

    monkeypatch.setattr(notifications_service, "record_event", record_then_fail)
    with pytest.raises(RuntimeError, match="después de registrar el aviso"):
        sc.act(client, shop, ctx, str(uuid4()))

    assert recorded == [sc.event_type]
    assert len(await _events(shop["company_id"])) == before
    assert await _deliveries(shop["company_id"]) == []
    assert outbox.outbox == []


@pytest.mark.parametrize("name", _IDS)
async def test_an_idempotent_retry_does_not_duplicate_the_notice(
    name: str, client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    sc = SCENARIOS[name]
    await _enable(shop["company_id"], sc.event_type)
    ctx = sc.setup(client, shop, shop["with_mail"])
    key = str(uuid4())
    first = sc.act(client, shop, ctx, key)
    assert first.status_code == sc.ok, first.text
    again = sc.act(client, shop, ctx, key)
    assert again.status_code == (sc.retry_status or sc.ok), again.text
    if sc.retry_status is None:
        assert again.json()["id"] == first.json()["id"]

    events = [e for e in await _events(shop["company_id"]) if e.event_type == sc.event_type]
    assert len(events) == 1
    assert len(await _deliveries(shop["company_id"])) == 1
    assert len(outbox.outbox) == 1


@pytest.mark.parametrize("name", _IDS)
async def test_a_customer_without_email_leaves_an_unroutable_delivery(
    name: str, client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    sc = SCENARIOS[name]
    await _enable(shop["company_id"], sc.event_type)
    ctx, response = _run(client, shop, sc, shop["without_mail"])
    assert response.status_code == sc.ok, response.text
    [delivery] = await _deliveries(shop["company_id"])
    assert delivery.status == "unroutable"
    assert delivery.to_address is None
    assert delivery.dedupe_key == sc.dedupe_key(ctx, response.json())
    assert outbox.outbox == []


# ------------------------------------------------------------ las decisiones ----


async def test_the_payoff_sends_ONE_mail_the_paid_off_and_not_also_the_receipt(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§18.1-3: un abono, un aviso. El que salda el contrato manda el paz y
    salvo, que además dice cuánto se pagó y con qué recibo: el comprobante no
    se pierde, se incluye."""
    await _enable(shop["company_id"], "payment_registered", "contract_paid_off")
    ctx = _with_contract(client, shop, shop["with_mail"])
    payment = _pay("1000000.00")(client, shop, ctx, str(uuid4()))
    assert payment.status_code == 201, payment.text
    p = payment.json()

    [delivery] = await _deliveries(shop["company_id"])
    assert delivery.event_type == "contract_paid_off"
    assert delivery.dedupe_key == f"payment:{p['id']}"
    [message] = outbox.outbox
    number = ctx["contract"]["number"]
    assert f"Paz y salvo del contrato #{number}" in message.subject
    assert "$1.000.000" in message.text
    assert f"recibo #{p['receipt_number']}" in message.text
    assert "No nos debe nada" in message.text


async def test_with_paid_off_turned_off_the_payoff_still_gets_its_receipt(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Si la empresa apagó el paz y salvo pero dejó el comprobante, el último
    abono igual tiene su comprobante: apagar un aviso no puede apagar otro."""
    await _enable(shop["company_id"], "payment_registered")
    ctx = _with_contract(client, shop, shop["with_mail"])
    payment = _pay("1000000.00")(client, shop, ctx, str(uuid4()))
    assert payment.status_code == 201, payment.text
    [delivery] = await _deliveries(shop["company_id"])
    assert delivery.event_type == "payment_registered"
    assert delivery.status == "sent"
    assert "Saldo de capital: $0" in outbox.outbox[0].text


async def test_a_credit_note_return_sends_the_credit_note_and_not_also_the_reversal(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    await _enable(shop["company_id"], "credit_note_issued", "sale_reversed")
    ctx = _with_sale(client, shop, shop["with_mail"])
    response = _return("credit_note")(client, shop, ctx, str(uuid4()))
    assert response.status_code == 201, response.text
    [delivery] = await _deliveries(shop["company_id"])
    assert delivery.event_type == "credit_note_issued"
    note = await _rows(
        "select number from public.credit_note where sale_return_id = :id",
        {"id": response.json()["id"]},
    )
    assert f"nota crédito #{note[0].number}" in outbox.outbox[0].text
    assert f"#{ctx['sale']['number']}" in outbox.outbox[0].text


async def test_with_credit_note_off_the_return_still_gets_its_reversal(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    await _enable(shop["company_id"], "sale_reversed")
    ctx = _with_sale(client, shop, shop["with_mail"])
    response = _return("credit_note")(client, shop, ctx, str(uuid4()))
    assert response.status_code == 201, response.text
    [delivery] = await _deliveries(shop["company_id"])
    assert delivery.event_type == "sale_reversed"
    assert "nota crédito" in outbox.outbox[0].text


async def test_the_return_amount_is_the_NET_of_the_document_not_the_gross(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """F21-33: una venta con descuento devuelve lo que el cliente PAGÓ por lo
    devuelto. 2 × 500.000 con 100.000 de descuento ⇒ devolver 1 son 450.000,
    no 500.000. El monto sale del documento (`total_amount`), nunca se
    recalcula en la plantilla."""
    await _enable(shop["company_id"], "sale_reversed")
    sale = _sale(
        client, shop, shop["with_mail"], discount_amount="100000.00", discount_reason="Cliente fiel"
    )
    assert sale.status_code == 201, sale.text
    ctx = {"sale": sale.json()}
    response = _return("cash")(client, shop, ctx, str(uuid4()))
    assert response.status_code == 201, response.text
    assert response.json()["total_amount"] == "450000.00"
    # La venta también dejó su hecho (C6, apagado): se mira solo el de la devolución.
    [event] = [e for e in await _events(shop["company_id"]) if e.event_type == "sale_reversed"]
    assert event.payload["amount"] == "450000.00"
    assert "$450.000" in outbox.outbox[0].text
    assert "$500.000" not in outbox.outbox[0].text


async def test_voiding_names_the_voided_amount_from_the_document(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    await _enable(shop["company_id"], "sale_reversed")
    ctx = _with_sale(client, shop, shop["with_mail"])
    response = client.post(
        f"/api/v1/sales/{ctx['sale']['id']}/void",
        headers=_headers(shop["token"]),
        json={"reason": "Error de digitación"},
    )
    assert response.status_code == 200, response.text
    text_ = outbox.outbox[0].text
    assert "anulación" in text_
    assert "$1.000.000" in text_


async def test_a_sale_without_customer_records_nothing(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§2.1: una venta de mostrador sin cliente no tiene a quién avisarle, y
    eso no es un hueco: es el negocio. Ni evento ni entrega."""
    await _enable(shop["company_id"], "sale_receipt")
    response = _sale(client, shop, None)
    assert response.status_code == 201, response.text
    assert await _events(shop["company_id"]) == []
    assert outbox.outbox == []


async def test_an_imported_contract_does_not_notify(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§3 y §18.1-5: `import_contract` es carga de datos históricos. El
    préstamo se entregó en otro sistema; avisarle «registramos su contrato»
    de algo que ya tenía es confuso, y una migración de 200 contratos sería
    una tanda de 200 correos sobre nada."""
    await _enable(shop["company_id"], "contract_created")
    response = client.post(
        "/api/v1/contracts/import",
        headers=_headers(shop["token"], str(uuid4())),
        json={
            "customer_id": str(shop["with_mail"]),
            "legacy_code": "VIEJO-001",
            "principal": "500000.00",
            "capital_balance": "500000.00",
            "interest_rate_pct": "5",
            "term_months": 4,
            "arrears_window_months": 4,
            "start_date": "2026-06-01",
            "interest_paid_until": "2026-09-01",
            "items": [{"category_id": str(shop["category_id"]), "description": "Anillo"}],
        },
    )
    assert response.status_code == 201, response.text
    assert await _events(shop["company_id"]) == []
    assert outbox.outbox == []


async def test_the_extension_mail_names_both_contracts_and_the_unmoved_due_date(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§2.1, C4: el cliente se va con un papel nuevo; si vuelve con el viejo,
    no le aceptan el abono. El correo nombra los DOS números, lo entregado y
    la fecha de cobro — que con `keep_anchor` no se movió (00053)."""
    await _enable(shop["company_id"], "loan_extended")
    ctx = _with_contract(client, shop, shop["with_mail"])
    old = ctx["contract"]
    response = SCENARIOS["C4"].act(client, shop, ctx, str(uuid4()))
    assert response.status_code == 201, response.text
    new = response.json()
    text_ = outbox.outbox[0].text
    assert f"#{old['number']}" in text_
    assert f"#{new['number']}" in text_
    assert "$300.000" in text_
    assert "$1.300.000" in text_
    assert "no cambió" in text_


async def test_a_second_receipt_in_the_same_week_is_not_throttled(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§18.1-1: el tope semanal de la Ley 2300 es de contactos de COBRANZA. Un
    comprobante de abono no es cobranza: con el tope aplicado, el segundo abono
    de la semana quedaba `throttled` y el cliente sin su comprobante."""
    await _enable(shop["company_id"], "payment_registered")
    ctx = _with_contract(client, shop, shop["with_mail"])
    for _ in range(2):
        paid = _pay("100000.00")(client, shop, ctx, str(uuid4()))
        assert paid.status_code == 201, paid.text
    assert [d.status for d in await _deliveries(shop["company_id"])] == ["sent", "sent"]
    assert len(outbox.outbox) == 2


async def test_the_lawyers_answer_is_configuration_receipts_can_count_again(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Si el abogado dice que un comprobante SÍ es un contacto bajo la Ley 2300,
    es un parámetro, no un rediseño: vuelve el comportamiento de antes."""
    await _enable(
        shop["company_id"], "payment_registered", limits={"transactional_in_weekly_cap": True}
    )
    ctx = _with_contract(client, shop, shop["with_mail"])
    for _ in range(2):
        assert _pay("100000.00")(client, shop, ctx, str(uuid4())).status_code == 201
    assert [d.status for d in await _deliveries(shop["company_id"])] == ["sent", "throttled"]


async def test_the_daily_cap_still_counts_receipts(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§3: el tope de 3 correos por cliente por día cuenta los transaccionales —
    es la regla de producto contra el cliente de 13 contratos, no la Ley 2300."""
    await _enable(shop["company_id"], "payment_registered")
    ctx = _with_contract(client, shop, shop["with_mail"])
    for _ in range(4):
        assert _pay("100000.00")(client, shop, ctx, str(uuid4())).status_code == 201
    statuses = [d.status for d in await _deliveries(shop["company_id"])]
    assert statuses == ["sent", "sent", "sent", "throttled"]


async def _send_reminder_now(company_id: UUID, customer_id: UUID) -> str:
    """Una entrega de recordatorio (R1) planificada a mano y despachada con el
    mismo reloj fijo: para ver qué cuenta el tope semanal."""
    async with AsyncSessionLocal() as s, s.begin():
        event_id = (
            await s.execute(
                text(
                    "insert into public.notification_event (company_id, event_type, audience, "
                    " customer_id, payload, dedupe_key, occurred_on) values (:cid, "
                    " 'installment_due_soon', 'customer', :cust, cast(:p as jsonb), :k, "
                    " date '2030-09-03') returning id"
                ),
                {
                    "cid": str(company_id),
                    "cust": str(customer_id),
                    "p": '{"due_date": "2030-09-06", "contracts": []}',
                    "k": f"due_soon:{uuid4()}",
                },
            )
        ).scalar_one()
        delivery_id = (
            await s.execute(
                text(
                    "insert into public.notification_delivery (company_id, event_id, channel, "
                    " to_address, status, legal_basis) values (:cid, :e, 'email', "
                    " 'juana@example.com', 'pending', 'consent') returning id"
                ),
                {"cid": str(company_id), "e": str(event_id)},
            )
        ).scalar_one()
    return await dispatcher.dispatch_delivery(delivery_id) or ""


async def test_a_receipt_does_not_spend_the_weekly_budget_of_a_reminder(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """La otra mitad de la misma premisa: si un comprobante no es cobranza, no
    gasta el cupo semanal de la cobranza. Un recordatorio después de un abono
    sale; dos recordatorios en la semana, no."""
    await _enable(shop["company_id"], "payment_registered", "installment_due_soon")
    ctx = _with_contract(client, shop, shop["with_mail"])
    assert _pay("100000.00")(client, shop, ctx, str(uuid4())).status_code == 201
    assert await _send_reminder_now(shop["company_id"], shop["with_mail"]) == "sent"
    assert await _send_reminder_now(shop["company_id"], shop["with_mail"]) == "throttled"


# ------------------------------------ F21-37: la devolución de liquidación mixta ----


def _mixed_sale(client: TestClient, shop: dict[str, Any]) -> dict[str, Any]:
    """Venta de 800.000 pagada con 500.000 de nota + 300.000 en efectivo. La
    nota sale de una venta anterior devuelta en nota (con los avisos todavía
    apagados: ese hecho queda registrado, pero no es el que se mira)."""
    first = _sale(
        client,
        shop,
        shop["with_mail"],
        lines=[{"item_id": str(shop["item_id"]), "quantity": "1", "unit_price": "500000.00"}],
    )
    assert first.status_code == 201, first.text
    ret = _return("credit_note")(client, shop, {"sale": first.json()}, str(uuid4()))
    assert ret.status_code == 201, ret.text
    sale = _sale(
        client,
        shop,
        shop["with_mail"],
        lines=[{"item_id": str(shop["item_id"]), "quantity": "1", "unit_price": "800000.00"}],
        credit_note_id=ret.json()["credit_note_id"],
        credit_note_amount="500000.00",
    )
    assert sale.status_code == 201, sale.text
    return {"sale": sale.json()}


async def test_a_mixed_return_sends_ONE_notice_that_names_both_amounts(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """F21-37: devuelta en efectivo, la venta mixta liquida 300.000 en
    efectivo y una nota NUEVA de 500.000. Es UNA devolución: un evento, una
    entrega, un correo —el de la nota crédito, que es el más específico— y
    dice los dos montos. Ni un segundo aviso por el efectivo, ni el total de
    800.000 como si todo hubiera salido del cajón."""
    ctx = _mixed_sale(client, shop)
    await _enable(shop["company_id"], "credit_note_issued", "sale_reversed")
    response = _return("cash")(client, shop, ctx, str(uuid4()))
    assert response.status_code == 201, response.text
    body = response.json()

    events = [e for e in await _events(shop["company_id"]) if e.entity_id == UUID(body["id"])]
    [event] = events
    assert event.dedupe_key == f"return:{body['id']}"
    assert event.event_type == "credit_note_issued"
    assert event.payload["amount"] == "800000.00"
    assert event.payload["credit_note_amount"] == "500000.00"
    assert event.payload["refunded_amount"] == "300000.00"
    assert event.payload["credit_note_number"] == body["credit_note_number"]

    [delivery] = [
        d for d in await _deliveries(shop["company_id"]) if d.dedupe_key == event.dedupe_key
    ]
    assert delivery.status == "sent"
    [message] = outbox.outbox
    assert f"nota crédito #{body['credit_note_number']} por $500.000" in message.text
    assert "$300.000" in message.text
    assert "$800.000" not in message.text


async def test_a_mixed_return_with_credit_note_off_still_names_both_amounts(
    client: TestClient, shop: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Con la nota crédito apagada sale el aviso de devolución (§18.1-3), y
    tampoco puede callar la nota: dice lo devuelto y lo que quedó en nota."""
    ctx = _mixed_sale(client, shop)
    await _enable(shop["company_id"], "sale_reversed")
    response = _return("cash")(client, shop, ctx, str(uuid4()))
    assert response.status_code == 201, response.text
    body = response.json()
    [event] = [e for e in await _events(shop["company_id"]) if e.entity_id == UUID(body["id"])]
    assert event.event_type == "sale_reversed"
    [message] = outbox.outbox
    assert "Le devolvimos $300.000" in message.text
    assert f"nota crédito #{body['credit_note_number']} por $500.000" in message.text
    assert "$800.000" not in message.text
