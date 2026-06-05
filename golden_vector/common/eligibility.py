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
