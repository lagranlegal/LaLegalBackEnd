from uuid import uuid4

import pytest

from app.common.pagination import (
    decode_cursor,
    decode_key_cursor,
    encode_cursor,
    encode_key_cursor,
    make_page,
)
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


def test_key_cursor_roundtrip() -> None:
    key = [False, "2026-01-31", 17, str(uuid4())]
    cursor = encode_key_cursor("next_due_asc", key)
    assert decode_key_cursor(cursor, sort="next_due_asc", size=4) == key


@pytest.mark.parametrize(
    ("cursor", "sort", "size"),
    [
        (encode_key_cursor("customer_asc", ["ana", -3, "x"]), "number_desc", 3),  # otro orden
        (encode_key_cursor("number_desc", [3, "x"]), "number_desc", 3),  # otro tamaño
        (encode_cursor(uuid4()), "number_desc", 2),  # cursor del formato viejo
        ("no-es-un-cursor!!", "number_desc", 2),
    ],
)
def test_key_cursor_invalido(cursor: str, sort: str, size: int) -> None:
    with pytest.raises(AppError):
        decode_key_cursor(cursor, sort=sort, size=size)
