"""Daily option-chain history (plan §6.1–§6.3) — the `option_chain_history_daily` artifact.

One authority per field: chain-level daily quantities (whole-chain OI / volume
sums and their put/call splits) have no existing home, so they accumulate here,
merge-forward, one row per (ticker, as_of_date).

DORMANT: this module is not wired into any stage yet. The active option schema
version stays 3; nothing publishes or reads this artifact until the v4 lane
flips it on.

Gate policy (plan §6.3):
* Same-day selection — keep the capture with the highest ``total_open_interest``;
  ties break on the latest ``run_id`` (run ids are ``%Y%m%dT%H%M%SZ-<command>-<hex>``
  so lexicographic order is time order).
* Completeness — a capture must clear trailing-median floors
  (``coverage_floor_ratio`` × trailing median over ``trailing_median_days``) on
  ``n_expirations``, ``n_contracts`` and ``total_open_interest``. A day whose best
  capture is itself partial is FLAGGED, never crowned as complete.
* Field-level gates — a negative or non-finite OI / volume / ratio is NA'd for
  that field only; the row survives with the reason recorded in ``capture_quality``.
* No-shrink — output (ticker, as_of_date) keys must be a superset of the previous
  history's keys; a violation raises rather than publishing a shrunken file.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from golden_vector.common.numeric import optional_float, optional_int
from golden_vector.common.strings import clean_string
from golden_vector.contracts.config_models import OptionHistoryQualityConfig
from golden_vector.contracts.option_artifacts import (
    CHAIN_HISTORY_COLUMNS,
    CHAIN_HISTORY_SCHEMA_VERSION,
)

ROW_STATUS_OBSERVED = "observed"
ROW_STATUS_CARRIED_FORWARD = "carried_forward"
ROW_STATUS_BACKFILLED = "backfilled"

CAPTURE_QUALITY_COMPLETE = "COMPLETE"
CAPTURE_QUALITY_PARTIAL = "PARTIAL"

_COUNT_FIELDS: tuple[str, ...] = (
    "total_open_interest",
    "put_oi_total",
    "call_oi_total",
    "put_oi_otm",
    "call_oi_otm",
    "total_volume",
    "put_volume",
    "call_volume",
    "n_contracts",
    "n_expirations",
)
_RATIO_FIELDS: tuple[str, ...] = (
    "put_call_oi_ratio_total",
    "put_call_oi_ratio_otm",
)
# Trailing-coverage floors are judged on these three always-present fields...
_COVERAGE_FIELDS: tuple[str, ...] = (
    "n_expirations",
    "n_contracts",
    "total_open_interest",
)
# ...plus the per-SIDE contract counts (plan §6.3) when they are available.
# These are OPTIONAL: `compute_options_features` emits them, but history rows
# written before it did carry neither column nor value. A field only earns a
# floor when BOTH today's capture and the trailing rows supply real numbers;
# otherwise the row degrades silently to the three mandatory floors above.
_OPTIONAL_COVERAGE_FIELDS: tuple[str, ...] = (
    "put_n_contracts",
    "call_n_contracts",
)


def build_chain_history_daily(
    *,
    features_frames: dict[str, pd.DataFrame],
    previous_history: pd.DataFrame | None,
    quality: OptionHistoryQualityConfig,
    published_run_id: str,
) -> pd.DataFrame:
    """Merge today's per-ticker options-features captures into the daily history.

    ``features_frames`` maps ticker -> a frame of ``compute_options_features``
    rows (one row per capture; several same-day captures are expected when a
    refresh runs more than once a day).
    """

    previous = _normalize_history(previous_history)
    observed_rows: list[dict[str, Any]] = []
    for ticker in sorted(features_frames):
        observed_rows.extend(
            _rows_for_ticker(
                ticker=ticker,
                frame=features_frames[ticker],
                previous=previous,
                quality=quality,
                published_run_id=published_run_id,
            )
        )

    observed = _normalize_history(pd.DataFrame(observed_rows))
    merged = _merge_forward(previous=previous, observed=observed)
    _assert_no_shrink(previous=previous, merged=merged)
    merged["published_run_id"] = str(published_run_id)
    return merged.loc[:, list(CHAIN_HISTORY_COLUMNS)].reset_index(drop=True)


def _rows_for_ticker(
    *,
    ticker: str,
    frame: pd.DataFrame,
    previous: pd.DataFrame,
    quality: OptionHistoryQualityConfig,
    published_run_id: str,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    captures_by_day: dict[str, list[dict[str, Any]]] = {}
    for record in frame.to_dict(orient="records"):
        as_of = clean_string(record.get("as_of_date"))
        if as_of is None:
            continue
        captures_by_day.setdefault(as_of, []).append(record)

    rows: list[dict[str, Any]] = []
    for as_of, captures in sorted(captures_by_day.items()):
        winner = _select_same_day_capture(captures)
        if winner is None:
            continue
        row, flags = _gated_row(winner)
        row["ticker"] = ticker
        row["as_of_date"] = as_of
        row["capture_run_id"] = clean_string(winner.get("run_id"))
        row["published_run_id"] = str(published_run_id)
        row["row_status"] = ROW_STATUS_OBSERVED
        row["oi_split_backfilled"] = False
        row["schema_version"] = CHAIN_HISTORY_SCHEMA_VERSION
        flags.extend(
            _coverage_flags(
                row=row,
                ticker=ticker,
                as_of_date=as_of,
                previous=previous,
                quality=quality,
            )
        )
        row["capture_quality"] = _quality_label(flags)
        rows.append(row)
    return rows


def _select_same_day_capture(captures: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest total OI wins the day; ties go to the latest (lexicographic) run id."""

    scored = [
        (
            optional_float(capture.get("total_open_interest")) or 0.0,
            clean_string(capture.get("run_id")) or "",
            index,
        )
        for index, capture in enumerate(captures)
    ]
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return captures[scored[0][2]]


