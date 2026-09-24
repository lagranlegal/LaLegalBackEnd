"""Catálogo y preferencias de avisos (docs/NOTIFICACIONES.md §2, §4.3, §9.2,
§12.3). Puro: sin BD."""

from decimal import Decimal

from app.modules.notifications import catalog, preferences
from app.modules.notifications.digest import subscription_milestone_crossed

CUSTOMER_EVENTS = {
    "contract_created",
    "payment_registered",
    "contract_paid_off",
    "loan_extended",
    "credit_note_issued",
    "sale_receipt",
    "sale_reversed",
    "installment_due_soon",
    "installment_overdue",
    "extension_started",
    "extension_ending_soon",
    "auction_ready_customer",
}


def test_every_customer_event_exists_and_is_born_off() -> None:
    """§12.3: C1–C7, R1–R5 y el aviso de remate, todos en el catálogo y apagados."""
    customer = {c for c, t in catalog.EVENT_TYPES.items() if t.audience == "customer"}
    assert customer == CUSTOMER_EVENTS
    assert all(not catalog.get(c).default_enabled for c in CUSTOMER_EVENTS)


def test_every_event_declares_a_purpose() -> None:
    assert all(t.purpose in ("service", "marketing") for t in catalog.EVENT_TYPES.values())


def test_defaults_company_switch_off_digest_events_on() -> None:
    prefs = preferences.parse({"timezone": "America/Bogota"})
    assert prefs.enabled is False
    assert prefs.event_setting(catalog.DAILY_DIGEST) is True
    # Con el interruptor general apagado, nada es efectivo.
    assert prefs.event_enabled(catalog.DAILY_DIGEST) is False
    assert prefs.discount_threshold == Decimal("0")
    assert prefs.cash_difference_threshold == Decimal("0")
    assert prefs.stale_after_days == 2


def test_turning_on_a_customer_event_is_just_a_setting() -> None:
    prefs = preferences.parse(
        {"notifications": {"enabled": True, "events": {"auction_ready_customer": True}}}
    )
    assert prefs.event_enabled("auction_ready_customer") is True
    assert prefs.event_enabled("extension_started") is False


def test_unknown_override_is_ignored_when_reading() -> None:
    prefs = preferences.parse({"notifications": {"events": {"no_existe": True}}})
    assert prefs.events == {}


def test_roundtrip_keeps_everything() -> None:
    raw = {
        "notifications": {
            "enabled": True,
            "events": {"company_daily_digest": False},
            "thresholds": {"discount_amount": "50000", "cash_difference_amount": "10000"},
            "customer_contact_limits": {"max_per_week": 2, "weekday_hours": ["08:00", "18:00"]},
            "stale_after_days": 3,
        }
    }
    prefs = preferences.parse(raw)
    assert preferences.parse({"notifications": preferences.to_settings(prefs)}) == prefs
    assert prefs.customer_contact_limits.max_per_week == 2


def test_purpose_basis_matrix() -> None:
    """§9.2-c. Hasta la fase 3 la base es siempre None → no sale nada al cliente."""
    assert catalog.basis_allows("service", "contract")
    assert catalog.basis_allows("service", "consent")
    assert not catalog.basis_allows("marketing", "contract")
    assert catalog.basis_allows("marketing", "consent")
    assert not catalog.basis_allows("service", None)


def test_subscription_milestones_by_crossing() -> None:
    from datetime import date

    exp = date(2030, 9, 20)
    # Hoy faltan 7 días y ayer faltaban 8: se cruzó el hito de 7.
    assert (
        subscription_milestone_crossed(
            expires_at=exp, after=date(2030, 9, 12), today=date(2030, 9, 13)
        )
        == 7
    )
    # Faltan 8: ningún hito.
    assert (
        subscription_milestone_crossed(
            expires_at=exp, after=date(2030, 9, 11), today=date(2030, 9, 12)
        )
        is None
    )
    # El job no corrió el día del hito: sale en la siguiente corrida.
    assert (
        subscription_milestone_crossed(
            expires_at=exp, after=date(2030, 9, 4), today=date(2030, 9, 7)
        )
        == 15
    )
    # Se cruzaron dos: gana el más urgente.
    assert (
        subscription_milestone_crossed(
            expires_at=exp, after=date(2030, 9, 1), today=date(2030, 9, 19)
        )
        == 1
    )
