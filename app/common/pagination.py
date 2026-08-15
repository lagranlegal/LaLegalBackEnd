import base64
from collections.abc import Callable
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
