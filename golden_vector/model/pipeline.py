"""Tool A profile and ranking pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.delta import (
    assign_delta_bucket,
    compute_delta_component_score,
)
from golden_vector.features.gamma import compute_gamma_component_score
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

    tool_a_outputs = _build_tool_a_outputs(
        horizon_metrics=horizon_metrics,
        app_config=app_config,
        run_context=run_context,
    )
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


def _build_tool_a_outputs(
    *,
    horizon_metrics: pd.DataFrame,
    app_config: AppConfig,
    run_context: RunContext,
) -> pd.DataFrame:
    core_rows = horizon_metrics[horizon_metrics["horizon_mode"] == "core"].copy()
    if core_rows.empty:
        return pd.DataFrame(columns=TOOL_A_OUTPUT_COLUMNS)

    group_keys = ["ticker", "as_of_date"]
    grouped_core = core_rows.groupby(group_keys, dropna=False)
    profiles = grouped_core.agg(
        total_core_horizon_count=("horizon_id", "size"),
        pass_core_horizon_count=("coverage_flag", lambda values: int(values.eq("PASS").sum())),
        fail_core_horizon_count=("coverage_flag", lambda values: int(values.eq("FAIL").sum())),
    ).reset_index()

    eligible_mask = (
        core_rows["coverage_flag"].eq("PASS")
        & core_rows["official_scoring_eligible"].fillna(False).astype(bool)
    )
    eligible_rows = core_rows.loc[
        eligible_mask,
        ["ticker", "as_of_date", "gold_delta", "gold_return"],
    ].copy()
    eligible_rows["gold_delta"] = pd.to_numeric(
        eligible_rows["gold_delta"],
        errors="coerce",
    )
    eligible_rows["gold_return"] = pd.to_numeric(
        eligible_rows["gold_return"],
        errors="coerce",
    )

    if not eligible_rows.empty:
        eligible_counts = (
            eligible_rows.groupby(group_keys, dropna=False)
            .size()
            .rename("eligible_core_horizon_count")
            .reset_index()
        )
        profiles = profiles.merge(
            eligible_counts,
            how="left",
            on=group_keys,
        )

        valid_delta_rows = eligible_rows.dropna(subset=["gold_delta"]).copy()
        if not valid_delta_rows.empty:
            core_delta = (
                valid_delta_rows.groupby(group_keys, dropna=False)["gold_delta"]
                .median()
                .rename("core_delta")
                .reset_index()
            )
            profiles = profiles.merge(
                core_delta,
                how="left",
                on=group_keys,
            )

            delta_value_counts = (
                valid_delta_rows.groupby(group_keys, dropna=False)["gold_delta"]
                .count()
                .rename("delta_value_count")
                .reset_index()
            )
            profiles = profiles.merge(
                delta_value_counts,
                how="left",
                on=group_keys,
            )

            stability_rows = valid_delta_rows.merge(
                core_delta,
                how="left",
                on=group_keys,
            )
            stability_rows["absolute_delta_deviation"] = (
                stability_rows["gold_delta"] - stability_rows["core_delta"]
            ).abs()
            delta_mad = (
                stability_rows.groupby(group_keys, dropna=False)["absolute_delta_deviation"]
                .median()
                .rename("delta_mad")
                .reset_index()
            )
            profiles = profiles.merge(
                delta_mad,
                how="left",
                on=group_keys,
            )

        gamma_rows = eligible_rows.dropna(subset=["gold_delta", "gold_return"]).copy()
        if not gamma_rows.empty:
            gamma_rows["gold_abs_return"] = gamma_rows["gold_return"].abs()
            gamma_rows["gold_abs_return_sq"] = gamma_rows["gold_abs_return"] ** 2
            gamma_rows["gold_delta_sq"] = gamma_rows["gold_delta"] ** 2
            gamma_rows["gold_cross_term"] = (
                gamma_rows["gold_abs_return"] * gamma_rows["gold_delta"]
            )

            gamma_stats = gamma_rows.groupby(group_keys, dropna=False).agg(
                gamma_pair_count=("gold_delta", "size"),
                gold_abs_return_unique=("gold_abs_return", "nunique"),
                gold_delta_unique=("gold_delta", "nunique"),
                gold_abs_return_sum=("gold_abs_return", "sum"),
                gold_delta_sum=("gold_delta", "sum"),
                gold_abs_return_sq_sum=("gold_abs_return_sq", "sum"),
                gold_delta_sq_sum=("gold_delta_sq", "sum"),
                gold_cross_term_sum=("gold_cross_term", "sum"),
            ).reset_index()
            profiles = profiles.merge(
                gamma_stats,
                how="left",
                on=group_keys,
            )

    for column_name in (
        "eligible_core_horizon_count",
        "delta_value_count",
        "delta_mad",
        "core_delta",
        "gamma_pair_count",
        "gold_abs_return_unique",
        "gold_delta_unique",
        "gold_abs_return_sum",
        "gold_delta_sum",
        "gold_abs_return_sq_sum",
        "gold_delta_sq_sum",
        "gold_cross_term_sum",
    ):
        if column_name not in profiles.columns:
            profiles[column_name] = pd.NA

    profiles["eligible_core_horizon_count"] = profiles["eligible_core_horizon_count"].fillna(0).astype(int)
    profiles["delta_value_count"] = profiles["delta_value_count"].fillna(0).astype(int)
    profiles["delta_mad"] = pd.to_numeric(profiles["delta_mad"], errors="coerce")
    profiles["core_delta"] = pd.to_numeric(profiles["core_delta"], errors="coerce")
    profiles["stability_score"] = pd.Series(
        [pd.NA] * len(profiles.index),
        dtype="Float64",
    )

    stability_mask = (
        profiles["delta_value_count"].ge(2)
        & profiles["core_delta"].notna()
        & profiles["delta_mad"].notna()
    )
    if stability_mask.any():
        scale = np.maximum(
            profiles.loc[stability_mask, "core_delta"].abs().to_numpy(dtype=float),
            0.25,
        )
        mad = profiles.loc[stability_mask, "delta_mad"].to_numpy(dtype=float)
        stability_values = 1.0 / (1.0 + (mad / scale))
        profiles.loc[stability_mask, "stability_score"] = stability_values

    profiles["gamma_proxy"] = pd.Series(
        [pd.NA] * len(profiles.index),
        dtype="Float64",
    )
    gamma_pair_count = pd.to_numeric(profiles["gamma_pair_count"], errors="coerce").fillna(0)
    gold_abs_return_unique = pd.to_numeric(profiles["gold_abs_return_unique"], errors="coerce").fillna(0)
    gold_delta_unique = pd.to_numeric(profiles["gold_delta_unique"], errors="coerce").fillna(0)
    enough_pairs = gamma_pair_count.ge(2)
    constant_gamma_mask = enough_pairs & (
        gold_abs_return_unique.lt(2) | gold_delta_unique.lt(2)
    )
    if constant_gamma_mask.any():
        profiles.loc[constant_gamma_mask, "gamma_proxy"] = 0.0

    gamma_calc_mask = enough_pairs & ~constant_gamma_mask
    if gamma_calc_mask.any():
        n = gamma_pair_count.loc[gamma_calc_mask].to_numpy(dtype=float)
        sum_x = profiles.loc[gamma_calc_mask, "gold_abs_return_sum"].to_numpy(dtype=float)
        sum_y = profiles.loc[gamma_calc_mask, "gold_delta_sum"].to_numpy(dtype=float)
        sum_x2 = profiles.loc[gamma_calc_mask, "gold_abs_return_sq_sum"].to_numpy(dtype=float)
        sum_y2 = profiles.loc[gamma_calc_mask, "gold_delta_sq_sum"].to_numpy(dtype=float)
        sum_xy = profiles.loc[gamma_calc_mask, "gold_cross_term_sum"].to_numpy(dtype=float)

        numerator = (n * sum_xy) - (sum_x * sum_y)
        denominator = np.sqrt(
            np.maximum((n * sum_x2) - (sum_x**2), 0.0)
            * np.maximum((n * sum_y2) - (sum_y**2), 0.0)
        )
        gamma_values = np.zeros(len(n), dtype=float)
        valid_denominator = denominator > 0
        if valid_denominator.any():
            gamma_values[valid_denominator] = np.clip(
                numerator[valid_denominator] / denominator[valid_denominator],
                -1.0,
                1.0,
            )
        profiles.loc[gamma_calc_mask, "gamma_proxy"] = gamma_values

    coverage_summaries = []
    score_eligibilities = []
    score_reasons = []
    delta_buckets = []
    delta_component_scores = []
    gamma_component_scores = []
    tool_a_scores = []
    regime_tags = []

    for profile in profiles.itertuples(index=False):
        core_delta = _optional_float(profile.core_delta)
        stability_score = _optional_float(profile.stability_score)
        gamma_proxy = _optional_float(profile.gamma_proxy)

        coverage_summary = determine_coverage_summary(
            total_core_count=int(profile.total_core_horizon_count),
            eligible_core_count=int(profile.eligible_core_horizon_count),
            fail_core_count=int(profile.fail_core_horizon_count),
            minimum_core_horizons_for_scoring=app_config.scoring.minimum_core_horizons_for_scoring,
        )
        score_eligible, score_reason = determine_score_eligibility(
            core_delta=core_delta,
            eligible_core_count=int(profile.eligible_core_horizon_count),
            coverage_summary=coverage_summary,
            scoring_config=app_config.scoring,
        )
        delta_bucket = assign_delta_bucket(
            core_delta,
            app_config.scoring.delta_buckets,
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

        coverage_summaries.append(coverage_summary)
        score_eligibilities.append(score_eligible)
        score_reasons.append(score_reason)
        delta_buckets.append(delta_bucket)
        delta_component_scores.append(delta_component_score)
        gamma_component_scores.append(gamma_component_score)
        tool_a_scores.append(tool_a_score)
        regime_tags.append(regime_tag)

    profiles["coverage_summary"] = coverage_summaries
    profiles["score_eligible"] = score_eligibilities
    profiles["score_eligibility_reason"] = score_reasons
    profiles["delta_bucket"] = delta_buckets
    profiles["delta_component_score"] = delta_component_scores
    profiles["gamma_component_score"] = gamma_component_scores
    profiles["tool_a_score"] = tool_a_scores
    profiles["regime_tag"] = regime_tags
    profiles["tool_a_rank"] = pd.Series(
        [pd.NA] * len(profiles.index),
        dtype="Int64",
    )
    profiles["source_run_id"] = run_context.run_id

    output_columns = [
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
    return profiles[output_columns].copy()


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)
