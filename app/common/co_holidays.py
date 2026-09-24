"""Festivos de Colombia — puro, sin BD ni dependencias.

Lo necesita el despachador de avisos para no escribirle a un cliente un
domingo o un festivo (Ley 2300 de 2023, docs/NOTIFICACIONES.md §12.3). Se
calcula en vez de copiarse de una lista porque una lista se vence el 31 de
diciembre y nadie se acuerda de actualizarla.

Reglas (Ley 51 de 1983, "Ley Emiliani", más los festivos religiosos móviles):

- **Fijos**: 1 ene, 1 may, 20 jul, 7 ago, 8 dic, 25 dic.
- **Trasladables al lunes siguiente** (si no caen en lunes): 6 ene (Reyes),
  19 mar (San José), 29 jun (San Pedro y San Pablo), 15 ago (Asunción),
  12 oct (Día de la Raza), 1 nov (Todos los Santos), 11 nov (Independencia de
  Cartagena).
- **Según Pascua**: Jueves y Viernes Santo (sin traslado); Ascensión
  (+43 días), Corpus Christi (+64) y Sagrado Corazón (+71), que ya caen en
  lunes porque la ley los traslada.
"""

from datetime import date, timedelta
from functools import lru_cache


def easter_sunday(year: int) -> date:
    """Domingo de Pascua, algoritmo anónimo gregoriano (Meeus/Jones/Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month, day = divmod(h + ll - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _next_monday(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


@lru_cache(maxsize=64)
def colombian_holidays(year: int) -> frozenset[date]:
    fixed = {
        date(year, 1, 1),
        date(year, 5, 1),
        date(year, 7, 20),
        date(year, 8, 7),
        date(year, 12, 8),
        date(year, 12, 25),
    }
    movable = {
        _next_monday(date(year, month, day))
        for month, day in ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))
    }
    easter = easter_sunday(year)
    easter_based = {
        easter - timedelta(days=3),  # Jueves Santo
        easter - timedelta(days=2),  # Viernes Santo
        easter + timedelta(days=43),  # Ascensión (lunes)
        easter + timedelta(days=64),  # Corpus Christi (lunes)
        easter + timedelta(days=71),  # Sagrado Corazón (lunes)
    }
    return frozenset(fixed | movable | easter_based)


def is_colombian_holiday(d: date) -> bool:
    return d in colombian_holidays(d.year)
