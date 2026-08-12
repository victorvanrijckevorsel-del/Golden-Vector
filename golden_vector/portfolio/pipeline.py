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
from golden_vector.normalize.calendar import fx_rate_to_usd_asof
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    read_current_model_parquet,
    resolve_current_foundation_manifest_path,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import optional_sha256_file
from golden_vector.common.frames import latest_records_by_key
from golden_vector.common.numeric import optional_finite_float, optional_float, sum_optional_floats
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
    # schema v2: cost currency separated from quote currency + backend GBP + provenance
    "quote_currency",
    "cost_currency",
    "cost_basis_total",
    "raw_broker_symbol",
    "source_name",
    "cost_basis_as_of_date",
    "value_gbp",
    "cost_gbp_at_current_fx",
    "pnl_gbp_at_current_fx",
    "fx_issues_json",
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
    *ANALYTICS_POSITION_COLUMNS,
    "position_status",
    "lot_count",
    # schema v2
    "quote_currency",
    "cost_currency",
    "value_gbp",
    "cost_gbp_at_current_fx",
    "pnl_gbp_at_current_fx",
    "avg_cost_gbp",
    "pnl_fraction_gbp",
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
    # schema v2
    "cost_currency_split_json",
    "total_value_gbp",
    "total_cost_gbp_at_current_fx",
    "total_pnl_gbp_at_current_fx",
    "as_of_date_min",
    "as_of_date_max",
    "snapshot_date_status",
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
    foundation_manifest_path: Path | None = None,
) -> PortfolioBuildResult:
    source_run_id = source_run_id or _new_portfolio_run_id()
    resolved_foundation_manifest_path = foundation_manifest_path or _portfolio_foundation_manifest_path(
        paths,
        use_model_state_artifacts=use_model_state_artifacts,
    )
    lots = load_lots(paths)
    requested_tickers = sorted({lot.ticker for lot in lots})
    foundation = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=True,
        include_equity_histories=bool(requested_tickers),
        include_market_snapshots=True,
        include_fx_histories=True,
        requested_tickers=requested_tickers,
        manifest_path=resolved_foundation_manifest_path,
    )
    ticker_info = build_ticker_info(app_config)
    snapshots_by_ticker = _snapshot_records_by_ticker(foundation.normalized_market_snapshots)
    source_hash = optional_sha256_file(paths.manual_portfolio_lots_path)
    portfolio_source_version = source_hash or "empty"
    valuations = [
        _safe_value_lot(
            lot,
            ticker_info=ticker_info,
            snapshot=snapshots_by_ticker.get(lot.ticker),
            max_fx_staleness_days=app_config.qa.max_fx_staleness_days,
            fx_histories=foundation.fx_histories,
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
        # Portfolio resilience is intentionally Our View only. The analytics
        # boundary enforces that source before its ticker-keyed lookup.
        tool_d=_read_current_or_latest_artifact(
            paths,
            artifact_name="tool_d_spot",
            fallback_path=paths.latest_tool_d_spot_snapshot_parquet_path,
            use_model_state=use_model_state_artifacts,
        ),
        benchmark_betas=benchmark_betas,
        reconciliation=reconciliation,
        gold_down_min_beta=app_config.hedge_readiness.down_beta_min_for_scenario,
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
        gold_down_min_beta=app_config.hedge_readiness.down_beta_min_for_scenario,
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


def _portfolio_foundation_manifest_path(
    paths: ProjectPaths,
    *,
    use_model_state_artifacts: bool,
) -> Path | None:
    if use_model_state_artifacts:
        return resolve_current_foundation_manifest_path(paths)
    return paths.latest_foundation_manifest_path


def _value_lot(
    lot: PortfolioLot,
    *,
    ticker_info: dict[str, TickerInfo],
    snapshot: dict[str, object] | None,
    max_fx_staleness_days: int,
    fx_histories: dict[str, pd.DataFrame] | None = None,
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
        return _missing_value(
            lot,
            company=company,
            reason="Current FX rate is missing.",
            status="MISSING_FX",
        )
    snapshot_currency = _optional_string(snapshot.get("currency")) or lot.buy_currency
    snapshot_currency = snapshot_currency.strip().upper()
    # Feed-specific minor-unit markers such as GBp are normalized upstream;
    # portfolio valuation compares major-unit configured currencies only.
    if snapshot_currency != lot.buy_currency:
        return _missing_value(
            lot,
            company=company,
            reason=(
                "Snapshot price currency "
                f"{snapshot_currency} does not match lot currency {lot.buy_currency}."
            ),
            status="CURRENCY_MISMATCH",
        )
    snapshot_status = str(snapshot.get("normalization_status") or "OK").strip().upper()
    fx_staleness_days = optional_float(snapshot.get("fx_staleness_days"))
    status_parts: list[str] = []
    reasons: list[str] = []
    quote_fx_stale = fx_staleness_days is not None and fx_staleness_days > max_fx_staleness_days
    if quote_fx_stale:
        status_parts.append("STALE_FX")
        reasons.append(f"Quote FX source is {fx_staleness_days:g} days old.")
    if snapshot_status != "OK":
        status_parts.append(snapshot_status)
        reasons.append(f"Snapshot status is {snapshot_status}.")
    valued = value_major_unit_price(
        ValuationInput(
            quantity=lot.shares,
            price_local=price_local,
            price_currency=snapshot_currency,
            fx_rate_to_usd=fx_rate,
        )
    )
    snapshot_scale_factor = optional_float(snapshot.get("price_scale_factor"))
    snapshot_minor_adjusted = bool(snapshot.get("minor_unit_adjusted") or False)
    quote_currency = lot.buy_currency
    cost_currency = (lot.cost_currency or lot.buy_currency).strip().upper()
    # optional_finite_float -> None for NaN/inf so a non-finite stored cost can
    # never reach the aggregates as a partial-cost fake gain.
    cost_basis = optional_finite_float(
        lot.cost_basis_total if lot.cost_basis_total is not None else lot.cost_local
    )
    snapshot_date = _optional_string(snapshot.get("snapshot_date"))
    histories = fx_histories or {}
    fx_issues: list[str] = []
    # Stale quote FX -> exclude USD/GBP value & P&L (degraded data is excluded, not
    # flag-only); local figures stay. A distinct cost-currency FX is unaffected.
    # USD lines never apply quote FX (rate is 1.0), so a stale quote-FX marker does
    # NOT corrupt their USD value -- only NON-USD lines must exclude the USD/GBP legs.
    quote_fx_excludes_value = quote_fx_stale and quote_currency != "USD"
    value_usd = None if quote_fx_excludes_value else valued.market_value_usd
    current_price_usd = None if quote_fx_excludes_value else valued.price_local_major * fx_rate

    # Cost -> USD via the COST currency's FX (not the quote FX). Same currency as
    # the quote leg reuses the snapshot rate (null when that quote FX is stale);
    # USD is 1.0; otherwise look it up, bounded by max_fx_staleness_days.
    if cost_currency == quote_currency:
        cost_fx = fx_rate
    elif cost_currency == "USD":
        cost_fx = 1.0
    else:
        cost_fx = fx_rate_to_usd_asof(
            histories.get(cost_currency), snapshot_date, max_staleness_days=max_fx_staleness_days
        )
    if cost_basis is None:
        cost_usd = None
        fx_issues.append("cost_basis")
        status_parts.append("INVALID_COST_BASIS")
        reasons.append("Cost basis is missing or not a finite number.")
    elif quote_fx_excludes_value and cost_currency == quote_currency:
        # Same-currency cost uses the (stale) quote FX; STALE_FX already flags it,
        # so exclude cost_usd without a redundant MISSING_COST_FX.
        cost_usd = None
    elif cost_fx is None or cost_fx <= 0:
        cost_usd = None
        fx_issues.append("cost_fx")
        status_parts.append("MISSING_COST_FX")
        reasons.append(f"Cost-currency FX ({cost_currency}) is unavailable or stale.")
    else:
        cost_usd = cost_basis * cost_fx

    # Local P&L is only meaningful when cost and quote currencies match and the
    # cost basis is finite. Use the canonical cost_basis (cost_basis_total when
    # present), not the legacy shares*buy_price.
    if cost_currency == quote_currency and cost_basis is not None:
        pnl_local = valued.market_value_local - cost_basis
        pnl_pct = pnl_local / cost_basis if cost_basis > 0 else None
    else:
        pnl_local = None
        pnl_pct = None

    pnl_usd = (value_usd - cost_usd) if (value_usd is not None and cost_usd is not None) else None

    # GBP presentation (backend-computed): value_gbp = value_usd / GBPUSD.
    if quote_currency == "GBP":
        gbp_to_usd = None if quote_fx_excludes_value else fx_rate
    elif cost_currency == "GBP" and cost_fx:
        gbp_to_usd = cost_fx
    else:
        gbp_to_usd = fx_rate_to_usd_asof(
            histories.get("GBP"), snapshot_date, max_staleness_days=max_fx_staleness_days
        )
    if gbp_to_usd and gbp_to_usd > 0:
        value_gbp = (value_usd / gbp_to_usd) if value_usd is not None else None
        cost_gbp = (cost_usd / gbp_to_usd) if cost_usd is not None else None
        pnl_gbp = (value_gbp - cost_gbp) if (value_gbp is not None and cost_gbp is not None) else None
    else:
        value_gbp = None
        cost_gbp = None
        pnl_gbp = None
        # Presentation-only: USD valuation stays valid, so do NOT degrade status.
        fx_issues.append("gbp_presentation_fx")

    status = "; ".join(dict.fromkeys(status_parts)) if status_parts else "OK"
    return LineValuation(
        lot=lot,
        company=company,
        current_price_local=valued.price_local_major,
        current_price_usd=current_price_usd,
        fx_rate_to_usd=fx_rate,
        snapshot_date=snapshot_date,
        value_local=valued.market_value_local,
        value_usd=value_usd,
        cost_local=cost_basis,
        cost_usd_at_current_fx=cost_usd,
        pnl_local=pnl_local,
        pnl_fraction_local=pnl_pct,
        pnl_usd_at_current_fx=pnl_usd,
        status=status,
        status_reason=None if status == "OK" else " ".join(reasons),
        price_scale_factor=snapshot_scale_factor or valued.price_scale_factor,
        minor_unit_adjusted=snapshot_minor_adjusted or valued.minor_unit_adjusted,
        quote_currency=quote_currency,
        cost_currency=cost_currency,
        value_gbp=value_gbp,
        cost_gbp_at_current_fx=cost_gbp,
        pnl_gbp_at_current_fx=pnl_gbp,
        fx_issues=tuple(fx_issues),
    )


def _safe_value_lot(
    lot: PortfolioLot,
    *,
    ticker_info: dict[str, TickerInfo],
    snapshot: dict[str, object] | None,
    max_fx_staleness_days: int,
    fx_histories: dict[str, pd.DataFrame] | None = None,
) -> LineValuation:
    info = ticker_info.get(lot.ticker)
    company = info.company if info is not None else None
    try:
        return _value_lot(
            lot,
            ticker_info=ticker_info,
            snapshot=snapshot,
            max_fx_staleness_days=max_fx_staleness_days,
            fx_histories=fx_histories or {},
        )
    except ValueError as exc:
        return _missing_value(
            lot,
            company=company,
            reason=f"Portfolio lot could not be valued: {exc}",
            status="INVALID_INPUT",
        )


def _missing_value(
    lot: PortfolioLot,
    *,
    company: str | None,
    reason: str,
    status: str = "MISSING_PRICE",
) -> LineValuation:
    return LineValuation(
        lot=lot,
        company=company,
        current_price_local=None,
        current_price_usd=None,
        fx_rate_to_usd=None,
        snapshot_date=None,
        value_local=None,
        value_usd=None,
        cost_local=optional_finite_float(
            lot.cost_basis_total if lot.cost_basis_total is not None else lot.cost_local
        ),
        cost_usd_at_current_fx=None,
        pnl_local=None,
        pnl_fraction_local=None,
        pnl_usd_at_current_fx=None,
        status=status,
        status_reason=reason,
        price_scale_factor=1.0,
        minor_unit_adjusted=False,
        quote_currency=lot.buy_currency,
        cost_currency=(lot.cost_currency or lot.buy_currency),
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
            "quote_currency": value.quote_currency or value.lot.buy_currency,
            "cost_currency": value.cost_currency or value.lot.cost_currency or value.lot.buy_currency,
            "cost_basis_total": value.lot.cost_basis_total,
            "raw_broker_symbol": value.lot.raw_broker_symbol,
            "source_name": value.lot.source_name,
            "cost_basis_as_of_date": (
                value.lot.cost_basis_as_of_date.isoformat() if value.lot.cost_basis_as_of_date else None
            ),
            "value_gbp": value.value_gbp,
            "cost_gbp_at_current_fx": value.cost_gbp_at_current_fx,
            "pnl_gbp_at_current_fx": value.pnl_gbp_at_current_fx,
            "fx_issues_json": json.dumps(list(value.fx_issues)),
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
    rows: list[dict[str, object]] = []
    for ticker, values in sorted(grouped.items()):
        total_shares = sum(value.lot.shares for value in values)
        value_local = sum_optional_floats(value.value_local for value in values)
        value_usd = sum_optional_floats(value.value_usd for value in values)
        first = values[0]
        quote_ccy = first.lot.buy_currency
        cost_ccys = {
            (value.lot.cost_currency or value.lot.buy_currency).strip().upper() for value in values
        }
        cost_ccy_label = next(iter(cost_ccys)) if len(cost_ccys) == 1 else "MIXED"
        same_ccy = cost_ccys == {quote_ccy.strip().upper()}
        # All-or-null: a partial cost beside a full value would look like a fake
        # gain, and a partial P&L is meaningless — so any missing leg nulls the
        # aggregate rather than summing the resolvable subset.
        value_complete = all(value.value_usd is not None for value in values)
        cost_complete = all(value.cost_usd_at_current_fx is not None for value in values)
        cost_usd = (
            sum_optional_floats(value.cost_usd_at_current_fx for value in values)
            if cost_complete
            else None
        )
        gbp_complete = all(
            value.value_gbp is not None and value.cost_gbp_at_current_fx is not None
            for value in values
        )
        value_gbp = sum_optional_floats(value.value_gbp for value in values) if gbp_complete else None
        cost_gbp = (
            sum_optional_floats(value.cost_gbp_at_current_fx for value in values)
            if gbp_complete
            else None
        )
        # Local cost is one well-defined currency only when every lot's cost ccy
        # equals the quote ccy AND each local cost is finite; otherwise NA (never
        # sum unlike currencies). The USD/GBP legs carry cross-currency cost.
        cost_local_ok = same_ccy and all(value.cost_local is not None for value in values)
        cost_local = sum(value.cost_local for value in values) if cost_local_ok else None
        avg_cost_local = (
            cost_local / total_shares if cost_local is not None and total_shares > 0 else None
        )
        if cost_local is not None and value_complete:
            pnl_local = value_local - cost_local if value_local is not None else None
            pnl_pct = pnl_local / cost_local if pnl_local is not None and cost_local > 0 else None
        else:
            # Cost currency differs/mixed/non-finite, or some lot is unvalued:
            # local P&L is not meaningful — USD/GBP P&L carry it instead.
            pnl_local = None
            pnl_pct = None
        pnl_usd = (
            value_usd - cost_usd
            if value_complete and cost_complete and value_usd is not None and cost_usd is not None
            else None
        )
        pnl_gbp = (
            value_gbp - cost_gbp
            if value_gbp is not None and cost_gbp is not None
            else None
        )
        # GBP presentation of cost/P&L for every position, so the per-row cost and P&L
        # are shown even when the cost currency differs from the quote currency (e.g. a
        # GBP cost on an AUD-quoted .AX name, where the local-currency figures are NA).
        # For same-currency (GBP) names these equal the local figures.
        avg_cost_gbp = (
            cost_gbp / total_shares if cost_gbp is not None and total_shares > 0 else None
        )
        pnl_fraction_gbp = (
            pnl_gbp / cost_gbp
            if pnl_gbp is not None and cost_gbp is not None and cost_gbp > 0
            else None
        )
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
            "avg_cost_local": avg_cost_local,
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
            "position_status": status,
            "lot_count": len(values),
            "quote_currency": quote_ccy,
            "cost_currency": cost_ccy_label,
            "value_gbp": value_gbp,
            "cost_gbp_at_current_fx": cost_gbp,
            "pnl_gbp_at_current_fx": pnl_gbp,
            "avg_cost_gbp": avg_cost_gbp,
            "pnl_fraction_gbp": pnl_fraction_gbp,
        })
    return _with_metadata(pd.DataFrame(rows, columns=POSITION_COLUMNS), source_run_id, snapshot_refresh_run_id)


def _currency_split(valuations, *, key) -> dict[str, dict[str, float | None]]:
    """Bucket valuations by ``key`` and aggregate value/cost/P&L per currency with
    all-or-null cost: a bucket's cost and P&L are null unless every valued lot in
    it has a cost (so a missing cost never reads as a partial sum / fake gain)."""

    members: dict[str, list[LineValuation]] = defaultdict(list)
    for value in valuations:
        members[str(key(value))].append(value)
    split: dict[str, dict[str, float | None]] = {}
    for currency, members_in_bucket in members.items():
        valued = [value for value in members_in_bucket if value.value_usd is not None]
        value_usd = sum_optional_floats(value.value_usd for value in valued) or 0.0
        cost_ok = bool(valued) and all(
            value.cost_usd_at_current_fx is not None for value in valued
        )
        cost_usd = (
            sum_optional_floats(value.cost_usd_at_current_fx for value in valued)
            if cost_ok
            else None
        )
        pnl_usd = (value_usd - cost_usd) if (cost_ok and cost_usd is not None) else None
        split[currency] = {
            "value_usd": value_usd,
            "cost_usd_at_current_fx": cost_usd,
            "pnl_usd_at_current_fx": pnl_usd,
        }
    return split


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
    # All-or-null over the valued book: a partial cost beside full value would look
    # like a fake gain, so any valued lot missing its cost nulls total cost + P&L.
    valued = [value for value in valuations if value.value_usd is not None]
    cost_complete = bool(valued) and all(
        value.cost_usd_at_current_fx is not None for value in valued
    )
    total_cost_usd = (
        sum_optional_floats(value.cost_usd_at_current_fx for value in valued)
        if cost_complete
        else None
    )
    total_pnl_usd = (
        total_value_usd - total_cost_usd if cost_complete and total_cost_usd is not None else None
    )
    gbp_complete = bool(valued) and all(
        value.value_gbp is not None and value.cost_gbp_at_current_fx is not None for value in valued
    )
    total_value_gbp = (
        sum_optional_floats(value.value_gbp for value in valued) if gbp_complete else None
    )
    total_cost_gbp = (
        sum_optional_floats(value.cost_gbp_at_current_fx for value in valued) if gbp_complete else None
    )
    total_pnl_gbp = (
        total_value_gbp - total_cost_gbp
        if gbp_complete and total_value_gbp is not None and total_cost_gbp is not None
        else None
    )
    # Per-currency splits with the same all-or-null discipline as the totals: a
    # bucket's cost/P&L is null unless every valued lot in it has a cost (never a
    # partial cost beside full value). Value exposure splits by quote currency;
    # cost/P&L also split by cost currency (which can differ from quote in v2).
    quote_split = _currency_split(valuations, key=lambda value: value.lot.buy_currency)
    cost_split = _currency_split(
        valuations, key=lambda value: (value.lot.cost_currency or value.lot.buy_currency)
    )
    status = _summary_status(valuations)
    as_of_dates = sorted(
        {
            str(value.snapshot_date)
            for value in valuations
            if value.snapshot_date
        }
    )
    # Label the basis of the whole book: when per-ticker snapshots span more than
    # one date, the headline date alone mislabels NAV/P&L. Surface min/max + a MIXED
    # flag so the page can show the range, not a single confident date.
    as_of_date_min = as_of_dates[0] if as_of_dates else None
    as_of_date_max = as_of_dates[-1] if as_of_dates else None
    if not as_of_dates:
        snapshot_date_status = "NONE"
    elif len(as_of_dates) > 1:
        snapshot_date_status = "MIXED"
    else:
        snapshot_date_status = "SINGLE"
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
                "currency_split_json": json.dumps(quote_split, sort_keys=True),
                "cost_currency_split_json": json.dumps(cost_split, sort_keys=True),
                "as_of_date": as_of_date_max,
                "total_value_gbp": total_value_gbp,
                "total_cost_gbp_at_current_fx": total_cost_gbp,
                "total_pnl_gbp_at_current_fx": total_pnl_gbp,
                "as_of_date_min": as_of_date_min,
                "as_of_date_max": as_of_date_max,
                "snapshot_date_status": snapshot_date_status,
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
    if statuses == {"OK"}:
        return "OK"
    # Drop "OK" when any lot is degraded, so the position status reads cleanly
    # (e.g. "MISSING_COST_FX", not "MISSING_COST_FX; OK").
    return "; ".join(sorted(status for status in statuses if status != "OK"))


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
