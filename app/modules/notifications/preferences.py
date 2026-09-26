"""Preferencias de avisos de una empresa — puro, sin BD.

Viven en `company.settings.notifications` (jsonb), docs/NOTIFICACIONES.md
§4.3. Todo lo que falte se lee con su default; nada de esto exige una
migración ni un backfill, y una empresa que nunca tocó la pantalla se
comporta exactamente como dicen los defaults de abajo.

    {
      "enabled": false,                       # ¿esta empresa manda correos? (§4.3, §11)
      "events": {"auction_ready_customer": true},   # override sobre el catálogo
      "thresholds": {"discount_amount": "0", "cash_difference_amount": "0"},
      "customer_contact_limits": {...},       # Ley 2300 (§12.3), solo audience='customer'
      "stale_after_days": 2,                  # ventana de rezago (§5.3, §12.2-5)
      "reminders": {"installment_days_before": [3], "extension_days_before": [3]}
    }

**Por qué `enabled` nace en `false`, también para el resumen.** Encenderlo es
un acto explícito (§4.3) y el deploy no puede, por sí solo, empezar a escribirle
a los administradores de las 7 empresas de la base — dos son laboratorios de QA
con correos de mentira, y un rebote temprano es reputación de `prendo.com.co`
que se pierde para todos (§8).
"""

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal, InvalidOperation
from typing import Any

from app.common.money import quantize
from app.modules.notifications import catalog

DEFAULT_STALE_AFTER_DAYS = 2


@dataclass(frozen=True)
class ContactLimits:
    """Límites de contacto al CLIENTE — parámetros del despachador, no lógica fija.

    Defaults conservadores, dentro de la Ley 2300 de 2023 («dejen de fregar»),
    tal como §12.3 pide mientras el abogado no diga si aplica: lunes a viernes
    de 7:00 a 19:00, sábados de 8:00 a 15:00, nunca domingos ni festivos, y un
    contacto por semana por canal. **Los horarios y el tope semanal son mi
    lectura de la ley, no un concepto legal** — por eso son parámetros: si el
    abogado dice otra cosa, se cambian en `settings` sin tocar código.

    A la EMPRESA no se le aplica nada de esto: el resumen va a sus propios
    usuarios, no a un deudor.
    """

    enabled: bool = True
    max_per_week: int = 1
    #: §3: además del semanal, el tope diario del diseño original.
    max_per_day: int = 3
    weekday_start: time = time(7, 0)
    weekday_end: time = time(19, 0)
    saturday_start: time = time(8, 0)
    saturday_end: time = time(15, 0)
    sundays_and_holidays: bool = False
    #: ¿Un comprobante (C1–C7) cuenta como contacto para el tope SEMANAL? Nace
    #: en `False` (docs/NOTIFICACIONES.md §18.1-1): la Ley 2300 limita los
    #: contactos de COBRANZA, y un comprobante de algo que el cliente acaba de
    #: hacer en el mostrador no es cobranza. Con el tope aplicado, el segundo
    #: abono de la semana quedaba `throttled` y el cliente sin su comprobante.
    #: Si un abogado dice que sí cuenta, se pone en `True` y vuelve el
    #: comportamiento anterior — sin código. **No toca la ventana horaria ni el
    #: tope diario**: esos siguen valiendo para todo aviso al cliente.
    transactional_in_weekly_cap: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_per_week": self.max_per_week,
            "max_per_day": self.max_per_day,
            "weekday_hours": [_fmt(self.weekday_start), _fmt(self.weekday_end)],
            "saturday_hours": [_fmt(self.saturday_start), _fmt(self.saturday_end)],
            "sundays_and_holidays": self.sundays_and_holidays,
            "transactional_in_weekly_cap": self.transactional_in_weekly_cap,
        }


#: §12.1-1 / §12.2-1: la cuota se recuerda 3 días antes y el día del
#: vencimiento. R4 («la prórroga vence pronto») no tenía número en el diseño
#: (§2.2 dice «N días»): se tomó el mismo 3 del recordatorio de cuota.
#: R1 solo 3 días antes (decisión del 25/09/2026, docs/NOTIFICACIONES.md §20.2-1).
#: Era `(3, 0)`: con el tope semanal, el aviso del día casi siempre quedaba
#: `throttled` porque el de 3 días antes ya había gastado el cupo.
DEFAULT_INSTALLMENT_DAYS_BEFORE: tuple[int, ...] = (3,)
DEFAULT_EXTENSION_DAYS_BEFORE: tuple[int, ...] = (3,)
MAX_DAYS_BEFORE = 30
MAX_REMINDER_POINTS = 5


