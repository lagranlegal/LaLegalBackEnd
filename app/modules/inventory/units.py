"""Unidades de medida de un producto (00036).

Vive aparte del resto del módulo porque lo consumen `inventory` y `sales`, y
porque la regla que expone —qué unidades admiten fracciones— es de negocio,
no de presentación.
"""

from decimal import Decimal
from typing import Literal

ProductUnit = Literal["unit", "gram", "kilogram", "meter", "liter"]

#: Abreviatura para mostrar junto a la cantidad. El backend la expone para que
#: front, comprobantes y reportes digan todos lo mismo — si cada uno tradujera
#: por su cuenta, "12,5 g" y "12,5 gr" acabarían conviviendo en la misma venta.
UNIT_ABBREVIATIONS: dict[str, str] = {
    "unit": "u",
    "gram": "g",
    "kilogram": "kg",
    "meter": "m",
    "liter": "L",
}

#: Unidades que NO admiten fracciones. Media cadena no existe: si alguien
#: escribe 1,5 en un producto contable, es un error de digitación y vale más
#: rechazarlo que registrar stock imposible.
#:
#: Es la única razón por la que la unidad importa en el backend y no solo al
#: mostrar. Todo lo demás —el símbolo, cómo se lee— es presentación.
DISCRETE_UNITS: frozenset[str] = frozenset({"unit"})


def allows_fractions(unit: str) -> bool:
    return unit not in DISCRETE_UNITS


def is_valid_quantity(unit: str, quantity: Decimal) -> bool:
    """Una cantidad válida para esta unidad.

    Positiva siempre; entera además si la unidad es discreta.
    """
    if quantity <= 0:
        return False
    return allows_fractions(unit) or quantity == quantity.to_integral_value()
