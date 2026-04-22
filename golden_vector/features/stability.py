"""Tool A stability metrics."""

from __future__ import annotations

import pandas as pd


def compute_stability_score(
    metric_rows: pd.DataFrame,
    *,
    core_delta: float | None,
) -> float | None:
    deltas = pd.to_numeric(metric_rows.get("gold_delta"), errors="coerce").dropna()
    if len(deltas.index) < 2:
        return None

    if core_delta is None:
        core_delta = float(deltas.median())

    scale = max(abs(core_delta), 0.25)
    mad = float((deltas - core_delta).abs().median())
    return float(1.0 / (1.0 + (mad / scale)))
