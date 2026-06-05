"""Load and cache structured option-trading data for the workspace UI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, cast

import pandas as pd

from golden_vector.common.files import optional_sha256_file as _file_sha256
from golden_vector.common.parquet import read_optional_parquet
from golden_vector.common.strings import unique_strings as _common_unique_strings
from golden_vector.app.model_state import (
    read_current_model_json,
    read_current_model_parquet,
    resolve_current_model_artifact_path,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.option_artifacts import OPTION_ARTIFACT_NAMES
from golden_vector.hedge._helpers import as_float
from golden_vector.hedge.option_artifact_builder import build_option_source_context
from golden_vector.hedge.option_artifact_frames import (
    candidate_slots_from_frame,
    liquidity_measurements_from_frame,
    overview_rows_from_frame,
    selected_candidate_grids_from_frame,
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
)
from golden_vector.hedge.options_liquidity import (
    candidate_bucket_ids,
)


@dataclass(frozen=True)
class OptionTradingCacheKey:
    options_refresh_run_id: str
    tool_a_refresh_run_ids: tuple[str, ...]
    tool_b_refresh_run_ids: tuple[str, ...]
    model_state_manifest_hash: str | None


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
            "chains are not measured, or the cached benchmark ETF contracts did "
            "not pass the Tradable gate."
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
    if benchmark is None or benchmark.tradable_count < 1:
        return False
    return True


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

    artifact_frames = _read_option_artifact_frames(paths)
    tool_a = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    tool_b = read_current_model_parquet(
        paths,
        "tool_b",
        fallback_path=paths.latest_tool_b_snapshot_parquet_path,
    )
    if artifact_frames is None:
        return _empty_data(
            tool_a=tool_a,
            tool_b=tool_b,
            reason="No option artifact snapshot exists yet. Run `python main.py refresh` first.",
        )
    manifest = (
        read_current_model_json(
            paths,
            "options",
            fallback_path=paths.latest_options_manifest_path,
        )
        or {}
    )

    cache_key = _cache_key(
        manifest=manifest,
        tool_a=tool_a,
        tool_b=tool_b,
        model_state_manifest_hash=_file_sha256(paths.latest_model_state_manifest_path),
    )
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    risk_free_rate = _artifact_context_float(
        artifact_frames["option_candidate_slots"],
        "risk_free_rate",
    )
    risk_free_rate_is_fallback = _artifact_context_bool(
        artifact_frames["option_candidate_slots"],
        "risk_free_rate_is_fallback",
    )
    source_context = build_option_source_context(
        manifest=manifest,
        tool_a=tool_a,
        tool_b=tool_b,
        risk_free_rate=risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
    )
    put_slots, call_slots = candidate_slots_from_frame(
        artifact_frames["option_candidate_slots"]
    )
    put_candidates, call_candidates = selected_candidate_grids_from_frame(
        artifact_frames["option_selected_candidates"]
    )
    liquidity_measurements = liquidity_measurements_from_frame(
        artifact_frames["option_liquidity_measurements"]
    )
    overview_rows = overview_rows_from_frame(artifact_frames["option_trading_overview"])
    overview = OptionTradingOverviewData(
        rows=overview_rows,
        reason=None if overview_rows else "No persisted option trading rows are available.",
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        source_context=source_context,
        liquidity_measurements=liquidity_measurements,
    )
    data = OptionTradingData(
        overview=overview,
        candidate_grids=put_candidates,
        call_candidate_grids=call_candidates,
        candidate_slots=put_slots,
        call_candidate_slots=call_slots,
        options_features=artifact_frames["candidate_finder_inputs"],
        tool_a=tool_a,
        tool_b=tool_b,
        raw_options_by_ticker={},
        risk_free_rate=risk_free_rate,
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


def _read_option_artifact_frames(paths: ProjectPaths) -> dict[str, pd.DataFrame] | None:
    frames: dict[str, pd.DataFrame] = {}
    for name in OPTION_ARTIFACT_NAMES:
        path = resolve_current_model_artifact_path(paths, name)
        if path is None:
            return None
        frames[name] = read_optional_parquet(path)
    return frames


def _artifact_context_float(frame: pd.DataFrame, key: str) -> float:
    value = _artifact_context_value(frame, key)
    return as_float(value) or 0.0


def _artifact_context_bool(frame: pd.DataFrame, key: str) -> bool:
    value = _artifact_context_value(frame, key)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _artifact_context_value(frame: pd.DataFrame, key: str) -> object:
    if key in frame.attrs:
        return frame.attrs.get(key)
    if key not in frame.columns or frame.empty:
        return None
    values = frame[key].dropna()
    if values.empty:
        return None
    return values.iloc[0]


def _cache_key(
    *,
    manifest: dict[str, Any],
    tool_a: pd.DataFrame,
    tool_b: pd.DataFrame,
    model_state_manifest_hash: str | None,
) -> OptionTradingCacheKey:
    return OptionTradingCacheKey(
        options_refresh_run_id=str(manifest.get("refresh_run_id") or "unknown"),
        tool_a_refresh_run_ids=_unique_strings(tool_a, "snapshot_refresh_run_id"),
        tool_b_refresh_run_ids=_unique_strings(tool_b, "snapshot_refresh_run_id"),
        model_state_manifest_hash=model_state_manifest_hash,
    )


def _unique_strings(frame: pd.DataFrame, column: str) -> tuple[str, ...]:
    return tuple(_common_unique_strings(frame, column))
