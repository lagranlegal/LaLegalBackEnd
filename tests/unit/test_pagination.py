from uuid import uuid4

import pytest

from app.common.pagination import decode_cursor, encode_cursor, make_page
from app.core.errors import AppError


def test_encode_decode_roundtrip() -> None:
    original = uuid4()
    assert decode_cursor(encode_cursor(original)) == original


def test_decode_invalid_cursor_raises() -> None:
    with pytest.raises(AppError):
        decode_cursor("not-a-valid-cursor!!")


def test_make_page_no_more_pages() -> None:
    ids = [uuid4() for _ in range(3)]
    page = make_page(ids, limit=5, id_getter=lambda x: x)
    assert page.items == ids
    assert page.next_cursor is None


def test_make_page_has_more_pages() -> None:
    ids = [uuid4() for _ in range(6)]
    page = make_page(ids, limit=5, id_getter=lambda x: x)
    assert page.items == ids[:5]
    assert decode_cursor(page.next_cursor) == ids[4]  # type: ignore[arg-type]
