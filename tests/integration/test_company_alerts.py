"""Las alertas inmediatas a la empresa (docs/NOTIFICACIONES.md §2.5, §19): fase 7.

Cuatro actos —anular una venta (A1), un descuento en venta o en abono (A2), un
retiro de capital del dueño (A3) y reabrir una caja (A4)— avisan el MISMO día a
quien tiene `notifications.receive_alerts`. Contra Postgres real y contra la API
real: cada documento se crea por el endpoint que usa el front, así que el
payload de la alerta sale de documentos de verdad. El correo lo recibe un
`RecordingProvider`: **nada sale a la red.**

El reparto de la empresa del fixture es el que decide los destinatarios:

- **Dueña** y **Socio**: rol Admin, con el permiso. Reciben.
- **Exsocio**: rol Admin, con el permiso, pero `inactive`. No recibe nunca.
- **Cajero**: todos los permisos de operar (anular, descontar, retirar,
  reabrir) y NINGUNO de recibir. Es quien hace los actos: la alerta existe para
  que otro se entere.

**El reloj del envío inmediato está fijo en un domingo a las 23:00** de Bogotá:
fuera de toda ventana hábil. Si la alerta respetara la ventana de la Ley 2300
—que es del cliente, no de la empresa—, estos tests no verían salir ningún correo.
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
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.modules.notifications import dispatcher, providers
from app.modules.notifications import service as notifications_service
from app.modules.notifications.providers import RecordingProvider

#: Domingo 1 de septiembre de 2030, 23:00 en Bogotá: fuera de la ventana hábil.
SUNDAY_11PM = datetime(2030, 9, 1, 23, 0, tzinfo=ZoneInfo("America/Bogota"))
COMPANY = "Compraventa Alertas"
RECEIVE = ("notifications.receive_alerts", "notifications.receive_digest")


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
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    real = dispatcher.dispatch_delivery

    async def at_fixed_time(delivery_id: UUID, **kwargs: Any) -> str | None:
        return await real(delivery_id, now=SUNDAY_11PM, **kwargs)

    monkeypatch.setattr(dispatcher, "dispatch_delivery", at_fixed_time)


@pytest_asyncio.fixture
async def firm(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict[str, Any], None]:
    """Empresa con dos Admin activos (Dueña, Socio), uno inactivo (Exsocio) y
    un Cajero que opera todo sin recibir nada; un cliente SIN correo (para que
    el aviso al cliente no se mezcle), el árbol de categorías, un lote, las
    cuentas de caja y banco, y la caja ABIERTA. Los avisos nacen apagados."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))
    cid, admin_role, cashier_role = uuid4(), uuid4(), uuid4()
    owner, partner, former, cashier = uuid4(), uuid4(), uuid4(), uuid4()
    customer = uuid4()
    cat1, cat2, cat3 = uuid4(), uuid4(), uuid4()
    product_id, item_id, register_id, session_id = uuid4(), uuid4(), uuid4(), uuid4()
    p = {"cid": str(cid)}
    emails = {
        "owner": f"duena-{owner}@example.com",
        "partner": f"socio-{partner}@example.com",
        "former": f"exsocio-{former}@example.com",
        "cashier": f"cajero-{cashier}@example.com",
    }

    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.company (id, name, contact_email, contact_phone) "
                "values (:cid, :name, 'contacto@alertas.example', '3001112233')"
            ),
            {**p, "name": COMPANY},
        )
        await s.execute(
            text(
                "insert into public.role (id, company_id, name) values "
                "(:a, :cid, 'Admin'), (:c, :cid, 'Cajero')"
            ),
            {**p, "a": str(admin_role), "c": str(cashier_role)},
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :r, id from public.permission"
            ),
            {"r": str(admin_role)},
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :r, id from public.permission where code not in :receive"
            ).bindparams(bindparam("receive", expanding=True)),
            {"r": str(cashier_role), "receive": list(RECEIVE)},
        )
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:o, :cid, :a, 'Dueña Pérez', :oe, 'active'), "
                "(:p, :cid, :a, 'Socio Gómez', :pe, 'active'), "
                "(:f, :cid, :a, 'Exsocio Ruiz', :fe, 'inactive'), "
                "(:c, :cid, :cr, 'Cajero Díaz', :ce, 'active')"
            ),
            {
                **p,
                "o": str(owner),
                "p": str(partner),
                "f": str(former),
                "c": str(cashier),
                "a": str(admin_role),
                "cr": str(cashier_role),
                "oe": emails["owner"],
                "pe": emails["partner"],
                "fe": emails["former"],
                "ce": emails["cashier"],
            },
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan, 'active', current_date + 30)"
            ),
            {**p, "plan": str(plan_id)},
        )
        await s.execute(
            text(
                "insert into public.customer (id, company_id, full_name, doc_type, doc_number, "
                " phone) values (:id, :cid, 'Juana Cliente Reservada', 'cc', :doc, '3000000001')"
            ),
            {**p, "id": str(customer), "doc": "1098765432"},
        )
        for cat_id, parent, level, name, letter in (
            (cat1, None, 1, "Joyería", "J"),
            (cat2, cat1, 2, "Oro", "O"),
        ):
            await s.execute(
                text(
                    "insert into public.category (id, company_id, parent_id, level, name, "
                    " code_letter) values (:id, :cid, :parent, :level, :name, :letter)"
                ),
                {
                    **p,
                    "id": str(cat_id),
                    "parent": str(parent) if parent else None,
                    "level": level,
                    "name": name,
                    "letter": letter,
                },
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
                "values (:id, :cid, :pid, 1, 'JOC0001-01I', 'other', 300000, 50, 'available')"
            ),
            {**p, "id": str(item_id), "pid": str(product_id)},
        )
        for name, kind in (("Caja principal", "cash"), ("Banco", "bank")):
            await s.execute(
                text(
                    "insert into public.account (company_id, name, type, is_default) "
                    "values (:cid, :name, :type, true)"
                ),
                {**p, "name": name, "type": kind},
            )
        await s.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {**p, "id": str(register_id)},
        )
        await s.execute(
            text(
                "insert into public.cash_session "
                "(id, company_id, register_id, opened_by, opening_balance, status) "
                "values (:id, :cid, :rid, :uid, 0, 'open')"
            ),
            {**p, "id": str(session_id), "rid": str(register_id), "uid": str(cashier)},
        )
        cash_account = (
            await s.execute(
                text("select id from public.account where company_id = :cid and type = 'cash'"),
                p,
            )
        ).scalar_one()

    def token(user_id: UUID, role_id: UUID) -> str:
        return make_token(private_pem, sub=str(user_id), company_id=str(cid), role_id=str(role_id))

    yield {
        "company_id": cid,
        "customer": customer,
        "category_id": cat3,
        "item_id": item_id,
        "session_id": session_id,
        "cash_account": cash_account,
        "emails": emails,
        "ids": {"owner": owner, "partner": partner, "former": former, "cashier": cashier},
        "tokens": {
            "cashier": token(cashier, cashier_role),
            "owner": token(owner, admin_role),
        },
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
        "delete from public.sale_line where company_id = :cid",
        "delete from public.sale where company_id = :cid",
        "delete from public.capital_movement where company_id = :cid",
        "delete from public.cash_movement where company_id = :cid",
        "delete from public.contract_payment where company_id = :cid",
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
        "delete from public.cash_session where company_id = :cid",
        "delete from public.account where company_id = :cid",
        "delete from public.cash_register where company_id = :cid",
        "delete from public.company where id = :cid",
    ):
        await _try(sql)


