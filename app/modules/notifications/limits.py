"""Límites de contacto al cliente (Ley 2300 de 2023) — puro, sin BD.

docs/NOTIFICACIONES.md §12.3: se construyen como PARÁMETROS del despachador y
se hacen cumplir **en un solo lugar** (§14): el despachador los consulta antes
de mandar cada entrega con `audience='customer'`. Ningún productor de eventos
los mira — si cada uno aplicara su tope, habría tantas reglas como productores.

Dos decisiones distintas, y por eso dos funciones:

- **La hora** (`next_allowed_moment`): fuera de horario la entrega NO se
  pierde, se corre al próximo momento hábil. Un recordatorio que el job
  decidió a las 3 a. m. sale a las 7 a. m., no se descarta.
- **El tope** (`exceeds_cap`): pasado el tope la entrega queda `throttled`,
  terminal (§4.2). Correrla a la semana siguiente sería mandar un aviso viejo.
"""

from datetime import datetime, time, timedelta

from app.common.co_holidays import is_colombian_holiday
from app.modules.notifications.preferences import ContactLimits


def _window_for(local: datetime, limits: ContactLimits) -> tuple[time, time] | None:
    """Ventana hábil del DÍA de `local`, o None si ese día no se contacta."""
    day = local.date()
    if day.weekday() == 6 or is_colombian_holiday(day):
        if not limits.sundays_and_holidays:
            return None
        return limits.weekday_start, limits.weekday_end
    if day.weekday() == 5:
        return limits.saturday_start, limits.saturday_end
    return limits.weekday_start, limits.weekday_end


def is_allowed_moment(local: datetime, limits: ContactLimits) -> bool:
    if not limits.enabled:
        return True
    window = _window_for(local, limits)
    if window is None:
        return False
    start, end = window
    return start <= local.time() < end


def next_allowed_moment(local: datetime, limits: ContactLimits) -> datetime:
    """El primer instante >= `local` en que se puede contactar al cliente.

    `local` tiene que venir con la zona horaria de la EMPRESA (ARCHITECTURE
    §10): "las 7 a. m." son las del cliente, no las de Fly en UTC.
    """
    if is_allowed_moment(local, limits):
        return local
    candidate = local
    for _ in range(15):  # dos semanas alcanzan incluso con un puente largo
        window = _window_for(candidate, limits)
        if window is not None:
            start, end = window
            if candidate.time() < start:
                return candidate.replace(
                    hour=start.hour, minute=start.minute, second=0, microsecond=0
                )
            if candidate.time() < end:
                return candidate
        candidate = (candidate + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return candidate


def exceeds_cap(
    *,
    sent_last_day: int,
    sent_last_week: int,
    limits: ContactLimits,
    transactional: bool = False,
) -> bool:
    """¿Mandar uno más superaría el tope? Cuenta lo YA enviado a ese destinatario.

    Dos topes que no son la misma regla (docs/NOTIFICACIONES.md §18.1-1):

    - **El diario** (§3) es de producto, contra el cliente de 13 contratos que
      recibiría 16 correos en un día. Cuenta TODO aviso al cliente, también los
      comprobantes.
    - **El semanal** es el de la Ley 2300, que limita los contactos de
      COBRANZA. Un comprobante (`transactional`) no es cobranza: no lo frena —
      salvo `transactional_in_weekly_cap`, que es la respuesta del abogado
      puesta como parámetro. Quien cuenta `sent_last_week` tiene que contar
      con el mismo criterio (`repository.count_sent_to`)."""
    if not limits.enabled:
        return False
    if sent_last_day >= limits.max_per_day:
        return True
    if transactional and not limits.transactional_in_weekly_cap:
        return False
    return sent_last_week >= limits.max_per_week
