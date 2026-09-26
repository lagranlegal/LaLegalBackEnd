"""Plantillas de correo (docs/NOTIFICACIONES.md §4.4, §8, §9.1). El test mira
el RENDER, no la plantilla: un test sobre la plantilla no cubre el payload."""

from app.modules.notifications import templates

BRAND = templates.Branding(
    company_name="LA GRAN LEGAL",
    contact_email="contacto@lagranlegal.example",
    contact_phone="300 000 0000",
    footer_note="Gracias por preferirnos",
)

#: Todo correo al cliente lleva salida (§9.2-e); el despachador la arma al
#: enviar. Sin ella la plantilla no redacta (ver el test de abajo).
UNSUB = "https://app.example.com/baja/AbC.dEf"


def test_money_is_colombian() -> None:
    assert templates.money("1234567.00") == "$1.234.567"
    assert templates.money("1500.50") == "$1.500,50"
    assert templates.money("-18000") == "-$18.000"


def test_customer_render_never_leaks_document_or_item() -> None:
    payload = {
        "contract_number": 42,
        "extension_ends_at": "2030-09-01",
        "first_name": "Juan Pérez",
        "unsubscribe_url": UNSUB,
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
        "auction_ready_customer",
        {"contract_number": 1, "extension_ends_at": "2030-09-01", "unsubscribe_url": UNSUB},
        BRAND,
    )
    assert rendered.from_name == "LA GRAN LEGAL (vía Prendo)"
    assert rendered.subject.startswith("LA GRAN LEGAL · ")
    assert "Prendo" not in rendered.subject
    assert rendered.reply_to == "contacto@lagranlegal.example"


def test_customer_header_is_the_company_not_prendo() -> None:
    """§8: el autor del aviso es la empresa. La marca del encabezado es la
    suya; Prendo aparece solo en «Enviado por Prendo en nombre de …»."""
    rendered = templates.render(
        "auction_ready_customer",
        {"contract_number": 1, "extension_ends_at": "2030-09-01", "unsubscribe_url": UNSUB},
        BRAND,
    )
    assert ">LA GRAN LEGAL</p>" in rendered.html
    assert ">Prendo</p>" not in rendered.html
    assert "Enviado por Prendo en nombre de LA GRAN LEGAL." in rendered.html
    assert "Enviado por Prendo en nombre de LA GRAN LEGAL." in rendered.text
    # La firma de la empresa (teléfono, nota) queda a la vista.
    assert "Tel. 300 000 0000" in rendered.html


def test_customer_values_are_escaped_in_html() -> None:
    brand = templates.Branding(
        company_name="<b>X</b>", contact_phone="<i>1</i>", footer_note="<u>n</u>"
    )
    rendered = templates.render(
        "auction_ready_customer",
        {
            "contract_number": "<s>1</s>",
            "extension_ends_at": "2030-09-01",
            "first_name": "<script>alert(1)</script>",
            "unsubscribe_url": UNSUB + '"><script>',
        },
        brand,
    )
    for tag in ("<b>", "<i>", "<u>", "<s>", "<script>"):
        assert tag not in rendered.html, tag


def test_no_reply_to_when_company_has_no_contact_email() -> None:
    brand = templates.Branding(company_name="X")
    rendered = templates.render(
        "auction_ready_customer",
        {"contract_number": 1, "extension_ends_at": "2030-09-01", "unsubscribe_url": UNSUB},
        brand,
    )
    assert rendered.reply_to is None


def test_customer_mail_carries_the_unsubscribe_page_link() -> None:
    """§9.2-e: salida en TODO correo al cliente, también en los de servicio,
    en el HTML y en el texto plano. Y es la página, no la API."""
    rendered = templates.render(
        "installment_due_soon",
        {
            "due_date": "2030-09-05",
            "contracts": [{"number": 1, "amount": "50000"}],
            "unsubscribe_url": UNSUB,
        },
        BRAND,
    )
    assert f'href="{UNSUB}"' in rendered.html
    assert UNSUB in rendered.text
    assert "Darse de baja" in rendered.html


def test_customer_mail_without_unsubscribe_link_is_not_written() -> None:
    import pytest

    base = {"contract_number": 1, "extension_ends_at": "2030-09-01"}
    for bad in (
        None,
        "",
        "https://api.example.com/api/v1/public/unsubscribe/x",
        "https://app.example.com/otra-cosa",
    ):
        with pytest.raises(ValueError, match="baja"):
            templates.render("auction_ready_customer", {**base, "unsubscribe_url": bad}, BRAND)


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
    # En el HTML el monto va en su propia celda, alineado a la derecha.
    assert 'align="right"' in rendered.html
    assert ">$20.000</td>" in rendered.html