async def _settings(
    company_id: UUID,
    *,
    enabled: bool = True,
    events: dict[str, bool] | None = None,
    discount_threshold: str | None = None,
) -> None:
    notifications: dict[str, Any] = {"enabled": enabled, "events": events or {}}
    if discount_threshold is not None:
        notifications["thresholds"] = {"discount_amount": discount_threshold}
    await _exec(
        "update public.company set settings = jsonb_set(coalesce(settings, '{}'::jsonb), "
        "'{notifications}', cast(:n as jsonb)) where id = :cid",
        {"cid": str(company_id), "n": json.dumps(notifications)},
    )


async def _alert_events(company_id: UUID) -> list[Any]:
    return await _rows(
        "select id, event_type, dedupe_key, entity_type, entity_id, payload, customer_id "
        "from public.notification_event where company_id = :cid and audience = 'company' "
        "and event_type like 'alert_%' order by created_at",
        {"cid": str(company_id)},
    )


async def _alert_deliveries(company_id: UUID) -> list[Any]:
    return await _rows(
        "select d.id, d.status, d.to_address, d.recipient_user_id, e.event_type, e.dedupe_key "
        "from public.notification_delivery d join public.notification_event e "
        "  on e.id = d.event_id "
        "where d.company_id = :cid and e.event_type like 'alert_%' order by d.to_address",
        {"cid": str(company_id)},
    )


