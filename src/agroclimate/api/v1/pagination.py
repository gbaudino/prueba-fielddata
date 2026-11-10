import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status


@dataclass(frozen=True, slots=True)
class PaginationCursor:
    created_at: datetime
    item_id: UUID


def encode_cursor(created_at: datetime, item_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": created_at.isoformat(), "id": str(item_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> PaginationCursor:
    try:
        if not value or len(value) > 256:
            raise ValueError("Invalid cursor length")

        padded_value = value + ("=" * (-len(value) % 4))
        payload = base64.b64decode(
            padded_value,
            altchars=b"-_",
            validate=True,
        )
        decoded = json.loads(payload)
        created_at = datetime.fromisoformat(decoded["created_at"])
        item_id = UUID(decoded["id"])

        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError("Cursor timestamp must be timezone-aware")

        return PaginationCursor(created_at=created_at, item_id=item_id)
    except (
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid pagination cursor",
        ) from exc
