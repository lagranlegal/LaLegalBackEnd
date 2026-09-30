"""Fechas "de la empresa" para los tests de integración.

Todas las empresas de prueba usan la zona por defecto (`America/Bogota`, ver
`company.settings` en 00002). El backend calcula "hoy" en esa zona
(`get_company_today`); un test que usa `date.today()` usa la del PROCESO.

En el Mac de desarrollo las dos coinciden y el error no se ve. En la CI (y en
Fly) el proceso corre en UTC: entre las 7 p. m. y la medianoche de Bogotá la
fecha UTC ya es la del día siguiente, y cualquier test que compare "hoy" contra
lo que el backend guardó falla solo de noche.

Lo mismo con una `date` pasada a una columna `timestamptz`: asyncpg la
convierte a la medianoche de la zona LOCAL del proceso, que en UTC cae a las
7 p. m. del día anterior en Bogotá. Para antedatar, `mediodia_empresa(d)`.
"""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

ZONA_EMPRESA = ZoneInfo("America/Bogota")


def hoy_empresa() -> date:
    """El "hoy" de la empresa de prueba, sin importar la zona del proceso."""
    return datetime.now(ZONA_EMPRESA).date()


def mediodia_empresa(d: date) -> datetime:
    """El mediodía de `d` en la zona de la empresa: un instante que cae en el
    día `d` de la empresa desde cualquier zona del proceso."""
    return datetime.combine(d, time(12), tzinfo=ZONA_EMPRESA)
