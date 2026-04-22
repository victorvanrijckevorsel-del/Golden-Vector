"""Phase 7 combined Tool A + Tool B pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.combined.join import join_tool_outputs
from golden_vector.combined.ranking import (
    compute_combined_score,
    determine_combined_verdict,
    determine_join_status,
    rank_combined_outputs,
)
from golden_vector.contracts.config_models import ScoringConfig
from golden_vector.ingestion.persist import persist_combined_outputs


COMBINED_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "gold_price_assumption",
    "core_delta",
    "regime_tag",
    "tool_a_score",
    "tool_a_rank",
    "screening_verdict",
    "confidence",
    "tool_b_score",
    "tool_b_rank",
    "best_upside_pct",
    "forward_pe",
    "fcf_yield",
    "combined_score",
    "combined_rank",
    "combined_verdict",
    "join_status",
    "coverage_summary",
    "tool_a_run_id",
    "tool_b_run_id",
    "combined_run_id",
]


@dataclass(frozen=True)
class CombinedExecutionResult:
    combined_outputs: pd.DataFrame
    overall_status: str
    summary: dict[str, object]


def execute_combined_pipeline(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    scoring_config: ScoringConfig,
    tool_a_outputs: pd.DataFrame,
    tool_b_outputs: pd.DataFrame,
    gold_price_assumption: float,
) -> CombinedExecutionResult:
    joined = join_tool_outputs(
        tool_a_outputs=tool_a_outputs,
        tool_b_outputs=tool_b_outputs,
        gold_price_assumption=gold_price_assumption,
    )

    if joined.empty:
        combined_outputs = pd.DataFrame(columns=COMBINED_OUTPUT_COLUMNS)
        persist_combined_outputs(
            paths=paths,
            run_context=run_context,
            combined_outputs=combined_outputs,
        )
        return CombinedExecutionResult(
            combined_outputs=combined_outputs,
            overall_status="FAIL",
            summary={
                "combined_output_row_count": 0,
                "complete_row_count": 0,
                "partial_row_count": 0,
                "ranked_row_count": 0,
                "combined_output_overall_status": "FAIL",
            },
        )

    combined_outputs = joined.copy()
    combined_outputs["join_status"] = combined_outputs.apply(determine_join_status, axis=1)
    combined_outputs["combined_score"] = combined_outputs.apply(compute_combined_score, axis=1)
    combined_outputs["combined_verdict"] = combined_outputs.apply(
        determine_combined_verdict,
        axis=1,
        thresholds=scoring_config.combined_verdict_thresholds,
    )
    combined_outputs["combined_run_id"] = run_context.run_id
    combined_outputs = rank_combined_outputs(combined_outputs)
    combined_outputs = combined_outputs[COMBINED_OUTPUT_COLUMNS].sort_values(
        ["as_of_date", "gold_price_assumption", "combined_rank", "ticker"],
        ascending=[True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    persist_combined_outputs(
        paths=paths,
        run_context=run_context,
        combined_outputs=combined_outputs,
    )

    complete_row_count = int((combined_outputs["join_status"] == "COMPLETE").sum())
    partial_row_count = int((combined_outputs["join_status"] == "PARTIAL").sum())
    ranked_row_count = int(combined_outputs["combined_rank"].notna().sum())

    overall_status = "PASS"
    if combined_outputs.empty:
        overall_status = "FAIL"
    elif complete_row_count == 0:
        overall_status = "WARN"
    elif partial_row_count > 0:
        overall_status = "WARN"

    summary = {
        "combined_output_row_count": len(combined_outputs.index),
        "complete_row_count": complete_row_count,
        "partial_row_count": partial_row_count,
        "ranked_row_count": ranked_row_count,
        "combined_output_overall_status": overall_status,
    }
    if not combined_outputs.empty:
        latest_as_of_date = combined_outputs["as_of_date"].max()
        latest_rows = combined_outputs[combined_outputs["as_of_date"] == latest_as_of_date]
        summary["latest_output_as_of_date"] = str(latest_as_of_date)
        summary["latest_snapshot_row_count"] = len(latest_rows.index)

    return CombinedExecutionResult(
        combined_outputs=combined_outputs,
        overall_status=overall_status,
        summary=summary,
    )
