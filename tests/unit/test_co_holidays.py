"""Festivos de Colombia (app/common/co_holidays.py): el despachador los usa
para no escribirle a un cliente un festivo (Ley 2300, NOTIFICACIONES §12.3)."""

from datetime import date

from app.common.co_holidays import colombian_holidays, easter_sunday, is_colombian_holiday


def test_easter_known_years() -> None:
    assert easter_sunday(2024) == date(2024, 3, 31)
    assert easter_sunday(2025) == date(2025, 4, 20)
    assert easter_sunday(2026) == date(2026, 4, 5)
    assert easter_sunday(2030) == date(2030, 4, 21)


def test_2026_calendar_matches_the_official_list() -> None:
    assert colombian_holidays(2026) == {
        date(2026, 1, 1),
        date(2026, 1, 12),  # Reyes, trasladado
        date(2026, 3, 23),  # San José, trasladado
        date(2026, 4, 2),  # Jueves Santo
        date(2026, 4, 3),  # Viernes Santo
        date(2026, 5, 1),
        date(2026, 5, 18),  # Ascensión
        date(2026, 6, 8),  # Corpus Christi
        date(2026, 6, 15),  # Sagrado Corazón
        date(2026, 6, 29),  # San Pedro y San Pablo (ya es lunes)
        date(2026, 7, 20),
        date(2026, 8, 7),
        date(2026, 8, 17),  # Asunción, trasladado
        date(2026, 10, 12),  # Día de la Raza (ya es lunes)
        date(2026, 11, 2),  # Todos los Santos, trasladado
        date(2026, 11, 16),  # Independencia de Cartagena, trasladado
        date(2026, 12, 8),
        date(2026, 12, 25),
    }


def test_moved_holiday_leaves_the_original_day_workable() -> None:
    # 12 oct 2030 es sábado: el festivo se corre al lunes 14.
    assert not is_colombian_holiday(date(2030, 10, 12))
    assert is_colombian_holiday(date(2030, 10, 14))
