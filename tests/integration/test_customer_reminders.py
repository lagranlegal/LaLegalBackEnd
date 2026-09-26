"""Fase 5 de avisos: los recordatorios al cliente R1–R4 (docs/NOTIFICACIONES.md
§2.2, §2.3, §5.3, §6.1, §20).

Contra Postgres real: el paso del job que decide los recordatorios
(`reminders.build_all_reminders`) y el despachador que los manda. Los
contratos se escriben directo en la base con el estado que `recompute_all_statuses`
les habría dejado ese día — así el test fija el INSTANTE (sept. 2030, lejos
del reloj real) sin depender de que el recálculo corra con la fecha de hoy.

**Ningún test manda un correo real:** `tests/conftest.py` vacía la key y los
envíos van a un `RecordingProvider`. Cada corrida se limita a la empresa del
test (`only_company_ids`).

Septiembre de 2030: lunes 2, martes 3, miércoles 4, jueves 5, viernes 6.
Todos los contratos son de $1.000.000 al 5 %: la cuota es $50.000.
"""

import json
from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.db import AsyncSessionLocal, engine
from app.core.settings import get_settings
from app.jobs import nightly
from app.modules.notifications import catalog, dispatcher, reminders
from app.modules.notifications.providers import RecordingProvider

R1 = "installment_due_soon"
R2 = "installment_overdue"
R3 = "extension_started"
R4 = "extension_ending_soon"


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


MON = _bog(2030, 9, 2)
TUE = _bog(2030, 9, 3)
THU = _bog(2030, 9, 5)
FRI = _bog(2030, 9, 6)


async def _exec(sql: str, params: dict[str, Any] | None = None) -> None:
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(text(sql), params or {})


