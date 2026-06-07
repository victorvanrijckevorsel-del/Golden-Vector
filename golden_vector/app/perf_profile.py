"""Read-only cached performance profiling helpers."""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import load_current_model_state_manifest
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.numeric import optional_float as _optional_float
from golden_vector.contracts.config_models import AppConfig
from golden_vector.ingestion.persist import _latest_snapshot
from golden_vector.hedge.option_artifact_builder import (
    build_option_artifact_inputs,
    scan_option_chains_for_artifacts,
    scan_option_contract_metrics,
)
from golden_vector.hedge.option_artifact_frames import build_option_artifact_frames
from golden_vector.hedge.option_artifact_sources import load_option_artifact_source_inputs
from golden_vector.model.structural import (
    StructuralTickerData,
    build_structural_history_frames,
    compute_volatility_diagnostics,
)
from golden_vector.model.pipeline import _build_tool_a_outputs
from golden_vector.model.scoring import rank_tool_a_outputs


class _PerfRunContext:
    run_id = "perf-profile"


def build_cached_perf_profile(paths: ProjectPaths) -> dict[str, Any]:
    """Time expensive local compute paths from cached artifacts only.

    This deliberately avoids RunContext and persistence. It is a diagnostic
    guardrail for performance work, not a model-building command.
    """

    profile_started = perf_counter()
    loaded_config = load_app_config(paths)
    app_config = loaded_config.app

    foundation_started = perf_counter()
    foundation_snapshot = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=True,
        include_equity_histories=True,
        include_market_snapshots=False,
    )
    foundation_seconds = perf_counter() - foundation_started

    tool_a_tickers = [
        ticker.ticker
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_a_enabled
    ]

    structural_started = perf_counter()
    per_ticker: list[dict[str, object]] = []

    def record_ticker(
        ticker: str,
        ticker_data: StructuralTickerData,
        elapsed_seconds: float | None,
    ) -> None:
        per_ticker.append(
            {
                "ticker": ticker,
                "duration_seconds": (
                    round(elapsed_seconds, 4) if elapsed_seconds is not None else None
                ),
                "structural_rows": int(len(ticker_data.structural_window_metrics.index)),
                "weekly_rows": int(len(ticker_data.weekly_series.index)),
            }
        )

    structural_frames = build_structural_history_frames(
        tickers=tool_a_tickers,
        normalized_equity_histories=foundation_snapshot.normalized_equity_histories,
        gold_history=foundation_snapshot.gold_history,
        scoring_config=app_config.scoring,
        on_ticker_built=record_ticker,
        timer=perf_counter,
    )
    structural_window_metrics = structural_frames.structural_window_metrics
    weekly_series = structural_frames.weekly_series
    structural_seconds = perf_counter() - structural_started

    volatility_started = perf_counter()
    volatility_diagnostics = compute_volatility_diagnostics(
        weekly_series=weekly_series,
        structural_window_metrics=structural_window_metrics,
        scoring_config=app_config.scoring,
    )
    volatility_seconds = perf_counter() - volatility_started

    output_started = perf_counter()
    tool_a_outputs = _build_tool_a_outputs(
        structural_window_metrics=structural_window_metrics,
        volatility_diagnostics=volatility_diagnostics,
        app_config=app_config,
        run_context=_PerfRunContext(),
        snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
    )
    output_seconds = perf_counter() - output_started

    rank_started = perf_counter()
    if not tool_a_outputs.empty:
        tool_a_outputs = rank_tool_a_outputs(tool_a_outputs)
        tool_a_outputs = tool_a_outputs.sort_values(
            ["as_of_date", "tool_a_rank", "ticker"],
            ascending=[True, True, True],
            na_position="last",
        ).reset_index(drop=True)
    rank_seconds = perf_counter() - rank_started
    latest_tool_a = _latest_snapshot(tool_a_outputs)
    tool_a_compute_seconds = (
        structural_seconds
        + volatility_seconds
        + output_seconds
        + rank_seconds
    )
    tool_a_harness_stage_seconds = foundation_seconds + tool_a_compute_seconds

    profile: dict[str, Any] = {
        "foundation_refresh_run_id": foundation_snapshot.refresh_run_id,
        "foundation_snapshot_as_of_date": foundation_snapshot.snapshot_as_of_date,
        "config_hash": loaded_config.config_hash,
        "timings": {
            "load_foundation_snapshot_seconds": round(foundation_seconds, 4),
            "tool_a_structural_build_seconds": round(structural_seconds, 4),
            "tool_a_volatility_seconds": round(volatility_seconds, 4),
            "tool_a_output_assembly_seconds": round(output_seconds, 4),
            "tool_a_rank_seconds": round(rank_seconds, 4),
            "tool_a_compute_seconds": round(tool_a_compute_seconds, 4),
            "tool_a_harness_stage_seconds": round(tool_a_harness_stage_seconds, 4),
        },
        "row_counts": {
            "tool_a_ticker_count": len(tool_a_tickers),
            "structural_window_rows": int(len(structural_window_metrics.index)),
            "weekly_series_rows": int(len(weekly_series.index)),
            "volatility_rows": int(len(volatility_diagnostics.index)),
            "tool_a_output_rows": int(len(tool_a_outputs.index)),
            "tool_a_latest_rows": int(len(latest_tool_a.index)),
        },
        "slowest_tool_a_tickers": sorted(
            per_ticker,
            key=lambda row: float(row["duration_seconds"]),
            reverse=True,
        )[:10],
    }
    profile["real_run_reconciliation"] = _real_tool_a_reconciliation(
        paths=paths,
        harness_seconds=tool_a_harness_stage_seconds,
    )
    profile["option_artifacts"] = _profile_option_artifacts(
        paths=paths,
        app_config=app_config,
        config_hash=loaded_config.config_hash,
    )
    profile["timings"]["cached_compute_profile_seconds"] = round(
        perf_counter() - profile_started,
        4,
    )
    return profile


