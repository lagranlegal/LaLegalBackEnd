"""Fecha "de hoy" para reglas de negocio — SIEMPRE en la zona horaria de la
empresa (`company.settings.timezone`), nunca en la del servidor.

Encontrado como bug real en el paso 6: Fly.io corre en UTC; Colombia es
UTC-5 sin horario de verano, así que entre las 7pm y la medianoche hora
Colombia, UTC ya está "un día adelante" — una ventana de 5 horas TODOS los
días, en pleno horario de atención, no un caso raro de medianoche. Cualquier
`date.today()` naive en reglas de negocio (caja diaria, meses de interés
adeudados, vencimientos) puede calcular el día equivocado en esa ventana.

Puro, sin BD — quien llama resuelve el `tz_name` de la empresa (ver
`app.modules.platform.integration.get_company_today`, que sí cachea la
consulta a BD) y se lo pasa a `today_in`.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "America/Bogota"


def today_in(tz_name: str | None, *, now: datetime | None = None) -> date:
    """`now` es inyectable (default: instante real en UTC) para poder
    testear determinísticamente el caso límite del bug — sin esto, un test
    solo falla si corre justo dentro de la ventana de 5 horas del desfase.
    """
    try:
        tz = ZoneInfo(tz_name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo(DEFAULT_TIMEZONE)
    reference = now if now is not None else datetime.now(UTC)
    return reference.astimezone(tz).date()