async def _rows(sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async with AsyncSessionLocal() as s:
        return list((await s.execute(text(sql), params or {})).all())


@pytest_asyncio.fixture
async def rem(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[dict[str, Any], None]:
    """Empresa con cuatro clientes que cubren la matriz de §9.2-c: Juana (correo
    y base `contract`), Pedro (sin correo), Ana (correo SIN base) y Luis (correo,
    base `contract`, dado de baja). Los avisos nacen APAGADOS, como en producción."""
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("NOTIFICATIONS_LINK_SECRET", "secreto-de-prueba-de-los-enlaces-de-baja")
    get_settings.cache_clear()

    cid = uuid4()
    juana, pedro, ana, luis = uuid4(), uuid4(), uuid4(), uuid4()
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(
            text(
                "insert into public.company (id, name, contact_email, contact_phone) "
                "values (:id, 'Compraventa Recordatorios', 'contacto@rec.example', '3004445566')"
            ),
            {"id": str(cid)},
        )
        plan_id = (await s.execute(text("select id from public.plan limit 1"))).scalar_one()
        await s.execute(
            text(
                "insert into public.subscription (company_id, plan_id, status, expires_at) "
                "values (:cid, :plan, 'active', '2031-12-31')"
            ),
            {"cid": str(cid), "plan": str(plan_id)},
        )
        for customer_id, name, email, basis, opt_out in (
            (juana, "Juana Pérez", "juana@example.com", "contract", False),
            (pedro, "Pedro Gómez", None, None, False),
            (ana, "Ana Ruiz", "ana@example.com", None, False),
            (luis, "Luis Mora", "luis@example.com", "contract", True),
        ):
            await s.execute(
                text(
                    "insert into public.customer (id, company_id, full_name, doc_type, "
                    "doc_number, phone, email, email_basis, email_basis_at, email_opt_out_at) "
                    "values (:id, :cid, :name, 'cc', :doc, '3000000000', :email, :basis, "
                    " case when cast(:basis as text) is null then null else now() end, "
                    " case when :opt_out then now() else null end)"
                ),
                {
                    "id": str(customer_id),
                    "cid": str(cid),
                    "name": name,
                    "doc": str(uuid4().int)[:10],
                    "email": email,
                    "basis": basis,
                    "opt_out": opt_out,
                },
            )

    yield {"company_id": cid, "juana": juana, "pedro": pedro, "ana": ana, "luis": luis}

    for sql in (
        "delete from public.notification_delivery where company_id = :cid",
        "delete from public.notification_event where company_id = :cid",
        "delete from public.contract where company_id = :cid",
        "delete from public.customer where company_id = :cid",
        "delete from public.subscription where company_id = :cid",
        "delete from public.company where id = :cid",
    ):
        await _exec(sql, {"cid": str(cid)})
    get_settings.cache_clear()


# ------------------------------------------------------------------ helpers ----

_NUMBER = iter(range(5000, 90_000))


async def _enable(company_id: UUID, *events: str, **notifications: Any) -> None:
    value = {"enabled": True, "events": {e: True for e in events}, **notifications}
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


async def _set_status(company_id: UUID, number: int, status: str) -> None:
    """Lo que `recompute_all_statuses` habría escrito esa noche."""
    await _exec(
        "update public.contract set status = cast(:st as contract_status) "
        "where company_id = :cid and number = :n",
        {"st": status, "cid": str(company_id), "n": number},
    )


async def _events(company_id: UUID, event_type: str | None = None) -> list[Any]:
    sql = (
        "select id, event_type, customer_id, dedupe_key, payload, target_date, occurred_on "
        "from public.notification_event where company_id = :cid"
    )
    params: dict[str, Any] = {"cid": str(company_id)}
    if event_type:
        sql += " and event_type = :t"
        params["t"] = event_type
    return await _rows(sql + " order by target_date, dedupe_key", params)


async def _deliveries(company_id: UUID, dedupe_key: str | None = None) -> list[Any]:
    sql = (
        "select d.id, d.status, d.to_address, d.scheduled_at, d.last_error, e.event_type, "
        "e.dedupe_key from public.notification_delivery d "
        "join public.notification_event e on e.id = d.event_id where d.company_id = :cid"
    )
    params: dict[str, Any] = {"cid": str(company_id)}
    if dedupe_key:
        sql += " and e.dedupe_key = :k"
        params["k"] = dedupe_key
    return await _rows(sql + " order by d.to_address nulls last", params)


async def _run(company_id: UUID, now: datetime) -> reminders.ReminderRunStats:
    return await reminders.build_all_reminders(now=now, only_company_ids=[company_id])


async def _dispatch(company_id: UUID, now: datetime, provider: RecordingProvider) -> None:
    await dispatcher.dispatch_due(provider=provider, now=now, only_company_ids=[company_id])


def _key(prefix: str, customer_id: UUID, day: str) -> str:
    return f"{prefix}:{customer_id}:{day}"


# ------------------------------------------------ cada uno, en su fecha objetivo ----


async def test_R1_goes_out_only_three_days_before(rem: dict[str, Any]) -> None:
    """De fábrica, solo 3 días antes (decisión del 25/09/2026, §20.2-1). La
    fecha de la cuota es `add_months(interest_paid_until, 1)`: 6/08 ⇒ vence el
    viernes 6/09. El tope semanal se relaja para que no sea él quien calle el
    viernes: si el viernes no sale nada, es porque no se planificó."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1, customer_contact_limits={"max_per_week": 5})
    number = await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, MON)  # a 4 días: nada
    assert await _events(cid) == []

    await _run(cid, TUE)  # a 3 días
    [event] = await _events(cid, R1)
    assert event.dedupe_key == _key("due_soon", juana, "2030-09-03")
    assert event.payload["contracts"][0]["due_date"] == "2030-09-06"
    await _dispatch(cid, TUE, provider)
    assert [d.status for d in await _deliveries(cid)] == ["sent"]

    # El viernes 6 vence y entra en mora; con R2 apagado, R1 no dice nada.
    await _set_status(cid, number, "in_arrears")
    await _run(cid, FRI)
    assert [e.dedupe_key for e in await _events(cid, R1)] == [event.dedupe_key]
    await _dispatch(cid, FRI, provider)
    assert len(provider.outbox) == 1


async def test_R1_configured_three_days_before_and_on_the_due_day(rem: dict[str, Any]) -> None:
    """Una empresa que configure `[3, 0]` (§12.1-1, el default hasta el
    25/09/2026) recibe los dos. El tope semanal se relaja acá para ver salir
    los dos (su efecto tiene su test)."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(
        cid,
        R1,
        customer_contact_limits={"max_per_week": 5},
        reminders={"installment_days_before": [3, 0]},
    )
    number = await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, MON)  # a 4 días: nada
    assert await _events(cid) == []

    await _run(cid, TUE)  # a 3 días
    [event] = await _events(cid, R1)
    assert event.dedupe_key == _key("due_soon", juana, "2030-09-03")
    assert event.target_date == date(2030, 9, 3)
    assert event.customer_id == juana
    [row] = event.payload["contracts"]
    assert row["number"] == number
    assert row["due_date"] == "2030-09-06"
    assert row["amount"] == "50000.00"
    await _dispatch(cid, TUE, provider)
    assert [d.status for d in await _deliveries(cid)] == ["sent"]
    mail = provider.outbox[0]
    assert mail.to == "juana@example.com"
    assert f"#{number}" in mail.text
    assert "6 de septiembre de 2030" in mail.text
    assert "$50.000" in mail.text

    # El viernes 6 el contrato ya figura en mora (months_owed pasa a 1 ese mismo
    # día); con R2 apagado, el aviso del día del vencimiento lo lleva R1.
    await _set_status(cid, number, "in_arrears")
    await _run(cid, FRI)
    due_day = _key("due_soon", juana, "2030-09-06")
    assert [e.dedupe_key for e in await _events(cid, R1)][-1] == due_day
    await _dispatch(cid, FRI, provider)
    assert [d.status for d in await _deliveries(cid, due_day)] == ["sent"]
    assert len(provider.outbox) == 2