# ----------------------------------------------------------------- operaciones ----


def _sale(client: TestClient, firm: dict[str, Any], token: str, key: str, **extra: Any) -> Any:
    body: dict[str, Any] = {
        "payment_method": "cash",
        "lines": [{"item_id": str(firm["item_id"]), "quantity": "2", "unit_price": "500000.00"}],
        **extra,
    }
    return client.post("/api/v1/sales", headers=_headers(token, key), json=body)


@dataclass(frozen=True)
class Scenario:
    event_type: str
    #: Prepara lo previo con el token del Cajero (una venta para anular…).
    setup: Callable[[TestClient, dict[str, Any]], dict[str, Any]]
    #: El acto. Recibe el token de quien lo hace y la llave de idempotencia.
    act: Callable[[TestClient, dict[str, Any], dict[str, Any], str, str], Any]
    #: La `dedupe_key` exacta, construida con el documento (§6.1, §19.1-2).
    dedupe_key: Callable[[dict[str, Any], dict[str, Any]], str]
    ok: int = 201
    #: 409 = el endpoint no admite repetirse (no lleva `Idempotency-Key`).
    retry_status: int | None = None


def _nothing(client: TestClient, firm: dict[str, Any]) -> dict[str, Any]:
    return {}


def _with_sale(client: TestClient, firm: dict[str, Any]) -> dict[str, Any]:
    response = _sale(client, firm, firm["tokens"]["cashier"], str(uuid4()))
    assert response.status_code == 201, response.text
    return {"sale": response.json()}


def _with_owed_contract(client: TestClient, firm: dict[str, Any]) -> dict[str, Any]:
    """Un contrato con un mes de interés adeudado: sin interés no hay qué
    descontar (el descuento de un abono sale del interés)."""
    response = client.post(
        "/api/v1/contracts",
        headers=_headers(firm["tokens"]["cashier"], str(uuid4())),
        json={
            "customer_id": str(firm["customer"]),
            "principal": "1000000.00",
            "interest_rate_pct": "5",
            "appraisal_value": "2000000.00",
            "payment_method": "cash",
            "items": [{"category_id": str(firm["category_id"]), "description": "Cadena 10g"}],
        },
    )
    assert response.status_code == 201, response.text
    # El atraso se fabrica en la base (como `test_contracts.py`): el contrato
    # es de verdad, lo único que se corre es su ancla.
    return {"contract": response.json(), "backdate": response.json()["id"]}


def _with_contribution(client: TestClient, firm: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/v1/capital/contributions",
        headers=_headers(firm["tokens"]["owner"], str(uuid4())),
        json={
            "account_id": str(firm["cash_account"]),
            "amount": "5000000.00",
            "notes": "Capital para prestar",
        },
    )
    assert response.status_code == 201, response.text
    return {}


def _with_closed_session(client: TestClient, firm: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/cashbox/sessions/{firm['session_id']}/close",
        headers=_headers(firm["tokens"]["cashier"]),
        json={"counted_cash": "0.00", "difference_reason": "Conteo del cierre"},
    )
    assert response.status_code == 200, response.text
    return {"closed": response.json()}


def _void(c: TestClient, f: dict[str, Any], ctx: dict[str, Any], token: str, key: str) -> Any:
    return c.post(
        f"/api/v1/sales/{ctx['sale']['id']}/void",
        headers=_headers(token),
        json={"reason": "Cobro doble del cajero"},
    )


def _discounted_sale(
    c: TestClient, f: dict[str, Any], ctx: dict[str, Any], token: str, key: str
) -> Any:
    return _sale(
        c,
        f,
        token,
        key,
        discount_amount=ctx.get("discount", "100000.00"),
        discount_reason="Cliente frecuente",
    )


def _discounted_payment(
    c: TestClient, f: dict[str, Any], ctx: dict[str, Any], token: str, key: str
) -> Any:
    return c.post(
        f"/api/v1/contracts/{ctx['contract']['id']}/payments",
        headers=_headers(token, key),
        json={
            "months_covered": 1,
            "payment_method": "cash",
            "discount_amount": ctx.get("discount", "10000.00"),
            "discount_reason": "Pagó puntual",
        },
    )


