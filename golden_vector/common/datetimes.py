"""Shared datetime parsing helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 datetime and return an aware value when possible."""

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
