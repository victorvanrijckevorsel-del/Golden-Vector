"""Replay manifest writer and verifier."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING

from golden_vector.app.config import expected_config_paths
from golden_vector.app.paths import ProjectPaths

if TYPE_CHECKING:
    from golden_vector.app.run_context import RunContext


MANIFEST_VERSION = 1
REPLAY_MANIFEST_FILE = "replay_manifest.json"
REPLAY_SNAPSHOT_DIR = "replay_snapshots"
CONFIG_SNAPSHOT_DIR = "configs"
MANUAL_DB_SNAPSHOT_FILE = "manual_screening.sqlite3"
FOUNDATION_MANIFEST_SNAPSHOT_FILE = "foundation_manifest.json"

VERDICT_OK = "OK"
VERDICT_PREDATES_REPLAY_MANIFEST = "PREDATES_REPLAY_MANIFEST"
VERDICT_SNAPSHOT_INTEGRITY_FAILED = "SNAPSHOT_INTEGRITY_FAILED"


@dataclass(frozen=True)
class VerifyAssetStatus:
    """Integrity status for one replay snapshot asset."""

    name: str
    snapshot_path: Path
    expected_sha256: str | None
    actual_sha256: str | None
    status: str
    message: str


@dataclass(frozen=True)
class VerifyResult:
    """Replay manifest verification result."""

    run_dir: Path
    manifest_path: Path
    verdict: str
    asset_statuses: list[VerifyAssetStatus] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    drift_findings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.verdict in {VERDICT_OK, VERDICT_PREDATES_REPLAY_MANIFEST}


def write_initial_replay_manifest(run_context: RunContext) -> Path:
    """Write phase-1 replay inputs: configs, manual data, and git state."""

    snapshot_dir = run_context.run_dir / REPLAY_SNAPSHOT_DIR
    config_snapshot_dir = snapshot_dir / CONFIG_SNAPSHOT_DIR
    config_snapshot_dir.mkdir(parents=True, exist_ok=True)

    configs = [
        _snapshot_config(run_context.paths, source_path, config_snapshot_dir)
        for source_path in expected_config_paths(run_context.paths).values()
    ]
    manual_data = _snapshot_manual_database(run_context.paths, snapshot_dir)

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "run_id": run_context.run_id,
        "command": run_context.command,
        "started_at_utc": run_context.started_at_utc,
        "git": _git_state(run_context.paths.repo_root),
        "configs": configs,
        "manual_data": manual_data,
        "foundation_run_consumed": None,
        "foundation_load_status": "not-applicable",
    }

    manifest_path = run_context.run_dir / REPLAY_MANIFEST_FILE
    _write_json_atomic(manifest_path, manifest)
    run_context.record_artifact(manifest_path)
    return manifest_path


def update_manifest_with_foundation(
    run_dir: Path,
    *,
    foundation_run_id: str,
    foundation_manifest_path: Path,
) -> None:
    """Patch a replay manifest with the foundation snapshot it consumed."""

    manifest_path = run_dir / REPLAY_MANIFEST_FILE
    try:
        manifest = _read_manifest_path(manifest_path)
    except Exception:
        return

    snapshot_path = run_dir / REPLAY_SNAPSHOT_DIR / FOUNDATION_MANIFEST_SNAPSHOT_FILE
    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_atomic(foundation_manifest_path, snapshot_path)
        manifest["foundation_run_consumed"] = {
            "run_id": foundation_run_id,
            "manifest_original_path": _best_effort_repo_relative(foundation_manifest_path),
            "snapshot_path": _run_relative(run_dir, snapshot_path),
            "manifest_sha256": _sha256_file(snapshot_path),
        }
        manifest["foundation_load_status"] = "captured"
    except Exception as exc:  # noqa: BLE001 - phase 2 must record and proceed.
        manifest["foundation_run_consumed"] = None
        manifest["foundation_load_status"] = f"error: {exc}"

    try:
        _write_json_atomic(manifest_path, manifest)
    except Exception:
        return


def read_manifest(run_dir_or_id: Path | str) -> dict[str, Any]:
    return _read_manifest_path(_resolve_run_dir(run_dir_or_id) / REPLAY_MANIFEST_FILE)


def verify_manifest(run_dir_or_id: Path | str) -> VerifyResult:
    run_dir = _resolve_run_dir(run_dir_or_id)
    manifest_path = run_dir / REPLAY_MANIFEST_FILE
    if not manifest_path.exists():
        return VerifyResult(
            run_dir=run_dir,
            manifest_path=manifest_path,
            verdict=VERDICT_PREDATES_REPLAY_MANIFEST,
            messages=["run predates replay manifests"],
        )

    manifest = _read_manifest_path(manifest_path)
    asset_statuses: list[VerifyAssetStatus] = []

    for config in manifest.get("configs", []):
        asset_statuses.append(
            _verify_snapshot_asset(
                run_dir,
                name=str(config.get("name", "config")),
                snapshot_path=Path(str(config.get("snapshot_path", ""))),
                expected_sha256=str(config.get("sha256", "")),
            )
        )

    manual_data = manifest.get("manual_data")
    if manual_data:
        asset_statuses.append(
            _verify_snapshot_asset(
                run_dir,
                name=MANUAL_DB_SNAPSHOT_FILE,
                snapshot_path=Path(str(manual_data.get("snapshot_path", ""))),
                expected_sha256=str(manual_data.get("sha256", "")),
            )
        )

    foundation_data = manifest.get("foundation_run_consumed")
    if foundation_data:
        asset_statuses.append(
            _verify_snapshot_asset(
                run_dir,
                name=FOUNDATION_MANIFEST_SNAPSHOT_FILE,
                snapshot_path=Path(str(foundation_data.get("snapshot_path", ""))),
                expected_sha256=str(foundation_data.get("manifest_sha256", "")),
            )
        )

    failed = any(asset.status != "ok" for asset in asset_statuses)
    return VerifyResult(
        run_dir=run_dir,
        manifest_path=manifest_path,
        verdict=VERDICT_SNAPSHOT_INTEGRITY_FAILED if failed else VERDICT_OK,
        asset_statuses=asset_statuses,
    )


def _snapshot_config(
    paths: ProjectPaths,
    source_path: Path,
    config_snapshot_dir: Path,
) -> dict[str, str]:
    snapshot_path = config_snapshot_dir / source_path.name
    _copy_file_atomic(source_path, snapshot_path)
    return {
        "name": source_path.name,
        "original_path": _repo_relative(paths, source_path),
        "snapshot_path": _run_relative(config_snapshot_dir.parents[1], snapshot_path),
        "sha256": _sha256_file(snapshot_path),
    }


def _snapshot_manual_database(
    paths: ProjectPaths,
    snapshot_dir: Path,
) -> dict[str, str] | None:
    manual_db_path = paths.manual_screening_store_path
    if not manual_db_path.exists():
        return None

    snapshot_path = snapshot_dir / MANUAL_DB_SNAPSHOT_FILE
    _backup_sqlite_database(manual_db_path, snapshot_path)
    return {
        "original_path": _repo_relative(paths, manual_db_path),
        "snapshot_path": _run_relative(snapshot_dir.parent, snapshot_path),
        "sha256": _sha256_file(snapshot_path),
    }


def _backup_sqlite_database(source_path: Path, snapshot_path: Path) -> None:
    tmp_path = snapshot_path.with_name(f"{snapshot_path.name}.tmp")
    tmp_path.unlink(missing_ok=True)
    try:
        source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
        with closing(
            sqlite3.connect(source_uri, uri=True, timeout=5.0)
        ) as source_connection:
            with closing(sqlite3.connect(tmp_path, timeout=5.0)) as snapshot_connection:
                source_connection.backup(snapshot_connection)
                snapshot_connection.commit()
        os.replace(tmp_path, snapshot_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _git_state(repo_root: Path) -> dict[str, str | bool | None]:
    try:
        commit_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001 - git provenance is best-effort.
        return {
            "commit": None,
            "dirty": None,
            "unavailable_reason": str(exc),
        }

    return {
        "commit": commit_result.stdout.strip(),
        "dirty": bool(status_result.stdout.strip()),
        "unavailable_reason": None,
    }


def _verify_snapshot_asset(
    run_dir: Path,
    *,
    name: str,
    snapshot_path: Path,
    expected_sha256: str,
) -> VerifyAssetStatus:
    resolved_snapshot_path = (
        snapshot_path if snapshot_path.is_absolute() else run_dir / snapshot_path
    )
    if not resolved_snapshot_path.exists():
        return VerifyAssetStatus(
            name=name,
            snapshot_path=resolved_snapshot_path,
            expected_sha256=expected_sha256,
            actual_sha256=None,
            status="missing",
            message="snapshot file is missing",
        )

    actual_sha256 = _sha256_file(resolved_snapshot_path)
    if actual_sha256 != expected_sha256:
        return VerifyAssetStatus(
            name=name,
            snapshot_path=resolved_snapshot_path,
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
            status="hash_mismatch",
            message="snapshot hash does not match manifest",
        )

    return VerifyAssetStatus(
        name=name,
        snapshot_path=resolved_snapshot_path,
        expected_sha256=expected_sha256,
        actual_sha256=actual_sha256,
        status="ok",
        message="sha256 matches recorded",
    )


def _resolve_run_dir(run_dir_or_id: Path | str) -> Path:
    if isinstance(run_dir_or_id, Path):
        return run_dir_or_id

    candidate = Path(run_dir_or_id)
    if candidate.is_absolute() or candidate.exists() or any(
        separator in run_dir_or_id for separator in ("/", "\\")
    ):
        return candidate
    return ProjectPaths.discover().runs_dir / run_dir_or_id


def _copy_file_atomic(source_path: Path, target_path: Path) -> None:
    if not source_path.exists():
        raise FileNotFoundError(f"Required replay manifest source is missing: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        shutil.copyfile(source_path, tmp_path)
        os.replace(tmp_path, target_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _write_json_atomic(target_path: Path, payload: dict[str, Any]) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_path, target_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _read_manifest_path(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(paths: ProjectPaths, path: Path) -> str:
    return path.relative_to(paths.repo_root).as_posix()


def _run_relative(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _best_effort_repo_relative(path: Path) -> str:
    try:
        return path.relative_to(ProjectPaths.discover().repo_root).as_posix()
    except ValueError:
        return str(path)
