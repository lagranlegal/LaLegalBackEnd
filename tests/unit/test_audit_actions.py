"""El catálogo de acciones auditadas, fijado.

POR QUÉ EXISTE (08/09/2026). Dos derivas silenciosas, encontradas el mismo
día porque Mateo invitó a un empleado, hizo una venta con su usuario y en
Auditoría no salía nada:

1. **Faltaban acciones.** Se auditaban las excepciones (descuentos,
   anulaciones, remates) pero no el trabajo diario: la venta, el abono, abrir
   la caja, el ingreso de inventario, el cliente. Una pantalla que se llama
   Auditoría y no muestra la operación más común del negocio no responde la
   única pregunta para la que un dueño la abre.

2. **Sobraban etiquetas y faltaban otras.** El front tenía "Abrió la caja"
   para una acción que el backend nunca escribía, y doce acciones que sí
   escribía salían en crudo en pantalla (`auction_contract`,
   `generate_recovery_link`…).

Este test lee los `action="..."` del código y los compara con la lista de
abajo. Si agregas una auditoría nueva, el test falla y te recuerda que la
etiqueta también hay que ponerla — porque el front no puede adivinarla y lo
que se ve en pantalla es el código pelado.
"""

import re
from pathlib import Path

ACCIONES_AUDITADAS = {
    # cashbox
    "open_session",
    "close_session",
    "reopen_session",
    "create_expense",
    "create_expense_category",
    # contracts
    "create_contract",
    "import_contract",
    "update_contract",
    "create_payment",
    "apply_payment_discount",
    "auction_contract",
    # sales
    "create_sale",
    "apply_sale_discount",
    "void_sale",
    "create_return",
    # inventory
    "create_entry",
    "pay_entry",
    "create_exit",
    "publish_item",
    "update_product",
    "create_transformation",
    # customers
    "create_customer",
    "update_customer",
    # catalogs
    "create_category",
    "update_category",
    "create_supplier",
    "update_supplier",
    # identity
    "invite_user",
    "update_user_role",
    "deactivate_user",
    "reactivate_user",
    "generate_recovery_link",
    "create_role",
    "rename_role",
    "update_role_permissions",
    # company
    "update_settings",
    "create_document_template",
    "update_document_template",
    "activate_document_template",
    "delete_document_template",
    # accounts
    "create_account",
    "update_account",
    "account_transfer",
    "settle_account",
    # platform
    "create_company",
    "extend_subscription",
    "set_company_status",
    "expire_subscription",
}


def _acciones_en_el_codigo() -> set[str]:
    """Los `action="..."` que aparecen junto a un `insert_audit_log`."""
    raiz = Path(__file__).resolve().parents[2] / "app" / "modules"
    encontradas: set[str] = set()
    for archivo in raiz.rglob("*.py"):
        texto = archivo.read_text(encoding="utf-8")
        if "insert_audit_log" not in texto:
            continue
        encontradas.update(re.findall(r'action="([a-z_]+)"', texto))
        # `action="reactivate_user" if active else "deactivate_user"`
        encontradas.update(re.findall(r'action="[a-z_]+" if \w+ else "([a-z_]+)"', texto))
    return encontradas


def test_el_catalogo_de_acciones_auditadas_no_cambia_en_silencio() -> None:
    en_codigo = _acciones_en_el_codigo()

    nuevas = en_codigo - ACCIONES_AUDITADAS
    assert not nuevas, (
        f"Auditorías nuevas sin registrar: {sorted(nuevas)}.\n"
        "Agrégalas a ACCIONES_AUDITADAS **y** a "
        "`frontend-starter/src/features/audit/labels.ts` — sin etiqueta, en "
        "pantalla se ve el código pelado."
    )

    desaparecidas = ACCIONES_AUDITADAS - en_codigo
    assert not desaparecidas, (
        f"Estas acciones ya no se auditan: {sorted(desaparecidas)}.\n"
        "Si fue a propósito, quítalas de acá y de las etiquetas del front — "
        "una etiqueta para algo que nunca se escribe es UI muerta, y ya pasó "
        "con `open_session`."
    )


def test_el_trabajo_diario_esta_auditado() -> None:
    """Lo que un dueño espera ver al preguntar "¿qué hizo esta persona hoy?".

    Fijado aparte y por nombre porque es el punto del reporte: no basta con
    que el catálogo sea consistente, tienen que estar ESTAS.
    """
    en_codigo = _acciones_en_el_codigo()
    for accion in ("create_sale", "create_payment", "open_session", "create_entry"):
        assert accion in en_codigo, f"'{accion}' dejó de auditarse"
