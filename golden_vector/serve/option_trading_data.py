"""Load and cache structured option-trading data for the workspace UI."""

from __future__ import annotations

from collections import OrderedDict

import logging
import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import pandas as pd

LOGGER = logging.getLogger(__name__)

from golden_vector.common.files import optional_sha256_file as _file_sha256
from golden_vector.common.files import sha256_file
from golden_vector.common.parquet import ParquetSchemaError, read_required_parquet
from golden_vector.common.strings import clean_string, normalize_ticker
from golden_vector.common.strings import unique_strings as _common_unique_strings
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    read_current_model_json,
    read_current_model_parquet,
    resolve_current_model_artifact_path,
    summarize_model_state_alignment,
    summarize_option_freshness,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.option_artifacts import (
    CHAIN_HISTORY_COLUMNS,
    CHAIN_HISTORY_SCHEMA_COLUMN,
    CHAIN_HISTORY_SCHEMA_VERSION,
    OPTION_AVAILABILITY_COLUMNS,
    OPTION_AVAILABILITY_SCHEMA_COLUMN,
    OPTION_AVAILABILITY_SCHEMA_VERSION,
    OPTION_TRADING_READ_SET,
    SUPPORTED_OPTION_SCHEMA_VERSIONS,
    normalized_option_schema_version,
)