async def test_R2_goes_out_the_day_it_enters_arrears_and_carries_the_due_day(
    rem: dict[str, Any],
) -> None:
    """R2 sale el día en que `months_owed` pasa de 0 a 1 — que ES el día del
    vencimiento. Con R1 y R2 encendidos, ese día sale UNO: el de mora, que lo
    dice todo (el mismo criterio que C2/C3, §18.1-3)."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1, R2)
    number = await _contract(cid, juana, status="in_arrears", interest_paid_until=date(2030, 8, 3))
    provider = RecordingProvider()

    await _run(cid, TUE)
    # (Su «3 días antes», el sábado 31/08, también se registra — el job «no
    # corrió» ese día — y queda `skipped_stale`: no es lo que mira este test.)
    tuesday = [e.event_type for e in await _events(cid) if e.target_date == date(2030, 9, 3)]
    assert tuesday == [R2]
    [event] = await _events(cid, R2)
    assert event.dedupe_key == _key("arrears", juana, "2030-09-03")
    assert event.target_date == date(2030, 9, 3)
    assert event.payload["contracts"][0]["number"] == number
    await _dispatch(cid, TUE, provider)
    [mail] = provider.outbox
    assert "venció el 3 de septiembre de 2030" in mail.text
    assert "$50.000" in mail.text


async def test_R3_goes_out_the_day_it_enters_extension_and_says_it_is_informative(
    rem: dict[str, Any],
) -> None:
    """Ventana de mora 4: 3/05 + 4 meses = entra en prórroga el martes 3/09,
    y la prórroga va hasta el 3/10."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R3)
    number = await _contract(
        cid,
        juana,
        status="in_extension",
        interest_paid_until=date(2030, 5, 3),
        extension_ends_at=date(2030, 10, 3),
    )
    provider = RecordingProvider()

    await _run(cid, MON)
    assert await _events(cid, R3) == []
    await _run(cid, TUE)
    [event] = await _events(cid, R3)
    assert event.dedupe_key == _key("extension", juana, "2030-09-03")
    assert event.payload["contracts"][0]["extension_ends_at"] == "2030-10-03"
    await _dispatch(cid, TUE, provider)
    [mail] = provider.outbox
    assert f"#{number}" in mail.text
    assert "3 de octubre de 2030" in mail.text
    assert "$200.000" in mail.text  # cuatro meses de $50.000 para ponerse al día
    assert "informativo" in mail.text
    assert "no reemplaza lo pactado en su contrato" in mail.text