def format_cached_perf_profile(profile: dict[str, Any]) -> str:
    """Return a human-readable perf-profile report."""

    timings = dict(profile.get("timings") or {})
    row_counts = dict(profile.get("row_counts") or {})
    option_artifacts = dict(profile.get("option_artifacts") or {})
    option_timings = dict(option_artifacts.get("timings") or {})
    option_rows = dict(option_artifacts.get("row_counts") or {})

    lines = [
        "Cached performance profile",
        "No Yahoo calls; no model artifacts written.",
        "",
        f"Foundation refresh: {profile.get('foundation_refresh_run_id') or '-'}",
        f"Snapshot as-of: {profile.get('foundation_snapshot_as_of_date') or '-'}",
        "",
        "Tool A",
        f"  tickers: {row_counts.get('tool_a_ticker_count', 0)}",
        f"  structural rows: {row_counts.get('structural_window_rows', 0)}",
        f"  weekly rows: {row_counts.get('weekly_series_rows', 0)}",
        f"  volatility rows: {row_counts.get('volatility_rows', 0)}",
        f"  output rows built: {row_counts.get('tool_a_output_rows', 0)}",
        f"  latest rows kept: {row_counts.get('tool_a_latest_rows', 0)}",
        _format_seconds(
            "  load foundation snapshot",
            timings.get("load_foundation_snapshot_seconds"),
        ),
        _format_seconds(
            "  structural build",
            timings.get("tool_a_structural_build_seconds"),
        ),
        _format_seconds("  volatility diagnostics", timings.get("tool_a_volatility_seconds")),
        _format_seconds("  output assembly", timings.get("tool_a_output_assembly_seconds")),
        _format_seconds("  rank outputs", timings.get("tool_a_rank_seconds")),
        _format_seconds("  Tool A compute", timings.get("tool_a_compute_seconds")),
        _format_seconds("  Tool A cached path", timings.get("tool_a_harness_stage_seconds")),
        "",
        "Slowest Tool A tickers",
    ]
    for row in profile.get("slowest_tool_a_tickers") or []:
        lines.append(
            "  {ticker}: {duration_seconds:.4f}s "
            "(structural={structural_rows}, weekly={weekly_rows})".format(**row)
        )

    reconciliation = dict(profile.get("real_run_reconciliation") or {})
    if reconciliation:
        lines.extend(
            [
                "",
                "Real-run reconciliation",
                f"  status: {reconciliation.get('status', '-')}",
                _format_seconds(
                    "  latest real Tool A stage",
                    reconciliation.get("real_stage_seconds"),
                ),
                _format_seconds(
                    "  cached harness Tool A path",
                    reconciliation.get("harness_seconds"),
                ),
                f"  ratio: {reconciliation.get('ratio', '-')}",
            ]
        )

    lines.extend(
        [
            "",
            "Option artifacts",
            f"  status: {option_artifacts.get('status', '-')}",
        ]
    )
    if option_artifacts.get("status") == "available":
        lines.extend(
            [
                f"  chains: {option_rows.get('chains', 0)}",
                f"  chain scans: {option_rows.get('chain_scans', 0)}",
                f"  contract metrics: {option_rows.get('contract_metrics', 0)}",
                f"  frame rows: {json.dumps(option_rows.get('frames', {}), sort_keys=True)}",
                _format_seconds("  load option sources", option_timings.get("load_sources_seconds")),
                _format_seconds("  scan chains once", option_timings.get("scan_chains_seconds")),
                _format_seconds("  build inputs", option_timings.get("build_inputs_seconds")),
                _format_seconds(
                    "  contract metrics",
                    option_timings.get("contract_metrics_seconds"),
                ),
                _format_seconds("  build frames", option_timings.get("build_frames_seconds")),
                _format_seconds("  option artifact compute", option_timings.get("total_seconds")),
            ]
        )
    else:
        lines.append(f"  reason: {option_artifacts.get('reason', '-')}")

    lines.extend(
        [
            "",
            _format_seconds(
                "Total cached profile",
                timings.get("cached_compute_profile_seconds"),
            ),
        ]
    )
    return "\n".join(lines)