# Artifacts the Option Trading screen actually renders. option_contract_metrics is
# build/diagnostic only (largest option parquet), so the UI verifies its presence +
# sha256 but never reads it into memory on a cache miss (audit M8).
_SERVE_RENDERED_OPTION_ARTIFACTS = frozenset(OPTION_TRADING_READ_SET) - {"option_contract_metrics"}
from golden_vector.screening.schema import validate_tool_b_output_schema
from golden_vector.hedge._helpers import as_float
from golden_vector.hedge.option_artifact_builder import build_option_source_context
from golden_vector.hedge.option_artifact_frames import (
    candidate_slots_from_frame,
    liquidity_measurements_from_frame,
    overview_rows_from_frame,
    selected_candidate_grids_from_frame,
)
from golden_vector.hedge.chain_history import (
    CAPTURE_QUALITY_COMPLETE,
    CAPTURE_QUALITY_PARTIAL,
    ROW_STATUS_OBSERVED,
)
from golden_vector.hedge.candidate_puts import (
    OptionCandidate,
    OptionCandidateSlot,
)
from golden_vector.hedge.option_availability import (
    AVAILABILITY_FETCH_FAILED,
    AVAILABILITY_FILTERED_WINDOW_EMPTY,
    AVAILABILITY_LISTED,
    AVAILABILITY_NONE_LISTED,
    AVAILABILITY_UNKNOWN,
    FETCH_STATUS_ABSENT,
    FETCH_STATUS_EMPTY,
    FETCH_STATUS_ERROR,
    FETCH_STATUS_SUCCESS,
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
    option_signal_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    option_skew_curve_points: pd.DataFrame = field(default_factory=pd.DataFrame)
    option_oi_strike_points: pd.DataFrame = field(default_factory=pd.DataFrame)
    option_signal_history_points: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: The RAW option_candidate_slots frame. The rebuilt ``OptionCandidateSlot``
    #: dataclasses drop the persisted greek columns (candidate_gamma / vega /
    #: theta / greeks_model_version), so the ticker page's greeks disclosure and
    #: sizing payload read them from here rather than recomputing anything.
    candidate_slots_frame: pd.DataFrame = field(default_factory=pd.DataFrame)


class OptionArtifactStaleSchemaError(ValueError):
    """Raised when persisted option artifacts are from an older schema."""


class OptionArtifactIntegrityError(ValueError):
    """Raised when a persisted option artifact fails its manifest sha256 check.

    Its own type (rather than a bare ValueError) so the loader can let it escape
    the friendly "could not be read" empty state: a file whose bytes disagree
    with the manifest is a corruption/tampering signal and must render loud,
    exactly like OptionArtifactStaleSchemaError does."""


# Bounded: keys change on every refresh, and each entry holds several MB of
# frames - an unbounded dict leaks one generation per refresh in a
# long-running server. 4 generations comfortably covers dial flips.
_CACHE: OrderedDict[OptionTradingCacheKey, OptionTradingData] = OrderedDict()
_CACHE_MAX_ENTRIES = 4


def clear_option_trading_cache() -> None:
    _CACHE.clear()
    # The ticker page's v4 readers cache off the same publish pointer; a test or
    # a refresh that resets one must reset both or the page serves the old
    # generation's availability against the new generation's candidates.
    _PAGE_CACHE.clear()


def build_option_trading_detail_data(
    data: OptionTradingData,
    *,
    ticker: str,
    app_config: AppConfig,
    sizing_request: OptionSizingRequest | None = None,
) -> OptionTradingDetailData:
    normalized = normalize_ticker(ticker) or ""
    overview_row = next(
        (row for row in data.overview.rows if row.ticker == normalized),
        None,
    )
    # "Most liquid" default (C4): when the user did not pick a horizon, the
    # backend-stamped per-ticker side-aware selection wins over the config
    # fallback. Serve never recomputes the choice — and never applies a
    # stamped horizon the UI cannot render (audit M4: stale artifacts or
    # extra config bands could stamp a non-displayable window).
    if (
        sizing_request is not None
        and not sizing_request.horizon_explicit
        and overview_row is not None
    ):
        stamped = (
            overview_row.most_liquid_put_horizon_days
            if sizing_request.side == "put"
            else overview_row.most_liquid_call_horizon_days
        )
        stamped_expiration = (
            overview_row.most_liquid_put_expiration
            if sizing_request.side == "put"
            else overview_row.most_liquid_call_expiration
        )
        if (
            stamped is not None
            and int(stamped) in app_config.hedge_readiness.display_horizons_days
        ):
            # The stamped expiry is the most-liquid rule's actual pick, which
            # can differ from the band-fit slot the matrix shows (audit M5);
            # the note keeps that visible. It also corrects any earlier
            # "defaulted to Xd" note (audit L3).
            note = f"Using the most-liquid window: {int(stamped)}d"
            if stamped_expiration:
                # The sized contract is the bucket-fit pick inside this
                # window, which can be a different expiry than the
                # most-liquid rule's own pick - say "window", never claim
                # the sized contract IS this expiry.
                note += f" (most-liquid expiry there: {stamped_expiration})"
            sizing_request = replace(
                sizing_request,
                horizon_days=int(stamped),
                notes=(*sizing_request.notes, f"{note}."),
            )
    # C5 bounded acceptance: the detail build recomputes scenario bundles for
    # ONE selected candidate from persisted data (no raw chain scans — a
    # guardrail test pins this). Timed so growth past "bounded" is visible.
    detail_started_at = perf_counter()
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
        # One config source for the put/call P&L ladders — same as the Hedge
        # Readiness + Speculation surfaces, so editing default_scenarios moves all
        # three together instead of leaving this page on a stale hardcoded ladder.
        put_gold_scenarios=tuple(app_config.hedge_readiness.default_scenarios),
    )
    LOGGER.debug(
        "option detail build for %s took %.3fs (request-time scenario compute "
        "is bounded to the selected candidate)",
        normalized,
        perf_counter() - detail_started_at,
    )
    detail = _with_proxy_fallbacks(
        data=data,
        detail=detail,
        app_config=app_config,
        request=sizing_request
        or OptionSizingRequest(
            horizon_days=app_config.hedge_readiness.option_signal_horizon_days
        ),
    )
    detail = _with_option_signal_payloads(data=data, detail=detail)
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
        signal_row=detail.signal_row,
        skew_curve_points=detail.skew_curve_points,
        oi_strike_points=detail.oi_strike_points,
        signal_history_points=detail.signal_history_points,
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
        normalized
        for ticker in app_config.hedge_readiness.benchmark_tickers
        for normalized in (normalize_ticker(ticker),)
        if normalized
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