# ------------------------------------ transaccionales al cliente (fases 4 y 6) ----


def _render(event_type: str, **payload: object) -> str:
    return templates.render(
        event_type, {"unsubscribe_url": UNSUB, "first_name": "Juana", **payload}, BRAND
    ).text


def test_paid_off_says_what_was_paid_because_it_replaces_the_receipt() -> None:
    """§18.1-3: el abono que salda el contrato manda el paz y salvo y NO además
    el comprobante. Si el paz y salvo no dijera lo pagado, ese abono sería el
    único sin comprobante."""
    text = _render(
        "contract_paid_off",
        contract_number=7,
        paid_on="2030-09-03",
        amount="1050000.00",
        receipt_number=31,
    )
    assert "Recibimos $1.050.000 (recibo #31)." in text
    assert "quedó saldado el 3 de septiembre de 2030. No nos debe nada." in text


def test_extension_only_promises_the_date_did_not_move_when_it_did_not() -> None:
    """00053: con `keep_anchor` la fecha de cobro no se mueve. Con las
    políticas viejas SÍ se mueve, y el correo no puede prometer lo contrario."""
    base = {
        "contract_number": 7,
        "new_contract_number": 9,
        "extension_amount": "300000.00",
        "capital_balance": "1300000.00",
        "next_due_date": "2030-10-01",
    }
    kept = _render("loan_extended", anchor_kept=True, **base)
    moved = _render("loan_extended", anchor_kept=False, **base)
    for text in (kept, moved):
        assert "#7 fue reemplazado por el #9" in text
        assert "$300.000" in text and "$1.300.000" in text
        assert "1 de octubre de 2030" in text
    assert "no cambió" in kept
    assert "no cambió" not in moved


def test_reversal_tells_void_from_return_and_how_it_was_settled() -> None:
    void = _render("sale_reversed", kind="void", sale_number=12, amount="1000000.00")
    cash = _render(
        "sale_reversed",
        kind="return",
        sale_number=12,
        return_number=3,
        amount="450000.00",
        settlement_method="cash",
    )
    note = _render(
        "sale_reversed",
        kind="return",
        sale_number=12,
        return_number=3,
        amount="450000.00",
        settlement_method="credit_note",
        credit_note_number=5,
    )
    assert "anulación de su compra #12 por $1.000.000" in void
    assert "devolución #3 de su compra #12" in cash and "Le devolvimos $450.000." in cash
    assert "nota crédito #5 por $450.000" in note and "Le devolvimos" not in note


def test_credit_note_names_the_sale_it_came_from() -> None:
    text = _render("credit_note_issued", credit_note_number=5, amount="450000.00", sale_number=12)
    assert "Por la devolución de su compra #12 se emitió la nota crédito #5 por $450.000." in text


def test_no_transactional_leaks_a_reason_or_an_item() -> None:
    """El motivo de una anulación es una nota interna; las líneas de la venta
    son los artículos. Aunque un productor los metiera, la plantilla no los lee."""
    text = _render(
        "sale_reversed",
        kind="void",
        sale_number=12,
        amount="1000000.00",
        reason="Cobro doble del cajero",
        lines=[{"description": "Cadena de oro"}],
    )
    assert "Cobro doble" not in text
    assert "Cadena" not in text


def test_a_mixed_return_names_the_note_and_the_cash_in_both_templates() -> None:
    """F21-37: una devolución de 800.000 sobre una venta pagada con 500.000 de
    nota se liquida con una nota nueva de 500.000 y 300.000 en efectivo. Sale
    UN aviso (el de la nota, o el de devolución si la nota está apagada), y
    cualquiera de los dos dice los dos montos — nunca los 800.000 como si
    todo hubiera salido del cajón o todo fuera nota."""
    mixed = {
        "kind": "return",
        "sale_number": 12,
        "return_number": 3,
        "amount": "800000.00",
        "settlement_method": "cash",
        "credit_note_number": 5,
        "credit_note_amount": "500000.00",
        "refunded_amount": "300000.00",
    }
    note = _render("credit_note_issued", **mixed)
    reversal = _render("sale_reversed", **mixed)
    for text in (note, reversal):
        assert "nota crédito #5 por $500.000" in text
        assert "$300.000" in text
        assert "$800.000" not in text
    assert "Le devolvimos $300.000 en efectivo" in reversal