def _gated_row(capture: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply field-level gates; a bad field is NA'd, the row survives."""

    row: dict[str, Any] = {}
    flags: list[str] = []
    for field in _COUNT_FIELDS:
        value = optional_int(capture.get(field))
        if value is not None and value < 0:
            flags.append(f"negative:{field}")
            value = None
        row[field] = value
    for field in _RATIO_FIELDS:
        value = optional_float(capture.get(field))
        if value is not None and value < 0:
            flags.append(f"negative:{field}")
            value = None
        row[field] = value
    for field in _OPTIONAL_COVERAGE_FIELDS:
        # Presence gate: an old capture without the key contributes nothing.
        if field not in capture:
            continue
        value = optional_int(capture.get(field))
        if value is not None and value < 0:
            flags.append(f"negative:{field}")
            value = None
        row[field] = value
    return row, flags


def _coverage_flags(
    *,
    row: dict[str, Any],
    ticker: str,
    as_of_date: str,
    previous: pd.DataFrame,
    quality: OptionHistoryQualityConfig,
) -> list[str]:
    """Trailing-median coverage floors (plan §6.3)."""

    trailing = _trailing_rows(
        previous=previous,
        ticker=ticker,
        as_of_date=as_of_date,
        window=int(quality.trailing_median_days),
    )
    if trailing.empty:
        return []
    floor_ratio = float(quality.coverage_floor_ratio)
    flags: list[str] = []
    for field in (*_COVERAGE_FIELDS, *_OPTIONAL_COVERAGE_FIELDS):
        if field not in trailing.columns:
            continue
        median = pd.to_numeric(trailing[field], errors="coerce").dropna().median()
        value = optional_float(row.get(field))
        if pd.isna(median) or value is None:
            continue
        if value < float(median) * floor_ratio:
            flags.append(f"below_trailing_floor:{field}")
    return flags


def _trailing_rows(
    *,
    previous: pd.DataFrame,
    ticker: str,
    as_of_date: str,
    window: int,
) -> pd.DataFrame:
    if previous.empty:
        return previous
    scoped = previous[
        (previous["ticker"].astype(str) == ticker)
        & (previous["as_of_date"].astype(str) < as_of_date)
    ]
    if scoped.empty:
        return scoped
    return scoped.sort_values("as_of_date").tail(max(1, int(window)))


def _quality_label(flags: list[str]) -> str:
    if not flags:
        return CAPTURE_QUALITY_COMPLETE
    return f"{CAPTURE_QUALITY_PARTIAL}:" + ",".join(sorted(set(flags)))


def _merge_forward(*, previous: pd.DataFrame, observed: pd.DataFrame) -> pd.DataFrame:
    """Prior rows keep their own provenance; today's observations win their key."""

    if observed.empty:
        return previous.copy()
    if previous.empty:
        return observed.copy()
    combined = pd.concat([previous, observed], ignore_index=True)
    return (
        combined.drop_duplicates(subset=["ticker", "as_of_date"], keep="last")
        .sort_values(["ticker", "as_of_date"])
        .reset_index(drop=True)
    )


def _assert_no_shrink(*, previous: pd.DataFrame, merged: pd.DataFrame) -> None:
    previous_keys = _keys(previous)
    lost = previous_keys - _keys(merged)
    if lost:
        preview = ", ".join(f"{ticker}@{as_of}" for ticker, as_of in sorted(lost)[:5])
        raise ValueError(
            "Refusing to publish option chain history: "
            f"{len(lost)} previously observed (ticker, date) row(s) would disappear "
            f"({preview}). Run directories are enrichment, never the authority."
        )


def _keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
    if frame.empty:
        return set()
    return {
        (str(ticker), str(as_of))
        for ticker, as_of in zip(
            frame["ticker"], frame["as_of_date"], strict=True
        )
    }


def _normalize_history(frame: pd.DataFrame | None) -> pd.DataFrame:
    columns = list(CHAIN_HISTORY_COLUMNS)
    if frame is None or frame.empty:
        return pd.DataFrame(columns=columns)
    result = frame.copy()
    for column in columns:
        if column not in result.columns:
            result[column] = None
    result["ticker"] = result["ticker"].map(clean_string)
    result["as_of_date"] = result["as_of_date"].map(clean_string)
    result = result.dropna(subset=["ticker", "as_of_date"])
    return result.loc[:, columns].reset_index(drop=True)
