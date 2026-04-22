"""Tool B ranking helpers."""

from __future__ import annotations

import pandas as pd


def rank_tool_b_outputs(tool_b_outputs: pd.DataFrame) -> pd.DataFrame:
    if tool_b_outputs.empty:
        return tool_b_outputs.copy()

    ranked = tool_b_outputs.copy()
    ranked["tool_b_rank"] = pd.Series([pd.NA] * len(ranked.index), dtype="Int64")

    for keys, _ in ranked.groupby(["as_of_date", "gold_price_assumption"], dropna=False):
        as_of_date, gold_price_assumption = keys
        eligible_mask = (
            (ranked["as_of_date"] == as_of_date)
            & (ranked["gold_price_assumption"] == gold_price_assumption)
            & ranked["tool_b_score"].notna()
        )
        eligible_scores = pd.to_numeric(
            ranked.loc[eligible_mask, "tool_b_score"],
            errors="coerce",
        )
        if eligible_scores.empty:
            continue

        ranked.loc[eligible_mask, "tool_b_rank"] = (
            eligible_scores.rank(method="dense", ascending=False).astype("Int64")
        )

    return ranked
