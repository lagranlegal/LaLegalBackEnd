"""Mapa canónico ruta -> permiso, sacado del AST de los routers.

Detecta el hueco que CLAUDE.md llama "bug de revisión": un endpoint sin
Depends(require_permission(...)).
"""

import ast
import json
import pathlib

OUT = pathlib.Path(__file__).parent / "_run" / "endpoint_map.json"
OUT.parent.mkdir(exist_ok=True)

BE = pathlib.Path(__file__).resolve().parents[2]  # la raíz de backend-starter
rows = []

for f in sorted(BE.glob("app/modules/*/router.py")):
    tree = ast.parse(f.read_text())
    mod = f.parent.name
    prefix = ""
    perm_vars: dict[str, str] = {}
    other_guards: dict[str, str] = {}

    for node in ast.walk(tree):
        # prefix del APIRouter
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            fn = node.value.func
            name = getattr(fn, "id", getattr(fn, "attr", ""))
            target = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
            if name == "APIRouter":
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
            elif name == "require_permission" and target:
                perm_vars[target] = node.value.args[0].value
            elif name in ("require_super_admin",) and target:
                other_guards[target] = "SUPER_ADMIN"

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if not (isinstance(fn, ast.Attribute) and getattr(fn.value, "id", "") == "router"):
                continue
            method = fn.attr.upper()
            path = dec.args[0].value if dec.args else ""
            # buscar Depends(...) en los argumentos de la función
            guard, deps = None, []
            src = ast.unparse(node.args)
            for var, code in perm_vars.items():
                if f"Depends({var})" in src:
                    guard = code
            for var, code in other_guards.items():
                if f"Depends({var})" in src:
                    guard = code
            if guard is None:
                if "require_permission(" in src:
                    i = src.index('require_permission("') + len('require_permission("')
                    guard = src[i : src.index('"', i)]
                elif "require_super_admin" in src:
                    guard = "SUPER_ADMIN"
                elif "get_current_user" in src or "CurrentUser" in src:
                    guard = "AUTENTICADO"
                else:
                    guard = None
            rows.append(
                {
                    "module": mod,
                    "method": method,
                    "path": prefix + path,
                    "permission": guard,
                    "fn": node.name,
                    "idempotency": "require_idempotency_key" in src,
                }
            )

rows.sort(key=lambda r: (r["module"], r["path"], r["method"]))
json.dump(rows, open(OUT, "w"), indent=2, ensure_ascii=False)

print(f"{len(rows)} endpoints mapeados\n")
sin = [r for r in rows if r["permission"] is None]
auth_only = [r for r in rows if r["permission"] == "AUTENTICADO"]
print(f"SIN ningún guard        : {len(sin)}")
for r in sin:
    print("   ", r["method"], r["path"], "→", r["fn"])
print(f"\nSolo AUTENTICADO (sin permiso): {len(auth_only)}")
for r in auth_only:
    print("   ", r["method"], r["path"], "→", r["fn"])
print(f"\nSUPER_ADMIN: {sum(1 for r in rows if r['permission'] == 'SUPER_ADMIN')}")
n_perm = sum(1 for r in rows if r["permission"] not in (None, "AUTENTICADO", "SUPER_ADMIN"))
print(f"Con permiso: {n_perm}")
print(f"Con Idempotency-Key: {sum(1 for r in rows if r['idempotency'])}")
