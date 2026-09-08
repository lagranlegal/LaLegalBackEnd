import json
import pathlib
from collections import defaultdict

res = json.load(open(pathlib.Path(__file__).parent / "_run" / "matrix_results.json"))
bad = [r for r in res if not r["ok"]]
print(f"{len(res)} comprobaciones · {len(res) - len(bad)} coinciden · {len(bad)} discrepan\n")

if bad:
    # agrupar por endpoint
    g = defaultdict(list)
    for r in bad:
        g[(r["endpoint"], r["permission"])].append(r)
    print("=== DISCREPANCIAS ===")
    for (ep, perm), rows in sorted(g.items()):
        print(f"\n{ep}   (permiso declarado: {perm})")
        for r in rows:
            esperado = "403" if r["expected_403"] else "NO 403"
            print(
                print(
                    f"    {r['actor']:10} esperado {esperado:6} → "
                    f"obtuvo {r['status']} {r['code'] or ''}"
                )
            )

# estadistica de codigos devueltos cuando SI tiene permiso
print("\n\n=== Códigos devueltos cuando el rol SÍ tiene el permiso ===")
c = defaultdict(int)
for r in res:
    if not r["expected_403"]:
        c[f"{r['status']} {r['code'] or ''}"] += 1
for k, v in sorted(c.items(), key=lambda x: -x[1]):
    print(f"  {v:4}  {k}")

print("\n=== Códigos devueltos cuando NO lo tiene ===")
c = defaultdict(int)
for r in res:
    if r["expected_403"]:
        c[f"{r['status']} {r['code'] or ''}"] += 1
for k, v in sorted(c.items(), key=lambda x: -x[1]):
    print(f"  {v:4}  {k}")
