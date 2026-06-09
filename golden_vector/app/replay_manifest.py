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

from golden_vector.common.files import repo_relative as _repo_relative
from golden_vector.common.files import sha256_file as _sha256_file
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
OPTIONS_MANIFEST_SNAPSHOT_FILE = "options_manifest.json"
TOOL_C_SNAPSHOT_DIR = "tool_c"
TOOL_D_SNAPSHOT_DIR = "tool_d"

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
        "options_manifest_captured": None,
        "options_manifest_status": "not-applicable",
        "tool_c_sources_captured": None,
        "tool_c_sources_status": "not-applicable",
        "tool_d_sources_captured": None,
        "tool_d_sources_status": "not-applicable",
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
            "source_assets": _foundation_source_assets(run_dir, snapshot_path),
        }
        manifest["foundation_load_status"] = "captured"
    except Exception as exc:  # noqa: BLE001 - phase 2 must record and proceed.
        manifest["foundation_run_consumed"] = None
        manifest["foundation_load_status"] = f"error: {exc}"

    try:
        _write_json_atomic(manifest_path, manifest)
    except Exception:
        return


def update_manifest_with_options(
    run_dir: Path,
    *,
    options_manifest_path: Path,
) -> None:
    """Patch a replay manifest with the latest options manifest it produced."""

    manifest_path = run_dir / REPLAY_MANIFEST_FILE
    try:
        manifest = _read_manifest_path(manifest_path)
    except Exception:
        return

    snapshot_path = run_dir / REPLAY_SNAPSHOT_DIR / OPTIONS_MANIFEST_SNAPSHOT_FILE
    try:
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        _copy_file_atomic(options_manifest_path, snapshot_path)
        manifest["options_manifest_captured"] = {
            "manifest_original_path": _best_effort_run_repo_relative(
                run_dir,
                options_manifest_path,
            ),
            "snapshot_path": _run_relative(run_dir, snapshot_path),
            "latest_options_manifest_sha256": _sha256_file(snapshot_path),
            "source_assets": _options_source_assets(run_dir, snapshot_path),
        }
        manifest["options_manifest_status"] = "captured"
    except Exception as exc:  # noqa: BLE001 - options capture should record and proceed.
        manifest["options_manifest_captured"] = None
        manifest["options_manifest_status"] = f"error: {exc}"

    try:
        _write_json_atomic(manifest_path, manifest)
    except Exception:
        return


def update_manifest_with_tool_c_sources(
    run_dir: Path,
    *,
    source_paths: dict[str, Path],
) -> list[Path]:
    """Patch a replay manifest with Tool C source snapshots."""

    return _update_manifest_with_named_sources(
        run_dir,
        field_name="tool_c_sources_captured",
        status_field_name="tool_c_sources_status",
        snapshot_subdir=TOOL_C_SNAPSHOT_DIR,
        source_paths=source_paths,
    )


