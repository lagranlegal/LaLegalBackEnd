"""Catálogo de eventos notificables (docs/NOTIFICACIONES.md §2, §4.3, §9.2).

Espejo EXACTO de la tabla `notification_event_type` que siembra `00058`. Vive
en los dos lados por una razón concreta: la BD lo necesita para la FK de
`notification_event.event_type` (un evento con un tipo inventado no entra), y
el código lo necesita para decidir sin consultar. Un test de integración
compara las dos listas en las dos direcciones, así que no pueden divergir sin
que la suite lo diga.

**Todos los avisos al CLIENTE nacen apagados** (`default_enabled=False`,
§12.3 — las preguntas legales están en pausa). Encender uno es
`company.settings.notifications.events.<code> = true`, sin código.
"""

from dataclasses import dataclass
from typing import Literal

Audience = Literal["customer", "company", "platform"]
Purpose = Literal["service", "marketing"]
Family = Literal["transactional", "reminder", "state", "digest", "alert", "platform"]


@dataclass(frozen=True)
class EventType:
    code: str
    audience: Audience
    #: Sin default a propósito (§9.2-b): quien agregue un evento tiene que
    #: decidir si es servicio del contrato o mercadeo.
    purpose: Purpose
    family: Family
    default_enabled: bool
    description: str


DAILY_DIGEST = "company_daily_digest"
WEEKLY_DIGEST = "company_weekly_digest"
AUCTION_READY_CUSTOMER = "auction_ready_customer"

_TYPES: tuple[EventType, ...] = (
    # §2.1 transaccionales al cliente (C1–C7)
    EventType(
        "contract_created",
        "customer",
        "service",
        "transactional",
        False,
        "C1 · Contrato creado: número, monto y fecha de la próxima cuota",
    ),
    EventType(
        "payment_registered",
        "customer",
        "service",
        "transactional",
        False,
        "C2 · Abono registrado: qué pagó, hasta cuándo quedó cubierto y saldo",
    ),
    EventType(
        "contract_paid_off",
        "customer",
        "service",
        "transactional",
        False,
        "C3 · Paz y salvo: el contrato quedó saldado",
    ),
    EventType(
        "loan_extended",
        "customer",
        "service",
        "transactional",
        False,
        "C4 · Préstamo ampliado: nace un contrato sucesor",
    ),
    EventType(
        "credit_note_issued",
        "customer",
        "service",
        "transactional",
        False,
        "C5 · Nota crédito emitida: saldo a favor",
    ),
    EventType(
        "sale_receipt",
        "customer",
        "service",
        "transactional",
        False,
        "C6 · Comprobante de venta (solo ventas con cliente)",
    ),
    EventType(
        "sale_reversed",
        "customer",
        "service",
        "transactional",
        False,
        "C7 · Venta anulada o devolución",
    ),
    # §2.2 recordatorios y cambios de estado al cliente (R1–R5)
    EventType(
        "installment_due_soon",
        "customer",
        "service",
        "reminder",
        False,
        "R1 · Cuota por vencer (3 días antes; los días se configuran)",
    ),
    EventType(
        "installment_overdue",
        "customer",
        "service",
        "state",
        False,
        "R2 · Cuota vencida: el contrato entró en mora",
    ),
    EventType(
        "extension_started",
        "customer",
        "service",
        "state",
        False,
        "R3 · El contrato entró en prórroga",
    ),
    EventType(
        "extension_ending_soon",
        "customer",
        "service",
        "reminder",
        False,
        "R4 · La prórroga vence pronto",
    ),
    EventType(
        AUCTION_READY_CUSTOMER,
        "customer",
        "service",
        "state",
        False,
        "R5 · Aviso al cliente de que su prenda está lista para remate",
    ),
    # §2.4 resumen a la empresa
    EventType(
        DAILY_DIGEST,
        "company",
        "service",
        "digest",
        True,
        "Resumen diario a la empresa: sale solo si hubo actividad o alertas",
    ),
    EventType(
        WEEKLY_DIGEST,
        "company",
        "service",
        "digest",
        True,
        "Resumen semanal a la empresa (lunes): sale siempre",
    ),
    # §2.5 alertas inmediatas a la empresa (fase 7: el tipo existe, el productor no)
    EventType("alert_sale_voided", "company", "service", "alert", True, "A1 · Venta anulada"),
    EventType(
        "alert_discount",
        "company",
        "service",
        "alert",
        True,
        "A2 · Descuento por encima del umbral de la empresa",
    ),
    EventType(
        "alert_capital_withdrawal",
        "company",
        "service",
        "alert",
        True,
        "A3 · Retiro de capital del dueño",
    ),
    EventType("alert_cash_reopened", "company", "service", "alert", True, "A4 · Caja reabierta"),
    # §2.6 de la plataforma (fase 2)
    EventType(
        "user_invitation", "platform", "service", "platform", True, "P1 · Invitación de usuario"
    ),
)

EVENT_TYPES: dict[str, EventType] = {t.code: t for t in _TYPES}


def get(code: str) -> EventType:
    return EVENT_TYPES[code]


#: §9.2-d — finalidad del evento → bases legales del cliente que la
#: habilitan. **Configuración de la plataforma, no del inquilino**: la ley es
#: la misma para todos. Si un abogado dice "estricto", se cambia a
#: `"service": frozenset({"consent"})` y nada más.
#:
#: Hasta la fase 3 no existe `customer.email_basis`, así que la base de todo
#: cliente es `None` y cualquier aviso al cliente que se encienda antes de esa
#: fase nace `suppressed`. Es a propósito: encender un evento no puede
#: adelantarse a la base legal que lo sostiene.
PURPOSE_ACCEPTED_BASES: dict[str, frozenset[str]] = {
    "service": frozenset({"contract", "consent"}),
    "marketing": frozenset({"consent"}),
}


def basis_allows(purpose: str, basis: str | None) -> bool:
    if basis is None:
        return False
    return basis in PURPOSE_ACCEPTED_BASES.get(purpose, frozenset())
