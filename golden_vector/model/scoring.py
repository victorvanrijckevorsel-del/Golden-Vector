"""Structural Tool A score construction and ranking."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import (
    AsymmetryThresholds,
    GammaThresholds,
    ScoreWeights,
    StructuralDeltaBands,
)


def compute_delta_component_score(
    core_delta: float | None,
    *,
    bands: StructuralDeltaBands,
) -> float:
    if core_delta is None or core_delta <= 0:
        return 0.0
    if core_delta <= bands.low_max:
        return _clamp(0.35 * (core_delta / bands.low_max))
    if core_delta <= bands.moderate_max:
        span = bands.moderate_max - bands.low_max
        return _clamp(0.35 + (0.35 * ((core_delta - bands.low_max) / span)))
    if core_delta <= bands.high_min:
        span = bands.high_min - bands.moderate_max
        return _clamp(0.7 + (0.2 * ((core_delta - bands.moderate_max) / span)))
    extra = min((core_delta - bands.high_min) / max(bands.high_min, 1e-9), 1.0)
    return _clamp(0.9 + (0.1 * extra))


def compute_gamma_component_score(
    gamma_value: float | None,
    *,
    thresholds: GammaThresholds,
) -> float:
    if gamma_value is None:
        return 0.5
    if gamma_value >= thresholds.positive_min:
        return 0.0
    if gamma_value <= thresholds.negative_max:
        return 1.0
    span = thresholds.positive_min - thresholds.negative_max
    return _clamp((thresholds.positive_min - gamma_value) / span)


def compute_asymmetry_component_score(
    *,
    asymmetry_ratio: float | None,
    up_beta: float | None,
    down_beta: float | None,
    thresholds: AsymmetryThresholds,
) -> float:
    if up_beta is None or down_beta is None:
        return 0.0
    if up_beta > 0 and down_beta <= 0:
        return 1.0
    if asymmetry_ratio is None:
        return 0.0
    if asymmetry_ratio <= thresholds.weak_max:
        return 0.0
    if asymmetry_ratio >= thresholds.strong_min:
        return 1.0
    span = thresholds.strong_min - thresholds.weak_max
    return _clamp((asymmetry_ratio - thresholds.weak_max) / span)


def compute_tool_a_score(
    *,
    delta_component_score: float,
    gamma_component_score: float,
    asymmetry_component_score: float,
    confidence_score: float | None,
    score_eligible: bool,
    weights: ScoreWeights,
) -> float | None:
    if not score_eligible:
        return None

    confidence_component = 0.0 if confidence_score is None else float(confidence_score)
    score = 100.0 * (
        (weights.structural_delta * delta_component_score)
        + (weights.structural_gamma * gamma_component_score)
        + (weights.asymmetry * asymmetry_component_score)
        + (weights.confidence * confidence_component)
    )
    return round(float(score), 4)


def rank_tool_a_outputs(tool_a_outputs: pd.DataFrame) -> pd.DataFrame:
    if tool_a_outputs.empty:
        return tool_a_outputs.copy()

    ranked = tool_a_outputs.copy()
    ranked["tool_a_rank"] = pd.Series([pd.NA] * len(ranked.index), dtype="Int64")
    eligible_mask = (
        ranked["score_eligible"].fillna(False).astype(bool)
        & ranked["tool_a_score"].notna()
    )
    if eligible_mask.any():
        eligible_rows = ranked.loc[eligible_mask].copy()
        eligible_rows["tool_a_rank"] = (
            pd.to_numeric(eligible_rows["tool_a_score"], errors="coerce")
            .groupby(eligible_rows["as_of_date"])
            .rank(method="dense", ascending=False)
            .astype("Int64")
        )
        ranked.loc[eligible_mask, "tool_a_rank"] = eligible_rows["tool_a_rank"].to_numpy()

    return ranked


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
