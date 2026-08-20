from decimal import Decimal

from app.modules.inventory.rules import (
    build_code,
    build_lot_code,
    build_product_code,
    split_cost_by_appraisal,
)


class TestBuildCode:
    def test_matches_claude_md_example(self) -> None:
        assert (
            build_code(
                cat1_letter="J", cat2_letter="O", cat3_letter="C", consecutive=1, suffix_letter="I"
            )
            == "JOC0001I"
        )

    def test_auction_suffix_is_r(self) -> None:
        code = build_code(
            cat1_letter="J", cat2_letter="O", cat3_letter="C", consecutive=1, suffix_letter="R"
        )
        assert code == "JOC0001R"

    def test_pads_consecutive_to_four_digits(self) -> None:
        code = build_code(
            cat1_letter="T", cat2_letter="E", cat3_letter="S", consecutive=42, suffix_letter="A"
        )
        assert code == "TES0042A"

    def test_multichar_category_letters(self) -> None:
        code = build_code(
            cat1_letter="JOY", cat2_letter="O", cat3_letter="CAD", consecutive=7, suffix_letter="X"
        )
        assert code == "JOYOCAD0007X"


class TestSplitCostByAppraisal:
    def test_proportional_when_all_appraised(self) -> None:
        shares = split_cost_by_appraisal(
            Decimal("900000"), [Decimal("500000"), Decimal("300000"), Decimal("200000")]
        )
        assert shares == [Decimal("450000.00"), Decimal("270000.00"), Decimal("180000.00")]
        assert sum(shares) == Decimal("900000")

    def test_equal_split_when_none_appraised(self) -> None:
        shares = split_cost_by_appraisal(Decimal("900000"), [None, None, None])
        assert shares == [Decimal("300000.00"), Decimal("300000.00"), Decimal("300000.00")]
        assert sum(shares) == Decimal("900000")

    def test_equal_split_when_partially_appraised(self) -> None:
        # Sin regla definida para mezclar tasado/no-tasado -> reparto simple
        shares = split_cost_by_appraisal(Decimal("900000"), [Decimal("500000"), None])
        assert shares == [Decimal("450000.00"), Decimal("450000.00")]
        assert sum(shares) == Decimal("900000")

    def test_single_item_gets_full_total(self) -> None:
        assert split_cost_by_appraisal(Decimal("123456.78"), [Decimal("1")]) == [
            Decimal("123456.78")
        ]

    def test_rounding_residue_goes_to_last_item(self) -> None:
        # 100 / 3 no cuadra exacto en centavos -> el último absorbe el residuo
        shares = split_cost_by_appraisal(Decimal("100"), [None, None, None])
        assert sum(shares) == Decimal("100")
        assert shares[0] == Decimal("33.33")
        assert shares[1] == Decimal("33.33")
        assert shares[2] == Decimal("33.34")

    def test_empty_list_returns_empty(self) -> None:
        assert split_cost_by_appraisal(Decimal("100"), []) == []


def test_build_product_code_omits_supplier_letter() -> None:
    """El SKU identifica QUÉ es, no a quién se le compró: el proveedor
    pertenece al lote. Si el SKU lo llevara, el mismo producto comprado a dos
    proveedores tendría dos SKU — que es el problema que 00021 corrige."""
    assert (
        build_product_code(cat1_letter="J", cat2_letter="A", cat3_letter="O", consecutive=7)
        == "JAO0007"
    )


def test_build_lot_code_keeps_supplier_traceability() -> None:
    """El lote conserva la letra del proveedor, así que no se pierde nada de
    lo que el esquema anterior identificaba — se le suma el producto."""

    def lot(n: int, letter: str) -> str:
        return build_lot_code(product_code="JAO0007", lot_number=n, suffix_letter=letter)

    assert lot(1, "I") == "JAO0007-01I"
    assert lot(3, "M") == "JAO0007-03M"
    # Remate: mismo formato, sufijo R.
    assert lot(1, "R") == "JAO0007-01R"


def test_two_lots_of_the_same_product_share_the_sku() -> None:
    """La propiedad que hace posible agrupar: el prefijo antes del guion es
    idéntico aunque cambien proveedor y número de lote."""
    a = build_lot_code(product_code="JAO0007", lot_number=1, suffix_letter="I")
    b = build_lot_code(product_code="JAO0007", lot_number=2, suffix_letter="M")
    assert a.split("-")[0] == b.split("-")[0] == "JAO0007"
