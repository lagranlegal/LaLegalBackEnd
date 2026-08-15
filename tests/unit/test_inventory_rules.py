from decimal import Decimal

from app.modules.inventory.rules import build_code, split_cost_by_appraisal


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
