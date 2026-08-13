"""Options ingestion phase for hedge-readiness data."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_options
from golden_vector.app.run_context import RunContext
from golden_vector.common.numeric import bool_or_false, int_or_zero, optional_float
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.options import (
    compute_options_features,
    rank_options_iv_cross_section,
)
from golden_vector.ingestion.collection_resilience import (
    map_with_bounded_workers,
    retry_policy_from_config,
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
    RAW_OPTIONS_COLUMNS,
    fetch_options_chain,
)
from golden_vector.ingestion.fetch_risk_free_rate import fetch_risk_free_rate
from golden_vector.ingestion.persist_options import (
    OptionsSnapshotRecord,
    build_options_snapshot_frame,
    persist_options_feature_snapshot,
    persist_options_snapshot_frame,
    safe_options_file_name,
    write_latest_options_manifest,
)
from golden_vector.ingestion.options_carry_forward import (
    PreviousOptionsTickerBundle,
    load_previous_options_ticker_bundles,
)
from golden_vector.ingestion.yahoo_client import YahooClient

LOGGER = logging.getLogger(__name__)
FULL_CHAIN_EXPIRY_FETCH_MODE = "all"


@dataclass(frozen=True)
class OptionsPhaseResult:
    status: str
    summary: dict[str, Any]
    manifest_path: Path | None


@dataclass(frozen=True)
class _OptionFetchTarget:
    ticker: str
    yahoo_symbol: str
    vehicle_type: str


@dataclass(frozen=True)
class _OptionTargetFetch:
    target: _OptionFetchTarget
    result: OptionsChainResult
    collection_event: dict[str, Any]


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

    client = yahoo_client or YahooClient(
        retry_policy=retry_policy_from_config(app_config.market_data)
    )
    targets = _option_fetch_targets(app_config)
    universe_target_count = sum(
        1 for target in targets if target.vehicle_type == "single_stock"
    )
    benchmark_target_count = sum(
        1 for target in targets if target.vehicle_type == "benchmark_etf"
    )
    risk_free_rate, risk_free_message = _fetch_risk_free_rate(
        client=client,
        as_of_date=as_of_date,
    )
    benchmark_paths, benchmark_statuses, benchmark_histories = _fetch_and_persist_benchmarks(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        client=client,
    )

    snapshot_records: list[OptionsSnapshotRecord] = []
    feature_rows: list[dict[str, Any]] = []
    collection_events: list[dict[str, Any]] = []
    status_counts = {
        OPTIONS_STATUS_SUCCESS: 0,
        OPTIONS_STATUS_EMPTY: 0,
        OPTIONS_STATUS_ERROR: 0,
    }
    previous_bundles = load_previous_options_ticker_bundles(paths)

    fetch_results = _fetch_option_targets(
        targets=targets,
        client=client,
        app_config=app_config,
        as_of_date=as_of_date,
        max_workers=app_config.market_data.yahoo_max_workers,
    )

    for fetched in fetch_results:
        target = fetched.target
        result = fetched.result
        collection_events.append(fetched.collection_event)
        if result.status == OPTIONS_STATUS_ERROR:
            LOGGER.warning(
                "Options fetch failed for %s (%s): %s",
                target.ticker,
                target.yahoo_symbol,
                result.message,
            )
            status_counts[OPTIONS_STATUS_ERROR] += 1
            snapshot_records.append(
                _record_failed_ticker_attempt(
                    paths=paths,
                    run_context=run_context,
                    ticker=target.ticker,
                    previous=previous_bundles.get(target.ticker),
                    attempt_message=result.message,
                )
            )
            continue
        # Persist the raw snapshot first. If snapshot persistence itself fails there
        # is genuinely nothing to record, so emit an error event and move on.
        try:
            snapshot_frame = build_options_snapshot_frame(
                frame=result.frame,
                ticker=target.ticker,
                as_of_date=as_of_date,
                run_id=run_context.run_id,
                options_available=result.options_available,
                message=result.message,
                captured_at_utc=run_context.started_at_utc,
                attempt_status=result.status,
                attempt_message=result.message,
            )
            record = persist_options_snapshot_frame(
                paths=paths,
                run_context=run_context,
                ticker=target.ticker,
                snapshot=snapshot_frame,
                options_available=result.options_available,
                message=result.message,
                source_refresh_run_id=run_context.run_id,
                source_as_of_date=as_of_date.isoformat(),
                captured_at_utc=run_context.started_at_utc,
                attempt_status=result.status,
                attempt_message=result.message,
            )
            # Carry the fetch's numeric expiration evidence into the manifest so
            # availability readers never have to parse the message prose.
            record = replace(
                record,
                expiration_count_available=_expiration_count_available(result),
            )
        except Exception as exc:  # noqa: BLE001 - per-ticker best effort by design.
            status_counts[OPTIONS_STATUS_ERROR] = (
                status_counts.get(OPTIONS_STATUS_ERROR, 0) + 1
            )
            collection_events.append(
                {
                    "ticker": target.ticker,
                    "source_symbol": target.yahoo_symbol,
                    "vehicle_type": target.vehicle_type,
                    "status": OPTIONS_STATUS_ERROR,
                    "message": str(exc),
                }
            )
            LOGGER.warning("Options snapshot persistence failed for %s: %s", target.ticker, exc)
            snapshot_records.append(
                _record_failed_ticker_attempt(
                    paths=paths,
                    run_context=run_context,
                    ticker=target.ticker,
                    previous=previous_bundles.get(target.ticker),
                    attempt_message=f"Snapshot persistence failed: {exc}",
                )
            )
            continue

        # Feature computation is a separate stage. If it fails, the raw snapshot is
        # already persisted, so keep the ticker in the manifest with an explicit
        # ERROR marker (H3) -- never let a per-ticker feature failure make the ticker
        # silently vanish from the run. The feature loader skips ERROR records.
        try:
            feature_row = _compute_feature_row(
                snapshot_record=record,
                snapshot_frame=snapshot_frame,
                options_result=result,
                paths=paths,
                ticker=target.ticker,
                as_of_date=as_of_date,
                risk_free_rate=risk_free_rate,
                run_id=run_context.run_id,
                app_config=app_config,
                price_history=_price_history_for_target(
                    target=target,
                    normalized_equity_histories=normalized_equity_histories,
                    benchmark_histories=benchmark_histories,
                ),
            )
            feature_row["option_vehicle_type"] = target.vehicle_type
            feature_row["options_source_symbol"] = target.yahoo_symbol
            feature_row.update(
                {
                    "source_refresh_run_id": run_context.run_id,
                    "source_as_of_date": as_of_date.isoformat(),
                    "captured_at_utc": run_context.started_at_utc,
                    "carried_forward": False,
                    "attempt_status": result.status,
                    "attempt_message": result.message,
                }
            )
        except Exception as exc:  # noqa: BLE001 - per-ticker best effort by design.
            status_counts[OPTIONS_STATUS_ERROR] = (
                status_counts.get(OPTIONS_STATUS_ERROR, 0) + 1
            )
            collection_events.append(
                {
                    "ticker": target.ticker,
                    "source_symbol": target.yahoo_symbol,
                    "vehicle_type": target.vehicle_type,
                    "status": OPTIONS_STATUS_ERROR,
                    "message": str(exc),
                }
            )
            LOGGER.warning("Options feature computation failed for %s: %s", target.ticker, exc)
            snapshot_records.append(
                _record_failed_ticker_attempt(
                    paths=paths,
                    run_context=run_context,
                    ticker=target.ticker,
                    previous=previous_bundles.get(target.ticker),
                    attempt_message=f"Feature computation failed: {exc}",
                )
            )
            continue

        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        snapshot_records.append(record)
        feature_rows.append(feature_row)

    option_collection_stats = _summarize_option_collection_events(collection_events)
    vendor_outage_status = _options_vendor_outage_status(
        target_count=len(targets),
        error_count=status_counts.get(OPTIONS_STATUS_ERROR, 0),
    )
    feature_paths: list[Path] = []
    feature_row_count = 0
    # Even when every current vendor request fails, publish a truthful options
    # generation instead of failing the entire multi-dataset refresh. Verified
    # prior ticker bundles remain available; tickers without one are explicit
    # unavailable records. The effective cohort is still re-ranked because a
    # corrupt/missing prior bundle can make it smaller than the old generation.
    feature_frame = _effective_feature_frame(
        current_features=pd.DataFrame(feature_rows),
        snapshot_records=snapshot_records,
        previous_bundles=previous_bundles,
    )
    feature_frame, snapshot_records, feature_persist_failures = (
        _persist_current_feature_snapshots(
            paths=paths,
            run_context=run_context,
            feature_frame=feature_frame,
            snapshot_records=snapshot_records,
            previous_bundles=previous_bundles,
            iv_column=(
                f"atm_iv_{app_config.hedge_readiness.option_signal_horizon_days}d"
            ),
        )
    )
    for ticker, message in feature_persist_failures.items():
        attempted = next(
            (
                row
                for row in feature_rows
                if str(row.get("ticker") or "").strip().upper() == ticker
            ),
            {},
        )
        # A ticker already carried because its fetch/feature attempt failed has
        # already contributed one ERROR. Only a newly failed current row changes
        # the attempt counts here.
        if not attempted:
            continue
        status_counts[OPTIONS_STATUS_ERROR] += 1
        attempted_status = str(attempted.get("attempt_status") or "").upper()
        if attempted_status in status_counts and status_counts[attempted_status] > 0:
            status_counts[attempted_status] -= 1
        collection_events.append(
            {
                "ticker": ticker,
                "status": OPTIONS_STATUS_ERROR,
                "message": message,
            }
        )
    feature_row_count = len(feature_frame.index)
    history_feature_frame = feature_frame[
        ~feature_frame.get(
            "carried_forward",
            pd.Series(False, index=feature_frame.index),
        ).map(bool_or_false)
    ]
    feature_paths = _append_feature_rows(
        paths=paths,
        run_context=run_context,
        feature_rows=history_feature_frame.to_dict(orient="records"),
    )
    option_collection_stats = _summarize_option_collection_events(collection_events)
    vendor_outage_status = _options_vendor_outage_status(
        target_count=len(targets),
        error_count=status_counts.get(OPTIONS_STATUS_ERROR, 0),
    )
    status = _phase_status(
        vendor_outage_status=vendor_outage_status,
        error_count=status_counts.get(OPTIONS_STATUS_ERROR, 0),
        expiration_error_count=int(
            option_collection_stats.get("expiration_error_count") or 0
        ),
        risk_free_message=risk_free_message,
        benchmark_statuses=benchmark_statuses,
    )
    summary: dict[str, Any] = {
        "options_phase_status": status,
        "options_phase_requested": True,
        "options_as_of_date": as_of_date.isoformat(),
        "options_ticker_count": len(targets),
        "options_universe_ticker_count": universe_target_count,
        "options_benchmark_ticker_count": benchmark_target_count,
        "options_success_count": status_counts.get(OPTIONS_STATUS_SUCCESS, 0),
        "options_empty_count": status_counts.get(OPTIONS_STATUS_EMPTY, 0),
        "options_error_count": status_counts.get(OPTIONS_STATUS_ERROR, 0),
        "options_carried_forward_count": sum(
            1 for record in snapshot_records if record.carried_forward
        ),
        "options_unavailable_count": sum(
            1 for record in snapshot_records if record.snapshot_path is None
        ),
        "options_vendor_outage_status": vendor_outage_status,
        "options_feature_row_count": feature_row_count,
        "options_feature_file_count": len(feature_paths),
        "risk_free_rate": risk_free_rate,
        "risk_free_rate_message": risk_free_message,
        "benchmark_count": len(benchmark_statuses),
        "benchmark_pass_count": sum(1 for item in benchmark_statuses if item.status == "PASS"),
        "benchmark_fail_count": sum(1 for item in benchmark_statuses if item.status == "FAIL"),
        "benchmark_snapshot_count": len(benchmark_paths),
        "options_collection_stats": option_collection_stats,
    }
    manifest_path = None
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


def _option_fetch_targets(app_config: AppConfig) -> list[_OptionFetchTarget]:
    targets: list[_OptionFetchTarget] = []
    seen: set[str] = set()
    for universe_ticker in app_config.universe.tickers:
        if not universe_ticker.active:
            continue
        ticker = universe_ticker.ticker.upper()
        targets.append(
            _OptionFetchTarget(
                ticker=ticker,
                yahoo_symbol=ticker,
                vehicle_type="single_stock",
            )
        )
        seen.add(ticker)

    benchmark_by_ticker = {
        benchmark.ticker.upper(): benchmark
        for benchmark in app_config.benchmarks.benchmarks
        if benchmark.active
    }
    for ticker in app_config.hedge_readiness.benchmark_tickers:
        benchmark = benchmark_by_ticker.get(ticker.upper())
        if benchmark is None or benchmark.ticker.upper() in seen:
            continue
        targets.append(
            _OptionFetchTarget(
                ticker=benchmark.ticker.upper(),
                yahoo_symbol=benchmark.yahoo_symbol.upper(),
                vehicle_type="benchmark_etf",
            )
        )
        seen.add(benchmark.ticker.upper())
    return targets


def _fetch_option_targets(
    *,
    targets: list[_OptionFetchTarget],
    client: YahooClient,
    app_config: AppConfig,
    as_of_date: date,
    max_workers: int,
) -> list[_OptionTargetFetch]:
    return map_with_bounded_workers(
        targets,
        max_workers=max_workers,
        func=lambda target: _fetch_option_target(
            target=target,
            client=client,
            app_config=app_config,
            as_of_date=as_of_date,
        ),
    )


def _fetch_option_target(
    *,
    target: _OptionFetchTarget,
    client: YahooClient,
    app_config: AppConfig,
    as_of_date: date,
) -> _OptionTargetFetch:
    started_at = perf_counter()
    try:
        result = fetch_options_chain(
            ticker=target.yahoo_symbol,
            as_of_date=as_of_date,
            yahoo_client=client,
            expiry_fetch_mode=FULL_CHAIN_EXPIRY_FETCH_MODE,
            target_dte_bands=None,
        )
    except Exception as exc:  # noqa: BLE001 - one ticker must not abort the pool.
        result = OptionsChainResult(
            ticker=target.yahoo_symbol,
            as_of_date=as_of_date,
            status=OPTIONS_STATUS_ERROR,
            frame=pd.DataFrame(columns=RAW_OPTIONS_COLUMNS),
            message=str(exc),
            collection_stats={
                "ticker": target.yahoo_symbol,
                "status": OPTIONS_STATUS_ERROR,
                "duration_seconds": round(perf_counter() - started_at, 3),
                "expiry_fetch_mode": FULL_CHAIN_EXPIRY_FETCH_MODE,
                "expiration_count_available": 0,
                "expiration_count_selected": 0,
                "expiration_error_count": 0,
                "message": str(exc),
            },
        )
    return _OptionTargetFetch(
        target=target,
        result=result,
        collection_event={
            **result.collection_stats,
            "ticker": target.ticker,
            "source_symbol": target.yahoo_symbol,
            "vehicle_type": target.vehicle_type,
            "message": result.message,
        },
    )


def _expiration_count_available(result: OptionsChainResult) -> int | None:
    """Expirations the vendor enumeration returned, or None when unrecorded."""

    stats = getattr(result, "collection_stats", None) or {}
    value = stats.get("expiration_count_available")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_failed_ticker_attempt(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    ticker: str,
    previous: PreviousOptionsTickerBundle | None,
    attempt_message: str | None,
) -> OptionsSnapshotRecord:
    """Publish one coherent prior ticker bundle, or an honest unavailable row."""

    if previous is None:
        return OptionsSnapshotRecord(
            ticker=ticker,
            options_available=False,
            row_count=0,
            snapshot_path=None,
            sha256=None,
            message=None,
            feature_status=OPTIONS_STATUS_ERROR,
            source_refresh_run_id=None,
            source_as_of_date=None,
            captured_at_utc=None,
            carried_forward=False,
            attempt_status=OPTIONS_STATUS_ERROR,
            attempt_message=attempt_message,
        )

    entry = previous.manifest_entry
    snapshot = previous.snapshot.copy()
    snapshot["source_refresh_run_id"] = previous.source_refresh_run_id
    snapshot["source_as_of_date"] = previous.source_as_of_date
    snapshot["captured_at_utc"] = previous.captured_at_utc
    snapshot["carried_forward"] = True
    snapshot["attempt_status"] = OPTIONS_STATUS_ERROR
    snapshot["attempt_message"] = attempt_message
    try:
        record = persist_options_snapshot_frame(
            paths=paths,
            run_context=run_context,
            ticker=ticker,
            snapshot=snapshot,
            options_available=bool(entry.get("options_available")),
            message=str(entry.get("message")) if entry.get("message") is not None else None,
            source_refresh_run_id=previous.source_refresh_run_id,
            source_as_of_date=previous.source_as_of_date,
            captured_at_utc=previous.captured_at_utc,
            carried_forward=True,
            attempt_status=OPTIONS_STATUS_ERROR,
            attempt_message=attempt_message,
        )
        feature_path, feature_sha256 = persist_options_feature_snapshot(
            paths=paths,
            run_context=run_context,
            ticker=ticker,
            feature=previous.feature,
        )
    except Exception as exc:  # noqa: BLE001 - failed carry remains honestly unavailable.
        LOGGER.warning("Prior options snapshot carry failed for %s: %s", ticker, exc)
        return OptionsSnapshotRecord(
            ticker=ticker,
            options_available=False,
            row_count=0,
            snapshot_path=None,
            sha256=None,
            message=None,
            feature_status=OPTIONS_STATUS_ERROR,
            attempt_status=OPTIONS_STATUS_ERROR,
            attempt_message=f"{attempt_message or 'Ticker attempt failed'}; carry failed: {exc}",
        )
    return replace(
        record,
        feature_path=feature_path,
        feature_sha256=feature_sha256,
        feature_status=str(entry.get("feature_status") or "OK").strip().upper(),
        expiration_count_available=_optional_int(entry.get("expiration_count_available")),
    )


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _price_history_for_target(
    *,
    target: _OptionFetchTarget,
    normalized_equity_histories: dict[str, pd.DataFrame],
    benchmark_histories: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    if target.vehicle_type == "benchmark_etf":
        return benchmark_histories.get(target.ticker, pd.DataFrame())
    return normalized_equity_histories.get(target.ticker, pd.DataFrame())


def _compute_feature_row(
    *,
    snapshot_record: OptionsSnapshotRecord,
    snapshot_frame: pd.DataFrame | None = None,
    options_result: OptionsChainResult,
    paths: ProjectPaths,
    ticker: str,
    as_of_date: date,
    risk_free_rate: float | None,
    run_id: str,
    app_config: AppConfig,
    price_history: pd.DataFrame,
) -> dict[str, Any]:
    snapshot = (
        snapshot_frame
        if snapshot_frame is not None
        else pd.read_parquet(snapshot_record.snapshot_path)
    )
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
        option_dte_bands={
            int(horizon): (int(band[0]), int(band[1]))
            for horizon, band in app_config.hedge_readiness.option_dte_bands.items()
        },
        optionability_core_horizons=tuple(
            app_config.hedge_readiness.optionability_core_horizons
        ),
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


def _persist_current_feature_snapshots(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    feature_frame: pd.DataFrame,
    snapshot_records: list[OptionsSnapshotRecord],
    previous_bundles: dict[str, PreviousOptionsTickerBundle],
    iv_column: str,
) -> tuple[pd.DataFrame, list[OptionsSnapshotRecord], dict[str, str]]:
    """Persist one consistently ranked effective feature cohort.

    The cohort includes both fresh and carried rows.  A cross-sectional
    percentile only has meaning relative to the generation displayed beside
    it, so a carried row keeps its verified source features/provenance but is
    re-ranked against the current effective cohort.  Carried rows are still
    excluded from mutable history by the caller.
    """

    remaining = feature_frame.copy()
    records = list(snapshot_records)
    failures: dict[str, str] = {}
    while not remaining.empty:
        remaining = remaining.copy()
        remaining["iv_percentile_cross_sectional"] = rank_options_iv_cross_section(
            remaining,
            iv_column=iv_column,
        )
        failed_this_pass: set[str] = set()
        for _, row in remaining.iterrows():
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker:
                continue
            try:
                feature_path, feature_sha256 = persist_options_feature_snapshot(
                    paths=paths,
                    run_context=run_context,
                    ticker=ticker,
                    feature=pd.DataFrame([row.to_dict()]),
                )
            except Exception as exc:  # noqa: BLE001 - ticker-level recovery boundary.
                message = f"Feature snapshot persistence failed: {exc}"
                failures[ticker] = message
                failed_this_pass.add(ticker)
                current = next((item for item in records if item.ticker == ticker), None)
                if current is None:
                    raise ValueError(
                        f"Options snapshot record missing for feature ticker {ticker}."
                    )
                replacement = (
                    _unavailable_ticker_record(ticker=ticker, attempt_message=message)
                    if current.carried_forward
                    else _record_failed_ticker_attempt(
                        paths=paths,
                        run_context=run_context,
                        ticker=ticker,
                        previous=previous_bundles.get(ticker),
                        attempt_message=message,
                    )
                )
                records = _replace_snapshot_record(
                    records,
                    replacement,
                )
                LOGGER.warning("Options feature snapshot persistence failed for %s: %s", ticker, exc)
                continue
            current = next((item for item in records if item.ticker == ticker), None)
            if current is None:
                raise ValueError(f"Options snapshot record missing for feature ticker {ticker}.")
            records = _replace_snapshot_record(
                records,
                replace(
                    current,
                    feature_path=feature_path,
                    feature_sha256=feature_sha256,
                ),
            )
        if not failed_this_pass:
            return remaining.reset_index(drop=True), records, failures
        remaining = _effective_feature_frame(
            current_features=remaining[
                ~remaining["ticker"].astype(str).str.upper().isin(failed_this_pass)
            ].reset_index(drop=True),
            snapshot_records=records,
            previous_bundles=previous_bundles,
        )
    return remaining, records, failures


def _effective_feature_frame(
    *,
    current_features: pd.DataFrame,
    snapshot_records: list[OptionsSnapshotRecord],
    previous_bundles: dict[str, PreviousOptionsTickerBundle],
) -> pd.DataFrame:
    """Combine fresh rows with verified carried rows for this generation."""

    rows_by_ticker: dict[str, dict[str, Any]] = {}
    if not current_features.empty and "ticker" in current_features.columns:
        for row in current_features.to_dict(orient="records"):
            ticker = str(row.get("ticker") or "").strip().upper()
            if ticker:
                rows_by_ticker[ticker] = row

    for record in snapshot_records:
        ticker = record.ticker.strip().upper()
        if record.snapshot_path is None or record.feature_status == OPTIONS_STATUS_ERROR:
            rows_by_ticker.pop(ticker, None)
            continue
        if not record.carried_forward:
            continue
        previous = previous_bundles.get(ticker)
        if previous is None:
            rows_by_ticker.pop(ticker, None)
            continue
        row = dict(previous.feature_row)
        row.update(
            {
                "ticker": ticker,
                "source_refresh_run_id": record.source_refresh_run_id,
                "source_as_of_date": record.source_as_of_date,
                "captured_at_utc": record.captured_at_utc,
                "carried_forward": True,
                "attempt_status": record.attempt_status,
                "attempt_message": record.attempt_message,
            }
        )
        rows_by_ticker[ticker] = row

    if not rows_by_ticker:
        return pd.DataFrame()
    return pd.DataFrame(
        [rows_by_ticker[ticker] for ticker in sorted(rows_by_ticker)]
    ).reset_index(drop=True)


def _unavailable_ticker_record(
    *,
    ticker: str,
    attempt_message: str,
) -> OptionsSnapshotRecord:
    """Return an honest unavailable row after an effective bundle cannot persist."""

    return OptionsSnapshotRecord(
        ticker=ticker,
        options_available=False,
        row_count=0,
        snapshot_path=None,
        sha256=None,
        message=None,
        feature_status=OPTIONS_STATUS_ERROR,
        source_refresh_run_id=None,
        source_as_of_date=None,
        captured_at_utc=None,
        carried_forward=False,
        attempt_status=OPTIONS_STATUS_ERROR,
        attempt_message=attempt_message,
    )


def _replace_snapshot_record(
    records: list[OptionsSnapshotRecord],
    replacement: OptionsSnapshotRecord,
) -> list[OptionsSnapshotRecord]:
    result = [record for record in records if record.ticker != replacement.ticker]
    result.append(replacement)
    return result


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
        write_parquet_atomic(frame, path, index=False)
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
) -> tuple[list[Path], list[BenchmarkFetchStatus], dict[str, pd.DataFrame]]:
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
        write_parquet_atomic(frame, run_path, index=False)
        write_parquet_atomic(frame, latest_path, index=False)
        run_context.record_artifact(run_path)
        run_context.record_artifact(latest_path)
        written_paths.append(run_path)
    return written_paths, statuses, histories


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
    vendor_outage_status: str,
    error_count: int,
    expiration_error_count: int,
    risk_free_message: str | None,
    benchmark_statuses: list[BenchmarkFetchStatus],
) -> str:
    # Options are one dataset inside a broader refresh. A total provider outage
    # is operationally important, but it must not discard equities,
    # fundamentals, or other data that refreshed successfully. Per-ticker
    # records make the options result honestly carried or unavailable.
    if vendor_outage_status == "FULL_OUTAGE":
        return "WARN"
    if (
        error_count
        or expiration_error_count
        or risk_free_message
        or any(item.status == "FAIL" for item in benchmark_statuses)
    ):
        return "WARN"
    return "PASS"


def _options_vendor_outage_status(*, target_count: int, error_count: int) -> str:
    if target_count > 0 and error_count == target_count:
        return "FULL_OUTAGE"
    if error_count:
        return "PARTIAL_OUTAGE"
    return "OK"


def _summarize_option_collection_events(
    events: list[dict[str, Any]],
    *,
    max_items: int = 10,
) -> dict[str, Any]:
    if not events:
        return {
            "total_count": 0,
            "success_count": 0,
            "empty_count": 0,
            "error_count": 0,
            "expiration_count_selected": 0,
            "expiration_error_count": 0,
            "failed": [],
            "slowest": [],
            "expiry_fetch_modes": {},
        }

    status_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    for event in events:
        status = str(event.get("status") or "UNKNOWN")
        mode = str(event.get("expiry_fetch_mode") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    sorted_by_duration = sorted(
        events,
        key=lambda item: optional_float(item.get("duration_seconds")) or 0.0,
        reverse=True,
    )
    failed = [
        _event_summary(event)
        for event in events
        if str(event.get("status") or "").upper() == OPTIONS_STATUS_ERROR
    ][:max_items]
    return {
        "total_count": len(events),
        "success_count": status_counts.get(OPTIONS_STATUS_SUCCESS, 0),
        "empty_count": status_counts.get(OPTIONS_STATUS_EMPTY, 0),
        "error_count": status_counts.get(OPTIONS_STATUS_ERROR, 0),
        "expiration_count_available": sum(
            int_or_zero(event.get("expiration_count_available"))
            for event in events
        ),
        "expiration_count_selected": sum(
            int_or_zero(event.get("expiration_count_selected"))
            for event in events
        ),
        "expiration_error_count": sum(
            int_or_zero(event.get("expiration_error_count"))
            for event in events
        ),
        "failed": failed,
        "slowest": [
            _event_summary(event)
            for event in sorted_by_duration[:max_items]
        ],
        "expiry_fetch_modes": mode_counts,
    }


def _event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": str(event.get("ticker") or ""),
        "source_symbol": str(event.get("source_symbol") or ""),
        "vehicle_type": str(event.get("vehicle_type") or ""),
        "status": str(event.get("status") or ""),
        "duration_seconds": optional_float(event.get("duration_seconds")) or 0.0,
        "expiration_count_selected": int_or_zero(event.get("expiration_count_selected")),
        "expiration_error_count": int_or_zero(event.get("expiration_error_count")),
        "message": str(event.get("message") or "") or None,
    }
