"""Reglas de negocio de contratos — puro, sin BD (CLAUDE.md: "servicio, puro
y testeable"). Todo lo que decide plata/estados de un contrato vive acá; el
resto del módulo solo persiste lo que esta capa calcula.
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.common.money import quantize

#: Estados de los que un contrato NO vuelve a salir. Es PÚBLICA a propósito:
#: `repository.list_active_contracts_for_recompute` la usa como filtro de la
#: consulta que alimenta el job nocturno, en vez de repetir la lista escrita a
#: mano (F21-10 — la lista quedó desincronizada once días y el job recalculó
#: contratos ya reemplazados). Agregar un estado terminal nuevo ACÁ alcanza:
#: la guarda de `compute_status` y el filtro de la consulta salen de esta
#: misma constante, no hay un segundo lugar que tocar.
#:
#: `superseded` (00051) entra acá por la misma razón que los otros dos: un
#: contrato que ya fue ampliado no vuelve a moverse. Sin esto, el recálculo
#: en lectura y el job nocturno lo devolverían a `in_arrears` en cuanto
#: pasara un mes, y aparecería en la cola de cobro un documento que ya no
#: existe como obligación.
#: Tres consumidores más, agregados el 21/09/2026 al cerrar el hallazgo
#: F21-11 (ver docs/QA_AUDITORIA.md): la puerta de los abonos
#: (`service.create_payment`) y el cupo de ampliación (`service.quote_extension`)
#: repetían estos estados a mano. La de abonos le faltaba `superseded`, así que
#: un contrato ya reemplazado admitía un abono.
#:
#: **Se decidió NO abrir una constante aparte** ("cerrado para abonos") aunque
#: el concepto no sea idéntico a "de acá no se sale". Con dos constantes de
#: valor idéntico, un estado terminal nuevo nace ABIERTO para abonos —
#: aceptar plata contra un documento que no debe moverse, que es exactamente
#: el defecto que se está arreglando, y falla en silencio. Derivándola de acá,
#: un estado terminal nuevo nace CERRADO: si algún día aparece uno que sí
#: deba admitir abonos (una cartera castigada que todavía recibe
#: recuperaciones sería el candidato), el rechazo se ve el primer día, lo
#: reporta quien atiende y ahí se parte la constante con el caso real en la
#: mano. Cerrado de más se nota; abierto de más no.
TERMINAL_STATUSES = frozenset({"paid", "auctioned", "superseded"})


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
    #: Meses de interés que exige SALDAR hoy: los adeudados, y como mínimo
    #: uno si el contrato todavía no causó ninguno (F4-11).
    payoff_months: int
    payoff_interest: Decimal
    #: `payoff_interest + capital_balance`: lo que cuesta recoger la prenda hoy.
    payoff_total: Decimal


def minimum_payoff_months(*, start_date: date, interest_paid_until: date) -> int:
    """Saldar un contrato causa como mínimo UN mes de interés (decisión del
    dueño, auditoría 27/09/2026, F4-11). La regla de meses completos, sola,
    dejaba que quien empeña y devuelve dentro del primer mes no pagara
    interés: `months_owed` es 0 hasta cumplir el mes.

    El mínimo es sobre la vida del contrato, no sobre cada abono: si el ancla
    ya se movió de la fecha de inicio, ya se cobró al menos un mes y el
    mínimo está cumplido. Un sucesor de recargo hereda la fecha de inicio de
    la raíz y el ancla del padre (00053), así que ampliar el préstamo no
    reinicia ni esquiva el mínimo.
    """
    return 1 if interest_paid_until <= start_date else 0


def quote_payment_options(
    *,
    capital_balance: Decimal,
    interest_rate_pct: Decimal,
    interest_paid_until: date,
    today: date,
    start_date: date | None = None,
) -> PaymentQuote:
    """CLAUDE.md: "el endpoint debe devolver los montos exactos aceptables
    para que la UI los muestre (1 mes, 2 meses, ..., todo + capital libre)".
    Cada opción es un múltiplo exacto de `monthly_interest` — un pago parcial
    de un mes nunca es una opción válida, por construcción.

    `start_date` activa el mínimo de un mes al saldar (F4-11). Las `options`
    no cambian —siguen siendo los meses ADEUDADOS—; el mínimo solo aparece en
    `payoff_*`, porque un mes por adelantado sin saldar no es un abono que
    la regla admita.
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
    minimum = (
        minimum_payoff_months(start_date=start_date, interest_paid_until=interest_paid_until)
        if start_date is not None
        else 0
    )
    payoff_months = max(owed, minimum)
    payoff_interest = quantize(monthly * payoff_months)
    return PaymentQuote(
        months_owed=owed,
        monthly_interest=monthly,
        options=options,
        payoff_months=payoff_months,
        payoff_interest=payoff_interest,
        payoff_total=quantize(payoff_interest + capital_balance),
    )


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

    **Salvo que no haya fecha que conservar** (F4-03 / B-06, 27/09/2026). La
    fecha de fin de prórroga es función del ancla: `interest_paid_until + N`
    meses de ventana `+ extension_months`. Un abono mueve el ancla, así que
    `create_payment` pasa `extension_ends_at=None` para que se recalcule
    desde la nueva; si el contrato sigue en prórroga, la fecha nueva es la
    que corresponde a la deuda que queda (cada mes pagado corre el fin un
    mes). Conservar un `None` dejaba un `in_extension` sin fin: fuera de la
    lista de remate y sin poder rematarse, y ni el GET ni el job lo
    reparaban. Con esta regla, además, una fila que ya quedó así se corrige
    en la siguiente lectura.
    """
    if current_status in TERMINAL_STATUSES:
        return current_status, extension_ends_at

    owed = months_between(interest_paid_until, today)
    if owed == 0:
        return "active", None
    if owed < arrears_window_months:
        return "in_arrears", None

    if current_status == "in_extension" and extension_ends_at is not None:
        return "in_extension", extension_ends_at

    trigger_date = add_months(interest_paid_until, arrears_window_months)
    new_extension_ends_at = add_months(trigger_date, extension_months)
    return "in_extension", new_extension_ends_at


# --------------------------------------------------------- «Para hoy» ----
#: Los motivos de `GET /contracts/attention`, en orden de URGENCIA: la
#: posición en esta tupla es el primer criterio del orden de la lista.
ATTENTION_REASONS = ("ready_for_auction", "in_arrears", "in_extension", "due_today")


@dataclass(frozen=True)
class Attention:
    """Por qué un contrato pide acción hoy, y cuánto se cobraría."""

    reason: str
    #: El estado EFECTIVO (`compute_status` con el hoy de la empresa), no el
    #: persistido: el job nocturno puede ir un día atrás.
    status: str
    months_owed: int
    #: Días desde la primera cuota sin pagar (`ancla + 1 mes`). 0 el día en
    #: que vence.
    days_overdue: int
    #: La fecha que explica el motivo: fin de prórroga (vencida o por vencer),
    #: la cuota que venció (mora) u hoy (vence hoy).
    reference_date: date
    #: Ponerse al día (`monthly × months_owed`, la última opción de
    #: `payment-options`); en «listo para remate», SALDAR (`payoff_total`):
    #: con la prórroga vencida la conversación es recoger la prenda o perderla.
    amount_due_today: Decimal
    #: `monthly × months_owed`: el interés atrasado.
    overdue_interest: Decimal


def attention_for(
    *,
    current_status: str,
    interest_paid_until: date,
    arrears_window_months: int,
    extension_months: int,
    extension_ends_at: date | None,
    capital_balance: Decimal,
    interest_rate_pct: Decimal,
    start_date: date,
    today: date,
) -> Attention | None:
    """El motivo por el que un contrato aparece en «Para hoy», o `None`.

    Los motivos no se solapan (cada contrato cuenta en UNA tarjeta):

    - `ready_for_auction`: prórroga con fin `< hoy` (el criterio de
      `/ready-for-auction`).
    - `due_today`: la primera cuota sin pagar vence HOY. Ese día
      `months_owed` ya es 1, así que el estado efectivo es `in_arrears` (o
      `in_extension` con ventana de un mes); el motivo, no el estado, es lo
      que distingue «vence hoy» de «en mora».
    - `in_arrears`: en mora con al menos un día de atraso.
    - `in_extension`: en prórroga sin vencer.

    Todo monto sale de `quote_payment_options`: la tarjeta y los botones de
    cobro del contrato no pueden decir números distintos.
    """
    status, ends_at = compute_status(
        current_status=current_status,
        interest_paid_until=interest_paid_until,
        arrears_window_months=arrears_window_months,
        extension_months=extension_months,
        extension_ends_at=extension_ends_at,
        today=today,
    )
    if status in TERMINAL_STATUSES or status == "active":
        return None

    quote = quote_payment_options(
        capital_balance=capital_balance,
        interest_rate_pct=interest_rate_pct,
        interest_paid_until=interest_paid_until,
        today=today,
        start_date=start_date,
    )
    # Fuera de los terminales y `active`, `months_owed >= 1`: hay opciones.
    catch_up = quote.options[-1].total
    first_due = add_months(interest_paid_until, 1)
    days_overdue = (today - first_due).days

    def _build(reason: str, reference: date, amount: Decimal) -> Attention:
        return Attention(
            reason=reason,
            status=status,
            months_owed=quote.months_owed,
            days_overdue=days_overdue,
            reference_date=reference,
            amount_due_today=amount,
            overdue_interest=catch_up,
        )

    if status == "in_extension" and ends_at is not None and ends_at < today:
        return _build("ready_for_auction", ends_at, quote.payoff_total)
    if first_due == today:
        return _build("due_today", today, quote.monthly_interest)
    if status == "in_arrears":
        return _build("in_arrears", first_due, catch_up)
    assert ends_at is not None  # `compute_status` siempre fija el fin de una prórroga
    return _build("in_extension", ends_at, catch_up)


def attention_sort_key(a: Attention, *, number: int) -> tuple[int, int, int]:
    """Orden de «Requieren acción»: remate (la prórroga vencida más vieja
    primero) → mora (más días de atraso primero) → prórroga (la que vence
    antes primero) → vence hoy. Desempata el número del contrato."""
    rank = ATTENTION_REASONS.index(a.reason)
    if a.reason == "in_arrears":
        within = -a.days_overdue
    elif a.reason == "due_today":
        within = 0
    else:
        within = a.reference_date.toordinal()
    return (rank, within, number)


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
