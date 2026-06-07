"""Workspace state objects, loaders, and route parsing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

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
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.horizons import build_core_horizons
from golden_vector.features.returns import compute_horizon_returns_for_ticker
from golden_vector.model.structural import build_structural_weekly_series
from golden_vector.screening.manual_data import load_manual_screening_data


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


@dataclass(frozen=True)
class ToolADetailState:
    weekly_series: pd.DataFrame
    structural_window_metrics: pd.DataFrame
    structural_metrics_load: "StructuralHistoryLoad"
    exploratory_horizons: pd.DataFrame
    structural_history_load: "StructuralHistoryLoad"
    foundation_error: str | None = None


@dataclass(frozen=True)
class OverviewFilters:
    """Phase 1B.4: lightweight overview controls passed via querystring.

    Empty string means "no filter" / "default sort". Only a small allow-list
    of sort keys is honored so the URL surface stays predictable.
    """

    search: str = ""
    profile: str = ""
    verdict: str = ""
    confidence: str = ""
    sort: str = ""

    SORT_OPTIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("ticker", "Ticker (A→Z)"),
        ("tool_a_rank", "Gold Sensitivity Rank (best first)"),
        ("tool_b_rank", "Corporate Finance Rank (best first)"),
        ("tool_a_score", "Gold Sensitivity Score (high→low)"),
        ("tool_b_score", "Corporate Finance Score (high→low)"),
    )

    def normalized_search(self) -> str:
        return str(self.search or "").strip().upper()

    def normalized_profile(self) -> str:
        return str(self.profile or "").strip().upper()

    def normalized_verdict(self) -> str:
        return str(self.verdict or "").strip().upper()

    def normalized_confidence(self) -> str:
        return str(self.confidence or "").strip().upper()

    def normalized_sort(self) -> str:
        sort = str(self.sort or "").strip().lower()
        allowed = {key for key, _ in self.SORT_OPTIONS}
        return sort if sort in allowed else "ticker"


def _load_workspace_state(paths: ProjectPaths, tool_b_tickers: list[str]) -> WorkspaceState:
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
    )


def _load_tool_a_detail(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    ticker: str,
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
        # Even when the foundation snapshot is unavailable, the structural-history
        # parquet might still be present and usable for the beta-history chart.
        return ToolADetailState(
            weekly_series=pd.DataFrame(),
            structural_window_metrics=pd.DataFrame(),
            structural_metrics_load=_load_published_structural_metrics(paths, ticker),
            exploratory_horizons=pd.DataFrame(),
            structural_history_load=_safe_load_structural_history(paths, ticker),
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
        structural_history_load=_safe_load_structural_history(paths, ticker),
        foundation_error=None,
    )

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


def _safe_load_structural_history(paths: ProjectPaths, ticker: str) -> "StructuralHistoryLoad":
    """Load the full per-window structural history for one ticker.

    Returns all three windows (6M / 12M / 3Y) so the rolling chart can draw
    three lines. Distinguishes ``missing`` / ``corrupt`` / ``no_rows`` / ``ok``
    so the chart panel can render the right fallback (codex P2 fix).
    """

    parquet_path = _current_structural_metrics_path(paths)
    if parquet_path is None:
        return StructuralHistoryLoad(status="missing", history=pd.DataFrame())
    if not parquet_path.exists():
        return StructuralHistoryLoad(status="missing", history=pd.DataFrame())
    try:
        frames: list[pd.DataFrame] = []
        for window_id in _STRUCTURAL_WINDOWS:
            frames.append(
                _load_structural_delta_history(paths, ticker=ticker, window_id=window_id)
            )
    except Exception as exc:  # parquet read error → corrupt
        return StructuralHistoryLoad(
            status="corrupt", history=pd.DataFrame(), error_message=str(exc)
        )
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return StructuralHistoryLoad(status="no_rows", history=pd.DataFrame())
    history = pd.concat(non_empty, ignore_index=True)
    return StructuralHistoryLoad(status="ok", history=history)


def _parse_ticker_route(path: str) -> tuple[str, str | None]:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0] != "ticker":
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


# Canonical structural windows available on the detail page. Order here
# is the display order for the switcher tabs.
_STRUCTURAL_WINDOWS: tuple[str, ...] = ("6M", "12M", "3Y")

# Number of weekly observations per window, used by the scatter-slice
# and volatility recompute helpers.
_WINDOW_WEEKS: dict[str, int] = {"6M": 26, "12M": 52, "3Y": 156}


def _load_structural_delta_history(
    paths: ProjectPaths,
    *,
    ticker: str,
    window_id: str = "12M",
) -> pd.DataFrame:
    """Read the published structural-metrics parquet for one ticker / window.

    Returns rows where ``window_status == 'ELIGIBLE'`` and ``structural_delta`` is
    finite, sorted by ``as_of_date``. Carries ``source_run_id`` for the Phase 1A
    provenance check. Empty DataFrame if the file is missing or no eligible rows
    exist for the ticker.
    """

    parquet_path = _current_structural_metrics_path(paths)
    if parquet_path is None:
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    if not parquet_path.exists():
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    frame = pd.read_parquet(parquet_path)
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    normalized_ticker = str(ticker).strip().upper()
    normalized_window = str(window_id).strip().upper()
    mask = (
        (frame["ticker"].astype(str).str.upper() == normalized_ticker)
        & (frame["window_id"].astype(str).str.upper() == normalized_window)
        & (frame.get("window_status", pd.Series(dtype=str)).astype(str).str.upper() == "ELIGIBLE")
    )
    history = frame.loc[mask].copy()
    if history.empty:
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    history["structural_delta"] = pd.to_numeric(history["structural_delta"], errors="coerce")
    history = history.loc[history["structural_delta"].notna()].copy()
    history["as_of_date"] = pd.to_datetime(history["as_of_date"], errors="coerce")
    history = history.loc[history["as_of_date"].notna()].copy()
    history = history.sort_values("as_of_date").reset_index(drop=True)
    return history


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


_WINDOW_COLORS: dict[str, str] = {
    "6M": "#8a6d3b",
    "12M": "#1d4b73",
    "3Y": "#5a3b8a",
}


@dataclass(frozen=True)
class StructuralHistoryLoad:
    """Structured load result for the beta-history parquet, per codex P2 fix.

    Distinguishes the file states the workspace must communicate differently:
    - ``ok`` — file loaded; ``history`` is the filtered DataFrame
    - ``missing`` — file does not exist on disk
    - ``no_rows`` — file exists but no eligible rows for the ticker / window
    - ``corrupt`` — file exists but pandas couldn't read it (or wrong shape)
    """

    status: str
    history: pd.DataFrame
    error_message: str | None = None
