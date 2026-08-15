"""Reglas puras de inventario — sin BD (mismo espíritu que
`app.modules.contracts.rules`): quien llama resuelve los datos de la BD, acá
solo vive el cálculo.
"""

from decimal import Decimal

from app.common.money import quantize


def build_code(
    *, cat1_letter: str, cat2_letter: str, cat3_letter: str, consecutive: int, suffix_letter: str
) -> str:
    """CLAUDE.md: `[letra cat1][cat2][cat3][consecutivo 4 dígitos][letra
    proveedor | 'R' si remate]` → `JOC0001I` / `JOC0001R`."""
    return f"{cat1_letter}{cat2_letter}{cat3_letter}{consecutive:04d}{suffix_letter}"


def split_cost_by_appraisal(total: Decimal, appraisals: list[Decimal | None]) -> list[Decimal]:
    """Reparte `total` (saldo capital + intereses pendientes de un remate)
    entre N artículos. Proporcional a `item_appraisal` si TODOS los
    artículos la tienen (>0); si a alguno le falta, partes iguales para
    todos (decisión: mezclar tasado/no-tasado no tiene una regla de negocio
    definida, así que se prefiere el reparto simple y predecible).

    El último elemento absorbe el residuo de redondeo para que la suma
    cuadre exacto con `total` al centavo (nunca se "pierde" ni se "regala"
    un centavo por redondeo acumulado).
    """
    n = len(appraisals)
    if n == 0:
        return []

    known_appraisals = [a for a in appraisals if a is not None and a > 0]
    if len(known_appraisals) == n:
        total_appraisal = sum(known_appraisals, Decimal("0"))
        shares = [quantize(total * a / total_appraisal) for a in known_appraisals[:-1]]
    else:
        equal_share = quantize(total / n)
        shares = [equal_share for _ in range(n - 1)]

    shares.append(total - sum(shares, Decimal("0")))
    return shares
