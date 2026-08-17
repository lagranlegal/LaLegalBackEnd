from datetime import date
from decimal import Decimal

from app.modules.contracts.rules import (
    add_months,
    compute_status,
    monthly_interest,
    months_between,
    months_since_start_exact,
    quote_payment_options,
)


class TestAddMonths:
    def test_simple(self) -> None:
        assert add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)

    def test_year_rollover(self) -> None:
        assert add_months(date(2026, 12, 15), 2) == date(2027, 2, 15)

    def test_clamps_to_shorter_month(self) -> None:
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_clamps_to_leap_day(self) -> None:
        assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)  # 2028 es bisiesto

    def test_zero_months_is_noop(self) -> None:
        assert add_months(date(2026, 3, 10), 0) == date(2026, 3, 10)


class TestMonthsBetween:
    def test_exact_one_month(self) -> None:
        assert months_between(date(2026, 1, 15), date(2026, 2, 15)) == 1

    def test_one_day_short_of_a_month(self) -> None:
        assert months_between(date(2026, 1, 15), date(2026, 2, 14)) == 0

    def test_one_day_past_a_month_is_still_one(self) -> None:
        assert months_between(date(2026, 1, 15), date(2026, 2, 16)) == 1

    def test_same_day_is_zero(self) -> None:
        assert months_between(date(2026, 1, 15), date(2026, 1, 15)) == 0

    def test_end_before_start_is_zero(self) -> None:
        assert months_between(date(2026, 2, 1), date(2026, 1, 1)) == 0

    def test_month_end_edge_case_matches_add_months_clamping(self) -> None:
        # 31-ene + 1 mes "completo" cae en 28-feb (add_months la recorta ahí),
        # así que 28-feb SÍ debe contar como un mes completo, no cero.
        assert months_between(date(2026, 1, 31), date(2026, 2, 28)) == 1
        assert months_between(date(2026, 1, 31), date(2026, 2, 27)) == 0

    def test_several_months(self) -> None:
        assert months_between(date(2025, 1, 1), date(2026, 4, 1)) == 15


class TestMonthsSinceStartExact:
    """docs/MIGRACION_CONTRATOS.md §3: valida `interest_paid_until` contra
    `start_date` en el import — reusa `add_months`, la misma convención de
    fin de mes que `due_date`/`months_owed`."""

    def test_same_day_is_zero_months(self) -> None:
        assert months_since_start_exact(date(2026, 1, 10), date(2026, 1, 10)) == 0

    def test_exact_multiple_of_months(self) -> None:
        assert months_since_start_exact(date(2026, 1, 10), date(2026, 6, 10)) == 5

    def test_one_day_off_is_misaligned(self) -> None:
        assert months_since_start_exact(date(2026, 1, 10), date(2026, 6, 11)) is None
        assert months_since_start_exact(date(2026, 1, 10), date(2026, 6, 9)) is None

    def test_before_start_date_is_misaligned(self) -> None:
        assert months_since_start_exact(date(2026, 6, 1), date(2026, 5, 1)) is None

    def test_future_prepaid_is_valid(self) -> None:
        # el cliente pagó intereses por adelantado en el sistema viejo:
        # interest_paid_until en el futuro respecto a start_date es válido.
        assert months_since_start_exact(date(2026, 1, 10), date(2027, 1, 10)) == 12

    def test_month_end_clamping_31_to_28(self) -> None:
        # 31-ene + 1 mes "completo" cae en 28-feb (add_months la recorta ahí,
        # igual que en months_between) — debe alinear, no rechazar.
        assert months_since_start_exact(date(2026, 1, 31), date(2026, 2, 28)) == 1
        assert months_since_start_exact(date(2026, 1, 31), date(2026, 2, 27)) is None

    def test_month_end_clamping_31_to_leap_29(self) -> None:
        assert months_since_start_exact(date(2028, 1, 31), date(2028, 2, 29)) == 1


