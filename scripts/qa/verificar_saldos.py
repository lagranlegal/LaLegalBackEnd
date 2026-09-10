"""Comprueba que el saldo de efectivo derivado (00048) cuadra con el arqueo.

La invariante que tiene que cumplirse siempre: lo que la API reporta como
saldo de las cuentas de efectivo es lo mismo que el turno abierto espera
encontrar en el cajón. Si los dos números se separan, un descuadre aparece
o desaparece según por dónde se mire.

    python scripts/qa/verificar_saldos.py [company_id]
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

import qa  # noqa: E402
import seed_contratos as seed  # noqa: E402

COMPANY_ID = sys.argv[1] if len(sys.argv) > 1 else seed.COMPANY_ID


def main() -> None:
    h = qa.admin_headers()
    ajustes = httpx.get(
        f"{qa.SUPABASE_URL}/rest/v1/cash_movement",
        headers=h,
        params={
            "select": "direction,amount,notes,session_id,reference_type",
            "company_id": f"eq.{COMPANY_ID}",
            "concept": "eq.adjustment",
        },
        timeout=qa.TIMEOUT,
    ).json()

    print(f"\n  Ajustes de efectivo en la empresa ({len(ajustes)}):")
    for m in ajustes:
        print(f"    {m['direction']:3s} {m['amount']:>12}  sesión={m['session_id']}  ref={m['reference_type']}")
        print(f"        {m['notes']}")

    client = seed.ensure_actor()
    try:
        print("\n  Saldos que devuelve GET /accounts:")
        efectivo = Decimal("0")
        for a in client.get("/accounts").body:
            marca = ""
            if a["type"] == "cash":
                efectivo += Decimal(a["balance"])
                marca = "  ← efectivo"
            print(
                f"    {a['name']:18s} {a['type']:11s} "
                f"opening={a['opening_balance']:>12s} balance={a['balance']:>12s}{marca}"
            )

        sesion = client.get("/cashbox/sessions/current")
        if not sesion.ok:
            print(f"\n  No hay turno abierto ({sesion.code}) — el saldo de arriba existe igual,")
            print("  que es justamente lo que cambió: antes el cajón reportaba 0.00.")
            return

        reporte = client.get(f"/cashbox/sessions/{sesion.body['id']}/report").body
        esperado = Decimal(reporte["expected_cash"])
        print(f"\n  Turno abierto del {sesion.body['session_date']}")
        print(f"    base de apertura      {sesion.body['opening_balance']:>14}")
        print(f"    efectivo esperado     {esperado:>14}   (arqueo del turno)")
        print(f"    suma de cuentas cash  {efectivo:>14}   (saldo derivado)")
        cuadra = esperado == efectivo
        print(f"\n  {'CUADRA' if cuadra else 'NO CUADRA'}: los dos caminos dan el mismo número."
              if cuadra else
              f"\n  NO CUADRA — diferencia de {efectivo - esperado}")
        if not cuadra:
            raise SystemExit(1)
    finally:
        seed.deactivate_actor()


if __name__ == "__main__":
    main()
