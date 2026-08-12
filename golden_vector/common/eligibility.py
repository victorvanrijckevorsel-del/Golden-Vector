"""Shared score-eligibility coercion helpers."""

from __future__ import annotations

import pandas as pd

FALSEY_SCORE_ELIGIBLE_VALUES = frozenset({"false", "0", "no", "n"})


def is_score_eligible(value: object, *, default: bool = True) -> bool:
    """Return whether a Tool A row should be treated as score-eligible.

    Missing values default to eligible for backwards compatibility with older
    Tool A snapshots that predate the explicit ``score_eligible`` column.
    Explicit false-like values still block scoring and view lenses.
    """

    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in FALSEY_SCORE_ELIGIBLE_VALUES


def score_eligible_mask(series: pd.Series, *, default: bool = True) -> pd.Series:
    """Vectorized score-eligibility mask with the shared scalar policy."""

    return series.map(lambda value: is_score_eligible(value, default=default)).astype(bool)


def ok_normalized_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """C4: the ONE normalization-eligibility boundary for history consumers.

    Keeps only rows whose ``normalization_status`` is OK when the column exists
    (equity histories carry it); frames without the column (gold, benchmarks -
    no FX normalization happens there) pass through unchanged. Every consumer
    of normalized USD histories (structural, horizon returns, performance,
    FX attribution) must resolve eligibility through this helper - a stale or
    invalid normalized row must never become a chart point or a horizon return.
    """

    if frame is None or frame.empty or "normalization_status" not in frame.columns:
        return frame
    status = frame["normalization_status"].fillna("").astype(str).str.upper()
    return frame.loc[status.eq("OK")]
