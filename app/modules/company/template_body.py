"""Reglas sobre el CUERPO de una plantilla de documento (ProseMirror/Tiptap).

Puras, sin base de datos: el servicio las aplica al crear, editar y activar.

El render es del front (`TemplateRenderer`), así que el backend no dibuja
nada; lo que sí puede y debe decidir es si un cuerpo es un documento del
editor y si imprimiría algo. Hasta la auditoría de QA (Fase 8) solo se
preguntaba `len(content) > 0`, y eso lo cumplían `{"content": [1, 2]}` y un
párrafo en blanco — dos cuerpos que se activaban y dejaban los contratos en
70 caracteres (F8-01, F8-03, F8-11).
"""

from typing import Any

#: Nodos que imprimen algo por sí solos aunque no lleven texto: el campo
#: dinámico, la tabla de prendas, el bloque de firma y la cláusula de avisos.
#: Los nombres son los de `frontend/src/lib/documents/nodes/*`.
_NODOS_QUE_IMPRIMEN = frozenset(
    {"mergeField", "itemsTableBlock", "signatureBlock", "noticeConsentClause"}
)

#: Un documento del editor nunca pasa de unos pocos niveles (doc → lista →
#: ítem → párrafo → texto). El tope solo existe para que un JSON hostil no
#: agote la pila de la recursión.
_PROFUNDIDAD_MAXIMA = 40


def es_documento_valido(body: Any) -> bool:
    """¿Es `body` un documento que el editor pudo haber producido?

    Tiptap (`editor.getJSON()`) siempre entrega `{"type": "doc", ...}`; cada
    nodo es un objeto con `type` de texto, y `content`, `marks`, `attrs` y
    `text` —si vienen— tienen su forma. No se valida la lista cerrada de tipos
    de nodo: el renderer ya ignora los que no conoce, y cerrarla aquí obligaría
    a desplegar el backend por cada extensión nueva del editor.
    """
    return (
        isinstance(body, dict) and body.get("type") == "doc" and _nodo_valido(body, profundidad=0)
    )


def _nodo_valido(nodo: Any, *, profundidad: int) -> bool:
    if profundidad > _PROFUNDIDAD_MAXIMA or not isinstance(nodo, dict):
        return False
    if not isinstance(nodo.get("type"), str) or not nodo["type"]:
        return False
    if "text" in nodo and not isinstance(nodo["text"], str):
        return False
    if "attrs" in nodo and not isinstance(nodo["attrs"], dict | None):
        return False
    if "marks" in nodo and not isinstance(nodo["marks"], list):
        return False
    contenido = nodo.get("content")
    if contenido is None:
        return True
    if not isinstance(contenido, list):
        return False
    return all(_nodo_valido(hijo, profundidad=profundidad + 1) for hijo in contenido)


def _recorrer(nodo: Any) -> list[dict[str, Any]]:
    """Todos los nodos del árbol, en orden de documento (supone uno válido)."""
    pila = [nodo]
    salida: list[dict[str, Any]] = []
    while pila:
        actual = pila.pop()
        if not isinstance(actual, dict):
            continue
        salida.append(actual)
        hijos = actual.get("content")
        if isinstance(hijos, list):
            pila.extend(reversed(hijos))
    return salida


def _clave_campo(nodo: dict[str, Any]) -> str:
    attrs = nodo.get("attrs") or {}
    clave = attrs.get("key") if isinstance(attrs, dict) else None
    return clave.strip() if isinstance(clave, str) else ""


def tiene_contenido(body: Any) -> bool:
    """¿Este documento imprimiría algo?

    Cuenta el texto que no es solo espacios y los nodos que imprimen sin texto
    (`_NODOS_QUE_IMPRIMEN`; un campo dinámico, solo si nombra un campo). Un
    `{}`, un `{"type": "doc", "content": []}` o un párrafo vacío son
    documentos válidos para el editor, pero en papel no dejan nada.
    """
    if not es_documento_valido(body):
        return False
    for nodo in _recorrer(body):
        tipo = nodo["type"]
        if tipo == "text" and nodo.get("text", "").strip():
            return True
        if tipo == "mergeField":
            if _clave_campo(nodo):
                return True
        elif tipo in _NODOS_QUE_IMPRIMEN:
            return True
    return False


#: Lo que un contrato de empeño no puede dejar de decir: a quién se le prestó,
#: sobre qué prendas y la firma de quien las entrega. Es el mínimo de lo que
#: la auditoría encontró faltando en el contrato de 70 caracteres. Las etiquetas
#: son las del catálogo del editor (`MERGE_FIELDS` / nodos del front), para que
#: el mensaje le diga a la empresa qué insertar con las palabras que ve.
_REQUISITOS_CONTRATO: tuple[tuple[str, str], ...] = (
    ("cliente.nombre", "el campo «Nombre del cliente»"),
    ("itemsTableBlock", "la tabla de prendas"),
    ("signatureBlock:cliente", "la firma del cliente"),
)


def faltantes_para_activar(document_type: str, body: Any) -> list[str]:
    """Qué le falta a una plantilla para poder ser la ACTIVA de su tipo.

    Solo el contrato tiene mínimos: el paz y salvo es una constancia de la
    empresa y la plantilla de partida del front no lleva firma del cliente.
    Supone un cuerpo ya validado con `tiene_contenido`.
    """
    if document_type != "contract":
        return []
    presentes: set[str] = set()
    for nodo in _recorrer(body):
        tipo = nodo["type"]
        if tipo == "mergeField":
            presentes.add(_clave_campo(nodo))
        elif tipo == "itemsTableBlock":
            presentes.add("itemsTableBlock")
        elif tipo == "signatureBlock":
            attrs = nodo.get("attrs") or {}
            # `cliente` es el default del nodo (`SignatureBlockNode.tsx`): un
            # bloque sin `attrs` es la firma del cliente.
            variante = attrs.get("variant", "cliente") if isinstance(attrs, dict) else "cliente"
            presentes.add(f"signatureBlock:{variante}")
    return [clave for clave, _ in _REQUISITOS_CONTRATO if clave not in presentes]


def describir_faltantes(claves: list[str]) -> list[str]:
    etiquetas = dict(_REQUISITOS_CONTRATO)
    return [etiquetas[c] for c in claves]
