"""Búsqueda por texto: el piso de caracteres y el prefijo de nombres.

EL PROBLEMA QUE RESUELVE (reportado por el cliente el 11/09/2026 como
"los buscadores solo filtran desde la quinta letra"). Eran dos causas
distintas, y ninguna era un umbral de cinco:

1. `plainto_tsquery` compara LEXEMAS ENTEROS. "Mateo" encuentra a Mateo;
   "Mate" no encuentra nada. Como los nombres de pila suelen tener cinco o
   seis letras, desde el mostrador se ve exactamente como un umbral de
   cinco — pero el mismo buscador tampoco encontraba "Jaramillo" con
   "Jaramill".

2. En contratos SÍ había un umbral literal de 5 para la cédula, puesto a
   propósito: teclear "5" hacía match por prefijo contra el documento de
   CUALQUIER cliente que empezara por 5, y un contrato ajeno aparecía como
   si fuera el buscado.

LA SOLUCIÓN: prefijo real (`to_tsquery` con el operador `:*`, que usa el
índice GIN que ya existe) con piso de tres caracteres.

**El piso va POR CLÁUSULA, nunca sobre la consulta entera.** El número de
contrato tiene que seguir encontrándose desde la primera tecla: los
consecutivos son cortos (1, 17, 213…) y un piso global rompería el
buscador que hoy funciona bien.
"""

import re

#: Desde cuántos caracteres tiene sentido filtrar por nombre o por documento.
#: Con menos, el resultado son cientos de filas que no responden nada — y en
#: el caso del documento, filas de OTRO cliente que solo comparten el primer
#: dígito. No aplica al número de contrato ni al código de inventario, que se
#: teclean completos o casi.
MIN_SEARCH_CHARS = 3

#: Todo lo que `to_tsquery` interpreta como sintaxis. Se descarta en vez de
#: escaparse: son signos que nadie teclea buscando a una persona, y dejarlos
#: pasar convierte un error de dedo en un `SyntaxError` de Postgres, que sale
#: como 500.
_NO_ES_LEXEMA = re.compile(r"[^\w\s]", re.UNICODE)


def prefix_tsquery(q: str) -> str | None:
    """Convierte lo tecleado en un `to_tsquery` de PREFIJO.

    `"jara mateo"` → `"jara:* & mateo:*"`. **TODAS las palabras llevan `:*`,
    no solo la última.** Una primera versión abría solo la última, con el
    razonamiento de que las anteriores el usuario ya las terminó — y es falso
    en un buscador que filtra mientras se escribe: quien teclea "jara mat"
    tiene las DOS a medias. Con la última sola, "jara mateo" no encontraba a
    Mateo Jaramillo, porque "jara" tiene que coincidir exacto contra el
    lexema "jaramill". Lo cazó el test de integración.

    Devuelve `None` cuando no queda nada que consultar — y hay que
    contemplarlo, porque pasa con entradas legítimas: `to_tsquery` no ignora
    las stopwords del español, así que buscar "de la" (parte de "De la Cruz")
    produce cero lexemas. Un `@@ ''` no coincide con nada y el usuario vería
    "sin resultados" para un apellido que sí existe. Quien llama debe caer a
    otra cláusula, no consultar con vacío.

    Nota sobre el stemming: la configuración `spanish` reduce "jaramillo" a
    "jaramill", así que el prefijo se compara contra la RAÍZ y no contra la
    palabra. Funciona igual porque un prefijo de la palabra es un prefijo de
    su raíz mientras no la exceda — y si la excede ("jaramillos"), lo que
    buscaba el usuario ya está encontrado por la raíz común.
    """
    limpio = _NO_ES_LEXEMA.sub(" ", q)
    palabras = [p for p in limpio.split() if p]
    if not palabras:
        return None
    return " & ".join(f"{palabra}:*" for palabra in palabras)


def name_clauses(column: str, q: str, *, prefix: str) -> tuple[list[str], dict[str, str]]:
    """Las cláusulas SQL para buscar una PERSONA o un PRODUCTO por nombre.

    Son dos, unidas por el `or` de quien llama:

    1. El full-text con prefijo, que usa el índice GIN y aguanta el orden de
       las palabras ("jara mateo" encuentra a "Mateo Jaramillo").
    2. Un `ilike` de respaldo, para lo que el full-text no puede ver: las
       stopwords del español ("de", "la", "los") son lexemas vacíos, así que
       sin él "De la Cruz" no se encontraría con "de la".

    `column` y `prefix` los fija el código que llama —nunca texto de un
    usuario—, así que interpolarlos es seguro. Mismo criterio que
    `customers.update_customer` con sus nombres de columna.
    """
    clauses = [f"{column} ilike :{prefix}_like"]
    params = {f"{prefix}_like": f"%{q.strip()}%"}
    tsq = prefix_tsquery(q)
    if tsq is not None:
        clauses.insert(
            0, f"to_tsvector('spanish', {column}) @@ to_tsquery('spanish', :{prefix}_tsq)"
        )
        params[f"{prefix}_tsq"] = tsq
    return clauses, params
