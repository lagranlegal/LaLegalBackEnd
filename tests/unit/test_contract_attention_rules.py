"""«Para hoy» (`GET /contracts/attention`): qué contrato pide acción y por qué.

Reglas puras de `rules.attention_for` y `rules.attention_sort_key`. Los montos
salen de `quote_payment_options`, así que estos tests además fijan que la
tarjeta y el botón de cobro del contrato digan el mismo número.
"""

from datetime import date
from decimal import Decimal

from app.modules.contracts import rules
from app.modules.contracts.rules import add_months, attention_for, attention_sort_key

HOY = date(2026, 9, 30)


def _att(
    *,
    ipu: date,
    status: str = "active",
    window: int = 4,
    extension_months: int = 1,
    extension_ends_at: date | None = None,
    capital: str = "1000000.00",
    rate: str = "5",
    start: date | None = None,
    today: date = HOY,
) -> rules.Attention | None:
    return attention_for(
        current_status=status,
        interest_paid_until=ipu,
        arrears_window_months=window,
        extension_months=extension_months,
        extension_ends_at=extension_ends_at,
        capital_balance=Decimal(capital),
        interest_rate_pct=Decimal(rate),
        start_date=start if start is not None else add_months(ipu, -6),
        today=today,
    )


def _a(**kw: object) -> rules.Attention:
    a = _att(**kw)  # type: ignore[arg-type]
    assert a is not None
    return a


class TestQuienNoPideAccion:
    def test_un_contrato_al_dia_no_aparece(self) -> None:
        assert _att(ipu=date(2026, 9, 15)) is None

    def test_la_vispera_del_vencimiento_todavia_no_aparece(self) -> None:
        assert _att(ipu=date(2026, 9, 1)) is None
        assert _att(ipu=date(2026, 8, 31), today=date(2026, 9, 29)) is None

    def test_los_terminales_nunca_aparecen(self) -> None:
        for status in rules.TERMINAL_STATUSES:
            assert _att(ipu=date(2026, 1, 1), status=status) is None


class TestVenceHoy:
    def test_el_mes_que_se_cumple_hoy_es_vence_hoy_con_un_mes(self) -> None:
        a = _att(ipu=date(2026, 8, 30))
        assert a is not None
        assert a.reason == "due_today"
        assert a.days_overdue == 0
        assert a.reference_date == HOY
        assert a.amount_due_today == Decimal("50000.00")

    def test_ese_dia_el_estado_efectivo_ya_es_mora(self) -> None:
        """`months_owed` pasa de 0 a 1 el día del vencimiento: el estado es
        `in_arrears` aunque el motivo sea «vence hoy»."""
        a = _att(ipu=date(2026, 8, 30))
        assert a is not None and a.status == "in_arrears"

    def test_con_ventana_de_un_mes_entra_en_prorroga_y_sigue_siendo_vence_hoy(self) -> None:
        a = _att(ipu=date(2026, 8, 30), window=1)
        assert a is not None
        assert a.status == "in_extension"
        assert a.reason == "due_today"

    def test_el_estado_persistido_viejo_no_importa(self) -> None:
        a = _att(ipu=date(2026, 8, 30), status="active")
        assert a is not None and a.reason == "due_today"


class TestMora:
    def test_mora_cobra_ponerse_al_dia(self) -> None:
        a = _att(ipu=date(2026, 7, 30))  # 2 meses adeudados
        assert a is not None
        assert a.reason == "in_arrears"
        assert a.months_owed == 2
        assert a.amount_due_today == Decimal("100000.00")
        assert a.overdue_interest == Decimal("100000.00")

    def test_dias_de_atraso_se_cuentan_desde_la_primera_cuota_sin_pagar(self) -> None:
        a = _att(ipu=date(2026, 7, 28))  # venció el 28/08
        assert a is not None
        assert a.reference_date == date(2026, 8, 28)
        assert a.days_overdue == 33

    def test_el_monto_es_el_mismo_que_payment_options(self) -> None:
        ipu = date(2026, 6, 10)
        a = _att(ipu=ipu, capital="733333.00", rate="4.5")
        q = rules.quote_payment_options(
            capital_balance=Decimal("733333.00"),
            interest_rate_pct=Decimal("4.5"),
            interest_paid_until=ipu,
            today=HOY,
            start_date=add_months(ipu, -6),
        )
        assert a is not None
        assert a.amount_due_today == q.options[-1].total