def _with_option_signal_payloads(
    *,
    data: OptionTradingData,
    detail: OptionTradingDetailData,
) -> OptionTradingDetailData:
    ticker = normalize_ticker(detail.ticker) or ""
    return replace(
        detail,
        signal_row=_first_ticker_record(data.option_signal_summary, ticker),
        skew_curve_points=tuple(_ticker_records(data.option_skew_curve_points, ticker)),
        oi_strike_points=tuple(_ticker_records(data.option_oi_strike_points, ticker)),
        signal_history_points=tuple(
            _ticker_records(data.option_signal_history_points, ticker)
        ),
    )


def _first_ticker_record(frame: pd.DataFrame, ticker: str) -> dict[str, object] | None:
    rows = _ticker_records(frame, ticker)
    return rows[0] if rows else None


def _ticker_records(frame: pd.DataFrame, ticker: str) -> list[dict[str, object]]:
    if frame.empty or "ticker" not in frame.columns or not ticker:
        return []
    mask = frame["ticker"].astype(str).str.upper() == ticker.upper()
    return list(frame[mask].to_dict(orient="records"))


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
    # Bucket preference comes from the hedge layer's configured bucket order
    # (near_atm, directional today) rather than a hardcoded twin that would
    # drift the moment a bucket is added or reordered. The requested bucket
    # always wins. Deferred: relocating this selection into the hedge layer
    # itself, so serve stops choosing candidates at all.
    bucket_order = {str(requested_bucket or ""): 0}
    for index, bucket_id in enumerate(candidate_bucket_ids(), start=1):
        bucket_order.setdefault(str(bucket_id), index)
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
    signal_horizon = int(app_config.hedge_readiness.option_signal_horizon_days)
    default_horizon = (
        signal_horizon if signal_horizon in target_horizons else target_horizons[0]
    )
    horizon_raw = _query_value(query, "horizon")
    horizon = _parse_int(horizon_raw)
    horizon_explicit = horizon in target_horizons
    if not horizon_explicit:
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
    # The user touched a size control if any size param was present in the query.
    size_explicit = bool(mode_raw or quantity_raw or _query_value(query, "budget"))
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
        horizon_explicit=horizon_explicit,
        size_explicit=size_explicit,
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
        value = float(cleaned)
        # inf/nan pass `<= 0` guards (nan <= 0 is False) and crash the
        # sizing math downstream; treat them as unparseable input.
        return value if math.isfinite(value) else None
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
    tool_b = validate_tool_b_output_schema(
        tool_b,
        label="Option Trading Corporate Finance artifact",
    )
    try:
        artifact_frames = _read_option_artifact_frames(paths)
    except (OptionArtifactStaleSchemaError, OptionArtifactIntegrityError):
        raise
    except (OSError, ValueError) as exc:
        return _empty_data(
            tool_a=tool_a,
            tool_b=tool_b,
            reason=f"Option artifact snapshot could not be read: {exc}",
        )
    if artifact_frames is None:
        freshness = summarize_option_freshness(load_current_model_state_manifest(paths))
        reason = (
            str(freshness["message"])
            if freshness is not None and freshness["status"] == "UNAVAILABLE"
            else "No option artifact snapshot exists yet. Run `python main.py refresh` first."
        )
        return _empty_data(tool_a=tool_a, tool_b=tool_b, reason=reason)
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
    source_context = _with_model_state_alignment_warnings(
        source_context,
        model_state=load_current_model_state_manifest(paths),
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
    overview_frame = artifact_frames["option_trading_overview"]
    overview_rows = overview_rows_from_frame(overview_frame)
    overview = OptionTradingOverviewData(
        rows=overview_rows,
        reason=None if overview_rows else "No persisted option trading rows are available.",
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        source_context=source_context,
        liquidity_measurements=liquidity_measurements,
        group_default_put_horizon_days=_frame_first_int(
            overview_frame, "group_default_put_horizon_days"
        ),
        group_default_call_horizon_days=_frame_first_int(
            overview_frame, "group_default_call_horizon_days"
        ),
    )
    data = OptionTradingData(
        overview=overview,
        candidate_grids=put_candidates,
        call_candidate_grids=call_candidates,
        candidate_slots=put_slots,
        call_candidate_slots=call_slots,
        option_signal_summary=artifact_frames["option_signal_summary"],
        option_skew_curve_points=artifact_frames["option_skew_curve_points"],
        option_oi_strike_points=artifact_frames["option_oi_strike_points"],
        option_signal_history_points=artifact_frames["option_signal_history_points"],
        candidate_slots_frame=artifact_frames["option_candidate_slots"],
        options_features=artifact_frames["candidate_finder_inputs"],
        tool_a=tool_a,
        tool_b=tool_b,
        raw_options_by_ticker={},
        risk_free_rate=risk_free_rate,
        risk_free_rate_is_fallback=risk_free_rate_is_fallback,
        cache_key=cache_key,
    )
    _CACHE[cache_key] = data
    while len(_CACHE) > _CACHE_MAX_ENTRIES:
        _CACHE.popitem(last=False)
    return data


# --- page-side v4 artifact readers (plan §6.4 / §8) -------------------------
# option_chain_history_daily and option_availability are deliberately OUTSIDE
# OPTION_TRADING_READ_SET: the Option Trading overview never reads them, so they
# get their own readers here (P11's loader-inventory gap). Everything below
# resolves through the model-state manifest exactly like its siblings — never a
# raw path — and a v3 generation resolves to UNAVAILABLE_PRE_V4 rather than an
# error or a claim that the ticker has no options.

OPTION_PAGE_OK = "OK"
OPTION_PAGE_UNAVAILABLE_PRE_V4 = "UNAVAILABLE_PRE_V4"
OPTION_PAGE_MISSING = "MISSING"
OPTION_PAGE_UNREADABLE = "UNREADABLE"

_PAGE_ARTIFACT_NAMES: tuple[str, ...] = (
    "option_availability",
    "option_chain_history_daily",
)

_PAGE_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "option_availability": (
        *OPTION_AVAILABILITY_COLUMNS,
        OPTION_AVAILABILITY_SCHEMA_COLUMN,
    ),
    "option_chain_history_daily": (
        *CHAIN_HISTORY_COLUMNS,
        CHAIN_HISTORY_SCHEMA_COLUMN,
    ),
}
_V4_AVAILABILITY_COLUMNS: tuple[str, ...] = (
    "ticker",
    "availability_status",
    "expirations_enumerated",
    "fetch_status",
    "fetch_message",
    "provider",
    "capture_date",
    "schema_version",
)
_AVAILABILITY_STATUSES = frozenset(
    {
        AVAILABILITY_LISTED,
        AVAILABILITY_NONE_LISTED,
        AVAILABILITY_FETCH_FAILED,
        AVAILABILITY_FILTERED_WINDOW_EMPTY,
        AVAILABILITY_UNKNOWN,
    }
)
_FETCH_STATUSES = frozenset(
    {
        FETCH_STATUS_SUCCESS,
        FETCH_STATUS_EMPTY,
        FETCH_STATUS_ERROR,
        FETCH_STATUS_ABSENT,
    }
)
_CHAIN_ROW_STATUSES = frozenset({ROW_STATUS_OBSERVED})


