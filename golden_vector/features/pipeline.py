"""Phase 3 Tool A horizon-return pipeline."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.horizons import build_core_horizons
from golden_vector.features.returns import RETURN_COLUMNS, compute_horizon_returns_for_ticker
from golden_vector.ingestion.persist import persist_horizon_outputs
from golden_vector.qa.horizon_quality import HorizonQaReport, evaluate_horizon_quality


@dataclass(frozen=True)
class HorizonExecutionResult:
    tool_a_tickers: list[str]
    horizon_metrics: pd.DataFrame
    qa_report: HorizonQaReport
    overall_status: str
    summary: dict[str, object]


def execute_horizon_pipeline(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    run_context: RunContext,
    gold_history: pd.DataFrame,
    normalized_equity_histories: dict[str, pd.DataFrame],
) -> HorizonExecutionResult:
    tool_a_tickers = [
        ticker.ticker
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_a_enabled
    ]
    if not tool_a_tickers:
        raise ValueError("No active Tool A tickers are configured in universe.yaml.")

    horizons = build_core_horizons(app_config.horizons)
    horizon_frames: list[pd.DataFrame] = []
    for ticker in tool_a_tickers:
        horizon_frames.append(
            compute_horizon_returns_for_ticker(
                usd_equity_history=normalized_equity_histories.get(
                    ticker,
                    pd.DataFrame(columns=RETURN_COLUMNS),
                ),
                gold_history=gold_history,
                horizons=horizons,
                near_zero_gold_return_threshold=app_config.qa.near_zero_gold_return_threshold,
            )
        )

    materialized = [frame for frame in horizon_frames if not frame.empty]
    horizon_metrics = (
        pd.concat(materialized, ignore_index=True)
        if materialized
        else pd.DataFrame(columns=RETURN_COLUMNS)
    )

    qa_report = evaluate_horizon_quality(
        tool_a_tickers=tool_a_tickers,
        horizon_metrics=horizon_metrics,
    )
    persist_horizon_outputs(
        paths=paths,
        run_context=run_context,
        horizon_metrics=horizon_metrics,
        qa_results=qa_report.results,
    )

    pass_rows = int((horizon_metrics["coverage_flag"] == "PASS").sum())
    fail_rows = int((horizon_metrics["coverage_flag"] == "FAIL").sum())
    official_rows = int(horizon_metrics["official_scoring_eligible"].fillna(False).sum())
    core_rows = int((horizon_metrics["horizon_mode"] == "core").sum())
    summary = {
        "tool_a_ticker_count": len(tool_a_tickers),
        "core_horizon_count": len(horizons),
        "horizon_row_count": len(horizon_metrics.index),
        "core_horizon_row_count": core_rows,
        "pass_horizon_row_count": pass_rows,
        "fail_horizon_row_count": fail_rows,
        "official_scoring_eligible_row_count": official_rows,
        "horizon_overall_status": qa_report.overall_status,
    }

    return HorizonExecutionResult(
        tool_a_tickers=tool_a_tickers,
        horizon_metrics=horizon_metrics,
        qa_report=qa_report,
        overall_status=qa_report.overall_status,
        summary=summary,
    )
