"""Checked portfolio artifact readers for the workspace UI."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.model_state import resolve_current_model_artifact_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.parquet import ParquetSchemaError, read_required_parquet
from golden_vector.portfolio.models import (
    PortfolioStaleSchemaError,
    PORTFOLIO_SCHEMA_VERSION,
)
from golden_vector.portfolio.benchmark_betas import (
    BENCHMARK_BETA_COLUMNS,
    BENCHMARK_BETA_DISPLAY_WINDOW_COLUMNS,
    BENCHMARK_BETA_REQUIRED_COLUMNS,
)
from golden_vector.portfolio.m4_artifacts import (
    CORRELATION_COLUMNS,
    HEDGE_SIZING_COLUMNS,
    RECONCILIATION_EXPORT_COLUMNS,
    VALUE_HISTORY_COLUMNS,
)
from golden_vector.portfolio.pipeline import (
    LINE_COLUMNS,
    POSITION_COLUMNS,
    SUMMARY_COLUMNS,
)
from golden_vector.portfolio.reconciliation import RECONCILIATION_COLUMNS


@dataclass(frozen=True)
class PortfolioData:
    lines: pd.DataFrame
    positions: pd.DataFrame
    summary: pd.DataFrame
    benchmark_betas: pd.DataFrame
    reconciliation: pd.DataFrame
    hedge_sizing: pd.DataFrame
    correlations: pd.DataFrame
    value_history: pd.DataFrame
    reconciliation_export: pd.DataFrame
    artifacts_missing: bool = False


def load_portfolio_data(paths: ProjectPaths) -> PortfolioData:
    artifact_paths = {
        "portfolio_lines": resolve_current_model_artifact_path(paths, "portfolio_lines"),
        "portfolio_positions": resolve_current_model_artifact_path(paths, "portfolio_positions"),
        "portfolio_summary": resolve_current_model_artifact_path(paths, "portfolio_summary"),
        "benchmark_betas": resolve_current_model_artifact_path(paths, "benchmark_betas"),
        "portfolio_reconciliation": resolve_current_model_artifact_path(paths, "portfolio_reconciliation"),
        "portfolio_hedge_sizing": resolve_current_model_artifact_path(paths, "portfolio_hedge_sizing"),
        "portfolio_correlations": resolve_current_model_artifact_path(paths, "portfolio_correlations"),
        "portfolio_value_history": resolve_current_model_artifact_path(paths, "portfolio_value_history"),
        "portfolio_reconciliation_export": resolve_current_model_artifact_path(
            paths,
            "portfolio_reconciliation_export",
        ),
    }
    missing = [name for name, path in artifact_paths.items() if path is None]
    if len(missing) == len(artifact_paths):
        return PortfolioData(
            lines=pd.DataFrame(columns=LINE_COLUMNS),
            positions=pd.DataFrame(columns=POSITION_COLUMNS),
            summary=pd.DataFrame(columns=SUMMARY_COLUMNS),
            benchmark_betas=pd.DataFrame(columns=BENCHMARK_BETA_COLUMNS),
            reconciliation=pd.DataFrame(columns=RECONCILIATION_COLUMNS),
            hedge_sizing=pd.DataFrame(columns=HEDGE_SIZING_COLUMNS),
            correlations=pd.DataFrame(columns=CORRELATION_COLUMNS),
            value_history=pd.DataFrame(columns=VALUE_HISTORY_COLUMNS),
            reconciliation_export=pd.DataFrame(columns=RECONCILIATION_EXPORT_COLUMNS),
            artifacts_missing=True,
        )
    if missing:
        raise PortfolioStaleSchemaError(
            "Portfolio artifacts are incomplete. Missing: "
            f"{', '.join(missing)}. Run python main.py refresh."
        )
    line_path = artifact_paths["portfolio_lines"]
    position_path = artifact_paths["portfolio_positions"]
    summary_path = artifact_paths["portfolio_summary"]
    benchmark_beta_path = artifact_paths["benchmark_betas"]
    reconciliation_path = artifact_paths["portfolio_reconciliation"]
    hedge_sizing_path = artifact_paths["portfolio_hedge_sizing"]
    correlations_path = artifact_paths["portfolio_correlations"]
    value_history_path = artifact_paths["portfolio_value_history"]
    reconciliation_export_path = artifact_paths["portfolio_reconciliation_export"]
    assert line_path is not None
    assert position_path is not None
    assert summary_path is not None
    assert benchmark_beta_path is not None
    assert reconciliation_path is not None
    assert hedge_sizing_path is not None
    assert correlations_path is not None
    assert value_history_path is not None
    assert reconciliation_export_path is not None
    try:
        # Benchmark betas: require everything EXCEPT the optional display-only 2Y/5Y betas,
        # then backfill those with NA. A pre-Phase-2 artifact lacks the 2Y/5Y columns; the
        # portfolio page does not use them, so it stays usable (the overview's 2Y/5Y
        # reference rows show the explicit "n/a for this window" cue, not a 503).
        benchmark_betas = read_required_parquet(
            benchmark_beta_path,
            label="benchmark betas",
            required_columns=BENCHMARK_BETA_REQUIRED_COLUMNS,
            schema_version=PORTFOLIO_SCHEMA_VERSION,
        )
        for _display_column in BENCHMARK_BETA_DISPLAY_WINDOW_COLUMNS:
            if _display_column not in benchmark_betas.columns:
                benchmark_betas[_display_column] = pd.NA
        return PortfolioData(
            lines=read_required_parquet(
                line_path,
                label="portfolio lines",
                required_columns=LINE_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            positions=read_required_parquet(
                position_path,
                label="portfolio positions",
                required_columns=POSITION_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            summary=read_required_parquet(
                summary_path,
                label="portfolio summary",
                required_columns=SUMMARY_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            benchmark_betas=benchmark_betas,
            reconciliation=read_required_parquet(
                reconciliation_path,
                label="portfolio reconciliation",
                required_columns=RECONCILIATION_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            hedge_sizing=read_required_parquet(
                hedge_sizing_path,
                label="portfolio hedge sizing",
                required_columns=HEDGE_SIZING_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            correlations=read_required_parquet(
                correlations_path,
                label="portfolio correlations",
                required_columns=CORRELATION_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            value_history=read_required_parquet(
                value_history_path,
                label="portfolio value history",
                required_columns=VALUE_HISTORY_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
            reconciliation_export=read_required_parquet(
                reconciliation_export_path,
                label="portfolio reconciliation export",
                required_columns=RECONCILIATION_EXPORT_COLUMNS,
                schema_version=PORTFOLIO_SCHEMA_VERSION,
            ),
        )
    except (ParquetSchemaError, ValueError, FileNotFoundError) as exc:
        raise PortfolioStaleSchemaError(str(exc)) from exc
