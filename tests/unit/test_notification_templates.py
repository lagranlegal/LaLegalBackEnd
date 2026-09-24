"""Plantillas de correo (docs/NOTIFICACIONES.md §4.4, §8, §9.1). El test mira
el RENDER, no la plantilla: un test sobre la plantilla no cubre el payload."""

from app.modules.notifications import templates

BRAND = templates.Branding(
    company_name="LA GRAN LEGAL",
    contact_email="contacto@lagranlegal.example",
    contact_phone="300 000 0000",
    footer_note="Gracias por preferirnos",
)


def test_money_is_colombian() -> None:
    assert templates.money("1234567.00") == "$1.234.567"
    assert templates.money("1500.50") == "$1.500,50"
    assert templates.money("-18000") == "-$18.000"


def test_customer_render_never_leaks_document_or_item() -> None:
    payload = {
        "contract_number": 42,
        "extension_ends_at": "2030-09-01",
        "first_name": "Juan Pérez",
        # Lo que un productor descuidado podría meter de más:
        "doc_number": "1032456789",
        "item_description": "Cadena de oro 18k",
        "address": "Calle 1 # 2-3",
    }
    rendered = templates.render("auction_ready_customer", payload, BRAND)
    for body in (rendered.html, rendered.text, rendered.subject):
        assert "1032456789" not in body
        assert "Cadena" not in body
        assert "Calle 1" not in body
    assert "#42" in rendered.text
    assert "Hola, Juan:" in rendered.text


def test_customer_sender_is_platform_on_behalf_of_company() -> None:
    rendered = templates.render(
        "auction_ready_customer", {"contract_number": 1, "extension_ends_at": "2030-09-01"}, BRAND
    )
    assert rendered.from_name == "LA GRAN LEGAL (vía Prendo)"
    assert rendered.subject.startswith("LA GRAN LEGAL · ")
    assert "Prendo" not in rendered.subject
    assert rendered.reply_to == "contacto@lagranlegal.example"


def test_no_reply_to_when_company_has_no_contact_email() -> None:
    brand = templates.Branding(company_name="X")
    rendered = templates.render(
        "auction_ready_customer", {"contract_number": 1, "extension_ends_at": "2030-09-01"}, brand
    )
    assert rendered.reply_to is None


def test_from_header_cannot_be_injected() -> None:
    header = templates.from_header('Evil" <x@y.com>\r\nBcc: a@b.c', "notificaciones@prendo.com.co")
    assert "\n" not in header and "\r" not in header
    assert header.endswith("<notificaciones@prendo.com.co>")
    assert header.count("<") == 1


def test_company_name_is_escaped_in_html() -> None:
    brand = templates.Branding(company_name="<script>alert(1)</script>")
    rendered = templates.render(
        "company_weekly_digest", {"day": "2030-09-02", "kind": "weekly"}, brand
    )
    assert "<script>" not in rendered.html


def test_digest_render_lists_ready_contracts_and_flags_thresholds() -> None:
    payload = {
        "kind": "daily",
        "day": "2030-09-03",
        "period": {"from": "2030-09-02", "to": "2030-09-02"},
        "activity": {
            "contracts_created": 1,
            "contracts_amount": "500000.00",
            "payments": 0,
            "payments_amount": "0",
            "sales": 0,
            "sales_amount": "0",
            "sales_voided": 0,
        },
        "ready_for_auction": {
            "total": 1,
            "new": 1,
            "contracts": [{"number": 7, "extension_ends_at": "2030-09-02", "new": True}],
        },
        "cash_differences": [
            {
                "session_date": "2030-09-02",
                "difference": "-20000.00",
                "reason": "faltó",
                "above_threshold": False,
            }
        ],
        "subscription": {"expires_at": "2030-09-10", "days_left": 7},
    }
    rendered = templates.render("company_daily_digest", payload, BRAND)
    assert rendered.from_name == "Prendo"
    assert "Resumen diario · LA GRAN LEGAL" in rendered.subject
    assert "Contrato #7" in rendered.text
    assert "faltante de $20.000" in rendered.text
    assert "sobre el umbral" not in rendered.text
    assert "Vence en 7 días" in rendered.text
