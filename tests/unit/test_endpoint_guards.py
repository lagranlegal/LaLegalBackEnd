"""Ningún endpoint sin guard: el «bug de revisión» de CLAUDE.md, en un test.

`CLAUDE.md` regla 3: *«todo endpoint lleva Depends(require_permission("modulo.accion")).
Deny-by-default: endpoint sin permiso explícito = error de revisión»*.

Hasta ahora eso se verificaba leyendo. Este test lo lee por nosotros: recorre
los routers con el AST y falla si aparece una ruta sin ningún guard. No toca
la red ni la base, así que corre en milisegundos y sirve de red para el
endpoint nuevo que alguien escriba con prisa.

La lista de excepciones es explícita y corta a propósito: cada entrada es una
decisión documentada, no un olvido.
"""

from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

# Rutas que a propósito NO llevan `require_permission`. Cada una con su porqué.
SIN_PERMISO_A_PROPOSITO = {
    # Información del propio usuario: pedirle un permiso para verse a sí mismo
    # dejaría fuera a quien todavía no tiene ninguno (API_GUIDE §2.6).
    ("GET", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
}

# `GET /api/v1/health` es público a propósito (lo usa el proxy, no una persona)
# y vive en `main.py`, fuera de los routers de módulo que este test recorre.


def _guard_de(fn: ast.FunctionDef | ast.AsyncFunctionDef, permisos: dict[str, str]) -> str | None:
    """Devuelve el guard que protege esta función, o None si no tiene ninguno."""
    firma = ast.unparse(fn.args)
    for var, code in permisos.items():
        if f"Depends({var})" in firma:
            return code
    if "require_permission(" in firma:
        return "inline"
    if "require_super_admin" in firma:
        return "SUPER_ADMIN"
    # Helpers que combinan dos permisos (p. ej. `_closings` en reports).
    if "Depends(_" in firma:
        return "helper"
    return None


def _rutas() -> list[tuple[str, str, str | None, str]]:
    encontradas = []
    for archivo in sorted(APP.glob("modules/*/router.py")):
        tree = ast.parse(archivo.read_text())
        prefijos: dict[str, str] = {}
        permisos: dict[str, str] = {}

        for nodo in ast.walk(tree):
            if not (isinstance(nodo, ast.Assign) and isinstance(nodo.value, ast.Call)):
                continue
            destino = nodo.targets[0]
            if not isinstance(destino, ast.Name):
                continue
            llamada = nodo.value.func
            nombre = getattr(llamada, "id", getattr(llamada, "attr", ""))
            if nombre == "APIRouter":
                for kw in nodo.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefijos[destino.id] = kw.value.value
            elif nombre == "require_permission":
                permisos[destino.id] = nodo.value.args[0].value

        for nodo in tree.body:
            if not isinstance(nodo, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for dec in nodo.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                fn = dec.func
                if not isinstance(fn, ast.Attribute):
                    continue
                router = getattr(fn.value, "id", "")
                if router not in prefijos:
                    continue
                path = prefijos[router] + (dec.args[0].value if dec.args else "")
                encontradas.append(
                    (fn.attr.upper(), path, _guard_de(nodo, permisos), archivo.parent.name)
                )
    return encontradas


def test_todo_endpoint_tiene_guard() -> None:
    rutas = _rutas()
    assert len(rutas) > 80, (
        f"solo se encontraron {len(rutas)} rutas — ¿cambió la forma de los routers?"
    )

    sin_guard = [
        (metodo, path, modulo)
        for metodo, path, guard, modulo in rutas
        if guard is None and (metodo, path) not in SIN_PERMISO_A_PROPOSITO
    ]
    assert not sin_guard, (
        "Endpoints sin `Depends(require_permission(...))` — deny-by-default (CLAUDE.md regla 3).\n"
        "Si alguno debe ser público, agrégalo a SIN_PERMISO_A_PROPOSITO con su porqué:\n"
        + "\n".join(f"  {m} {p}  ({mod})" for m, p, mod in sin_guard)
    )


def test_las_excepciones_siguen_existiendo() -> None:
    """Una excepción que ya no corresponde a ninguna ruta es basura que engaña.

    Sin esto, borrar un endpoint dejaría su permiso-excepción en la lista, y el
    día que alguien creara otro con el mismo path heredaría el permiso sin
    querer.
    """
    reales = {(m, p) for m, p, _, _ in _rutas()}
    huerfanas = SIN_PERMISO_A_PROPOSITO - reales
    assert not huerfanas, f"excepciones que ya no apuntan a ninguna ruta: {huerfanas}"
