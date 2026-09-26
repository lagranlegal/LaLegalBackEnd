"""El planificador de los recordatorios al cliente R1–R4 (docs/NOTIFICACIONES.md
§2.2, §2.3, §6.1, §20) — puro, sin base: recibe los contratos con sus fechas
ya derivadas por `contracts.integration` y decide qué eventos nacen.

Martes 3 de septiembre de 2030 es el «hoy» de casi todos.

De fábrica R1 sale solo 3 días antes (`[3]`, decisión del 25/09/2026). Los
tests del choque «el día del vencimiento» configuran `[3, 0]` a propósito:
una empresa puede volver a pedir el aviso del día, y ahí el choque existe."""

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from app.modules.contracts.integration import ReminderContract
from app.modules.notifications import reminders
from app.modules.notifications.preferences import ReminderSchedule

TODAY = date(2030, 9, 3)
R1, R2, R3, R4 = (
    "installment_due_soon",
    "installment_overdue",
    "extension_started",
    "extension_ending_soon",
)


def _c(
    customer: UUID,
    number: int,
    *,
    status: str = "active",
    due: date,
    arrears_on: date | None = None,
    extension_on: date | None = None,
    extension_ends_at: date | None = None,
    window: int = 4,
    owed: int = 0,
) -> ReminderContract:
    return ReminderContract(
        contract_id=uuid4(),
        number=number,
        customer_id=customer,
        status=status,
        arrears_window_months=window,
        next_due_date=due,
        arrears_entered_on=arrears_on,
        extension_entered_on=extension_on,
        extension_ends_at=extension_ends_at,
        capital_balance=Decimal("1000000.00"),
        monthly_interest=Decimal("50000.00"),
        months_owed=owed,
        amount_to_catch_up=Decimal("50000.00") * owed,
    )


#: Lo que una empresa configura si quiere también el aviso del día (§20.2-1).
WITH_DUE_DAY = ReminderSchedule(installment_days_before=(3, 0))


def _plan(
    contracts: list[ReminderContract],
    *,
    on: set[str],
    today: date = TODAY,
    schedule: ReminderSchedule | None = None,
) -> list[reminders.PlannedReminder]:
    return reminders.plan_reminders(
        contracts,
        today=today,
        schedule=schedule or ReminderSchedule(),
        lookback_days=7,
        event_enabled=lambda code: code in on,
    )


def _on_today(planned: list[reminders.PlannedReminder]) -> list[reminders.PlannedReminder]:
    """Solo lo del día. Un contrato que vence HOY también tuvo su «3 días antes»
    hace tres días, dentro de la ventana de búsqueda: ese se planifica igual (y
    el rezago lo deja `skipped_stale` si nunca se registró) — no es lo que
    miran estos tests."""
    return [p for p in planned if p.target_date == TODAY]


def test_keys_carry_the_customer_and_the_target_day_not_the_run_day() -> None:
    juana = uuid4()
    [planned] = _plan([_c(juana, 1, due=date(2030, 9, 6))], on={R1})
    assert planned.event_type == R1
    assert planned.target_date == date(2030, 9, 3)
    assert planned.dedupe_key == f"due_soon:{juana}:2030-09-03"
    # Corrido dos días después, la llave es la misma: habla del martes.
    [late] = _plan([_c(juana, 1, due=date(2030, 9, 6))], on={R1}, today=date(2030, 9, 5))
    assert late.dedupe_key == planned.dedupe_key


def test_the_default_is_ONE_R1_three_days_before_and_nothing_on_the_due_day() -> None:
    """Decisión del 25/09/2026: de fábrica, R1 solo 3 días antes. Con el tope
    semanal de la Ley 2300 el aviso del día casi siempre quedaba `throttled`
    —el de 3 días antes ya gastaba el cupo—, y 3 días le dan al cliente tiempo
    de conseguir la plata."""
    assert ReminderSchedule().installment_days_before == (3,)
    juana = uuid4()
    [planned] = _plan([_c(juana, 1, due=date(2030, 9, 6))], on={R1})
    assert (planned.event_type, planned.target_date) == (R1, date(2030, 9, 3))
    # El día del vencimiento, aun con R2 apagado: R1 no dice nada.
    due_today = _c(
        juana, 1, status="in_arrears", due=date(2030, 9, 3), arrears_on=date(2030, 9, 3), owed=1
    )
    assert [p.event_type for p in _on_today(_plan([due_today], on={R1}))] == [R2]
    # Y el mismo contrato visto desde cada día de la semana: un solo R1.
    days = {
        p.target_date
        for today in (date(2030, 9, d) for d in range(1, 8))
        for p in _plan([_c(juana, 1, due=date(2030, 9, 6))], on={R1}, today=today)
    }
    assert days == {date(2030, 9, 3)}