@dataclass(frozen=True)
class OptionPageArtifacts:
    """The two page-only v4 artifacts plus the state that produced them."""

    state: str
    reason: str | None = None
    generation_schema_version: int | None = None
    availability: pd.DataFrame = field(default_factory=pd.DataFrame)
    chain_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: Generation-level freshness, shared with every other option surface.
    freshness_status: str | None = None
    freshness_as_of_date: str | None = None
    freshness_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == OPTION_PAGE_OK


# Bounded like the main option cache: the key is the model-state manifest hash,
# which changes on every publish, so an unbounded dict would leak a generation
# per refresh in a long-running server.
_PAGE_CACHE: OrderedDict[str, OptionPageArtifacts] = OrderedDict()
_PAGE_CACHE_MAX_ENTRIES = 4


def load_option_page_artifacts(paths: ProjectPaths) -> OptionPageArtifacts:
    """Read the ticker page's two v4-only option artifacts.

    Never raises for a missing/old/corrupt artifact: the page must degrade with a
    reason, and "the file is not there" must never be rendered as "this company
    has no listed options" (plan §8).
    """

    cache_key = _file_sha256(paths.latest_model_state_manifest_path) or ""
    cached = _PAGE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result = _read_option_page_artifacts(paths)
    # A read/IO failure can be transient while the immutable pointer is
    # unchanged. Never pin that failure in the process cache forever; the next
    # request gets one chance to recover. Stable states remain generation-keyed.
    if result.state != OPTION_PAGE_UNREADABLE:
        _PAGE_CACHE[cache_key] = result
        while len(_PAGE_CACHE) > _PAGE_CACHE_MAX_ENTRIES:
            _PAGE_CACHE.popitem(last=False)
    return result


