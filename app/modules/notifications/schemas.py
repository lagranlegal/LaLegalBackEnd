from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DeliveryStatus = Literal[
    "pending",
    "sending",
    "sent",
    "delivered",
    "bounced",
    "failed",
    "dead",
    "unroutable",
    "suppressed",
    "throttled",
    "skipped_stale",
    "skipped_no_provider",
]


class EventTypeSettingOut(BaseModel):
    code: str
    audience: Literal["customer", "company", "platform"]
    purpose: Literal["service", "marketing"]
    family: str
    description: str
    default_enabled: bool
    #: El valor del evento para esta empresa (override o default del catálogo),
    #: SIN mirar el interruptor general.
    enabled: bool
    #: `true` si la empresa lo cambió respecto del catálogo.
    overridden: bool
    #: Lo que de verdad pasa hoy: `enabled` Y el interruptor general.
    effective: bool


class ThresholdsOut(BaseModel):
    discount_amount: Decimal
    cash_difference_amount: Decimal


class ContactLimitsOut(BaseModel):
    """Límites de contacto al CLIENTE (Ley 2300). No aplican a la empresa."""

    enabled: bool
    max_per_week: int
    max_per_day: int
    weekday_hours: tuple[str, str]
    saturday_hours: tuple[str, str]
    sundays_and_holidays: bool
    #: Si los comprobantes (C1–C7) cuentan para el tope SEMANAL. `false` por
    #: defecto: el tope semanal es de cobranza (NOTIFICACIONES §18.1-1). La
    #: ventana horaria y el tope diario los alcanzan igual.
    transactional_in_weekly_cap: bool


class ReminderScheduleOut(BaseModel):
    """Cuántos días antes salen los recordatorios por fecha (NOTIFICACIONES §20).
    De mayor a menor; `0` es el mismo día."""

    #: R1 · la cuota. De fábrica `[3, 0]`: 3 días antes y el día del vencimiento.
    installment_days_before: list[int]
    #: R4 · el fin de la prórroga. De fábrica `[3]`.
    extension_days_before: list[int]


class DigestRecipientOut(BaseModel):
    user_id: UUID
    full_name: str
    email: str


class NotificationSettingsOut(BaseModel):
    #: Interruptor general de la empresa. Apagado por defecto (§4.3, §11).
    enabled: bool
    #: Hay proveedor de correo configurado en la plataforma. Si es `false`,
    #: nada sale aunque todo esté encendido (las entregas quedan
    #: `skipped_no_provider`) — la pantalla debe decirlo.
    provider_configured: bool
    events: list[EventTypeSettingOut]
    thresholds: ThresholdsOut
    customer_contact_limits: ContactLimitsOut
    stale_after_days: int
    #: Aditivo (fase 5). Con el tope semanal de la Ley 2300 (1 por semana), dos
    #: puntos a menos de 7 días no salen los dos: el segundo queda `throttled`.
    reminders: ReminderScheduleOut
    #: A quién le llega hoy el resumen: usuarios activos con el permiso
    #: `notifications.receive_digest`.
    digest_recipients: list[DigestRecipientOut]
    #: A quién le llegan hoy las alertas inmediatas (A1–A4, §2.5, fase 7):
    #: usuarios activos con `notifications.receive_alerts`. Aditivo. Ojo: la
    #: alerta NO le llega a quien hizo el acto, aunque esté en esta lista.
    alert_recipients: list[DigestRecipientOut]


class ThresholdsIn(BaseModel):
    discount_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    cash_difference_amount: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )


def _check_hhmm(value: str) -> str:
    parts = value.split(":")
    if len(parts) != 2 or not all(p.isdigit() and len(p) == 2 for p in parts):
        raise ValueError("La hora va como HH:MM.")
    hh, mm = int(parts[0]), int(parts[1])
    if hh > 23 or mm > 59:
        raise ValueError("La hora va como HH:MM.")
    return value


class ContactLimitsIn(BaseModel):
    enabled: bool | None = None
    max_per_week: int | None = Field(default=None, ge=0, le=50)
    max_per_day: int | None = Field(default=None, ge=0, le=20)
    weekday_hours: tuple[str, str] | None = None
    saturday_hours: tuple[str, str] | None = None
    sundays_and_holidays: bool | None = None
    transactional_in_weekly_cap: bool | None = None

    @field_validator("weekday_hours", "saturday_hours")
    @classmethod
    def _hours(cls, value: tuple[str, str] | None) -> tuple[str, str] | None:
        if value is None:
            return None
        start, end = _check_hhmm(value[0]), _check_hhmm(value[1])
        if start >= end:
            raise ValueError("La hora de inicio tiene que ser anterior a la de fin.")
        return start, end


def _check_days(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    if len(set(value)) != len(value):
        raise ValueError("Los días no se pueden repetir.")
    return sorted(value, reverse=True)


class ReminderScheduleIn(BaseModel):
    installment_days_before: list[int] | None = Field(default=None, max_length=5)
    extension_days_before: list[int] | None = Field(default=None, max_length=5)

    @field_validator("installment_days_before", "extension_days_before")
    @classmethod
    def _days(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(d < 0 or d > 30 for d in value):
            raise ValueError("Cada valor va entre 0 y 30 días.")
        return _check_days(value)


class NotificationSettingsUpdateIn(BaseModel):
    """PATCH parcial: lo que no viene no cambia.

    `events` es un mapa código → `true`/`false`/`null`; `null` borra el
    override y el evento vuelve al default del catálogo.
    """

    enabled: bool | None = None
    events: dict[str, bool | None] | None = None
    thresholds: ThresholdsIn | None = None
    customer_contact_limits: ContactLimitsIn | None = None
    stale_after_days: int | None = Field(default=None, ge=0, le=30)
    reminders: ReminderScheduleIn | None = None


class DeliveryOut(BaseModel):
    id: UUID
    event_id: UUID
    event_type: str
    audience: str
    occurred_on: date
    channel: str
    to_address: str | None
    recipient_user_id: UUID | None
    status: DeliveryStatus
    attempts: int
    last_error: str | None
    provider_id: str | None
    scheduled_at: datetime
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime
    #: Con qué base legal se decidió mandarla (NOTIFICACIONES §9.2-a): la de
    #: ESE día, que es la que hay que poder mostrar después. Solo en entregas
    #: al cliente que salieron o iban a salir.
    legal_basis: Literal["contract", "consent"] | None = None


class UnsubscribeOut(BaseModel):
    """Lo que ve quien abre el enlace de baja (NOTIFICACIONES §17). Lo justo
    para reconocerse: la empresa y el correo enmascarado. Ni el nombre del
    cliente ni su documento — quien tiene el enlace puede no ser el titular
    (un correo reenviado)."""

    company_name: str
    #: `j•••@gmail.com`. `null` si la ficha ya no tiene correo.
    email_hint: str | None
    #: `null` = sigue suscrito. Con fecha = ya se dio de baja (y desde cuándo).
    unsubscribed_at: datetime | None
