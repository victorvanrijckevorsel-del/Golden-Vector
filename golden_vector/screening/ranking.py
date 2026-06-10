"""Tool B ranking helpers."""

from __future__ import annotations

import pandas as pd


def rank_tool_b_outputs(tool_b_outputs: pd.DataFrame) -> pd.DataFrame:
    if tool_b_outputs.empty:
        return tool_b_outputs.copy()

    ranked = tool_b_outputs.copy()
    ranked = _rank_score_column(
        ranked,
        score_column="fundamental_check_score",
        rank_column="fundamental_check_rank",
    )
    if "fundamental_check_score_official" in ranked.columns:
        ranked = _rank_score_column(
            ranked,
            score_column="fundamental_check_score_official",
            rank_column="fundamental_check_rank_official",
        )
    return ranked


def _rank_score_column(
    ranked: pd.DataFrame,
    *,
    score_column: str,
    rank_column: str,
) -> pd.DataFrame:
    ranked[rank_column] = pd.Series([pd.NA] * len(ranked.index), dtype="Int64")
    if score_column not in ranked.columns:
        return ranked

    group_columns = ["as_of_date", "gold_price_assumption"]
    for _, group in ranked.groupby(group_columns, dropna=False):
        group_index = group.index
        eligible_mask = ranked.index.isin(group_index) & ranked[score_column].notna()
        eligible_scores = pd.to_numeric(
            ranked.loc[eligible_mask, score_column],
            errors="coerce",
        )
        if eligible_scores.empty:
            continue

        ranked.loc[eligible_mask, rank_column] = (
            eligible_scores.rank(method="dense", ascending=False).astype("Int64")
        )

    return ranked
