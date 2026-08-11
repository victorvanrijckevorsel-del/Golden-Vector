"""Persist run-local options snapshots and the latest options manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.common.files import atomic_write_text
from golden_vector.common.files import repo_relative as _repo_relative
from golden_vector.common.files import sha256_file as _sha256_file
from golden_vector.common.parquet import write_parquet_atomic
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
    # "OK" when this run produced a feature row for the ticker; "ERROR" when the raw
    # snapshot persisted but feature computation failed. Recording the ERROR ticker
    # (instead of dropping it) lets readers tell "errored" from "not in this run".
    feature_status: str = "OK"
    # How many expirations the vendor enumeration returned (fetch collection
    # stats). Numeric evidence for availability: 0 with a successful fetch means
    # "nothing listed"; >0 with no rows means the configured window filtered them
    # away. None = legacy/unknown, and readers fall back to the message text.
    expiration_count_available: int | None = None

    def manifest_entry(self, paths: ProjectPaths) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "options_available": self.options_available,
            "row_count": self.row_count,
            "snapshot_path": _repo_relative(paths, self.snapshot_path),
            "sha256": self.sha256,
            "message": self.message,
            "feature_status": self.feature_status,
            "expiration_count_available": self.expiration_count_available,
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

    snapshot = build_options_snapshot_frame(
        frame=frame,
        ticker=ticker,
        as_of_date=as_of_date,
        run_id=run_context.run_id,
        options_available=options_available,
        message=message,
    )
    return persist_options_snapshot_frame(
        paths=paths,
        run_context=run_context,
        ticker=ticker,
        snapshot=snapshot,
        options_available=options_available,
        message=message,
    )


def persist_options_snapshot_frame(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    ticker: str,
    snapshot: pd.DataFrame,
    options_available: bool,
    message: str | None = None,
) -> OptionsSnapshotRecord:
    """Write an already identity-stamped options snapshot frame."""

    snapshot_path = _options_snapshot_dir(run_context) / f"{safe_options_file_name(ticker)}.parquet"
    write_parquet_atomic(snapshot, snapshot_path, index=False)
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
    atomic_write_text(
        manifest_path,
        json.dumps(to_jsonable(payload), indent=2, sort_keys=True),
    )
    run_context.record_artifact(manifest_path)
    return manifest_path


def build_options_snapshot_frame(
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


def safe_options_file_name(value: str) -> str:
    """Return the stable filesystem name for one options ticker artifact."""

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