def _withdraw(c: TestClient, f: dict[str, Any], ctx: dict[str, Any], token: str, key: str) -> Any:
    return c.post(
        "/api/v1/capital/withdrawals",
        headers=_headers(token, key),
        json={
            "account_id": str(f["cash_account"]),
            "amount": "1000000.00",
            "notes": "Utilidades de agosto",
        },
    )


def _reopen(c: TestClient, f: dict[str, Any], ctx: dict[str, Any], token: str, key: str) -> Any:
    return c.post(
        f"/api/v1/cashbox/sessions/{f['session_id']}/reopen",
        headers=_headers(token),
        json={"reason": "Faltó registrar un gasto"},
    )


def _reopen_key(ctx: dict[str, Any], body: dict[str, Any]) -> str:
    closed_at = datetime.fromisoformat(ctx["closed"]["closed_at"].replace("Z", "+00:00"))
    return f"alert:reopen:{body['id']}:{closed_at.isoformat()}"


SCENARIOS: dict[str, Scenario] = {
    "A1": Scenario(
        "alert_sale_voided",
        _with_sale,
        _void,
        lambda ctx, body: f"alert:void:{body['id']}",
        ok=200,
        retry_status=409,
    ),
    "A2-venta": Scenario(
        "alert_discount",
        _nothing,
        _discounted_sale,
        lambda ctx, body: f"alert:discount:sale:{body['id']}",
    ),
    "A2-abono": Scenario(
        "alert_discount",
        _with_owed_contract,
        _discounted_payment,
        lambda ctx, body: f"alert:discount:payment:{body['id']}",
    ),
    "A3": Scenario(
        "alert_capital_withdrawal",
        _with_contribution,
        _withdraw,
        lambda ctx, body: f"alert:withdrawal:{body['id']}",
    ),
    "A4": Scenario(
        "alert_cash_reopened",
        _with_closed_session,
        _reopen,
        _reopen_key,
        ok=200,
        retry_status=409,
    ),
}
_IDS = list(SCENARIOS)


async def _prepare(client: TestClient, firm: dict[str, Any], sc: Scenario) -> dict[str, Any]:
    ctx = sc.setup(client, firm)
    if "backdate" in ctx:
        await _exec(
            "update public.contract set start_date = start_date - interval '2 months', "
            "interest_paid_until = interest_paid_until - interval '2 months' where id = :id",
            {"id": ctx["backdate"]},
        )
    return ctx


async def _run(
    client: TestClient, firm: dict[str, Any], sc: Scenario, *, actor: str = "cashier"
) -> tuple[dict[str, Any], Any]:
    ctx = await _prepare(client, firm, sc)
    return ctx, sc.act(client, firm, ctx, firm["tokens"][actor], str(uuid4()))


# ------------------------------------------------------------ las promesas ----