@dataclass(frozen=True)
class ReminderSchedule:
    """Cuántos días antes salen los recordatorios por fecha (R1 y R4,
    docs/NOTIFICACIONES.md §20). Parámetros por empresa, como pidió §12.2-1.
    De fábrica, 3 días antes para los dos: §12.2-1 le había puesto a R1
    también el día del vencimiento, y el 25/09/2026 se sacó (§20.2-1).

    **Ojo con el tope semanal (Ley 2300):** con un contacto por semana, dos
    puntos a menos de 7 días uno del otro no salen los dos — el segundo queda
    `throttled`. Es la ley aplicada tal cual (§12.3), no un defecto; §20.4 lo
    discute."""

    installment_days_before: tuple[int, ...] = DEFAULT_INSTALLMENT_DAYS_BEFORE
    extension_days_before: tuple[int, ...] = DEFAULT_EXTENSION_DAYS_BEFORE

    def as_dict(self) -> dict[str, Any]:
        return {
            "installment_days_before": list(self.installment_days_before),
            "extension_days_before": list(self.extension_days_before),
        }


@dataclass(frozen=True)
class NotificationPrefs:
    enabled: bool = False
    events: dict[str, bool] = field(default_factory=dict)
    #: §12.2-4: nacen en 0 (se avisa todo). El umbral decide SOLO la alerta
    #: inmediata (fase 7) y la marca "sobre el umbral" del resumen; lo que
    #: queda por debajo igual sale en el resumen.
    discount_threshold: Decimal = Decimal("0.00")
    cash_difference_threshold: Decimal = Decimal("0.00")
    customer_contact_limits: ContactLimits = field(default_factory=ContactLimits)
    stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
    reminders: ReminderSchedule = field(default_factory=ReminderSchedule)

    def above_discount_threshold(self, amount: Decimal) -> bool:
        """¿Este descuento pasa el umbral? Estricto (`>`), así que con el
        umbral en 0 —como nace, §12.2-4— TODO descuento lo pasa. Una sola
        definición para las dos cosas que decide: la alerta inmediata A2
        (fase 7) y la marca «sobre el umbral» del resumen."""
        return abs(amount) > self.discount_threshold

    def event_enabled(self, code: str) -> bool:
        """El interruptor efectivo de un evento: el de la empresa Y el del evento
        (override por empresa, o el `default_enabled` del catálogo).

        **Salvo los de la plataforma** (`audience='platform'`, hoy solo la
        invitación, docs/NOTIFICACIONES.md §16): ni el interruptor general ni
        un override los tocan. El interruptor contesta «¿este negocio le
        escribe a sus clientes / a sus administradores?»; la invitación no la
        escribe el negocio, la escribe Prendo a alguien que todavía no tiene
        cuenta (§8). Si el interruptor —que nace apagado— la gobernara, ninguna
        empresa podría invitar a nadie por correo hasta encender los avisos a
        sus clientes: dos decisiones sin relación, amarradas por accidente.
        """
        if catalog.get(code).audience == "platform":
            return self.event_setting(code)
        if not self.enabled:
            return False
        return self.event_setting(code)

    def event_setting(self, code: str) -> bool:
        """El valor del evento sin mirar el interruptor general.

        Para los de la plataforma, siempre el del catálogo: el PATCH ya rechaza
        el override (`NOTIFICATION_EVENT_NOT_CONFIGURABLE`), pero el jsonb se
        puede escribir por otros caminos y leer tiene que ser tan estricto como
        escribir."""
        et = catalog.get(code)
        if et.audience == "platform":
            return et.default_enabled
        if code in self.events:
            return self.events[code]
        return catalog.get(code).default_enabled


def _fmt(t: time) -> str:
    return t.strftime("%H:%M")


def _parse_time(value: Any, default: time) -> time:
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return default


