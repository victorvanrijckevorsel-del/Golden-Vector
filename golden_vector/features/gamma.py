"""Tool A convexity-like metrics."""

from __future__ import annotations

import pandas as pd


def compute_gamma_proxy(metric_rows: pd.DataFrame) -> float | None:
    if metric_rows.empty:
        return None

    working = metric_rows.copy()
    working["gold_abs_return"] = pd.to_numeric(
        working.get("gold_return"),
        errors="coerce",
    ).abs()
    working["gold_delta"] = pd.to_numeric(
        working.get("gold_delta"),
        errors="coerce",
    )
    working = working.dropna(subset=["gold_abs_return", "gold_delta"])
    if len(working.index) < 2:
        return None
    if working["gold_abs_return"].nunique() < 2:
        return 0.0

    correlation = working["gold_abs_return"].corr(working["gold_delta"])
    if pd.isna(correlation):
        return 0.0
    return float(max(-1.0, min(1.0, correlation)))


def compute_gamma_component_score(gamma_proxy: float | None) -> float:
    if gamma_proxy is None:
        return 0.5
    clipped = max(-1.0, min(1.0, float(gamma_proxy)))
    return (clipped + 1.0) / 2.0
