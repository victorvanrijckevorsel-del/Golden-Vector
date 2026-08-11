"""The ``ticker-page`` stage orchestrator (plan §5.5).

Compute once -> persist -> serve reads. This module owns the *stage*: it calls
the four pure builders in ``golden_vector.model.ticker_page``, self-reports
per-substep seconds + row counts through the shared timing helper, and persists
through ``persist_ticker_page_artifacts`` with explicit provenance.

Identity is never guessed here:

* **in-refresh** — the caller passes the live refresh context's
  ``parent_refresh_id`` / ``snapshot_refresh_run_id`` (the manifest is only
  published at refresh end, so reading it mid-refresh would read the *previous*
  generation);
* **standalone** — ``load_ticker_page_stage_inputs`` resolves everything through
  the CURRENT model-state manifest and refuses to run on a mixed tool
  generation.

``cli.py`` stays thin: it decides which of the two identity sources applies and
hands the loaded inputs to :func:`run_ticker_page_stage`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd

from golden_vector.app.model_state import resolve_current_model_artifact_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.common.parquet import read_optional_parquet
from golden_vector.common.stage_timing import record_step_timing
from golden_vector.contracts.ticker_page import (
    PERFORMANCE_COLUMNS,
    RESEARCH_SERIES_COLUMNS,
    empty_artifact_frame,
)
from golden_vector.features.horizons import build_core_horizons
from golden_vector.features.returns import compute_horizon_returns_for_ticker
from golden_vector.ingestion.persist_ticker_page import persist_ticker_page_artifacts
from golden_vector.model.structural import build_structural_weekly_series
from golden_vector.model.ticker_page import (
    build_gold_response_pack,
    build_performance_series,
    build_research_series,
    build_score_percentiles,
)
from golden_vector.normalize.prices_usd import normalize_equity_history_to_usd
from golden_vector.screening.pipeline import materialize_tool_b_finance_source

#: Benchmarks whose series the performance artifact carries (§5.6).
BENCHMARK_SERIES_TICKERS: tuple[str, ...] = ("GDX", "GDXJ")

#: Longest core horizon is 3 years (~756 trading days); keep a buffer so the most
#: recent as_of can still find its longest start. Mirrors the serve loader.
_HORIZON_HISTORY_TAIL_ROWS = 900


class TickerPageGenerationMismatchError(RuntimeError):
    """Standalone ``ticker-page`` refused to run on a mixed tool generation."""


@dataclass(frozen=True)
class TickerPageStageInputs:
    """Everything the stage needs, already loaded by the caller."""

    app_config: Any
    manual_data: Any
    normalized_market_snapshots: pd.DataFrame
    official_fundamentals: pd.DataFrame | None
    gold_history: pd.DataFrame
    normalized_equity_histories: dict[str, pd.DataFrame]
    tool_a_latest: pd.DataFrame
    tool_b_latest: pd.DataFrame
    tool_c_latest: pd.DataFrame
    tool_d_latest: pd.DataFrame
    structural_window_metrics: pd.DataFrame
    benchmark_histories: dict[str, pd.DataFrame]
    benchmark_series_run_ids: dict[str, str]
    snapshot_refresh_run_id: str
    snapshot_as_of_date: Any
    config_hash: str
    upstream_run_ids: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------


def resolve_benchmark_histories(
    *,
    paths: ProjectPaths,
    app_config: Any,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], list[str]]:
    """Resolve GDX/GDXJ USD histories + their provenance run ids (§4.4, P9).

    Preferred source is the options manifest's **immutable run-stamped**
    benchmark snapshots, which carry a real ``refresh_run_id``. When the
    manifest has no entry for a benchmark we fall back to the shared mutable
    cache loader (``load_benchmark_normalized_histories`` — one copy of the
    read+normalize step) and mark that series ``series_source_run_id='unknown'``
    plus a returned warning: a file mtime is not provenance.
    """

    # Lazy import: the app layer must not carry a top-level portfolio dependency.
    from golden_vector.portfolio.benchmark_betas import (
        load_benchmark_normalized_histories,
    )

    manifest = _read_json_object(paths.latest_options_manifest_path)
    manifest_run_id = ""
    snapshot_by_ticker: dict[str, Path] = {}
    if manifest is not None:
        manifest_run_id = str(manifest.get("refresh_run_id") or "").strip()
        for value in manifest.get("benchmark_snapshot_paths") or []:
            path = paths.resolve_repo_relative(str(value))
            snapshot_by_ticker[path.stem.upper()] = path

    histories: dict[str, pd.DataFrame] = {}
    run_ids: dict[str, str] = {}
    warnings: list[str] = []
    unresolved: list[str] = []

    for ticker in BENCHMARK_SERIES_TICKERS:
        path = snapshot_by_ticker.get(ticker)
        if path is None or not path.exists() or not manifest_run_id:
            unresolved.append(ticker)
            continue
        raw = read_optional_parquet(path)
        if raw.empty:
            unresolved.append(ticker)
            continue
        try:
            histories[ticker.lower()] = normalize_equity_history_to_usd(
                frame=raw,
                fx_history=pd.DataFrame(),
                max_fx_staleness_days=app_config.qa.max_fx_staleness_days,
            )
        except Exception as error:  # noqa: BLE001 - degrade this benchmark only
            warnings.append(
                f"{ticker} immutable benchmark snapshot could not be normalized: {error}"
            )
            unresolved.append(ticker)
            continue
        run_ids[ticker.lower()] = manifest_run_id

    if unresolved:
        try:
            cached, load_errors = load_benchmark_normalized_histories(
                paths=paths, app_config=app_config
            )
        except Exception as error:  # noqa: BLE001 - benchmarks are optional
            cached, load_errors = {}, {ticker: str(error) for ticker in unresolved}
        for ticker in unresolved:
            frame = cached.get(ticker)
            if frame is None or frame.empty:
                warnings.append(
                    f"{ticker} benchmark history unavailable: "
                    f"{load_errors.get(ticker, 'no cached history')}"
                )
                continue
            histories[ticker.lower()] = frame
            run_ids[ticker.lower()] = "unknown"
            warnings.append(
                f"{ticker} benchmark series has no run-stamped provenance "
                "(the options manifest lists no immutable snapshot for it); "
                "series_source_run_id='unknown'. A file mtime is not provenance."
            )
    return histories, run_ids, warnings


def load_ticker_page_stage_inputs(
    *,
    paths: ProjectPaths,
    app_config: Any,
    config_hash: str,
    foundation_snapshot: Any,
    use_model_state: bool,
    manual_data: Any,
    official_fundamentals: pd.DataFrame | None,
) -> TickerPageStageInputs:
    """Load the four tool frames + supporting inputs for the stage.

    ``use_model_state=True`` (standalone) resolves every tool frame through the
    current manifest; ``False`` (in-refresh) reads the aliases the just-completed
    tool steps published, exactly as tool-c/tool-d do mid-refresh.
    """

    tool_frames: dict[str, pd.DataFrame] = {}
    for name, fallback in (
        ("tool_a", paths.latest_tool_a_snapshot_parquet_path),
        ("tool_b", paths.latest_tool_b_snapshot_parquet_path),
        ("tool_c", paths.latest_tool_c_snapshot_parquet_path),
        ("tool_d", paths.latest_tool_d_snapshot_parquet_path),
    ):
        path = (
            resolve_current_model_artifact_path(paths, name, fallback_path=fallback)
            if use_model_state
            else (fallback if fallback.exists() else None)
        )
        if path is None:
            raise FileNotFoundError(
                f"No current {name} output exists yet; the ticker-page stage needs all "
                "four tool artifacts. Run `python main.py refresh` first."
            )
        tool_frames[name] = pd.read_parquet(path)

    structural_path = (
        resolve_current_model_artifact_path(
            paths,
            "tool_a_structural_metrics",
            fallback_path=paths.latest_tool_a_structural_metrics_path,
        )
        if use_model_state
        else (
            paths.latest_tool_a_structural_metrics_path
            if paths.latest_tool_a_structural_metrics_path.exists()
            else None
        )
    )
    structural_window_metrics = (
        read_optional_parquet(structural_path) if structural_path else pd.DataFrame()
    )

    benchmark_histories, benchmark_run_ids, warnings = resolve_benchmark_histories(
        paths=paths, app_config=app_config
    )

    return TickerPageStageInputs(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
        official_fundamentals=official_fundamentals,
        gold_history=foundation_snapshot.gold_history,
        normalized_equity_histories=dict(
            foundation_snapshot.normalized_equity_histories or {}
        ),
        tool_a_latest=tool_frames["tool_a"],
        tool_b_latest=tool_frames["tool_b"],
        tool_c_latest=tool_frames["tool_c"],
        tool_d_latest=tool_frames["tool_d"],
        structural_window_metrics=structural_window_metrics,
        benchmark_histories=benchmark_histories,
        benchmark_series_run_ids=benchmark_run_ids,
        snapshot_refresh_run_id=str(foundation_snapshot.refresh_run_id or ""),
        snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
        config_hash=config_hash,
        warnings=tuple(warnings),
    )


def assert_tool_generation_aligned(manifest: dict[str, Any] | None) -> str:
    """Return the aligned tool generation id, or raise (standalone guard, §5.5).

    A standalone ticker-page build inherits identity from the current manifest,
    so all four tools must name the SAME ``snapshot_refresh_run_id``. Building
    across a mixed generation would stamp one identity onto rows derived from
    two — the exact split-brain the manifest exists to prevent.
    """

    if not isinstance(manifest, dict):
        raise TickerPageGenerationMismatchError(
            "No current model-state manifest exists; run `python main.py refresh` "
            "before a standalone ticker-page build."
        )
    artifacts = manifest.get("artifacts")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    observed: dict[str, list[str]] = {}
    for name in ("tool_a", "tool_b", "tool_c", "tool_d"):
        entry = artifacts.get(name)
        entry = entry if isinstance(entry, dict) else {}
        ids = [
            str(value).strip()
            for value in (entry.get("snapshot_refresh_run_ids") or [])
            if str(value).strip()
        ]
        observed[name] = ids
    missing = sorted(name for name, ids in observed.items() if not ids)
    if missing:
        raise TickerPageGenerationMismatchError(
            "Current model state does not expose a snapshot_refresh_run_id for: "
            + ", ".join(missing)
            + ". Run `python main.py refresh` before a standalone ticker-page build."
        )
    distinct = sorted({run_id for ids in observed.values() for run_id in ids})
    if len(distinct) != 1:
        detail = "; ".join(f"{name}={','.join(ids)}" for name, ids in observed.items())
        raise TickerPageGenerationMismatchError(
            "Tool generation is not aligned, so a standalone ticker-page build would "
            f"stamp one identity onto rows from several ({detail}). "
            "Run `python main.py refresh` first."
        )
    return distinct[0]


# ---------------------------------------------------------------------------
# The stage
# ---------------------------------------------------------------------------


def run_ticker_page_stage(
    *,
    paths: ProjectPaths,
    app_config: Any,
    run_context: RunContext,
    parent_refresh_id: str,
    snapshot_refresh_run_id: str,
    config_hash: str,
    upstream_run_ids: dict[str, str] | None = None,
    manual_data: Any,
    normalized_market_snapshots: pd.DataFrame,
    official_fundamentals: pd.DataFrame | None,
    gold_history: pd.DataFrame,
    normalized_equity_histories: dict[str, pd.DataFrame],
    tool_a_latest: pd.DataFrame,
    tool_b_latest: pd.DataFrame,
    tool_c_latest: pd.DataFrame,
    tool_d_latest: pd.DataFrame,
    structural_window_metrics: pd.DataFrame | None = None,
    benchmark_histories: dict[str, pd.DataFrame] | None = None,
    benchmark_series_run_ids: dict[str, str] | None = None,
    snapshot_as_of_date: Any = None,
    input_warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build + persist the four ticker-page artifacts. Returns a summary dict."""

    timings: dict[str, dict[str, object]] = {}
    warnings: list[str] = list(input_warnings)

    universe = _tool_b_universe(app_config)

    # --- substep 1: gold response pack -----------------------------------
    started_at = perf_counter()
    gold_response, diagnostics = build_gold_response_pack(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=normalized_market_snapshots,
        official_fundamentals=official_fundamentals,
        gold_history=gold_history,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
        snapshot_as_of_date=snapshot_as_of_date,
        source_run_id=run_context.run_id,
    )
    record_step_timing(
        timings,
        "gold_response",
        started_at,
        rows_built=len(gold_response.index),
        extra={"diagnostic_rows": int(len(diagnostics.index))},
    )

    # --- substep 2: percentiles ------------------------------------------
    started_at = perf_counter()
    tool_b_by_source = {
        source: materialize_tool_b_finance_source(
            tool_b_latest, finance_source=source
        )
        for source in ("our", "yahoo")
    }
    percentiles = build_score_percentiles(
        app_config=app_config,
        tool_a_latest=tool_a_latest,
        tool_b_latest_by_source=tool_b_by_source,
        tool_c_latest=tool_c_latest,
        tool_d_latest=tool_d_latest,
    )
    record_step_timing(
        timings, "percentiles", started_at, rows_built=len(percentiles.index)
    )

    # --- substep 3: performance series (per ticker) -----------------------
    started_at = perf_counter()
    performance_frames: list[pd.DataFrame] = []
    performance_failures: list[str] = []
    for ticker in universe:
        equity_history = normalized_equity_histories.get(ticker)
        if equity_history is None or equity_history.empty:
            performance_failures.append(f"{ticker}: no normalized equity history")
            continue
        try:
            performance_frames.append(
                build_performance_series(
                    app_config=app_config,
                    equity_history=equity_history,
                    gold_history=gold_history,
                    benchmark_histories=benchmark_histories or {},
                    ticker=ticker,
                    equity_as_of_date=_equity_as_of(equity_history, snapshot_as_of_date),
                    series_source_run_ids=benchmark_series_run_ids,
                )
            )
        except Exception as error:  # noqa: BLE001 - degrade per item (senior rule)
            performance_failures.append(f"{ticker}: {error}")
    performance = _concat(
        performance_frames, columns=PERFORMANCE_COLUMNS, artifact="performance"
    )
    if performance_failures:
        warnings.append(
            f"performance series unavailable for {len(performance_failures)} ticker(s): "
            + "; ".join(performance_failures[:10])
        )
    record_step_timing(
        timings,
        "performance",
        started_at,
        rows_built=len(performance.index),
        extra={
            "tickers_built": len(performance_frames),
            "tickers_failed": len(performance_failures),
        },
    )

    # --- substep 4: research series (per ticker) --------------------------
    started_at = perf_counter()
    horizons = build_core_horizons(app_config.horizons)
    structural = (
        structural_window_metrics
        if structural_window_metrics is not None
        else pd.DataFrame()
    )
    research_frames: list[pd.DataFrame] = []
    research_failures: list[str] = []
    for ticker in universe:
        equity_history = normalized_equity_histories.get(ticker)
        if equity_history is None or equity_history.empty:
            research_failures.append(f"{ticker}: no normalized equity history")
            continue
        try:
            weekly_series, _ = build_structural_weekly_series(
                usd_equity_history=equity_history,
                gold_history=gold_history,
            )
            equity_for_horizons = (
                equity_history.tail(_HORIZON_HISTORY_TAIL_ROWS)
                if len(equity_history.index) > _HORIZON_HISTORY_TAIL_ROWS
                else equity_history
            )
            exploratory_horizons = compute_horizon_returns_for_ticker(
                usd_equity_history=equity_for_horizons,
                gold_history=gold_history,
                horizons=horizons,
                near_zero_gold_return_threshold=(
                    app_config.qa.near_zero_gold_return_threshold
                ),
            )
            if not exploratory_horizons.empty:
                latest_as_of = exploratory_horizons["as_of_date"].max()
                exploratory_horizons = exploratory_horizons.loc[
                    exploratory_horizons["as_of_date"] == latest_as_of
                ].copy()
            research_frames.append(
                build_research_series(
                    ticker=ticker,
                    weekly_series_frame=weekly_series,
                    exploratory_horizons_frame=exploratory_horizons,
                    structural_window_metrics_frame=_ticker_rows(structural, ticker),
                )
            )
        except Exception as error:  # noqa: BLE001 - degrade per item (senior rule)
            research_failures.append(f"{ticker}: {error}")
    research_series = _concat(
        research_frames, columns=RESEARCH_SERIES_COLUMNS, artifact="research_series"
    )
    if research_failures:
        warnings.append(
            f"research series unavailable for {len(research_failures)} ticker(s): "
            + "; ".join(research_failures[:10])
        )
    record_step_timing(
        timings,
        "research_series",
        started_at,
        rows_built=len(research_series.index),
        extra={
            "tickers_built": len(research_frames),
            "tickers_failed": len(research_failures),
        },
    )

    # --- substep 5: persist ----------------------------------------------
    started_at = perf_counter()
    written_paths = persist_ticker_page_artifacts(
        paths,
        run_context,
        gold_response=gold_response,
        percentiles=percentiles,
        performance=performance,
        research_series=research_series,
        diagnostics=diagnostics,
        source_run_id=run_context.run_id,
        snapshot_refresh_run_id=snapshot_refresh_run_id,
        parent_refresh_id=parent_refresh_id,
        config_hash=config_hash,
    )
    rows_persisted = int(
        len(gold_response.index)
        + len(percentiles.index)
        + len(performance.index)
        + len(research_series.index)
    )
    record_step_timing(
        timings,
        "persist",
        started_at,
        rows_persisted=rows_persisted,
        extra={"files_written": len(written_paths)},
    )

    summary: dict[str, Any] = {
        "source_run_id": run_context.run_id,
        "parent_refresh_id": parent_refresh_id,
        "snapshot_refresh_run_id": snapshot_refresh_run_id,
        "config_hash": config_hash,
        "upstream_run_ids": dict(upstream_run_ids or {}),
        "universe_ticker_count": len(universe),
        "rows": {
            "gold_response": int(len(gold_response.index)),
            "percentiles": int(len(percentiles.index)),
            "performance": int(len(performance.index)),
            "research_series": int(len(research_series.index)),
            "linearity_diagnostics": int(len(diagnostics.index)),
        },
        "timings": timings,
        "warnings": warnings,
        "artifact_paths": [path.as_posix() for path in written_paths],
    }
    run_context.write_json("ticker_page_stage_summary.json", summary)
    return summary


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _tool_b_universe(app_config: Any) -> list[str]:
    return sorted(
        str(ticker.ticker).upper()
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_b_enabled
    )


def _concat(
    frames: list[pd.DataFrame], *, columns: tuple[str, ...], artifact: str
) -> pd.DataFrame:
    """Concatenate per-ticker frames, always keeping the contract column set.

    A fully degraded build (no ticker produced rows) must still write a frame
    with the artifact's real DTYPES, not an all-object placeholder — otherwise
    the persisted schema silently changes shape under every reader on exactly
    the day the build went wrong.
    """

    live = [frame for frame in frames if frame is not None and not frame.empty]
    if not live:
        return empty_artifact_frame(artifact)
    return pd.concat(live, ignore_index=True)[list(columns)]


def _ticker_rows(frame: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if frame is None or frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame()
    return frame.loc[frame["ticker"].astype(str).str.upper() == ticker].copy()


def _equity_as_of(equity_history: pd.DataFrame, snapshot_as_of_date: Any) -> Any:
    if "date" in equity_history.columns:
        dates = pd.to_datetime(equity_history["date"], errors="coerce").dropna()
        if not dates.empty:
            return dates.max()
    return snapshot_as_of_date


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable manifest is simply absent here
        return None
    return payload if isinstance(payload, dict) else None
