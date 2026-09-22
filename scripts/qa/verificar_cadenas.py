"""Vigila las invariantes de las cadenas de contratos (el recargo, 00051).

    python scripts/qa/verificar_cadenas.py

Sale con código **1** si alguna invariante está rota, **0** si todo está
limpio, así que sirve en un cron.

POR QUÉ ESTO ES UN SCRIPT Y NO UN TEST
======================================
Mismo motivo que `verificar_sedes.py`: un test de CI corre contra un Postgres
efímero con sus fixtures, así que **nunca vería** que un job nocturno dejó
contratos reales con el estado equivocado. La invariante que importa acá es
sobre los DATOS VIVOS, no sobre el código — el código ya lo cubren
`tests/unit/test_contract_recompute_query.py` y los tests del recargo.

QUÉ VIGILA, Y POR QUÉ IMPORTA
=============================
**F21-10** (`docs/QA_AUDITORIA.md`): la Machine del job nocturno quedó clavada
a la imagen del 08/09 y estuvo **once días** recalculando contratos
`superseded` como si siguieran vivos. Dejó 4 contratos con el estado
equivocado, y uno de ellos con una prórroga viva que lo iba a meter solo en
«Listos para remate».

**Nada avisó.** No hay constraint ni chequeo en la base que diga "un contrato
con sucesor está `superseded`", así que el daño fue invisible hasta que
alguien lo fue a buscar a mano. Este script convierte ese riesgo invisible en
una señal: si el job vuelve a desincronizarse —o si alguien revierte un
estado a mano— aparece acá al día siguiente, no once días después.

Las tres invariantes:

1. **Todo contrato con sucesor está `superseded`.** Es la definición misma de
   la cadena: `extend_loan` cierra el viejo y hace nacer el nuevo en la misma
   transacción. La columna es `parent_contract_id` (00051:74);
   `root_contract_id` es la raíz de la cadena y NO sirve para esto.

2. **Ningún `contract_item` en `transferred` cuelga de un contrato que no esté
   `superseded`.** Es la invariante espejo: `mark_items_transferred` corre en
   la MISMA transacción que el paso a `superseded`, así que una divergencia
   acá no puede venir del recargo — significa que alguien (el job, una
   corrección a mano) movió el status del contrato después.

3. **Ningún contrato en estado terminal tiene `extension_ends_at`.** Un
   terminal no puede tener una prórroga viva: es una bomba con fecha, un
   documento que ya no es una obligación entrando solo a la cola de remate.
   Los estados terminales salen de `rules.TERMINAL_STATUSES`, NO de una lista
   escrita acá — escribirla a mano es exactamente el error de F21-10.

SOLO LECTURA
============
La base dev remota tiene datos reales de clientes (cédulas, fotos de
documento, Ley 1581). La transacción se abre con `SET TRANSACTION READ ONLY`
y el reporte imprime únicamente id, número, empresa y estado del contrato:
**ningún dato personal**.

QUÉ BASE MIRA
=============
Por defecto, `DATABASE_URL` del `.env` del backend — la Supabase **dev
remota**, que es la que tiene los datos vivos. `QA_DATABASE_URL` la
sobreescribe; sirve para ejercer la detección contra la Postgres LOCAL de
tests (`supabase start`, puerto 54322), que es el único lugar donde se puede
fabricar una cadena rota a propósito.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).parent))

import qa  # noqa: E402

from app.modules.contracts import rules  # noqa: E402

# NullPool + statement_cache_size=0: la conexión va por Supavisor en modo
# transacción y asyncpg no puede reutilizar prepared statements (ver
# `app/core/db.py`).
CONEXION: dict[str, Any] = {"statement_cache_size": 0}

#: La dev remota por defecto; `QA_DATABASE_URL` para apuntar a otra (ver el
#: encabezado). Nunca se hardcodea una URL acá: sale del `.env` vía `qa`.
URL_BASE = os.environ.get("QA_DATABASE_URL") or qa.BE["DATABASE_URL"]


# ------------------------------------------------------------ invariantes ---
# Cada consulta devuelve SIEMPRE las mismas cuatro columnas visibles
# (contrato, número, empresa, estado) más el detalle propio de la invariante.

INVARIANTE_1 = """
select c.id::text as contrato, c.number, co.name as empresa, c.status,
       (select count(*) from public.contract s where s.parent_contract_id = c.id) as detalle
from public.contract c
join public.company co on co.id = c.company_id
where exists (select 1 from public.contract s where s.parent_contract_id = c.id)
  and c.status <> 'superseded'
order by co.name, c.number
"""

INVARIANTE_2 = """
select c.id::text as contrato, c.number, co.name as empresa, c.status,
       count(*) as detalle
from public.contract_item ci
join public.contract c on c.id = ci.contract_id
join public.company co on co.id = c.company_id
where ci.status = 'transferred'
  and c.status <> 'superseded'
