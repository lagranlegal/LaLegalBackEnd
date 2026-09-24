"""Integración de los avisos por correo, fase 1 (docs/NOTIFICACIONES.md §11, §14).

Cubre la maquinaria completa contra Postgres real: el resumen a la empresa
(tercer paso del job), el despachador (cuarto paso), la idempotencia, los
umbrales, E8, los eventos al cliente apagados, los límites de la Ley 2300 y el
caso sin `RESEND_API_KEY`.

**Ningún test manda un correo real:** `tests/conftest.py` vacía la key, y los
que "envían" inyectan un `RecordingProvider`. Los instantes son FIJOS (sept.
2030, lejos del reloj real) y cada corrida se limita a la empresa del test
(`only_company_ids`), para no tocar el resto de la base local.
"""

import json
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from _jwt_helpers import FakeJwkClient, make_token
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, text

from app.core import security
from app.core.db import AsyncSessionLocal, engine
from app.jobs import nightly
from app.modules.notifications import catalog, digest, dispatcher
from app.modules.notifications.providers import (
    NullProvider,
    RecordingProvider,
    SendResult,
    get_default_provider,
)


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


def _bog(y: int, m: int, d: int, hh: int = 12, mm: int = 0) -> datetime:
    """Hora de Bogotá (UTC-5, sin horario de verano) expresada en UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) + timedelta(hours=5)


MON = _bog(2030, 9, 2)  # lunes
TUE = _bog(2030, 9, 3)
NEXT_MON = _bog(2030, 9, 9)


async def _exec(sql: str, params: dict[str, Any] | None = None) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(text(sql), params or {})


async def _rows(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async with AsyncSessionLocal() as s:
        return list((await s.execute(text(sql), params or {})).all())


@pytest_asyncio.fixture
async def notif(
    monkeypatch: pytest.MonkeyPatch, rsa_keypair: tuple[str, object]
) -> AsyncGenerator[dict[str, Any], None]:
    """Empresa con un Admin (company.configure + receive_digest), un Asesor sin
    ninguno de los dos, dos clientes (con y sin correo), una caja y una
    suscripción lejana. Los avisos nacen APAGADOS, como en producción."""
    private_pem, public_key = rsa_keypair
    monkeypatch.setattr(security, "get_jwk_client", lambda: FakeJwkClient(public_key))

    cid, admin_role, asesor_role = uuid4(), uuid4(), uuid4()
    admin_id, asesor_id = uuid4(), uuid4()
    customer_mail, customer_nomail = uuid4(), uuid4()
    register_id = uuid4()

    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.company (id, name, contact_email, contact_phone) "
                "values (:id, 'Compraventa Avisos', 'contacto@avisos.example', '3001112233')"
            ),
            {"id": str(cid)},
        )
        await s.execute(
            text(
                "insert into public.role (id, company_id, name) values "
                "(:a, :cid, 'Admin'), (:b, :cid, 'Asesor')"
            ),
            {"a": str(admin_role), "b": str(asesor_role), "cid": str(cid)},
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code in :codes"
            ).bindparams(bindparam("codes", expanding=True)),
            {
                "role_id": str(admin_role),
                "codes": ["company.configure", "notifications.receive_digest"],
            },
        )
        await s.execute(
            text(
                "insert into public.role_permission (role_id, permission_id) "
                "select :role_id, id from public.permission where code = 'contracts.view'"
            ),
            {"role_id": str(asesor_role)},
        )
        await s.execute(
            text(
                "insert into public.app_user (id, company_id, role_id, full_name, email, status) "
                "values (:a, :cid, :ar, 'Dueña', :ae, 'active'), "
                "(:b, :cid, :br, 'Asesor', :be, 'active')"
            ),
            {
                "a": str(admin_id),
                "b": str(asesor_id),
                "cid": str(cid),
                "ar": str(admin_role),
                "br": str(asesor_role),
                "ae": f"duena-{admin_id}@example.com",
                "be": f"asesor-{asesor_id}@example.com",
            },
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan, 'active', '2031-12-31')"
            ),
            {"cid": str(cid), "plan": str(plan_id)},
        )
        await s.execute(
            text(
                "insert into public.customer (id, company_id, full_name, doc_type, doc_number, "
                "phone, email) values "
                "(:a, :cid, 'Juana Pérez', 'cc', :da, '3000000001', 'juana@example.com'), "
                "(:b, :cid, 'Pedro Gómez', 'cc', :db, '3000000002', null)"
            ),
            {
                "a": str(customer_mail),
                "b": str(customer_nomail),
                "cid": str(cid),
                "da": str(uuid4().int)[:10],
                "db": str(uuid4().int)[:10],
            },
        )
        await s.execute(
            text("insert into public.cash_register (id, company_id) values (:id, :cid)"),
            {"id": str(register_id), "cid": str(cid)},
        )

    yield {
        "company_id": cid,
        "admin_id": admin_id,
        "admin_email": f"duena-{admin_id}@example.com",
        "customer_mail": customer_mail,
        "customer_nomail": customer_nomail,
        "register_id": register_id,
        "admin_token": make_token(
            private_pem, sub=str(admin_id), company_id=str(cid), role_id=str(admin_role)
        ),
        "asesor_token": make_token(
            private_pem, sub=str(asesor_id), company_id=str(cid), role_id=str(asesor_role)
        ),
    }

    for sql in (
        "delete from public.notification_delivery where company_id = :cid",
        "delete from public.notification_event where company_id = :cid",
        "delete from public.audit_log where company_id = :cid",
        "delete from public.cash_session where company_id = :cid",
        "delete from public.cash_register where company_id = :cid",
        "delete from public.contract where company_id = :cid",
        "delete from public.customer where company_id = :cid",
        "delete from public.app_user where company_id = :cid",
        "delete from public.role_permission where role_id in "
        "(select id from public.role where company_id = :cid)",
        "delete from public.role where company_id = :cid",
        "delete from public.subscription where company_id = :cid",
        "delete from public.company where id = :cid",
    ):
        try:
            await _exec(sql, {"cid": str(cid)})
        except Exception:
            # `audit_log` es inmutable (trigger): su borrado falla a propósito
            # y no tiene FK, así que no bloquea el resto de la limpieza.
            pass


# ------------------------------------------------------------------ helpers ----

_NUMBER = iter(range(1, 10_000))


async def _enable(company_id: UUID, **notifications: Any) -> None:
    value = {"enabled": True, **notifications}
    await _exec(
        "update public.company set settings = jsonb_set(settings, '{notifications}', "
        "cast(:v as jsonb), true) where id = :id",
        {"v": json.dumps(value), "id": str(company_id)},
    )


async def _contract(
    company_id: UUID,
    customer_id: UUID,
    *,
    status: str,
    interest_paid_until: date,
    extension_ends_at: date | None = None,
    window: int = 4,
) -> int:
    number = next(_NUMBER)
    await _exec(
        """
        insert into public.contract
            (company_id, number, customer_id, principal, capital_balance, interest_rate_pct,
             term_months, arrears_window_months, start_date, due_date, interest_paid_until,
             status, extension_ends_at, created_at)
        values (:cid, :n, :cust, 1000000, 1000000, 5, 4, :w, '2030-01-01', '2030-05-01',
                :ipu, cast(:st as contract_status), :ext, '2020-01-01')
        """,
        {
            "cid": str(company_id),
            "n": number,
            "cust": str(customer_id),
            "w": window,
            "ipu": interest_paid_until,
            "st": status,
            "ext": extension_ends_at,
        },
    )
    return number


async def _events(company_id: UUID, event_type: str) -> list[Any]:
    return await _rows(
        "select id, payload, occurred_on from public.notification_event "
        "where company_id = :cid and event_type = :t order by occurred_on",
        {"cid": str(company_id), "t": event_type},
    )


async def _deliveries(company_id: UUID, event_type: str | None = None) -> list[Any]:
    sql = (
        "select d.id, d.status, d.to_address, d.attempts, d.last_error, d.scheduled_at, "
        "e.event_type from public.notification_delivery d "
        "join public.notification_event e on e.id = d.event_id where d.company_id = :cid"
    )
    params: dict[str, Any] = {"cid": str(company_id)}
    if event_type:
        sql += " and e.event_type = :t"
        params["t"] = event_type
    return await _rows(sql + " order by d.created_at", params)


async def _digest(company_id: UUID, now: datetime) -> digest.DigestRunStats:
    return await digest.build_all_digests(now=now, only_company_ids=[company_id])


async def _dispatch(company_id: UUID, now: datetime, provider: Any) -> dispatcher.DispatchStats:
    return await dispatcher.dispatch_due(provider=provider, now=now, only_company_ids=[company_id])


# -------------------------------------------------- idempotencia y el resumen ----


async def test_running_the_job_twice_does_not_duplicate(notif: dict[str, Any]) -> None:
    """§14: correr el job dos veces la misma noche ⇒ un solo correo."""
    cid = notif["company_id"]
    await _enable(cid)
    number = await _contract(
        cid,
        notif["customer_mail"],
        status="in_extension",
        interest_paid_until=date(2030, 4, 1),
        extension_ends_at=date(2030, 9, 1),
    )

    await _digest(cid, MON)
    second = await _digest(cid, MON)
    assert second.already_done == 1

    assert len(await _events(cid, catalog.WEEKLY_DIGEST)) == 1
    assert len(await _events(cid, catalog.DAILY_DIGEST)) == 1
    deliveries = await _deliveries(cid)
    assert [(d.status, d.to_address, d.event_type) for d in deliveries] == [
        ("pending", notif["admin_email"], catalog.WEEKLY_DIGEST)
    ]

    provider = RecordingProvider()
    await _dispatch(cid, MON, provider)
    await _dispatch(cid, MON, provider)
    assert len(provider.outbox) == 1
    message = provider.outbox[0]
    assert message.to == notif["admin_email"]
    assert message.from_header == '"Prendo" <notificaciones@prendo.com.co>'
    assert "Resumen semanal · Compraventa Avisos" in message.subject
    assert f"Contrato #{number}" in message.text
    assert [d.status for d in await _deliveries(cid)] == ["sent"]


async def test_empty_daily_is_not_sent_but_weekly_always_is(notif: dict[str, Any]) -> None:
    """§12.2-2: el diario sale solo con actividad o alertas; el semanal, siempre."""
    cid = notif["company_id"]
    await _enable(cid)

    await _digest(cid, MON)  # lunes: semanal, aunque no haya nada
    await _digest(cid, TUE)  # martes sin nada: diario registrado, sin correo
    await _digest(cid, NEXT_MON)  # lunes siguiente: otro semanal

    dailies = await _events(cid, catalog.DAILY_DIGEST)
    assert [e.occurred_on for e in dailies] == [
        date(2030, 9, 2),
        date(2030, 9, 3),
        date(2030, 9, 9),
    ]
    tuesday = dailies[1].payload
    assert tuesday["has_alerts"] is False and tuesday["has_activity"] is False
    assert len(await _events(cid, catalog.WEEKLY_DIGEST)) == 2
    assert [d.event_type for d in await _deliveries(cid)] == [
        catalog.WEEKLY_DIGEST,
        catalog.WEEKLY_DIGEST,
    ]


async def test_daily_goes_out_with_new_ready_contract_and_state_changes(
    notif: dict[str, Any],
) -> None:
    """E1 nuevo + E2 (entró en mora) ⇒ el diario sale. Y E1 reusa el predicado
    de ready-for-auction: un `in_extension` que todavía no vence no aparece."""
    cid = notif["company_id"]
    await _enable(cid)
    await _digest(cid, MON)

    ready = await _contract(
        cid,
        notif["customer_mail"],
        status="in_extension",
        interest_paid_until=date(2030, 4, 2),
        extension_ends_at=date(2030, 9, 2),  # vence el lunes ⇒ listo el martes
    )
    await _contract(
        cid,
        notif["customer_mail"],
        status="in_extension",
        interest_paid_until=date(2030, 5, 3),
        extension_ends_at=date(2030, 10, 3),  # prórroga viva: NO está listo
    )
    arrears = await _contract(
        cid,
        notif["customer_nomail"],
        status="in_arrears",
        interest_paid_until=date(2030, 8, 3),  # add_months(+1) = martes 3/09
    )

    await _digest(cid, TUE)
    daily = (await _events(cid, catalog.DAILY_DIGEST))[-1].payload
    assert daily["has_alerts"] is True
    assert daily["ready_for_auction"]["total"] == 1
    assert daily["ready_for_auction"]["contracts"][0] == {
        "number": ready,
        "extension_ends_at": "2030-09-02",
        "new": True,
    }
    assert daily["entered_arrears"] == [{"number": arrears, "since": "2030-09-03"}]
    assert [d.event_type for d in await _deliveries(cid)] == [
        catalog.WEEKLY_DIGEST,
        catalog.DAILY_DIGEST,
    ]


async def test_disabled_company_records_events_but_sends_nothing(notif: dict[str, Any]) -> None:
    """El interruptor general nace apagado (§4.3, §11): el hecho queda, la entrega no."""
    cid = notif["company_id"]
    await _digest(cid, MON)
    assert len(await _events(cid, catalog.WEEKLY_DIGEST)) == 1
    assert await _deliveries(cid) == []


# ---------------------------------------------------------------- umbrales ----


async def _closed_session(
    company_id: UUID, register_id: UUID, *, session_date: date, difference: str, closed_at: datetime
) -> None:
    await _exec(
        """
        insert into public.cash_session
            (company_id, register_id, session_date, opened_by, opening_balance, expected_cash,
             counted_cash, difference, difference_reason, closed_at, status)
        values (:cid, :rid, :sd, :cid, 0, 100000, 100000 + cast(:diff as numeric),
                cast(:diff as numeric), 'conteo', :closed, 'closed')
        """,
        {
            "cid": str(company_id),
            "rid": str(register_id),
            "sd": session_date,
            "diff": difference,
            "closed": closed_at,
        },
    )


async def test_threshold_flags_but_below_threshold_still_in_digest(
    client: TestClient, notif: dict[str, Any]
) -> None:
    """§12.2-4: el umbral es por empresa, nace en 0, y lo que queda por debajo
    IGUAL sale en el resumen — el umbral solo decide la marca (y la alerta, fase 7)."""
    cid = notif["company_id"]
    headers = {"Authorization": f"Bearer {notif['admin_token']}"}
    response = client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"enabled": True, "thresholds": {"cash_difference_amount": "50000"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["thresholds"] == {
        "discount_amount": "0.00",
        "cash_difference_amount": "50000.00",
    }

    await _digest(cid, MON)
    await _closed_session(
        cid,
        notif["register_id"],
        session_date=date(2030, 8, 31),
        difference="-20000",
        closed_at=_bog(2030, 9, 2, 15),
    )
    await _closed_session(
        cid,
        notif["register_id"],
        session_date=date(2030, 9, 1),
        difference="80000",
        closed_at=_bog(2030, 9, 2, 16),
    )
    await _digest(cid, TUE)

    daily = (await _events(cid, catalog.DAILY_DIGEST))[-1].payload
    assert [(d["difference"], d["above_threshold"]) for d in daily["cash_differences"]] == [
        ("-20000.00", False),
        ("80000.00", True),
    ]
    provider = RecordingProvider()
    await _dispatch(cid, TUE, provider)
    daily_mail = next(m for m in provider.outbox if "Resumen diario" in m.subject)
    assert "faltante de $20.000" in daily_mail.text
    assert "sobrante de $80.000 — «conteo» ⚠ sobre el umbral" in daily_mail.text


async def test_thresholds_default_to_zero_so_everything_is_flagged(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid)
    await _digest(cid, MON)
    await _closed_session(
        cid,
        notif["register_id"],
        session_date=date(2030, 9, 2),
        difference="-100",
        closed_at=_bog(2030, 9, 2, 19),
    )
    await _digest(cid, TUE)
    daily = (await _events(cid, catalog.DAILY_DIGEST))[-1].payload
    assert daily["cash_differences"][0]["above_threshold"] is True


# ---------------------------------------------------------------------- E8 ----


async def _set_expiry(company_id: UUID, expires_at: date) -> None:
    await _exec(
        "update public.subscription set expires_at = :e where company_id = :cid",
        {"e": expires_at, "cid": str(company_id)},
    )


async def test_subscription_expiring_in_7_days_triggers_the_daily(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid)
    await _set_expiry(cid, date(2030, 9, 10))
    await _digest(cid, MON)
    weekly = (await _events(cid, catalog.WEEKLY_DIGEST))[0].payload
    assert weekly["subscription"] == {"expires_at": "2030-09-10", "days_left": 8}

    await _digest(cid, TUE)
    daily = (await _events(cid, catalog.DAILY_DIGEST))[-1].payload
    assert daily["subscription"] == {"expires_at": "2030-09-10", "days_left": 7}
    assert daily["has_alerts"] is True

    provider = RecordingProvider()
    await _dispatch(cid, TUE, provider)
    assert any("Vence en 7 días" in m.text for m in provider.outbox)


async def test_subscription_between_milestones_does_not_trigger(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid)
    await _set_expiry(cid, date(2030, 9, 11))  # el martes faltan 8
    await _digest(cid, MON)
    await _digest(cid, TUE)
    daily = (await _events(cid, catalog.DAILY_DIGEST))[-1].payload
    assert daily["subscription"] is None
    assert [d.event_type for d in await _deliveries(cid)] == [catalog.WEEKLY_DIGEST]


# ------------------------------------------------------ eventos al cliente ----


async def test_customer_auction_notice_off_by_default(notif: dict[str, Any]) -> None:
    """§14: con `auction_ready_customer` apagado, la noche produce E1 a la
    empresa y NINGUNA entrega al cliente. El hecho sí queda registrado."""
    cid = notif["company_id"]
    await _enable(cid)
    await _contract(
        cid,
        notif["customer_mail"],
        status="in_extension",
        interest_paid_until=date(2030, 4, 1),
        extension_ends_at=date(2030, 9, 1),
    )
    await _digest(cid, MON)

    assert len(await _events(cid, catalog.AUCTION_READY_CUSTOMER)) == 1
    assert await _deliveries(cid, catalog.AUCTION_READY_CUSTOMER) == []
    assert len(await _deliveries(cid, catalog.WEEKLY_DIGEST)) == 1


async def test_customer_auction_notice_on_is_only_a_setting(notif: dict[str, Any]) -> None:
    """Encendido: produce las dos entregas. La del cliente con correo nace
    `suppressed` porque hasta la fase 3 no hay base legal registrada (§9.2-c):
    encender un evento no se adelanta a la base que lo sostiene. La del cliente
    sin correo, `unroutable` (§1: el caso normal, registrado)."""
    cid = notif["company_id"]
    await _enable(cid, events={"auction_ready_customer": True})
    for customer in (notif["customer_mail"], notif["customer_nomail"]):
        await _contract(
            cid,
            customer,
            status="in_extension",
            interest_paid_until=date(2030, 4, 1),
            extension_ends_at=date(2030, 9, 1),
        )
    await _digest(cid, MON)

    customer_deliveries = await _deliveries(cid, catalog.AUCTION_READY_CUSTOMER)
    assert sorted((d.status, d.to_address) for d in customer_deliveries) == [
        ("suppressed", "juana@example.com"),
        ("unroutable", None),
    ]
    assert len(await _deliveries(cid, catalog.WEEKLY_DIGEST)) == 1

    provider = RecordingProvider()
    await _dispatch(cid, MON, provider)
    assert all("juana" not in m.to for m in provider.outbox)


# ------------------------------------------------------- Ley 2300 (despacho) ----


async def _pending(
    company_id: UUID,
    *,
    event_type: str,
    to: str,
    payload: dict[str, Any],
    customer_id: UUID | None = None,
    target_date: date | None = None,
) -> UUID:
    """Una entrega `pending` escrita a mano: el despachador no pregunta de dónde
    salió, y así se prueba sin depender de la base legal de la fase 3."""
    et = catalog.get(event_type)
    async with AsyncSessionLocal() as s, s.begin():
        event_id = (
            await s.execute(
                text(
                    """
                    insert into public.notification_event
                        (company_id, event_type, audience, customer_id, payload, dedupe_key,
                         occurred_on, target_date)
                    values (:cid, :t, :a, :cust, cast(:p as jsonb), :k, '2030-09-01', :td)
                    returning id
                    """
                ),
                {
                    "cid": str(company_id),
                    "t": event_type,
                    "a": et.audience,
                    "cust": str(customer_id) if customer_id else None,
                    "p": json.dumps(payload),
                    "k": f"test:{uuid4()}",
                    "td": target_date,
                },
            )
        ).scalar_one()
        delivery_id = (
            await s.execute(
                text(
                    "insert into public.notification_delivery "
                    "(company_id, event_id, to_address, status, scheduled_at) "
                    "values (:cid, :e, :to, 'pending', '2030-01-01') returning id"
                ),
                {"cid": str(company_id), "e": str(event_id), "to": to},
            )
        ).scalar_one()
    return UUID(str(delivery_id))


_DUE = {"due_date": "2030-09-05", "contracts": [{"number": 1, "amount": "50000"}]}


async def _status(delivery_id: UUID) -> tuple[str, datetime]:
    row = (
        await _rows(
            "select status, scheduled_at from public.notification_delivery where id = :id",
            {"id": str(delivery_id)},
        )
    )[0]
    return row.status, row.scheduled_at


_DUE_ON = {"installment_due_soon": True}


async def test_customer_mail_waits_for_business_hours(notif: dict[str, Any]) -> None:
    """Domingo ⇒ no se contacta: la entrega se corre al lunes 7:00 hora Colombia."""
    cid = notif["company_id"]
    await _enable(cid, events=_DUE_ON)
    delivery = await _pending(
        cid,
        event_type="installment_due_soon",
        to="juana@example.com",
        payload=_DUE,
        customer_id=notif["customer_mail"],
    )
    provider = RecordingProvider()
    await _dispatch(cid, _bog(2030, 9, 1, 10), provider)
    status, scheduled = await _status(delivery)
    assert status == "pending"
    assert scheduled == _bog(2030, 9, 2, 7)
    assert provider.outbox == []

    await _dispatch(cid, _bog(2030, 9, 2, 7, 30), provider)
    assert (await _status(delivery))[0] == "sent"
    assert provider.outbox[0].subject.startswith("Compraventa Avisos · ")
    assert provider.outbox[0].reply_to == "contacto@avisos.example"


async def test_customer_mail_skips_colombian_holidays(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid, events=_DUE_ON)
    delivery = await _pending(
        cid, event_type="installment_due_soon", to="juana@example.com", payload=_DUE
    )
    await _dispatch(cid, _bog(2030, 10, 14, 9), RecordingProvider())  # festivo (lunes)
    assert await _status(delivery) == ("pending", _bog(2030, 10, 15, 7))


async def test_weekly_cap_per_customer_throttles(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid, events=_DUE_ON)
    first = await _pending(
        cid, event_type="installment_due_soon", to="juana@example.com", payload=_DUE
    )
    await _dispatch(cid, _bog(2030, 9, 2, 9), RecordingProvider())
    assert (await _status(first))[0] == "sent"

    second = await _pending(
        cid, event_type="installment_due_soon", to="JUANA@example.com", payload=_DUE
    )
    await _dispatch(cid, _bog(2030, 9, 4, 9), RecordingProvider())
    assert (await _status(second))[0] == "throttled"

    third = await _pending(
        cid, event_type="installment_due_soon", to="juana@example.com", payload=_DUE
    )
    await _dispatch(cid, _bog(2030, 9, 10, 9), RecordingProvider())  # pasó la semana
    assert (await _status(third))[0] == "sent"


async def test_limits_are_relaxed_by_configuration(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid, events=_DUE_ON, customer_contact_limits={"enabled": False})
    delivery = await _pending(
        cid, event_type="installment_due_soon", to="juana@example.com", payload=_DUE
    )
    await _dispatch(cid, _bog(2030, 9, 1, 3), RecordingProvider())  # domingo 3 a. m.
    assert (await _status(delivery))[0] == "sent"


async def test_limits_do_not_apply_to_the_company(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid)
    delivery = await _pending(
        cid,
        event_type=catalog.DAILY_DIGEST,
        to=notif["admin_email"],
        payload={"day": "2030-09-01", "kind": "daily"},
        target_date=date(2030, 9, 1),
    )
    await _dispatch(cid, _bog(2030, 9, 1, 3), RecordingProvider())  # domingo 3 a. m.
    assert (await _status(delivery))[0] == "sent"


# ----------------------------------------------- rezago, reintentos, proveedor ----


async def test_turning_an_event_off_stops_what_was_pending(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid)  # installment_due_soon sigue en su default: apagado
    delivery = await _pending(
        cid, event_type="installment_due_soon", to="juana@example.com", payload=_DUE
    )
    provider = RecordingProvider()
    await _dispatch(cid, _bog(2030, 9, 2, 9), provider)
    assert (await _status(delivery))[0] == "suppressed"
    assert provider.outbox == []


async def test_stale_delivery_is_skipped_not_sent(notif: dict[str, Any]) -> None:
    """§5.3: un aviso cuya fecha quedó más de `stale_after_days` (2) atrás se registra."""
    cid = notif["company_id"]
    await _enable(cid)
    delivery = await _pending(
        cid,
        event_type=catalog.DAILY_DIGEST,
        to=notif["admin_email"],
        payload={"day": "2030-09-01", "kind": "daily"},
        target_date=date(2030, 9, 1),
    )
    provider = RecordingProvider()
    await _dispatch(cid, _bog(2030, 9, 4, 10), provider)
    assert (await _status(delivery))[0] == "skipped_stale"
    assert provider.outbox == []


async def test_retryable_failure_backs_off_then_dies(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid, stale_after_days=30)
    delivery = await _pending(
        cid,
        event_type=catalog.DAILY_DIGEST,
        to=notif["admin_email"],
        payload={"day": "2030-09-02", "kind": "daily"},
        target_date=date(2030, 9, 2),
    )
    failing = RecordingProvider(fail_with=SendResult(ok=False, retryable=True, error="HTTP 503"))
    now = MON
    for expected_delay in (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24)):
        await _dispatch(cid, now, failing)
        status, scheduled = await _status(delivery)
        assert status == "failed"
        assert scheduled == now + expected_delay
        now = scheduled
    await _dispatch(cid, now, failing)
    row = (await _deliveries(cid))[0]
    assert (row.status, row.attempts, row.last_error) == ("dead", 4, "HTTP 503")


async def test_permanent_failure_dies_at_once(notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid)
    delivery = await _pending(
        cid,
        event_type=catalog.DAILY_DIGEST,
        to=notif["admin_email"],
        payload={"day": "2030-09-02", "kind": "daily"},
        target_date=date(2030, 9, 2),
    )
    rejected = RecordingProvider(fail_with=SendResult(ok=False, retryable=False, error="HTTP 422"))
    await _dispatch(cid, MON, rejected)
    assert (await _status(delivery))[0] == "dead"


async def test_without_resend_key_the_job_does_not_fail(notif: dict[str, Any]) -> None:
    """Sin `RESEND_API_KEY`: el job termina, y la entrega queda en un estado
    que dice exactamente qué pasó — no `sent`, no `failed`, no silencio."""
    assert isinstance(get_default_provider(), NullProvider)
    cid = notif["company_id"]
    await _enable(cid)

    await nightly.run()  # el reloj real y el proveedor por defecto

    deliveries = await _deliveries(cid)
    assert deliveries, "el semanal debió planificarse para la Dueña"
    assert {d.status for d in deliveries} == {"skipped_no_provider"}
    assert "RESEND_API_KEY" in deliveries[0].last_error


# --------------------------------------------------------------- endpoints ----


def test_settings_defaults(client: TestClient, notif: dict[str, Any]) -> None:
    response = client.get(
        "/api/v1/notifications/settings",
        headers={"Authorization": f"Bearer {notif['admin_token']}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["provider_configured"] is False
    assert body["stale_after_days"] == 2
    assert body["customer_contact_limits"]["weekday_hours"] == ["07:00", "19:00"]
    events = {e["code"]: e for e in body["events"]}
    assert events["auction_ready_customer"]["enabled"] is False
    assert events["company_daily_digest"]["enabled"] is True
    assert events["company_daily_digest"]["effective"] is False  # interruptor general apagado
    assert all(not e["enabled"] for e in events.values() if e["audience"] == "customer")
    assert [r["email"] for r in body["digest_recipients"]] == [notif["admin_email"]]


async def test_patch_settings_is_audited(client: TestClient, notif: dict[str, Any]) -> None:
    headers = {"Authorization": f"Bearer {notif['admin_token']}"}
    response = client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"enabled": True, "events": {"auction_ready_customer": True}},
    )
    assert response.status_code == 200, response.text
    events = {e["code"]: e for e in response.json()["events"]}
    assert events["auction_ready_customer"]["effective"] is True
    assert events["auction_ready_customer"]["overridden"] is True

    audit = await _rows(
        "select module, action, before, after from public.audit_log where company_id = :cid",
        {"cid": str(notif["company_id"])},
    )
    assert len(audit) == 1
    assert (audit[0].module, audit[0].action) == ("notifications", "update_settings")
    assert audit[0].after["changed_fields"] == ["enabled", "events"]
    assert audit[0].before["enabled"] is False

    # `null` borra el override: vuelve al default del catálogo.
    response = client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"events": {"auction_ready_customer": None}},
    )
    events = {e["code"]: e for e in response.json()["events"]}
    assert events["auction_ready_customer"]["enabled"] is False
    assert events["auction_ready_customer"]["overridden"] is False

    # La zona horaria de la empresa sobrevive: solo se tocó la rama `notifications`.
    settings = await _rows(
        "select settings from public.company where id = :id", {"id": str(notif["company_id"])}
    )
    assert settings[0].settings["timezone"] == "America/Bogota"


def test_patch_unknown_or_platform_event_is_rejected(
    client: TestClient, notif: dict[str, Any]
) -> None:
    headers = {"Authorization": f"Bearer {notif['admin_token']}"}
    unknown = client.patch(
        "/api/v1/notifications/settings", headers=headers, json={"events": {"no_existe": True}}
    )
    assert unknown.status_code == 400
    assert unknown.json()["code"] == "NOTIFICATION_EVENT_UNKNOWN"
    platform = client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"events": {"user_invitation": False}},
    )
    assert platform.status_code == 400
    assert platform.json()["code"] == "NOTIFICATION_EVENT_NOT_CONFIGURABLE"
    bad_hours = client.patch(
        "/api/v1/notifications/settings",
        headers=headers,
        json={"customer_contact_limits": {"weekday_hours": ["19:00", "07:00"]}},
    )
    assert bad_hours.status_code == 422


def test_endpoints_require_company_configure(client: TestClient, notif: dict[str, Any]) -> None:
    headers = {"Authorization": f"Bearer {notif['asesor_token']}"}
    for method, path in (
        ("GET", "/api/v1/notifications/settings"),
        ("PATCH", "/api/v1/notifications/settings"),
        ("GET", "/api/v1/notifications/deliveries"),
    ):
        response = client.request(method, path, headers=headers, json={})
        assert response.status_code == 403, (method, path)
        assert response.json()["code"] == "PERMISSION_DENIED"


async def test_list_deliveries(client: TestClient, notif: dict[str, Any]) -> None:
    cid = notif["company_id"]
    await _enable(cid, events={"auction_ready_customer": True})
    await _contract(
        cid,
        notif["customer_nomail"],
        status="in_extension",
        interest_paid_until=date(2030, 4, 1),
        extension_ends_at=date(2030, 9, 1),
    )
    await _digest(cid, MON)
    headers = {"Authorization": f"Bearer {notif['admin_token']}"}

    response = client.get("/api/v1/notifications/deliveries", headers=headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {(i["event_type"], i["status"]) for i in items} == {
        (catalog.WEEKLY_DIGEST, "pending"),
        (catalog.AUCTION_READY_CUSTOMER, "unroutable"),
    }
    filtered = client.get(
        "/api/v1/notifications/deliveries", headers=headers, params={"status": "unroutable"}
    ).json()["items"]
    assert [i["to_address"] for i in filtered] == [None]

    paged = client.get(
        "/api/v1/notifications/deliveries", headers=headers, params={"limit": 1}
    ).json()
    assert len(paged["items"]) == 1 and paged["next_cursor"]


# ---------------------------------------------------------------- catálogo ----


async def test_catalog_in_db_matches_code() -> None:
    rows = await _rows(
        "select code, audience, purpose, family, default_enabled "
        "from public.notification_event_type"
    )
    in_db = {(r.code, r.audience, r.purpose, r.family, r.default_enabled) for r in rows}
    in_code = {
        (t.code, t.audience, t.purpose, t.family, t.default_enabled)
        for t in catalog.EVENT_TYPES.values()
    }
    assert in_db == in_code


async def test_digest_permission_seeded_for_admins_only() -> None:
    """00058 le da los permisos al rol con `identity.manage_roles` de las
    empresas existentes; `platform.service` los excluye del Moderador."""
    from app.modules.platform.service import build_seed_role_permissions

    codes = {"notifications.receive_digest", "notifications.receive_alerts", "reports.view"}
    matrix = build_seed_role_permissions(codes)
    assert codes <= matrix["Admin"]
    assert not (matrix["Moderador"] & {"notifications.receive_digest"})
    assert not (matrix["Asesor"] & codes)
    rows = await _rows(
        "select code from public.permission where module = 'notifications' order by code"
    )
    assert [r.code for r in rows] == [
        "notifications.receive_alerts",
        "notifications.receive_digest",
    ]
