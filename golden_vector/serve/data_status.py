"""Small product-wide status derived from persisted refresh publications."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from golden_vector.app.latest_successful_refresh import (
    SuccessfulModelRefresh,
    load_latest_successful_model_refresh,
)
from golden_vector.app.market_hours_refresh import (
    US_MARKET_TIMEZONE,
    count_completed_us_market_close_slots,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.datetimes import parse_iso_datetime
from golden_vector.serve.option_refresh import (
    REFRESH_STATUS_FAILED,
    REFRESH_STATUS_RUNNING,
    REFRESH_STATUS_UNKNOWN,
    OptionRefreshStatus,
    read_option_refresh_status,
)

DATA_STATUS_SCHEMA_VERSION = 1
STRONG_WARNING_AFTER_TRADING_DAYS = 2


@dataclass(frozen=True)
class DataStatus:
    status: str
    tone: str
    text: str
    last_successful_refresh_at_utc: str | None
    latest_run_id: str | None
    age_trading_days: int | None
    refresh_attempt_status: str
    refresh_attempt_started_at_utc: str | None
    refresh_attempt_finished_at_utc: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": DATA_STATUS_SCHEMA_VERSION,
            "status": self.status,
            "tone": self.tone,
            "text": self.text,
            "last_successful_refresh_at_utc": self.last_successful_refresh_at_utc,
            "latest_run_id": self.latest_run_id,
            "age_trading_days": self.age_trading_days,
            "refresh_attempt": {
                "status": self.refresh_attempt_status,
                "started_at_utc": self.refresh_attempt_started_at_utc,
                "finished_at_utc": self.refresh_attempt_finished_at_utc,
            },
        }


def build_data_status(
    paths: ProjectPaths,
    *,
    now: datetime | None = None,
) -> DataStatus:
    """Build a display-ready status without fetching or computing analytics."""

    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    instant = instant.astimezone(UTC)
    latest = load_latest_successful_model_refresh(paths)
    refresh = read_option_refresh_status(paths)
    age = _trading_day_age(latest, now=instant)
    label = _updated_label(latest)
    attempt_is_newer = _attempt_is_newer(refresh, latest)

    if refresh.status == REFRESH_STATUS_RUNNING and attempt_is_newer:
        # Only the literal lead-in word is lowercased. Lowercasing the whole
        # label mangled the month and the timezone ("updated aug 11, 4:00 pm et").
        text = (
            f"Refreshing · {_updated_label(latest, lead='updated')}"
            if latest
            else "Refreshing · no completed refresh yet"
        )
        return _status(
            "running",
            "running",
            text,
            latest=latest,
            age=age,
            refresh=refresh,
        )
    if refresh.status == REFRESH_STATUS_FAILED and attempt_is_newer:
        text = f"{label} · latest refresh failed" if latest else "Latest refresh failed"
        return _status(
            "failed",
            "warning",
            text,
            latest=latest,
            age=age,
            refresh=refresh,
        )
    if refresh.status == REFRESH_STATUS_UNKNOWN and attempt_is_newer:
        text = f"{label} · refresh status unavailable" if latest else "Data status unavailable"
        return _status(
            "unknown",
            "warning",
            text,
            latest=latest,
            age=age,
            refresh=refresh,
        )
    if latest is None:
        return _status(
            "unavailable",
            "warning",
            "No completed refresh yet",
            latest=None,
            age=None,
            refresh=refresh,
        )
    if age is not None and age >= STRONG_WARNING_AFTER_TRADING_DAYS:
        return _status(
            "stale",
            "warning",
            f"{label} · data may be stale",
            latest=latest,
            age=age,
            refresh=refresh,
        )
    return _status(
        "current",
        "ok",
        label,
        latest=latest,
        age=age,
        refresh=refresh,
    )


def _status(
    status: str,
    tone: str,
    text: str,
    *,
    latest: SuccessfulModelRefresh | None,
    age: int | None,
    refresh: OptionRefreshStatus,
) -> DataStatus:
    return DataStatus(
        status=status,
        tone=tone,
        text=text,
        last_successful_refresh_at_utc=(latest.generated_at_utc if latest else None),
        latest_run_id=(latest.parent_refresh_id if latest else None),
        age_trading_days=age,
        refresh_attempt_status=refresh.status,
        refresh_attempt_started_at_utc=refresh.started_at,
        refresh_attempt_finished_at_utc=refresh.finished_at,
    )


def _updated_label(latest: SuccessfulModelRefresh | None, *, lead: str = "Updated") -> str:
    if latest is None:
        return "No completed refresh yet"
    value = latest.generated_at.astimezone(US_MARKET_TIMEZONE)
    month_day = value.strftime("%b %d").replace(" 0", " ")
    clock = value.strftime("%I:%M %p").lstrip("0")
    return f"{lead} {month_day}, {clock} ET"


def _attempt_is_newer(
    refresh: OptionRefreshStatus,
    latest: SuccessfulModelRefresh | None,
) -> bool:
    attempt_at = parse_iso_datetime(refresh.finished_at) or parse_iso_datetime(refresh.started_at)
    if attempt_at is None:
        return latest is None
    return latest is None or attempt_at >= latest.generated_at


def _trading_day_age(
    latest: SuccessfulModelRefresh | None,
    *,
    now: datetime,
) -> int | None:
    if latest is None:
        return None
    return count_completed_us_market_close_slots(latest.generated_at, through=now)
