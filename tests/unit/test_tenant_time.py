from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.common.tenant_time import today_in


def test_bogota_is_still_yesterday_when_utc_already_rolled_over() -> None:
    # 02:00 UTC == 21:00 del día anterior en Bogotá (UTC-5, sin horario de
    # verano) — el caso exacto del bug real encontrado en el paso 6: en esta
    # ventana, un `date.today()` naive del servidor (UTC) calcula un día
    # adelantado respecto al día de negocio real de la empresa.
    reference = datetime(2026, 8, 15, 2, 0, tzinfo=UTC)
    assert today_in("America/Bogota", now=reference).isoformat() == "2026-08-14"
    assert reference.date().isoformat() == "2026-08-15"  # lo que daría un date.today() naive


def test_outside_the_skew_window_both_agree() -> None:
    reference = datetime(2026, 8, 15, 15, 0, tzinfo=UTC)  # 10am Bogotá
    assert today_in("America/Bogota", now=reference).isoformat() == "2026-08-15"


def test_unknown_timezone_falls_back_to_default() -> None:
    reference = datetime(2026, 8, 15, 2, 0, tzinfo=UTC)
    assert today_in("Not/AnActualTimezone", now=reference) == today_in(
        "America/Bogota", now=reference
    )


def test_none_timezone_uses_default() -> None:
    reference = datetime(2026, 8, 15, 2, 0, tzinfo=UTC)
    assert today_in(None, now=reference) == today_in("America/Bogota", now=reference)


def test_matches_real_clock_when_now_not_given() -> None:
    expected = datetime.now(ZoneInfo("America/Bogota")).date()
    assert today_in("America/Bogota") == expected


# --- mes en curso y mes anterior (dashboard: «vs. agosto») -----------------
def test_el_mes_anterior_es_completo_y_termina_la_vispera_del_primero() -> None:
    from app.common.tenant_time import previous_month_bounds

    assert previous_month_bounds(date(2026, 9, 30)) == (date(2026, 8, 1), date(2026, 8, 31))
    assert previous_month_bounds(date(2026, 3, 1)) == (date(2026, 2, 1), date(2026, 2, 28))


def test_en_enero_el_mes_anterior_es_diciembre_del_ano_pasado() -> None:
    from app.common.tenant_time import previous_month_bounds

    assert previous_month_bounds(date(2027, 1, 15)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_el_mes_en_curso_empieza_el_primero() -> None:
    from app.common.tenant_time import month_start

    assert month_start(date(2026, 2, 28)) == date(2026, 2, 1)
