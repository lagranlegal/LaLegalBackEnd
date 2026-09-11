"""Vigila que siga habiendo UN solo lugar físico por empresa.

    python scripts/qa/verificar_sedes.py

POR QUÉ ESTO ES UN SCRIPT Y NO UN TEST
======================================
Un test de CI corre contra un Postgres local efímero con sus fixtures, así que
**nunca vería** que una empresa real creció una segunda registradora. La
invariante que importa acá es sobre los DATOS VIVOS, no sobre el código — el
código ya lo cubre `tests/integration/test_cashbox.py` y `test_platform.py`.

QUÉ VIGILA, Y POR QUÉ IMPORTA
=============================
Multi-caja y multi-sucursal están aplazados (`docs/SUCURSALES.md`). Esa
decisión es segura mientras se cumpla una premisa: **cada empresa opera en un
solo lugar físico**. Mientras sea cierta, el día que se implementen sucursales
todo lo registrado hasta entonces se atribuye a "Sede principal" sin
ambigüedad, y no se pierde nada.

El riesgo es que esa premisa deje de ser cierta **sin que nadie lo note**: el
cliente abre un segundo local, sigue operando sobre el mismo registro, y nada
falla. Meses después, "¿cuánto vendió Chapinero?" no tiene respuesta y ya no
se puede reconstruir — el inventario en particular no tiene ningún vínculo con
una caja.

Este script convierte ese riesgo invisible en una señal. Con una empresa se
puede revisar a ojo; con veinte no.

QUÉ NO DETECTA
==============
Dos locales operando sobre UNA sola caja y UNA sola cuenta de efectivo. Eso es
indetectable desde el software — es exactamente igual a un local con mucho
movimiento. Esa parte depende de que el cliente avise, y el momento de avisar
es ANTES de abrir el segundo local.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

import qa  # noqa: E402


def _get(table: str, params: dict[str, str]) -> list[dict]:
    r = httpx.get(
        f"{qa.SUPABASE_URL}/rest/v1/{table}",
        headers=qa.admin_headers(),
        params=params,
        timeout=qa.TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    empresas = _get("company", {"select": "id,name,status", "order": "name"})
    registers = _get("cash_register", {"select": "id,company_id,active"})
    cuentas = _get("account", {"select": "id,company_id,name,type,active,register_id"})

    print(f"\n  {len(empresas)} empresas\n")
    print(f"  {'EMPRESA':<38} {'CAJAS':>6} {'CAJONES':>8} {'SIN LIGAR':>10}")
    print(f"  {'-' * 38} {'-' * 6} {'-' * 8} {'-' * 10}")

    hallazgos: list[str] = []

    for e in empresas:
        cid = e["id"]
        cajas = [r for r in registers if r["company_id"] == cid and r["active"]]
        cajones = [
            a for a in cuentas if a["company_id"] == cid and a["type"] == "cash" and a["active"]
        ]
        sin_ligar = [a for a in cajones if a["register_id"] is None]

        marca = " " if (len(cajas) == 1 and len(cajones) == 1 and not sin_ligar) else "!"
        print(
            f"{marca} {e['name'][:38]:<38} {len(cajas):>6} {len(cajones):>8} {len(sin_ligar):>10}"
        )

        if len(cajas) > 1:
            hallazgos.append(
                f"{e['name']}: {len(cajas)} cajas registradoras activas. "
                "La app no puede operar con varias — toda operación de dinero "
                "va a fallar con MULTIPLE_REGISTERS_NOT_SUPPORTED."
            )
        if len(cajas) == 0:
            hallazgos.append(
                f"{e['name']}: ninguna caja registradora activa. "
                "No se puede abrir turno ni registrar un cobro en efectivo."
            )
        if len(cajones) > 1:
            hallazgos.append(
                f"{e['name']}: {len(cajones)} cuentas de efectivo activas. "
                "El arqueo mezcla dos cajones y es incuadrable por construcción; "
                "y el día que haya sucursales, esos movimientos ya no se pueden atribuir."
            )
        if sin_ligar:
            nombres = ", ".join(a["name"] for a in sin_ligar)
            hallazgos.append(
                f"{e['name']}: cajón sin ligar a su registradora ({nombres}). "
                "Debería haberlo hecho la migración 00052 o el alta de la empresa."
            )

    if not hallazgos:
        print("\n  OK — una caja y un cajón ligado por empresa.")
        print("  La premisa de SUCURSALES.md §3 se sostiene: aplazar sigue siendo seguro.\n")
        return 0

    print(f"\n  {len(hallazgos)} hallazgo(s):\n")
    for h in hallazgos:
        print(f"    · {h}")
    print("\n  Ver docs/SUCURSALES.md — §5 (las acciones) y §7 (la ventana cerrándose).\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
