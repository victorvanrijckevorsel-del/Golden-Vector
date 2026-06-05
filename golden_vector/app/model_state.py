"""Current model-state manifest helpers.

The model-state manifest is intentionally shaped as the future single atomic
pointer for a coherent Golden Vector build. I1 still lets existing readers use
their legacy latest aliases, but this contract is the path readers will resolve
through in I2/I3.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import to_jsonable

MODEL_STATE_MANIFEST_VERSION = 1

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "foundation",
    "options",
    "tool_a",
    "tool_b",
    "tool_c",
    "tool_d",
)

PLANNED_I3_ARTIFACTS: tuple[str, ...] = (
    "option_contract_metrics",
    "option_liquidity_measurements",
    "option_candidate_slots",
    "option_trading_overview",
    "candidate_finder_inputs",
)


def write_current_model_state_manifest(
    *,
    paths: ProjectPaths,
    config_hash: str | None,
    parent_refresh_id: str | None = None,
    stage_timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build and atomically publish the current model-state manifest."""

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash=config_hash,
        parent_refresh_id=parent_refresh_id,
        stage_timings=stage_timings,
    )
    target = paths.latest_model_state_manifest_path
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(to_jsonable(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(target)
    return payload


def load_current_model_state_manifest(paths: ProjectPaths) -> dict[str, Any] | None:
    """Load the latest model-state manifest, returning None when absent."""

    path = paths.latest_model_state_manifest_path
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_current_model_state_manifest(
    *,
    paths: ProjectPaths,
    config_hash: str | None,
    parent_refresh_id: str | None = None,
    stage_timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect current published artifacts and return a coherent-state manifest."""

    generated_at = _utc_now_iso()
    artifacts = _artifact_map(paths)
    alignment = _alignment(artifacts)
    warnings = list(alignment["warnings"])
    missing_required = [
        name
        for name in REQUIRED_ARTIFACTS
        if not artifacts[name].get("present")
    ]
    for name in missing_required:
        warnings.append(f"Required artifact is missing: {name}.")
    warnings.extend(_artifact_health_warnings(artifacts))

    state = "complete"
    if missing_required or alignment["status"] != "OK":
        state = "incomplete"
    if any(_is_required_health_warning(warning) for warning in warnings):
        state = "incomplete"

    return {
        "manifest_version": MODEL_STATE_MANIFEST_VERSION,
        "generated_at_utc": generated_at,
        "parent_refresh_id": parent_refresh_id,
        "build_kind": "full_model",
        "state": state,
        "publish": {
            "atomic_pointer": True,
            "path": _repo_relative(paths, paths.latest_model_state_manifest_path),
            "latest_aliases_authoritative": False,
        },
        "config": {
            "combined_hash": config_hash,
        },
        "manual_data": _file_artifact(
            paths=paths,
            name="manual_screening_store",
            path=paths.manual_screening_store_path,
            kind="sqlite",
            required_for_complete=False,
        ),
        "artifacts": artifacts,
        "alignment": alignment,
        "warnings": warnings,
        "stage_timings": stage_timings or {},
    }


def summarize_model_state_manifest(payload: dict[str, Any] | None) -> list[str]:
    """Return concise status lines for CLI/UI display."""

    if payload is None:
        return [
            "Model state manifest: NOT FOUND",
            "  Legacy latest files are being inspected directly.",
        ]
    state = str(payload.get("state") or "unknown").upper()
    parent = payload.get("parent_refresh_id")
    generated = payload.get("generated_at_utc") or "?"
    lines = [
        f"Model state manifest: {state}",
        f"  generated_at_utc: {generated}",
        f"  parent_refresh_id: {parent if parent else '(pending I2)'}",
    ]
    alignment = payload.get("alignment") if isinstance(payload.get("alignment"), dict) else {}
    if alignment:
        lines.append(f"  alignment: {alignment.get('status', 'UNKNOWN')}")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    for warning in warnings:
        lines.append(f"  - {warning}")
    return lines


def _artifact_map(paths: ProjectPaths) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {
        "foundation": _foundation_artifact(paths),
        "options": _options_artifact(paths),
        "tool_a": _parquet_artifact(
            paths=paths,
            name="tool_a",
            path=paths.latest_tool_a_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_b": _parquet_artifact(
            paths=paths,
            name="tool_b",
            path=paths.latest_tool_b_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_c": _parquet_artifact(
            paths=paths,
            name="tool_c",
            path=paths.latest_tool_c_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_d": _parquet_artifact(
            paths=paths,
            name="tool_d",
            path=paths.latest_tool_d_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_d_spot": _parquet_artifact(
            paths=paths,
            name="tool_d_spot",
            path=paths.latest_tool_d_spot_snapshot_parquet_path,
            required_for_complete=False,
        ),
    }
    for name in PLANNED_I3_ARTIFACTS:
        artifacts[name] = {
            "name": name,
            "kind": "planned",
            "planned_phase": "I3",
            "present": False,
            "required_for_complete": False,
            "schema_version": None,
        }
    return artifacts


def _foundation_artifact(paths: ProjectPaths) -> dict[str, Any]:
    artifact = _json_artifact(
        paths=paths,
        name="foundation",
        path=paths.latest_foundation_manifest_path,
        required_for_complete=True,
    )
    payload = artifact.pop("_payload", None)
    if isinstance(payload, dict):
        artifact.update(
            {
                "refresh_run_id": _clean_string(payload.get("refresh_run_id")),
                "snapshot_as_of_date": payload.get("snapshot_as_of_date"),
                "foundation_status": payload.get("foundation_status"),
                "raw_qa_status": _nested_status(payload.get("raw_qa_summary")),
                "normalization_qa_status": _nested_status(
                    payload.get("normalization_qa_summary")
                ),
            }
        )
    return artifact


def _options_artifact(paths: ProjectPaths) -> dict[str, Any]:
    artifact = _json_artifact(
        paths=paths,
        name="options",
        path=paths.latest_options_manifest_path,
        required_for_complete=True,
    )
    payload = artifact.pop("_payload", None)
    if isinstance(payload, dict):
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        artifact.update(
            {
                "refresh_run_id": _clean_string(payload.get("refresh_run_id")),
                "as_of_date": payload.get("as_of_date"),
                "options_phase_status": summary.get("options_phase_status"),
                "options_success_count": summary.get("options_success_count"),
                "options_error_count": summary.get("options_error_count"),
                "options_feature_row_count": summary.get("options_feature_row_count"),
            }
        )
    return artifact


def _json_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    required_for_complete: bool,
) -> dict[str, Any]:
    artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="json",
        required_for_complete=required_for_complete,
    )
    if not artifact["present"]:
        return artifact
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        artifact["read_error"] = str(exc)
        artifact["present"] = False
        return artifact
    artifact["_payload"] = payload
    return artifact


def _parquet_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    required_for_complete: bool,
) -> dict[str, Any]:
    artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="parquet",
        required_for_complete=required_for_complete,
    )
    if not artifact["present"]:
        return artifact
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        artifact["read_error"] = str(exc)
        artifact["present"] = False
        return artifact
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(_first_present(frame, "schema_version"))
    artifact["snapshot_refresh_run_ids"] = _unique_strings(
        frame,
        "snapshot_refresh_run_id",
    )
    artifact["source_run_ids"] = _unique_strings(frame, "source_run_id")
    return artifact


def _file_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    kind: str,
    required_for_complete: bool,
) -> dict[str, Any]:
    present = path.exists()
    artifact: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "path": _repo_relative(paths, path),
        "present": present,
        "required_for_complete": required_for_complete,
        "schema_version": None,
    }
    if present:
        artifact.update(
            {
                "sha256": _sha256_file(path),
                "modified_at_utc": _mtime_iso(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return artifact


def _alignment(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    warnings: list[str] = []
    foundation_id = _clean_string(artifacts["foundation"].get("refresh_run_id"))
    options_id = _clean_string(artifacts["options"].get("refresh_run_id"))
    if foundation_id and options_id and foundation_id != options_id:
        warnings.append(
            f"Foundation refresh {foundation_id} does not match options refresh {options_id}."
        )
    for name in ("tool_a", "tool_b", "tool_c", "tool_d"):
        artifact = artifacts[name]
        if not artifact.get("present"):
            continue
        run_ids = tuple(artifact.get("snapshot_refresh_run_ids") or ())
        if not run_ids:
            warnings.append(f"{name} does not carry snapshot_refresh_run_id.")
            continue
        if len(run_ids) > 1:
            warnings.append(
                f"{name} carries multiple snapshot_refresh_run_id values: {', '.join(run_ids)}."
            )
        if foundation_id and foundation_id not in run_ids:
            warnings.append(
                f"{name} references {', '.join(run_ids)} while foundation is {foundation_id}."
            )
    status = "OK" if not warnings else "WARN"
    return {
        "status": status,
        "foundation_refresh_run_id": foundation_id,
        "options_refresh_run_id": options_id,
        "tool_refresh_run_ids": {
            name: artifacts[name].get("snapshot_refresh_run_ids") or []
            for name in ("tool_a", "tool_b", "tool_c", "tool_d")
        },
        "warnings": warnings,
    }


def _artifact_health_warnings(artifacts: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    foundation_status = _clean_string(artifacts["foundation"].get("foundation_status"))
    if foundation_status and foundation_status not in {"PASS", "WARN"}:
        warnings.append(f"Foundation status is not usable: {foundation_status}.")
    options_status = _clean_string(artifacts["options"].get("options_phase_status"))
    if options_status and options_status == "FAIL":
        warnings.append("Options phase status is FAIL.")
    for name in ("tool_a", "tool_b", "tool_c", "tool_d"):
        artifact = artifacts[name]
        if artifact.get("present") and int(artifact.get("row_count") or 0) == 0:
            warnings.append(f"{name} has zero rows.")
    return warnings


def _is_required_health_warning(warning: str) -> bool:
    return (
        warning.startswith("Foundation status is not usable:")
        or warning == "Options phase status is FAIL."
        or warning.endswith(" has zero rows.")
    )


def _nested_status(value: object) -> object:
    if isinstance(value, dict):
        return value.get("overall_status")
    return None


def _first_present(frame: pd.DataFrame, column: str) -> object | None:
    if column not in frame.columns:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    return values.iloc[0]


def _unique_strings(frame: pd.DataFrame, column: str) -> list[str]:
    if frame.empty or column not in frame.columns:
        return []
    values: set[str] = set()
    for value in frame[column].dropna().unique():
        normalized = _clean_string(value)
        if normalized:
            values.add(normalized)
    return sorted(values)


def _clean_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    return text


def _repo_relative(paths: ProjectPaths, path: Path) -> str:
    try:
        return path.relative_to(paths.repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