def update_manifest_with_tool_d_sources(
    run_dir: Path,
    *,
    source_paths: dict[str, Path],
    metadata: dict[str, Any] | None = None,
) -> list[Path]:
    """Patch a replay manifest with Tool D source snapshots."""

    return _update_manifest_with_named_sources(
        run_dir,
        field_name="tool_d_sources_captured",
        status_field_name="tool_d_sources_status",
        snapshot_subdir=TOOL_D_SNAPSHOT_DIR,
        source_paths=source_paths,
        metadata=metadata,
    )


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

    options_data = manifest.get("options_manifest_captured")
    if options_data:
        asset_statuses.append(
            _verify_snapshot_asset(
                run_dir,
                name=OPTIONS_MANIFEST_SNAPSHOT_FILE,
                snapshot_path=Path(str(options_data.get("snapshot_path", ""))),
                expected_sha256=str(options_data.get("latest_options_manifest_sha256", "")),
            )
        )

    for source_block_name in ("tool_c_sources_captured", "tool_d_sources_captured"):
        source_block = manifest.get(source_block_name)
        if not source_block:
            continue
        for source_asset in _valid_source_assets(source_block.get("source_assets", [])):
            asset_statuses.append(
                _verify_snapshot_asset(
                    run_dir,
                    name=str(source_asset.get("name", "source_asset")),
                    snapshot_path=Path(str(source_asset.get("snapshot_path", ""))),
                    expected_sha256=str(source_asset.get("sha256", "")),
                )
            )

    failed = any(asset.status != "ok" for asset in asset_statuses)
    return VerifyResult(
        run_dir=run_dir,
        manifest_path=manifest_path,
        verdict=VERDICT_SNAPSHOT_INTEGRITY_FAILED if failed else VERDICT_OK,
        asset_statuses=asset_statuses,
        drift_findings=_current_checkout_drift_findings(manifest, run_dir=run_dir),
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


def _manifest_source_assets(manifest: dict[str, Any]) -> list[dict[str, str | None]]:
    assets: list[dict[str, str | None]] = []
    foundation_data = manifest.get("foundation_run_consumed") or {}
    assets.extend(_valid_source_assets(foundation_data.get("source_assets", [])))
    options_data = manifest.get("options_manifest_captured") or {}
    assets.extend(_valid_source_assets(options_data.get("source_assets", [])))
    tool_c_data = manifest.get("tool_c_sources_captured") or {}
    assets.extend(_valid_source_assets(tool_c_data.get("source_assets", [])))
    tool_d_data = manifest.get("tool_d_sources_captured") or {}
    assets.extend(_valid_source_assets(tool_d_data.get("source_assets", [])))
    return assets


def _valid_source_assets(raw_assets: object) -> list[dict[str, str | None]]:
    if not isinstance(raw_assets, list):
        return []
    assets: list[dict[str, str | None]] = []
    for raw_asset in raw_assets:
        if not isinstance(raw_asset, dict):
            continue
        original_path = str(raw_asset.get("original_path", "")).strip()
        if not original_path:
            continue
        assets.append(
            {
                "name": str(raw_asset.get("name", "source_asset")),
                "original_path": original_path,
                "snapshot_path": str(raw_asset.get("snapshot_path", "")),
                "sha256": _optional_sha256(raw_asset.get("sha256")) or "",
            }
        )
    return assets


def _resolve_run_dir(run_dir_or_id: Path | str) -> Path:
    if isinstance(run_dir_or_id, Path):
        return run_dir_or_id

    candidate = Path(run_dir_or_id)
    if candidate.is_absolute() or candidate.exists() or any(
        separator in run_dir_or_id for separator in ("/", "\\")
    ):
        return candidate
    return ProjectPaths.discover().runs_dir / run_dir_or_id


def _current_checkout_drift_findings(
    manifest: dict[str, Any],
    *,
    run_dir: Path,
) -> list[str]:
    try:
        ProjectPaths.discover()
    except Exception:
        return ["unavailable - no current checkout context"]
    findings: list[str] = []

    assets = _manifest_original_assets(manifest)
    assets.extend(
        (
            str(source_asset.get("name", "source_asset")),
            str(source_asset.get("original_path", "")),
            _optional_sha256(source_asset.get("sha256")) or "",
        )
        for source_asset in _manifest_source_assets(manifest)
    )

    for name, original_path, expected_sha256 in assets:
        if not original_path:
            continue
        if not expected_sha256:
            findings.append(
                f"[WARN] {name} was unavailable when the run snapshot was captured"
            )
            continue
        current_path = _resolve_original_asset_path(run_dir, Path(original_path))
        if not current_path.exists():
            findings.append(f"[WARN] {name} is missing from the current checkout")
            continue

        actual_sha256 = _sha256_file(current_path)
        if actual_sha256 == expected_sha256:
            findings.append(f"[OK] {name} matches the run snapshot")
        else:
            findings.append(f"[WARN] {name} differs from the run snapshot")

    return findings


def _manifest_original_assets(
    manifest: dict[str, Any],
) -> list[tuple[str, str, str]]:
    assets: list[tuple[str, str, str]] = []
    for config in manifest.get("configs", []):
        assets.append(
            (
                str(config.get("name", "config")),
                str(config.get("original_path", "")),
                str(config.get("sha256", "")),
            )
        )

    manual_data = manifest.get("manual_data")
    if manual_data:
        assets.append(
            (
                MANUAL_DB_SNAPSHOT_FILE,
                str(manual_data.get("original_path", "")),
                str(manual_data.get("sha256", "")),
            )
        )

    foundation_data = manifest.get("foundation_run_consumed")
    if foundation_data:
        assets.append(
            (
                FOUNDATION_MANIFEST_SNAPSHOT_FILE,
                str(foundation_data.get("manifest_original_path", "")),
                str(foundation_data.get("manifest_sha256", "")),
            )
        )

    return [
        (name, original_path, expected_sha256)
        for name, original_path, expected_sha256 in assets
        if original_path and expected_sha256
    ]


def _foundation_source_assets(
    run_dir: Path,
    foundation_manifest_path: Path,
) -> list[dict[str, str | None]]:
    try:
        foundation_manifest = _read_manifest_path(foundation_manifest_path)
    except Exception:
        return []

    fields = (
        ("foundation:raw_gold.parquet", "gold_history_path"),
        ("foundation:raw_equities.parquet", "raw_equities_snapshot_path"),
        ("foundation:raw_fx.parquet", "raw_fx_snapshot_path"),
        ("foundation:usd_equities.parquet", "normalized_equities_snapshot_path"),
        (
            "foundation:market_snapshots_usd.parquet",
            "normalized_market_snapshots_snapshot_path",
        ),
    )
    assets: list[dict[str, str | None]] = []
    for name, field_name in fields:
        raw_path = str(foundation_manifest.get(field_name, "")).strip()
        asset = _source_asset_record(run_dir, name=name, raw_path=raw_path)
        if asset is not None:
            assets.append(asset)
    return assets


def _options_source_assets(
    run_dir: Path,
    options_manifest_path: Path,
) -> list[dict[str, str | None]]:
    try:
        options_manifest = _read_manifest_path(options_manifest_path)
    except Exception:
        return []

    assets: list[dict[str, str | None]] = []
    for snapshot in options_manifest.get("snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        raw_path = str(snapshot.get("snapshot_path", "")).strip()
        expected_sha256 = str(snapshot.get("sha256", "")).strip()
        if not raw_path or not expected_sha256:
            continue
        ticker = str(snapshot.get("ticker", "unknown")).strip() or "unknown"
        assets.append(
            {
                "name": f"options:{ticker}.parquet",
                "original_path": raw_path,
                "sha256": expected_sha256,
            }
        )

    benchmark_paths = options_manifest.get("benchmark_snapshot_paths", [])
    for index, raw_path_obj in enumerate(benchmark_paths, start=1):
        raw_path = str(raw_path_obj).strip()
        asset = _source_asset_record(
            run_dir,
            name=f"options:benchmark:{index}",
            raw_path=raw_path,
        )
        if asset is not None:
            assets.append(asset)
    return assets


def _source_asset_record(
    run_dir: Path,
    *,
    name: str,
    raw_path: str,
) -> dict[str, str | None] | None:
    if not raw_path:
        return None
    resolved_path = _resolve_original_asset_path(run_dir, Path(raw_path))
    if not resolved_path.exists():
        return {
            "name": name,
            "original_path": raw_path,
            "sha256": None,
        }
    return {
        "name": name,
        "original_path": raw_path,
        "sha256": _sha256_file(resolved_path),
    }


def _update_manifest_with_named_sources(
    run_dir: Path,
    *,
    field_name: str,
    status_field_name: str,
    snapshot_subdir: str,
    source_paths: dict[str, Path],
    metadata: dict[str, Any] | None = None,
) -> list[Path]:
    manifest_path = run_dir / REPLAY_MANIFEST_FILE
    copied_paths: list[Path] = []
    try:
        manifest = _read_manifest_path(manifest_path)
    except Exception:
        return copied_paths

    try:
        source_assets: list[dict[str, str]] = []
        snapshot_dir = run_dir / REPLAY_SNAPSHOT_DIR / snapshot_subdir
        for name, source_path in sorted(source_paths.items()):
            snapshot_path = snapshot_dir / _safe_snapshot_file_name(name, source_path)
            _copy_file_atomic(source_path, snapshot_path)
            copied_paths.append(snapshot_path)
            source_assets.append(
                {
                    "name": name,
                    "original_path": _best_effort_run_repo_relative(run_dir, source_path),
                    "snapshot_path": _run_relative(run_dir, snapshot_path),
                    "sha256": _sha256_file(snapshot_path),
                }
            )
        block: dict[str, Any] = {"source_assets": source_assets}
        if metadata:
            block["metadata"] = metadata
        manifest[field_name] = block
        manifest[status_field_name] = "captured"
    except Exception as exc:  # noqa: BLE001 - source provenance should record and proceed.
        manifest[field_name] = None
        manifest[status_field_name] = f"error: {exc}"
        copied_paths = []

    try:
        _write_json_atomic(manifest_path, manifest)
    except Exception:
        return copied_paths
    return copied_paths


def _safe_snapshot_file_name(name: str, source_path: Path) -> str:
    safe_name = str(name).strip() or source_path.stem
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
        safe_name = safe_name.replace(old, new)
    suffix = source_path.suffix or ".dat"
    if safe_name.endswith(suffix):
        return safe_name
    return f"{safe_name}{suffix}"


def _resolve_original_asset_path(run_dir: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    try:
        run_repo_candidate = run_dir.parents[2] / path
    except IndexError:
        run_repo_candidate = path
    if _run_dir_is_repo_run_dir(run_dir):
        return run_repo_candidate
    if run_repo_candidate.exists():
        return run_repo_candidate
    try:
        checkout_candidate = ProjectPaths.discover().repo_root / path
        if checkout_candidate.exists():
            return checkout_candidate
    except Exception:
        pass
    return run_repo_candidate


def _run_dir_is_repo_run_dir(run_dir: Path) -> bool:
    return run_dir.parent.name == "runs" and run_dir.parent.parent.name == "data"


def _optional_sha256(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _run_relative(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _best_effort_repo_relative(path: Path) -> str:
    try:
        return path.relative_to(ProjectPaths.discover().repo_root).as_posix()
    except ValueError:
        return str(path)


def _best_effort_run_repo_relative(run_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(run_dir.parents[2]).as_posix()
    except (IndexError, ValueError):
        return _best_effort_repo_relative(path)
