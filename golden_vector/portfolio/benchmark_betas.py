"""Portfolio benchmark beta artifact builder."""

from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.eligibility import is_score_eligible
from golden_vector.common.frames import latest_records_by_key
from golden_vector.common.numeric import optional_float
from golden_vector.common.parquet import read_optional_parquet
from golden_vector.contracts.config_models import AppConfig, BenchmarkTicker
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.model.pipeline import build_tool_a_outputs_from_metrics
from golden_vector.model.structural import (
    build_structural_history_frames,
    compute_volatility_diagnostics,
)
from golden_vector.normalize.prices_usd import normalize_equity_history_to_usd
from golden_vector.portfolio.models import PORTFOLIO_SCHEMA_VERSION

BENCHMARK_BETA_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "benchmark_ticker",
    "benchmark_label",
    "as_of_date",
    "anchor_window_id",
    "window_start",
    "window_end",
    "n_weeks",
    "benchmark_price_usd",
    "benchmark_price_date",
    "down_beta_core",
    "up_beta_core",
    "confidence_label",
    "confidence_score",
    "score_eligible",
    "method_version",
    "benchmark_status",
    "benchmark_status_reason",
]

BENCHMARK_BETA_METHOD_VERSION = "tool_a_structural_weekly_v1"
PUBLISHABLE_CONFIDENCE_LABELS = {"HIGH", "MEDIUM"}


