"""Plantillas de correo — en código, en español, NO editables por el inquilino.

docs/NOTIFICACIONES.md §4.4: la entregabilidad de `prendo.com.co` es un recurso
compartido, así que el cuerpo es de la plataforma. Lo que sí es de la empresa
(§8): su nombre, su teléfono, su `contact_email` como `Reply-To` y su
`footer_note`.

Puro: recibe el `payload` del evento y la marca de la empresa, devuelve el
correo listo. Todo valor que venga de datos pasa por `html.escape`.

**§9.1 — lo que NUNCA va en un cuerpo:** cédula, descripción de la prenda,
dirección, teléfono del cliente, fotos, adjuntos. Las plantillas solo leen
del payload las claves de abajo; aunque un productor metiera de más, no se
renderiza. Un test lo verifica sobre el render, no sobre la plantilla.
"""

import html
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.notifications import catalog

_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

PLATFORM_NAME = "Prendo"


@dataclass(frozen=True)
class Branding:
    company_name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    footer_note: str | None = None


@dataclass(frozen=True)
class RenderedEmail:
    from_name: str
    subject: str
    html: str
    text: str
    reply_to: str | None


# ---------------------------------------------------------------- formato ----
def money(value: Any) -> str:
    """Pesos colombianos: `$1.234.567`, y los centavos solo si existen."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount).quantize(Decimal("0.01"))
    whole, cents = divmod(amount, 1)
    grouped = f"{int(whole):,}".replace(",", ".")
    if cents:
        return f"{sign}${grouped},{int(cents * 100):02d}"
    return f"{sign}${grouped}"


def long_date(value: Any) -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value))
    return f"{d.day} de {_MONTHS[d.month - 1]} de {d.year}"


def short_date(value: Any) -> str:
    d = value if isinstance(value, date) else date.fromisoformat(str(value))
    return f"{d.day} {_MONTHS[d.month - 1][:3]} {d.year}"


def _clean_display_name(name: str) -> str:
    """Un nombre de empresa no puede inyectar cabeceras ni romper el `From`."""
    return " ".join(name.replace('"', "").replace("<", "").replace(">", "").split())


def from_header(display_name: str, address: str) -> str:
    return f'"{_clean_display_name(display_name)}" <{address}>'


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _layout(*, title: str, blocks_html: list[str], footer_lines: list[str]) -> str:
    body = "\n".join(blocks_html)
    footer = "<br>".join(_esc(line) for line in footer_lines)
    return (
        "<!doctype html>\n"
        '<html lang="es"><body style="margin:0;padding:0;background:#f4f4f5;'
        'font-family:Arial,sans-serif;color:#18181b">\n'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td align="center" style="padding:24px 12px">\n'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        'style="max-width:600px;width:100%;background:#ffffff;border-radius:8px">\n'
        '<tr><td style="padding:24px 24px 8px 24px">'
        f'<h1 style="margin:0;font-size:20px">{_esc(title)}</h1></td></tr>\n'
        '<tr><td style="padding:8px 24px 16px 24px;font-size:14px;line-height:1.5">\n'
        f"{body}\n"
        "</td></tr>\n"
        '<tr><td style="padding:16px 24px 24px 24px;font-size:12px;color:#71717a;'
        f'border-top:1px solid #e4e4e7">{footer}</td></tr>\n'
        "</table></td></tr></table></body></html>"
    )


def _p(text: str) -> str:
    return f'<p style="margin:0 0 12px 0">{_esc(text)}</p>'


def _section(title: str, rows: list[str], *, note: str | None = None) -> str:
    items = "".join(f'<li style="margin:0 0 4px 0">{_esc(r)}</li>' for r in rows)
    note_html = f'<p style="margin:0 0 8px 0;color:#52525b">{_esc(note)}</p>' if note else ""
    return (
        f'<h2 style="margin:20px 0 8px 0;font-size:16px">{_esc(title)}</h2>'
        f'{note_html}<ul style="margin:0 0 8px 0;padding-left:20px">{items}</ul>'
    )


# ------------------------------------------------------------ resumen (E*) ----
_LIST_CAP = 30


def _capped(rows: list[str], total: int) -> list[str]:
    if total > len(rows):
        return [*rows, f"… y {total - len(rows)} más en la aplicación."]
    return rows


def digest_sections(payload: dict[str, Any]) -> list[tuple[str, list[str], str | None]]:
    """Secciones del resumen en orden de urgencia: (título, renglones, nota)."""
    sections: list[tuple[str, list[str], str | None]] = []

    sub = payload.get("subscription")
    if sub:
        days = int(sub["days_left"])
        when = "mañana" if days == 1 else f"en {days} días"
        sections.append(
            (
                "Su suscripción a Prendo vence pronto",
                [
                    f"Vence {when}, el {long_date(sub['expires_at'])}. "
                    "Al vencer se bloquea el acceso de todos los usuarios; "
                    "los datos no se borran."
                ],
                None,
            )
        )

    ready = payload.get("ready_for_auction") or {}
    if ready.get("total"):
        rows = [
            f"Contrato #{c['number']} — prórroga vencida el {short_date(c['extension_ends_at'])}"
            + (" (nuevo)" if c.get("new") else "")
            for c in ready.get("contracts", [])
        ]
        new = int(ready.get("new", 0))
        note = f"{ready['total']} contrato(s) ya se pueden rematar" + (
            f"; {new} nuevo(s) desde el último resumen." if new else "."
        )
        sections.append(("Listos para remate", _capped(rows, int(ready["total"])), note))

    unclosed = payload.get("unclosed_cash") or []
    if unclosed:
        sections.append(
            (
                "Caja sin cerrar",
                [f"La caja del {long_date(s['session_date'])} sigue abierta." for s in unclosed],
                None,
            )
        )

    diffs = payload.get("cash_differences") or []
    if diffs:
        rows = []
        for d in diffs:
            kind = "sobrante" if Decimal(str(d["difference"])) > 0 else "faltante"
            flag = " ⚠ sobre el umbral" if d.get("above_threshold") else ""
            reason = f" — «{d['reason']}»" if d.get("reason") else ""
            rows.append(
                f"Cierre del {short_date(d['session_date'])}: {kind} de "
                f"{money(abs(Decimal(str(d['difference']))))}{reason}{flag}"
            )
        sections.append(("Descuadres de arqueo", rows, None))

    discounts = payload.get("discounts") or []
    if discounts:
        rows = []
        for d in discounts:
            what = "Venta" if d["kind"] == "sale" else "Abono (recibo)"
            flag = " ⚠ sobre el umbral" if d.get("above_threshold") else ""
            rows.append(f"{what} #{d['number']}: descuento de {money(d['amount'])}{flag}")
        sections.append(("Descuentos concedidos", rows, None))

    arrears = payload.get("entered_arrears") or []
    if arrears:
        sections.append(
            (
                "Entraron en mora",
                _capped(
                    [
                        f"Contrato #{c['number']} (desde el {short_date(c['since'])})"
                        for c in arrears
                    ],
                    int(payload.get("entered_arrears_total", len(arrears))),
                ),
                None,
            )
        )
    extension = payload.get("entered_extension") or []
    if extension:
        sections.append(
            (
                "Entraron en prórroga",
                _capped(
                    [
                        f"Contrato #{c['number']} — la prórroga vence el "
                        f"{short_date(c['extension_ends_at'])}"
                        for c in extension
                    ],
                    int(payload.get("entered_extension_total", len(extension))),
                ),
                None,
            )
        )

    act = payload.get("activity") or {}
    if act:
        period = payload.get("period") or {}
        label = (
            f"del {short_date(period['from'])} al {short_date(period['to'])}"
            if period and period.get("from") != period.get("to")
            else (f"del {short_date(period['to'])}" if period else "")
        )
        sections.append(
            (
                f"Movimiento {label}".strip(),
                [
                    f"Contratos nuevos: {act['contracts_created']} "
                    f"({money(act['contracts_amount'])} prestados)",
                    f"Abonos: {act['payments']} ({money(act['payments_amount'])})",
                    f"Ventas: {act['sales']} ({money(act['sales_amount'])})"
                    + (f"; anuladas: {act['sales_voided']}" if act.get("sales_voided") else ""),
                ],
                None,
            )
        )

    stale = payload.get("stale_inventory")
    if stale and stale.get("product_count"):
        sections.append(
            (
                "Mercancía sin rotación",
                [
                    f"{stale['product_count']} producto(s) llevan {stale['threshold_days']} días "
                    f"o más en vitrina, con {money(stale['total_cost_value'])} al costo."
                ],
                None,
            )
        )
    payables = payload.get("payables")
    if payables and Decimal(str(payables.get("total", "0"))) > 0:
        sections.append(
            (
                "Cuentas por pagar a proveedores",
                [
                    f"Total: {money(payables['total'])}; con más de 60 días: "
                    f"{money(payables['days_over_60'])}."
                ],
                None,
            )
        )

    dead = int(payload.get("dead_deliveries", 0))
    if dead:
        sections.append(
            ("Avisos que no se pudieron enviar", [f"{dead} correo(s) fallaron 3 veces."], None)
        )
    return sections


def render_digest(event_type: str, payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    weekly = event_type == catalog.WEEKLY_DIGEST
    day = payload["day"]
    kind = "Resumen semanal" if weekly else "Resumen diario"
    subject = f"{kind} · {branding.company_name} · {short_date(day)}"
    sections = digest_sections(payload)
    intro = (
        f"Así va {branding.company_name} esta semana."
        if weekly
        else f"Lo que pasó en {branding.company_name} y lo que necesita atención."
    )
    if not sections:
        intro += " Todo en orden: no hay alertas ni movimiento que reportar."
    blocks = [_p(intro)] + [_section(t, rows, note=n) for t, rows, n in sections]
    footer = [
        f"Lo recibe porque su rol en {branding.company_name} tiene el permiso "
        "«Recibir el resumen». Quien administra la empresa puede quitarlo o apagar "
        "el resumen en Configuración.",
        f"{PLATFORM_NAME} · prendo.com.co",
    ]
    text_lines = [intro, ""]
    for title, rows, note in sections:
        text_lines.append(title.upper())
        if note:
            text_lines.append(note)
        text_lines.extend(f"- {r}" for r in rows)
        text_lines.append("")
    text_lines.extend(footer)
    return RenderedEmail(
        # §8: el destinatario es un usuario de Prendo; la contraparte es Prendo.
        from_name=PLATFORM_NAME,
        subject=subject,
        html=_layout(title=f"{kind} — {long_date(day)}", blocks_html=blocks, footer_lines=footer),
        text="\n".join(text_lines),
        reply_to=None,
    )


# ------------------------------------------------------- avisos al cliente ----
def _first_name(payload: dict[str, Any]) -> str:
    name = str(payload.get("first_name") or "").strip()
    return name.split()[0] if name else ""


def _customer_lines(event_type: str, p: dict[str, Any]) -> tuple[str, list[str]]:
    """(asunto sin el prefijo de la empresa, párrafos). Solo lee claves conocidas."""
    n = p.get("contract_number")
    if event_type == "contract_created":
        return f"Su contrato #{n}", [
            f"Registramos su contrato #{n} por {money(p['principal'])}.",
            f"Su próxima cuota vence el {long_date(p['next_due_date'])}.",
        ]
    if event_type == "payment_registered":
        return f"Recibimos su abono al contrato #{n}", [
            f"Recibimos {money(p['amount'])} (recibo #{p['receipt_number']}).",
            f"Sus intereses quedaron cubiertos hasta el {long_date(p['interest_paid_until'])}.",
            f"Saldo de capital: {money(p['capital_balance'])}.",
        ]
    if event_type == "contract_paid_off":
        return f"Paz y salvo del contrato #{n}", [
            f"Su contrato #{n} quedó saldado el {long_date(p['paid_on'])}. No nos debe nada.",
            "Guarde este correo como constancia.",
        ]
    if event_type == "loan_extended":
        return f"Su préstamo fue ampliado: nuevo contrato #{p['new_contract_number']}", [
            f"Su contrato #{n} fue reemplazado por el #{p['new_contract_number']}, "
            f"con un capital de {money(p['capital_balance'])}.",
            "Sus abonos de ahora en adelante van al contrato nuevo. La fecha de cobro no cambió.",
        ]
    if event_type == "credit_note_issued":
        return "Tiene un saldo a favor", [
            f"Se emitió la nota crédito #{p['credit_note_number']} por {money(p['amount'])}.",
        ]
    if event_type == "sale_receipt":
        return f"Comprobante de su compra #{p['sale_number']}", [
            f"Gracias por su compra #{p['sale_number']} por {money(p['total'])}.",
        ]
    if event_type == "sale_reversed":
        return f"Su compra #{p['sale_number']} fue anulada o devuelta", [
            f"Registramos la anulación o devolución de su compra #{p['sale_number']} "
            f"por {money(p['amount'])}.",
        ]
    if event_type == "installment_due_soon":
        contracts = p.get("contracts") or []
        return f"Su cuota vence el {long_date(p['due_date'])}", [
            f"Le recordamos que el {long_date(p['due_date'])} vence la cuota de:",
            *[f"Contrato #{c['number']}: {money(c['amount'])}" for c in contracts],
        ]
    if event_type == "installment_overdue":
        return f"Su contrato #{n} tiene una cuota vencida", [
            f"La cuota de su contrato #{n} venció el {long_date(p['due_date'])}.",
        ]
    if event_type == "extension_started":
        return f"Su contrato #{n} entró en prórroga", [
            f"Su contrato #{n} entró en prórroga. Tiene hasta el "
            f"{long_date(p['extension_ends_at'])} para ponerse al día.",
        ]
    if event_type == "extension_ending_soon":
        return f"La prórroga de su contrato #{n} vence pronto", [
            f"La prórroga de su contrato #{n} vence el {long_date(p['extension_ends_at'])}.",
        ]
    if event_type == catalog.AUCTION_READY_CUSTOMER:
        return f"Su contrato #{n} está vencido", [
            f"La prórroga de su contrato #{n} venció el {long_date(p['extension_ends_at'])} "
            "sin que se registrara el pago.",
            "Comuníquese con nosotros lo antes posible.",
        ]
    raise ValueError(f"Sin plantilla para el evento {event_type!r}")


def render_customer(event_type: str, payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    subject_tail, paragraphs = _customer_lines(event_type, payload)
    first = _first_name(payload)
    greeting = f"Hola, {first}:" if first else "Hola:"
    contact = (
        f"Tel. {branding.contact_phone}"
        if branding.contact_phone
        else (branding.contact_email or "")
    )
    footer = [
        " · ".join(x for x in (branding.company_name, contact, branding.footer_note or "") if x),
        f"Enviado por {PLATFORM_NAME} en nombre de {branding.company_name}. "
        f"Si no desea recibir estos avisos, avísele a {branding.company_name}.",
    ]
    blocks = [_p(greeting)] + [_p(line) for line in paragraphs]
    return RenderedEmail(
        # §8: el remitente es la plataforma, el autor es la empresa.
        from_name=f"{branding.company_name} (vía {PLATFORM_NAME})",
        # §8: el asunto nunca dice Prendo.
        subject=f"{branding.company_name} · {subject_tail}",
        html=_layout(title=subject_tail, blocks_html=blocks, footer_lines=footer),
        text="\n\n".join([greeting, *paragraphs, *footer]),
        reply_to=branding.contact_email or None,
    )


# ------------------------------------------------ de la plataforma (P1) ----

#: Lo único que puede llevar el enlace de un correo de invitación. Es la forma
#: que arma `identity/auth_admin.py::_app_link`: la página de la app canjea el
#: `token_hash` por POST (`verifyOtp`). Cualquier otra cosa —el `action_link`
#: de GoTrue (`/auth/v1/verify?token=…`) o un `#access_token=`— es un token que
#: se quema con un GET, y los escáneres de correo hacen GET sobre cada enlace
#: apenas llega (bug reproducido el 03/09/2026).
_SAFE_INVITE_PATH = "/auth/callback?token_hash="


def _check_invite_link(link: str) -> str:
    if _SAFE_INVITE_PATH not in link or "/auth/v1/verify" in link or "#" in link:
        raise ValueError(
            "El enlace de la invitación no es el de la app (/auth/callback?token_hash=…): "
            "un correo nunca lleva un token canjeable por GET."
        )
    return link


def render_user_invitation(payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    """P1 · Invitación de usuario (docs/NOTIFICACIONES.md §2.6, §8, §16).

    **El remitente es Prendo, sin «(vía …)» y sin `Reply-To`** (§8): la
    contraparte de alguien que va a ser usuario de Prendo es Prendo. El nombre
    de la empresa va en el asunto y en el cuerpo porque es lo que la persona
    reconoce — «me invitaron a la compraventa donde trabajo» —, pero ni su
    teléfono ni su `footer_note`: el correo no es de la empresa.

    Solo lee `invitee_name` e `invite_link`. El enlace NO viene del payload
    guardado: lo pone el despachador en memoria al enviar (§16), porque es una
    credencial que vence en minutos.
    """
    link = _check_invite_link(str(payload["invite_link"]))
    first = _first_name({"first_name": payload.get("invitee_name")})
    company = branding.company_name
    greeting = f"Hola, {first}:" if first else "Hola:"
    subject = f"Invitación a {company} en {PLATFORM_NAME}"
    paragraphs = [
        f"{company} lo invitó a usar {PLATFORM_NAME}, el sistema con el que lleva sus "
        "contratos, su inventario y su caja.",
        "Para activar su cuenta, abra el enlace y cree su contraseña:",
    ]
    after = [
        "El enlace sirve una sola vez y vence en poco tiempo. Si ya no funciona, pídale "
        f"a quien lo invitó en {company} que le genere uno nuevo.",
        "Si no esperaba esta invitación, ignore este correo: sin contraseña nadie puede "
        "entrar a la cuenta.",
    ]
    footer = [f"{PLATFORM_NAME} · prendo.com.co"]
    button = (
        '<p style="margin:16px 0 20px 0">'
        f'<a href="{_esc(link)}" style="display:inline-block;background:#18181b;'
        "color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:6px;"
        'font-weight:bold">Crear mi contraseña</a></p>'
        '<p style="margin:0 0 12px 0;font-size:12px;color:#52525b">'
        f"Si el botón no abre, copie esta dirección en el navegador:<br>{_esc(link)}</p>"
    )
    blocks = [_p(greeting), *[_p(x) for x in paragraphs], button, *[_p(x) for x in after]]
    return RenderedEmail(
        from_name=PLATFORM_NAME,
        subject=subject,
        html=_layout(title=f"Lo invitaron a {company}", blocks_html=blocks, footer_lines=footer),
        text="\n\n".join([greeting, *paragraphs, link, *after, *footer]),
        reply_to=None,
    )


def render(event_type: str, payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    et = catalog.get(event_type)
    if et.family == "digest":
        return render_digest(event_type, payload, branding)
    if et.audience == "customer":
        return render_customer(event_type, payload, branding)
    if event_type == "user_invitation":
        return render_user_invitation(payload, branding)
    raise ValueError(f"El evento {event_type!r} todavía no tiene plantilla (fase posterior).")