async def test_R4_goes_out_three_days_before_the_extension_ends(rem: dict[str, Any]) -> None:
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R4)
    number = await _contract(
        cid,
        juana,
        status="in_extension",
        interest_paid_until=date(2030, 4, 6),
        extension_ends_at=date(2030, 9, 6),
    )
    provider = RecordingProvider()

    await _run(cid, MON)
    assert await _events(cid, R4) == []
    await _run(cid, TUE)
    [event] = await _events(cid, R4)
    assert event.dedupe_key == _key("extension_ending", juana, "2030-09-03")
    await _dispatch(cid, TUE, provider)
    [mail] = provider.outbox
    assert f"#{number}" in mail.text
    assert "6 de septiembre de 2030" in mail.text
    assert "no reemplaza lo pactado en su contrato" in mail.text


# ------------------------------------------------------------------- apagado ----


async def _one_of_each_on_tuesday(cid: UUID, juana: UUID) -> None:
    await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    await _contract(cid, juana, status="in_arrears", interest_paid_until=date(2030, 8, 3))
    await _contract(
        cid,
        juana,
        status="in_extension",
        interest_paid_until=date(2030, 5, 3),
        extension_ends_at=date(2030, 10, 3),
    )
    await _contract(
        cid,
        juana,
        status="in_extension",
        interest_paid_until=date(2030, 4, 6),
        extension_ends_at=date(2030, 9, 6),
    )


async def test_off_by_default_the_fact_is_recorded_and_nothing_goes_out(
    rem: dict[str, Any],
) -> None:
    """Los cuatro nacen `default_enabled = false` (§12.3). Con la empresa
    encendida y los eventos en su default, el hecho queda y la entrega no."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid)
    await _one_of_each_on_tuesday(cid, juana)

    await _run(cid, TUE)
    tuesday = [e.event_type for e in await _events(cid) if e.target_date == date(2030, 9, 3)]
    assert sorted(tuesday) == sorted([R1, R2, R3, R4])
    assert await _deliveries(cid) == []
    provider = RecordingProvider()
    await _dispatch(cid, TUE, provider)
    assert provider.outbox == []


async def test_company_switch_off_beats_an_event_on(rem: dict[str, Any]) -> None:
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1, R2, R3, R4)
    await _exec(
        "update public.company set settings = jsonb_set(settings, "
        "'{notifications,enabled}', 'false') where id = :id",
        {"id": str(cid)},
    )
    await _one_of_each_on_tuesday(cid, juana)
    await _run(cid, TUE)
    tuesday = [e for e in await _events(cid) if e.target_date == date(2030, 9, 3)]
    assert len(tuesday) == 4
    assert await _deliveries(cid) == []


# ----------------------------------------------------- idempotencia y rezago ----


async def test_running_the_job_twice_does_not_duplicate(rem: dict[str, Any]) -> None:
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1)
    await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, TUE)
    await _dispatch(cid, TUE, provider)
    await _run(cid, TUE + timedelta(hours=3))
    await _dispatch(cid, TUE + timedelta(hours=3), provider)

    assert len(await _events(cid, R1)) == 1
    assert len(await _deliveries(cid)) == 1
    assert len(provider.outbox) == 1


async def test_late_run_inside_the_window_still_sends(rem: dict[str, Any]) -> None:
    """El job no corrió el martes ni el miércoles; el jueves (2 días tarde, y
    `stale_after_days = 2`) el recordatorio del martes todavía sale — y dice la
    FECHA de la cuota, no «en 3 días», porque ya no son 3."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1)
    await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, THU)
    key = _key("due_soon", juana, "2030-09-03")
    assert [d.status for d in await _deliveries(cid, key)] == ["pending"]
    await _dispatch(cid, THU, provider)
    assert [d.status for d in await _deliveries(cid, key)] == ["sent"]
    assert "6 de septiembre de 2030" in provider.outbox[0].text
    assert "en 3 días" not in provider.outbox[0].text


