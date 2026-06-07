"""Structural Tool A profile and ranking pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.common.numeric import strict_optional_float as _optional_float
from golden_vector.contracts.config_models import AppConfig, ScoringConfig
from golden_vector.ingestion.persist import (
    _latest_snapshot,
    persist_tool_a_outputs,
    persist_tool_a_structural_metrics,
)
from golden_vector.model.explanations import (
    build_asymmetry_explanation,
    build_confidence_explanation,
    build_delta_explanation,
    build_gamma_explanation,
    build_interaction_explanation,
    build_summary_explanation,
    build_volatility_explanation,
)
from golden_vector.model.labels import (
    determine_confidence_label,
    determine_profile_label,
    determine_score_eligibility,
    determine_volatility_context,
)
from golden_vector.model.scoring import (
    compute_asymmetry_component_score,
    compute_delta_component_score,
    compute_gamma_component_score,
    compute_tool_a_score,
    rank_tool_a_outputs,
)
from golden_vector.model.structural import (
    build_structural_history_frames,
    choose_structural_anchor_window,
    compute_volatility_diagnostics,
    weighted_median,
)


TOOL_A_OUTPUT_COLUMNS = [
    "ticker",
    "as_of_date",
    "anchor_window_id",
    "volatility_anchor_window_id",
    "structural_delta_6m",
    "structural_delta_12m",
    "structural_delta_3y",
    "structural_delta_core",
    "gamma_6m",
    "gamma_12m",
    "gamma_3y",
    "structural_gamma_core",
    "up_beta_6m",
    "down_beta_6m",
    "up_beta_12m",
    "down_beta_12m",
    "up_beta_3y",
    "down_beta_3y",
    "up_beta_core",
    "down_beta_core",
    "asymmetry_ratio_6m",
    "asymmetry_ratio_12m",
    "asymmetry_ratio_3y",
    "asymmetry_ratio_core",
    "r_squared_6m",
    "r_squared_12m",
    "r_squared_3y",
    "weeks_6m",
    "weeks_12m",
    "weeks_3y",
    "window_status_6m",
    "window_status_12m",
    "window_status_3y",
    "delta_stability_score",
    "confidence_score",
    "confidence_label",
    "total_volatility_52w",
    "residual_volatility_52w",
    "downside_volatility_52w",
    "volatility_context",
    "profile_label",
    "tool_a_score",
    "tool_a_rank",
    "score_eligible",
    "score_eligibility_reason",
    "eligible_structural_window_count",
    "positive_delta_window_count",
    "normalization_issue_summary",
    "snapshot_refresh_run_id",
    "fx_policy_max_staleness_days",
    "fx_policy_block_on_stale_fx",
    "delta_explanation",
    "gamma_explanation",
    "asymmetry_explanation",
    "volatility_explanation",
    "confidence_explanation",
    "interaction_explanation",
    "tool_a_summary_explanation",
    "source_run_id",
]


@dataclass(frozen=True)
class ToolAProfileExecutionResult:
    tool_a_outputs: pd.DataFrame
    structural_window_metrics: pd.DataFrame
    overall_status: str
    summary: dict[str, object]


def execute_tool_a_profile_pipeline(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    run_context: RunContext,
    gold_history: pd.DataFrame,
    normalized_equity_histories: dict[str, pd.DataFrame],
    snapshot_refresh_run_id: str,
) -> ToolAProfileExecutionResult:
    tool_a_tickers = [
        ticker.ticker
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_a_enabled
    ]
    stage_timings: dict[str, dict[str, object]] = {}

    started_at = perf_counter()
    structural_frames = build_structural_history_frames(
        tickers=tool_a_tickers,
        normalized_equity_histories=normalized_equity_histories,
        gold_history=gold_history,
        scoring_config=app_config.scoring,
    )
    structural_window_metrics = structural_frames.structural_window_metrics
    if not structural_window_metrics.empty:
        structural_window_metrics["source_run_id"] = run_context.run_id
    weekly_series = structural_frames.weekly_series
    _record_step_timing(
        stage_timings,
        "structural_build",
        started_at,
        rows_built=len(structural_window_metrics.index),
        extra={"weekly_series_rows": len(weekly_series.index)},
    )

    started_at = perf_counter()
    structural_paths = persist_tool_a_structural_metrics(
        paths=paths,
        run_context=run_context,
        structural_window_metrics=structural_window_metrics,
        publish_latest_aliases=not structural_window_metrics.empty,
    )
    _record_step_timing(
        stage_timings,
        "persist_structural_metrics",
        started_at,
        rows_built=len(structural_window_metrics.index),
        rows_persisted=len(structural_window_metrics.index),
        extra={"file_count": len(structural_paths)},
    )

    if structural_window_metrics.empty:
        tool_a_outputs = pd.DataFrame(columns=TOOL_A_OUTPUT_COLUMNS)
        started_at = perf_counter()
        output_paths = persist_tool_a_outputs(
            paths=paths,
            run_context=run_context,
            tool_a_outputs=tool_a_outputs,
            publish_latest_aliases=False,
        )
        _record_step_timing(
            stage_timings,
            "persist_outputs",
            started_at,
            rows_built=0,
            rows_persisted=0,
            extra={"file_count": len(output_paths)},
        )
        return ToolAProfileExecutionResult(
            tool_a_outputs=tool_a_outputs,
            structural_window_metrics=structural_window_metrics,
            overall_status="FAIL",
            summary={
                "tool_a_output_row_count": 0,
                "latest_snapshot_row_count": 0,
                "score_eligible_row_count": 0,
                "ranked_row_count": 0,
                "tool_a_output_overall_status": "FAIL",
                "tool_a_stage_timings": stage_timings,
            },
        )

    started_at = perf_counter()
    volatility_diagnostics = compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_window_metrics,
        scoring_config=app_config.scoring,
    )
    _record_step_timing(
        stage_timings,
        "volatility_diagnostics",
        started_at,
        rows_built=len(volatility_diagnostics.index),
    )

    started_at = perf_counter()
    tool_a_outputs = _build_tool_a_outputs(
        structural_window_metrics=structural_window_metrics,
        volatility_diagnostics=volatility_diagnostics,
        app_config=app_config,
        run_context=run_context,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
    )
    output_build_stats = dict(tool_a_outputs.attrs.get("output_build_stats") or {})
    _record_step_timing(
        stage_timings,
        "output_assembly",
        started_at,
        rows_built=len(tool_a_outputs.index),
        extra=output_build_stats,
    )
    if not tool_a_outputs.empty:
        started_at = perf_counter()
        tool_a_outputs = rank_tool_a_outputs(tool_a_outputs)
        tool_a_outputs = tool_a_outputs.sort_values(
            ["as_of_date", "tool_a_rank", "ticker"],
            ascending=[True, True, True],
            na_position="last",
        ).reset_index(drop=True)
        _record_step_timing(
            stage_timings,
            "rank_outputs",
            started_at,
            rows_built=len(tool_a_outputs.index),
        )

    latest_snapshot = _latest_snapshot(tool_a_outputs)
    started_at = perf_counter()
    output_paths = persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=tool_a_outputs,
        publish_latest_aliases=not tool_a_outputs.empty,
    )
    _record_step_timing(
        stage_timings,
        "persist_outputs",
        started_at,
        rows_built=len(tool_a_outputs.index),
        rows_persisted=len(latest_snapshot.index),
        extra={"file_count": len(output_paths)},
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
        "structural_window_metric_row_count": len(structural_window_metrics.index),
        "tool_a_output_row_count": len(tool_a_outputs.index),
        "latest_snapshot_row_count": len(latest_snapshot.index),
        "tool_a_output_unrestricted_group_count": int(
            output_build_stats.get("unrestricted_group_count") or 0
        ),
        "tool_a_output_built_group_count": int(
            output_build_stats.get("built_group_count") or len(tool_a_outputs.index)
        ),
        "tool_a_output_candidate_date_count": int(
            output_build_stats.get("candidate_date_count") or 0
        ),
        "tool_a_output_build_keep_ratio": _build_keep_ratio(
            rows_built=len(tool_a_outputs.index),
            rows_persisted=len(latest_snapshot.index),
        ),
        "score_eligible_row_count": score_eligible_count,
        "ranked_row_count": ranked_count,
        "tool_a_output_overall_status": overall_status,
        "official_structural_windows": app_config.scoring.structural_windows,
        "tool_a_stage_timings": stage_timings,
    }
    waste_warning = _build_keep_warning(
        rows_built=len(tool_a_outputs.index),
        rows_persisted=len(latest_snapshot.index),
    )
    if waste_warning:
        summary["tool_a_output_warnings"] = [waste_warning]
    if not tool_a_outputs.empty:
        latest_as_of_date = tool_a_outputs["as_of_date"].max()
        summary["latest_output_as_of_date"] = str(latest_as_of_date)

    return ToolAProfileExecutionResult(
        tool_a_outputs=tool_a_outputs,
        structural_window_metrics=structural_window_metrics,
        overall_status=overall_status,
        summary=summary,
    )


def _build_tool_a_outputs(
    *,
    structural_window_metrics: pd.DataFrame,
    volatility_diagnostics: pd.DataFrame,
    app_config: AppConfig,
    run_context: RunContext,
    snapshot_refresh_run_id: str,
    restrict_to_latest_snapshot_dates: bool = True,
) -> pd.DataFrame:
    metrics = structural_window_metrics.copy()
    metrics["as_of_date"] = pd.to_datetime(metrics["as_of_date"]).dt.date
    vol = volatility_diagnostics.copy()
    if not vol.empty:
        vol["as_of_date"] = pd.to_datetime(vol["as_of_date"]).dt.date

    unrestricted_group_count = _output_group_count(metrics)
    candidate_dates = _latest_snapshot_candidate_dates(metrics)
    if restrict_to_latest_snapshot_dates and candidate_dates:
        metrics = metrics.loc[metrics["as_of_date"].isin(candidate_dates)].copy()

    weight_map = app_config.scoring.structural_weight_map()
    grouped = metrics.groupby(["ticker", "as_of_date"], dropna=False)
    volatility_index = (
        vol.set_index(["ticker", "as_of_date"])
        if not vol.empty
        else None
    )
    rows: list[dict[str, object]] = []

    for (ticker, as_of_date), frame in grouped:
        window_map = {str(row.window_id).upper(): row for row in frame.itertuples(index=False)}
        eligible_frame = frame.loc[frame["window_status"].astype(str).eq("ELIGIBLE")].copy()
        delta_values = _window_value_map(
            eligible_frame=eligible_frame,
            window_map=window_map,
            column_name="structural_delta",
            weight_map=weight_map,
        )
        gamma_values = _window_value_map(
            eligible_frame=eligible_frame,
            window_map=window_map,
            column_name="gamma_value",
            weight_map=weight_map,
        )
        asymmetry_values = _window_value_map(
            eligible_frame=eligible_frame,
            window_map=window_map,
            column_name="asymmetry_ratio",
            weight_map=weight_map,
        )
        up_beta_values = _window_value_map(
            eligible_frame=eligible_frame,
            window_map=window_map,
            column_name="up_beta",
            weight_map=weight_map,
        )
        down_beta_values = _window_value_map(
            eligible_frame=eligible_frame,
            window_map=window_map,
            column_name="down_beta",
            weight_map=weight_map,
        )

        structural_delta_core = weighted_median(delta_values, weights=weight_map)
        structural_gamma_core = weighted_median(gamma_values, weights=weight_map)
        asymmetry_ratio_core = weighted_median(asymmetry_values, weights=weight_map)
        up_beta_core = weighted_median(up_beta_values, weights=weight_map)
        down_beta_core = weighted_median(down_beta_values, weights=weight_map)

        delta_stability_score = _compute_delta_stability_score(
            delta_values=delta_values,
            structural_delta_core=structural_delta_core,
            scoring_config=app_config.scoring,
        )
        normalization_issue_summary = _first_non_empty(
            frame["normalization_issue_summary"].tolist()
        )
        eligible_structural_window_count = int(len(eligible_frame.index))
        positive_delta_window_count = int(
            pd.to_numeric(eligible_frame["structural_delta"], errors="coerce").gt(0).sum()
        )
        confidence_score = _compute_confidence_score(
            delta_values=delta_values,
            eligible_window_metrics=eligible_frame,
            delta_stability_score=delta_stability_score,
            scoring_config=app_config.scoring,
        )
        score_eligible, score_reason = determine_score_eligibility(
            structural_delta_core=structural_delta_core,
            eligible_structural_window_count=eligible_structural_window_count,
            confidence_score=confidence_score,
            normalization_issue_summary=normalization_issue_summary,
            scoring_config=app_config.scoring,
        )
        confidence_label = determine_confidence_label(
            confidence_score=confidence_score,
            scoring_config=app_config.scoring,
            score_eligible=score_eligible,
            score_eligibility_reason=score_reason,
        )

        anchor_window_id = choose_structural_anchor_window(
            window_metrics=frame,
            scoring_config=app_config.scoring,
            require_eligible=True,
        ) or choose_structural_anchor_window(
            window_metrics=frame,
            scoring_config=app_config.scoring,
            require_eligible=False,
        )
        anchor_row = window_map.get(anchor_window_id) if anchor_window_id else None
        anchor_delta = _optional_float(getattr(anchor_row, "structural_delta", None))
        anchor_up_beta = _optional_float(getattr(anchor_row, "up_beta", None))
        anchor_down_beta = _optional_float(getattr(anchor_row, "down_beta", None))
        anchor_asymmetry_ratio = _optional_float(
            getattr(anchor_row, "asymmetry_ratio", None)
        )

        volatility_row = (
            volatility_index.loc[(ticker, as_of_date)].to_dict()
            if volatility_index is not None and (ticker, as_of_date) in volatility_index.index
            else {}
        )
        total_volatility_52w = _optional_float(volatility_row.get("total_volatility_52w"))
        residual_volatility_52w = _optional_float(
            volatility_row.get("residual_volatility_52w")
        )
        downside_volatility_52w = _optional_float(
            volatility_row.get("downside_volatility_52w")
        )
        volatility_anchor_window_id = volatility_row.get("volatility_anchor_window_id")
        volatility_context = determine_volatility_context(
            total_volatility_52w=total_volatility_52w,
            residual_volatility_52w=residual_volatility_52w,
            downside_volatility_52w=downside_volatility_52w,
            scoring_config=app_config.scoring,
        )

        delta_component_score = compute_delta_component_score(
            structural_delta_core,
            bands=app_config.scoring.delta_bands,
        )
        gamma_component_score = compute_gamma_component_score(
            structural_gamma_core,
            thresholds=app_config.scoring.gamma_thresholds,
        )
        asymmetry_component_score = compute_asymmetry_component_score(
            asymmetry_ratio=asymmetry_ratio_core,
            up_beta=up_beta_core,
            down_beta=down_beta_core,
            thresholds=app_config.scoring.asymmetry_thresholds,
        )
        tool_a_score = compute_tool_a_score(
            delta_component_score=delta_component_score,
            gamma_component_score=gamma_component_score,
            asymmetry_component_score=asymmetry_component_score,
            confidence_score=confidence_score,
            score_eligible=score_eligible,
            weights=app_config.scoring.weights,
        )
        profile_label = determine_profile_label(
            score_eligible=score_eligible,
            score_eligibility_reason=score_reason,
            structural_delta_core=structural_delta_core,
            structural_gamma_core=structural_gamma_core,
            asymmetry_ratio_core=asymmetry_ratio_core,
            up_beta_core=up_beta_core,
            down_beta_core=down_beta_core,
            confidence_label=confidence_label,
            residual_volatility_52w=residual_volatility_52w,
            volatility_context=volatility_context,
            scoring_config=app_config.scoring,
        )

        delta_explanation = build_delta_explanation(
            anchor_delta=anchor_delta,
            anchor_window_id=anchor_window_id,
            structural_delta_core=structural_delta_core,
            score_eligible=score_eligible,
            score_eligibility_reason=score_reason,
            scoring_config=app_config.scoring,
        )
        gamma_explanation = build_gamma_explanation(
            gamma_core=structural_gamma_core,
            up_beta_anchor=anchor_up_beta,
            down_beta_anchor=anchor_down_beta,
            anchor_window_id=anchor_window_id,
            score_eligible=score_eligible,
            score_eligibility_reason=score_reason,
            scoring_config=app_config.scoring,
        )
        asymmetry_explanation = build_asymmetry_explanation(
            asymmetry_ratio_anchor=anchor_asymmetry_ratio,
            up_beta_anchor=anchor_up_beta,
            down_beta_anchor=anchor_down_beta,
            score_eligibility_reason=score_reason,
            scoring_config=app_config.scoring,
        )
        volatility_explanation = build_volatility_explanation(
            volatility_context=volatility_context,
            residual_volatility_52w=residual_volatility_52w,
            downside_volatility_52w=downside_volatility_52w,
        )
        confidence_explanation = build_confidence_explanation(
            confidence_label=confidence_label,
            confidence_score=confidence_score,
            score_eligibility_reason=score_reason,
        )
        interaction_explanation = build_interaction_explanation(
            score_eligible=score_eligible,
            score_eligibility_reason=score_reason,
            profile_label=profile_label,
            structural_delta_core=structural_delta_core,
            structural_gamma_core=structural_gamma_core,
            asymmetry_ratio_core=asymmetry_ratio_core,
            volatility_context=volatility_context,
            confidence_label=confidence_label,
            scoring_config=app_config.scoring,
        )
        summary_explanation = build_summary_explanation(
            profile_label=profile_label,
            confidence_label=confidence_label,
            score_eligibility_reason=score_reason,
            interaction_explanation=interaction_explanation,
        )

        rows.append(
            {
                "ticker": ticker,
                "as_of_date": as_of_date,
                "anchor_window_id": anchor_window_id,
                "volatility_anchor_window_id": volatility_anchor_window_id,
                "structural_delta_6m": _optional_float(
                    getattr(window_map.get("6M"), "structural_delta", None)
                ),
                "structural_delta_12m": _optional_float(
                    getattr(window_map.get("12M"), "structural_delta", None)
                ),
                "structural_delta_3y": _optional_float(
                    getattr(window_map.get("3Y"), "structural_delta", None)
                ),
                "structural_delta_core": structural_delta_core,
                "gamma_6m": _optional_float(getattr(window_map.get("6M"), "gamma_value", None)),
                "gamma_12m": _optional_float(getattr(window_map.get("12M"), "gamma_value", None)),
                "gamma_3y": _optional_float(getattr(window_map.get("3Y"), "gamma_value", None)),
                "structural_gamma_core": structural_gamma_core,
                "up_beta_6m": _optional_float(getattr(window_map.get("6M"), "up_beta", None)),
                "down_beta_6m": _optional_float(getattr(window_map.get("6M"), "down_beta", None)),
                "up_beta_12m": _optional_float(getattr(window_map.get("12M"), "up_beta", None)),
                "down_beta_12m": _optional_float(getattr(window_map.get("12M"), "down_beta", None)),
                "up_beta_3y": _optional_float(getattr(window_map.get("3Y"), "up_beta", None)),
                "down_beta_3y": _optional_float(getattr(window_map.get("3Y"), "down_beta", None)),
                "up_beta_core": up_beta_core,
                "down_beta_core": down_beta_core,
                "asymmetry_ratio_6m": _optional_float(
                    getattr(window_map.get("6M"), "asymmetry_ratio", None)
                ),
                "asymmetry_ratio_12m": _optional_float(
                    getattr(window_map.get("12M"), "asymmetry_ratio", None)
                ),
                "asymmetry_ratio_3y": _optional_float(
                    getattr(window_map.get("3Y"), "asymmetry_ratio", None)
                ),
                "asymmetry_ratio_core": asymmetry_ratio_core,
                "r_squared_6m": _optional_float(getattr(window_map.get("6M"), "r_squared", None)),
                "r_squared_12m": _optional_float(getattr(window_map.get("12M"), "r_squared", None)),
                "r_squared_3y": _optional_float(getattr(window_map.get("3Y"), "r_squared", None)),
                "weeks_6m": int(getattr(window_map.get("6M"), "week_count", 0) or 0),
                "weeks_12m": int(getattr(window_map.get("12M"), "week_count", 0) or 0),
                "weeks_3y": int(getattr(window_map.get("3Y"), "week_count", 0) or 0),
                "window_status_6m": getattr(window_map.get("6M"), "window_status", None),
                "window_status_12m": getattr(window_map.get("12M"), "window_status", None),
                "window_status_3y": getattr(window_map.get("3Y"), "window_status", None),
                "delta_stability_score": delta_stability_score,
                "confidence_score": confidence_score,
                "confidence_label": confidence_label,
                "total_volatility_52w": total_volatility_52w,
                "residual_volatility_52w": residual_volatility_52w,
                "downside_volatility_52w": downside_volatility_52w,
                "volatility_context": volatility_context,
                "profile_label": profile_label,
                "tool_a_score": tool_a_score,
                "tool_a_rank": pd.NA,
                "score_eligible": score_eligible,
                "score_eligibility_reason": score_reason,
                "eligible_structural_window_count": eligible_structural_window_count,
                "positive_delta_window_count": positive_delta_window_count,
                "normalization_issue_summary": normalization_issue_summary,
                "snapshot_refresh_run_id": snapshot_refresh_run_id,
                "fx_policy_max_staleness_days": int(app_config.qa.max_fx_staleness_days),
                "fx_policy_block_on_stale_fx": bool(app_config.qa.block_on_stale_fx),
                "delta_explanation": delta_explanation,
                "gamma_explanation": gamma_explanation,
                "asymmetry_explanation": asymmetry_explanation,
                "volatility_explanation": volatility_explanation,
                "confidence_explanation": confidence_explanation,
                "interaction_explanation": interaction_explanation,
                "tool_a_summary_explanation": summary_explanation,
                "source_run_id": run_context.run_id,
            }
        )

    output = pd.DataFrame(rows, columns=TOOL_A_OUTPUT_COLUMNS)
    output.attrs["output_build_stats"] = {
        "unrestricted_group_count": int(unrestricted_group_count),
        "built_group_count": int(_output_group_count(metrics)),
        "candidate_date_count": int(len(candidate_dates)),
        "candidate_dates": [str(value) for value in sorted(candidate_dates)],
    }
    return output


def _latest_snapshot_candidate_dates(metrics: pd.DataFrame) -> set[object]:
    if metrics.empty or "ticker" not in metrics.columns or "as_of_date" not in metrics.columns:
        return set()
    latest_by_ticker = metrics.groupby("ticker")["as_of_date"].max()
    return set(latest_by_ticker.dropna().tolist())


def _output_group_count(metrics: pd.DataFrame) -> int:
    if metrics.empty:
        return 0
    return int(metrics[["ticker", "as_of_date"]].drop_duplicates().shape[0])


def _record_step_timing(
    timings: dict[str, dict[str, object]],
    step: str,
    started_at: float,
    *,
    rows_built: int | None = None,
    rows_persisted: int | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    entry: dict[str, object] = {
        "duration_seconds": round(perf_counter() - started_at, 3),
    }
    if rows_built is not None:
        entry["rows_built"] = int(rows_built)
    if rows_persisted is not None:
        entry["rows_persisted"] = int(rows_persisted)
    if extra:
        entry.update(extra)
    timings[step] = entry


def _build_keep_ratio(*, rows_built: int, rows_persisted: int) -> float | None:
    if rows_persisted <= 0:
        return None
    return round(float(rows_built) / float(rows_persisted), 4)


def _build_keep_warning(
    *,
    rows_built: int,
    rows_persisted: int,
    threshold: float = 5.0,
) -> str | None:
    ratio = _build_keep_ratio(rows_built=rows_built, rows_persisted=rows_persisted)
    if ratio is None or ratio <= threshold:
        return None
    return (
        "Tool A built "
        f"{rows_built} output rows but persisted {rows_persisted} latest rows "
        f"({ratio:.1f}x). Check for build-vs-keep waste."
    )


def _window_value_map(
    *,
    eligible_frame: pd.DataFrame,
    window_map: dict[str, object],
    column_name: str,
    weight_map: dict[str, float],
) -> dict[str, float | None]:
    eligible_window_ids = {
        str(value).upper() for value in eligible_frame["window_id"].astype(str).tolist()
    }
    values: dict[str, float | None] = {}
    for window_id in weight_map:
        if window_id not in eligible_window_ids:
            values[window_id] = None
            continue
        values[window_id] = _optional_float(getattr(window_map.get(window_id), column_name, None))
    return values


def _compute_delta_stability_score(
    *,
    delta_values: dict[str, float | None],
    structural_delta_core: float | None,
    scoring_config: ScoringConfig,
) -> float | None:
    usable = [
        float(value)
        for value in delta_values.values()
        if value is not None and pd.notna(value)
    ]
    if len(usable) < 2 or structural_delta_core is None:
        return None
    array = np.asarray(usable, dtype=float)
    mad = float(np.median(np.abs(array - float(structural_delta_core))))
    scale = max(
        abs(float(structural_delta_core)),
        scoring_config.confidence_thresholds.stability_floor,
    )
    return round(float(1.0 / (1.0 + (mad / scale))), 4)


def _compute_confidence_score(
    *,
    delta_values: dict[str, float | None],
    eligible_window_metrics: pd.DataFrame,
    delta_stability_score: float | None,
    scoring_config: ScoringConfig,
) -> float | None:
    if eligible_window_metrics.empty:
        return None

    total_windows = max(len(scoring_config.structural_windows), 1)
    coverage_score = len(eligible_window_metrics.index) / total_windows

    fit_values = pd.to_numeric(eligible_window_metrics["r_squared"], errors="coerce").dropna()
    mean_fit = float(fit_values.mean()) if not fit_values.empty else 0.0
    minimum_fit = float(fit_values.min()) if not fit_values.empty else 0.0
    fit_score = _clamp((0.6 * mean_fit) + (0.4 * minimum_fit))

    usable_deltas = [
        float(value)
        for value in delta_values.values()
        if value is not None and pd.notna(value)
    ]
    if len(usable_deltas) >= 2:
        signs = {1 if value > 0 else -1 if value < 0 else 0 for value in usable_deltas}
        sign_score = 1.0 if len(signs) == 1 else 0.35
    else:
        sign_score = 0.25

    stability_score = 0.0 if delta_stability_score is None else float(delta_stability_score)
    regime_ready_count = int(
        (
            eligible_window_metrics["up_beta"].notna()
            & eligible_window_metrics["down_beta"].notna()
        ).sum()
    )
    regime_score = regime_ready_count / total_windows

    confidence = (
        (0.25 * coverage_score)
        + (0.30 * fit_score)
        + (0.20 * sign_score)
        + (0.15 * stability_score)
        + (0.10 * regime_score)
    )
    return round(float(_clamp(confidence)), 4)


def _first_non_empty(values: list[object]) -> str | None:
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
