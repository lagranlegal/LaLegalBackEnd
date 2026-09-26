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
from datetime import date, datetime
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


# ------------------------------------------------------------------ molde ----
# El lenguaje visual es el de las plantillas de Supabase Auth que están en uso
# (`frontend-starter/docs/correo-invitacion.html` y `correo-recuperacion.html`),
# y las razones son las de su cabecera: tablas y estilos EN LÍNEA (Outlook y
# Gmail ignoran hojas de estilo y rompen con flex/grid), 560 px como tope y una sola
# columna (se lee en móvil sin media queries), el botón es una tabla con fondo
# (un <button> se ve como texto), el enlace se repite como texto, y ninguna
# imagen externa (se bloquean por defecto, y no hay píxel de apertura).
#
# Los colores son los de ese molde, con los contrastes medidos allá (WCAG AA):
# sobre el beige nunca va `_MUTED` (4.39:1), va `_BODY`.
_BG = "#f1ebdd"  # fondo del correo y de los recuadros de aviso
_BORDER = "#ddd7c9"
_BRAND = "#7a5a1c"  # la marca del encabezado y los enlaces
_TITLE = "#24211c"
_BODY = "#4b463d"
_MUTED = "#716c63"  # secundario, solo sobre blanco
_GOLD = "#c99a3d"  # el botón, con texto `_TITLE` (blanco daría 2.57:1)
_FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

#: La línea debajo de la tarjeta en los correos de la plataforma: la misma de
#: las plantillas de Supabase.
PLATFORM_TAGLINE = f"{PLATFORM_NAME} — el sistema de gestión para compraventas"


def _tr(inner: str, *, top: int = 24) -> str:
    """Una franja de la tarjeta. Cada bloque va en su propia fila, como en el
    molde: el espaciado vertical lo da el `padding`, que es lo único que todos
    los clientes respetan igual."""
    return f'<tr><td style="padding:{top}px 32px 0 32px;">{inner}</td></tr>'


def _layout(
    *,
    brand_label: str,
    title: str,
    rows_html: list[str],
    footer_html: list[str],
    meta: str | None = None,
    tagline: str | None = None,
) -> str:
    """El marco común. `brand_label`, `title`, `meta` y `tagline` son texto y se
    escapan acá; `rows_html` y `footer_html` ya vienen escapados (llevan
    enlaces, y un enlace no se puede escapar entero).

    `brand_label` es la marca del encabezado — «Prendo» en los correos de la
    plataforma, el nombre de la empresa en los del cliente (§8)."""
    meta_html = (
        f'<p style="margin:8px 0 0 0;font-size:14px;line-height:1.5;color:{_MUTED};">'
        f"{_esc(meta)}</p>"
        if meta
        else ""
    )
    footer = "".join(
        f'<p style="margin:{0 if i == 0 else 8}px 0 0 0;font-size:12px;line-height:1.6;'
        f'color:{_MUTED};">{line}</p>'
        for i, line in enumerate(footer_html)
    )
    tagline_html = (
        f'<p style="margin:16px 0 0 0;font-size:12px;color:{_BODY};">{_esc(tagline)}</p>'
        if tagline
        else ""
    )
    return (
        "<!doctype html>\n"
        '<html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(title)}</title></head>\n"
        f'<body style="margin:0;padding:0;background-color:{_BG};">\n'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{_BG};margin:0;padding:32px 12px;font-family:{_FONT};">'
        '<tr><td align="center">\n'
        # 100 % con tope de 560, y no 560 con `max-width:100%` como en la
        # plantilla de Supabase: una tabla con ancho fijo no se encoge, y a
        # 360 px esa desborda (medido: 592 px de ancho). Outlook de escritorio
        # ignora `max-width`, así que para él va una tabla fantasma de 560.
        '<!--[if mso]><table role="presentation" width="560" cellpadding="0" '
        'cellspacing="0" align="center"><tr><td><![endif]-->\n'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;max-width:560px;background-color:#ffffff;border-radius:14px;'
        f'border:1px solid {_BORDER};overflow:hidden;">\n'
        # Encabezado
        '<tr><td style="padding:28px 32px 0 32px;">'
        '<p style="margin:0;font-size:13px;font-weight:600;letter-spacing:0.08em;'
        f'text-transform:uppercase;color:{_BRAND};">{_esc(brand_label)}</p></td></tr>\n'
        # Título
        '<tr><td style="padding:20px 32px 0 32px;">'
        '<h1 style="margin:0;font-size:26px;line-height:1.25;'
        f'color:{_TITLE};font-weight:600;">{_esc(title)}</h1>{meta_html}</td></tr>\n'
        + "\n".join(rows_html)
        + "\n"
        # Pie
        '<tr><td style="padding:24px 32px 28px 32px;">'
        f'<div style="border-top:1px solid {_BORDER};padding-top:16px;">{footer}</div>'
        "</td></tr>\n"
        "</table>\n"
        "<!--[if mso]></td></tr></table><![endif]-->\n"
        f"{tagline_html}\n"
        "</td></tr></table>\n</body></html>"
    )


