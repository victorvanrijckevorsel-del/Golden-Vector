"""Render-only wording for persisted per-ticker option-data provenance.

One extra job lives here beyond formatting, and it is deliberate. The per-ticker
``display_staleness_trading_days`` / ``display_freshness_status`` columns are
stamped when the option artifacts are BUILT. On a full vendor outage the build
is skipped and the previous generation is carried forward untouched, so those
columns keep saying "0 trading days / LATEST" no matter how long the outage
lasts — the 3-trading-day warning could never fire.

The generation's own age is known to every page (the model-state manifest's
option freshness domain records the carried snapshot date), so the resolution
is: classify the GENERATION age once through the SHARED classifier
(``app.market_hours_refresh.classify_us_trading_day_freshness`` — never a second
copy of the trading-day calendar), then show the WORSE of the row's stamped age
and the generation's age. No threshold is compared here; the classifier emits
STALE and every screen keys off that status.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from golden_vector.app.market_hours_refresh import (
    OPTION_FRESHNESS_LATEST,
    OPTION_FRESHNESS_STALE,
    OPTION_FRESHNESS_STORED,
    US_MARKET_TIMEZONE,
    classify_us_trading_day_freshness,
)
from golden_vector.app.model_state import summarize_option_freshness

#: The model-state option freshness status that means "this generation is the
#: previous good snapshot, kept because the refresh could not publish".
GENERATION_CARRIED_FORWARD = "CARRIED_FORWARD"

#: Ordered worst-last. Selection only — used to pick which of two already
#: classified verdicts to display, never to classify anything.
_FRESHNESS_SEVERITY = {
    OPTION_FRESHNESS_LATEST: 0,
    OPTION_FRESHNESS_STORED: 1,
    OPTION_FRESHNESS_STALE: 2,
}


def format_collected_at_et(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        captured = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    local = captured.astimezone(US_MARKET_TIMEZONE)
    hour = local.strftime("%I").lstrip("0") or "0"
    return f"{local.strftime('%b')} {local.day}, {hour}:{local.strftime('%M %p')} ET"


def format_source_date(value: object) -> str | None:
    try:
        parsed = date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def latest_available_label(
    *,
    source_as_of_date: object,
    captured_at_utc: object,
    carried_forward: bool,
) -> str:
    source = format_source_date(source_as_of_date)
    collected = format_collected_at_et(captured_at_utc)
    if carried_forward:
        lead = "Options data: Latest available stored snapshot"
        if source:
            lead += f" from {source}"
    else:
        lead = "Options data: Latest available"
    if collected:
        return f"{lead}; collected {collected}."
    if source and not carried_forward:
        return f"{lead} as of {source}."
    return f"{lead}."


@dataclass(frozen=True)
class OptionGenerationFreshness:
    """Age of the option GENERATION the page is rendering from."""

    carried_forward: bool
    trading_days: int | None = None
    status: str | None = None

    @property
    def stale(self) -> bool:
        return self.carried_forward and self.status == OPTION_FRESHNESS_STALE


@dataclass(frozen=True)
class OptionRowFreshness:
    """A ticker's stamped provenance widened by the generation it was carried in."""

    trading_days: int | None = None
    status: str | None = None
    carried_forward: bool = False

    @property
    def stale(self) -> bool:
        return self.status == OPTION_FRESHNESS_STALE


def option_generation_freshness(
    *,
    freshness_status: object,
    as_of_date: object,
    through_date: date | None = None,
) -> OptionGenerationFreshness:
    """Classify how old the carried generation is, through the shared classifier.

    Only a carried-forward generation is aged here: when the refresh published
    fresh option artifacts, the per-ticker columns were stamped by that same
    build and are already right.
    """

    carried = str(freshness_status or "").strip().upper() == GENERATION_CARRIED_FORWARD
    if not carried:
        return OptionGenerationFreshness(carried_forward=False)
    verdict = classify_us_trading_day_freshness(as_of_date, through_date=through_date)
    return OptionGenerationFreshness(
        carried_forward=True,
        trading_days=verdict.trading_days,
        status=verdict.status,
    )


def option_generation_freshness_from_manifest(
    model_state_manifest: dict[str, Any] | None,
    *,
    through_date: date | None = None,
) -> OptionGenerationFreshness:
    """The manifest-side entry point, so no page re-reads the freshness domain."""

    summary = summarize_option_freshness(model_state_manifest) or {}
    return option_generation_freshness(
        freshness_status=summary.get("status"),
        as_of_date=summary.get("as_of_date"),
        through_date=through_date,
    )


def resolve_option_row_freshness(
    *,
    trading_days: int | None,
    status: object,
    carried_forward: bool,
    generation: OptionGenerationFreshness,
) -> OptionRowFreshness:
    """Show the worse of the row's stamped age and the carried generation's age."""

    row_status = (str(status).strip().upper() or None) if status is not None else None
    return OptionRowFreshness(
        trading_days=_older_age(trading_days, generation.trading_days),
        status=_worse_status(row_status, generation.status),
        carried_forward=bool(carried_forward) or generation.carried_forward,
    )


def stored_snapshot_warning(freshness: OptionRowFreshness | None) -> str | None:
    """The stale-snapshot warning, driven by the classifier's STALE status."""

    if freshness is None or not freshness.stale:
        return None
    if freshness.trading_days is None:
        return (
            "This snapshot is too old to trade from. The latest refresh could not "
            "replace it, so treat quotes as stale."
        )
    return (
        f"This snapshot is {freshness.trading_days} US trading days old. "
        "The latest refresh could not replace it, so treat quotes as stale."
    )


def _older_age(left: int | None, right: int | None) -> int | None:
    known = [value for value in (left, right) if value is not None]
    return max(known) if known else None


def _worse_status(left: str | None, right: str | None) -> str | None:
    ranked = [value for value in (left, right) if value in _FRESHNESS_SEVERITY]
    if not ranked:
        return left or right
    return max(ranked, key=_FRESHNESS_SEVERITY.__getitem__)
