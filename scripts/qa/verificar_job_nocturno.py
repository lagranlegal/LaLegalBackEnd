#!/usr/bin/env python3
"""Guardián de la Machine programada del job nocturno en Fly.

POR QUÉ ESTO ES UN SCRIPT Y NO UN TEST
--------------------------------------
Es una invariante de INFRAESTRUCTURA VIVA: depende de lo que hay desplegado en
Fly en este momento, no del código. Ningún test contra base efímera puede verla,
y su violación es **silenciosa** por construcción: el job simplemente no corre, o
corre con una imagen vieja, y nadie se entera hasta que alguien va a buscar el
daño a mano.

Ya costó dos incidentes:

1. **27/08/2026** — la Machine fue borrada por error, tomada por "máquina
   huérfana". Ninguna suscripción llegó nunca a `expired`, y eso tapó que una
   suscripción vencida no se podía renovar por ninguna vía: la empresa quedaba
   muerta para siempre.
2. **F21-10 (10–21/09/2026)** — `fly deploy` **no** actualiza esta Machine, así
   que quedó clavada a su imagen del 08/09, sin la guarda de `compute_status`
   que había entrado el 10/09. Once días recalculando contratos ya reemplazados
   por una ampliación como si siguieran vivos: 4 contratos dañados, cartera
   inflada y un contrato sustituido a punto de salir a remate.
   Ver `docs/QA_AUDITORIA.md` §F21-10.

Y se descubrió de paso que **`fly secrets set` tampoco la actualiza**: el rolling
update toca solo la máquina del grupo `app`.

LA CAUSA COMÚN, QUE SIGUE ABIERTA A PROPÓSITO
---------------------------------------------
La Machine **no tiene process group** (su `metadata` está vacía), así que toda
operación de `flyctl` que itere por grupo la saltea — y a ojo es indistinguible
de basura.

**No se le puso uno, y la decisión es deliberada:** ponerle
`fly_process_group=nightly` sin declararlo en `fly.dev.toml` puede hacer que el
próximo `fly deploy` la trate como huérfana de un grupo inexistente y la borre;
y declararlo en el toml hace que `fly deploy` la gestione y pueda recrearla
**sin** el `schedule`, que es exactamente el modo de falla de F21-10. El arreglo
causaría el problema que quiere evitar.

Así que en vez de tocar la máquina frágil, se vigila. Este script convierte tres
riesgos invisibles en una señal con código de salida.

QUÉ VERIFICA
------------
1. Que la Machine `nightly-job` **exista**.
2. Que tenga `schedule` (si se pierde, el job deja de correr y su ausencia es
   silenciosa: no hay health check ni alerta).
3. Que su **imagen coincida** con el release actual de la app. Esta es la que
   F21-10 rompió, y la que nadie estaba mirando.

Sale con código 1 si alguna falla. Solo lectura: no ejecuta ninguna mutación.

USO
---
    python scripts/qa/verificar_job_nocturno.py
    FLY_APP=compraventa-backend-prod python scripts/qa/verificar_job_nocturno.py

Requiere `flyctl` autenticado (`flyctl auth whoami`). Si no lo está, el script
lo dice y sale con 2 — "no se pudo verificar" no es lo mismo que "está sano", y
confundirlos sería repetir el error que este script existe para evitar.
"""

from __future__ import annotations

import json
import os
import subprocess

APP = os.environ.get("FLY_APP", "compraventa-backend-dev")
NOMBRE_MACHINE = os.environ.get("FLY_NIGHTLY_MACHINE", "nightly-job")


def _fly(*args: str) -> str:
    try:
        p = subprocess.run(
            ["flyctl", *args], capture_output=True, text=True, timeout=90, check=False
        )
    except FileNotFoundError:
        print("  ERROR: `flyctl` no está en el PATH.")
        raise SystemExit(2) from None
    except subprocess.TimeoutExpired:
        print("  ERROR: `flyctl` no respondió en 90s.")
        raise SystemExit(2) from None
    if p.returncode != 0:
        print(f"  ERROR: `flyctl {' '.join(args)}` falló:\n    {p.stderr.strip()[:400]}")
        raise SystemExit(2)
    return p.stdout


def _tag(image: str) -> str:
    """`registry.fly.io/app:deployment-XXX@sha256:...` -> `deployment-XXX`.

    La Machine guarda tag + digest y el release solo el tag, así que se compara
    por tag: es lo que identifica el deploy.
    """
    sin_digest = image.split("@", 1)[0]
    return sin_digest.rsplit(":", 1)[-1] if ":" in sin_digest else sin_digest


def main() -> int:
    print(f"\n  Guardián del job nocturno — app `{APP}`  (SOLO LECTURA)\n")

    machines = json.loads(_fly("machine", "list", "--app", APP, "--json") or "[]")
    releases = json.loads(_fly("releases", "--app", APP, "--json") or "[]")

    fallas: list[str] = []

    # 1 · existe
    job = next((m for m in machines if m.get("name") == NOMBRE_MACHINE), None)
    if job is None:
        nombres = ", ".join(sorted(m.get("name", "?") for m in machines)) or "(ninguna)"
        print(f"  [ROTA] la Machine `{NOMBRE_MACHINE}` NO EXISTE. Máquinas presentes: {nombres}")
        print("\n  El job nocturno no está corriendo. Ya pasó el 27/08/2026: se borró")
        print("  como 'máquina huérfana' y ninguna suscripción llegó nunca a `expired`.")
        return 1
    print(f"  [OK  ] la Machine `{NOMBRE_MACHINE}` existe ({job.get('id')})")

    cfg = job.get("config", {}) or {}

    # 2 · schedule
    schedule = cfg.get("schedule")
    if not schedule:
        fallas.append(
            "sin `schedule`: la Machine existe pero NO se dispara sola. "
            "Arreglo: `flyctl machine update <id> --schedule daily --app " + APP + "`"
        )
        print("  [ROTA] no tiene `schedule` — existe pero no corre")
    else:
        print(f"  [OK  ] `schedule` = {schedule}")

    # 3 · imagen al día (la causa de F21-10)
    tag_job = _tag(cfg.get("image") or "")
    tag_release = ""
    if releases:
        r = releases[0]
        tag_release = _tag(r.get("ImageRef") or r.get("imageRef") or "")
    if not tag_release:
        fallas.append("no se pudo leer la imagen del release actual de la app")
        print("  [ ?  ] no se pudo determinar la imagen del release actual")
    elif tag_job != tag_release:
        fallas.append(
            f"imagen DESACTUALIZADA: la Machine corre `{tag_job}` y la app `{tag_release}`. "
            f"Arreglo: `flyctl machine update {job.get('id')} --image "
            f"registry.fly.io/{APP}:{tag_release} --app {APP}` y **verificar que el "
            "`schedule` sobreviva`"
        )
        print(f"  [ROTA] imagen vieja — Machine `{tag_job}` vs app `{tag_release}`")
    else:
        print(f"  [OK  ] imagen al día ({tag_release})")

    # informativo: el process group vacío es la causa común, y sigue así a propósito
    if not (cfg.get("metadata") or {}).get("fly_process_group"):
        print(
            "\n  [aviso] la Machine no tiene process group: `fly deploy` y "
            "`fly secrets set`\n          la saltean, y a ojo parece huérfana. "
            "Es deliberado — ver el docstring."
        )

    if fallas:
        print("\n  ROTO. Qué pasa y cómo se arregla:\n")
        for f in fallas:
            print(f"   - {f}\n")
        return 1

    print("\n  OK — el job nocturno existe, se dispara solo y corre la imagen desplegada.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
