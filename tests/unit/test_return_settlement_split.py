"""F21-37: cómo se parte la liquidación de una devolución sobre una venta que
se pagó (toda o en parte) con nota crédito. La regla —proporcional a cómo se
pagó la venta, sobre el ACUMULADO devuelto— y su porqué viven en
`app/modules/sales/settlement.py`."""

from decimal import Decimal

import pytest

from app.modules.sales.settlement import split_return_settlement

D = Decimal


def _split(total: str, redeemed: str, before: str, amount: str) -> tuple[str, str]:
    note, money = split_return_settlement(
        sale_total=D(total), redeemed=D(redeemed), returned_before=D(before), amount=D(amount)
    )
    return str(note), str(money)


def test_sin_nota_todo_vuelve_por_el_medio_elegido() -> None:
    """Regresión: una venta sin nota se liquida exactamente como antes."""
    assert _split("800000.00", "0", "0", "800000.00") == ("0.00", "800000.00")
    assert _split("800000.00", "0", "300000.00", "500000.00") == ("0.00", "500000.00")


def test_el_caso_del_hallazgo_devuelta_completa() -> None:
    """800.000 = 500.000 de nota + 300.000 en efectivo, devuelta de una vez."""
    assert _split("800000.00", "500000.00", "0", "800000.00") == ("500000.00", "300000.00")


def test_la_nota_cubrio_toda_la_venta() -> None:
    assert _split("400000.00", "400000.00", "0", "150000.00") == ("150000.00", "0.00")
    assert _split("400000.00", "400000.00", "150000.00", "250000.00") == ("250000.00", "0.00")


def test_parciales_con_residuo_cierran_exacto_por_medio() -> None:
    """3 × 333.333,33 con 100.000 de descuento (total 899.999,99, las
    devoluciones valen 300.000,00 + 299.999,99 + 300.000,00 por F21-33),
    pagada con 500.000 de nota + 399.999,99 en efectivo. Cada medio se
    reparte sobre el acumulado y la última se lleva el residuo."""
    total, redeemed = D("899999.99"), D("500000.00")
    before = D("0")
    notes: list[Decimal] = []
    moneys: list[Decimal] = []
    for amount in (D("300000.00"), D("299999.99"), D("300000.00")):
        note, money = split_return_settlement(
            sale_total=total, redeemed=redeemed, returned_before=before, amount=amount
        )
        assert note + money == amount
        notes.append(note)
        moneys.append(money)
        before += amount
        # En NINGÚN punto un medio devuelve más de lo que se pagó con él.
        assert sum(notes) <= redeemed
        assert sum(moneys) <= total - redeemed
    assert notes == [D("166666.67"), D("166666.66"), D("166666.67")]
    assert moneys == [D("133333.33"), D("133333.33"), D("133333.33")]
    assert sum(notes) == redeemed
    assert sum(moneys) == total - redeemed


@pytest.mark.parametrize("pieces", [1, 2, 3, 7, 13, 101])
def test_cualquier_particion_cierra_al_centavo(pieces: int) -> None:
    """Partir la misma venta en N devoluciones —con montos que no dividen
    exacto— siempre termina en la nota y el efectivo que se cobraron."""
    total, redeemed = D("1000000.01"), D("333333.33")
    step = (total / pieces).quantize(D("0.01"))
    amounts = [step] * (pieces - 1) + [total - step * (pieces - 1)]
    before = D("0")
    note_sum = money_sum = D("0")
    for amount in amounts:
        note, money = split_return_settlement(
            sale_total=total, redeemed=redeemed, returned_before=before, amount=amount
        )
        assert note >= 0 and money >= 0
        note_sum += note
        money_sum += money
        before += amount
    assert note_sum == redeemed
    assert money_sum == total - redeemed


def test_un_centavo_nunca_da_una_parte_negativa() -> None:
    """Devoluciones de un centavo: el redondeo del acumulado puede mandar el
    centavo a la nota o a la plata, pero nunca deja una parte negativa."""
    total, redeemed = D("0.03"), D("0.02")
    before = D("0")
    parts = []
    for _ in range(3):
        note, money = split_return_settlement(
            sale_total=total, redeemed=redeemed, returned_before=before, amount=D("0.01")
        )
        assert note >= 0 and money >= 0 and note + money == D("0.01")
        parts.append((note, money))
        before += D("0.01")
    assert sum(n for n, _ in parts) == redeemed


def test_venta_en_cero_no_divide_por_cero() -> None:
    """Una venta 100% descontada vale 0: no hay nada que partir."""
    assert _split("0.00", "0", "0", "0.00") == ("0.00", "0.00")