group by c.id, c.number, co.name, c.status
order by co.name, c.number
"""

INVARIANTE_3 = """
select c.id::text as contrato, c.number, co.name as empresa, c.status,
       c.extension_ends_at as detalle
from public.contract c
join public.company co on co.id = c.company_id
where c.extension_ends_at is not null
  and c.status = any(:terminales)
order by co.name, c.number
"""

INVARIANTES: list[dict[str, Any]] = [
    {
        "nombre": "todo contrato con sucesor está en 'superseded'",
        "sql": INVARIANTE_1,
        "params": {},
        "detalle": "sucesores",
        "explica": (
            "El contrato fue ampliado (tiene hijo por `parent_contract_id`) pero su "
            "estado dice que sigue vivo. Es el daño de F21-10: el job nocturno lo "
            "recalculó como si fuera una obligación abierta. Aparece en las colas de "
            "cobro y de remate un documento que ya no existe como deuda — la deuda la "
            "lleva el sucesor, y cobrarla dos veces es el riesgo."
        ),
    },
    {
        "nombre": "ningún item 'transferred' cuelga de un contrato no 'superseded'",
        "sql": INVARIANTE_2,
        "params": {},
        "detalle": "prendas",
        "explica": (
            "Las prendas están marcadas como pasadas al sucesor, pero el contrato no "
            "figura reemplazado. `mark_items_transferred` corre en la MISMA transacción "
            "que el paso a 'superseded', así que esto no lo pudo dejar el recargo: "
            "alguien movió el status del contrato después. Es la misma rotura que la "
            "invariante 1, vista desde las prendas."
        ),
    },
    {
        "nombre": "ningún contrato terminal tiene prórroga viva (`extension_ends_at`)",
        "sql": INVARIANTE_3,
        "params": {"terminales": sorted(rules.TERMINAL_STATUSES)},
        "detalle": "prórroga hasta",
        "explica": (
            "Una bomba con fecha: el contrato está cerrado pero conserva el vencimiento "
            "de una prórroga. Cuando esa fecha pase, entra solo a «Listos para remate» "
            "un documento que ya no es una obligación. Reparar el estado de un contrato "
            "de la invariante 1 SIN limpiar `extension_ends_at` deja justo esto."
        ),
    },
]


# ---------------------------------------------------------------- reporte ---
def _imprimir_filas(filas: Sequence[Any], etiqueta_detalle: str) -> None:
    print(f"    {'EMPRESA':<28} {'Nº':>6} {'ESTADO':<14} {etiqueta_detalle:<14} CONTRATO")
    print(f"    {'-' * 28} {'-' * 6} {'-' * 14} {'-' * 14} {'-' * 36}")
    for f in filas:
        print(
            f"    {str(f.empresa)[:28]:<28} {f.number:>6} {f.status:<14} "
            f"{str(f.detalle):<14} {f.contrato}"
        )


async def _correr() -> int:
    print(f"\n  Base: {URL_BASE.split('@')[-1]}  (SOLO LECTURA)")
    print(f"  Terminales según rules.TERMINAL_STATUSES: {sorted(rules.TERMINAL_STATUSES)}\n")

    motor = create_async_engine(URL_BASE, poolclass=NullPool, connect_args=CONEXION)
    rotas: list[tuple[dict[str, Any], Sequence[Any]]] = []
    try:
        async with motor.connect() as conexion:
            # Read-only EXPLÍCITO y por transacción (no por sesión: bajo un
            # pooler en modo transacción una sesión no es nuestra).
            await conexion.execute(text("SET TRANSACTION READ ONLY"))
            for inv in INVARIANTES:
                filas = (await conexion.execute(text(inv["sql"]), inv["params"])).fetchall()
                marca = "OK  " if not filas else "ROTA"
                cuantas = f" — {len(filas)} fila(s)" if filas else ""
                print(f"  [{marca}] {inv['nombre']}{cuantas}")
                if filas:
                    rotas.append((inv, filas))
            # Nada se escribió; el rollback lo deja explícito.
            await conexion.rollback()
    finally:
        await motor.dispose()

    if not rotas:
        print("\n  OK — las cadenas de contratos están sanas.")
        print("  Ningún contrato reemplazado quedó figurando como vivo (F21-10).\n")
        return 0

    total = sum(len(f) for _, f in rotas)
    print(f"\n  {len(rotas)} invariante(s) rota(s), {total} contrato(s) afectado(s):\n")
    for inv, filas in rotas:
        print(f"  ── {inv['nombre']}")
        print(f"     {inv['explica']}\n")
        _imprimir_filas(filas, inv["detalle"])
        print()
    print("  Ver docs/QA_AUDITORIA.md → F21-10, y docs/RECARGOS.md para la cadena.\n")
    return 1


def main() -> int:
    return asyncio.run(_correr())


if __name__ == "__main__":
    raise SystemExit(main())