def test_one_event_per_customer_day_and_type_listing_every_contract() -> None:
    juana, pedro = uuid4(), uuid4()
    planned = _on_today(
        _plan(
            [
                _c(juana, 3, due=date(2030, 9, 6)),
                _c(juana, 1, due=date(2030, 9, 6)),
                _c(
                    juana, 2, status="in_arrears", due=date(2030, 9, 3), arrears_on=date(2030, 9, 3)
                ),
                _c(pedro, 4, due=date(2030, 9, 6)),
            ],
            on={R1},
            schedule=WITH_DUE_DAY,  # el #2 entra por el aviso del día
        )
    )
    by_customer = {p.customer_id: p for p in planned if p.event_type == R1}
    assert set(by_customer) == {juana, pedro}
    assert [r["number"] for r in by_customer[juana].payload()["contracts"]] == [1, 2, 3]


def test_the_due_day_is_ONE_notice_arrears_wins_if_on() -> None:
    """Con `[3, 0]` configurado (de fábrica ya no: §20.2-1). El día del
    vencimiento el contrato entra en mora (months_owed = 1). R1
    «vence hoy» y R2 «venció» serían el mismo aviso dos veces: sale R2 si está
    encendido, y R1 si solo R1 lo está (como C2/C3, §18.1-3). El hecho de la
    mora se planifica siempre —apagado se registra sin entrega, §4.3—; lo que
    cambia es si R1 lo lleva también."""
    juana = uuid4()
    contract = _c(
        juana, 1, status="in_arrears", due=date(2030, 9, 3), arrears_on=date(2030, 9, 3), owed=1
    )

    def today(on: set[str]) -> list[str]:
        return sorted(
            p.event_type for p in _on_today(_plan([contract], on=on, schedule=WITH_DUE_DAY))
        )

    assert today({R1, R2}) == [R2]
    assert today({R1}) == [R1, R2]
    # Los dos apagados: se registran los dos hechos, ninguno con entrega.
    assert today(set()) == [R1, R2]


def test_window_one_contract_goes_straight_to_extension_and_R3_carries_the_due_day() -> None:
    """Tecnología (ventana 1), con `[3, 0]` configurado: el día del vencimiento
    entra en PRÓRROGA, sin pasar por mora. Ese día el aviso lo lleva R3."""
    juana = uuid4()
    contract = _c(
        juana,
        1,
        status="in_extension",
        due=date(2030, 9, 3),
        extension_on=date(2030, 9, 3),
        extension_ends_at=date(2030, 10, 3),
        window=1,
        owed=1,
    )

    def today(on: set[str]) -> list[str]:
        return sorted(
            p.event_type for p in _on_today(_plan([contract], on=on, schedule=WITH_DUE_DAY))
        )

    assert today({R1, R3}) == [R3]
    assert today({R1}) == [R3, R1]


def test_nothing_before_its_day_and_nothing_older_than_the_lookback() -> None:
    juana = uuid4()
    assert _plan([_c(juana, 1, due=date(2030, 9, 7))], on={R1}) == []  # a 4 días
    # El «3 días antes» de una cuota que venció ayer sí se planifica (hace 4
    # días, dentro de la ventana): es el que el rezago deja `skipped_stale`.
    late = _plan([_c(juana, 1, status="in_arrears", due=date(2030, 9, 2))], on={R1})
    assert [p.target_date for p in late] == [date(2030, 8, 30)]
    with_due_day = _plan(
        [_c(juana, 1, status="in_arrears", due=date(2030, 9, 2))], on={R1}, schedule=WITH_DUE_DAY
    )
    assert [p.target_date for p in with_due_day] == [date(2030, 8, 30), date(2030, 9, 2)]
    old = _c(juana, 1, status="in_arrears", due=date(2030, 8, 20), arrears_on=date(2030, 8, 20))
    assert _plan([old], on={R2}) == []  # 14 días atrás: fuera de la ventana de búsqueda


