"""Tool A profile and ranking pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.delta import (
    assign_delta_bucket,
    compute_core_delta,
    compute_delta_component_score,
)
from golden_vector.features.gamma import (
    compute_gamma_component_score,
    compute_gamma_proxy,
)
from golden_vector.features.stability import compute_stability_score
from golden_vector.ingestion.persist import persist_tool_a_outputs
from golden_vector.model.labels import (
    determine_coverage_summary,
    determine_regime_tag,
    determine_score_eligibility,
)
from golden_vector.model.scoring import compute_tool_a_score, rank_tool_a_outputs


TOOL_A_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "core_delta",
    "delta_bucket",
    "gamma_proxy",
    "stability_score",
    "regime_tag",
    "tool_a_score",
    "tool_a_rank",
    "score_eligible",
    "score_eligibility_reason",
    "coverage_summary",
    "eligible_core_horizon_count",
    "pass_core_horizon_count",
    "fail_core_horizon_count",
    "total_core_horizon_count",
    "source_run_id",
]


@dataclass(frozen=True)
class ToolAProfileExecutionResult:
    tool_a_outputs: pd.DataFrame
    overall_status: str
    summary: dict[str, object]


def execute_tool_a_profile_pipeline(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    run_context: RunContext,
    horizon_metrics: pd.DataFrame,
) -> ToolAProfileExecutionResult:
    rows: list[dict[str, object]] = []
    if horizon_metrics.empty:
        tool_a_outputs = pd.DataFrame(columns=TOOL_A_OUTPUT_COLUMNS)
        persist_tool_a_outputs(
            paths=paths,
            run_context=run_context,
            tool_a_outputs=tool_a_outputs,
        )
        return ToolAProfileExecutionResult(
            tool_a_outputs=tool_a_outputs,
            overall_status="FAIL",
            summary={
                "tool_a_output_row_count": 0,
                "score_eligible_row_count": 0,
                "ranked_row_count": 0,
                "tool_a_output_overall_status": "FAIL",
            },
        )

    grouped = horizon_metrics.groupby(["ticker", "as_of_date"], dropna=False)
    for (ticker, as_of_date), group in grouped:
        core_rows = group[group["horizon_mode"] == "core"].copy()
        pass_core_rows = core_rows[core_rows["coverage_flag"] == "PASS"].copy()
        eligible_core_rows = core_rows[
            core_rows["coverage_flag"].eq("PASS")
            & core_rows["official_scoring_eligible"].fillna(False).astype(bool)
        ].copy()

        total_core_count = len(core_rows.index)
        pass_core_count = len(pass_core_rows.index)
        fail_core_count = int((core_rows["coverage_flag"] == "FAIL").sum())
        eligible_core_count = len(eligible_core_rows.index)

        core_delta = compute_core_delta(eligible_core_rows)
        delta_bucket = assign_delta_bucket(
            core_delta,
            app_config.scoring.delta_buckets,
        )
        stability_score = compute_stability_score(
            eligible_core_rows,
            core_delta=core_delta,
        )
        gamma_proxy = compute_gamma_proxy(eligible_core_rows)
        coverage_summary = determine_coverage_summary(
            total_core_count=total_core_count,
            eligible_core_count=eligible_core_count,
            fail_core_count=fail_core_count,
            minimum_core_horizons_for_scoring=app_config.scoring.minimum_core_horizons_for_scoring,
        )
        score_eligible, score_reason = determine_score_eligibility(
            core_delta=core_delta,
            eligible_core_count=eligible_core_count,
            coverage_summary=coverage_summary,
            scoring_config=app_config.scoring,
        )
        delta_component_score = compute_delta_component_score(
            core_delta,
            app_config.scoring.delta_buckets,
        )
        gamma_component_score = compute_gamma_component_score(gamma_proxy)
        tool_a_score = compute_tool_a_score(
            delta_component_score=delta_component_score,
            stability_score=stability_score,
            gamma_component_score=gamma_component_score,
            score_eligible=score_eligible,
            weights=app_config.scoring.weights,
        )
        regime_tag = determine_regime_tag(
            core_delta=core_delta,
            delta_bucket=delta_bucket,
            stability_score=stability_score,
            gamma_proxy=gamma_proxy,
            scoring_config=app_config.scoring,
        )

        rows.append(
            {
                "ticker": str(ticker),
                "as_of_date": as_of_date,
                "core_delta": core_delta,
                "delta_bucket": delta_bucket,
                "gamma_proxy": gamma_proxy,
                "stability_score": stability_score,
                "regime_tag": regime_tag,
                "tool_a_score": tool_a_score,
                "tool_a_rank": None,
                "score_eligible": score_eligible,
                "score_eligibility_reason": score_reason,
                "coverage_summary": coverage_summary,
                "eligible_core_horizon_count": eligible_core_count,
                "pass_core_horizon_count": pass_core_count,
                "fail_core_horizon_count": fail_core_count,
                "total_core_horizon_count": total_core_count,
                "source_run_id": run_context.run_id,
            }
        )

    tool_a_outputs = pd.DataFrame(rows, columns=TOOL_A_OUTPUT_COLUMNS)
    if not tool_a_outputs.empty:
        tool_a_outputs = rank_tool_a_outputs(tool_a_outputs)
        tool_a_outputs = tool_a_outputs.sort_values(
            ["as_of_date", "tool_a_rank", "ticker"],
            ascending=[True, True, True],
            na_position="last",
        ).reset_index(drop=True)

    persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=tool_a_outputs,
    )

    score_eligible_count = (
        int(tool_a_outputs["score_eligible"].fillna(False).sum())
        if not tool_a_outputs.empty
        else 0
    )
    ranked_count = (
        int(tool_a_outputs["tool_a_rank"].notna().sum())
        if not tool_a_outputs.empty
        else 0
    )
    overall_status = "PASS"
    if tool_a_outputs.empty:
        overall_status = "FAIL"
    elif score_eligible_count == 0:
        overall_status = "WARN"

    summary = {
        "tool_a_output_row_count": len(tool_a_outputs.index),
        "score_eligible_row_count": score_eligible_count,
        "ranked_row_count": ranked_count,
        "tool_a_output_overall_status": overall_status,
    }
    if not tool_a_outputs.empty:
        latest_as_of_date = tool_a_outputs["as_of_date"].max()
        latest_rows = tool_a_outputs[tool_a_outputs["as_of_date"] == latest_as_of_date]
        summary["latest_output_as_of_date"] = str(latest_as_of_date)
        summary["latest_snapshot_row_count"] = len(latest_rows.index)

    return ToolAProfileExecutionResult(
        tool_a_outputs=tool_a_outputs,
        overall_status=overall_status,
        summary=summary,
    )
