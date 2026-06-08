"""Build persisted portfolio artifacts from manual lots and current snapshots."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    read_current_model_parquet,
    resolve_current_foundation_manifest_path,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import optional_sha256_file
from golden_vector.common.frames import latest_records_by_key
from golden_vector.common.numeric import optional_float, sum_optional_floats
from golden_vector.common.parquet import read_optional_parquet
from golden_vector.contracts.config_models import AppConfig
from golden_vector.portfolio.analytics import (
    ANALYTICS_POSITION_COLUMNS,
    apply_position_weights,
    enrich_portfolio_analytics,
)
from golden_vector.portfolio.artifacts import (
    write_portfolio_artifact_pair,
    write_portfolio_csv_pair,
)
from golden_vector.portfolio.benchmark_betas import build_benchmark_betas_frame
from golden_vector.portfolio.m4_artifacts import build_m4_portfolio_artifacts
from golden_vector.portfolio.manual_store import load_lots
from golden_vector.portfolio.models import (
    LineValuation,
    PortfolioBuildResult,
    PortfolioLot,
    PORTFOLIO_SCHEMA_VERSION,
    TickerInfo,
)
from golden_vector.portfolio.reconciliation import build_manual_reconciliation_frame
from golden_vector.portfolio.valuation import ValuationInput, value_major_unit_price


LINE_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "source_export_sha256",
    "portfolio_source_version",
    "lot_id",
    "ticker",
    "company",
    "shares",
    "buy_price",
    "buy_currency",
    "buy_date",
    "cost_local",
    "current_price_local",
    "current_price_usd",
    "fx_rate_to_usd",
    "snapshot_date",
    "value_local",
    "value_usd",
    "cost_usd_at_current_fx",
    "pnl_local",
    "pnl_fraction_local",
    "pnl_usd_at_current_fx",
    "line_status",
    "line_status_reason",
    "price_scale_factor",
    "minor_unit_adjusted",
    "created_at",
    "updated_at",
    "note",
]

POSITION_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "source_export_sha256",
    "portfolio_source_version",
    "ticker",
    "company",
    "currency",
    "total_shares",
    "avg_cost_local",
    "cost_local",
    "current_price_local",
    "current_price_usd",
    "fx_rate_to_usd",
    "snapshot_date",
    "value_local",
    "value_usd",
    "cost_usd_at_current_fx",
    "pnl_local",
    "pnl_fraction_local",
    "pnl_usd_at_current_fx",
    # M1 legacy equity-weight field. The UI consumes nav_weight_fraction from
    # M3 so broker cash can enter the denominator when import lands.
    "position_weight_fraction",
    *ANALYTICS_POSITION_COLUMNS,
    "position_status",
    "lot_count",
]

SUMMARY_COLUMNS = [
    "schema_version",
    "source_run_id",
    "snapshot_refresh_run_id",
    "source_export_sha256",
    "portfolio_source_version",
    "portfolio_status",
    "lot_count",
    "position_count",
    "total_value_usd",
    "total_cost_usd_at_current_fx",
    "total_pnl_usd_at_current_fx",
    "equity_value_usd",
    "cash_value_usd",
    "nav_value_usd",
    "cash_weight_fraction",
    "tool_a_coverage_value_usd",
    "tool_a_coverage_fraction",
    "modeled_gold_down_10_loss_usd",
    "largest_position_weight_fraction",
    "top3_position_weight_fraction",
    "effective_exposure_json",
    "data_issues_json",
    "benchmark_beta_status",
    "reconciliation_status",
    "resilience_coverage_fraction",
    "currency_split_json",
    "as_of_date",
]


def build_ticker_info(app_config: AppConfig) -> dict[str, TickerInfo]:
    return {
        ticker.ticker: TickerInfo(
            ticker=ticker.ticker,
            currency=ticker.currency,
            company=ticker.company,
            active=ticker.active,
        )
        for ticker in app_config.universe.tickers
    }


def build_portfolio_artifacts(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    parent_refresh_id: str | None = None,
    source_run_id: str | None = None,
    publish_model_state: bool = True,
    config_hash: str | None = None,
    use_model_state_artifacts: bool = True,
) -> PortfolioBuildResult:
    source_run_id = source_run_id or _new_portfolio_run_id()
    foundation_manifest_path = resolve_current_foundation_manifest_path(paths)
    lots = load_lots(paths)
    requested_tickers = sorted({lot.ticker for lot in lots})
    foundation = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=True,
        include_equity_histories=bool(requested_tickers),
        include_market_snapshots=True,
        requested_tickers=requested_tickers,
        manifest_path=foundation_manifest_path,
    )
    ticker_info = build_ticker_info(app_config)
    snapshots_by_ticker = _snapshot_records_by_ticker(foundation.normalized_market_snapshots)
    source_hash = optional_sha256_file(paths.manual_portfolio_lots_path)
    portfolio_source_version = source_hash or "empty"
    valuations = [
        _value_lot(
            lot,
            ticker_info=ticker_info,
            snapshot=snapshots_by_ticker.get(lot.ticker),
        )
        for lot in lots
    ]

    lines = _lines_frame(
        valuations,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=foundation.refresh_run_id,
        source_hash=source_hash,
        portfolio_source_version=portfolio_source_version,
    )
    positions = _positions_frame(
        valuations,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=foundation.refresh_run_id,
        source_hash=source_hash,
        portfolio_source_version=portfolio_source_version,
    )
    summary = _summary_frame(
        valuations,
        positions,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=foundation.refresh_run_id,
        source_hash=source_hash,
        portfolio_source_version=portfolio_source_version,
    )
    benchmark_betas = build_benchmark_betas_frame(
        paths=paths,
        app_config=app_config,
        gold_history=foundation.gold_history,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=foundation.refresh_run_id,
    )
    reconciliation = build_manual_reconciliation_frame(
        source_run_id=source_run_id,
        snapshot_refresh_run_id=foundation.refresh_run_id,
        source_hash=source_hash,
        portfolio_source_version=portfolio_source_version,
        gv_price_date=str(summary.iloc[0]["as_of_date"]) if not summary.empty else None,
    )
    positions, summary = enrich_portfolio_analytics(
        positions=positions,
        summary=summary,
        tool_a=_read_current_or_latest_artifact(
            paths,
            artifact_name="tool_a",
            fallback_path=paths.latest_tool_a_snapshot_parquet_path,
            use_model_state=use_model_state_artifacts,
        ),
        tool_d=_read_current_or_latest_artifact(
            paths,
            artifact_name="tool_d_spot",
            fallback_path=paths.latest_tool_d_spot_snapshot_parquet_path,
            use_model_state=use_model_state_artifacts,
        ),
        benchmark_betas=benchmark_betas,
        reconciliation=reconciliation,
    )
    positions = apply_position_weights(positions, summary)
    positions = _with_metadata(
        _ensure_columns(positions, POSITION_COLUMNS),
        source_run_id,
        foundation.refresh_run_id,
    )
    summary = _with_metadata(
        _ensure_columns(summary, SUMMARY_COLUMNS),
        source_run_id,
        foundation.refresh_run_id,
    )
    (
        hedge_sizing,
        correlations,
        value_history,
        reconciliation_export,
    ) = build_m4_portfolio_artifacts(
        positions=positions,
        lines=lines,
        summary=summary,
        benchmark_betas=benchmark_betas,
        normalized_equity_histories=foundation.normalized_equity_histories,
        source_run_id=source_run_id,
        snapshot_refresh_run_id=foundation.refresh_run_id,
    )

    write_portfolio_artifact_pair(
        paths=paths,
        frame=lines,
        prefix="portfolio_lines",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=positions,
        prefix="portfolio_positions",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=summary,
        prefix="portfolio_summary",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=benchmark_betas,
        prefix="benchmark_betas",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=reconciliation,
        prefix="portfolio_reconciliation",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=hedge_sizing,
        prefix="portfolio_hedge_sizing",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=correlations,
        prefix="portfolio_correlations",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=value_history,
        prefix="portfolio_value_history",
        source_run_id=source_run_id,
    )
    write_portfolio_artifact_pair(
        paths=paths,
        frame=reconciliation_export,
        prefix="portfolio_reconciliation_export",
        source_run_id=source_run_id,
    )
    write_portfolio_csv_pair(
        paths=paths,
        frame=reconciliation_export,
        prefix="portfolio_reconciliation_export",
        source_run_id=source_run_id,
    )
    if publish_model_state:
        # A manual lot edit intentionally republishes the global current-state
        # manifest after rebuilding portfolio artifacts. The manifest builder
        # reads every artifact from disk, so this keeps portfolio pointers fresh
        # without recalculating Tool A/B/C/D or touching live market data.
        manifest = load_current_model_state_manifest(paths) or {}
        manifest_config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        resolved_config_hash = config_hash or str(manifest_config.get("config_hash") or "")
        write_current_model_state_manifest(
            paths=paths,
            config_hash=resolved_config_hash or None,
            parent_refresh_id=parent_refresh_id or str(manifest.get("parent_refresh_id") or "") or None,
        )
    summary_status = str(summary.iloc[0]["portfolio_status"]) if not summary.empty else "EMPTY"
    return PortfolioBuildResult(
        source_run_id=source_run_id,
        lines_count=len(lines.index),
        positions_count=len(positions.index),
        summary_status=summary_status,
    )


def build_portfolio_artifacts_from_current_config(
    paths: ProjectPaths,
    *,
    parent_refresh_id: str | None = None,
    publish_model_state: bool = True,
) -> PortfolioBuildResult:
    loaded_config = load_app_config(paths)
    return build_portfolio_artifacts(
        paths=paths,
        app_config=loaded_config.app,
        parent_refresh_id=parent_refresh_id,
        publish_model_state=publish_model_state,
        config_hash=loaded_config.config_hash,
    )


def _read_current_or_latest_artifact(
    paths: ProjectPaths,
    *,
    artifact_name: str,
    fallback_path: Path,
    use_model_state: bool,
) -> pd.DataFrame:
    if use_model_state:
        return read_current_model_parquet(
            paths,
            artifact_name,
            fallback_path=fallback_path,
        )
    return read_optional_parquet(fallback_path)


def _value_lot(
    lot: PortfolioLot,
    *,
    ticker_info: dict[str, TickerInfo],
    snapshot: dict[str, object] | None,
) -> LineValuation:
    info = ticker_info.get(lot.ticker)
    company = info.company if info is not None else None
    if snapshot is None:
        return _missing_value(lot, company=company, reason="No current snapshot price.")
    price_local = optional_float(snapshot.get("share_price_local"))
    fx_rate = optional_float(snapshot.get("fx_rate_to_usd"))
    if price_local is None or price_local <= 0:
        return _missing_value(lot, company=company, reason="Current price is missing.")
    if fx_rate is None or fx_rate <= 0:
        return _missing_value(lot, company=company, reason="Current FX rate is missing.")
    snapshot_status = str(snapshot.get("normalization_status") or "OK")
    valued = value_major_unit_price(
        ValuationInput(
            quantity=lot.shares,
            price_local=price_local,
            price_currency=lot.buy_currency,
            fx_rate_to_usd=fx_rate,
        )
    )
    snapshot_scale_factor = optional_float(snapshot.get("price_scale_factor"))
    snapshot_minor_adjusted = bool(snapshot.get("minor_unit_adjusted") or False)
    cost_usd = lot.cost_local * fx_rate
    pnl_local = valued.market_value_local - lot.cost_local
    pnl_pct = pnl_local / lot.cost_local if lot.cost_local > 0 else None
    pnl_usd = valued.market_value_usd - cost_usd
    status = "OK" if snapshot_status == "OK" else snapshot_status
    return LineValuation(
        lot=lot,
        company=company,
        current_price_local=valued.price_local_major,
        current_price_usd=valued.price_local_major * fx_rate,
        fx_rate_to_usd=fx_rate,
        snapshot_date=_optional_string(snapshot.get("snapshot_date")),
        value_local=valued.market_value_local,
        value_usd=valued.market_value_usd,
        cost_local=lot.cost_local,
        cost_usd_at_current_fx=cost_usd,
        pnl_local=pnl_local,
        pnl_fraction_local=pnl_pct,
        pnl_usd_at_current_fx=pnl_usd,
        status=status,
        status_reason=None if status == "OK" else f"Snapshot status is {snapshot_status}.",
        price_scale_factor=snapshot_scale_factor or valued.price_scale_factor,
        minor_unit_adjusted=snapshot_minor_adjusted or valued.minor_unit_adjusted,
    )


def _missing_value(lot: PortfolioLot, *, company: str | None, reason: str) -> LineValuation:
    return LineValuation(
        lot=lot,
        company=company,
        current_price_local=None,
        current_price_usd=None,
        fx_rate_to_usd=None,
        snapshot_date=None,
        value_local=None,
        value_usd=None,
        cost_local=lot.cost_local,
        cost_usd_at_current_fx=None,
        pnl_local=None,
        pnl_fraction_local=None,
        pnl_usd_at_current_fx=None,
        status="MISSING_PRICE",
        status_reason=reason,
        price_scale_factor=1.0,
        minor_unit_adjusted=False,
    )


def _lines_frame(
    valuations: list[LineValuation],
    *,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    source_hash: str | None,
    portfolio_source_version: str,
) -> pd.DataFrame:
    rows = [
        {
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "source_run_id": source_run_id,
            "snapshot_refresh_run_id": snapshot_refresh_run_id,
            "source_export_sha256": source_hash,
            "portfolio_source_version": portfolio_source_version,
            "lot_id": value.lot.id,
            "ticker": value.lot.ticker,
            "company": value.company,
            "shares": value.lot.shares,
            "buy_price": value.lot.buy_price,
            "buy_currency": value.lot.buy_currency,
            "buy_date": value.lot.buy_date.isoformat(),
            "cost_local": value.cost_local,
            "current_price_local": value.current_price_local,
            "current_price_usd": value.current_price_usd,
            "fx_rate_to_usd": value.fx_rate_to_usd,
            "snapshot_date": value.snapshot_date,
            "value_local": value.value_local,
            "value_usd": value.value_usd,
            "cost_usd_at_current_fx": value.cost_usd_at_current_fx,
            "pnl_local": value.pnl_local,
            "pnl_fraction_local": value.pnl_fraction_local,
            "pnl_usd_at_current_fx": value.pnl_usd_at_current_fx,
            "line_status": value.status,
            "line_status_reason": value.status_reason,
            "price_scale_factor": value.price_scale_factor,
            "minor_unit_adjusted": value.minor_unit_adjusted,
            "created_at": value.lot.created_at.isoformat(),
            "updated_at": value.lot.updated_at.isoformat(),
            "note": value.lot.note,
        }
        for value in valuations
    ]
    return _with_metadata(pd.DataFrame(rows, columns=LINE_COLUMNS), source_run_id, snapshot_refresh_run_id)


def _positions_frame(
    valuations: list[LineValuation],
    *,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    source_hash: str | None,
    portfolio_source_version: str,
) -> pd.DataFrame:
    grouped: dict[str, list[LineValuation]] = defaultdict(list)
    for value in valuations:
        grouped[value.lot.ticker].append(value)
    total_value_usd = sum_optional_floats(value.value_usd for value in valuations) or 0.0
    rows: list[dict[str, object]] = []
    for ticker, values in sorted(grouped.items()):
        total_shares = sum(value.lot.shares for value in values)
        cost_local = sum(value.cost_local for value in values)
        value_local = sum_optional_floats(value.value_local for value in values)
        value_usd = sum_optional_floats(value.value_usd for value in values)
        cost_usd = sum_optional_floats(value.cost_usd_at_current_fx for value in values)
        pnl_local = (
            value_local - cost_local
            if value_local is not None
            else None
        )
        pnl_pct = pnl_local / cost_local if pnl_local is not None and cost_local > 0 else None
        pnl_usd = (
            value_usd - cost_usd
            if value_usd is not None and cost_usd is not None
            else None
        )
        first = values[0]
        status = _combined_status(values)
        rows.append({
            "schema_version": PORTFOLIO_SCHEMA_VERSION,
            "source_run_id": source_run_id,
            "snapshot_refresh_run_id": snapshot_refresh_run_id,
            "source_export_sha256": source_hash,
            "portfolio_source_version": portfolio_source_version,
            "ticker": ticker,
            "company": first.company,
            "currency": first.lot.buy_currency,
            "total_shares": total_shares,
            "avg_cost_local": cost_local / total_shares if total_shares > 0 else None,
            "cost_local": cost_local,
            "current_price_local": first.current_price_local,
            "current_price_usd": first.current_price_usd,
            "fx_rate_to_usd": first.fx_rate_to_usd,
            "snapshot_date": first.snapshot_date,
            "value_local": value_local,
            "value_usd": value_usd,
            "cost_usd_at_current_fx": cost_usd,
            "pnl_local": pnl_local,
            "pnl_fraction_local": pnl_pct,
            "pnl_usd_at_current_fx": pnl_usd,
            "position_weight_fraction": (
                value_usd / total_value_usd
                if value_usd is not None and total_value_usd > 0
                else None
            ),
            "position_status": status,
            "lot_count": len(values),
        })
    return _with_metadata(pd.DataFrame(rows, columns=POSITION_COLUMNS), source_run_id, snapshot_refresh_run_id)


def _summary_frame(
    valuations: list[LineValuation],
    positions: pd.DataFrame,
    *,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    source_hash: str | None,
    portfolio_source_version: str,
) -> pd.DataFrame:
    total_value_usd = sum_optional_floats(value.value_usd for value in valuations) or 0.0
    total_cost_usd = sum_optional_floats(value.cost_usd_at_current_fx for value in valuations) or 0.0
    total_pnl_usd = (
        total_value_usd - total_cost_usd
        if valuations and total_cost_usd > 0
        else None
    )
    split: dict[str, dict[str, float]] = {}
    for value in valuations:
        bucket = split.setdefault(
            value.lot.buy_currency,
            {"value_usd": 0.0, "cost_usd_at_current_fx": 0.0, "pnl_usd_at_current_fx": 0.0},
        )
        bucket["value_usd"] += value.value_usd or 0.0
        bucket["cost_usd_at_current_fx"] += value.cost_usd_at_current_fx or 0.0
        bucket["pnl_usd_at_current_fx"] += value.pnl_usd_at_current_fx or 0.0
    status = _summary_status(valuations)
    as_of_dates = sorted(
        {
            str(value.snapshot_date)
            for value in valuations
            if value.snapshot_date
        }
    )
    frame = pd.DataFrame(
        [
            {
                "schema_version": PORTFOLIO_SCHEMA_VERSION,
                "source_run_id": source_run_id,
                "snapshot_refresh_run_id": snapshot_refresh_run_id,
                "source_export_sha256": source_hash,
                "portfolio_source_version": portfolio_source_version,
                "portfolio_status": status,
                "lot_count": len(valuations),
                "position_count": len(positions.index),
                "total_value_usd": total_value_usd,
                "total_cost_usd_at_current_fx": total_cost_usd,
                "total_pnl_usd_at_current_fx": total_pnl_usd,
                "currency_split_json": json.dumps(split, sort_keys=True),
                "as_of_date": as_of_dates[-1] if as_of_dates else None,
            }
        ],
        columns=SUMMARY_COLUMNS,
    )
    return _with_metadata(frame, source_run_id, snapshot_refresh_run_id)


def _with_metadata(
    frame: pd.DataFrame,
    source_run_id: str,
    snapshot_refresh_run_id: str,
) -> pd.DataFrame:
    frame.attrs["schema_version"] = PORTFOLIO_SCHEMA_VERSION
    frame.attrs["source_run_id"] = source_run_id
    frame.attrs["snapshot_refresh_run_id"] = snapshot_refresh_run_id
    return frame


def _ensure_columns(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return frame[columns]


def _snapshot_records_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, object]]:
    return latest_records_by_key(frame, "ticker")


def _combined_status(values: list[LineValuation]) -> str:
    statuses = {value.status for value in values}
    return "OK" if statuses == {"OK"} else "; ".join(sorted(statuses))


def _summary_status(values: list[LineValuation]) -> str:
    if not values:
        return "EMPTY"
    return "OK" if all(value.status == "OK" for value in values) else "WARN"


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text or None


def _new_portfolio_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-portfolio-{uuid4().hex[:8]}"