async def test_late_run_outside_the_window_is_skipped_stale(rem: dict[str, Any]) -> None:
    """§5.3: tres días tarde ya no es noticia. El hecho queda, con su entrega
    `skipped_stale` — la alarma de que el job estuvo caído —, y no sale nada."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1, R2)
    await _contract(cid, juana, status="in_arrears", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, _bog(2030, 9, 9))  # lunes 9: el martes 3 quedó 6 días atrás
    stale = _key("due_soon", juana, "2030-09-03")
    assert [d.status for d in await _deliveries(cid, stale)] == ["skipped_stale"]
    arrears = _key("arrears", juana, "2030-09-06")  # 3 días atrás
    assert [d.status for d in await _deliveries(cid, arrears)] == ["skipped_stale"]
    await _dispatch(cid, _bog(2030, 9, 9), provider)
    assert provider.outbox == []


# ------------------------------------------------------------------ agrupación ----


async def test_several_contracts_same_customer_same_day_is_one_mail(
    rem: dict[str, Any],
) -> None:
    """§2.3: el recordatorio es por (cliente, día, tipo), no por contrato. El
    martes a Juana le tocan dos cuotas que vencen el viernes (3 días antes) y
    una que vence ese mismo martes (con R2 apagado, la lleva R1): UN correo que
    nombra las tres. Pedro, sin correo, tiene su propio evento `unroutable`.
    Con `[3, 0]` configurado: de fábrica (`[3]`) todas las cuotas de un mismo
    día vencen el mismo día, y la mezcla de fechas es lo que se mira acá."""
    cid, juana, pedro = rem["company_id"], rem["juana"], rem["pedro"]
    await _enable(cid, R1, reminders={"installment_days_before": [3, 0]})
    a = await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    b = await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    c = await _contract(cid, juana, status="in_arrears", interest_paid_until=date(2030, 8, 3))
    await _contract(cid, pedro, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, TUE)
    events = [e for e in await _events(cid, R1) if e.target_date == date(2030, 9, 3)]
    assert sorted(e.customer_id for e in events) == sorted([juana, pedro])
    mine = next(e for e in events if e.customer_id == juana)
    assert [r["number"] for r in mine.payload["contracts"]] == sorted([a, b, c])
    today = [(d.status, d.to_address) for e in events for d in await _deliveries(cid, e.dedupe_key)]
    assert sorted(today, key=str) == sorted(
        [("pending", "juana@example.com"), ("unroutable", None)], key=str
    )

    await _dispatch(cid, TUE, provider)
    [mail] = provider.outbox
    for number in (a, b, c):
        assert f"#{number}" in mail.text
    assert "6 de septiembre de 2030" in mail.text
    assert "3 de septiembre de 2030" in mail.text


# -------------------------------------------------------- Ley 2300 (despacho) ----


async def test_weekly_cap_throttles_the_second_reminder_but_not_a_receipt(
    rem: dict[str, Any],
) -> None:
    """§20: los cuatro son cobranza y comparten el tope de 1 por semana; el
    comprobante de un abono (C2) no es cobranza y sale igual (§18.1-1). Con
    `[3, 0]` configurado: es el caso que llevó a sacar el 0 del default."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1, "payment_registered", reminders={"installment_days_before": [3, 0]})
    number = await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, TUE)
    await _dispatch(cid, TUE, provider)
    assert [d.status for d in await _deliveries(cid)] == ["sent"]

    await _set_status(cid, number, "in_arrears")
    await _run(cid, FRI)  # el día del vencimiento: segundo recordatorio en la semana
    receipt = await _receipt(cid, juana, number)
    await _dispatch(cid, FRI, provider)

    due_day = _key("due_soon", juana, "2030-09-06")
    [throttled] = await _deliveries(cid, due_day)
    assert throttled.status == "throttled"
    assert [d.status for d in await _deliveries(cid, receipt)] == ["sent"]
    assert len(provider.outbox) == 2
    assert "Recibimos" in provider.outbox[1].subject