def _profile_option_artifacts(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    config_hash: str,
) -> dict[str, Any]:
    load_started = perf_counter()
    sources = load_option_artifact_source_inputs(paths, use_model_state=False)
    load_seconds = perf_counter() - load_started
    if sources is None:
        return {
            "status": "missing",
            "reason": "No latest options manifest is available.",
            "timings": {"load_sources_seconds": round(load_seconds, 4)},
            "row_counts": {},
        }

    scan_started = perf_counter()
    scans = scan_option_chains_for_artifacts(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
    )
    scan_seconds = perf_counter() - scan_started

    build_started = perf_counter()
    built = build_option_artifact_inputs(
        app_config=app_config,
        features=sources.features,
        tool_a=sources.tool_a,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
        manifest=sources.manifest,
        scans_by_ticker=scans,
    )
    build_seconds = perf_counter() - build_started

    metrics_started = perf_counter()
    contract_metrics = scan_option_contract_metrics(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
        scans_by_ticker=scans,
    )
    metrics_seconds = perf_counter() - metrics_started

    frames_started = perf_counter()
    frames = build_option_artifact_frames(
        built=built,
        contract_metrics=contract_metrics,
        options_features=sources.features,
        manifest=sources.manifest,
        source_run_id="perf-profile",
        parent_refresh_id="perf-profile",
        config_hash=config_hash,
        risk_free_rate=sources.risk_free_rate,
        risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
    )
    frames_seconds = perf_counter() - frames_started

    return {
        "status": "available",
        "options_refresh_run_id": str(sources.manifest.get("refresh_run_id") or ""),
        "options_as_of_date": str(sources.manifest.get("as_of_date") or ""),
        "timings": {
            "load_sources_seconds": round(load_seconds, 4),
            "scan_chains_seconds": round(scan_seconds, 4),
            "build_inputs_seconds": round(build_seconds, 4),
            "contract_metrics_seconds": round(metrics_seconds, 4),
            "build_frames_seconds": round(frames_seconds, 4),
            "total_seconds": round(
                load_seconds
                + scan_seconds
                + build_seconds
                + metrics_seconds
                + frames_seconds,
                4,
            ),
        },
        "row_counts": {
            "chains": len(sources.chains),
            "chain_scans": len(scans),
            "contract_metrics": len(contract_metrics),
            "frames": {name: int(len(frame.index)) for name, frame in frames.items()},
        },
    }


def _real_tool_a_reconciliation(
    *,
    paths: ProjectPaths,
    harness_seconds: float,
) -> dict[str, object]:
    manifest = load_current_model_state_manifest(paths)
    if not manifest:
        return {"status": "missing_model_state", "harness_seconds": round(harness_seconds, 4)}
    stage_timings = manifest.get("stage_timings")
    if not isinstance(stage_timings, dict):
        return {"status": "missing_stage_timings", "harness_seconds": round(harness_seconds, 4)}
    tool_a = stage_timings.get("tool_a")
    if not isinstance(tool_a, dict):
        return {"status": "missing_tool_a_timing", "harness_seconds": round(harness_seconds, 4)}
    real_seconds = _optional_float(tool_a.get("duration_seconds"))
    if real_seconds is None or real_seconds <= 0:
        return {"status": "missing_tool_a_duration", "harness_seconds": round(harness_seconds, 4)}
    ratio = round(float(harness_seconds) / real_seconds, 4)
    status = "ok" if 0.85 <= ratio <= 1.15 else "diverged"
    return {
        "status": status,
        "real_stage_seconds": round(real_seconds, 4),
        "harness_seconds": round(harness_seconds, 4),
        "ratio": ratio,
    }


def _format_seconds(label: str, value: object) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return f"{label}: -"
    return f"{label}: {seconds:.4f}s"
