"""Límites de contacto al cliente (Ley 2300) como PARÁMETROS del despachador
(docs/NOTIFICACIONES.md §12.3). Puro: sin BD."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.modules.notifications.limits import (
    cap_release_moment,
    exceeds_cap,
    is_allowed_moment,
    next_allowed_moment,
)
from app.modules.notifications.preferences import ContactLimits

BOG = ZoneInfo("America/Bogota")
DEFAULT = ContactLimits()


def _at(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=BOG)


def test_weekday_window_is_7_to_19() -> None:
    assert not is_allowed_moment(_at(2030, 9, 2, 6, 59), DEFAULT)
    assert is_allowed_moment(_at(2030, 9, 2, 7, 0), DEFAULT)
    assert is_allowed_moment(_at(2030, 9, 2, 18, 59), DEFAULT)
    assert not is_allowed_moment(_at(2030, 9, 2, 19, 0), DEFAULT)


def test_saturday_window_is_8_to_15() -> None:
    assert not is_allowed_moment(_at(2030, 9, 7, 7, 30), DEFAULT)
    assert is_allowed_moment(_at(2030, 9, 7, 14, 0), DEFAULT)
    assert not is_allowed_moment(_at(2030, 9, 7, 15, 0), DEFAULT)


def test_sunday_moves_to_monday_morning() -> None:
    assert next_allowed_moment(_at(2030, 9, 1, 10), DEFAULT) == _at(2030, 9, 2, 7)


def test_saturday_afternoon_skips_sunday() -> None:
    assert next_allowed_moment(_at(2030, 9, 7, 16), DEFAULT) == _at(2030, 9, 9, 7)


def test_holiday_monday_moves_to_tuesday() -> None:
    # 14/10/2030: Día de la Raza trasladado al lunes.
    assert next_allowed_moment(_at(2030, 10, 14, 9), DEFAULT) == _at(2030, 10, 15, 7)


def test_night_moves_to_next_morning_and_inside_window_is_untouched() -> None:
    assert next_allowed_moment(_at(2030, 9, 3, 3), DEFAULT) == _at(2030, 9, 3, 7)
    assert next_allowed_moment(_at(2030, 9, 3, 10, 15), DEFAULT) == _at(2030, 9, 3, 10, 15)


def test_disabled_limits_allow_anything() -> None:
    off = ContactLimits(enabled=False)
    assert is_allowed_moment(_at(2030, 9, 1, 3), off)
    assert not exceeds_cap(sent_last_day=10, sent_last_week=10, limits=off)


def test_limits_are_parameters_not_constants() -> None:
    relaxed = ContactLimits(
        sundays_and_holidays=True, weekday_start=time(6, 0), weekday_end=time(21, 0)
    )
    assert is_allowed_moment(_at(2030, 9, 1, 20), relaxed)


def test_weekly_and_daily_caps() -> None:
    assert not exceeds_cap(sent_last_day=0, sent_last_week=0, limits=DEFAULT)
    assert exceeds_cap(sent_last_day=0, sent_last_week=1, limits=DEFAULT)
    three_a_week = ContactLimits(max_per_week=5, max_per_day=3)
    assert exceeds_cap(sent_last_day=3, sent_last_week=3, limits=three_a_week)
    assert not exceeds_cap(sent_last_day=2, sent_last_week=4, limits=three_a_week)


def test_a_receipt_is_not_stopped_by_the_weekly_cap_but_is_by_the_daily_one() -> None:
    """§18.1-1: el semanal es el de la Ley 2300, de cobranza; el diario (§3) es
    de producto y cuenta todo."""
    assert not exceeds_cap(sent_last_day=1, sent_last_week=5, limits=DEFAULT, transactional=True)
    assert exceeds_cap(sent_last_day=3, sent_last_week=0, limits=DEFAULT, transactional=True)
    # La respuesta del abogado, como parámetro: el comprobante vuelve a contar.
    strict = ContactLimits(transactional_in_weekly_cap=True)
    assert exceeds_cap(sent_last_day=0, sent_last_week=1, limits=strict, transactional=True)
    # Y un recordatorio sigue frenado por el semanal, como siempre.
    assert exceeds_cap(sent_last_day=0, sent_last_week=1, limits=DEFAULT, transactional=False)


# ------------------------------------ cuándo se libera el cupo (§20.6) ----

_SECOND = timedelta(seconds=1)


def test_under_the_cap_the_moment_is_now() -> None:
    now = _at(2030, 9, 6, 12)
    assert cap_release_moment(now=now, sent_last_day=[], sent_last_week=[], limits=DEFAULT) == now


def test_the_week_frees_up_when_the_oldest_contact_leaves_the_window() -> None:
    """El despachador cuenta `sent_at >= now − 7 días`: a las 12:00 en punto del
    martes siguiente el de las 12:00 del martes TODAVÍA cuenta. Un segundo
    después, no."""
    r1 = _at(2030, 9, 3, 12)
    moment = cap_release_moment(
        now=_at(2030, 9, 6, 12), sent_last_day=[], sent_last_week=[r1], limits=DEFAULT
    )
    assert moment == _at(2030, 9, 10, 12) + _SECOND


def test_with_a_cap_of_two_it_is_the_second_most_recent_that_must_leave() -> None:
    """Si el tope bajó y hay más enviados que cupo, no alcanza con que salga el
    más viejo: tiene que quedar uno menos que el tope."""
    two = ContactLimits(max_per_week=2)
    sent = [_at(2030, 9, 2, 9), _at(2030, 9, 3, 9), _at(2030, 9, 4, 9)]
    moment = cap_release_moment(
        now=_at(2030, 9, 5, 9), sent_last_day=[], sent_last_week=sent, limits=two
    )
    assert moment == _at(2030, 9, 10, 9) + _SECOND


def test_the_daily_cap_frees_up_after_24_hours_and_both_caps_must_allow() -> None:
    """Tres comprobantes hoy (no cuentan en el semanal) frenan un recordatorio
    por el DIARIO: se libera cuando el primero cumple 24 h. Con los dos topes
    llenos, gana el que se libera más tarde."""
    receipts = [_at(2030, 9, 6, 9), _at(2030, 9, 6, 10), _at(2030, 9, 6, 11)]
    now = _at(2030, 9, 6, 12)
    daily = cap_release_moment(now=now, sent_last_day=receipts, sent_last_week=[], limits=DEFAULT)
    assert daily == _at(2030, 9, 7, 9) + _SECOND
    both = cap_release_moment(
        now=now, sent_last_day=receipts, sent_last_week=[_at(2030, 9, 3, 12)], limits=DEFAULT
    )
    assert both == _at(2030, 9, 10, 12) + _SECOND


def test_a_cap_of_zero_never_frees_up_and_disabled_limits_never_wait() -> None:
    now = _at(2030, 9, 6, 12)
    never = ContactLimits(max_per_week=0)
    assert cap_release_moment(now=now, sent_last_day=[], sent_last_week=[], limits=never) is None
    off = ContactLimits(enabled=False)
    busy = [_at(2030, 9, 6, 9)] * 5
    assert cap_release_moment(now=now, sent_last_day=busy, sent_last_week=busy, limits=off) == now
