"""Shared percentile-rank helpers."""

from __future__ import annotations

import pandas as pd


def oriented_percentile(series: pd.Series, *, high_good: bool) -> pd.Series:
    """Return a 0-100 percentile where higher values mean better fit.

    Missing values are excluded from the peer pool and remain missing in the
    output. The endpoint convention intentionally follows pandas'
    ``rank(pct=True)`` behavior, so a one-value peer group receives 100.
    """

    values = pd.to_numeric(series, errors="coerce")
    return values.rank(pct=True, ascending=high_good, method="average") * 100.0
