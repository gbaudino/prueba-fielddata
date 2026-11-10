from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException

from agroclimate.api.v1.pagination import decode_cursor, encode_cursor


def test_pagination_cursor_round_trip() -> None:
    created_at = datetime(2026, 11, 9, 18, 30, tzinfo=UTC)
    item_id = uuid4()

    decoded = decode_cursor(encode_cursor(created_at, item_id))

    assert decoded.created_at == created_at
    assert decoded.item_id == item_id


@pytest.mark.parametrize("value", ["", "not-a-cursor", "e30", "a" * 257])
def test_invalid_pagination_cursor_returns_422(value: str) -> None:
    with pytest.raises(HTTPException) as error:
        decode_cursor(value)

    assert error.value.status_code == 422
