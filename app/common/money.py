from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import Field

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=0)]

_CENTS = Decimal("0.01")


def quantize(value: Decimal) -> Decimal:
    """Redondea a centavos (ROUND_HALF_UP) — para resultados de cálculos
    (tasa % × saldo) que puedan salir con más de 2 decimales. Nunca usar
    float en dinero (CLAUDE.md regla 4)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)
