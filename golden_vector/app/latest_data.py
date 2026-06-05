"""Helpers for reading and writing the latest validated local market-data snapshot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.ingestion.foundation import FoundationExecutionResult
from golden_vector.ingestion.registry import build_foundation_registry


@dataclass(frozen=True)
class LatestFoundationSnapshot:
    refresh_run_id: str
    snapshot_as_of_date: str | None
    foundation_status: str
    raw_qa_summary: dict[str, Any]
    normalization_qa_summary: dict[str, Any]
    summary: dict[str, Any]
    gold_history: pd.DataFrame
    normalized_equity_histories: dict[str, pd.DataFrame]
    normalized_market_snapshots: pd.DataFrame
    manifest_path: Path


def write_latest_foundation_manifest(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    app_config: AppConfig,
    foundation_result: FoundationExecutionResult,
) -> Path:
    registry = build_foundation_registry(app_config.universe)
    payload = {
        "refresh_run_id": run_context.run_id,
        "command": run_context.command,
        "foundation_status": foundation_result.overall_status,
        "foundation_signature": _foundation_signature(app_config),
        "raw_qa_summary": foundation_result.raw_qa_report.summary(),
        "normalization_qa_summary": (
            foundation_result.normalization_qa_report.summary()
            if foundation_result.normalization_qa_report is not None
            else {"overall_status": "SKIPPED"}
        ),
        "snapshot_as_of_date": _snapshot_as_of_date(foundation_result),
        "gold_history_path": _repo_relative(
            paths,
            run_context.run_dir / "snapshots" / "raw_gold.parquet",
        ),
        "normalized_equities_snapshot_path": _repo_relative(
            paths,
            run_context.run_dir / "snapshots" / "usd_equities.parquet",
        ),
        "normalized_market_snapshots_snapshot_path": _repo_relative(
            paths,
            run_context.run_dir / "snapshots" / "market_snapshots_usd.parquet",
        ),
        "summary": foundation_result.summary,
    }
    manifest_path = paths.latest_foundation_manifest_path
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    run_context.record_artifact(manifest_path)
    return manifest_path


def load_latest_foundation_snapshot(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    include_gold_history: bool = True,
    include_equity_histories: bool = True,
    include_market_snapshots: bool = True,
    requested_tickers: list[str] | None = None,
    manifest_path: Path | None = None,
) -> LatestFoundationSnapshot:
    manifest_path = manifest_path or paths.latest_foundation_manifest_path
    if not manifest_path.exists():
        raise FileNotFoundError(
            "No validated local market-data snapshot exists yet. Run `python main.py update-data` first."
        )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    foundation_status = str(payload.get("foundation_status", ""))
    if foundation_status not in {"PASS", "WARN"}:
        raise ValueError(
            "Latest local market-data snapshot is not usable. Run `python main.py update-data` again."
        )
    _validate_foundation_signature(payload=payload, app_config=app_config)

    gold_history = pd.DataFrame()
    if include_gold_history:
        gold_history_path = paths.resolve_repo_relative(str(payload["gold_history_path"]))
        gold_history = _read_required_parquet(
            gold_history_path,
            description="gold history",
        )

    normalized_market_snapshots = pd.DataFrame()
    if include_market_snapshots:
        normalized_market_snapshots_path = paths.resolve_repo_relative(
            str(payload["normalized_market_snapshots_snapshot_path"])
        )
        normalized_market_snapshots = _read_required_parquet(
            normalized_market_snapshots_path,
            description="normalized market snapshots",
        )

    normalized_equity_histories: dict[str, pd.DataFrame] = {}
    if include_equity_histories:
        equity_snapshot_path = paths.resolve_repo_relative(
            str(payload["normalized_equities_snapshot_path"])
        )
        equity_snapshot = _read_required_parquet(
            equity_snapshot_path,
            description="normalized equity histories snapshot",
        )
        tickers_to_load = requested_tickers or [
            ticker.ticker
            for ticker in app_config.universe.tickers
            if ticker.active and ticker.tool_a_enabled
        ]
        equity_columns = list(equity_snapshot.columns)
        for ticker in tickers_to_load:
            if equity_snapshot.empty or "ticker" not in equity_snapshot.columns:
                normalized_equity_histories[ticker] = pd.DataFrame(columns=equity_columns)
                continue
            ticker_frame = equity_snapshot[equity_snapshot["ticker"].astype(str) == str(ticker)].copy()
            if ticker_frame.empty:
                normalized_equity_histories[ticker] = pd.DataFrame(columns=equity_columns)
            else:
                normalized_equity_histories[ticker] = ticker_frame.reset_index(drop=True)

    return LatestFoundationSnapshot(
        refresh_run_id=str(payload["refresh_run_id"]),
        snapshot_as_of_date=payload.get("snapshot_as_of_date"),
        foundation_status=foundation_status,
        raw_qa_summary=dict(payload.get("raw_qa_summary", {})),
        normalization_qa_summary=dict(payload.get("normalization_qa_summary", {})),
        summary=dict(payload.get("summary", {})),
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        normalized_market_snapshots=normalized_market_snapshots,
        manifest_path=manifest_path,
    )


def _snapshot_as_of_date(foundation_result: FoundationExecutionResult) -> str | None:
    if not foundation_result.normalized_market_snapshots.empty and "snapshot_date" in foundation_result.normalized_market_snapshots.columns:
        return str(foundation_result.normalized_market_snapshots["snapshot_date"].max())
    if not foundation_result.gold_history.empty and "date" in foundation_result.gold_history.columns:
        return str(foundation_result.gold_history["date"].max())
    return None


def _read_required_parquet(path: Path, *, description: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"Latest local snapshot is incomplete because {description} is missing: {path}"
        )
    return pd.read_parquet(path)


def _repo_relative(paths: ProjectPaths, path: Path) -> str:
    return path.relative_to(paths.repo_root).as_posix()


def _foundation_signature(app_config: AppConfig) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for ticker in app_config.universe.tickers:
        if not ticker.active or not (ticker.tool_a_enabled or ticker.tool_b_enabled):
            continue
        rows.append(
            {
                "ticker": ticker.ticker,
                "currency": ticker.currency,
                "tool_a_enabled": ticker.tool_a_enabled,
                "tool_b_enabled": ticker.tool_b_enabled,
            }
        )
    return {
        "universe": sorted(rows, key=lambda item: str(item["ticker"])),
        "refresh_policy": {
            "max_fx_staleness_days": int(app_config.qa.max_fx_staleness_days),
            "block_on_stale_fx": bool(app_config.qa.block_on_stale_fx),
        },
    }


def _validate_foundation_signature(*, payload: dict[str, Any], app_config: AppConfig) -> None:
    payload_signature = payload.get("foundation_signature")
    current_signature = _foundation_signature(app_config)
    if payload_signature != current_signature:
        raise ValueError(
            "The latest local market-data snapshot does not match the current active universe/currency configuration. "
            "Run `python main.py update-data` again."
        )