def _read_option_page_artifacts(paths: ProjectPaths) -> OptionPageArtifacts:
    model_state = load_current_model_state_manifest(paths)
    freshness = summarize_option_freshness(model_state)
    freshness_status = (
        str(freshness.get("status") or "").strip().upper() if freshness else None
    )
    freshness_as_of = str(freshness.get("as_of_date") or "") or None if freshness else None
    freshness_message = str(freshness.get("message") or "") or None if freshness else None

    def _degraded(state: str, reason: str, version: int | None = None) -> OptionPageArtifacts:
        return OptionPageArtifacts(
            state=state,
            reason=reason,
            generation_schema_version=version,
            freshness_status=freshness_status,
            freshness_as_of_date=freshness_as_of,
            freshness_message=freshness_message,
        )

    if not _model_state_has_option_artifacts(model_state):
        return _degraded(
            OPTION_PAGE_MISSING,
            "No option artifacts have been published yet. Run "
            "`python main.py refresh` to build them.",
        )
    generation_version = _generation_option_schema_version(paths, model_state)
    if generation_version is not None and generation_version < 4:
        return _degraded(
            OPTION_PAGE_UNAVAILABLE_PRE_V4,
            "awaiting first v4 refresh",
            generation_version,
        )

    frames: dict[str, pd.DataFrame] = {}
    for name in _PAGE_ARTIFACT_NAMES:
        path = resolve_current_model_artifact_path(paths, name)
        if path is None:
            # The generation stamps v4 (or its version is unknown) yet a v4-only
            # artifact is absent from the manifest: a real gap, not "no options".
            if generation_version is None:
                return _degraded(
                    OPTION_PAGE_UNAVAILABLE_PRE_V4,
                    "awaiting first v4 refresh",
                    generation_version,
                )
            return _degraded(
                OPTION_PAGE_MISSING,
                f"the {name} artifact is missing from the current model state",
                generation_version,
            )
        try:
            _verify_artifact_sha256(model_state=model_state, name=name, path=path)
            frame = read_required_parquet(
                path,
                label=f"Option artifact {name}",
                required_columns=_page_required_columns(
                    name=name,
                    generation_version=generation_version,
                ),
            )
            _validate_option_page_artifact(
                frame,
                name=name,
                generation_version=generation_version,
            )
        except (OptionArtifactIntegrityError, ParquetSchemaError, OSError, ValueError) as exc:
            return _degraded(
                OPTION_PAGE_UNREADABLE,
                f"the {name} artifact could not be read ({exc})",
                generation_version,
            )
        frames[name] = frame
    return OptionPageArtifacts(
        state=OPTION_PAGE_OK,
        reason=None,
        generation_schema_version=generation_version,
        availability=frames["option_availability"],
        chain_history=frames["option_chain_history_daily"],
        freshness_status=freshness_status,
        freshness_as_of_date=freshness_as_of,
        freshness_message=freshness_message,
    )


def _page_required_columns(
    *,
    name: str,
    generation_version: int | None,
) -> tuple[str, ...]:
    if name == "option_availability" and generation_version == 4:
        return (*_V4_AVAILABILITY_COLUMNS, OPTION_AVAILABILITY_SCHEMA_COLUMN)
    return _PAGE_REQUIRED_COLUMNS[name]


