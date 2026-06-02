"""Load and cache structured option-trading data for the workspace UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
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
from golden_vector.hedge.candidate_puts import OptionCandidate, build_candidate_grid
from golden_vector.hedge.option_trading import (
    OptionSide,
    OptionSizingRequest,
    OptionTradingDetailData,
    OptionTradingOverviewData,
    SizingMode,
    build_option_trading_detail,
    build_option_trading_overview,
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
        sizing_request=sizing_request,
        overview_row=overview_row,
        risk_free_rate=data.risk_free_rate,
        risk_free_rate_is_fallback=data.risk_free_rate_is_fallback,
        target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
        down_beta_min_for_scenario=(
            app_config.hedge_readiness.down_beta_min_for_scenario
        ),
    )
    if detail.row is not None or not data.overview.reason:
        return detail
    return OptionTradingDetailData(
        ticker=detail.ticker,
        row=detail.row,
        put_candidates=detail.put_candidates,
        put_bundles=detail.put_bundles,
        call_candidates=detail.call_candidates,
        call_bundles=detail.call_bundles,
        sizing=detail.sizing,
        reason=data.overview.reason,
        risk_free_rate_is_fallback=detail.risk_free_rate_is_fallback,
    )


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

    target_horizons = tuple(app_config.hedge_readiness.target_horizons_days)
    default_horizon = 60 if 60 in target_horizons else target_horizons[0]
    horizon_raw = _query_value(query, "horizon")
    horizon = _parse_int(horizon_raw)
    if horizon not in target_horizons:
        if horizon_raw:
            notes.append(f"Invalid horizon; defaulted to {default_horizon}d.")
        horizon = default_horizon

    default_quantity = app_config.hedge_readiness.default_scenario_quantity
    mode_raw = _query_value(query, "size_mode").lower()
    size_mode: SizingMode = (
        cast(SizingMode, mode_raw)
        if mode_raw in {"contracts", "budget"}
        else "contracts"
    )
    if mode_raw and mode_raw not in {"contracts", "budget"}:
        notes.append("Invalid sizing mode; defaulted to contracts.")

    quantity = _parse_int(_query_value(query, "quantity"))
    if quantity is None or quantity <= 0:
        if _query_value(query, "quantity"):
            notes.append(f"Invalid quantity; defaulted to {default_quantity}.")
        quantity = default_quantity

    budget = _parse_float(_query_value(query, "budget"))
    if size_mode == "budget" and (budget is None or budget <= 0):
        notes.append("Invalid budget; defaulted to contract quantity mode.")
        size_mode = "contracts"
        budget = None

    return OptionSizingRequest(
        side=side,
        horizon_days=horizon,
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
    candidate_grids = _candidate_grids(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=effective_risk_free_rate,
        manifest=manifest,
        option_type="P",
        target_delta=app_config.hedge_readiness.target_delta,
    )
    call_candidate_grids = _candidate_grids(
        app_config=app_config,
        features=features,
        tool_b=tool_b,
        chains=chains,
        risk_free_rate=effective_risk_free_rate,
        manifest=manifest,
        option_type="C",
        target_delta=abs(app_config.hedge_readiness.target_delta),
    )
    overview = build_option_trading_overview(
        tool_a=tool_a,
        options_features=features,
        candidate_grids=candidate_grids,
        call_candidate_grids=call_candidate_grids,
        risk_free_rate=effective_risk_free_rate,
        target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
        down_beta_min_for_scenario=app_config.hedge_readiness.down_beta_min_for_scenario,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )
    data = OptionTradingData(
        overview=overview,
        candidate_grids=candidate_grids,
        call_candidate_grids=call_candidate_grids,
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


def _candidate_grids(
    *,
    app_config: AppConfig,
    features: pd.DataFrame,
    tool_b: pd.DataFrame,
    chains: dict[str, pd.DataFrame],
    risk_free_rate: float,
    manifest: dict[str, Any],
    option_type: Literal["P", "C"],
    target_delta: float,
) -> dict[str, list[OptionCandidate]]:
    feature_by_ticker = rows_by_ticker_series(features, strip=True)
    tool_b_by_ticker = rows_by_ticker_series(tool_b, strip=True)
    as_of_date = _manifest_as_of_date(manifest)
    grids: dict[str, list[OptionCandidate]] = {}
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
            grids[ticker] = []
            continue
        grids[ticker] = build_candidate_grid(
            option_type=option_type,
            ticker=ticker,
            chain=chain,
            underlying_price=price,
            risk_free_rate=risk_free_rate,
            target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
            target_delta=target_delta,
            max_spread_pct=app_config.hedge_readiness.candidate_max_spread_pct,
            min_open_interest=app_config.hedge_readiness.candidate_min_open_interest,
            min_volume=app_config.hedge_readiness.candidate_min_volume,
            min_implied_volatility=(
                app_config.hedge_readiness.candidate_min_implied_volatility
            ),
            max_implied_volatility=(
                app_config.hedge_readiness.candidate_max_implied_volatility
            ),
            as_of_date=as_of_date,
        )
    return grids


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