async def test_with_the_default_R1_still_spends_the_week_of_R2(rem: dict[str, Any]) -> None:
    """§20.4: sacar el 0 de R1 no libera el día del vencimiento. El tope es de 7
    días corridos, y R2 nace 3 días después del R1: con los dos encendidos, R2
    queda `throttled`. Se deja fijado para que nadie lo descubra en producción."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1, R2)
    number = await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, TUE)
    await _dispatch(cid, TUE, provider)
    assert [d.status for d in await _deliveries(cid)] == ["sent"]

    await _set_status(cid, number, "in_arrears")
    await _run(cid, FRI)
    await _dispatch(cid, FRI, provider)
    assert [e.event_type for e in await _events(cid) if e.target_date == date(2030, 9, 6)] == [R2]
    [arrears] = await _deliveries(cid, _key("arrears", juana, "2030-09-06"))
    assert arrears.status == "throttled"
    assert len(provider.outbox) == 1


async def _receipt(cid: UUID, customer_id: UUID, number: int) -> str:
    """Un C2 pendiente con el payload que escribe `create_payment` (§18.2)."""
    key = f"payment:{uuid4()}"
    async with AsyncSessionLocal() as s, s.begin():
        event_id = (
            await s.execute(
                text(
                    """
                    insert into public.notification_event
                        (company_id, event_type, audience, customer_id, payload, dedupe_key,
                         occurred_on)
                    values (:cid, 'payment_registered', 'customer', :cust, cast(:p as jsonb),
                            :k, '2030-09-06')
                    returning id
                    """
                ),
                {
                    "cid": str(cid),
                    "cust": str(customer_id),
                    "k": key,
                    "p": json.dumps(
                        {
                            "contract_number": number,
                            "receipt_number": 1,
                            "amount": "50000.00",
                            "interest_paid_until": "2030-09-06",
                            "capital_balance": "1000000.00",
                        }
                    ),
                },
            )
        ).scalar_one()
        await s.execute(
            text(
                "insert into public.notification_delivery "
                "(company_id, event_id, to_address, status, legal_basis) "
                "values (:cid, :e, 'juana@example.com', 'pending', 'contract')"
            ),
            {"cid": str(cid), "e": str(event_id)},
        )
    return key


async def test_out_of_hours_waits_for_the_next_business_moment(rem: dict[str, Any]) -> None:
    """El job no tiene hora fija (§15.2-10). Si decide a las 22:00, el correo
    sale a las 7:00 del día hábil siguiente — no se pierde ni se adelanta."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R1)
    await _contract(cid, juana, status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    night = _bog(2030, 9, 3, 22)
    await _run(cid, night)
    await _dispatch(cid, night, provider)
    [delivery] = await _deliveries(cid)
    assert delivery.status == "pending"
    assert delivery.scheduled_at == _bog(2030, 9, 4, 7)
    assert provider.outbox == []

    await _dispatch(cid, _bog(2030, 9, 4, 7, 30), provider)
    assert [d.status for d in await _deliveries(cid)] == ["sent"]


# ------------------------------------------------------------------ base legal ----


async def test_without_basis_or_opted_out_it_is_suppressed(rem: dict[str, Any]) -> None:
    """§9.2-c: sin base legal → `suppressed`; dado de baja → `suppressed`, aunque
    tenga base; sin correo → `unroutable`. Solo Juana recibe."""
    cid = rem["company_id"]
    await _enable(cid, R1)
    for who in ("juana", "pedro", "ana", "luis"):
        await _contract(cid, rem[who], status="active", interest_paid_until=date(2030, 8, 6))
    provider = RecordingProvider()

    await _run(cid, TUE)
    assert [(d.status, d.to_address) for d in await _deliveries(cid)] == [
        ("suppressed", "ana@example.com"),
        ("pending", "juana@example.com"),
        ("suppressed", "luis@example.com"),
        ("unroutable", None),
    ]
    await _dispatch(cid, TUE, provider)
    assert [m.to for m in provider.outbox] == ["juana@example.com"]


# ---------------------------------------------------------------- el job ----


async def test_the_nightly_job_runs_reminders_after_statuses_and_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§5.2: después de `recompute_all_statuses` (R2/R3 se leen del estado que
    ese paso persiste) y antes del despachador (que manda lo que el paso crea)."""
    order: list[str] = []

    async def _step(name: str, value: Any) -> Any:
        order.append(name)
        return value

    monkeypatch.setattr(
        nightly.contracts_service, "recompute_all_statuses", lambda db: _step("statuses", 0)
    )
    monkeypatch.setattr(
        nightly.platform_service,
        "expire_overdue_subscriptions",
        lambda db: _step("subscriptions", 0),
    )
    monkeypatch.setattr(
        nightly.notifications_digest,
        "build_all_digests",
        lambda **kw: _step("digest", nightly.notifications_digest.DigestRunStats()),
    )
    monkeypatch.setattr(
        nightly.notifications_reminders,
        "build_all_reminders",
        lambda **kw: _step("reminders", reminders.ReminderRunStats()),
    )
    monkeypatch.setattr(
        nightly.notifications_dispatcher,
        "dispatch_due",
        lambda **kw: _step("dispatch", dispatcher.DispatchStats()),
    )
    await nightly.run(now=TUE, provider=RecordingProvider())
    assert order == ["statuses", "subscriptions", "digest", "reminders", "dispatch"]


async def test_catalog_keeps_the_four_reminders_off() -> None:
    for code in (R1, R2, R3, R4, catalog.AUCTION_READY_CUSTOMER):
        assert catalog.get(code).default_enabled is False


async def test_a_payment_inside_the_extension_does_not_restart_R3(rem: dict[str, Any]) -> None:
    """Entró en prórroga el 1/08 (ancla 1/04, ventana 4; vence el 1/09). Abona un
    mes y sigue en prórroga (debe más de la ventana): el ancla pasa al 1/05 y el
    día de entrada DERIVADO sería el 1/09 — dentro de la ventana de búsqueda.
    No hay un segundo «entró en prórroga» (`contracts.integration`)."""
    cid, juana = rem["company_id"], rem["juana"]
    await _enable(cid, R3)
    await _contract(
        cid,
        juana,
        status="in_extension",
        interest_paid_until=date(2030, 5, 1),
        extension_ends_at=date(2030, 9, 1),
    )
    await _run(cid, TUE)
    assert await _events(cid, R3) == []


async def test_preferences_read_back_a_bad_schedule_as_the_default() -> None:
    """El jsonb se puede escribir por otros caminos: leer es tan estricto como
    escribir, y lo que no se entiende cae al default."""
    from app.modules.notifications import preferences

    for raw in ([31], ["3"], [True], "3", [1, 2, 3, 4, 5, 6]):
        prefs = preferences.parse(
            {"notifications": {"reminders": {"installment_days_before": raw}}}
        )
        assert prefs.reminders.installment_days_before == (3,), raw
    # Un faltante, en cualquier nivel, también: ninguna empresa necesita backfill.
    for settings in (None, {}, {"notifications": {}}, {"notifications": {"reminders": {}}}):
        assert preferences.parse(settings).reminders.installment_days_before == (3,), settings
    ok = preferences.parse({"notifications": {"reminders": {"extension_days_before": [1, 7]}}})
    assert ok.reminders.extension_days_before == (7, 1)
