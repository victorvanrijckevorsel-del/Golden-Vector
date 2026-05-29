"""Persist run-local options snapshots and the latest options manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext, to_jsonable

OPTIONS_MANIFEST_VERSION = 1


@dataclass(frozen=True)
class OptionsSnapshotRecord:
    ticker: str
    options_available: bool
    row_count: int
    snapshot_path: Path
    sha256: str
    message: str | None = None

    def manifest_entry(self, paths: ProjectPaths) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "options_available": self.options_available,
            "row_count": self.row_count,
            "snapshot_path": _repo_relative(paths, self.snapshot_path),
            "sha256": self.sha256,
            "message": self.message,
        }


def persist_options_snapshot(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    ticker: str,
    frame: pd.DataFrame,
    as_of_date: date,
    options_available: bool,
    message: str | None = None,
) -> OptionsSnapshotRecord:
    """Write one run-local options snapshot for a ticker.

    Empty/non-optionable chains still get a one-row marker so absence never
    has to mean either "not optionable" or "forgotten during persistence."
    """

    snapshot = _with_snapshot_identity(
        frame=frame,
        ticker=ticker,
        as_of_date=as_of_date,
        run_id=run_context.run_id,
        options_available=options_available,
        message=message,
    )
    snapshot_path = _options_snapshot_dir(run_context) / f"{_safe_name(ticker)}.parquet"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot.to_parquet(snapshot_path, index=False)
    run_context.record_artifact(snapshot_path)
    return OptionsSnapshotRecord(
        ticker=ticker,
        options_available=options_available,
        row_count=len(snapshot.index),
        snapshot_path=snapshot_path,
        sha256=_sha256_file(snapshot_path),
        message=message,
    )


def write_latest_options_manifest(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    as_of_date: date,
    snapshot_records: list[OptionsSnapshotRecord],
    risk_free_rate: float | None = None,
    benchmark_snapshot_paths: list[Path] | None = None,
    summary: dict[str, Any] | None = None,
) -> Path:
    """Write the latest-options pointer manifest for the current run."""

    manifest_path = paths.latest_options_manifest_path
    benchmark_paths = benchmark_snapshot_paths or []
    payload = {
        "manifest_version": OPTIONS_MANIFEST_VERSION,
        "refresh_run_id": run_context.run_id,
        "command": run_context.command,
        "as_of_date": as_of_date.isoformat(),
        "options_snapshot_dir": _repo_relative(paths, _options_snapshot_dir(run_context)),
        "risk_free_rate": risk_free_rate,
        "snapshots": [
            record.manifest_entry(paths)
            for record in sorted(snapshot_records, key=lambda item: item.ticker)
        ],
        "benchmark_snapshot_paths": [
            _repo_relative(paths, path)
            for path in sorted(benchmark_paths, key=lambda item: item.as_posix())
        ],
        "summary": summary or {},
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(to_jsonable(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    run_context.record_artifact(manifest_path)
    return manifest_path


def _with_snapshot_identity(
    *,
    frame: pd.DataFrame,
    ticker: str,
    as_of_date: date,
    run_id: str,
    options_available: bool,
    message: str | None,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            [
                {
                    "ticker": ticker,
                    "as_of_date": as_of_date.isoformat(),
                    "run_id": run_id,
                    "options_available": bool(options_available),
                    "empty_reason": message,
                }
            ]
        )

    snapshot = frame.copy()
    snapshot["ticker"] = ticker
    snapshot["as_of_date"] = as_of_date.isoformat()
    snapshot["run_id"] = run_id
    snapshot["options_available"] = bool(options_available)
    if "empty_reason" not in snapshot.columns:
        snapshot["empty_reason"] = None
    return snapshot


def _options_snapshot_dir(run_context: RunContext) -> Path:
    return run_context.run_dir / "snapshots" / "options"


def _repo_relative(paths: ProjectPaths, path: Path) -> str:
    return path.relative_to(paths.repo_root).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str) -> str:
    sanitized = value
    for old, new in (
        ("\\", "_"),
        ("/", "_"),
        (":", "_"),
        ("*", "_"),
        ("?", "_"),
        ('"', "_"),
        ("<", "_"),
        (">", "_"),
        ("|", "_"),
        ("=", "-"),
    ):
        sanitized = sanitized.replace(old, new)
    return sanitized
