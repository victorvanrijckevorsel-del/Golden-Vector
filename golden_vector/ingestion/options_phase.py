"""Options ingestion phase for hedge-readiness data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_options
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.options import (
    compute_options_features,
    rank_options_iv_cross_section,
)
from golden_vector.ingestion.fetch_benchmarks import (
    BenchmarkFetchStatus,
    fetch_benchmark_histories,
)
from golden_vector.ingestion.fetch_options import (
    OPTIONS_STATUS_EMPTY,
    OPTIONS_STATUS_ERROR,
    OPTIONS_STATUS_SUCCESS,
    OptionsChainResult,
    fetch_options_chain,
)
from golden_vector.ingestion.fetch_risk_free_rate import fetch_risk_free_rate
from golden_vector.ingestion.persist_options import (
    OptionsSnapshotRecord,
    persist_options_snapshot,
    safe_options_file_name,
    write_latest_options_manifest,
)
from golden_vector.ingestion.yahoo_client import YahooClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OptionsPhaseResult:
    status: str
    summary: dict[str, Any]
    manifest_path: Path | None


def skipped_options_phase_summary(*, reason: str) -> dict[str, Any]:
    """Return the metadata summary used when options ingestion is intentionally skipped."""

    return {
        "options_phase_status": "SKIPPED",
        "options_phase_requested": False,
        "options_phase_skip_reason": reason,
    }


def run_options_ingestion_phase(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    app_config: AppConfig,
    normalized_equity_histories: dict[str, pd.DataFrame],
    as_of_date: date,
    yahoo_client: YahooClient | None = None,
) -> OptionsPhaseResult:
    """Fetch, persist, and feature-engineer the latest option-chain snapshot."""

    client = yahoo_client or YahooClient()
    active_tickers = [
        ticker.ticker
        for ticker in app_config.universe.tickers
        if ticker.active
    ]
    risk_free_rate, risk_free_message = _fetch_risk_free_rate(
        client=client,
        as_of_date=as_of_date,
    )
    benchmark_paths, benchmark_statuses = _fetch_and_persist_benchmarks(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        client=client,
    )

    snapshot_records: list[OptionsSnapshotRecord] = []
    feature_rows: list[dict[str, Any]] = []
    status_counts = {
        OPTIONS_STATUS_SUCCESS: 0,
        OPTIONS_STATUS_EMPTY: 0,
        OPTIONS_STATUS_ERROR: 0,
    }

    for ticker in active_tickers:
        try:
            result = fetch_options_chain(
                ticker=ticker,
                as_of_date=as_of_date,
                yahoo_client=client,
            )
            if result.status == OPTIONS_STATUS_ERROR:
                LOGGER.warning("Options fetch failed for %s: %s", ticker, result.message)

            record = persist_options_snapshot(
                paths=paths,
                run_context=run_context,
                ticker=ticker,
                frame=result.frame,
                as_of_date=as_of_date,
                options_available=result.options_available,
                message=result.message,
            )
            feature_row = _compute_feature_row(
                snapshot_record=record,
                options_result=result,
                paths=paths,
                ticker=ticker,
                as_of_date=as_of_date,
                risk_free_rate=risk_free_rate,
                run_id=run_context.run_id,
                app_config=app_config,
                price_history=normalized_equity_histories.get(ticker, pd.DataFrame()),
            )
        except Exception as exc:  # noqa: BLE001 - per-ticker best effort by design.
            status_counts[OPTIONS_STATUS_ERROR] = (
                status_counts.get(OPTIONS_STATUS_ERROR, 0) + 1
            )
            LOGGER.warning("Options pipeline failed for %s: %s", ticker, exc)
            continue

        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        snapshot_records.append(record)
        feature_rows.append(feature_row)

    feature_frame = pd.DataFrame(feature_rows)
    if not feature_frame.empty:
        feature_frame["iv_percentile_cross_sectional"] = rank_options_iv_cross_section(
            feature_frame,
        )
    feature_paths = _append_feature_rows(
        paths=paths,
        run_context=run_context,
        feature_rows=feature_frame.to_dict(orient="records"),
    )

    status = _phase_status(
        error_count=status_counts.get(OPTIONS_STATUS_ERROR, 0),
        risk_free_message=risk_free_message,
        benchmark_statuses=benchmark_statuses,
    )
    summary: dict[str, Any] = {
        "options_phase_status": status,
        "options_phase_requested": True,
        "options_as_of_date": as_of_date.isoformat(),
        "options_ticker_count": len(active_tickers),
        "options_success_count": status_counts.get(OPTIONS_STATUS_SUCCESS, 0),
        "options_empty_count": status_counts.get(OPTIONS_STATUS_EMPTY, 0),
        "options_error_count": status_counts.get(OPTIONS_STATUS_ERROR, 0),
        "options_feature_row_count": len(feature_rows),
        "options_feature_file_count": len(feature_paths),
        "risk_free_rate": risk_free_rate,
        "risk_free_rate_message": risk_free_message,
        "benchmark_count": len(benchmark_statuses),
        "benchmark_pass_count": sum(1 for item in benchmark_statuses if item.status == "PASS"),
        "benchmark_fail_count": sum(1 for item in benchmark_statuses if item.status == "FAIL"),
        "benchmark_snapshot_count": len(benchmark_paths),
    }
    manifest_path = write_latest_options_manifest(
        paths=paths,
        run_context=run_context,
        as_of_date=as_of_date,
        snapshot_records=snapshot_records,
        risk_free_rate=risk_free_rate,
        benchmark_snapshot_paths=benchmark_paths,
        summary=summary,
    )
    update_manifest_with_options(
        run_context.run_dir,
        options_manifest_path=manifest_path,
    )
    run_context.write_json("options_phase_summary.json", summary)
    return OptionsPhaseResult(status=status, summary=summary, manifest_path=manifest_path)


def _compute_feature_row(
    *,
    snapshot_record: OptionsSnapshotRecord,
    options_result: OptionsChainResult,
    paths: ProjectPaths,
    ticker: str,
    as_of_date: date,
    risk_free_rate: float | None,
    run_id: str,
    app_config: AppConfig,
    price_history: pd.DataFrame,
) -> dict[str, Any]:
    snapshot = pd.read_parquet(snapshot_record.snapshot_path)
    underlying_price = _underlying_price(
        snapshot=snapshot,
        options_result=options_result,
        price_history=price_history,
    )
    row = compute_options_features(
        chain=snapshot,
        underlying_price=underlying_price,
        risk_free_rate=risk_free_rate,
        price_history=price_history,
        as_of_date=as_of_date,
        target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
        target_delta=app_config.hedge_readiness.target_delta,
        optionability_open_interest_threshold=(
            app_config.hedge_readiness.optionability_open_interest_threshold
        ),
        implied_move_max_spread_pct=app_config.hedge_readiness.implied_move_max_spread_pct,
        implied_move_min_open_interest=(
            app_config.hedge_readiness.implied_move_min_open_interest
        ),
        implied_move_min_volume=app_config.hedge_readiness.implied_move_min_volume,
        candidate_max_spread_pct=app_config.hedge_readiness.candidate_max_spread_pct,
        candidate_min_open_interest=(
            app_config.hedge_readiness.candidate_min_open_interest
        ),
        candidate_min_volume=app_config.hedge_readiness.candidate_min_volume,
        candidate_min_implied_volatility=(
            app_config.hedge_readiness.candidate_min_implied_volatility
        ),
        candidate_max_implied_volatility=(
            app_config.hedge_readiness.candidate_max_implied_volatility
        ),
    )
    row["ticker"] = ticker
    row["run_id"] = run_id
    row["options_snapshot_path"] = snapshot_record.snapshot_path.relative_to(paths.repo_root).as_posix()
    row["options_fetch_status"] = options_result.status
    row["options_fetch_message"] = options_result.message
    row["underlying_price"] = underlying_price if underlying_price > 0 else None
    return row


def _append_feature_rows(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    feature_rows: list[dict[str, Any]],
) -> list[Path]:
    written_paths: list[Path] = []
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    for row in feature_rows:
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue
        path = paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet"
        frame = pd.DataFrame([row])
        if path.exists():
            existing = pd.read_parquet(path)
            run_id = str(row.get("run_id") or "")
            if run_id and "run_id" in existing.columns:
                existing = existing[existing["run_id"].astype(str) != run_id]
            frame = pd.concat([existing, frame], ignore_index=True)
        frame.to_parquet(path, index=False)
        run_context.record_artifact(path)
        written_paths.append(path)
    return written_paths


def _fetch_risk_free_rate(
    *,
    client: YahooClient,
    as_of_date: date,
) -> tuple[float | None, str | None]:
    try:
        return fetch_risk_free_rate(as_of_date=as_of_date, yahoo_client=client), None
    except Exception as exc:  # noqa: BLE001 - deltas can degrade to null.
        LOGGER.warning("Risk-free rate fetch failed: %s", exc)
        return None, str(exc)


def _fetch_and_persist_benchmarks(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    app_config: AppConfig,
    client: YahooClient,
) -> tuple[list[Path], list[BenchmarkFetchStatus]]:
    histories, statuses = fetch_benchmark_histories(
        client,
        app_config.benchmarks.benchmarks,
    )
    snapshot_dir = run_context.run_dir / "snapshots" / "benchmarks"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    paths.benchmarks_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for ticker, frame in sorted(histories.items()):
        run_path = snapshot_dir / f"{safe_options_file_name(ticker)}.parquet"
        latest_path = paths.benchmarks_dir / f"{safe_options_file_name(ticker)}.parquet"
        frame.to_parquet(run_path, index=False)
        frame.to_parquet(latest_path, index=False)
        run_context.record_artifact(run_path)
        run_context.record_artifact(latest_path)
        written_paths.append(run_path)
    return written_paths, statuses


def _underlying_price(
    *,
    snapshot: pd.DataFrame,
    options_result: OptionsChainResult,
    price_history: pd.DataFrame,
) -> float:
    if not snapshot.empty and "underlying_price" in snapshot.columns:
        values = pd.to_numeric(snapshot["underlying_price"], errors="coerce").dropna()
        if not values.empty and float(values.iloc[0]) > 0:
            return float(values.iloc[0])
    if not options_result.frame.empty and "underlying_price" in options_result.frame.columns:
        values = pd.to_numeric(options_result.frame["underlying_price"], errors="coerce").dropna()
        if not values.empty and float(values.iloc[0]) > 0:
            return float(values.iloc[0])
    if not price_history.empty and "adj_close_usd" in price_history.columns:
        values = pd.to_numeric(price_history["adj_close_usd"], errors="coerce").dropna()
        if not values.empty and float(values.iloc[-1]) > 0:
            return float(values.iloc[-1])
    return 0.0


def _phase_status(
    *,
    error_count: int,
    risk_free_message: str | None,
    benchmark_statuses: list[BenchmarkFetchStatus],
) -> str:
    if error_count or risk_free_message or any(item.status == "FAIL" for item in benchmark_statuses):
        return "WARN"
    return "PASS"
