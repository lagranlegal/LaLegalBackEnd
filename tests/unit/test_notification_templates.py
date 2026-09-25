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
