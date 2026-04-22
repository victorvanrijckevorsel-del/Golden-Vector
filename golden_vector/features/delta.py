"""Tool A delta metrics."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import DeltaBucketThresholds


def compute_core_delta(metric_rows: pd.DataFrame) -> float | None:
    deltas = pd.to_numeric(metric_rows.get("gold_delta"), errors="coerce").dropna()
    if deltas.empty:
        return None
    return float(deltas.median())


def assign_delta_bucket(
    core_delta: float | None,
    thresholds: DeltaBucketThresholds,
) -> str | None:
    if core_delta is None:
        return None

    magnitude = abs(core_delta)
    if magnitude <= thresholds.low_max:
        return "LOW"
    if magnitude <= thresholds.moderate_max:
        return "MODERATE"
    return "HIGH"


def compute_delta_component_score(
    core_delta: float | None,
    thresholds: DeltaBucketThresholds,
) -> float:
    if core_delta is None or core_delta <= 0:
        return 0.0

    low_max = max(float(thresholds.low_max), 1e-9)
    moderate_max = max(float(thresholds.moderate_max), low_max)

    if core_delta <= low_max:
        return _clamp(0.5 * (core_delta / low_max))

    if core_delta <= moderate_max:
        span = max(moderate_max - low_max, 1e-9)
        return _clamp(0.5 + (0.25 * ((core_delta - low_max) / span)))

    extra = min((core_delta - moderate_max) / moderate_max, 1.0)
    return _clamp(0.75 + (0.25 * extra))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