def test_a_note_only_return_keeps_its_old_wording() -> None:
    """Los avisos ya registrados antes de F21-37 no traen los montos
    partidos: la plantilla cae al `amount` de siempre."""
    text = _render("credit_note_issued", credit_note_number=5, amount="450000.00", sale_number=12)
    assert "nota crédito #5 por $450.000." in text
    assert "efectivo" not in text


# ------------------------------------------ alertas a la empresa (A1–A4, §19) ----

_ALERT_BASE = {"actor_name": "Cajero Díaz", "at": "2030-09-01T23:05-05:00"}


def test_alert_is_from_prendo_and_names_the_company_in_the_subject() -> None:
    rendered = templates.render(
        "alert_sale_voided",
        {
            **_ALERT_BASE,
            "sale_number": 12,
            "total": "800000.00",
            "refunded_amount": "800000.00",
            "sold_at": "2030-09-01",
            "reason": "Cobro doble",
        },
        BRAND,
    )
    # §8: el destinatario es un usuario de Prendo; la empresa, en el asunto.
    assert rendered.from_name == "Prendo"
    assert rendered.reply_to is None
    assert rendered.subject == "Alerta · LA GRAN LEGAL · Venta #12 anulada"
    assert "Cajero Díaz anuló la venta #12." in rendered.text
    assert "1 sep 2030, 23:05" in rendered.text
    assert "«Cobro doble»" in rendered.text
    # Sin `Reply-To` ni teléfono del inquilino: no es un correo de la empresa.
    assert "300 000 0000" not in rendered.html


def test_alert_reason_is_escaped_in_html() -> None:
    rendered = templates.render(
        "alert_capital_withdrawal",
        {
            **_ALERT_BASE,
            "movement_number": 3,
            "amount": "1000000.00",
            "account_name": "Caja <principal>",
            "kind": "profit",
            "movement_date": "2030-09-01",
            "reason": "<script>alert(1)</script>",
        },
        BRAND,
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "Caja &lt;principal&gt;" in rendered.html
    assert "Reparto de utilidad" in rendered.text


def test_discount_alert_tells_sale_from_payment_and_shows_a_nonzero_threshold() -> None:
    sale = templates.render(
        "alert_discount",
        {
            **_ALERT_BASE,
            "kind": "sale",
            "sale_number": 7,
            "subtotal": "1000000.00",
            "discount_amount": "100000.00",
            "total": "900000.00",
            "reason": "Frecuente",
            "threshold": "0.00",
        },
        BRAND,
    )
    assert sale.subject.endswith("Descuento de $100.000 en la venta #7")
    # Con umbral 0 no se muestra: «umbral $0» no le dice nada a nadie.
    assert "Umbral" not in sale.text
    payment = templates.render(
        "alert_discount",
        {
            **_ALERT_BASE,
            "kind": "payment",
            "contract_number": 40,
            "receipt_number": 91,
            "interest_amount": "50000.00",
            "discount_amount": "20000.00",
            "total": "30000.00",
            "reason": "Puntual",
            "threshold": "10000.00",
        },
        BRAND,
    )
    assert payment.subject.endswith("Descuento de $20.000 en un abono al contrato #40")
    assert "Recibo: #91" in payment.text
    assert "Umbral de alerta: $10.000" in payment.text


def test_reopen_alert_says_what_the_undone_close_said() -> None:
    rendered = templates.render(
        "alert_cash_reopened",
        {
            **_ALERT_BASE,
            "session_date": "2030-09-01",
            "closed_at": "2030-09-01T19:02-05:00",
            "counted_cash": "480000.00",
            "difference": "-20000.00",
            "reason": "Faltó un gasto",
        },
        BRAND,
    )
    assert rendered.subject.endswith("Caja del 1 sep 2030 reabierta")
    assert "Se había cerrado el: 1 sep 2030, 19:02" in rendered.text
    assert "Faltante de ese cierre (se revierte): $20.000" in rendered.text
    assert "Contado en ese cierre: $480.000" in rendered.text


def test_alert_never_renders_customer_data_a_producer_slipped_in() -> None:
    rendered = templates.render(
        "alert_sale_voided",
        {
            **_ALERT_BASE,
            "sale_number": 1,
            "total": "10.00",
            "reason": "x",
            "customer_name": "Juana Pérez",
            "doc_number": "1032456789",
            "item_description": "Cadena de oro 18k",
        },
        BRAND,
    )
    for body in (rendered.html, rendered.text, rendered.subject):
        assert "Juana" not in body
        assert "1032456789" not in body
        assert "Cadena" not in body
