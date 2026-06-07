"""Tool B ranking helpers."""

from __future__ import annotations

import pandas as pd


def rank_tool_b_outputs(tool_b_outputs: pd.DataFrame) -> pd.DataFrame:
    if tool_b_outputs.empty:
        return tool_b_outputs.copy()

    ranked = tool_b_outputs.copy()
    ranked["fundamental_check_rank"] = pd.Series(
        [pd.NA] * len(ranked.index),
        dtype="Int64",
    )

    group_columns = ["as_of_date", "gold_price_assumption"]
    for _, group in ranked.groupby(group_columns, dropna=False):
        group_index = group.index
        eligible_mask = ranked.index.isin(group_index) & ranked[
            "fundamental_check_score"
        ].notna()
        eligible_scores = pd.to_numeric(
            ranked.loc[eligible_mask, "fundamental_check_score"],
            errors="coerce",
        )
        if eligible_scores.empty:
            continue

        ranked.loc[eligible_mask, "fundamental_check_rank"] = (
            eligible_scores.rank(method="dense", ascending=False).astype("Int64")
        )

    return ranked
