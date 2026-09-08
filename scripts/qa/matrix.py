"""Matriz de permisos: cada endpoint x cada rol.

Técnica: `require_permission` es un Depends, se evalúa ANTES del body y de la
query. Así que un request con body vacío y un UUID inexistente:
  - devuelve 403 PERMISSION_DENIED si al rol le falta el permiso
  - devuelve 422 / 404 / 400 si lo tiene (y entonces murió por otra razón)
No crea ni modifica nada.
"""
import json, uuid, sys
import qa

FAKE = "00000000-0000-4000-8000-000000000000"
rows = json.load(open(qa.SCRATCH / "endpoint_map.json"))
# corrección manual: estos dos exigen DOS permisos (helper _closings)
for r in rows:
    if r["path"].endswith(("/reports/closings", "/reports/closings-breakdown")):
        r["permission"] = "reports.view+cashbox.view_history"

sessions = qa.load("sessions")
ACTORS = ["Admin", "Moderador", "Asesor", "Bodega"]
clients = {a: qa.Client(a, sessions[a]["token"]) for a in ACTORS}
perms = {a: set(sessions[a]["permissions"]) for a in ACTORS}

def fill(path: str) -> str:
    out = []
    for seg in path.split("/"):
        out.append(FAKE if seg.startswith("{") else seg)
    return "/".join(out)

def expected_403(actor: str, permission: str | None) -> bool | None:
    if permission in (None, "AUTENTICADO", "PUBLICO"):
        return False
    if permission == "SUPER_ADMIN":
        return True          # ninguno de los 4 es super-admin
    needed = set(permission.split("+"))
    return not needed.issubset(perms[actor])

results = []
targets = [r for r in rows if not r["path"].startswith("/api/v1/platform")]
platform = [r for r in rows if r["path"].startswith("/api/v1/platform")]
print(f"Barriendo {len(targets)} endpoints tenant x 4 roles = {len(targets)*4} requests")
print(f"(+ {len(platform)} de /platform, que se prueban aparte)\n")

for i, r in enumerate(targets):
    path = fill(r["path"]).replace("/api/v1", "")
    for actor in ACTORS:
        c = clients[actor]
        kw = {"json": {}} if r["method"] in ("POST", "PATCH", "PUT") else {}
        res = c.request(r["method"], path, idem=r["idempotency"], **kw)
        got_403 = res.status == 403
        exp = expected_403(actor, r["permission"])
        ok = (got_403 == exp)
        results.append({
            "endpoint": f'{r["method"]} {r["path"]}', "actor": actor,
            "permission": r["permission"], "expected_403": exp,
            "status": res.status, "code": res.code, "ok": ok,
        })
    if (i + 1) % 20 == 0:
        print(f"  … {i+1}/{len(targets)}", flush=True)

json.dump(results, open(qa.SCRATCH / "matrix_results.json", "w"), indent=2, ensure_ascii=False)
bad = [r for r in results if not r["ok"]]
print(f"\n{len(results)} comprobaciones · {len(results)-len(bad)} coinciden · {len(bad)} DISCREPAN")
