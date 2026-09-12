"""Siembra contratos de prueba en TODOS los estados, para una empresa real.

Pedido por Mateo (09/09/2026) para poder probar la pantalla de contratos con
algo más que cinco contratos `active` recién creados.

## Por qué el import y no la creación normal

`POST /contracts` desembolsa: exige caja abierta y escribe un `cash_movement`.
Sembrar 22 contratos por ahí le movería el efectivo esperado de la sesión a la
empresa. `POST /contracts/import` (docs/MIGRACION_CONTRATOS.md) existe justo
para la foto financiera al corte: **sin sesión de caja y sin `cash_movement`**.

Y es el único camino que permite fabricar estados, porque acepta `start_date` e
`interest_paid_until` — los dos hechos de los que el backend DERIVA el estado.
`status` nunca se acepta en el body (un solo origen de verdad), así que acá no
se "pone" un estado: se eligen las fechas que lo producen, y el mismo recálculo
que usa `GET /contracts/{id}` lo persiste antes de responder.

## Los seis estados y cómo se fabrican (hoy = la fecha de la empresa, Bogotá)

`owed` = meses completos entre `interest_paid_until` y hoy.
`N` = `arrears_window_months` del contrato · `E` = `extension_months`.

| Estado | Condición | Palanca |
|---|---|---|
| `active` | `owed == 0` | `interest_paid_until` > hoy − 1 mes (o en el futuro) |
| `in_arrears` | `1 <= owed < N` | solo con `N > 1`; en Tecnología `N = 1`, no existe |
| `in_extension` | `owed >= N` y `extension_ends_at >= hoy` | `ends = ipu + N + E` |
| listo para remate | `in_extension` y `extension_ends_at < hoy` | mismo estado, `ends` pasado |
| `paid` | terminal | importar y saldar (abono de `owed` meses + todo el capital) |
| `auctioned` | terminal | importar con prórroga vencida y `POST /contracts/{id}/auction` |

**"Listo para remate" NO es un `status`**: es `in_extension` con
`extension_ends_at` pasado, que es lo que consulta
`GET /contracts/ready-for-auction`. Por eso el conteo por estado muestra 8
`in_extension`: 4 en prórroga vigente + 4 vencidas.

## Restricción que gobierna todas las fechas

`interest_paid_until` debe caer en un número ENTERO de meses desde
`start_date` (`IMPORT_DATES_MISALIGNED`) — el modelo solo entiende meses
completos anclados al día de inicio. Acá cada contrato declara `start_date` y
`meses` y el `interest_paid_until` se DERIVA con `rules.add_months`, la misma
función del backend: es imposible que este archivo y el servidor discrepen.

## Efectos colaterales, a propósito

- Los 3 `paid` generan un `contract_payment` y su `cash_movement` — **por
  transferencia a Bancolombia**, para no distorsionar el conteo de efectivo del
  cajón de la sesión abierta.
- Los 3 `auctioned` crean su `inventory_item` en `draft` y su
  `inventory_entry`, que es lo que hace el remate. Quedan sin publicar.

## Idempotente

`Idempotency-Key = legacy_code` (la recomendación operativa del doc de
migración): reejecutar no duplica nada. Todo lleva `legacy_code` con prefijo
`DEMO-` y una nota fechada, así que el rastro es localizable y borrable —
`--limpiar` lo hace.

## Uso

    cd backend-starter
    python scripts/qa/seed_contratos.py            # siembra
    python scripts/qa/seed_contratos.py --verificar # solo cuenta lo que hay
    python scripts/qa/seed_contratos.py --limpiar   # borra lo sembrado
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))

import qa  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.modules.contracts import rules  # noqa: E402

# ---------------------------------------------------------------- empresa ---
COMPANY_ID = "f1aa473d-b8df-457b-bcf0-0fcbe06db6fe"  # LA GRAN LEGAL
ADMIN_ROLE_ID = "2550c586-06be-4b49-9d0b-454f75b4c230"

#: El usuario que firma los datos de prueba. Nombre explícito a propósito: en
#: la UI se lee "creado por Datos de prueba (QA)", que es lo que distingue esto
#: del trabajo real de la empresa.
ACTOR_EMAIL = "qa.datos.prueba@qalab.com"
ACTOR_NAME = "Datos de prueba (QA)"

BANCOLOMBIA = "85187e8e-6134-4e4d-862b-25c86fd382c3"  # cuenta bank, para los abonos

# Categorías nivel 3 (el import las exige) y el snapshot que hereda cada una.
# Joyería define plazo 4 / mora 5; Tecnología plazo 2 / mora 1 — la ventana de
# 1 mes es lo que hace que un contrato de Tecnología NUNCA pase por `in_arrears`.
ITALIANO = "678051ac-a06f-4d59-9e14-f1b69333b2b2"
NACIONAL = "2f84b029-b435-4384-aaa8-d761f9a00927"
PLATA = "e137ffe8-76d6-4bf6-bb20-620c8cdfc4bd"
IPHONE = "3a102bc0-f0d1-4c72-9acc-f1101709fd18"
SAMSUNG = "697cbbb5-2a69-4e92-a431-9e73cf3d8527"
APPLE = "e10dde0c-f411-4ea0-a9fe-59a6ce711d71"
DELL = "9551281a-b0b5-43de-9296-c4b10a3ab783"

JOYERIA = {"term_months": 4, "arrears_window_months": 5, "extension_months": 1}
TECNO = {"term_months": 2, "arrears_window_months": 1, "extension_months": 1}

CUSTOMERS = [
    "3417b8b7-392b-4fe0-bc84-bc99f56d0ac0",  # Pepito Perez
    "0379333a-7b6d-4fcd-a82a-9c4eba62ad19",  # darly vergara
    "94873bc1-1945-4e76-a6e5-58629764855c",  # martha delsy melguiso
    "aa89c17c-3887-442f-80ad-04def5defab3",  # mateo jaramillo quiroga
    "f219e938-ced5-404e-8253-bfb266f9211a",  # Wendy Andrade
]

NOTE = "Datos de prueba sembrados el 09/09/2026 (scripts/qa/seed_contratos.py). Borrables."


# ------------------------------------------------------------- el catálogo ---
@dataclass
class Seed:
    """Un contrato a sembrar. `meses` es N en `interest_paid_until =
    start_date + N meses`: la fecha se deriva, nunca se escribe a mano, para
    no poder desalinearla (`IMPORT_DATES_MISALIGNED`)."""

    code: str
    bucket: str
    snapshot: dict[str, int]
    start: date
    meses: int
    principal: int
    capital: int
    rate: str
    items: list[dict]
    appraisal: int | None = None
    #: Para los `paid`: el abono que los salda. Se calcula contra la cotización
    #: real del backend, no acá.
    payoff: bool = False
    #: Para los `auctioned`: se remata después de importar.
    auction: bool = False
    resultado: dict = field(default_factory=dict)

    @property
    def ipu(self) -> date:
        return rules.add_months(self.start, self.meses)


def _joya(cat: str, desc: str, gramos: str, avaluo: int) -> dict:
    return {
        "category_id": cat,
        "description": desc,
        "weight_grams": gramos,
        "item_appraisal": avaluo,
        "photos": [],
    }


def _tec(cat: str, desc: str, serial: str, avaluo: int) -> dict:
    return {
        "category_id": cat,
        "description": desc,
        "serial_imei": serial,
        "item_appraisal": avaluo,
        "photos": [],
    }


# Las fechas se eligieron contra hoy = 2026-09-09 (zona de la empresa). El
# script comprueba el estado REAL que devolvió el backend contra `bucket`, así
# que si se corre otro día y una fecha ya no produce el estado esperado, FALLA
# en vez de sembrar algo distinto en silencio.
# `fmt: off` a propósito y no por descuido: esta lista es una TABLA DE DATOS,
# y está alineada a mano para poder leerla como tal — cada fila es un caso de
# prueba y las columnas se comparan de un vistazo. El formateador la explota a
# un argumento por línea (unas 300 líneas en vez de 80) y deja de verse qué
# distingue un caso del siguiente, que es justo para lo que existe el archivo.
# fmt: off
SEEDS: list[Seed] = [
    # ---- active: owed == 0 -------------------------------------------------
    Seed("DEMO-A1", "active", JOYERIA, date(2026, 5, 12), 3, 1_200_000, 1_200_000, "5",
         [_joya(ITALIANO, "Cadena oro 18k eslabón italiano", "18.40", 13_000_000)],
         appraisal=13_000_000),
    Seed("DEMO-A2", "active", JOYERIA, date(2026, 6, 20), 2, 800_000, 600_000, "5",
         [_joya(NACIONAL, "Anillo oro 18k con circón", "6.20", 1_050_000),
          _joya(NACIONAL, "Par de aretes oro 18k", "3.10", 520_000)],
         appraisal=1_570_000),
    Seed("DEMO-A3", "active", TECNO, date(2026, 8, 25), 0, 500_000, 500_000, "8",
         [_tec(IPHONE, "iPhone 13 128GB negro", "356789104523987", 2_600_000)],
         appraisal=2_600_000),
    # Pagó intereses por adelantado: `interest_paid_until` en el FUTURO. El doc
    # de migración lo declara válido y es el caso que nadie prueba nunca.
    Seed("DEMO-A4", "active", JOYERIA, date(2026, 4, 9), 6, 2_000_000, 1_500_000, "4.5",
         [_joya(ITALIANO, "Cadena oro 18k 60cm + dije", "31.75", 22_000_000)],
         appraisal=22_000_000),

    # ---- in_arrears: 1 <= owed < 5 (solo Joyería; Tecnología tiene N=1) ----
    Seed("DEMO-M1", "in_arrears", JOYERIA, date(2026, 4, 9), 4, 1_000_000, 1_000_000, "5",
         [_joya(NACIONAL, "Pulsera oro 18k tejido cubano", "14.80", 1_400_000)],
         appraisal=1_400_000),
    Seed("DEMO-M2", "in_arrears", JOYERIA, date(2026, 3, 9), 4, 1_500_000, 1_200_000, "5",
         [_joya(ITALIANO, "Cadena oro 18k 50cm", "21.30", 16_000_000)],
         appraisal=16_000_000),
    Seed("DEMO-M3", "in_arrears", JOYERIA, date(2026, 2, 9), 4, 600_000, 600_000, "6",
         [_joya(PLATA, "Cadena plata 925 con dije", "42.60", 780_000)],
         appraisal=780_000),
    Seed("DEMO-M4", "in_arrears", JOYERIA, date(2026, 1, 9), 4, 3_000_000, 2_400_000, "4",
         [_joya(ITALIANO, "Cadena oro 18k 70cm eslabón grueso", "45.20", 32_000_000),
          _joya(NACIONAL, "Anillo de sello oro 18k", "11.40", 1_900_000)],
         appraisal=33_900_000),

    # ---- in_extension con prórroga VIGENTE (extension_ends_at >= hoy) ------
    Seed("DEMO-P1", "in_extension", JOYERIA, date(2025, 12, 9), 4, 900_000, 900_000, "5",
         [_joya(NACIONAL, "Anillo de matrimonio oro 18k", "7.90", 1_150_000)],
         appraisal=1_150_000),
    Seed("DEMO-P2", "in_extension", JOYERIA, date(2025, 11, 20), 4, 2_500_000, 2_000_000, "4.5",
         [_joya(ITALIANO, "Cadena oro 18k 65cm", "36.10", 27_000_000)],
         appraisal=27_000_000),
    Seed("DEMO-P3", "in_extension", TECNO, date(2026, 6, 9), 2, 700_000, 700_000, "8",
         [_tec(SAMSUNG, "Samsung Galaxy S23 256GB", "352019887654321", 1_900_000)],
         appraisal=1_900_000),
    Seed("DEMO-P4", "in_extension", TECNO, date(2026, 5, 25), 2, 400_000, 400_000, "8",
         [_tec(IPHONE, "iPhone 11 64GB blanco", "356123409876543", 1_100_000)],
         appraisal=1_100_000),

    # ---- prórroga VENCIDA: aparecen en GET /contracts/ready-for-auction ----
    Seed("DEMO-R1", "vencida", JOYERIA, date(2025, 10, 9), 4, 1_100_000, 1_100_000, "5",
         [_joya(NACIONAL, "Gargantilla oro 18k", "12.60", 1_450_000)],
         appraisal=1_450_000),
    Seed("DEMO-R2", "vencida", JOYERIA, date(2025, 8, 15), 4, 1_800_000, 1_500_000, "5",
         [_joya(ITALIANO, "Cadena oro 18k 55cm + medalla", "24.90", 2_300_000)],
         appraisal=2_300_000),
    Seed("DEMO-R3", "vencida", TECNO, date(2026, 4, 9), 2, 450_000, 450_000, "8",
         [_tec(APPLE, "MacBook Air M1 8/256", "C02FL1TXQ6L4", 3_400_000)],
         appraisal=3_400_000),
    Seed("DEMO-R4", "vencida", TECNO, date(2026, 3, 30), 2, 950_000, 950_000, "7.5",
         [_tec(DELL, "Dell Inspiron 15 i5 16/512", "8XKQ2Z3", 2_100_000)],
         appraisal=2_100_000),

    # ---- auctioned: se importan con prórroga vencida y se rematan ----------
    Seed("DEMO-X1", "auctioned", JOYERIA, date(2025, 9, 20), 4, 1_300_000, 1_300_000, "5",
         [_joya(NACIONAL, "Anillo oro 18k con esmeralda", "9.30", 1_650_000)],
         appraisal=1_650_000, auction=True),
    Seed("DEMO-X2", "auctioned", JOYERIA, date(2025, 7, 5), 4, 2_200_000, 1_900_000, "4.5",
         [_joya(ITALIANO, "Cadena oro 18k 60cm eslabón barbado", "29.70", 2_800_000)],
         appraisal=2_800_000, auction=True),
    Seed("DEMO-X3", "auctioned", TECNO, date(2026, 2, 18), 2, 600_000, 600_000, "8",
         [_tec(SAMSUNG, "Samsung Galaxy A54 128GB", "353987123456780", 1_250_000)],
         appraisal=1_250_000, auction=True),

    # ---- paid: se importan y se saldan (abono por TRANSFERENCIA) -----------
    Seed("DEMO-S1", "paid", JOYERIA, date(2026, 4, 9), 4, 500_000, 500_000, "5",
         [_joya(PLATA, "Pulsera plata 925", "28.40", 620_000)],
         appraisal=620_000, payoff=True),
    Seed("DEMO-S2", "paid", JOYERIA, date(2026, 5, 9), 4, 1_000_000, 1_000_000, "5",
         [_joya(NACIONAL, "Dije oro 18k con cadena corta", "8.70", 1_250_000)],
         appraisal=1_250_000, payoff=True),
    Seed("DEMO-S3", "paid", TECNO, date(2026, 5, 9), 2, 350_000, 350_000, "8",
         [_tec(IPHONE, "iPhone SE 2020 64GB", "356444555666777", 900_000)],
         appraisal=900_000, payoff=True),
]
# fmt: on


# ------------------------------------------------------------------ actor ----
def ensure_actor() -> qa.Client:
    """Crea (o reactiva) el usuario que firma los datos y devuelve su cliente.

    No se puede invitar por API: `POST /identity/invitations` exige
    `identity.manage_users`, que exige ya ser usuario de la empresa. El
    bootstrap es el que documenta el RUNBOOK para el laboratorio — auth user
    con el `SUPABASE_SERVICE_ROLE_KEY` + fila `app_user` con el rol Admin —
    y no gasta cuota de correo.
    """
    h = qa.admin_headers()
    r = httpx.get(
        f"{qa.SUPABASE_URL}/auth/v1/admin/users",
        headers=h,
        params={"filter": ACTOR_EMAIL},
        timeout=qa.TIMEOUT,
    )
    r.raise_for_status()
    existing = [u for u in r.json().get("users", []) if u["email"] == ACTOR_EMAIL]
    if existing:
        uid = existing[0]["id"]
        httpx.put(
            f"{qa.SUPABASE_URL}/auth/v1/admin/users/{uid}",
            headers=h,
            json={"password": qa.TEST_PASSWORD, "email_confirm": True},
            timeout=qa.TIMEOUT,
        ).raise_for_status()
        print(f"  actor: auth user ya existía ({uid}), contraseña refijada")
    else:
        r = httpx.post(
            f"{qa.SUPABASE_URL}/auth/v1/admin/users",
            headers=h,
            json={"email": ACTOR_EMAIL, "password": qa.TEST_PASSWORD, "email_confirm": True},
            timeout=qa.TIMEOUT,
        )
        r.raise_for_status()
        uid = r.json()["id"]
        print(f"  actor: auth user creado ({uid})")

    r = httpx.post(
        f"{qa.SUPABASE_URL}/rest/v1/app_user",
        headers={**h, "Prefer": "resolution=merge-duplicates,return=representation"},
        json={
            "id": uid,
            "company_id": COMPANY_ID,
            "role_id": ADMIN_ROLE_ID,
            "full_name": ACTOR_NAME,
            "email": ACTOR_EMAIL,
            "status": "active",
        },
        timeout=qa.TIMEOUT,
    )
    if r.status_code >= 300:
        raise SystemExit(f"no se pudo crear la fila app_user: {r.status_code} {r.text}")

    client = qa.client_for(ACTOR_EMAIL, qa.TEST_PASSWORD, "seed-admin")
    claims = qa.decode_jwt(client.token)
    if claims.get("company_id") != COMPANY_ID:
        raise SystemExit(f"el JWT no trae company_id de LA GRAN LEGAL: {claims.get('company_id')}")
    print(f"  actor: JWT con company_id y role_id correctos (amr={claims.get('amr')})")
    return client


def deactivate_actor() -> None:
    """Deja el usuario técnico inactivo: es un admin con contraseña conocida
    dentro de la empresa de un cliente. Sin `active` el hook no le emite
    claims y no puede entrar. Reejecutar el script lo reactiva."""
    httpx.patch(
        f"{qa.SUPABASE_URL}/rest/v1/app_user",
        headers=qa.admin_headers(),
        params={"email": f"eq.{ACTOR_EMAIL}", "company_id": f"eq.{COMPANY_ID}"},
        json={"status": "inactive"},
        timeout=qa.TIMEOUT,
    )


# ------------------------------------------------------------- verificación --
def contar() -> None:
    """Cuenta lo que hay HOY en la empresa, por estado, separando la prórroga
    vencida (que no es un `status` sino `in_extension` + fecha pasada)."""
    c = ensure_actor()
    total: dict[str, int] = {}
    demo: dict[str, int] = {}
    cursor = None
    while True:
        path = "/contracts?limit=100" + (f"&cursor={cursor}" if cursor else "")
        r = c.get(path)
        if not r.ok:
            raise SystemExit(f"GET /contracts falló: {r.status_code} {r.body}")
        for row in r.body["items"]:
            total[row["status"]] = total.get(row["status"], 0) + 1
            if (row["legacy_code"] or "").startswith("DEMO-"):
                demo[row["status"]] = demo.get(row["status"], 0) + 1
        cursor = r.body.get("next_cursor")
        if not cursor:
            break
    r = c.get("/contracts/ready-for-auction")
    listos = r.body if r.ok else []
    print("\n  Contratos por estado en LA GRAN LEGAL (total / de los que sembramos):")
    for st in sorted(set(total) | set(demo)):
        print(f"    {st:14s} {total.get(st, 0):3d}   ({demo.get(st, 0)} DEMO)")
    print(
        f"    {'LISTOS REMATE':14s} {len(listos):3d}"
        f"   ({sum(1 for x in listos if (x['legacy_code'] or '').startswith('DEMO-'))} DEMO)"
    )
    print(f"    {'TOTAL':14s} {sum(total.values()):3d}   ({sum(demo.values())} DEMO)")


def limpiar() -> None:
    """Borra lo sembrado. Va por el service role porque no hay endpoint de
    borrado de contratos, y no lo habrá: un contrato no se borra, se salda o
    se remata (`audit_log` es inmutable y esto no lo toca).

    Todo se localiza por ID, nunca por tipo: borrar `cash_movement` por
    `reference_type = 'contract_payment'` alcanzaría abonos reales de la
    empresa. Los ids de los abonos DEMO se leen primero y el borrado va contra
    esa lista exacta.
    """
    h = qa.admin_headers()
    r = httpx.get(
        f"{qa.SUPABASE_URL}/rest/v1/contract",
        headers=h,
        params={
            "select": "id,legacy_code",
            "company_id": f"eq.{COMPANY_ID}",
            "legacy_code": "like.DEMO-%",
        },
        timeout=qa.TIMEOUT,
    )
    contratos = [row["id"] for row in r.json()]
    if not contratos:
        print("  nada que borrar")
        return
    inc = f"in.({','.join(contratos)})"

    def ids_de(table: str, filtro: dict[str, str]) -> list[str]:
        rr = httpx.get(
            f"{qa.SUPABASE_URL}/rest/v1/{table}",
            headers=h,
            params={"select": "id", "company_id": f"eq.{COMPANY_ID}", **filtro},
            timeout=qa.TIMEOUT,
        )
        return [row["id"] for row in rr.json()] if rr.status_code == 200 else []

    pagos = ids_de("contract_payment", {"contract_id": inc})
    articulos = ids_de("inventory_item", {"source_contract_id": inc})
    print(
        f"  borrando {len(contratos)} contratos DEMO, {len(pagos)} abonos "
        f"y {len(articulos)} artículos de remate…"
    )

    plan: list[tuple[str, dict[str, str]]] = []
    if pagos:
        plan.append(("cash_movement", {"reference_id": f"in.({','.join(pagos)})"}))
        plan.append(("contract_payment", {"id": f"in.({','.join(pagos)})"}))
    if articulos:
        # El lote del remate cuelga de un inventory_entry; sus líneas primero.
        plan.append(("inventory_entry_line", {"item_id": f"in.({','.join(articulos)})"}))
    # El vínculo bidireccional contrato↔inventario impide borrar el artículo
    # mientras la prenda lo apunte: se suelta antes.
    plan.append(("contract_item", {"contract_id": inc}))
    if articulos:
        plan.append(("inventory_item", {"id": f"in.({','.join(articulos)})"}))
    plan.append(("contract", {"id": inc}))

    for table, params in plan:
        rr = httpx.delete(
            f"{qa.SUPABASE_URL}/rest/v1/{table}",
            headers=h,
            params={"company_id": f"eq.{COMPANY_ID}", **params},
            timeout=qa.TIMEOUT,
        )
        print(f"    {table}: {rr.status_code} {rr.text[:120] if rr.status_code >= 300 else ''}")


# ------------------------------------------------------------------ siembra --
def sembrar() -> None:
    hoy_local = date.today()
    print(f"\n  Sembrando en LA GRAN LEGAL · {len(SEEDS)} contratos · hoy(local)={hoy_local}")
    c = ensure_actor()

    creados = 0
    for s in SEEDS:
        body = {
            "legacy_code": s.code,
            "customer_id": CUSTOMERS[creados % len(CUSTOMERS)],
            "principal": s.principal,
            "capital_balance": s.capital,
            "interest_rate_pct": s.rate,
            "start_date": s.start.isoformat(),
            "interest_paid_until": s.ipu.isoformat(),
            "items": s.items,
            "appraisal_value": s.appraisal,
            "notes": NOTE,
            **s.snapshot,
        }
        r = c.post("/contracts/import", json=body, idem=s.code)
        if not r.ok:
            qa.check(f"{s.code} import", False, f"{r.status_code} {r.code} {r.body}", "alta")
            continue
        s.resultado = r.body
        creados += 1
        got = r.body["status"]
        ends = r.body["extension_ends_at"]
        # `vencida` y `auctioned` se importan igual: `in_extension` con la
        # prórroga ya pasada (lo que `POST /auction` exige). La diferencia es
        # que los `auctioned` se rematan después.
        if s.bucket in ("vencida", "auctioned"):
            ok = got == "in_extension" and ends is not None and date.fromisoformat(ends) < hoy_local
            esperado = "in_extension con prórroga vencida"
        elif s.bucket == "paid":
            # El estado al importar no importa: lo que importa es que se pueda
            # saldar, y eso lo comprueba el paso siguiente.
            ok = got in ("active", "in_arrears", "in_extension")
            esperado = "un estado vivo"
        else:
            ok = got == s.bucket
            esperado = s.bucket
        qa.check(
            f"{s.code} → {got}" + (f" (prórroga hasta {ends})" if ends else ""),
            ok,
            f"esperaba {esperado}, ipu={s.ipu} ends={ends}",
            "alta",
        )

    # ---- saldar los `paid` -------------------------------------------------
    for s in SEEDS:
        if not s.payoff or not s.resultado:
            continue
        cid = s.resultado["id"]
        q = c.get(f"/contracts/{cid}/payment-options")
        if not q.ok:
            qa.check(f"{s.code} cotización", False, str(q.body), "alta")
            continue
        owed = q.body["months_owed"]
        r = c.post(
            f"/contracts/{cid}/payments",
            json={
                "months_covered": owed,
                "capital_amount": str(Decimal(s.capital)),
                "payment_method": "transfer",
                "account_id": BANCOLOMBIA,
            },
            idem=f"{s.code}-PAYOFF",
        )
        if not r.ok:
            qa.check(f"{s.code} saldar", False, f"{r.status_code} {r.code} {r.body}", "alta")
            continue
        det = c.get(f"/contracts/{cid}")
        qa.check(
            f"{s.code} → paid (recibo #{r.body['receipt_number']}, "
            f"{owed} mes(es) + capital, total {r.body['total']})",
            det.ok and det.body["status"] == "paid",
            str(det.body),
            "alta",
        )

    # ---- rematar los `auctioned` ------------------------------------------
    for s in SEEDS:
        if not s.auction or not s.resultado:
            continue
        cid = s.resultado["id"]
        # `POST /auction` no pide `Idempotency-Key`: es idempotente por el
        # estado (un contrato ya rematado ya no está `in_extension`, así que
        # un segundo intento responde CONTRACT_NOT_READY_FOR_AUCTION).
        r = c.post(f"/contracts/{cid}/auction")
        if not r.ok:
            det = c.get(f"/contracts/{cid}")
            ya = det.ok and det.body["status"] == "auctioned"
            qa.check(
                f"{s.code} → auctioned",
                ya,
                f"{r.status_code} {r.code} {r.body}",
                "alta",
            )
            continue
        qa.check(f"{s.code} → auctioned", r.body["status"] == "auctioned", str(r.body), "alta")

    qa.save(
        "seed_contratos",
        [
            {
                "code": s.code,
                "bucket": s.bucket,
                "id": s.resultado.get("id"),
                "number": s.resultado.get("number"),
                "status": s.resultado.get("status"),
            }
            for s in SEEDS
        ],
    )
    contar()

    if qa.FINDINGS:
        print(f"\n  ⚠ {len(qa.FINDINGS)} comprobaciones fallaron:")
        for f in qa.FINDINGS:
            print(f"    - {f['name']}: {f['detail']}")
    else:
        print("\n  Todas las comprobaciones pasaron.")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if arg == "--verificar":
            contar()
        elif arg == "--limpiar":
            limpiar()
        else:
            sembrar()
    finally:
        if arg != "--dejar-actor-activo":
            deactivate_actor()
            print(f"\n  actor {ACTOR_EMAIL} dejado INACTIVO (no puede entrar a la app).")
