"""Tool A score construction and ranking."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import ScoreWeights


def compute_tool_a_score(
    *,
    delta_component_score: float,
    stability_score: float | None,
    gamma_component_score: float,
    score_eligible: bool,
    weights: ScoreWeights,
) -> float | None:
    if not score_eligible:
        return None

    stability_component = 0.0 if stability_score is None else float(stability_score)
    score = 100.0 * (
        (weights.core_delta * delta_component_score)
        + (weights.stability * stability_component)
        + (weights.gamma_proxy * gamma_component_score)
    )
    return round(float(score), 4)


def rank_tool_a_outputs(tool_a_outputs: pd.DataFrame) -> pd.DataFrame:
    if tool_a_outputs.empty:
        return tool_a_outputs.copy()

    ranked = tool_a_outputs.copy()
    ranked["tool_a_rank"] = pd.Series([pd.NA] * len(ranked.index), dtype="Int64")

    for as_of_date, group in ranked.groupby("as_of_date"):
        eligible_mask = (
            (ranked["as_of_date"] == as_of_date)
            & ranked["score_eligible"].fillna(False).astype(bool)
            & ranked["tool_a_score"].notna()
        )
        eligible_scores = pd.to_numeric(
            ranked.loc[eligible_mask, "tool_a_score"],
            errors="coerce",
        )
        if eligible_scores.empty:
            continue

        ranked.loc[eligible_mask, "tool_a_rank"] = (
            eligible_scores.rank(method="dense", ascending=False).astype("Int64")
        )

    return ranked
