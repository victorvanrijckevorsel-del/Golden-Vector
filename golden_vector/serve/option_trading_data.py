"""Load and cache structured option-trading data for the workspace UI."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge._helpers import (
    as_float,
    is_optionable_tier,
    optionability_tier,
    row_float,
    row_string,
    rows_by_ticker_series,
)
from golden_vector.hedge.candidate_puts import (
    OptionCandidate,
    OptionCandidateSlot,
)
from golden_vector.hedge.option_trading import (
    OptionSide,
    OptionLiquidityMeasurement,
    OptionProxyFallback,
    OptionSizingRequest,
    OptionTradingDetailData,
    OptionTradingOverviewData,
    OptionTradingSourceContext,
    SizingMode,
    build_option_trading_detail,
    build_option_trading_overview,
)
from golden_vector.hedge.options_liquidity import (
    build_bucket_slots,
    candidate_bucket_ids,
    scan_option_chain,
    settings_from_config,
)
from golden_vector.ingestion.persist_options import safe_options_file_name


@dataclass(frozen=True)
class OptionTradingCacheKey:
    options_refresh_run_id: str
    tool_a_refresh_run_ids: tuple[str, ...]
    tool_b_refresh_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class OptionTradingData:
    overview: OptionTradingOverviewData
    candidate_grids: dict[str, list[OptionCandidate]]
    call_candidate_grids: dict[str, list[OptionCandidate]]
    candidate_slots: dict[str, list[OptionCandidateSlot]]
    call_candidate_slots: dict[str, list[OptionCandidateSlot]]
    options_features: pd.DataFrame
    tool_a: pd.DataFrame
    tool_b: pd.DataFrame
    raw_options_by_ticker: dict[str, pd.DataFrame]
    risk_free_rate: float
    risk_free_rate_is_fallback: bool
    cache_key: OptionTradingCacheKey | None


_CACHE: dict[OptionTradingCacheKey, OptionTradingData] = {}


def clear_option_trading_cache() -> None:
    _CACHE.clear()


def build_option_trading_detail_data(
    data: OptionTradingData,
    *,
    ticker: str,
    app_config: AppConfig,
    sizing_request: OptionSizingRequest | None = None,
) -> OptionTradingDetailData:
    normalized = ticker.strip().upper()
    overview_row = next(
        (row for row in data.overview.rows if row.ticker == normalized),
        None,
    )
    detail = build_option_trading_detail(
        ticker=normalized,
        tool_a=data.tool_a,
        candidate_grids=data.candidate_grids,
        call_candidate_grids=data.call_candidate_grids,
        put_candidate_slots=data.candidate_slots,
        call_candidate_slots=data.call_candidate_slots,
        sizing_request=sizing_request,
        overview_row=overview_row,
        risk_free_rate=data.risk_free_rate,
        risk_free_rate_is_fallback=data.risk_free_rate_is_fallback,
        source_context=data.overview.source_context,
        target_horizons_days=tuple(app_config.hedge_readiness.display_horizons_days),
        down_beta_min_for_scenario=(
            app_config.hedge_readiness.down_beta_min_for_scenario
        ),
    )
    detail = _with_proxy_fallbacks(
        data=data,
        detail=detail,
        app_config=app_config,
        request=sizing_request or OptionSizingRequest(),
    )
    if detail.row is not None or not data.overview.reason:
        return detail
    return OptionTradingDetailData(
        ticker=detail.ticker,
        row=detail.row,
        put_candidates=detail.put_candidates,
        put_bundles=detail.put_bundles,
        put_slots=detail.put_slots,
        call_candidates=detail.call_candidates,
        call_bundles=detail.call_bundles,
        call_slots=detail.call_slots,
        sizing=detail.sizing,
        reason=data.overview.reason,
        risk_free_rate_is_fallback=detail.risk_free_rate_is_fallback,
        source_context=detail.source_context,
        proxy_fallbacks=detail.proxy_fallbacks,
        proxy_fallback_note=detail.proxy_fallback_note,
    )


def _with_proxy_fallbacks(
    *,
    data: OptionTradingData,
    detail: OptionTradingDetailData,
    app_config: AppConfig,
    request: OptionSizingRequest,
) -> OptionTradingDetailData:
    if detail.row is None or detail.row.option_vehicle_type == "benchmark_etf":
        return detail
    if detail.sizing is not None and detail.sizing.bundle is not None:
        return detail
    side = request.side
    horizon_days = request.horizon_days
    benchmark_tickers = tuple(
        str(ticker).strip().upper()
        for ticker in app_config.hedge_readiness.benchmark_tickers
        if str(ticker).strip()
    )
    if not _benchmark_liquidity_supports_proxy(data.overview.liquidity_measurements):
        note = (
            "GDX/GDXJ proxy alternatives are hidden because benchmark ETF option "
            "chains are not measured, or the cached liquidity check does not show "
            "a cleaner ETF market."
        )
        return replace(detail, proxy_fallback_note=note)
    source = data.candidate_grids if side == "put" else data.call_candidate_grids
    fallbacks: list[OptionProxyFallback] = []
    for ticker in benchmark_tickers:
        candidate = _proxy_candidate_for_request(
            source.get(ticker, []),
            side=side,
            horizon_days=horizon_days,
            requested_bucket=request.bucket,
        )
        if candidate is None:
            continue
        fallbacks.append(
            OptionProxyFallback(
                ticker=ticker,
                side=side,
                horizon_days=horizon_days,
                candidate=candidate,
                reason=(
                    "Benchmark ETF option vehicle. It expresses the sector, "
                    f"not {detail.ticker} one-for-one."
                ),
            )
        )
    if not fallbacks:
        return replace(
            detail,
            proxy_fallback_note=(
                "Benchmark ETF chains were measured, but no same-side, same-horizon "
                "ETF proxy candidate passed the Tradable gate."
            ),
        )
    return replace(detail, proxy_fallbacks=tuple(fallbacks))


def _benchmark_liquidity_supports_proxy(
    measurements: tuple[OptionLiquidityMeasurement, ...],
) -> bool:
    benchmark = next(
        (
            measurement
            for measurement in measurements
            if measurement.group_label == "Benchmark ETFs"
        ),
        None,
    )
    single_stock = next(
        (
            measurement
            for measurement in measurements
            if measurement.group_label == "Single-stock miners"
        ),
        None,
    )
    if benchmark is None or benchmark.tradable_count < 1:
        return False
    if single_stock is None:
        return True
    if (
        benchmark.median_rel_spread is not None
        and single_stock.median_rel_spread is not None
    ):
        return benchmark.median_rel_spread <= single_stock.median_rel_spread
    return benchmark.contract_count > 0


def _proxy_candidate_for_request(
    candidates: list[OptionCandidate],
    *,
    side: OptionSide,
    horizon_days: int,
    requested_bucket: str | None,
) -> OptionCandidate | None:
    side_type = "P" if side == "put" else "C"
    eligible = [
        candidate
        for candidate in candidates
        if candidate.option_type == side_type
        and candidate.horizon_days == horizon_days
        and candidate.liquidity_tier == "tradable"
    ]
    if not eligible:
        return None
    bucket_order = {
        str(requested_bucket or ""): 0,
        "near_atm": 1,
        "directional": 2,
    }
    return sorted(
        eligible,
        key=lambda candidate: (
            bucket_order.get(str(candidate.bucket or ""), 9),
            candidate.rel_spread is None,
            candidate.rel_spread or 999.0,
            -(candidate.open_interest or 0),
        ),
    )[0]


def parse_option_sizing_request(
    query: dict[str, list[str]],
    *,
    app_config: AppConfig,
) -> OptionSizingRequest:
    """Parse the GET-only ticker sizing calculator query."""

    notes: list[str] = []
    side_raw = _query_value(query, "side").lower()
    side: OptionSide = (
        cast(OptionSide, side_raw) if side_raw in {"put", "call"} else "put"
    )
    if side_raw and side_raw not in {"put", "call"}:
        notes.append("Invalid side; defaulted to put.")

    target_horizons = tuple(app_config.hedge_readiness.display_horizons_days)
    default_horizon = 60 if 60 in target_horizons else target_horizons[0]
    horizon_raw = _query_value(query, "horizon")
    horizon = _parse_int(horizon_raw)
    if horizon not in target_horizons:
        if horizon_raw:
            notes.append(f"Invalid horizon; defaulted to {default_horizon}d.")
        horizon = default_horizon

    bucket_raw = _query_value(query, "bucket").lower().replace("-", "_")
    bucket = bucket_raw if bucket_raw in _allowed_buckets() else None
    if bucket_raw and bucket is None:
        notes.append("Invalid bucket; defaulted to the first available contract.")

    default_quantity = app_config.hedge_readiness.default_scenario_quantity
    mode_raw = _query_value(query, "size_mode").lower()
    size_mode: SizingMode = (
        cast(SizingMode, mode_raw)
        if mode_raw in {"contracts", "budget"}
        else "contracts"
    )
    if mode_raw and mode_raw not in {"contracts", "budget"}:
        notes.append("Invalid sizing mode; defaulted to contracts.")

    quantity_raw = _query_value(query, "quantity")
    quantity = _parse_int(quantity_raw)
    budget = _parse_float(_query_value(query, "budget"))
    if size_mode == "budget" and (budget is None or budget <= 0):
        notes.append("Invalid budget; defaulted to contract quantity mode.")
        size_mode = "contracts"
        budget = None
    if quantity is None or quantity <= 0:
        if size_mode == "contracts" and quantity_raw:
            notes.append(f"Invalid quantity; defaulted to {default_quantity}.")
        quantity = default_quantity

    return OptionSizingRequest(
        side=side,
        horizon_days=horizon,
        bucket=bucket,
        size_mode=size_mode,
        quantity=quantity,
        budget=budget,
        notes=tuple(notes),
    )


def _query_value(query: dict[str, list[str]], key: str) -> str:
    return str(query.get(key, [""])[0]).strip()


def _parse_int(raw: str) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_float(raw: str) -> float | None:
    cleaned = str(raw or "").replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _allowed_buckets() -> set[str]:
    return set(candidate_bucket_ids())


def load_option_trading_data(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
) -> OptionTradingData:
    """Load latest option-trading rows and reuse them until provenance changes."""

    manifest = _read_options_manifest(paths)
    tool_a = _read_optional_parquet(paths.latest_tool_a_snapshot_parquet_path)
    tool_b = _read_optional_parquet(paths.latest_tool_b_snapshot_parquet_path)
    if manifest is None:
        return _empty_data(
            tool_a=tool_a,
            tool_b=tool_b,
            reason="No options snapshot exists yet. Run `python main.py update-data` first.",
        )

    cache_key = _cache_key(manifest=manifest, tool_a=tool_a, tool_b=tool_b)
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    features = _load_features(paths=paths, manifest=manifest)
    chains = _load_chains(paths=paths, manifest=manifest)
    risk_free_rate = as_float(manifest.get("risk_free_rate"))
    risk_free_rate_is_fallback = risk_free_rate is None
    effective_risk_free_rate = risk_free_rate if risk_free_rate is not None else 0.0
    candidate_slots = _candidate_slots(
        app_config=app_config,
        features=features,
        tool_a=tool_a,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=effective_risk_free_rate,
        manifest=manifest,
        option_type="P",
        target_delta=app_config.hedge_readiness.target_delta,
    )
    call_candidate_slots = _candidate_slots(
        app_config=app_config,
        features=features,
        tool_a=tool_a,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=effective_risk_free_rate,
        manifest=manifest,
        option_type="C",
        target_delta=abs(app_config.hedge_readiness.target_delta),
    )
    candidate_grids = _accepted_candidate_grids(candidate_slots)
    call_candidate_grids = _accepted_candidate_grids(call_candidate_slots)
    source_context = _source_context(
        manifest=manifest,
        risk_free_rate=effective_risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )
    liquidity_measurements = _liquidity_measurements(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=effective_risk_free_rate,
        manifest=manifest,
    )
    overview = build_option_trading_overview(
        tool_a=tool_a,
        options_features=features,
        candidate_grids=candidate_grids,
        call_candidate_grids=call_candidate_grids,
        risk_free_rate=effective_risk_free_rate,
        target_horizons_days=tuple(app_config.hedge_readiness.display_horizons_days),
        down_beta_min_for_scenario=app_config.hedge_readiness.down_beta_min_for_scenario,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        source_context=source_context,
        liquidity_measurements=liquidity_measurements,
    )
    data = OptionTradingData(
        overview=overview,
        candidate_grids=candidate_grids,
        call_candidate_grids=call_candidate_grids,
        candidate_slots=candidate_slots,
        call_candidate_slots=call_candidate_slots,
        options_features=features,
        tool_a=tool_a,
        tool_b=tool_b,
        raw_options_by_ticker=chains,
        risk_free_rate=effective_risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        cache_key=cache_key,
    )
    _CACHE[cache_key] = data
    return data


def _empty_data(
    *,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    reason: str,
) -> OptionTradingData:
    return OptionTradingData(
        overview=OptionTradingOverviewData(rows=(), reason=reason),
        candidate_grids={},
        call_candidate_grids={},
        candidate_slots={},
        call_candidate_slots={},
        options_features=pd.DataFrame(),
        tool_a=tool_a,
        tool_b=tool_b,
        raw_options_by_ticker={},
        risk_free_rate=0.0,
        risk_free_rate_is_fallback=False,
        cache_key=None,
    )


def _read_options_manifest(paths: ProjectPaths) -> dict[str, Any] | None:
    if not paths.latest_options_manifest_path.exists():
        return None
    try:
        return json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def _cache_key(
    *,
    manifest: dict[str, Any],
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
) -> OptionTradingCacheKey:
    return OptionTradingCacheKey(
        options_refresh_run_id=str(manifest.get("refresh_run_id") or "unknown"),
        tool_a_refresh_run_ids=_unique_strings(tool_a, "snapshot_refresh_run_id"),
        tool_b_refresh_run_ids=_unique_strings(tool_b, "snapshot_refresh_run_id"),
    )


def _unique_strings(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    if frame.empty or column not in frame.columns:
        return ()
    values = {
        str(value).strip()
        for value in frame[column].dropna().unique()
        if str(value).strip() and str(value).strip().lower() != "nan"
    }
    return tuple(sorted(values))


def _load_chains(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    chains: dict[str, pd.DataFrame] = {}
    for item in manifest.get("snapshots", []):
        ticker = str(item.get("ticker", "")).strip().upper()
        if not ticker:
            continue
        snapshot_path = paths.resolve_repo_relative(str(item.get("snapshot_path", "")))
        chains[ticker] = _read_optional_parquet(snapshot_path)
    return chains


def _load_features(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> pd.DataFrame:
    rows: list[pd.Series] = []
    refresh_run_id = str(manifest.get("refresh_run_id") or "")
    for item in manifest.get("snapshots", []):
        ticker = str(item.get("ticker", "")).strip()
        if not ticker:
            continue
        feature_path = paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet"
        frame = _read_optional_parquet(feature_path)
        if frame.empty:
            continue
        if "run_id" in frame.columns and refresh_run_id:
            matching = frame[frame["run_id"].astype(str) == refresh_run_id]
            if not matching.empty:
                rows.append(matching.iloc[-1])
            continue
        # Legacy feature snapshots without run_id cannot be provenance-checked.
        # Use only the latest row so old local data still renders, but prefer
        # modern run_id-bearing snapshots for stale-data protection.
        rows.append(frame.iloc[-1])
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).reset_index(drop=True)
    if "ticker" in result.columns:
        result["ticker"] = result["ticker"].astype(str).str.upper()
    return result


def _candidate_slots(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
    manifest: dict[str, Any],
    option_type: Literal["P", "C"],
    target_delta: float,
) -> dict[str, list[OptionCandidateSlot]]:
    feature_by_ticker = rows_by_ticker_series(features, strip=True)
    tool_a_by_ticker = rows_by_ticker_series(tool_a, strip=True)
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


def _accepted_candidate_grids(
    slots_by_ticker: dict[str, list[OptionCandidateSlot]],
) -> dict[str, list[OptionCandidate]]:
    return {
        ticker: _unique_candidates(
            [slot.candidate for slot in slots if slot.candidate is not None]
        )
        for ticker, slots in slots_by_ticker.items()
    }


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


def _liquidity_measurements(
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


def _tier_count(rows: list[dict[str, float | str]], tier: str) -> int:
    return sum(1 for row in rows if row.get("liquidity_tier") == tier)


def _median(values: Iterable[float | str]) -> float | None:
    numeric = [
        value
        for value in (_safe_float(value) for value in values)
        if value is not None
    ]
    numeric.sort()
    if not numeric:
        return None
    midpoint = len(numeric) // 2
    if len(numeric) % 2:
        return numeric[midpoint]
    return (numeric[midpoint - 1] + numeric[midpoint]) / 2.0


def _safe_float(value: float | str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_context(
    *,
    manifest: dict[str, Any],
    risk_free_rate: float,
    risk_free_rate_is_fallback: bool,
) -> OptionTradingSourceContext:
    as_of_raw = str(manifest.get("as_of_date") or "").strip() or None
    refresh_raw = str(manifest.get("refresh_run_id") or "").strip() or None
    return OptionTradingSourceContext(
        as_of_date=as_of_raw,
        refresh_run_id=refresh_raw,
        risk_free_rate=risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )


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
