"""Join published Tool A and Tool B outputs for the combined layer."""

from __future__ import annotations

import pandas as pd


def join_tool_outputs(
    *,
    tool_a_outputs: pd.DataFrame,
    tool_b_outputs: pd.DataFrame,
    gold_price_assumption: float,
) -> pd.DataFrame:
    tool_a_join = _prepare_tool_a_outputs(tool_a_outputs, gold_price_assumption)
    tool_b_join = _prepare_tool_b_outputs(tool_b_outputs)
    _assert_unique_join_keys(tool_a_join, dataset_name="tool_a_outputs")
    _assert_unique_join_keys(tool_b_join, dataset_name="tool_b_outputs")

    if tool_a_join.empty and tool_b_join.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "as_of_date",
                "gold_price_assumption",
                "core_delta",
                "regime_tag",
                "tool_a_score",
                "tool_a_rank",
                "coverage_summary",
                "tool_a_run_id",
                "screening_verdict",
                "confidence",
                "tool_b_score",
                "tool_b_rank",
                "best_upside_pct",
                "forward_pe",
                "fcf_yield",
                "tool_b_run_id",
            ]
        )

    joined = tool_a_join.merge(
        tool_b_join,
        how="outer",
        on=["ticker", "as_of_date", "gold_price_assumption"],
    )
    if "coverage_summary" not in joined.columns:
        joined["coverage_summary"] = pd.NA
    joined["coverage_summary"] = joined["coverage_summary"].fillna("TOOL_B_ONLY")
    return joined.sort_values(
        ["as_of_date", "gold_price_assumption", "ticker"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _prepare_tool_a_outputs(
    tool_a_outputs: pd.DataFrame,
    gold_price_assumption: float,
) -> pd.DataFrame:
    if tool_a_outputs.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "as_of_date",
                "gold_price_assumption",
                "core_delta",
                "regime_tag",
                "tool_a_score",
                "tool_a_rank",
                "coverage_summary",
                "tool_a_run_id",
            ]
        )

    return (
        tool_a_outputs[
            [
                "ticker",
                "as_of_date",
                "core_delta",
                "regime_tag",
                "tool_a_score",
                "tool_a_rank",
                "coverage_summary",
                "source_run_id",
            ]
        ]
        .rename(columns={"source_run_id": "tool_a_run_id"})
        .assign(gold_price_assumption=float(gold_price_assumption))
    )


def _prepare_tool_b_outputs(tool_b_outputs: pd.DataFrame) -> pd.DataFrame:
    if tool_b_outputs.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "as_of_date",
                "gold_price_assumption",
                "screening_verdict",
                "confidence",
                "tool_b_score",
                "tool_b_rank",
                "best_upside_pct",
                "forward_pe",
                "fcf_yield",
                "tool_b_run_id",
            ]
        )

    return tool_b_outputs[
        [
            "ticker",
            "as_of_date",
            "gold_price_assumption",
            "screening_verdict",
            "confidence",
            "tool_b_score",
            "tool_b_rank",
            "best_upside_pct",
            "forward_pe",
            "fcf_yield",
            "source_run_id",
        ]
    ].rename(columns={"source_run_id": "tool_b_run_id"})


def _assert_unique_join_keys(frame: pd.DataFrame, *, dataset_name: str) -> None:
    if frame.empty:
        return

    key_columns = ["ticker", "as_of_date", "gold_price_assumption"]
    duplicates = frame[frame.duplicated(subset=key_columns, keep=False)].copy()
    if duplicates.empty:
        return

    sample_records = (
        duplicates[key_columns]
        .drop_duplicates()
        .head(5)
        .to_dict(orient="records")
    )
    raise ValueError(
        f"{dataset_name} contains duplicate combined join keys: {sample_records}"
    )
