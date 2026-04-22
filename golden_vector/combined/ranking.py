"""Combined-layer scoring, verdicts, and ranking."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import CombinedVerdictThresholds


def determine_join_status(row: pd.Series) -> str:
    has_tool_a = pd.notna(row.get("tool_a_run_id")) and pd.notna(row.get("tool_a_score"))
    has_tool_b = pd.notna(row.get("tool_b_run_id")) and pd.notna(row.get("tool_b_score"))
    return "COMPLETE" if has_tool_a and has_tool_b else "PARTIAL"


def compute_combined_score(row: pd.Series) -> float | None:
    if determine_join_status(row) != "COMPLETE":
        return None
    tool_a_score = _numeric(row.get("tool_a_score"))
    tool_b_score = _numeric(row.get("tool_b_score"))
    if tool_a_score is None or tool_b_score is None:
        return None
    return round((tool_a_score + tool_b_score) / 2.0, 4)


def determine_combined_verdict(
    row: pd.Series,
    *,
    thresholds: CombinedVerdictThresholds,
) -> str:
    tool_a_present = pd.notna(row.get("tool_a_run_id"))
    tool_b_present = pd.notna(row.get("tool_b_run_id"))
    tool_a_score = _numeric(row.get("tool_a_score"))
    screening_verdict = row.get("screening_verdict")
    join_status = determine_join_status(row)

    if join_status == "PARTIAL":
        if tool_a_present and tool_b_present:
            return "INCOMPLETE"
        if tool_a_present:
            return "TOOL_A_ONLY"
        if tool_b_present:
            return "TOOL_B_ONLY"
        return "UNAVAILABLE"

    assert tool_a_score is not None
    if (
        screening_verdict == "STRONG_CANDIDATE"
        and tool_a_score >= thresholds.high_conviction_min_tool_a_score
    ):
        return "HIGH_CONVICTION"
    if (
        screening_verdict in {"STRONG_CANDIDATE", "WATCHLIST"}
        and tool_a_score >= thresholds.dual_pass_min_tool_a_score
    ):
        return "DUAL_PASS"
    if (
        screening_verdict == "SCREEN_OUT"
        and tool_a_score >= thresholds.dual_pass_min_tool_a_score
    ):
        return "GOLD_BETA_ONLY"
    if screening_verdict == "STRONG_CANDIDATE":
        return "VALUATION_ONLY"
    return "REVIEW"


def rank_combined_outputs(combined_outputs: pd.DataFrame) -> pd.DataFrame:
    if combined_outputs.empty:
        return combined_outputs.copy()

    ranked = combined_outputs.copy()
    ranked["combined_rank"] = pd.Series([pd.NA] * len(ranked.index), dtype="Int64")

    for keys, _ in ranked.groupby(["as_of_date", "gold_price_assumption"], dropna=False):
        as_of_date, gold_price_assumption = keys
        eligible_mask = (
            (ranked["as_of_date"] == as_of_date)
            & (ranked["gold_price_assumption"] == gold_price_assumption)
            & ranked["combined_score"].notna()
        )
        eligible_scores = pd.to_numeric(
            ranked.loc[eligible_mask, "combined_score"],
            errors="coerce",
        )
        if eligible_scores.empty:
            continue

        ranked.loc[eligible_mask, "combined_rank"] = (
            eligible_scores.rank(method="dense", ascending=False).astype("Int64")
        )

    return ranked


def _numeric(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
