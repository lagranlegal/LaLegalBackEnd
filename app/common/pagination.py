import base64
import json
from collections.abc import Callable
from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.errors import AppError


class CursorPage[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(last_id: UUID) -> str:
    return base64.urlsafe_b64encode(str(last_id).encode()).decode()


def decode_cursor(cursor: str) -> UUID:
    try:
        return UUID(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("Cursor de paginación inválido.", details={"cursor": cursor}) from exc


def make_page[T](rows: list[T], limit: int, id_getter: Callable[[T], UUID]) -> CursorPage[T]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(id_getter(items[-1])) if has_more and items else None
    return CursorPage(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Paginación por FECHA, para listados donde el orden cronológico es el punto.
#
# El cursor de arriba ordena por `id`, y los ids son UUID aleatorios: sirve
# para paginar sin repetir ni saltarse filas, pero el orden que produce no
# significa nada. En un listado cualquiera se nota poco. En el audit log era
# el defecto entero: **la auditoría salía en orden arbitrario**, así que lo
# último que hizo alguien podía caer en cualquier página. Reportado el
# 08/09/2026 como "no me aparecen sus movimientos" — y en parte era eso: sí
# aparecían, revueltos entre 143 filas.
#
# La llave es `(created_at, id)`: la fecha manda y el id desempata, así que
# dos filas del mismo instante nunca se pierden ni se repiten. Es exactamente
# el índice `ix_audit_company_date (company_id, created_at desc)` que ya
# existía en las migraciones desde el día uno, sin que nadie lo usara.
# ---------------------------------------------------------------------------


def encode_time_cursor(created_at: datetime, last_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{last_id}".encode()).decode()


def decode_time_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        crudo = base64.urlsafe_b64decode(cursor.encode()).decode()
        fecha, ident = crudo.split("|", 1)
        return datetime.fromisoformat(fecha), UUID(ident)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("Cursor de paginación inválido.", details={"cursor": cursor}) from exc


def make_time_page[T](
    rows: list[T], limit: int, key_getter: Callable[[T], tuple[datetime, UUID]]
) -> CursorPage[T]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_time_cursor(*key_getter(items[-1])) if has_more and items else None
    return CursorPage(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# La misma llave, pero sobre una FECHA DE DOCUMENTO (`date`, no `datetime`).
#
# La diferencia con `encode_time_cursor` no es de tipo, es de significado:
# `created_at` dice cuándo se REGISTRÓ algo y la fecha del documento dice
# cuándo OCURRIÓ. En un aporte de capital son distintas a propósito — el
# dueño puede registrar el lunes la plata que metió el viernes — y el
# historial tiene que salir por lo que pasó, no por lo que se tecleó.
#
# Mismo par `(fecha, id)`: la fecha manda y el id desempata, así que dos
# documentos del mismo día nunca se pierden ni se repiten al paginar. Con
# `date` sola no alcanzaría: varias filas comparten fecha todo el tiempo.
# ---------------------------------------------------------------------------


def encode_date_cursor(document_date: date, last_id: UUID) -> str:
    return base64.urlsafe_b64encode(f"{document_date.isoformat()}|{last_id}".encode()).decode()


def decode_date_cursor(cursor: str) -> tuple[date, UUID]:
    try:
        crudo = base64.urlsafe_b64decode(cursor.encode()).decode()
        fecha, ident = crudo.split("|", 1)
        return date.fromisoformat(fecha), UUID(ident)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("Cursor de paginación inválido.", details={"cursor": cursor}) from exc


def make_date_page[T](
    rows: list[T], limit: int, key_getter: Callable[[T], tuple[date, UUID]]
) -> CursorPage[T]:
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_date_cursor(*key_getter(items[-1])) if has_more and items else None
    return CursorPage(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Cursor de LLAVE COMPUESTA, para listados con orden elegible (`?sort=`).
#
# Los cursores de arriba fijan una sola llave. Cuando el cliente elige el
# orden, la llave cambia con él: `(número, id)`, `(nombre del cliente,
# número, id)`… El cursor guarda la llave completa de la última fila Y el
# nombre del orden con que se emitió: un cursor de `customer_asc` pegado en
# una request con `number_desc` apuntaría a un lugar sin sentido, así que se
# rechaza como inválido en vez de devolver una página revuelta.
#
# Los valores viajan como JSON (texto, número, booleano); quien lo usa
# convierte fechas y UUID a texto al emitirlo y de vuelta al leerlo, porque
# sabe el tipo de cada posición de su llave.
# ---------------------------------------------------------------------------


def encode_key_cursor(sort: str, key: list[Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps({"s": sort, "k": key}).encode()).decode()


def decode_key_cursor(cursor: str, *, sort: str, size: int) -> list[Any]:
    """La llave del cursor, si fue emitido para `sort` y tiene `size`
    posiciones; si no, `AppError` de cursor inválido."""
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        key = data["k"]
        if data["s"] != sort or not isinstance(key, list) or len(key) != size:
            raise ValueError("cursor de otro orden")
        return key
    except (ValueError, UnicodeDecodeError, TypeError, KeyError) as exc:
        raise AppError("Cursor de paginación inválido.", details={"cursor": cursor}) from exc
