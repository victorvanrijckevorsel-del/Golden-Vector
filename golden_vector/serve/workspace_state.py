"""Workspace state objects, loaders, and route parsing helpers."""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    read_current_model_json,
    read_current_model_parquet,
    resolve_current_foundation_manifest_path,
    resolve_current_model_artifact_path,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.frames import select_finance_source_rows
from golden_vector.common.parquet import read_optional_parquet
from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.tool_d import (
    TOOL_D_SCHEMA_VERSION,
    YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
)
from golden_vector.features.horizons import build_core_horizons
from golden_vector.features.returns import compute_horizon_returns_for_ticker
from golden_vector.model.benchmark_comparison import (
    BetaUniverseComparison,
    resolve_beta_universe_comparisons_by_window,
)
from golden_vector.model.structural import (
    build_rebased_comparison_series,
    build_structural_weekly_series,
)
from golden_vector.common.windows import ALL_WINDOWS, window_weeks
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.schema import validate_tool_b_output_schema


@dataclass(frozen=True)
class WorkspaceState:
    tool_b_tickers: list[str]
    foundation_manifest: dict[str, Any] | None
    company_inputs: pd.DataFrame
    source_verification: pd.DataFrame
    reporting_calendar: pd.DataFrame
    stock_notes: pd.DataFrame
    latest_tool_a: pd.DataFrame
    latest_tool_b: pd.DataFrame
    latest_tool_c: pd.DataFrame
    latest_tool_d: pd.DataFrame
    tool_a_alias_present: bool
    tool_b_alias_present: bool
    tool_c_alias_present: bool
    tool_d_alias_present: bool
    model_state_manifest: dict[str, Any] | None
    # GDX/GDXJ per-window betas (the tiny 2-row benchmark file) for overview reference rows.
    latest_benchmark_betas: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass(frozen=True)
class ToolDSourceSelection:
    """Exact-source Tool D rows plus an honest reason when none are usable."""

    frame: pd.DataFrame
    reason: str | None = None


def select_tool_d_source_rows(
    frame: pd.DataFrame,
    *,
    finance_source: str,
    label: str,
    ticker: str | None = None,
) -> ToolDSourceSelection:
    """Select one Tool D finance source, optionally narrowed to one ticker.

    A pre-v4 artifact already labels its rows ``our`` but cannot contain Yahoo
    rows. That migration state gets the contract-owned rebuild reason; every
    other missing key gets a source-specific absence reason. No caller may
    borrow the alternate source to make an empty selection look complete.
    """

    normalized_source = str(finance_source).strip().lower()
    # Keep the same fail-loud request contract as the shared selector even
    # when schema metadata is malformed; invalid caller input is not a
    # data-degradation state. The empty probe validates without inspecting
    # stored rows before their schema generation is known.
    select_finance_source_rows(
        frame.iloc[0:0].copy(),
        finance_source=finance_source,
        label=label,
    )
    schema_state = _tool_d_schema_state(frame)
    if schema_state == "malformed":
        return ToolDSourceSelection(
            frame=frame.iloc[0:0].copy(),
            reason=(
                "Corporate Resilience artifact has malformed Tool D schema-version "
                "metadata; selected-source data is unavailable."
            ),
        )

    # Legacy v3 is an explicitly Our-View-only compatibility state. Validate
    # every stored source before deciding whether Yahoo needs a rebuild so a
    # malformed v3 Yahoo row can never be served as if it were legitimate.
    selection_source = normalized_source
    if schema_state == "legacy_our":
        legacy_our = select_finance_source_rows(
            frame,
            finance_source="our",
            label=label,
        )
        if len(legacy_our.index) != len(frame.index):
            return ToolDSourceSelection(
                frame=frame.iloc[0:0].copy(),
                reason=(
                    "Corporate Resilience legacy Tool D artifact contains a non-Our-View "
                    "source; selected-source data is unavailable."
                ),
            )
        if normalized_source == "yahoo":
            return ToolDSourceSelection(
                frame=frame.iloc[0:0].copy(),
                reason=YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
            )
        selection_source = "our"

    selected = select_finance_source_rows(
        frame,
        finance_source=selection_source,
        label=label,
    )
    if "ticker" in selected.columns:
        selected_tickers = selected["ticker"].astype(str).str.strip().str.upper()
        duplicate_tickers = selected_tickers.loc[
            selected_tickers.ne("") & selected_tickers.duplicated(keep=False)
        ]
        if not duplicate_tickers.empty:
            sample = ", ".join(sorted(set(duplicate_tickers.tolist()))[:5])
            raise ValueError(
                f"{label} has duplicate persisted (ticker, finance_source) rows "
                f"for {finance_source!r} (e.g. {sample}); refusing row-order selection."
            )
    normalized_ticker = str(ticker or "").strip().upper()
    if normalized_ticker:
        if "ticker" not in selected.columns and not selected.empty:
            raise ValueError(f"{label} has rows but no 'ticker' column.")
        if "ticker" in selected.columns:
            selected = selected.loc[
                selected["ticker"].astype(str).str.strip().str.upper().eq(normalized_ticker)
            ].copy()
    if not selected.empty:
        return ToolDSourceSelection(frame=selected)

    source_label = "Yahoo Fundamentals" if normalized_source == "yahoo" else "Our View"
    return ToolDSourceSelection(
        frame=selected,
        reason=(
            f"No persisted {source_label} Corporate Resilience data is available "
            f"for {label}."
        ),
    )


