from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import AfterValidator, Field

Money = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=0)]

#: Un monto que TIENE que mover plata: gasto, traslado, liquidación, aporte,
#: retiro, capital de un contrato. `Money` admite 0 porque también tipa
#: descuentos y conteos opcionales; acá 0 no significa nada y la base lo
#: rechaza con un CHECK (F5-04, F4-12). `decimal_places=2`: 0,001 o 10,555
#: son 422, no un redondeo callado a 0,00 o a 10,56.
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]

#: Cantidad de inventario: unidades, gramos, metros. Hasta TRES decimales,
#: los de `numeric(14,3)` en la base; con más, 422 y no un redondeo callado.
Quantity = Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=3)]

_CENTS = Decimal("0.01")


def quantize(value: Decimal) -> Decimal:
    """Redondea a centavos (ROUND_HALF_UP) — para resultados de cálculos
    (tasa % × saldo) que puedan salir con más de 2 decimales. Nunca usar
    float en dinero (CLAUDE.md regla 4)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


#: Un monto de SALIDA: siempre con dos decimales (F7-09 / F7-15, auditoría
#: fase 7). Una suma vacía de Postgres (`coalesce(sum(...), 0)`) llega como
#: `Decimal("0")` y se serializaba "0"; una suma de `costo × cantidad` con
#: gramos llegaba con cinco decimales ("2317208.20100"). El front formatea
#: lo que recibe, así que el mismo concepto se veía distinto según la
#: pantalla. Redondear acá es la ÚLTIMA línea: las consultas ya redondean por
#: lote, y esto garantiza la escala aunque una consulta nueva lo olvide.
MoneyOut = Annotated[Decimal, AfterValidator(quantize)]