def test_extension_reminders() -> None:
    juana = uuid4()
    started = _c(
        juana,
        1,
        status="in_extension",
        due=date(2030, 5, 3),
        extension_on=date(2030, 9, 3),
        extension_ends_at=date(2030, 10, 3),
        owed=4,
    )
    ending = _c(
        juana,
        2,
        status="in_extension",
        due=date(2030, 5, 6),
        extension_on=date(2030, 8, 6),
        extension_ends_at=date(2030, 9, 6),
        owed=4,
    )
    planned = {p.event_type: p for p in _plan([started, ending], on={R3, R4})}
    assert set(planned) == {R3, R4}
    assert planned[R3].dedupe_key == f"extension:{juana}:2030-09-03"
    assert planned[R3].payload()["contracts"][0]["amount"] == "200000.00"
    assert planned[R4].dedupe_key == f"extension_ending:{juana}:2030-09-03"
    assert planned[R4].payload()["contracts"][0]["extension_ends_at"] == "2030-09-06"


def test_extension_without_a_coherent_entry_day_does_not_restart_R3() -> None:
    """`contracts.integration` deja `extension_entered_on = None` cuando el ancla
    se movió con la prórroga en curso: no hay un segundo «entró en prórroga»."""
    juana = uuid4()
    moved = _c(
        juana,
        1,
        status="in_extension",
        due=date(2030, 6, 3),
        extension_on=None,
        extension_ends_at=date(2030, 9, 1),
        owed=4,
    )
    assert [p.event_type for p in _plan([moved], on={R3}) if p.event_type == R3] == []


def test_payload_carries_numbers_dates_and_amounts_only() -> None:
    juana = uuid4()
    [planned] = _plan([_c(juana, 7, due=date(2030, 9, 6))], on={R1})
    [row] = planned.payload()["contracts"]
    assert set(row) == {"number", "due_date", "amount", "capital_balance"}
    assert row == {
        "number": 7,
        "due_date": "2030-09-06",
        "amount": "50000.00",
        "capital_balance": "1000000.00",
    }


# ------------------------- hasta cuándo se puede reprogramar uno (§20.6) ----


def test_R1_and_R4_can_wait_only_until_the_date_they_announce() -> None:
    """«Su cuota vence el 6» sigue siendo cierto el 6; el 7 es desinformación.
    Con varios contratos, manda el que vence primero. Un payload del formato
    viejo (la fecha arriba) también se lee; sin fecha, no se reprograma."""
    r1 = {
        "contracts": [
            {"number": 1, "due_date": "2030-09-09"},
            {"number": 2, "due_date": "2030-09-06"},
        ]
    }
    assert reminders.deferrable_until(R1, r1) == date(2030, 9, 6)
    old = {"due_date": "2030-09-05", "contracts": [{"number": 1, "amount": "50000"}]}
    assert reminders.deferrable_until(R1, old) == date(2030, 9, 5)
    assert reminders.deferrable_until(R1, {"contracts": []}) is None
    r4 = {"contracts": [{"number": 3, "extension_ends_at": "2030-10-03"}]}
    assert reminders.deferrable_until(R4, r4) == date(2030, 10, 3)


def test_R2_and_R3_do_not_expire_by_date_and_the_rest_are_not_deferred() -> None:
    """La mora y la prórroga siguen siendo ciertas días después: las acota la
    re-verificación al enviar, no una fecha. Un comprobante o R5 no se
    reprograman."""
    assert reminders.deferrable_until(R2, {"contracts": []}) == date.max
    assert reminders.deferrable_until(R3, {"contracts": []}) == date.max
    assert reminders.deferrable_until("payment_registered", {}) is None
    assert reminders.deferrable_until("auction_ready_customer", {}) is None