def _tool_d_schema_state(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "empty"
    if "tool_d_schema_version" not in frame.columns:
        return "malformed"
    versions = pd.to_numeric(frame["tool_d_schema_version"], errors="coerce")
    if versions.isna().any():
        return "malformed"
    if bool(versions.eq(float(TOOL_D_SCHEMA_VERSION)).all()):
        return "v4"
    # Pre-v4 artifacts were Our-View-only. Integer schema generations remain
    # readable for that source so their existing field-level migration notices
    # (for example the v1 FCF rebuild notice) can render honestly. Yahoo stays
    # unavailable until a dual-source v4 refresh is published.
    legacy_versions = versions.ge(1.0) & versions.lt(float(TOOL_D_SCHEMA_VERSION))
    integral_versions = versions.eq(versions.round())
    if bool((legacy_versions & integral_versions).all()) and versions.nunique() == 1:
        return "legacy_our"
    return "malformed"


@dataclass(frozen=True)
class ToolADetailState:
    weekly_series: pd.DataFrame
    structural_window_metrics: pd.DataFrame
    structural_metrics_load: "StructuralHistoryLoad"
    exploratory_horizons: pd.DataFrame
    foundation_error: str | None = None
    # Backend-resolved, per-window comparison of this stock vs GDX/GDXJ vs the miner universe.
    # Keyed by window id ("6M"/"12M"/"3Y"); the panel only formats the resolved markers.
    benchmark_comparison_by_window: dict[str, BetaUniverseComparison] = field(
        default_factory=dict
    )
    # Backend-built rebased (indexed-to-100) price overlay per window:
    # {window_id: {label: (dates, rebased_values)}}. The panel only draws it.
    rebased_overlay_by_window: dict[
        str, dict[str, tuple[list, list]]
    ] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Request-path memoization (deep-review perf fix, 2026-08-11).
#
# The canon is "compute once → persist → serve reads", but the detail page's
# deep-dive state has always been ASSEMBLED per request from persisted inputs
# (the accepted exception documented on _build_rebased_overlay_by_window).
# Profiling the real /ticker/<T> request showed ~83% of every hit re-reading
# ~11 parquet files and re-running the same assembly for UNCHANGED inputs
# (~1.1-1.6s per page, paid again on every window/lens switch).
#
# These caches memoize the two per-request loaders keyed on the
# (path, mtime_ns, size) signature of every file that can change their
# output. The model-state manifest governs every resolve_current_* choice
# (published artifacts are immutable run-stamped files, so WHICH file gets
# read only changes when the manifest changes); the latest-* aliases cover
# the manifest-less fallback route; the manual store covers user saves.
# Publish is all-or-nothing, so an unchanged signature means byte-identical
# inputs. Degraded detail loads (foundation_error) are never cached, so a
# transient I/O failure retries on the next request.

_STATE_CACHE: OrderedDict[tuple, WorkspaceState] = OrderedDict()
_STATE_CACHE_MAX = 4
_DETAIL_CACHE: OrderedDict[tuple, ToolADetailState] = OrderedDict()
_DETAIL_CACHE_MAX = 24


def clear_workspace_state_cache() -> None:
    """Drop every memoized loader result (test hook)."""
    _STATE_CACHE.clear()
    _DETAIL_CACHE.clear()
    # The ticker page's Lab render cache is a sibling of _DETAIL_CACHE and must
    # be dropped by the same hook, or a test that rewrites Lab artifacts sees a
    # stale render. Imported locally: serve.ticker_page.behaviour imports this
    # module, so a top-level import would be circular.
    from golden_vector.serve.ticker_page.behaviour import clear_lab_render_cache

    clear_lab_render_cache()


def _stat_entry(path: object) -> tuple:
    if path is None:
        return ("<none>", None, None)
    try:
        stat_result = os.stat(path)
    except OSError:
        return (str(path), None, None)
    return (str(path), stat_result.st_mtime_ns, stat_result.st_size)


def _loader_inputs_signature(paths: ProjectPaths) -> tuple:
    return tuple(
        _stat_entry(candidate)
        for candidate in (
            paths.latest_model_state_manifest_path,
            paths.latest_foundation_manifest_path,
            paths.latest_tool_a_snapshot_parquet_path,
            paths.latest_tool_b_snapshot_parquet_path,
            paths.latest_tool_c_snapshot_parquet_path,
            paths.latest_tool_d_spot_snapshot_parquet_path,
            paths.latest_tool_d_snapshot_parquet_path,
            paths.latest_benchmark_betas_path,
            paths.latest_tool_a_structural_metrics_path,
            paths.manual_screening_store_path,
        )
    )


def _fresh_state_view(state: WorkspaceState) -> WorkspaceState:
    """Per-request view of a cached state. Frames are handed out as cheap
    block-sharing copies so a renderer's column-level assignment can never
    write into the cached object (no renderer mutates today; this keeps that
    an invariant instead of a hope)."""
    return replace(
        state,
        foundation_manifest=(
            dict(state.foundation_manifest)
            if state.foundation_manifest is not None
            else None
        ),
        model_state_manifest=(
            dict(state.model_state_manifest)
            if state.model_state_manifest is not None
            else None
        ),
        company_inputs=state.company_inputs.copy(deep=False),
        source_verification=state.source_verification.copy(deep=False),
        reporting_calendar=state.reporting_calendar.copy(deep=False),
        stock_notes=state.stock_notes.copy(deep=False),
        latest_tool_a=state.latest_tool_a.copy(deep=False),
        latest_tool_b=state.latest_tool_b.copy(deep=False),
        latest_tool_c=state.latest_tool_c.copy(deep=False),
        latest_tool_d=state.latest_tool_d.copy(deep=False),
        latest_benchmark_betas=state.latest_benchmark_betas.copy(deep=False),
    )


def _fresh_detail_view(detail: ToolADetailState) -> ToolADetailState:
    return replace(
        detail,
        weekly_series=detail.weekly_series.copy(deep=False),
        structural_window_metrics=detail.structural_window_metrics.copy(deep=False),
        exploratory_horizons=detail.exploratory_horizons.copy(deep=False),
        benchmark_comparison_by_window=dict(detail.benchmark_comparison_by_window),
        rebased_overlay_by_window=dict(detail.rebased_overlay_by_window),
    )


def _load_workspace_state(paths: ProjectPaths, tool_b_tickers: list[str]) -> WorkspaceState:
    cache_key = (tuple(tool_b_tickers), _loader_inputs_signature(paths))
    cached = _STATE_CACHE.get(cache_key)
    if cached is not None:
        _STATE_CACHE.move_to_end(cache_key)
        return _fresh_state_view(cached)
    state = _load_workspace_state_uncached(paths, tool_b_tickers)
    _STATE_CACHE[cache_key] = state
    while len(_STATE_CACHE) > _STATE_CACHE_MAX:
        _STATE_CACHE.popitem(last=False)
    return _fresh_state_view(state)


def _load_workspace_state_uncached(
    paths: ProjectPaths, tool_b_tickers: list[str]
) -> WorkspaceState:
    loaded = load_manual_screening_data(paths, tickers=tool_b_tickers)
    model_state_manifest = load_current_model_state_manifest(paths)
    foundation_manifest = read_current_model_json(
        paths,
        "foundation",
        fallback_path=paths.latest_foundation_manifest_path,
    )
    tool_a_path = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    tool_b_path = resolve_current_model_artifact_path(
        paths,
        "tool_b",
        fallback_path=paths.latest_tool_b_snapshot_parquet_path,
    )
    tool_c_path = resolve_current_model_artifact_path(
        paths,
        "tool_c",
        fallback_path=paths.latest_tool_c_snapshot_parquet_path,
    )
    tool_d_path = resolve_current_model_artifact_path(
        paths,
        "tool_d_spot",
        fallback_path=paths.latest_tool_d_spot_snapshot_parquet_path,
    )
    if tool_d_path is None:
        tool_d_path = resolve_current_model_artifact_path(
            paths,
            "tool_d",
            fallback_path=paths.latest_tool_d_snapshot_parquet_path,
        )
    latest_tool_a = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    latest_tool_b = read_current_model_parquet(
        paths,
        "tool_b",
        fallback_path=paths.latest_tool_b_snapshot_parquet_path,
    )
    latest_tool_b = validate_tool_b_output_schema(
        latest_tool_b,
        label="workspace Corporate Finance artifact",
    )
    latest_tool_c = read_current_model_parquet(
        paths,
        "tool_c",
        fallback_path=paths.latest_tool_c_snapshot_parquet_path,
    )
    latest_tool_d = read_current_model_parquet(
        paths,
        "tool_d_spot",
        fallback_path=paths.latest_tool_d_spot_snapshot_parquet_path,
    )
    if latest_tool_d.empty:
        latest_tool_d = read_current_model_parquet(
            paths,
            "tool_d",
            fallback_path=paths.latest_tool_d_snapshot_parquet_path,
        )
    benchmark_betas_path = resolve_current_model_artifact_path(
        paths,
        "benchmark_betas",
        fallback_path=paths.latest_benchmark_betas_path,
    )
    latest_benchmark_betas = (
        read_optional_parquet(benchmark_betas_path) if benchmark_betas_path is not None else None
    )
    if latest_benchmark_betas is None:
        latest_benchmark_betas = pd.DataFrame()
    if not latest_tool_a.empty and "ticker" in latest_tool_a.columns:
        latest_tool_a["ticker"] = latest_tool_a["ticker"].astype(str).str.upper()
    if not latest_tool_b.empty and "ticker" in latest_tool_b.columns:
        latest_tool_b["ticker"] = latest_tool_b["ticker"].astype(str).str.upper()
    if not latest_tool_c.empty and "ticker" in latest_tool_c.columns:
        latest_tool_c["ticker"] = latest_tool_c["ticker"].astype(str).str.upper()
    if not latest_tool_d.empty and "ticker" in latest_tool_d.columns:
        latest_tool_d["ticker"] = latest_tool_d["ticker"].astype(str).str.upper()
    return WorkspaceState(
        tool_b_tickers=tool_b_tickers,
        foundation_manifest=foundation_manifest,
        company_inputs=loaded.company_inputs,
        source_verification=loaded.source_verification,
        reporting_calendar=loaded.reporting_calendar,
        stock_notes=loaded.stock_notes,
        latest_tool_a=latest_tool_a,
        latest_tool_b=latest_tool_b,
        latest_tool_c=latest_tool_c,
        latest_tool_d=latest_tool_d,
        tool_a_alias_present=tool_a_path is not None,
        tool_b_alias_present=tool_b_path is not None,
        tool_c_alias_present=tool_c_path is not None,
        tool_d_alias_present=tool_d_path is not None,
        model_state_manifest=model_state_manifest,
        latest_benchmark_betas=latest_benchmark_betas,
    )


def _load_tool_a_detail(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    ticker: str,
    universe_tool_a: pd.DataFrame | None = None,
) -> ToolADetailState:
    # app_config is process-constant (one config per server) and
    # universe_tool_a's content is covered by the same artifact signature,
    # so neither needs to join the key.
    cache_key = (str(ticker).upper(), _loader_inputs_signature(paths))
    cached = _DETAIL_CACHE.get(cache_key)
    if cached is not None:
        _DETAIL_CACHE.move_to_end(cache_key)
        return _fresh_detail_view(cached)
    detail = _load_tool_a_detail_uncached(
        paths, app_config=app_config, ticker=ticker, universe_tool_a=universe_tool_a
    )
    if detail.foundation_error is None:
        _DETAIL_CACHE[cache_key] = detail
        while len(_DETAIL_CACHE) > _DETAIL_CACHE_MAX:
            _DETAIL_CACHE.popitem(last=False)
    return _fresh_detail_view(detail)


def _load_tool_a_detail_uncached(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    ticker: str,
    universe_tool_a: pd.DataFrame | None = None,
) -> ToolADetailState:
    try:
        foundation_manifest_path = resolve_current_foundation_manifest_path(
            paths,
            require_current_manifest=True,
        )
        foundation_snapshot = load_latest_foundation_snapshot(
            paths=paths,
            app_config=app_config,
            include_gold_history=True,
            include_equity_histories=True,
            include_market_snapshots=False,
            requested_tickers=[ticker],
            manifest_path=foundation_manifest_path,
        )
    except Exception as exc:
        # Even when the foundation snapshot is unavailable, the published structural
        # metrics may still be present so the page-level file-health notice is accurate.
        return ToolADetailState(
            weekly_series=pd.DataFrame(),
            structural_window_metrics=pd.DataFrame(),
            structural_metrics_load=_load_published_structural_metrics(paths, ticker),
            exploratory_horizons=pd.DataFrame(),
            foundation_error=str(exc),
        )

    # Performance fix (post-deep-review): the previous implementation called
    # build_structural_ticker_data which recomputed structural_window_metrics for
    # every weekly date in the ticker's full history (~1,300 weeks × 3 windows
    # × ~52 datapoint regressions) on every detail-page hit. For NEM that took
    # ~25 seconds. tool-a already computed and persisted the same metrics in
    # tool_a_structural_latest.parquet, so we read them from there instead and
    # only build the cheap weekly_series for the scatter panel sample.
    full_equity_history = foundation_snapshot.normalized_equity_histories.get(
        ticker,
        pd.DataFrame(columns=[]),
    )
    weekly_series, _ = build_structural_weekly_series(
        usd_equity_history=full_equity_history,
        gold_history=foundation_snapshot.gold_history,
    )
    structural_metrics_load = _load_published_structural_metrics(paths, ticker)
    structural_window_metrics = structural_metrics_load.history

    # Horizons: compute only the most recent slice. The longest core horizon is
    # 3 years ≈ 756 trading days; we keep ~3 years + buffer so the most recent
    # as_of_date can find its longest start. The workspace uses only the latest
    # as_of_date's horizons.
    equity_for_horizons = (
        full_equity_history.tail(900) if len(full_equity_history.index) > 900 else full_equity_history
    )
    exploratory_horizons = compute_horizon_returns_for_ticker(
        usd_equity_history=equity_for_horizons,
        gold_history=foundation_snapshot.gold_history,
        horizons=build_core_horizons(app_config.horizons),
        near_zero_gold_return_threshold=app_config.qa.near_zero_gold_return_threshold,
    )
    if not exploratory_horizons.empty:
        latest_as_of_date = exploratory_horizons["as_of_date"].max()
        exploratory_horizons = exploratory_horizons.loc[
            exploratory_horizons["as_of_date"] == latest_as_of_date
        ].copy()
    return ToolADetailState(
        weekly_series=weekly_series,
        structural_window_metrics=structural_window_metrics,
        structural_metrics_load=structural_metrics_load,
        exploratory_horizons=exploratory_horizons,
        foundation_error=None,
        benchmark_comparison_by_window=_resolve_benchmark_comparison(
            paths, ticker, universe_df=universe_tool_a
        ),
        rebased_overlay_by_window=_build_rebased_overlay_by_window(
            paths,
            app_config,
            ticker=ticker,
            weekly_series=weekly_series,
            gold_history=foundation_snapshot.gold_history,
        ),
    )


def _build_rebased_overlay_by_window(
    paths: ProjectPaths,
    app_config: AppConfig,
    *,
    ticker: str,
    weekly_series: pd.DataFrame,
    gold_history: pd.DataFrame,
) -> dict[str, dict[str, tuple[list, list]]]:
    """Backend-built rebased (indexed-to-100) overlay of this stock vs gold vs GDX/GDXJ, one set
    per window lookback (``_WINDOW_WEEKS``). The detail panel only draws it. GDX/GDXJ are optional
    — a missing benchmark history simply omits that line. Reuses the shared benchmark loader + the
    cheap weekly-series builder (no per-page structural-metric recompute).

    Architecture note (deliberate): this is serve-time ASSEMBLY, not serve-time arithmetic. The
    rebasing math lives in the model layer (``common.numeric.rebase_to_base`` →
    ``model.structural.build_rebased_comparison_series``); here we only orchestrate load → call the
    model builders → assemble a display dict. That matches the established detail-page exception —
    ``weekly_series``, ``exploratory_horizons`` and ``benchmark_comparison_by_window`` are all built
    on this same per-request path in ``_build_tool_a_detail_state`` — and the work is O(window) over
    already-loaded prices, so it is intentionally NOT promoted to a persisted artifact."""

    # The overlay is an optional display aid — degrade to "no chart" on ANY failure rather than
    # 500 the whole detail page (matches _resolve_benchmark_comparison's never-break-the-page rule).
    try:
        if weekly_series.empty or "as_of_date" not in weekly_series.columns:
            return {}
        sorted_weekly = weekly_series.sort_values("as_of_date")
        stock_dates = list(pd.to_datetime(sorted_weekly["as_of_date"]))
        # pd.to_numeric(errors="coerce") — NOT .astype(float) — so nullable pd.NA values become
        # NaN (which rebase_to_base then treats as a per-point gap) instead of raising TypeError.
        series_by_label: dict[str, tuple[list, list]] = {
            ticker: (
                stock_dates,
                pd.to_numeric(sorted_weekly["stock_basis_usd"], errors="coerce").tolist(),
            ),
            "Gold": (
                stock_dates,
                pd.to_numeric(sorted_weekly["gold_basis_usd"], errors="coerce").tolist(),
            ),
        }

        # Lazy import keeps the serve module free of a top-level portfolio dependency.
        from golden_vector.portfolio.benchmark_betas import load_benchmark_normalized_histories

        try:
            # load_errors is intentionally discarded: GDX/GDXJ are optional here, so a failed
            # benchmark load simply omits that line (same policy as _resolve_benchmark_comparison).
            normalized_histories, _ = load_benchmark_normalized_histories(
                paths=paths, app_config=app_config
            )
        except Exception:  # noqa: BLE001 - benchmarks are optional; never break the page.
            normalized_histories = {}
        for label, history in normalized_histories.items():
            bench_weekly, _ = build_structural_weekly_series(
                usd_equity_history=history, gold_history=gold_history
            )
            if bench_weekly.empty or "as_of_date" not in bench_weekly.columns:
                continue
            bench_weekly = bench_weekly.sort_values("as_of_date")
            series_by_label[label] = (
                list(pd.to_datetime(bench_weekly["as_of_date"])),
                pd.to_numeric(bench_weekly["stock_basis_usd"], errors="coerce").tolist(),
            )

        return {
            window: build_rebased_comparison_series(series_by_label, window_weeks=weeks)
            for window, weeks in _WINDOW_WEEKS.items()
        }
    except Exception:  # noqa: BLE001 - overlay is an optional display aid; degrade to no chart.
        return {}


def _resolve_benchmark_comparison(
    paths: ProjectPaths,
    ticker: str,
    *,
    universe_df: pd.DataFrame | None = None,
) -> dict[str, BetaUniverseComparison]:
    """Resolve the per-window stock-vs-GDX/GDXJ-vs-universe comparison from persisted artifacts.

    The caller passes the already-loaded ``latest_tool_a`` frame (the detail route loads it for
    WorkspaceState anyway) so we never re-read that parquet per request; only the tiny 2-row
    benchmark file is read here. Any failure (missing universe/benchmark parquet) degrades to an
    empty dict so the detail page still renders. All beta math happens in the model resolver.
    """

    try:
        universe = (
            universe_df
            if universe_df is not None
            else read_current_model_parquet(
                paths,
                "tool_a",
                fallback_path=paths.latest_tool_a_snapshot_parquet_path,
            )
        )
        benchmark_path = resolve_current_model_artifact_path(
            paths,
            "benchmark_betas",
            fallback_path=paths.latest_benchmark_betas_path,
        )
        benchmark = (
            read_optional_parquet(benchmark_path) if benchmark_path is not None else None
        )
        return resolve_beta_universe_comparisons_by_window(
            ticker=ticker,
            window_ids=_STRUCTURAL_WINDOWS,
            universe_df=universe,
            benchmark_df=benchmark,
        )
    except Exception:  # noqa: BLE001 - comparison is optional; never break the detail page.
        return {}

def _load_published_structural_metrics(
    paths: ProjectPaths,
    ticker: str,
) -> "StructuralHistoryLoad":
    """Read the full set of structural_window_metrics for one ticker from the
    published parquet, with no recomputation. Returns the same structured load
    result as the chart helper so the workspace can present one consistent
    artifact-health story across the detail page (codex follow-up to Fix #5).
    """
    parquet_path = _current_structural_metrics_path(paths)
    if parquet_path is None:
        return StructuralHistoryLoad(status="missing", history=pd.DataFrame())
    if not parquet_path.exists():
        return StructuralHistoryLoad(status="missing", history=pd.DataFrame())
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:
        return StructuralHistoryLoad(
            status="corrupt", history=pd.DataFrame(), error_message=str(exc)
        )
    if frame.empty or "ticker" not in frame.columns:
        return StructuralHistoryLoad(status="no_rows", history=frame)
    normalized = str(ticker).strip().upper()
    filtered = frame.loc[frame["ticker"].astype(str).str.upper() == normalized].copy()
    if filtered.empty:
        return StructuralHistoryLoad(status="no_rows", history=filtered)
    return StructuralHistoryLoad(status="ok", history=filtered)


def _parse_ticker_route(path: str) -> tuple[str, str | None]:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0] != "ticker":
        return "", None
    # Deep-review L2: trailing segments are NOT ignored — /ticker/NEM/company/x
    # must 404, not silently behave like the company save route.
    if len(parts) > 3:
        return "", None
    ticker = parts[1].strip().upper()
    action = parts[2] if len(parts) > 2 else None
    return ticker, action


