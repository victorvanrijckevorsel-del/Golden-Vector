"""Shared option artifact builder used by refresh and UI compatibility paths."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Literal

import pandas as pd

from golden_vector.common.strings import unique_strings
from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge._helpers import (
    as_float,
    is_optionable_tier,
    optionability_tier,
    row_float,
    row_string,
    rows_by_ticker_series,
)
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingOverviewData,
    OptionTradingSourceContext,
    build_option_trading_overview,
)
from golden_vector.hedge.options_liquidity import (
    OptionContractMetrics,
    build_bucket_slots,
    candidate_bucket_ids,
    scan_option_chain,
    settings_from_config,
)


@dataclass(frozen=True)
class OptionArtifactBuildResult:
    overview: OptionTradingOverviewData
    candidate_grids: dict[str, list[OptionCandidate]]
    call_candidate_grids: dict[str, list[OptionCandidate]]
    candidate_slots: dict[str, list[OptionCandidateSlot]]
    call_candidate_slots: dict[str, list[OptionCandidateSlot]]
    liquidity_measurements: tuple[OptionLiquidityMeasurement, ...]
    source_context: OptionTradingSourceContext


def build_option_artifact_inputs(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
    risk_free_rate_is_fallback: bool,
    manifest: dict[str, Any],
) -> OptionArtifactBuildResult:
    """Build current option rows from already-loaded model and option-chain inputs."""

    candidate_slots = build_option_candidate_slots(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=risk_free_rate,
        manifest=manifest,
        option_type="P",
        target_delta=app_config.hedge_readiness.target_delta,
    )
    call_candidate_slots = build_option_candidate_slots(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=risk_free_rate,
        manifest=manifest,
        option_type="C",
        target_delta=abs(app_config.hedge_readiness.target_delta),
    )
    candidate_grids = accepted_candidate_grids(candidate_slots)
    call_candidate_grids = accepted_candidate_grids(call_candidate_slots)
    source_context = build_option_source_context(
        manifest=manifest,
        tool_a=tool_a,
        tool_b=tool_b,
        risk_free_rate=risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )
    liquidity_measurements = build_option_liquidity_measurements(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=risk_free_rate,
        manifest=manifest,
    )
    overview = build_option_trading_overview(
        tool_a=tool_a,
        options_features=features,
        candidate_grids=candidate_grids,
        call_candidate_grids=call_candidate_grids,
        risk_free_rate=risk_free_rate,
        target_horizons_days=tuple(app_config.hedge_readiness.display_horizons_days),
        down_beta_min_for_scenario=app_config.hedge_readiness.down_beta_min_for_scenario,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        source_context=source_context,
        liquidity_measurements=liquidity_measurements,
    )
    return OptionArtifactBuildResult(
        overview=overview,
        candidate_grids=candidate_grids,
        call_candidate_grids=call_candidate_grids,
        candidate_slots=candidate_slots,
        call_candidate_slots=call_candidate_slots,
        liquidity_measurements=liquidity_measurements,
        source_context=source_context,
    )


def build_option_candidate_slots(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
    manifest: dict[str, Any],
    option_type: Literal["P", "C"],
    target_delta: float,
) -> dict[str, list[OptionCandidateSlot]]:
    feature_by_ticker = rows_by_ticker_series(features, strip=True)
    tool_b_by_ticker = rows_by_ticker_series(tool_b, strip=True)
    as_of_date = _manifest_as_of_date(manifest)
    liquidity_settings = settings_from_config(app_config.hedge_readiness)
    slots_by_ticker: dict[str, list[OptionCandidateSlot]] = {}
    for ticker, feature in feature_by_ticker.items():
        if not is_optionable_tier(optionability_tier(row_string(feature, "optionability_tier"))):
            continue
        chain = chains.get(ticker, pd.DataFrame())
        price = _current_stock_price(
            feature=feature,
            tool_b_row=tool_b_by_ticker.get(ticker),
            chain=chain,
        )
        if price is None or price <= 0:
            slots_by_ticker[ticker] = [
                OptionCandidateSlot(
                    ticker=ticker,
                    option_type=option_type,
                    horizon_days=horizon,
                    target_delta=float(target_delta),
                    expiration=None,
                    days_to_expiry=None,
                    status="no_price",
                    reason=(
                        "No cached stock price is available, so option deltas "
                        "cannot be computed."
                    ),
                    bucket=bucket,
                )
                for horizon in app_config.hedge_readiness.display_horizons_days
                for bucket in candidate_bucket_ids()
            ]
            continue
        slots_by_ticker[ticker] = build_bucket_slots(
            option_type=option_type,
            ticker=ticker,
            chain=chain,
            underlying_price=price,
            risk_free_rate=risk_free_rate,
            target_horizons_days=tuple(app_config.hedge_readiness.display_horizons_days),
            settings=liquidity_settings,
            as_of_date=as_of_date,
        )
    return slots_by_ticker


def accepted_candidate_grids(
    slots_by_ticker: dict[str, list[OptionCandidateSlot]],
) -> dict[str, list[OptionCandidate]]:
    return {
        ticker: _unique_candidates(
            [slot.candidate for slot in slots if slot.candidate is not None]
        )
        for ticker, slots in slots_by_ticker.items()
    }


def build_option_liquidity_measurements(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
    manifest: dict[str, Any],
) -> tuple[OptionLiquidityMeasurement, ...]:
    feature_by_ticker = rows_by_ticker_series(features, strip=True)
    tool_b_by_ticker = rows_by_ticker_series(tool_b, strip=True)
    benchmark_tickers = {
        str(ticker).upper()
        for ticker in app_config.hedge_readiness.benchmark_tickers
    }
    settings = settings_from_config(app_config.hedge_readiness)
    as_of_date = _manifest_as_of_date(manifest)
    grouped: dict[str, list[dict[str, float | str]]] = {
        "Benchmark ETFs": [],
        "Single-stock miners": [],
    }
    seen_tickers: dict[str, set[str]] = {
        "Benchmark ETFs": set(),
        "Single-stock miners": set(),
    }

    for ticker, chain in chains.items():
        feature = feature_by_ticker.get(ticker)
        if feature is None:
            continue
        price = _current_stock_price(
            feature=feature,
            tool_b_row=tool_b_by_ticker.get(ticker),
            chain=chain,
        )
        if price is None or price <= 0:
            continue
        scan = scan_option_chain(
            ticker=ticker,
            chain=chain,
            underlying_price=price,
            risk_free_rate=risk_free_rate,
            settings=settings,
            as_of_date=as_of_date,
        )
        metrics = [
            metric
            for metric in scan.metrics
            if metric.rel_spread is not None
            and metric.mid is not None
            and metric.mid > 0
        ]
        if not metrics:
            continue
        group = (
            "Benchmark ETFs"
            if ticker in benchmark_tickers
            or row_string(feature, "option_vehicle_type") == "benchmark_etf"
            else "Single-stock miners"
        )
        seen_tickers[group].add(ticker)
        grouped[group].extend(
            {
                "rel_spread": float(metric.rel_spread),
                "open_interest": float(metric.open_interest),
                "volume": float(metric.volume),
                "near_spot_depth": float(metric.near_spot_depth_count),
                "liquidity_tier": metric.liquidity_tier,
            }
            for metric in metrics
        )

    measurements: list[OptionLiquidityMeasurement] = []
    for group in ("Benchmark ETFs", "Single-stock miners"):
        rows = grouped[group]
        if not rows:
            if group == "Benchmark ETFs" and benchmark_tickers:
                measurements.append(
                    OptionLiquidityMeasurement(
                        group_label=group,
                        ticker_count=0,
                        contract_count=0,
                        median_rel_spread=None,
                        median_open_interest=None,
                        median_volume=None,
                        median_near_spot_depth=None,
                    )
                )
            continue
        measurements.append(
            OptionLiquidityMeasurement(
                group_label=group,
                ticker_count=len(seen_tickers[group]),
                contract_count=len(rows),
                median_rel_spread=_median(row["rel_spread"] for row in rows),
                median_open_interest=_median(row["open_interest"] for row in rows),
                median_volume=_median(row["volume"] for row in rows),
                median_near_spot_depth=_median(row["near_spot_depth"] for row in rows),
                tradable_count=_tier_count(rows, "tradable"),
                watch_count=_tier_count(rows, "watch"),
                no_trade_count=_tier_count(rows, "no_trade"),
            )
        )
    return tuple(measurements)


def scan_option_contract_metrics(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
    manifest: dict[str, Any],
) -> tuple[OptionContractMetrics, ...]:
    """Scan all loaded option chains into per-contract liquidity metrics."""

    feature_by_ticker = rows_by_ticker_series(features, strip=True)
    tool_b_by_ticker = rows_by_ticker_series(tool_b, strip=True)
    settings = settings_from_config(app_config.hedge_readiness)
    as_of_date = _manifest_as_of_date(manifest)
    metrics: list[OptionContractMetrics] = []
    for ticker, chain in chains.items():
        feature = feature_by_ticker.get(ticker)
        if feature is None:
            continue
        price = _current_stock_price(
            feature=feature,
            tool_b_row=tool_b_by_ticker.get(ticker),
            chain=chain,
        )
        if price is None or price <= 0:
            continue
        scan = scan_option_chain(
            ticker=ticker,
            chain=chain,
            underlying_price=price,
            risk_free_rate=risk_free_rate,
            settings=settings,
            as_of_date=as_of_date,
        )
        metrics.extend(scan.metrics)
    return tuple(metrics)


def build_option_source_context(
    *,
    manifest: dict[str, Any],
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    risk_free_rate: float,
    risk_free_rate_is_fallback: bool,
) -> OptionTradingSourceContext:
    as_of_raw = str(manifest.get("as_of_date") or "").strip() or None
    refresh_raw = str(manifest.get("refresh_run_id") or "").strip() or None
    tool_a_refresh_run_ids = tuple(unique_strings(tool_a, "snapshot_refresh_run_id"))
    tool_b_refresh_run_ids = tuple(unique_strings(tool_b, "snapshot_refresh_run_id"))
    return OptionTradingSourceContext(
        as_of_date=as_of_raw,
        refresh_run_id=refresh_raw,
        tool_a_refresh_run_ids=tool_a_refresh_run_ids,
        tool_b_refresh_run_ids=tool_b_refresh_run_ids,
        context_warnings=_context_warnings(
            options_refresh_run_id=refresh_raw,
            tool_a_refresh_run_ids=tool_a_refresh_run_ids,
            tool_b_refresh_run_ids=tool_b_refresh_run_ids,
        ),
        risk_free_rate=risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )


def _unique_candidates(candidates: list[OptionCandidate]) -> list[OptionCandidate]:
    seen: set[tuple[int, str, float, str]] = set()
    unique: list[OptionCandidate] = []
    for candidate in candidates:
        key = (
            candidate.horizon_days,
            candidate.expiration,
            candidate.strike,
            candidate.option_type,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _tier_count(rows: list[dict[str, float | str]], tier: str) -> int:
    return sum(1 for row in rows if row.get("liquidity_tier") == tier)


def _median(values: Iterable[float | str]) -> float | None:
    numeric = [value for value in (as_float(value) for value in values) if value is not None]
    return float(median(numeric)) if numeric else None


def _context_warnings(
    *,
    options_refresh_run_id: str | None,
    tool_a_refresh_run_ids: tuple[str, ...],
    tool_b_refresh_run_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not options_refresh_run_id:
        return ()
    mixed_parts: list[str] = []
    if not _run_ids_match(tool_a_refresh_run_ids, options_refresh_run_id):
        mixed_parts.append(f"Tool A uses {_format_run_ids(tool_a_refresh_run_ids)}")
    if not _run_ids_match(tool_b_refresh_run_ids, options_refresh_run_id):
        mixed_parts.append(f"Tool B uses {_format_run_ids(tool_b_refresh_run_ids)}")
    if not mixed_parts:
        return ()
    return (
        "Refresh context is mixed: options snapshot uses "
        f"{options_refresh_run_id}; {'; '.join(mixed_parts)}. "
        "Scenario betas and fundamentals may lag the option chains. Run "
        "python main.py refresh to realign the full model outputs.",
    )


def _run_ids_match(run_ids: tuple[str, ...], expected: str) -> bool:
    return bool(run_ids) and all(run_id == expected for run_id in run_ids)


def _format_run_ids(run_ids: tuple[str, ...]) -> str:
    return ", ".join(run_ids) if run_ids else "no recorded refresh id"


def _current_stock_price(
    *,
    feature: pd.Series,
    tool_b_row: pd.Series | None,
    chain: pd.DataFrame,
) -> float | None:
    for value in (
        row_float(feature, "underlying_price"),
        row_float(tool_b_row, "share_price_usd"),
        _chain_underlying_price(chain),
    ):
        if value is not None and value > 0:
            return value
    return None


def _chain_underlying_price(chain: pd.DataFrame) -> float | None:
    if chain.empty or "underlying_price" not in chain.columns:
        return None
    values = chain["underlying_price"].dropna()
    if values.empty:
        return None
    return as_float(values.iloc[0])


def _manifest_as_of_date(manifest: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(manifest.get("as_of_date")))
    except (TypeError, ValueError):
        return None