def _parse_hours(value: Any, default: tuple[time, time]) -> tuple[time, time]:
    if isinstance(value, list | tuple) and len(value) == 2:
        return _parse_time(value[0], default[0]), _parse_time(value[1], default[1])
    return default


def _parse_decimal(value: Any) -> Decimal:
    try:
        parsed = quantize(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")
    return parsed if parsed >= 0 else Decimal("0.00")


def parse_limits(raw: Any) -> ContactLimits:
    d = raw if isinstance(raw, dict) else {}
    base = ContactLimits()
    weekday = _parse_hours(d.get("weekday_hours"), (base.weekday_start, base.weekday_end))
    saturday = _parse_hours(d.get("saturday_hours"), (base.saturday_start, base.saturday_end))
    return ContactLimits(
        enabled=bool(d.get("enabled", base.enabled)),
        max_per_week=int(d.get("max_per_week", base.max_per_week)),
        max_per_day=int(d.get("max_per_day", base.max_per_day)),
        weekday_start=weekday[0],
        weekday_end=weekday[1],
        saturday_start=saturday[0],
        saturday_end=saturday[1],
        sundays_and_holidays=bool(d.get("sundays_and_holidays", base.sundays_and_holidays)),
        transactional_in_weekly_cap=bool(
            d.get("transactional_in_weekly_cap", base.transactional_in_weekly_cap)
        ),
    )


def parse_days(raw: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    """Una lista de días antes: enteros entre 0 y 30, sin repetir, de mayor a
    menor. Lo que no se entienda cae al default — leer tiene que ser tan
    estricto como escribir (el jsonb se puede tocar por otros caminos)."""
    if not isinstance(raw, list | tuple):
        return default
    days: set[int] = set()
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        if not 0 <= value <= MAX_DAYS_BEFORE:
            return default
        days.add(value)
    if len(days) > MAX_REMINDER_POINTS:
        return default
    return tuple(sorted(days, reverse=True))


def parse_reminders(raw: Any) -> ReminderSchedule:
    d = raw if isinstance(raw, dict) else {}
    return ReminderSchedule(
        installment_days_before=parse_days(
            d.get("installment_days_before"), DEFAULT_INSTALLMENT_DAYS_BEFORE
        ),
        extension_days_before=parse_days(
            d.get("extension_days_before"), DEFAULT_EXTENSION_DAYS_BEFORE
        ),
    )


def parse(settings: dict[str, Any] | None) -> NotificationPrefs:
    """`settings` es el jsonb COMPLETO de `company.settings`."""
    raw = (settings or {}).get("notifications") or {}
    if not isinstance(raw, dict):
        raw = {}
    events_raw = raw.get("events") or {}
    events = {
        code: bool(value)
        for code, value in (events_raw.items() if isinstance(events_raw, dict) else [])
        if code in catalog.EVENT_TYPES
    }
    thresholds = raw.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        thresholds = {}
    stale = raw.get("stale_after_days", DEFAULT_STALE_AFTER_DAYS)
    return NotificationPrefs(
        enabled=bool(raw.get("enabled", False)),
        events=events,
        discount_threshold=_parse_decimal(thresholds.get("discount_amount", "0")),
        cash_difference_threshold=_parse_decimal(thresholds.get("cash_difference_amount", "0")),
        customer_contact_limits=parse_limits(raw.get("customer_contact_limits")),
        stale_after_days=(
            int(stale) if isinstance(stale, int) and stale >= 0 else DEFAULT_STALE_AFTER_DAYS
        ),
        reminders=parse_reminders(raw.get("reminders")),
    )


def to_settings(prefs: NotificationPrefs) -> dict[str, Any]:
    """La forma que se guarda en `company.settings.notifications`."""
    return {
        "enabled": prefs.enabled,
        "events": dict(sorted(prefs.events.items())),
        "thresholds": {
            "discount_amount": str(prefs.discount_threshold),
            "cash_difference_amount": str(prefs.cash_difference_threshold),
        },
        "customer_contact_limits": prefs.customer_contact_limits.as_dict(),
        "stale_after_days": prefs.stale_after_days,
        "reminders": prefs.reminders.as_dict(),
    }