# Tool A Detail Provenance Rule (plan v3 §1): foundation-backed panels on the
# detail page must match the displayed Tool A row's snapshot_refresh_run_id.
# When they don't, each panel is suppressed with a visible fallback card rather
# than rendered with stale numbers.
DETAIL_ALIGNMENT_ALIGNED = "ALIGNED"
DETAIL_ALIGNMENT_FOUNDATION_AHEAD = "FOUNDATION_AHEAD"
DETAIL_ALIGNMENT_FOUNDATION_MISSING = "FOUNDATION_MISSING"
DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH = "TOOL_A_MISSING_REFRESH"


# Structural windows the detail page exposes — the FULL registry set (6M/1Y/2Y/3Y/5Y), so
# every descriptive metric (delta/gamma/asymmetry/beta/R²/weeks/volatility/scatter/overlay)
# follows the horizon switcher with no mixing. Score/Confidence/Profile are cross-window
# summaries (across the scoring windows) and are labelled as such, not faked per-window.
# ONE definition, from the registry. Order = switcher tab display order.
_STRUCTURAL_WINDOWS: tuple[str, ...] = ALL_WINDOWS

# Weekly-observation count per detail window, sourced from the ONE registry (no literals)
# — used by the scatter-slice / volatility recompute / rebased-overlay helpers.
_WINDOW_WEEKS: dict[str, int] = {window: window_weeks(window) for window in _STRUCTURAL_WINDOWS}