def _validate_option_page_artifact(
    frame: pd.DataFrame,
    *,
    name: str,
    generation_version: int | None,
) -> None:
    """Validate the page-only v4 contract before any row can affect the UI.

    In particular, ``NONE_LISTED`` is allowed to hide the Options section, so a
    checksum-valid file is not enough: its full columns, set/own versions, keys,
    and enums must all be valid first.
    """

    _require_supported_option_schema(frame, name=name)
    if generation_version is not None:
        _require_exact_version(
            frame,
            column="schema_version",
            expected=generation_version,
            name=name,
        )

    tickers = frame["ticker"].map(normalize_ticker)
    if tickers.isna().any():
        raise ParquetSchemaError(f"Option artifact {name}: ticker contains missing values")

    if name == "option_availability":
        _require_exact_version(
            frame,
            column=OPTION_AVAILABILITY_SCHEMA_COLUMN,
            expected=(1 if generation_version == 4 else OPTION_AVAILABILITY_SCHEMA_VERSION),
            name=name,
        )
        if tickers.duplicated(keep=False).any():
            raise ParquetSchemaError(
                f"Option artifact {name}: duplicate ticker rows are not allowed"
            )
        _require_enum(
            frame,
            column="availability_status",
            allowed=_AVAILABILITY_STATUSES,
            name=name,
            upper=False,
        )
        _require_enum(
            frame,
            column="fetch_status",
            allowed=_FETCH_STATUSES,
            name=name,
            upper=False,
        )
        return

    if name != "option_chain_history_daily":
        raise ParquetSchemaError(f"Unsupported option page artifact: {name}")
    _require_exact_version(
        frame,
        column=CHAIN_HISTORY_SCHEMA_COLUMN,
        expected=CHAIN_HISTORY_SCHEMA_VERSION,
        name=name,
    )
    dates = frame["as_of_date"].map(clean_string)
    if dates.isna().any():
        raise ParquetSchemaError(
            f"Option artifact {name}: as_of_date contains missing values"
        )
    keys = pd.DataFrame({"ticker": tickers, "as_of_date": dates})
    if keys.duplicated(keep=False).any():
        raise ParquetSchemaError(
            f"Option artifact {name}: duplicate ticker/as_of_date rows are not allowed"
        )
    _require_enum(
        frame,
        column="row_status",
        allowed=_CHAIN_ROW_STATUSES,
        name=name,
        upper=False,
    )
    qualities = frame["capture_quality"].map(clean_string)
    invalid_quality = qualities.map(
        lambda value: not (
            value == CAPTURE_QUALITY_COMPLETE
            or (value or "").startswith(f"{CAPTURE_QUALITY_PARTIAL}:")
        )
    )
    if invalid_quality.any():
        found = sorted({value or "missing" for value in qualities[invalid_quality]})
        raise ParquetSchemaError(
            f"Option artifact {name}: capture_quality contains invalid value(s): "
            + ", ".join(found)
        )


def _require_exact_version(
    frame: pd.DataFrame,
    *,
    column: str,
    expected: int,
    name: str,
) -> None:
    """Require one exact row-level version; an empty typed artifact is valid."""

    if frame.empty:
        return
    missing_version = frame[column].isna().any()
    versions = {
        normalized_option_schema_version(value)
        for value in frame[column].dropna().unique()
    }
    if missing_version or versions != {expected}:
        found = ", ".join(sorted(str(value) for value in versions if value is not None))
        raise ParquetSchemaError(
            f"Option artifact {name}: {column} expected {expected}, got "
            f"{found or 'missing'}"
        )


def _require_enum(
    frame: pd.DataFrame,
    *,
    column: str,
    allowed: frozenset[str],
    name: str,
    upper: bool = True,
) -> None:
    values = frame[column].map(clean_string)
    normalized = values.map(
        lambda value: value.upper() if upper and value is not None else value
    )
    invalid = normalized.isna() | ~normalized.isin(allowed)
    if invalid.any():
        found = sorted({value or "missing" for value in normalized[invalid]})
        raise ParquetSchemaError(
            f"Option artifact {name}: {column} contains invalid value(s): "
            + ", ".join(found)
        )