class TestProrroga:
    def test_prorroga_vigente_cobra_ponerse_al_dia_y_refiere_al_fin(self) -> None:
        ipu = date(2026, 5, 15)  # 4 meses → prórroga; fin = ipu + 4 + 1 = 15/10
        a = _att(ipu=ipu)
        assert a is not None
        assert a.reason == "in_extension"
        assert a.status == "in_extension"
        assert a.reference_date == date(2026, 10, 15)
        assert a.amount_due_today == Decimal("200000.00")

    def test_conserva_la_fecha_de_fin_ya_fijada(self) -> None:
        a = _att(ipu=date(2026, 5, 15), status="in_extension", extension_ends_at=date(2026, 10, 3))
        assert a is not None and a.reference_date == date(2026, 10, 3)


class TestListoParaRemate:
    def test_prorroga_vencida_es_listo_para_remate_y_cobra_saldar(self) -> None:
        a = _att(ipu=date(2026, 3, 1), status="in_extension", extension_ends_at=date(2026, 9, 27))
        assert a is not None
        assert a.reason == "ready_for_auction"
        assert a.reference_date == date(2026, 9, 27)
        # 6 meses adeudados (01/03 → 01/09) + capital.
        assert a.amount_due_today == Decimal("1300000.00")

    def test_el_dia_del_fin_todavia_no_esta_listo(self) -> None:
        """Mismo criterio que `/ready-for-auction`: vencida es `fin < hoy`."""
        a = _att(ipu=date(2026, 5, 1), status="in_extension", extension_ends_at=HOY)
        assert a is not None and a.reason == "in_extension"

    def test_sin_fecha_persistida_se_deriva_del_ancla(self) -> None:
        a = _att(ipu=date(2026, 3, 1), status="in_arrears")  # fin = 01/03+4+1 = 01/08
        assert a is not None
        assert a.reason == "ready_for_auction"
        assert a.reference_date == date(2026, 8, 1)


class TestOrden:
    def test_remate_luego_mora_por_atraso_luego_prorroga_luego_vence_hoy(self) -> None:
        hoy_vence = _a(ipu=date(2026, 8, 30))
        mora_corta = _a(ipu=date(2026, 8, 20))
        mora_larga = _a(ipu=date(2026, 6, 20))
        prorroga = _a(ipu=date(2026, 5, 15))
        remate = _a(ipu=date(2026, 3, 1), status="in_extension", extension_ends_at=date(2026, 9, 1))
        entradas = [(hoy_vence, 1), (prorroga, 2), (mora_corta, 3), (remate, 4), (mora_larga, 5)]
        ordenadas = sorted(entradas, key=lambda e: attention_sort_key(e[0], number=e[1]))
        assert [n for _, n in ordenadas] == [4, 5, 3, 2, 1]

    def test_remates_por_fecha_de_vencimiento_mas_vieja_primero(self) -> None:
        viejo = _a(ipu=date(2026, 2, 1), status="in_extension", extension_ends_at=date(2026, 8, 1))
        nuevo = _a(ipu=date(2026, 3, 1), status="in_extension", extension_ends_at=date(2026, 9, 1))
        assert attention_sort_key(viejo, number=9) < attention_sort_key(nuevo, number=1)

    def test_prorrogas_la_que_vence_antes_primero(self) -> None:
        pronto = _a(
            ipu=date(2026, 5, 15), status="in_extension", extension_ends_at=date(2026, 10, 2)
        )
        tarde = _a(
            ipu=date(2026, 5, 15), status="in_extension", extension_ends_at=date(2026, 10, 20)
        )
        assert attention_sort_key(pronto, number=9) < attention_sort_key(tarde, number=1)
