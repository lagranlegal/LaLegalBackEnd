"""El planificador de los recordatorios al cliente R1–R4 (docs/NOTIFICACIONES.md
§2.2, §2.3, §6.1, §20) — puro, sin base: recibe los contratos con sus fechas
ya derivadas por `contracts.integration` y decide qué eventos nacen.

Martes 3 de septiembre de 2030 es el «hoy» de casi todos."""

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


def _plan(
    contracts: list[ReminderContract], *, on: set[str], today: date = TODAY
) -> list[reminders.PlannedReminder]:
    return reminders.plan_reminders(
        contracts,
        today=today,
        schedule=ReminderSchedule(),
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
        )
    )
    by_customer = {p.customer_id: p for p in planned if p.event_type == R1}
    assert set(by_customer) == {juana, pedro}
    assert [r["number"] for r in by_customer[juana].payload()["contracts"]] == [1, 2, 3]


def test_the_due_day_is_ONE_notice_arrears_wins_if_on() -> None:
    """El día del vencimiento el contrato entra en mora (months_owed = 1). R1
    «vence hoy» y R2 «venció» serían el mismo aviso dos veces: sale R2 si está
    encendido, y R1 si solo R1 lo está (como C2/C3, §18.1-3). El hecho de la
    mora se planifica siempre —apagado se registra sin entrega, §4.3—; lo que
    cambia es si R1 lo lleva también."""
    juana = uuid4()
    contract = _c(
        juana, 1, status="in_arrears", due=date(2030, 9, 3), arrears_on=date(2030, 9, 3), owed=1
    )
    assert [p.event_type for p in _on_today(_plan([contract], on={R1, R2}))] == [R2]
    assert sorted(p.event_type for p in _on_today(_plan([contract], on={R1}))) == [R1, R2]
    # Los dos apagados: se registran los dos hechos, ninguno con entrega.
    assert sorted(p.event_type for p in _on_today(_plan([contract], on=set()))) == [R1, R2]


def test_window_one_contract_goes_straight_to_extension_and_R3_carries_the_due_day() -> None:
    """Tecnología (ventana 1): el día del vencimiento entra en PRÓRROGA, sin pasar
    por mora. Ese día el aviso lo lleva R3."""
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
    assert [p.event_type for p in _on_today(_plan([contract], on={R1, R3}))] == [R3]
    assert sorted(p.event_type for p in _on_today(_plan([contract], on={R1}))) == [R3, R1]


def test_nothing_before_its_day_and_nothing_older_than_the_lookback() -> None:
    juana = uuid4()
    assert _plan([_c(juana, 1, due=date(2030, 9, 7))], on={R1}) == []  # a 4 días
    # El «3 días antes» de una cuota que venció ayer sí se planifica (hace 4
    # días, dentro de la ventana): es el que el rezago deja `skipped_stale`.
    late = _plan([_c(juana, 1, status="in_arrears", due=date(2030, 9, 2))], on={R1})
    assert [p.target_date for p in late] == [date(2030, 8, 30), date(2030, 9, 2)]
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