def _generation_option_schema_version(
    paths: ProjectPaths,
    model_state: dict[str, Any] | None,
) -> int | None:
    """The schema version the CURRENT generation stamped on its option set.

    Read from an artifact present in every supported set, so a v3 generation is
    identified without depending on the v4-only files it does not have.
    """

    path = resolve_current_model_artifact_path(paths, "option_candidate_slots")
    if path is None:
        return None
    try:
        frame = read_required_parquet(
            path,
            label="Option artifact option_candidate_slots",
            required_columns=("schema_version",),
        )
    except (ParquetSchemaError, OSError, ValueError):
        return None
    versions = {
        normalized_option_schema_version(value)
        for value in frame["schema_version"].dropna().unique()
    } - {None}
    if len(versions) != 1:
        return None
    return int(next(iter(versions)))


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
        option_signal_summary=pd.DataFrame(),
        option_skew_curve_points=pd.DataFrame(),
        option_oi_strike_points=pd.DataFrame(),
        option_signal_history_points=pd.DataFrame(),
        options_features=pd.DataFrame(),
        tool_a=tool_a,
        tool_b=tool_b,
        raw_options_by_ticker={},
        risk_free_rate=0.0,
        risk_free_rate_is_fallback=False,
        cache_key=None,
    )


def _read_option_artifact_frames(paths: ProjectPaths) -> dict[str, pd.DataFrame] | None:
    model_state = load_current_model_state_manifest(paths)
    freshness = summarize_option_freshness(model_state)
    if freshness is not None and freshness["status"] == "UNAVAILABLE":
        # The manifest explicitly declared the option domain unavailable (no
        # verified prior snapshot). That is a calm empty state, not the
        # stale-schema error path below.
        return None
    frames: dict[str, pd.DataFrame] = {}
    # The Option Trading overview reads the v3 TEN in every supported generation:
    # the two v4 additions are page-side artifacts with their own readers. The
    # schema gate is set-aware, so a carried-forward v3 generation and a fresh v4
    # generation both serve identically (legacy reader window, plan §6.4).
    for name in OPTION_TRADING_READ_SET:
        path = resolve_current_model_artifact_path(paths, name)
        if path is None:
            if _model_state_has_option_artifacts(model_state):
                raise OptionArtifactStaleSchemaError(
                    "Option Trading data is from the previous version. "
                    "Run python main.py refresh to rebuild the option artifacts. "
                    f"Details: missing required option artifact {name} in the current model-state manifest."
                )
            return None
        _verify_artifact_sha256(model_state=model_state, name=name, path=path)
        if name not in _SERVE_RENDERED_OPTION_ARTIFACTS:
            # option_contract_metrics is build/diagnostic only -- its presence and
            # sha256 are verified above, but it is never rendered, so don't read the
            # largest option parquet into memory on a UI cache miss. (audit M8)
            continue
        try:
            frame = read_required_parquet(
                path,
                label=f"Option artifact {name}",
                required_columns=("schema_version", "source_run_id"),
            )
            _require_supported_option_schema(frame, name=name)
            frames[name] = frame
        except ParquetSchemaError as exc:
            raise OptionArtifactStaleSchemaError(
                "Option Trading data is from the previous version. "
                "Run python main.py refresh to rebuild the option artifacts. "
                f"Details: {exc}"
            ) from exc
    return frames