@pytest.mark.parametrize("name", _IDS)
async def test_on_one_delivery_per_recipient_with_the_permission(
    name: str, client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Encendida (el interruptor general; la casilla nace encendida por
    catálogo): una entrega por cada usuario ACTIVO con el permiso, y salen ya
    —un domingo a las 23:00—. El Exsocio (inactivo) y el Cajero (sin permiso,
    y además autor) no reciben."""
    sc = SCENARIOS[name]
    await _settings(firm["company_id"])
    ctx, response = await _run(client, firm, sc)
    assert response.status_code == sc.ok, response.text

    [event] = await _alert_events(firm["company_id"])
    assert event.event_type == sc.event_type
    assert event.dedupe_key == sc.dedupe_key(ctx, response.json())
    assert event.customer_id is None
    deliveries = await _alert_deliveries(firm["company_id"])
    emails = firm["emails"]
    assert sorted(d.to_address for d in deliveries) == sorted([emails["owner"], emails["partner"]])
    assert {d.status for d in deliveries} == {"sent"}
    assert {d.recipient_user_id for d in deliveries} == {
        firm["ids"]["owner"],
        firm["ids"]["partner"],
    }
    assert sorted(m.to for m in outbox.outbox) == sorted([emails["owner"], emails["partner"]])
    for message in outbox.outbox:
        assert message.subject.startswith(f"Alerta · {COMPANY} · ")
        assert message.from_header.startswith('"Prendo"')
        assert "Cajero Díaz" in message.text


@pytest.mark.parametrize("name", _IDS)
async def test_the_actor_does_not_receive_their_own_alert(
    name: str, client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    """La Dueña tiene el permiso, pero si el acto es suyo la alerta va solo al
    Socio: §3, un hecho cuyo destinatario es quien hizo clic es una pantalla."""
    sc = SCENARIOS[name]
    await _settings(firm["company_id"])
    _, response = await _run(client, firm, sc, actor="owner")
    assert response.status_code == sc.ok, response.text
    deliveries = await _alert_deliveries(firm["company_id"])
    assert [d.to_address for d in deliveries] == [firm["emails"]["partner"]]
    assert [m.to for m in outbox.outbox] == [firm["emails"]["partner"]]
    assert "Dueña Pérez" in outbox.outbox[0].text


@pytest.mark.parametrize("name", _IDS)
async def test_company_switch_off_records_the_fact_but_sends_nothing(
    name: str, client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Como nace en producción: el interruptor general apagado. El hecho queda
    (§4.3), sin entregas."""
    sc = SCENARIOS[name]
    ctx, response = await _run(client, firm, sc)
    assert response.status_code == sc.ok, response.text
    events = await _alert_events(firm["company_id"])
    assert [e.dedupe_key for e in events] == [sc.dedupe_key(ctx, response.json())]
    assert await _alert_deliveries(firm["company_id"]) == []
    assert outbox.outbox == []


@pytest.mark.parametrize("name", _IDS)
async def test_the_event_off_sends_nothing(
    name: str, client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    sc = SCENARIOS[name]
    await _settings(firm["company_id"], events={sc.event_type: False})
    _, response = await _run(client, firm, sc)
    assert response.status_code == sc.ok, response.text
    assert await _alert_deliveries(firm["company_id"]) == []
    assert outbox.outbox == []


@pytest.mark.parametrize("name", _IDS)
async def test_if_the_operation_fails_after_recording_the_alert_both_roll_back(
    name: str,
    client: TestClient,
    firm: dict[str, Any],
    outbox: RecordingProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La alerta va DENTRO de la transacción del documento (§5.1). Se fuerza
    una falla justo DESPUÉS de registrarla: si viviera en otra transacción,
    quedaría la alerta de un acto que no existe."""
    sc = SCENARIOS[name]
    await _settings(firm["company_id"])
    ctx = await _prepare(client, firm, sc)
    real = notifications_service.record_event
    recorded: list[str] = []

    async def record_then_fail(*args: Any, **kwargs: Any) -> Any:
        outcome = await real(*args, **kwargs)
        if kwargs["event_type"].startswith("alert_"):
            recorded.append(kwargs["event_type"])
            raise RuntimeError("falla después de registrar la alerta")
        return outcome

    monkeypatch.setattr(notifications_service, "record_event", record_then_fail)
    with pytest.raises(RuntimeError, match="después de registrar la alerta"):
        sc.act(client, firm, ctx, firm["tokens"]["cashier"], str(uuid4()))

    assert recorded == [sc.event_type]
    assert await _alert_events(firm["company_id"]) == []
    assert await _alert_deliveries(firm["company_id"]) == []
    assert outbox.outbox == []
    # Y el acto tampoco quedó: la auditoría es de la misma transacción.
    audit = await _rows(
        "select action from public.audit_log where company_id = :cid "
        "and action in ('void_sale', 'apply_sale_discount', 'apply_payment_discount', "
        "'withdrawal', 'reopen_session')",
        {"cid": str(firm["company_id"])},
    )
    assert audit == []


@pytest.mark.parametrize("name", _IDS)
async def test_an_idempotent_retry_does_not_duplicate_the_alert(
    name: str, client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    sc = SCENARIOS[name]
    await _settings(firm["company_id"])
    ctx = await _prepare(client, firm, sc)
    key = str(uuid4())
    token = firm["tokens"]["cashier"]
    first = sc.act(client, firm, ctx, token, key)
    assert first.status_code == sc.ok, first.text
    again = sc.act(client, firm, ctx, token, key)
    assert again.status_code == (sc.retry_status or sc.ok), again.text
    if sc.retry_status is None:
        assert again.json()["id"] == first.json()["id"]

    assert len(await _alert_events(firm["company_id"])) == 1
    assert len(await _alert_deliveries(firm["company_id"])) == 2
    assert len(outbox.outbox) == 2


async def test_an_inactive_user_with_the_permission_never_receives(
    client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    """Explícito, aunque lo cubre cada escenario: el Exsocio conserva el rol
    Admin (y con él el permiso), pero ya no trabaja ahí."""
    await _settings(firm["company_id"])
    _, response = await _run(client, firm, SCENARIOS["A3"])
    assert response.status_code == 201, response.text
    addresses = {d.to_address for d in await _alert_deliveries(firm["company_id"])}
    assert firm["emails"]["former"] not in addresses
    assert firm["emails"]["former"] not in {m.to for m in outbox.outbox}


# ------------------------------------------------------------- A2 y el umbral ----


@pytest.mark.parametrize("name", ["A2-venta", "A2-abono"])
@pytest.mark.parametrize(
    ("threshold", "discount", "alerts"),
    [
        ("15000.00", "10000.00", False),  # por debajo
        ("10000.00", "10000.00", False),  # igual: «por encima» es estricto
        ("5000.00", "10000.00", True),  # por encima
        ("0.00", "1.00", True),  # umbral 0 (como nace): todo descuento alerta
    ],
)
async def test_discount_alerts_only_above_the_threshold(
    name: str,
    threshold: str,
    discount: str,
    alerts: bool,
    client: TestClient,
    firm: dict[str, Any],
    outbox: RecordingProvider,
) -> None:
    sc = SCENARIOS[name]
    await _settings(firm["company_id"], discount_threshold=threshold)
    ctx = await _prepare(client, firm, sc)
    ctx["discount"] = discount
    response = sc.act(client, firm, ctx, firm["tokens"]["cashier"], str(uuid4()))
    assert response.status_code == 201, response.text
    events = await _alert_events(firm["company_id"])
    if alerts:
        assert [e.event_type for e in events] == ["alert_discount"]
        assert len(outbox.outbox) == 2
    else:
        # Por debajo no es el evento «descuento por encima del umbral»: no se
        # registra. El descuento sigue en el documento, la auditoría y el resumen.
        assert events == []
        assert outbox.outbox == []


# ------------------------------------------------------------ qué dice cada una ----


@pytest.mark.parametrize("name", _IDS)
async def test_the_alert_says_who_what_how_much_and_why_but_not_the_customer(
    name: str, client: TestClient, firm: dict[str, Any], outbox: RecordingProvider
) -> None:
    """§19.1-3: quién, qué, cuánto, cuándo y el motivo. Del cliente, nada: ni
    su nombre ni su cédula (§9.1); el número del documento alcanza. Tampoco la
    prenda ni el artículo."""
    sc = SCENARIOS[name]
    await _settings(firm["company_id"])
    _, response = await _run(client, firm, sc)
    assert response.status_code == sc.ok, response.text
    message = outbox.outbox[0]
    expected = {
        "A1": ["anuló la venta #", "$1.000.000", "«Cobro doble del cajero»"],
        "A2-venta": ["descuento de $100.000 en la venta #", "$900.000", "«Cliente frecuente»"],
        "A2-abono": ["descuento de $10.000 en un abono al contrato #", "$50.000", "«Pagó puntual»"],
        "A3": ["retiro de capital del dueño por $1.000.000", "Caja principal", "«Utilidades de"],
        "A4": ["reabrió la caja del", "Faltó registrar un gasto"],
    }[name]
    for body in (message.text, message.html):
        for fragment in expected:
            assert fragment in body, (fragment, body)
        assert "Cajero Díaz" in body
        for secret in ("Juana", "1098765432", "Cadena", "JOC0001"):
            assert secret not in body
    assert "Cajero Díaz" in message.text
    [event] = await _alert_events(firm["company_id"])
    assert event.payload["actor_name"] == "Cajero Díaz"
    assert "at" in event.payload


# ------------------------------------------------------------------ pantalla ----


def test_settings_lists_who_receives_the_alerts(client: TestClient, firm: dict[str, Any]) -> None:
    response = client.get(
        "/api/v1/notifications/settings", headers=_headers(firm["tokens"]["owner"])
    )
    assert response.status_code == 200, response.text
    recipients = response.json()["alert_recipients"]
    assert sorted(r["email"] for r in recipients) == sorted(
        [firm["emails"]["owner"], firm["emails"]["partner"]]
    )
    assert {r["full_name"] for r in recipients} == {"Dueña Pérez", "Socio Gómez"}