def _current_structural_metrics_path(paths: ProjectPaths) -> Path | None:
    return resolve_current_model_artifact_path(
        paths,
        "tool_a_structural_metrics",
        fallback_path=paths.latest_tool_a_structural_metrics_path,
    )


def _structural_history_matches_tool_a(
    structural_history: pd.DataFrame,
    tool_a_row: dict[str, Any],
) -> bool:
    """Phase 2B provenance gate.

    The history rows carry ``source_run_id`` (added in Phase 1A). The Tool A row
    also carries ``source_run_id``. They must match for the chart to render —
    otherwise the structural file was produced by a different ``tool-a`` run and
    might not reflect the published row.
    """

    if structural_history.empty or "source_run_id" not in structural_history.columns:
        return False
    tool_a_run_id = str(tool_a_row.get("source_run_id") or "").strip()
    if not tool_a_run_id or tool_a_run_id.lower() == "nan":
        return False
    history_ids = {
        str(value).strip()
        for value in structural_history["source_run_id"].dropna().unique()
    }
    return history_ids == {tool_a_run_id}


@dataclass(frozen=True)
class StructuralHistoryLoad:
    """Structured load result for the published structural-metrics parquet.

    Distinguishes the file states the workspace must communicate differently:
    - ``ok`` — file loaded; ``history`` is the filtered DataFrame
    - ``missing`` — file does not exist on disk
    - ``no_rows`` — file exists but no eligible rows for the ticker / window
    - ``corrupt`` — file exists but pandas couldn't read it (or wrong shape)
    """

    status: str
    history: pd.DataFrame
    error_message: str | None = None
