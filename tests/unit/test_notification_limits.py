"""Límites de contacto al cliente (Ley 2300) como PARÁMETROS del despachador
(docs/NOTIFICACIONES.md §12.3). Puro: sin BD."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.modules.notifications.limits import exceeds_cap, is_allowed_moment, next_allowed_moment
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