def _p(text: str, *, last: bool = False) -> str:
    """Un párrafo del cuerpo; escapa. `last` le quita el margen de abajo."""
    return (
        f'<p style="margin:0 0 {0 if last else 16}px 0;font-size:16px;line-height:1.6;'
        f'color:{_BODY};">{_esc(text)}</p>'
    )


def _paragraphs(texts: list[str]) -> str:
    return "".join(_p(t, last=i == len(texts) - 1) for i, t in enumerate(texts))


def _button(url: str, label: str) -> str:
    """Píldora dorada hecha con una tabla (un <button> no se ve en un correo)."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
        f'<td style="background-color:{_GOLD};border-radius:9999px;">'
        f'<a href="{_esc(url)}" style="display:inline-block;padding:14px 32px;font-size:16px;'
        f'font-weight:600;color:{_TITLE};text-decoration:none;">{_esc(label)}</a>'
        "</td></tr></table>"
    )


def _link_fallback(url: str) -> str:
    """El enlace repetido como texto: si el botón no se ve, igual se entra."""
    return (
        f'<p style="margin:0 0 6px 0;font-size:13px;line-height:1.5;color:{_MUTED};">'
        "Si el botón no funciona, copia y pega esta dirección en tu navegador:</p>"
        '<p style="margin:0;font-size:13px;line-height:1.5;word-break:break-all;">'
        f'<a href="{_esc(url)}" style="color:{_BRAND};">{_esc(url)}</a></p>'
    )


def _notice(inner_html: str) -> str:
    """Recuadro de aviso sobre beige. El texto va en `_BODY`: `_MUTED` no llega
    a AA sobre este fondo."""
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background-color:{_BG};border-radius:10px;"><tr>'
        '<td style="padding:14px 16px;">'
        f'<p style="margin:0;font-size:13px;line-height:1.6;color:{_BODY};">{inner_html}</p>'
        "</td></tr></table>"
    )


def _strong(text: str) -> str:
    return f'<strong style="color:{_TITLE};">{_esc(text)}</strong>'


# ------------------------------------------------------------ resumen (E*) ----
_LIST_CAP = 30


@dataclass(frozen=True)
class DigestRow:
    """Un renglón del resumen. En el HTML, `label` a la izquierda y `amount` a
    la derecha, alineados como en un libro; en el texto plano, la frase de
    siempre (`text`), o «label: amount» si no hay una propia.

    `note` (el motivo de un descuadre) y `alert` (sobre el umbral) se muestran
    aparte en el HTML y al final de la frase en el texto."""

    label: str
    amount: str | None = None
    text: str | None = None
    note: str | None = None
    alert: bool = False
    muted: bool = False

    def plain(self) -> str:
        if self.text:
            base = self.text
        elif self.amount:
            base = f"{self.label}: {self.amount}"
        else:
            base = self.label
        note = f" — «{self.note}»" if self.note else ""
        flag = " ⚠ sobre el umbral" if self.alert else ""
        return f"{base}{note}{flag}"


def _capped(rows: list[DigestRow], total: int) -> list[DigestRow]:
    if total > len(rows):
        return [*rows, DigestRow(f"… y {total - len(rows)} más en la aplicación.", muted=True)]
    return rows


def digest_sections(
    payload: dict[str, Any],
) -> list[tuple[str, list[DigestRow], str | None]]:
    """Secciones del resumen en orden de urgencia: (título, renglones, nota)."""
    sections: list[tuple[str, list[DigestRow], str | None]] = []

    sub = payload.get("subscription")
    if sub:
        days = int(sub["days_left"])
        when = "mañana" if days == 1 else f"en {days} días"
        sections.append(
            (
                "Su suscripción a Prendo vence pronto",
                [
                    DigestRow(
                        f"Vence {when}, el {long_date(sub['expires_at'])}. "
                        "Al vencer se bloquea el acceso de todos los usuarios; "
                        "los datos no se borran."
                    )
                ],
                None,
            )
        )

    ready = payload.get("ready_for_auction") or {}
    if ready.get("total"):
        rows = [
            DigestRow(
                f"Contrato #{c['number']} — prórroga vencida el "
                f"{short_date(c['extension_ends_at'])}" + (" (nuevo)" if c.get("new") else "")
            )
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
                [
                    DigestRow(f"La caja del {long_date(s['session_date'])} sigue abierta.")
                    for s in unclosed
                ],
                None,
            )
        )

    diffs = payload.get("cash_differences") or []
    if diffs:
        rows = []
        for d in diffs:
            kind = "sobrante" if Decimal(str(d["difference"])) > 0 else "faltante"
            amount = money(abs(Decimal(str(d["difference"]))))
            rows.append(
                DigestRow(
                    f"Cierre del {short_date(d['session_date'])}: {kind}",
                    amount=amount,
                    text=f"Cierre del {short_date(d['session_date'])}: {kind} de {amount}",
                    note=d.get("reason") or None,
                    alert=bool(d.get("above_threshold")),
                )
            )
        sections.append(("Descuadres de arqueo", rows, None))

    discounts = payload.get("discounts") or []
    if discounts:
        rows = []
        for d in discounts:
            what = "Venta" if d["kind"] == "sale" else "Abono (recibo)"
            rows.append(
                DigestRow(
                    f"{what} #{d['number']}: descuento",
                    amount=money(d["amount"]),
                    text=f"{what} #{d['number']}: descuento de {money(d['amount'])}",
                    alert=bool(d.get("above_threshold")),
                )
            )
        sections.append(("Descuentos concedidos", rows, None))

    arrears = payload.get("entered_arrears") or []
    if arrears:
        sections.append(
            (
                "Entraron en mora",
                _capped(
                    [
                        DigestRow(f"Contrato #{c['number']} (desde el {short_date(c['since'])})")
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
                        DigestRow(
                            f"Contrato #{c['number']} — la prórroga vence el "
                            f"{short_date(c['extension_ends_at'])}"
                        )
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
        voided = f"; anuladas: {act['sales_voided']}" if act.get("sales_voided") else ""
        sections.append(
            (
                f"Movimiento {label}".strip(),
                [
                    DigestRow(
                        f"Contratos nuevos: {act['contracts_created']} — monto prestado",
                        amount=money(act["contracts_amount"]),
                        text=f"Contratos nuevos: {act['contracts_created']} "
                        f"({money(act['contracts_amount'])} prestados)",
                    ),
                    DigestRow(
                        f"Abonos: {act['payments']}",
                        amount=money(act["payments_amount"]),
                        text=f"Abonos: {act['payments']} ({money(act['payments_amount'])})",
                    ),
                    DigestRow(
                        f"Ventas: {act['sales']}{voided}",
                        amount=money(act["sales_amount"]),
                        text=f"Ventas: {act['sales']} ({money(act['sales_amount'])}){voided}",
                    ),
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
                    DigestRow(
                        f"{stale['product_count']} producto(s) llevan {stale['threshold_days']} "
                        "días o más en vitrina (al costo)",
                        amount=money(stale["total_cost_value"]),
                        text=f"{stale['product_count']} producto(s) llevan "
                        f"{stale['threshold_days']} días o más en vitrina, con "
                        f"{money(stale['total_cost_value'])} al costo.",
                    )
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
                    DigestRow("Total", amount=money(payables["total"])),
                    DigestRow("Con más de 60 días", amount=money(payables["days_over_60"])),
                ],
                None,
            )
        )

    dead = int(payload.get("dead_deliveries", 0))
    if dead:
        sections.append(
            (
                "Avisos que no se pudieron enviar",
                [DigestRow(f"{dead} correo(s) fallaron 3 veces.")],
                None,
            )
        )
    return sections


def _digest_row_html(row: DigestRow, *, first: bool) -> str:
    border = "" if first else f"border-top:1px solid {_BORDER};"
    color = _MUTED if row.muted else _BODY
    extra = ""
    if row.note:
        extra += f'<br><span style="font-size:13px;color:{_MUTED};">«{_esc(row.note)}»</span>'
    if row.alert:
        extra += (
            f'<br><span style="display:inline-block;margin-top:4px;padding:2px 8px;'
            f"border-radius:9999px;background-color:{_BG};font-size:12px;font-weight:600;"
            f'color:{_BRAND};">⚠ Sobre el umbral</span>'
        )
    amount = (
        f'<td align="right" valign="top" style="{border}padding:10px 0 10px 12px;'
        f'font-size:15px;line-height:1.5;font-weight:600;color:{_TITLE};white-space:nowrap;">'
        f"{_esc(row.amount)}</td>"
        if row.amount
        else ""
    )
    colspan = "" if row.amount else ' colspan="2"'
    return (
        f'<tr><td{colspan} valign="top" style="{border}padding:10px 0;font-size:15px;'
        f'line-height:1.5;color:{color};">{_esc(row.label)}{extra}</td>{amount}</tr>'
    )


def _digest_section_html(title: str, rows: list[DigestRow], note: str | None) -> str:
    note_html = (
        f'<p style="margin:4px 0 0 0;font-size:13px;line-height:1.5;color:{_MUTED};">'
        f"{_esc(note)}</p>"
        if note
        else ""
    )
    body = "".join(_digest_row_html(r, first=i == 0) for i, r in enumerate(rows))
    return _tr(
        f'<h2 style="margin:0;font-size:18px;line-height:1.3;color:{_TITLE};font-weight:600;">'
        f"{_esc(title)}</h2>{note_html}"
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin-top:8px;">{body}</table>',
        top=28,
    )


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
    meta = f"{branding.company_name} · {long_date(day)}"
    why = (
        f"Lo recibe porque su rol en {branding.company_name} tiene el permiso "
        "«Recibir el resumen». Quien administra la empresa puede quitarlo o apagar "
        "el resumen en Configuración."
    )
    rows = [_tr(_p(intro, last=True), top=20)] + [
        _digest_section_html(t, r, n) for t, r, n in sections
    ]
    text_lines = [PLATFORM_NAME.upper(), "", kind, meta, "", intro, ""]
    for title, section_rows, note in sections:
        text_lines.append(title.upper())
        if note:
            text_lines.append(note)
        text_lines.extend(f"- {r.plain()}" for r in section_rows)
        text_lines.append("")
    text_lines.extend(["---", why, "", f"{PLATFORM_TAGLINE} · prendo.com.co"])
    return RenderedEmail(
        # §8: el destinatario es un usuario de Prendo; la contraparte es Prendo.
        from_name=PLATFORM_NAME,
        subject=subject,
        html=_layout(
            brand_label=PLATFORM_NAME,
            title=kind,
            meta=meta,
            rows_html=rows,
            footer_html=[_esc(why)],
            tagline=PLATFORM_TAGLINE,
        ),
        text="\n".join(text_lines),
        reply_to=None,
    )


# ------------------------------------------------------- avisos al cliente ----
def _first_name(payload: dict[str, Any]) -> str:
    name = str(payload.get("first_name") or "").strip()
    return name.split()[0] if name else ""


def _positive(amount: Any) -> str | None:
    """El monto si es mayor que cero, o None. Los montos llegan como texto
    (`"0.00"` es verdadero para Python): esto evita un «le devolvimos $0»."""
    if amount is None:
        return None
    return str(amount) if Decimal(str(amount)) > 0 else None


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
        # El abono que salda el contrato manda ESTE correo y no además el
        # comprobante (§18.1-3): por eso dice lo pagado y el recibo.
        paid = (
            [f"Recibimos {money(p['amount'])} (recibo #{p['receipt_number']})."]
            if "amount" in p
            else []
        )
        return f"Paz y salvo del contrato #{n}", [
            *paid,
            f"Su contrato #{n} quedó saldado el {long_date(p['paid_on'])}. No nos debe nada.",
            "Guarde este correo como constancia.",
        ]
    if event_type == "loan_extended":
        new = p["new_contract_number"]
        # "No cambió" solo si de verdad no cambió: con las políticas viejas
        # (anteriores a 00053) el sucesor arranca el ancla el día del recargo.
        due = (
            f"Su fecha de cobro no cambió: la próxima cuota vence el "
            f"{long_date(p['next_due_date'])}."
            if p.get("anchor_kept")
            else f"Su próxima cuota vence el {long_date(p['next_due_date'])}."
        )
        return f"Su préstamo fue ampliado: nuevo contrato #{new}", [
            f"Le entregamos {money(p['extension_amount'])} más sobre su préstamo.",
            f"Su contrato #{n} fue reemplazado por el #{new}, "
            f"con un capital de {money(p['capital_balance'])}.",
            f"Sus abonos de ahora en adelante van al contrato #{new}.",
            due,
        ]
    if event_type == "credit_note_issued":
        origin = (
            f"Por la devolución de su compra #{p['sale_number']} se"
            if p.get("sale_number") is not None
            else "Se"
        )
        # F21-37: una devolución puede liquidarse en nota Y en efectivo (la
        # parte que se pagó con nota vuelve como nota; la de plata, en plata).
        # Es UN aviso, y dice los dos montos: callar el efectivo dejaría al
        # cliente sin constancia de la plata que recibió. Los avisos de antes
        # no traen el reparto: la nota era por `amount`.
        refunded = _positive(p.get("refunded_amount"))
        return "Tiene un saldo a favor", [
            f"{origin} emitió la nota crédito #{p['credit_note_number']} por "
            f"{money(p.get('credit_note_amount') or p['amount'])}.",
            *([f"Además le devolvimos {money(refunded)} en efectivo."] if refunded else []),
            "Puede usarla como parte de pago en su próxima compra.",
        ]
    if event_type == "sale_receipt":
        return f"Comprobante de su compra #{p['sale_number']}", [
            f"Gracias por su compra #{p['sale_number']} por {money(p['total'])}.",
        ]
    if event_type == "sale_reversed":
        sale = p["sale_number"]
        if p.get("kind") == "void":
            return f"Su compra #{sale} fue anulada", [
                f"Registramos la anulación de su compra #{sale} por {money(p['amount'])}.",
            ]
        if p.get("kind") == "return":
            refunded = _positive(p.get("refunded_amount"))
            if p.get("credit_note_number") is not None and refunded:
                # F21-37: liquidación mixta — el mismo hecho que el aviso de la
                # nota, contado desde la devolución (si la empresa apagó C5).
                settled = (
                    f"Le devolvimos {money(refunded)} en efectivo, y el resto quedó en la "
                    f"nota crédito #{p['credit_note_number']} por "
                    f"{money(p['credit_note_amount'])}."
                )
            elif p.get("credit_note_number") is not None:
                settled = (
                    f"Se liquidó con la nota crédito #{p['credit_note_number']} por "
                    f"{money(p.get('credit_note_amount') or p['amount'])}."
                )
            else:
                settled = f"Le devolvimos {money(p['amount'])}."
            return f"Devolución de su compra #{sale}", [
                f"Registramos la devolución #{p['return_number']} de su compra #{sale}.",
                settled,
            ]
        return f"Su compra #{sale} fue anulada o devuelta", [
            f"Registramos la anulación o devolución de su compra #{sale} por {money(p['amount'])}.",
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


def _check_unsubscribe_url(url: Any) -> str:
    """§9.2-e: todo correo al cliente lleva salida, incluidos los de servicio.
    Sin enlace no se redacta — un correo sin salida es el que termina marcado
    como spam, y esa marca la paga `prendo.com.co` para todos los inquilinos.

    Y la salida es la PÁGINA de baja, nunca un endpoint de la API: el GET no
    da de baja (los escáneres abren los enlaces solos, 03/09/2026)."""
    link = str(url or "")
    if "/baja/" not in link or "/api/" in link or "#" in link:
        raise ValueError("Un correo al cliente sin enlace de baja (a la página /baja/…) no sale.")
    return link


def render_customer(event_type: str, payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    """Aviso al cliente. **El autor es la empresa** (§8): su nombre va en el
    encabezado, donde los correos de la plataforma dicen «Prendo». El molde es
    el mismo —es la plataforma la que lo gobierna, §4.4—, pero un cliente de
    la compraventa que lee «PRENDO» arriba de su contrato de empeño ve una marca
    que nunca oyó, y eso se lee como phishing. Prendo aparece solo donde lo
    exige la honestidad: «Enviado por Prendo en nombre de …», bajo la tarjeta.
    """
    unsubscribe_url = _check_unsubscribe_url(payload.get("unsubscribe_url"))
    subject_tail, paragraphs = _customer_lines(event_type, payload)
    first = _first_name(payload)
    company = branding.company_name
    greeting = f"Hola, {first}:" if first else "Hola:"
    contact = (
        f"Tel. {branding.contact_phone}"
        if branding.contact_phone
        else (branding.contact_email or "")
    )
    signature = " · ".join(x for x in (company, contact, branding.footer_note or "") if x)
    sent_by = f"Enviado por {PLATFORM_NAME} en nombre de {company}."
    optout = f"¿No quiere recibir más avisos de {company} por correo?"
    rows = [_tr(_paragraphs([greeting, *paragraphs]), top=20)]
    if contact or branding.footer_note:
        # La firma de la empresa, a la vista: es a quien el cliente le responde.
        rows.append(_tr(_notice(_esc(signature))))
    footer_html = [
        f'{_esc(optout)} <a href="{_esc(unsubscribe_url)}" '
        f'style="color:{_BRAND};text-decoration:underline;">Darse de baja</a>'
    ]
    return RenderedEmail(
        # §8: el remitente es la plataforma, el autor es la empresa.
        from_name=f"{company} (vía {PLATFORM_NAME})",
        # §8: el asunto nunca dice Prendo.
        subject=f"{company} · {subject_tail}",
        html=_layout(
            brand_label=company,
            title=subject_tail,
            rows_html=rows,
            footer_html=footer_html,
            tagline=sent_by,
        ),
        text="\n\n".join(
            [
                company.upper(),
                subject_tail,
                greeting,
                *paragraphs,
                "---",
                signature,
                sent_by,
                f"{optout} Darse de baja: {unsubscribe_url}",
            ]
        ),
        reply_to=branding.contact_email or None,
    )


# ------------------------------------------- alertas a la empresa (A1–A4) ----
_WITHDRAWAL_KIND = {"profit": "Reparto de utilidad", "capital_return": "Devolución de capital"}


def _when(value: Any) -> str:
    """`2030-09-03T10:00-05:00` → `3 sep 2030, 10:00`. La hora ya viene en la
    zona de la empresa (la pone `record_company_alert`): acá no se convierte."""
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    return f"{short_date(moment.date())}, {moment.strftime('%H:%M')}"


def _alert_lines(event_type: str, p: dict[str, Any]) -> tuple[str, str, list[DigestRow]]:
    """(titular, frase, renglones «dato: valor»). Solo lee claves conocidas —
    ni el cliente ni los artículos llegan acá (§9.1): el número del documento
    es con lo que se pregunta."""
    who = str(p.get("actor_name") or "Un usuario")
    if event_type == "alert_sale_voided":
        n = p["sale_number"]
        rows = [DigestRow("Total de la venta", amount=money(p["total"]))]
        if _positive(p.get("refunded_amount")):
            rows.append(DigestRow("Salió de la caja", amount=money(p["refunded_amount"])))
        if p.get("sold_at"):
            rows.append(DigestRow("Vendida el", amount=short_date(p["sold_at"])))
        return f"Venta #{n} anulada", f"{who} anuló la venta #{n}.", rows
    if event_type == "alert_discount":
        amount = money(p["discount_amount"])
        if p.get("kind") == "payment":
            n = p["contract_number"]
            rows = [
                DigestRow("Recibo", amount=f"#{p['receipt_number']}"),
                DigestRow("Interés del abono", amount=money(p["interest_amount"])),
                DigestRow("Descuento", amount=amount),
                DigestRow("Cobrado", amount=money(p["total"])),
            ]
            headline = f"Descuento de {amount} en un abono al contrato #{n}"
            sentence = f"{who} concedió un descuento de {amount} en un abono al contrato #{n}."
        else:
            n = p["sale_number"]
            rows = [
                DigestRow("Antes del descuento", amount=money(p["subtotal"])),
                DigestRow("Descuento", amount=amount),
                DigestRow("Cobrado", amount=money(p["total"])),
            ]
            headline = f"Descuento de {amount} en la venta #{n}"
            sentence = f"{who} concedió un descuento de {amount} en la venta #{n}."
        if _positive(p.get("threshold")):
            rows.append(DigestRow("Umbral de alerta", amount=money(p["threshold"]), muted=True))
        return headline, sentence, rows
    if event_type == "alert_capital_withdrawal":
        amount = money(p["amount"])
        rows = [
            DigestRow("Retiro", amount=f"#{p['movement_number']}"),
            DigestRow("Monto", amount=amount),
            DigestRow("Cuenta", amount=str(p["account_name"])),
            DigestRow("Clase", amount=_WITHDRAWAL_KIND.get(str(p.get("kind")), str(p.get("kind")))),
            DigestRow("Fecha del retiro", amount=short_date(p["movement_date"])),
        ]
        return (
            f"Retiro de capital por {amount}",
            f"{who} registró un retiro de capital del dueño por {amount}.",
            rows,
        )
    if event_type == "alert_cash_reopened":
        day = short_date(p["session_date"])
        rows = [DigestRow("Caja del", amount=day)]
        if p.get("closed_at"):
            rows.append(DigestRow("Se había cerrado el", amount=_when(p["closed_at"])))
        if p.get("counted_cash") is not None:
            rows.append(DigestRow("Contado en ese cierre", amount=money(p["counted_cash"])))
        if p.get("difference") is not None and Decimal(str(p["difference"])) != 0:
            diff = Decimal(str(p["difference"]))
            kind = "Sobrante" if diff > 0 else "Faltante"
            rows.append(DigestRow(f"{kind} de ese cierre (se revierte)", amount=money(abs(diff))))
        return (
            f"Caja del {day} reabierta",
            f"{who} reabrió la caja del {day}. El cierre y su acta quedaron sin efecto "
            "hasta que se vuelva a cerrar.",
            rows,
        )
    raise ValueError(f"Sin plantilla para la alerta {event_type!r}")


def render_alert(event_type: str, payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    """A1–A4 (docs/NOTIFICACIONES.md §2.5, §19). **Remitente y marca: Prendo**,
    como el resumen (§8): el destinatario es un usuario de Prendo. La empresa va
    en el asunto, porque quien trabaja en dos compraventas tiene que saber de
    cuál es la alerta.

    Lo que dice es lo que alguien necesita para PREGUNTAR el mismo día: quién,
    qué, cuánto, cuándo y el motivo que escribió. El motivo va porque acá el
    lector es la empresa —al cliente no se le dice (C7, §18.2)—, y va
    escapado y entre comillas: es texto libre de un empleado."""
    company = branding.company_name
    headline, sentence, rows = _alert_lines(event_type, payload)
    rows = (
        [DigestRow("Quién", amount=str(payload.get("actor_name") or "—"))]
        + ([DigestRow("Cuándo", amount=_when(payload["at"]))] if payload.get("at") else [])
        + rows
    )
    reason = str(payload.get("reason") or "").strip()
    subject = f"Alerta · {company} · {headline}"
    why = (
        f"La recibe porque su rol en {company} tiene el permiso «Recibir por correo las "
        "alertas inmediatas». A quien hizo el acto no le llega. Quien administra la empresa "
        "puede quitar el permiso en Identidad → Roles o apagar esta alerta en Configuración."
    )
    table = "".join(_digest_row_html(r, first=i == 0) for i, r in enumerate(rows))
    html_rows = [
        _tr(_p(sentence, last=True), top=20),
        _tr(
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
            f"{table}</table>"
        ),
    ]
    if reason:
        html_rows.append(_tr(_notice(f"{_strong('Motivo:')} «{_esc(reason)}»")))
    text_lines = [PLATFORM_NAME.upper(), "", headline, company, "", sentence, ""]
    text_lines.extend(f"- {r.plain()}" for r in rows)
    if reason:
        text_lines.extend(["", f"Motivo: «{reason}»"])
    text_lines.extend(["", "---", why, "", f"{PLATFORM_TAGLINE} · prendo.com.co"])
    return RenderedEmail(
        from_name=PLATFORM_NAME,
        subject=subject,
        html=_layout(
            brand_label=PLATFORM_NAME,
            title=headline,
            meta=company,
            rows_html=html_rows,
            footer_html=[_esc(why)],
            tagline=PLATFORM_TAGLINE,
        ),
        text="\n".join(text_lines),
        reply_to=None,
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

    **Es la plantilla «Invite user» de Supabase** (`frontend-starter/docs/
    correo-invitacion.html`) con los mismos textos, en *tú*, y dos diferencias
    a propósito: nombra a la empresa en el cuerpo —el backend sí sabe quién
    invitó; Supabase, con una sola plantilla por proyecto, no— y el pie no
    repite el correo del destinatario (solo se leen las dos claves de abajo).

    **El remitente es Prendo, sin «(vía …)» y sin `Reply-To`** (§8): la
    contraparte de alguien que va a ser usuario de Prendo es Prendo, y por eso
    la marca del encabezado también. El nombre de la empresa va en el asunto y
    en el cuerpo porque es lo que la persona reconoce —«me invitaron a la
    compraventa donde trabajo»—, pero ni su teléfono ni su `footer_note`: el
    correo no es de la empresa.

    Solo lee `invitee_name` e `invite_link`. El enlace NO viene del payload
    guardado: lo pone el despachador en memoria al enviar (§16), porque es una
    credencial que vence en minutos.
    """
    link = _check_invite_link(str(payload["invite_link"]))
    first = _first_name({"first_name": payload.get("invitee_name")})
    company = branding.company_name
    title = f"Hola {first}, te damos la bienvenida" if first else "Te damos la bienvenida"
    subject = f"Invitación a {company} en {PLATFORM_NAME}"
    invited = (
        f"Te invitaron a trabajar en {company} con {PLATFORM_NAME}, el sistema con el que "
        "tu equipo maneja la compraventa."
    )
    duties = (
        "Desde ahí vas a atender clientes, registrar contratos de empeño, vender en la tienda "
        "y manejar la caja del día, según el rol que te asignaron."
    )
    start = "Para empezar solo falta que crees tu contraseña."
    notice_strong = "Este enlace es personal y temporal."
    notice_rest = (
        "No lo compartas con nadie. Si vence antes de que puedas usarlo, pídele al "
        f"administrador de {company} que te mande uno nuevo."
    )
    why = (
        f"Recibiste este correo porque alguien de {company} creó una cuenta a tu nombre. "
        "Si no esperabas esta invitación, puedes ignorar este mensaje: la cuenta no se "
        "activa hasta que crees tu contraseña."
    )
    # El mismo texto que `invited`, con la empresa en negrita: por eso no pasa
    # por `_p`, que escaparía el <strong>. Cada pedazo dinámico va escapado.
    body = (
        f'<p style="margin:0 0 16px 0;font-size:16px;line-height:1.6;color:{_BODY};">'
        f"Te invitaron a trabajar en {_strong(company)} con {_esc(PLATFORM_NAME)}, el "
        f"sistema con el que tu equipo maneja la compraventa. {_esc(duties)}</p>"
    )
    rows = [
        _tr(body + _p(start, last=True), top=20),
        _tr(_button(link, "Crear mi contraseña")),
        _tr(_link_fallback(link)),
        _tr(_notice(f"{_strong(notice_strong)} {_esc(notice_rest)}")),
    ]
    text = "\n\n".join(
        [
            PLATFORM_NAME.upper(),
            title,
            f"{invited} {duties}",
            f"{start} Créala en esta dirección:\n{link}",
            f"{notice_strong} {notice_rest}",
            "---",
            why,
            PLATFORM_TAGLINE,
        ]
    )
    return RenderedEmail(
        from_name=PLATFORM_NAME,
        subject=subject,
        html=_layout(
            brand_label=PLATFORM_NAME,
            title=title,
            rows_html=rows,
            footer_html=[_esc(why)],
            tagline=PLATFORM_TAGLINE,
        ),
        text=text,
        reply_to=None,
    )


def render(event_type: str, payload: dict[str, Any], branding: Branding) -> RenderedEmail:
    et = catalog.get(event_type)
    if et.family == "digest":
        return render_digest(event_type, payload, branding)
    if et.audience == "customer":
        return render_customer(event_type, payload, branding)
    if et.family == "alert":
        return render_alert(event_type, payload, branding)
    if event_type == "user_invitation":
        return render_user_invitation(payload, branding)
    raise ValueError(f"El evento {event_type!r} todavía no tiene plantilla (fase posterior).")
