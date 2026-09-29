"""El estado de resultados se puede rehacer sumando sus renglones a mano.

Verificación de la tanda F/G: los subtotales se calculaban con los valores
crudos —el costo de ventas sale de `costo × cantidad` con cantidades de 3
decimales— y `MoneyOut` redondeaba cada campo al serializar, así que un
subtotal podía no ser la resta de los renglones que se ven encima. Puro: los
repositorios se reemplazan por filas con sub-centavos.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from app.modules.reports import service


def _row(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(_mapping=values)


async def test_subtotals_are_derived_from_the_rounded_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def tz(*_: Any, **__: Any) -> str:
        return "America/Bogota"

    def returns(value: Any) -> Any:
        async def fake(*_: Any, **__: Any) -> Any:
            return value

        return fake

    monkeypatch.setattr(service.platform_integration, "get_company_timezone", tz)
    monkeypatch.setattr(
        service.repository,
        "profit_summary",
        returns(
            _row(
                gross_revenue="3976916.674",
                discounts="0",
                returns_gross="0",
                returns_discounts="0",
                cost_of_goods_sold="3288458.455",
                returns_cost="0",
                price_discounts="0",
                auction_interest="0",
            )
        ),
    )
    monkeypatch.setattr(
        service.repository,
        "pawn_performance",
        returns(
            _row(
                interest_collected="0",
                interest_discounts="0",
                capital_disbursed="0",
                capital_recovered="0",
            )
        ),
    )
    monkeypatch.setattr(
        service.repository,
        "operating_expenses",
        returns(_row(total="100.005", expense_count=1)),
    )
    monkeypatch.setattr(service.repository, "inventory_purchased", returns(Decimal("0")))
    monkeypatch.setattr(
        service.repository,
        "inventory_shrinkage",
        returns(_row(total="0.004", exit_count=1)),
    )
    monkeypatch.setattr(service.repository, "settlement_commissions", returns(Decimal("0")))
    monkeypatch.setattr(
        service.repository,
        "inventory_purchase_payments",
        returns(_row(purchases_paid="0", transformation_paid="0")),
    )
    monkeypatch.setattr(service.repository, "cash_differences", returns(Decimal("0")))

    result = await service.get_income_statement(
        None,  # type: ignore[arg-type]
        company_id=uuid4(),
        from_date=date(2030, 9, 1),
        to_date=date(2030, 9, 30),
    )
    dumped = {
        k: Decimal(str(v))
        for k, v in result.model_dump(mode="json").items()
        if k
        in {
            "sales_revenue",
            "sales_returns",
            "interest_revenue",
            "total_revenue",
            "cost_of_goods_sold",
            "gross_profit",
            "operating_expenses",
            "inventory_shrinkage",
            "settlement_commissions",
            "cash_differences",
            "operating_profit",
        }
    }
    assert dumped["total_revenue"] == (
        dumped["sales_revenue"] - dumped["sales_returns"] + dumped["interest_revenue"]
    )
    assert dumped["gross_profit"] == dumped["total_revenue"] - dumped["cost_of_goods_sold"]
    assert dumped["operating_profit"] == (
        dumped["gross_profit"]
        - dumped["operating_expenses"]
        - dumped["inventory_shrinkage"]
        - dumped["settlement_commissions"]
        + dumped["cash_differences"]
    )
    # 3.976.916,67 − 3.288.458,46 = 688.458,21 (con los crudos: 688.458,219 → ,22).
    assert dumped["gross_profit"] == Decimal("688458.21")
