import base64
import json
from datetime import datetime
from uuid import UUID

from ares.event_journal.models import JournalEvent


def encode_cursor(event: JournalEvent) -> str:
    return (
        base64.urlsafe_b64encode(
            json.dumps([event.recorded_at.isoformat(), str(event.id)]).encode()
        )
        .decode()
        .rstrip("=")
    )


def decode_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if value is None:
        return None
    try:
        if len(value) > 512:
            raise ValueError
        data = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(data, list) or len(data) != 2:
            raise ValueError
        at, event_id = datetime.fromisoformat(data[0]), UUID(data[1])
        if at.tzinfo is None:
            raise ValueError
        return at, event_id
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("invalid_cursor") from error


def validate_limit(limit: int) -> None:
    if not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