def _require_supported_option_schema(frame: pd.DataFrame, *, name: str) -> None:
    """Fail loud unless the artifact carries ONE supported option schema version."""

    # Reconciliation first (restores what the old `schema_version=` checked-read
    # path did): the parquet FILE metadata is written at publish time and cannot
    # be edited by a column rewrite, so a column that disagrees with it means the
    # file is not what it claims to be. Membership in the supported set is only
    # meaningful once the two agree.
    # frame.attrs carries the file-level parquet key/value metadata, populated by
    # read_required_parquet via parquet_context_metadata.
    metadata_versions = {
        normalized_option_schema_version(value)
        for value in ([frame.attrs.get("schema_version")] if frame.attrs.get("schema_version") is not None else [])
    } - {None}
    column_versions = {
        normalized_option_schema_version(value)
        for value in frame["schema_version"].dropna().unique()
    }
    if metadata_versions and not (column_versions <= metadata_versions):
        raise ParquetSchemaError(
            f"Option artifact {name}: schema_version column "
            f"({', '.join(sorted(str(version) for version in column_versions)) or 'missing'}) "
            "disagrees with the parquet file metadata "
            f"({', '.join(sorted(str(version) for version in metadata_versions))})"
        )
    versions = column_versions or metadata_versions
    if len(versions) == 1 and versions <= set(SUPPORTED_OPTION_SCHEMA_VERSIONS):
        return
    found = ", ".join(sorted(str(version) for version in versions)) or "missing"
    raise ParquetSchemaError(
        f"Option artifact {name}: schema_version expected one of "
        f"{', '.join(str(version) for version in SUPPORTED_OPTION_SCHEMA_VERSIONS)}, "
        f"got {found}"
    )


def _model_state_has_option_artifacts(model_state: dict[str, Any] | None) -> bool:
    artifacts = model_state.get("artifacts") if isinstance(model_state, dict) else None
    if not isinstance(artifacts, dict):
        return False
    return any(
        str(name).startswith("option_") or str(name) == "candidate_finder_inputs"
        for name in artifacts
    )


# Stat-gated verification memo (deep-review perf): the biggest option parquet
# was re-hashed on EVERY request. Published artifacts are immutable run-stamped
# files, so once a given (path, mtime_ns, size) has hashed to the expected
# value it cannot change without the stat changing; a mismatching or unstatable
# file is never memoized, so corruption is re-checked every time.
_VERIFIED_SHA_STATS: dict[tuple[str, int, int], str] = {}
_VERIFIED_SHA_STATS_MAX = 64


def _verify_artifact_sha256(
    *,
    model_state: dict[str, Any] | None,
    name: str,
    path: Path,
) -> None:
    artifacts = model_state.get("artifacts") if isinstance(model_state, dict) else None
    artifact = artifacts.get(name) if isinstance(artifacts, dict) else None
    if not isinstance(artifact, dict):
        return
    expected = str(artifact.get("sha256") or "").strip()
    if not expected:
        return
    stat_key: tuple[str, int, int] | None = None
    try:
        stat_result = os.stat(path)
        stat_key = (str(path), stat_result.st_mtime_ns, stat_result.st_size)
    except OSError:
        stat_key = None
    if stat_key is not None and _VERIFIED_SHA_STATS.get(stat_key) == expected:
        return
    actual = sha256_file(path)
    if actual != expected:
        display_path = str(artifact.get("path") or path)
        raise OptionArtifactIntegrityError(
            f"Option artifact {name} sha256 mismatch at {display_path}: "
            f"expected {expected}, got {actual}."
        )
    if stat_key is not None:
        if len(_VERIFIED_SHA_STATS) >= _VERIFIED_SHA_STATS_MAX:
            _VERIFIED_SHA_STATS.clear()
        _VERIFIED_SHA_STATS[stat_key] = expected


def _frame_first_int(frame: pd.DataFrame, column: str) -> int | None:
    if column not in frame.columns or frame.empty:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return int(values.iloc[0]) if not values.empty else None


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


def _with_model_state_alignment_warnings(
    context: OptionTradingSourceContext,
    *,
    model_state: dict[str, Any] | None,
) -> OptionTradingSourceContext:
    alignment = summarize_model_state_alignment(model_state)
    if alignment is None or alignment.get("status") == "OK":
        return context
    warnings = _dedupe_context_warnings(
        [
            *(
                str(message)
                for message in alignment.get("warnings", ())
                if str(message).strip()
            ),
            *context.context_warnings,
        ]
    )
    return replace(context, context_warnings=tuple(warnings))


def _dedupe_context_warnings(values: list[str]) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        warnings.append(text)
    return warnings


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