def build_benchmark_betas_frame(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    gold_history: pd.DataFrame,
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    active_benchmarks = [
        benchmark
        for benchmark in app_config.benchmarks.benchmarks
        if benchmark.active
    ]
    raw_histories = {
        benchmark.ticker: _read_cached_benchmark_history(paths, benchmark)
        for benchmark in active_benchmarks
    }
    normalized_histories: dict[str, pd.DataFrame] = {}
    load_errors: dict[str, str] = {}
    for benchmark in active_benchmarks:
        raw = raw_histories.get(benchmark.ticker, pd.DataFrame())
        if raw.empty:
            load_errors[benchmark.ticker] = "No cached benchmark history is available."
            continue
        try:
            normalized_histories[benchmark.ticker] = normalize_equity_history_to_usd(
                frame=raw,
                fx_history=pd.DataFrame(),
                max_fx_staleness_days=app_config.qa.max_fx_staleness_days,
            )
        except Exception as exc:  # noqa: BLE001 - one bad benchmark must fail closed.
            load_errors[benchmark.ticker] = f"Benchmark history normalization failed: {exc}"

    structural_frames = build_structural_history_frames(
        tickers=[benchmark.ticker for benchmark in active_benchmarks],
        normalized_equity_histories=normalized_histories,
        gold_history=gold_history,
        scoring_config=app_config.scoring,
    )
    outputs = _benchmark_tool_a_outputs(
        structural_window_metrics=structural_frames.structural_window_metrics,
        weekly_series=structural_frames.weekly_series,
        app_config=app_config,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
    )
    latest_by_ticker = _latest_output_by_ticker(outputs)
    weekly_ranges = _weekly_ranges(structural_frames.weekly_series)
    latest_prices = {
        ticker: _latest_price_record(history)
        for ticker, history in normalized_histories.items()
    }

    rows = [
        _benchmark_row(
            benchmark,
            row=latest_by_ticker.get(benchmark.ticker),
            weekly_range=weekly_ranges.get(benchmark.ticker),
            price_record=latest_prices.get(benchmark.ticker),
            load_error=load_errors.get(benchmark.ticker),
            source_run_id=source_run_id,
            snapshot_refresh_run_id=snapshot_refresh_run_id,
            gold_history_empty=gold_history.empty,
        )
        for benchmark in active_benchmarks
    ]
    frame = pd.DataFrame(rows, columns=BENCHMARK_BETA_COLUMNS)
    frame.attrs["schema_version"] = PORTFOLIO_SCHEMA_VERSION
    frame.attrs["source_run_id"] = source_run_id
    frame.attrs["snapshot_refresh_run_id"] = snapshot_refresh_run_id
    return frame


def _benchmark_tool_a_outputs(
    *,
    structural_window_metrics: pd.DataFrame,
    weekly_series: pd.DataFrame,
    app_config: AppConfig,
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    if structural_window_metrics.empty:
        return pd.DataFrame()
    volatility = compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_window_metrics,
        scoring_config=app_config.scoring,
    )
    return build_tool_a_outputs_from_metrics(
        structural_window_metrics=structural_window_metrics,
        volatility_diagnostics=volatility,
        app_config=app_config,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
    )


def _weekly_ranges(weekly: pd.DataFrame) -> dict[str, tuple[date | None, date | None, int]]:
    if weekly.empty or "ticker" not in weekly.columns:
        return {}
    ranges: dict[str, tuple[date | None, date | None, int]] = {}
    for ticker, group in weekly.groupby("ticker", dropna=False):
        dates = pd.to_datetime(group.get("stock_week_date"), errors="coerce").dropna()
        if dates.empty:
            ranges[str(ticker).upper()] = (None, None, 0)
            continue
        ranges[str(ticker).upper()] = (
            dates.min().date(),
            dates.max().date(),
            int(len(dates.index)),
        )
    return ranges


def _latest_output_by_ticker(outputs: pd.DataFrame) -> dict[str, dict[str, object]]:
    return latest_records_by_key(outputs, "ticker", sort_column="as_of_date")


def _benchmark_row(
    benchmark: BenchmarkTicker,
    *,
    row: dict[str, object] | None,
    weekly_range: tuple[date | None, date | None, int] | None,
    price_record: dict[str, object] | None,
    load_error: str | None,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    gold_history_empty: bool,
) -> dict[str, object]:
    window_start, window_end, weekly_count = weekly_range or (None, None, 0)
    anchor_window_id = str(row.get("anchor_window_id") or "") if row else ""
    n_weeks = _anchor_week_count(row, anchor_window_id) if row else None
    confidence = str(row.get("confidence_label") or "").upper() if row else None
    down_beta = optional_float(row.get("down_beta_core")) if row else None
    up_beta = optional_float(row.get("up_beta_core")) if row else None
    score_eligible = (
        is_score_eligible(row.get("score_eligible"), default=False)
        if row is not None
        else False
    )
    status, reason = _benchmark_status(
        load_error=load_error,
        gold_history_empty=gold_history_empty,
        row=row,
        confidence=confidence,
        down_beta=down_beta,
        up_beta=up_beta,
    )
    return {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "source_run_id": source_run_id,
        "snapshot_refresh_run_id": snapshot_refresh_run_id,
        "benchmark_ticker": benchmark.ticker,
        "benchmark_label": benchmark.label,
        "as_of_date": row.get("as_of_date") if row else None,
        "anchor_window_id": anchor_window_id or None,
        "window_start": window_start,
        "window_end": window_end,
        "n_weeks": n_weeks if n_weeks is not None else weekly_count,
        "benchmark_price_usd": (
            optional_float(price_record.get("close_usd")) if price_record else None
        ),
        "benchmark_price_date": price_record.get("date") if price_record else None,
        "down_beta_core": down_beta,
        "up_beta_core": up_beta,
        "confidence_label": confidence,
        "confidence_score": optional_float(row.get("confidence_score")) if row else None,
        "score_eligible": score_eligible,
        "method_version": BENCHMARK_BETA_METHOD_VERSION,
        "benchmark_status": status,
        "benchmark_status_reason": reason,
    }


def _benchmark_status(
    *,
    load_error: str | None,
    gold_history_empty: bool,
    row: dict[str, object] | None,
    confidence: str | None,
    down_beta: float | None,
    up_beta: float | None,
) -> tuple[str, str | None]:
    if load_error:
        return "MISSING_HISTORY", load_error
    if gold_history_empty:
        return "MISSING_GOLD_HISTORY", "Gold history is missing."
    if row is None or down_beta is None or up_beta is None:
        return "UNAVAILABLE", "Benchmark beta could not be estimated."
    if confidence not in PUBLISHABLE_CONFIDENCE_LABELS:
        return "LOW_CONFIDENCE", f"Benchmark beta confidence is {confidence or 'UNKNOWN'}."
    return "OK", None


def _anchor_week_count(row: dict[str, object] | None, anchor_window_id: str) -> int | None:
    if not row or not anchor_window_id:
        return None
    value = optional_float(row.get(f"weeks_{anchor_window_id}"))
    if value is None:
        return None
    return int(value)


def _read_cached_benchmark_history(
    paths: ProjectPaths,
    benchmark: BenchmarkTicker,
) -> pd.DataFrame:
    path = paths.benchmarks_dir / f"{safe_options_file_name(benchmark.ticker)}.parquet"
    return read_optional_parquet(path)


def _latest_price_record(frame: pd.DataFrame) -> dict[str, object] | None:
    if frame.empty or "date" not in frame.columns:
        return None
    working = frame.copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working = working.dropna(subset=["date"]).sort_values("date")
    if working.empty:
        return None
    row = working.iloc[-1].to_dict()
    row["date"] = working.iloc[-1]["date"].date()
    return row