class TestMonthlyInterest:
    def test_basic_five_percent(self) -> None:
        assert monthly_interest(Decimal("5"), Decimal("1000000")) == Decimal("50000.00")

    def test_quantizes_to_cents(self) -> None:
        # 4.99% de 333333 = 16633.3167 -> redondeo a 16633.32
        result = monthly_interest(Decimal("4.99"), Decimal("333333"))
        assert result == Decimal("16633.32")

    def test_decreases_as_balance_decreases(self) -> None:
        before = monthly_interest(Decimal("5"), Decimal("1000000"))
        after = monthly_interest(Decimal("5"), Decimal("800000"))
        assert after < before
        assert after == Decimal("40000.00")


class TestQuotePaymentOptions:
    def test_up_to_date_has_no_options(self) -> None:
        quote = quote_payment_options(
            capital_balance=Decimal("1000000"),
            interest_rate_pct=Decimal("5"),
            interest_paid_until=date(2026, 3, 1),
            today=date(2026, 3, 1),
        )
        assert quote.months_owed == 0
        assert quote.options == []

    def test_two_months_owed_gives_two_options(self) -> None:
        quote = quote_payment_options(
            capital_balance=Decimal("1000000"),
            interest_rate_pct=Decimal("5"),
            interest_paid_until=date(2026, 1, 1),
            today=date(2026, 3, 5),
        )
        assert quote.months_owed == 2
        assert quote.monthly_interest == Decimal("50000.00")
        assert [o.months for o in quote.options] == [1, 2]
        assert quote.options[0].total == Decimal("50000.00")
        assert quote.options[1].total == Decimal("100000.00")

    def test_only_the_full_catch_up_option_allows_capital(self) -> None:
        quote = quote_payment_options(
            capital_balance=Decimal("1000000"),
            interest_rate_pct=Decimal("5"),
            interest_paid_until=date(2026, 1, 1),
            today=date(2026, 3, 5),
        )
        assert quote.options[0].allows_capital is False
        assert quote.options[1].allows_capital is True


class TestComputeStatus:
    def test_up_to_date_is_active(self) -> None:
        status, ext = compute_status(
            current_status="active",
            interest_paid_until=date(2026, 3, 1),
            arrears_window_months=4,
            extension_months=1,
            extension_ends_at=None,
            today=date(2026, 3, 1),
        )
        assert status == "active"
        assert ext is None

    def test_below_window_is_in_arrears(self) -> None:
        status, ext = compute_status(
            current_status="active",
            interest_paid_until=date(2026, 1, 1),
            arrears_window_months=4,
            extension_months=1,
            extension_ends_at=None,
            today=date(2026, 3, 1),  # 2 meses adeudados, ventana 4
        )
        assert status == "in_arrears"
        assert ext is None

    def test_reaching_window_triggers_extension(self) -> None:
        status, ext = compute_status(
            current_status="in_arrears",
            interest_paid_until=date(2026, 1, 1),
            arrears_window_months=4,
            extension_months=1,
            extension_ends_at=None,
            today=date(2026, 5, 1),  # exactamente 4 meses adeudados
        )
        assert status == "in_extension"
        # dispara en interest_paid_until + 4 meses = 2026-05-01, +1 mes de prórroga
        assert ext == date(2026, 6, 1)

    def test_already_in_extension_does_not_retrigger(self) -> None:
        original_ext = date(2026, 6, 1)
        status, ext = compute_status(
            current_status="in_extension",
            interest_paid_until=date(2026, 1, 1),
            arrears_window_months=4,
            extension_months=1,
            extension_ends_at=original_ext,
            today=date(2026, 9, 1),  # muchos meses después, ya en prórroga
        )
        assert status == "in_extension"
        assert ext == original_ext  # no se recalcula

    def test_terminal_statuses_never_change(self) -> None:
        for terminal in ("paid", "auctioned"):
            status, _ = compute_status(
                current_status=terminal,
                interest_paid_until=date(2020, 1, 1),
                arrears_window_months=4,
                extension_months=1,
                extension_ends_at=None,
                today=date(2026, 1, 1),
            )
            assert status == terminal
