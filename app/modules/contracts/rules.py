"""Reglas de negocio de contratos — puro, sin BD (CLAUDE.md: "servicio, puro
y testeable"). Todo lo que decide plata/estados de un contrato vive acá; el
resto del módulo solo persiste lo que esta capa calcula.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.common.money import quantize

#: `superseded` (00051) entra acá por la misma razón que los otros dos: un
#: contrato que ya fue ampliado no vuelve a moverse. Sin esto, el recálculo
#: en lectura y el job nocturno lo devolverían a `in_arrears` en cuanto
#: pasara un mes, y aparecería en la cola de cobro un documento que ya no
#: existe como obligación.
_TERMINAL_STATUSES = {"paid", "auctioned", "superseded"}


def add_months(d: date, n: int) -> date:
    """Suma `n` meses calendario, recortando el día al último día del mes
    destino si no existe (31 ene + 1 mes = 28/29 feb, no un error)."""
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def months_between(start: date, end: date) -> int:
    """Meses COMPLETOS entre `start` y `end`. Usa `add_months` para el ajuste
    (no comparación cruda de `.day`) para que sea consistente en meses con
    distinto número de días — ver tests para el caso 31-ene → 28-feb.
    """
    if end <= start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, months) > end:
        months -= 1
    while add_months(start, months + 1) <= end:
        months += 1
    return max(months, 0)


def months_since_start_exact(start: date, end: date) -> int | None:
    """N tal que `add_months(start, N) == end`, o `None` si `end` no cae
    exactamente en un múltiplo entero de meses desde `start` (import de
    contratos: valida `interest_paid_until` contra `start_date` reusando la
    misma convención de fin de mes que `due_date`/`months_owed`, en vez de
    inventar otra — ver docs/MIGRACION_CONTRATOS.md §3)."""
    n = (end.year - start.year) * 12 + (end.month - start.month)
    if n < 0:
        return None
    return n if add_months(start, n) == end else None


def monthly_interest(interest_rate_pct: Decimal, capital_balance: Decimal) -> Decimal:
    """CLAUDE.md: interés mensual = tasa_contrato × saldo_capital_actual."""
    return quantize(interest_rate_pct / Decimal(100) * capital_balance)


@dataclass(frozen=True)
class PaymentOption:
    months: int
    interest_amount: Decimal
    total: Decimal
    allows_capital: bool  # solo True cuando months == months_owed (intereses al día)


@dataclass(frozen=True)
class PaymentQuote:
    months_owed: int
    monthly_interest: Decimal
    options: list[PaymentOption]


def quote_payment_options(
    *, capital_balance: Decimal, interest_rate_pct: Decimal, interest_paid_until: date, today: date
) -> PaymentQuote:
    """CLAUDE.md: "el endpoint debe devolver los montos exactos aceptables
    para que la UI los muestre (1 mes, 2 meses, ..., todo + capital libre)".
    Cada opción es un múltiplo exacto de `monthly_interest` — un pago parcial
    de un mes nunca es una opción válida, por construcción.
    """
    owed = months_between(interest_paid_until, today)
    monthly = monthly_interest(interest_rate_pct, capital_balance)
    options = [
        PaymentOption(
            months=n,
            interest_amount=quantize(monthly * n),
            total=quantize(monthly * n),
            allows_capital=(n == owed),
        )
        for n in range(1, owed + 1)
    ]
    return PaymentQuote(months_owed=owed, monthly_interest=monthly, options=options)


def compute_status(
    *,
    current_status: str,
    interest_paid_until: date,
    arrears_window_months: int,
    extension_months: int,
    extension_ends_at: date | None,
    today: date,
) -> tuple[str, date | None]:
    """Máquina de estados (CLAUDE.md): active → in_arrears → in_extension.

    Los TERMINALES nunca se recalculan, cada uno lo fija quien corresponde:
    `paid` el servicio de abonos, `auctioned` SOLO la acción manual Rematar,
    y `superseded` la ampliación de préstamo (00051).
    `in_extension` se dispara UNA vez; no se vuelve a calcular `extension_ends_at`
    mientras siga en ese estado (aunque sigan pasando meses sin pagar).
    """
    if current_status in _TERMINAL_STATUSES:
        return current_status, extension_ends_at

    owed = months_between(interest_paid_until, today)
    if owed == 0:
        return "active", None
    if owed < arrears_window_months:
        return "in_arrears", None

    if current_status == "in_extension":
        return "in_extension", extension_ends_at

    trigger_date = add_months(interest_paid_until, arrears_window_months)
    new_extension_ends_at = add_months(trigger_date, extension_months)
    return "in_extension", new_extension_ends_at


# ------------------------------------------------------ ampliar préstamo ----
@dataclass(frozen=True)
class ExtensionQuote:
    """Cuánto puede retirar el cliente sobre la garantía que ya dejó."""

    #: Techo que impone la tasación: `avalúo × LTV`. `None` si no hay
    #: tasación o la categoría no define LTV — sin techo no hay cupo que
    #: calcular, y prestar sin techo es prestar a ciegas.
    ceiling: Decimal | None
    #: Lo que queda libre bajo ese techo. Nunca negativo hacia afuera: si el
    #: contrato ya está por encima (pasa cuando el LTV se corrige a la baja
    #: después de firmar), el cupo es cero, no una deuda.
    available: Decimal
    #: Último día en que se admite un recargo, medido desde la RAÍZ de la
    #: cadena. `None` si la ventana es 0 (recargos apagados).
    window_ends_on: date | None


def quote_extension(
    *,
    capital_balance: Decimal,
    appraisal_value: Decimal | None,
    max_ltv_pct: Decimal | None,
    root_start_date: date,
    extension_window_days: int,
) -> ExtensionQuote:
    """El cupo y la ventana de un recargo (docs/RECARGOS.md §3 y §4).

    **La ventana se mide desde `root_start_date`**, la fecha del PRIMER
    contrato de la cadena, nunca desde el actual. Sin eso, un recargo de $1
    el día 27 reinicia el reloj y el cliente encadena recargos para siempre;
    con el ancla en la raíz, 28 días son 28 días haya habido uno o cinco.
    """
    if appraisal_value is None or appraisal_value <= 0 or max_ltv_pct is None:
        ceiling: Decimal | None = None
        available = Decimal("0.00")
    else:
        ceiling = quantize(appraisal_value * max_ltv_pct / Decimal(100))
        available = max(quantize(ceiling - capital_balance), Decimal("0.00"))

    window_ends_on = (
        root_start_date + timedelta(days=extension_window_days)
        if extension_window_days > 0
        else None
    )
    return ExtensionQuote(ceiling=ceiling, available=available, window_ends_on=window_ends_on)


def extension_window_is_open(*, window_ends_on: date | None, today: date) -> bool:
    """Con la ventana en 0 (`window_ends_on is None`) no hay recargos: es
    cómo una empresa —o un contrato puntual— apaga la función."""
    return window_ends_on is not None and today <= window_ends_on
