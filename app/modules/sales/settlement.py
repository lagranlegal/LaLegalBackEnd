"""Cómo se parte la liquidación de una devolución (F21-37).

Una venta puede cobrarse en dos cosas distintas: **nota crédito** (00043,
`credit_note_redemption`) y **plata** (el `cash_movement` de la venta, por su
`payment_method`). Una nota no es plata: nunca entró al cajón. Por eso, al
devolver, cada parte vuelve por su lado (decisión de Mateo, opción A):

- lo pagado con nota vuelve como **nota crédito nueva** ligada a la
  devolución;
- lo pagado en plata vuelve **por el medio elegido** (`settlement_method`).

Hasta F21-37 la devolución liquidaba el total por el medio elegido: una venta
de 800.000 = 500.000 de nota + 300.000 en efectivo, devuelta en efectivo,
sacaba 800.000 del cajón con 300.000 entrados.

REPARTO DE UNA DEVOLUCIÓN PARCIAL — proporcional, no «primero la nota».
Cada peso de la venta se pagó en la misma mezcla que la venta entera: nadie
sabe si la cadena se pagó con la nota y el anillo con efectivo, y el sistema
no debería inventarlo. Es el mismo criterio que ya reparte el descuento de la
cabecera entre las líneas (F21-33): la mercancía que el cliente conserva y la
que devuelve cargan la misma proporción de nota y de plata, y el resultado no
depende del orden en que devuelva las piezas.

Las alternativas, y a quién perjudican:

- **Primero la nota** deja al cliente PEOR en toda devolución parcial que no
  agota la venta: recibe nota (que solo sirve en esta tienda) donde la
  proporcional le daría plata. Con la venta de arriba, devolver 300.000
  daría 300.000 en nota y 0 en efectivo; la proporcional da 187.500 en nota y
  112.500 en efectivo. (Nunca al revés: la plata acumulada proporcional,
  `plata × x / total`, es siempre ≥ `x − nota`, lo que daría «primero la
  nota», porque `x ≤ total`.)
- **Primero la plata** deja peor al NEGOCIO: devuelve efectivo antes que nota
  y convierte, en la práctica, la nota en la forma de pago de lo que el
  cliente se queda.

Las tres coinciden al agotar la venta; solo difieren en el camino.

REDONDEO — sobre el ACUMULADO, como `return_line_amounts_sql`. La parte en
nota de una devolución es la diferencia entre la parte en nota del acumulado
devuelto DESPUÉS de ella y ANTES de ella, redondeando el acumulado una sola
vez. La suma telescopa: lo devuelto en nota hasta cualquier punto es
`round(nota × devuelto / total)`, que nunca pasa de `nota` porque lo devuelto
nunca pasa de `total`; y la devolución que agota la venta (acumulado =
`total`, que F21-33 garantiza exacto) cierra en `nota` y en `total − nota`
al centavo. La parte en plata es el resto de la devolución, así que nunca hay
un centavo de más ni de menos entre las dos.
"""

from decimal import Decimal

from app.common.money import quantize

_ZERO = Decimal("0.00")


def split_return_settlement(
    *,
    sale_total: Decimal,
    redeemed: Decimal,
    returned_before: Decimal,
    amount: Decimal,
) -> tuple[Decimal, Decimal]:
    """(parte que vuelve en nota, parte que vuelve en plata) de UNA devolución.

    - `sale_total`: el `total` de la venta (neto del descuento).
    - `redeemed`: lo que la venta pagó con notas crédito — TODAS las que
      redimió, sumadas; la redención no distingue de qué nota vino cada peso.
    - `returned_before`: lo devuelto por las devoluciones ANTERIORES de la
      venta (`return_line_amounts_sql`).
    - `amount`: lo que vale ESTA devolución (`sum_sale_return_amount`).

    Sin nota (el caso de siempre) todo vuelve por el medio elegido.
    """
    if redeemed <= 0 or sale_total <= 0:
        return _ZERO, quantize(amount)
    redeemed = min(redeemed, sale_total)

    def note_share(returned: Decimal) -> Decimal:
        return quantize(redeemed * min(returned, sale_total) / sale_total)

    note = note_share(returned_before + amount) - note_share(returned_before)
    # Defensivo: por construcción ya está en [0, amount] (el acumulado es
    # monótono y cada devolución vale al menos el centavo que puede moverse).
    note = min(max(note, _ZERO), amount)
    return quantize(note), quantize(amount - note)
