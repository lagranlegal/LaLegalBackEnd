import base64
from collections.abc import Callable
from datetime import datetime
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
