"""Todo código de error del backend está en el catálogo de `API_GUIDE` §15.

*«Un código de error es un contrato entre dos capas, y nadie lo compila»* — es
el principio que este proyecto se ganó cuando el backend devolvía `NOT_FOUND`
donde el front escuchaba `CASH_SESSION_NOT_OPEN`. El front decide comportamiento
por `code` (modal de abrir caja, pantalla de bloqueo, error por campo), así que
un código que el backend inventa y la documentación no recoge es un contrato
que solo conoce una de las dos partes.

La auditoría de QA encontró **nueve** códigos así (Fase 1, H-08). Este test los
habría cazado el día que nacieron.

Mismo molde que `test_audit_actions.py`, que ya demostró que funciona:
leer lo que el código hace de verdad y compararlo con lo que decimos que hace.
"""

from __future__ import annotations

import pathlib
import re

RAIZ = pathlib.Path(__file__).resolve().parents[2]
APP = RAIZ / "app"
CATALOGO = RAIZ / "docs" / "API_GUIDE.md"

# Códigos que se generan pero no son de negocio: no van al catálogo.
NO_SON_DE_NEGOCIO = {
    "INTERNAL_ERROR",  # el 500 genérico del handler; no hay nada que el front pueda decidir
}


def _codigos_del_codigo() -> set[str]:
    """Todos los `code = "X"` y `code="X"` que el backend puede devolver."""
    encontrados: set[str] = set()
    for archivo in APP.rglob("*.py"):
        for m in re.finditer(r'\bcode\s*=\s*"([A-Z][A-Z0-9_]+)"', archivo.read_text()):
            encontrados.add(m.group(1))
    return encontrados - NO_SON_DE_NEGOCIO


def _codigos_documentados() -> set[str]:
    """Los que aparecen en la tabla del §15, donde la primera celda es el código."""
    texto = CATALOGO.read_text()
    # Solo la tabla del §15: el resto del documento tiene tablas de endpoints
    # cuya primera celda es un método HTTP, no un código de error.
    inicio = texto.index("## 15.")
    fin = texto.find("\n## ", inicio + 1)
    seccion = texto[inicio : fin if fin != -1 else len(texto)]
    documentados: set[str] = set()
    for linea in seccion.splitlines():
        if not linea.startswith("|"):
            continue
        primera = linea.split("|")[1]
        # una fila puede documentar dos códigos juntos: `CONFLICT` / `LAST_ADMIN_SAFEGUARD`
        documentados.update(re.findall(r"`([A-Z][A-Z0-9_]+)`", primera))
    return documentados


def test_todo_codigo_de_error_esta_documentado() -> None:
    sin_documentar = sorted(_codigos_del_codigo() - _codigos_documentados())
    assert not sin_documentar, (
        "Códigos de error que el backend devuelve y `docs/API_GUIDE.md` §15 no recoge.\n"
        "El front decide comportamiento por `code`: si no está documentado, la otra capa\n"
        "no sabe que existe. Agrégalos a la tabla con su HTTP y cuándo ocurre:\n"
        + "\n".join(f"  {c}" for c in sin_documentar)
    )


def test_el_catalogo_no_documenta_codigos_muertos() -> None:
    """Un código documentado que ya nadie devuelve manda a manejar algo imposible.

    Es el reverso del anterior y vale igual: el front puede estar escuchando por
    un `code` que el backend dejó de emitir hace meses, y esa rama de UI nunca
    se ejecuta — *«una rama de UI que nunca se ha visto no está escrita, está
    pendiente»*.
    """
    # `PERMISSION_DENIED`, `UNAUTHORIZED`, etc. los emite el middleware con otra
    # forma sintáctica; se listan acá para no dar un falso positivo.
    EMITIDOS_FUERA_DE_UN_LITERAL = {
        "UNAUTHORIZED",
        "PERMISSION_DENIED",
        "SUBSCRIPTION_EXPIRED",
        "NOT_FOUND",
        "CONFLICT",
        "BAD_REQUEST",
        "VALIDATION_ERROR",
        "IDEMPOTENCY_KEY_REQUIRED",
    }
    muertos = sorted(_codigos_documentados() - _codigos_del_codigo() - EMITIDOS_FUERA_DE_UN_LITERAL)
    assert not muertos, (
        "Códigos documentados que ningún módulo emite ya. Si se retiraron, sácalos\n"
        "del catálogo; si los emite el core con otra forma, agrégalos a la lista\n"
        "de excepciones de este test:\n" + "\n".join(f"  {c}" for c in muertos)
    )
