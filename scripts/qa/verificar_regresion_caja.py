"""Regresión de los flujos que toca el cambio de `_resolve_active_register`.

    python scripts/qa/verificar_regresion_caja.py

Contra el backend DESPLEGADO, con login real del laboratorio de QA. No toca
las empresas reales.

QUÉ SE EXPONE Y POR QUÉ ESTOS FLUJOS
====================================
El cambio reemplazó `get_active_register` (que hacía `order by created_at
limit 1`) por `list_active_registers` + un helper único que falla si hay más
de una. Cuatro endpoints lo usan:

    open_session · get_current_session · get_today_session · create_expense

Contratos, abonos y ventas **no** pasan por ahí: resuelven la sesión con
`cashbox.integration.get_open_session`, que consulta `cash_session` directo
por `company_id`. Se comprueban igual, para confirmar que siguen intactos.

Y `00052` pobló `account.register_id`. `AccountOut` **no** expone esa columna,
así que el contrato de la API no cambió — pero el listado de cuentas y el
extracto se leen igual para confirmarlo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import qa  # noqa: E402

ADMIN = "qa.admin@qalab.com"


def main() -> int:
    print(f"\n  Backend: {qa.API}\n")
    c = qa.client_for(ADMIN, qa.TEST_PASSWORD, "admin-qa")

    # ---------------------------------------------------------------- bootstrap
    me = c.get("/me")
    qa.check("GET /me responde", me.ok, f"status={me.status}")
    empresa = me.body.get("company", {}).get("name", "?") if me.ok else "?"
    print(f"  Empresa del laboratorio: {empresa}\n")

    # ------------------------------------------------------- cuentas (00052)
    cuentas = c.get("/accounts")
    qa.check("GET /accounts responde", cuentas.ok, f"status={cuentas.status}")
    if cuentas.ok:
        # El contrato de la API NO cambió: `register_id` es interno.
        expone_register = any("register_id" in a for a in cuentas.body)
        qa.check(
            "AccountOut NO expone register_id (contrato intacto)",
            not expone_register,
            "si lo expusiera, el front vería un campo nuevo sin pedirlo",
        )
        efectivo = [a for a in cuentas.body if a["type"] == "cash" and a["active"]]
        qa.check(
            "una sola cuenta de efectivo activa",
            len(efectivo) == 1,
            f"hay {len(efectivo)}",
        )
        for a in cuentas.body:
            print(f"    {a['type']:<11} {a['name']:<22} saldo {a['balance']:>14}")

        # El extracto: su comportamiento no cambió (saldo corriente para los
        # cuatro tipos desde 00048), solo se corrigió el docstring que decía
        # lo contrario que su propio service.
        if efectivo:
            ext = c.get(
                f"/accounts/{efectivo[0]['id']}/statement",
                params={"from_date": "2026-09-01", "to_date": "2026-09-30"},
            )
            qa.check("GET /accounts/{id}/statement responde", ext.ok, f"status={ext.status}")
            if ext.ok:
                qa.check(
                    "el cajón SÍ lleva saldo corriente (00048)",
                    ext.body.get("has_running_balance") is True,
                    f"has_running_balance={ext.body.get('has_running_balance')}",
                )

    # ------------------------------------------- los 4 endpoints que cambiaron
    print()
    actual = c.get("/cashbox/sessions/current")
    qa.check(
        "GET /cashbox/sessions/current no rompe",
        actual.ok or actual.body.get("code") == "CASH_SESSION_NOT_OPEN",
        f"status={actual.status} code={actual.body.get('code')}",
    )
    hay_sesion = actual.ok

    hoy = c.get("/cashbox/sessions/today")
    qa.check(
        "GET /cashbox/sessions/today no rompe",
        hoy.ok or hoy.status == 404,
        f"status={hoy.status} code={hoy.body.get('code')}",
    )

    # Ninguno de los dos puede devolver el error nuevo: con una sola
    # registradora, el helper resuelve igual que antes.
    for nombre, r in (("current", actual), ("today", hoy)):
        qa.check(
            f"/{nombre} no dispara MULTIPLE_REGISTERS_NOT_SUPPORTED",
            r.body.get("code") != "MULTIPLE_REGISTERS_NOT_SUPPORTED",
            "con una registradora el comportamiento debe ser idéntico al de antes",
        )

    if hay_sesion:
        sid = actual.body["id"]
        print(f"\n  Sesión abierta: {sid} (fecha {actual.body['session_date']})")

        reporte = c.get(f"/cashbox/sessions/{sid}/report")
        qa.check("GET /sessions/{id}/report no rompe", reporte.ok, f"status={reporte.status}")
        if reporte.ok:
            print(f"    esperado en el cajón: {reporte.body['expected_cash']}")

        # `create_expense` es el cuarto consumidor del helper, y además mueve
        # plata de verdad: es la comprobación que importa.
        cats = c.get("/cashbox/expense-categories")
        if cats.ok and cats.body:
            gasto = c.post(
                "/cashbox/expenses",
                idem=True,
                json={
                    "category_id": cats.body[0]["id"],
                    "description": "QA regresión 00052 — borrable",
                    "amount": "1000.00",
                    "payment_method": "cash",
                },
            )
            qa.check(
                "POST /cashbox/expenses (movimiento real de dinero)",
                gasto.ok,
                f"status={gasto.status} code={gasto.body.get('code')}",
            )
            if gasto.ok:
                despues = c.get(f"/cashbox/sessions/{sid}/report")
                qa.check(
                    "el gasto bajó el efectivo esperado",
                    despues.ok and despues.body["expected_cash"] != reporte.body["expected_cash"],
                    f"antes {reporte.body['expected_cash']} → "
                    f"después {despues.body.get('expected_cash')}",
                )
    else:
        print("\n  (sin sesión abierta: no se prueba el gasto)")

    # ------------------------------------ flujos que NO pasan por el helper
    print()
    for nombre, path in (
        ("contratos", "/contracts"),
        ("ventas", "/sales"),
        ("inventario", "/inventory/items"),
        ("clientes", "/customers"),
        ("auditoría", "/audit-log"),
        ("dashboard", "/reports/dashboard"),
    ):
        r = c.get(path)
        qa.check(f"GET {path} ({nombre}) intacto", r.ok, f"status={r.status}")

    print()
    if not qa.FINDINGS:
        print("  OK — los flujos existentes se comportan igual que antes.\n")
        return 0
    print(f"  {len(qa.FINDINGS)} hallazgo(s):")
    for f in qa.FINDINGS:
        print(f"    · {f['name']} — {f['detail']}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
