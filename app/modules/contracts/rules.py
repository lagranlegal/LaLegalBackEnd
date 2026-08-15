"""Reglas de negocio de contratos — puro, sin BD (CLAUDE.md: "servicio, puro
y testeable"). Todo lo que decide plata/estados de un contrato vive acá; el
resto del módulo solo persiste lo que esta capa calcula.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.common.money import quantize

_TERMINAL_STATUSES = {"paid", "auctioned"}


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
    `paid`/`auctioned` son terminales — nunca se recalculan (paid lo cierra
    el servicio de abonos; auctioned SOLO la acción manual Rematar).
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
