"""Current model-state manifest helpers.

The model-state manifest is intentionally shaped as the future single atomic
pointer for a coherent Golden Vector build. I1 still lets existing readers use
their legacy latest aliases, but this contract is the path readers will resolve
through in I2/I3.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.common.files import atomic_write_bytes as _atomic_write_bytes
from golden_vector.common.files import atomic_write_text as _atomic_write_text
from golden_vector.common.files import repo_relative as _repo_relative
from golden_vector.common.files import safe_file_fragment as _safe_file_fragment
from golden_vector.common.files import sha256_file as _sha256_file
from golden_vector.common.parquet import parquet_context_metadata
from golden_vector.common.strings import clean_string as _common_clean_string
from golden_vector.common.strings import unique_strings as _common_unique_strings
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import to_jsonable
from golden_vector.contracts.option_artifacts import (
    OPTION_ARTIFACT_NAMES,
    OPTION_ARTIFACT_PREFIXES,
    REQUIRED_OPTION_ARTIFACT_NAMES,
    option_artifact_latest_path,
)

MODEL_STATE_MANIFEST_VERSION = 1
CURRENT_FOUNDATION_UNAVAILABLE_MESSAGE = (
    "Current model-state manifest does not expose a usable immutable foundation artifact."
)

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "foundation",
    "options",
    "tool_a",
    "tool_b",
    "tool_c",
    "tool_d",
    *REQUIRED_OPTION_ARTIFACT_NAMES,
)

PLANNED_I3_ARTIFACTS: tuple[str, ...] = OPTION_ARTIFACT_NAMES
PORTFOLIO_ARTIFACTS: tuple[str, ...] = (
    "portfolio_lines",
    "portfolio_positions",
    "portfolio_summary",
    "benchmark_betas",
    "portfolio_reconciliation",
    "portfolio_hedge_sizing",
    "portfolio_correlations",
    "portfolio_value_history",
    "portfolio_reconciliation_export",
)
PORTFOLIO_ALIGNMENT_ARTIFACTS: tuple[str, ...] = (
    "portfolio_lines",
    "portfolio_positions",
    "portfolio_summary",
    "benchmark_betas",
    "portfolio_reconciliation",
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
    snapshot_path = _model_state_snapshot_path(paths, payload)
    payload["publish"]["retention_snapshot_path"] = _repo_relative(paths, snapshot_path)
    serialized = json.dumps(to_jsonable(payload), indent=2, sort_keys=True)
    _atomic_write_text(snapshot_path, serialized)
    target = paths.latest_model_state_manifest_path
    _atomic_write_text(target, serialized)
    return payload


def resolve_current_model_artifact_path(
    paths: ProjectPaths,
    artifact_name: str,
    *,
    fallback_path: Path | None = None,
) -> Path | None:
    """Resolve a current artifact through the model-state manifest.

    The fallback exists only for the transition period before a manifest has
    been published, or for old tests/fixtures that carry a partial manifest.
    When a manifest explicitly contains an artifact entry, a missing/unusable
    entry returns None rather than silently reading a mutable alias.
    """

    payload = load_current_model_state_manifest(paths)
    if payload is None:
        return _existing_path_or_none(fallback_path)
    if payload.get("manifest_readable") is False:
        return None
    if not isinstance(payload.get("artifacts"), dict):
        return None
    artifact = _manifest_artifact(payload, artifact_name)
    if artifact is None:
        return None
    if not artifact.get("usable"):
        return None
    if artifact.get("immutable") is not True:
        return None
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        return None
    path = paths.resolve_repo_relative(raw_path)
    return path if path.exists() else None


def resolve_current_foundation_manifest_path(
    paths: ProjectPaths,
    *,
    require_current_manifest: bool = False,
) -> Path | None:
    """Resolve the foundation manifest selected by current model state.

    When ``require_current_manifest`` is true, a present-but-unusable model-state
    manifest is treated as a hard failure instead of silently dropping to the
    mutable foundation alias. This is the safe behavior for I2 readers that
    rebuild panels or scenarios from foundation data.
    """

    manifest_path = resolve_current_model_artifact_path(
        paths,
        "foundation",
        fallback_path=paths.latest_foundation_manifest_path,
    )
    if (
        manifest_path is None
        and require_current_manifest
        and load_current_model_state_manifest(paths) is not None
    ):
        raise FileNotFoundError(CURRENT_FOUNDATION_UNAVAILABLE_MESSAGE)
    return manifest_path


def read_current_model_parquet(
    paths: ProjectPaths,
    artifact_name: str,
    *,
    fallback_path: Path | None = None,
) -> pd.DataFrame:
    """Read a current Parquet artifact through the model-state manifest."""

    path = resolve_current_model_artifact_path(
        paths,
        artifact_name,
        fallback_path=fallback_path,
    )
    if path is None:
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def read_current_model_json(
    paths: ProjectPaths,
    artifact_name: str,
    *,
    fallback_path: Path | None = None,
) -> dict[str, Any] | None:
    """Read a current JSON artifact through the model-state manifest."""

    path = resolve_current_model_artifact_path(
        paths,
        artifact_name,
        fallback_path=fallback_path,
    )
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_current_model_state_manifest(paths: ProjectPaths) -> dict[str, Any] | None:
    """Load the latest model-state manifest, returning None when absent."""

    path = paths.latest_model_state_manifest_path
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _unreadable_manifest_payload(
            paths=paths,
            path=path,
            error=f"Could not read model-state manifest: {exc}",
        )
    if not isinstance(payload, dict):
        return _unreadable_manifest_payload(
            paths=paths,
            path=path,
            error="Could not read model-state manifest: root JSON value is not an object.",
        )
    return payload


def build_current_model_state_manifest(
    *,
    paths: ProjectPaths,
    config_hash: str | None,
    parent_refresh_id: str | None = None,
    stage_timings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect current published artifacts and return a coherent-state manifest."""

    generated_at = _utc_now_iso()
    artifacts = _artifact_map(paths, artifact_stamp=parent_refresh_id)
    alignment = _alignment(artifacts)
    warnings = list(alignment["warnings"])
    missing_required = [
        name
        for name in REQUIRED_ARTIFACTS
        if not artifacts[name].get("usable")
    ]
    for name in missing_required:
        if artifacts[name].get("present"):
            warnings.append(f"Required artifact is not usable: {name}.")
        else:
            warnings.append(f"Required artifact is missing: {name}.")
    warnings.extend(_artifact_health_warnings(artifacts))

    state = "complete"
    if missing_required or alignment["status"] != "OK":
        state = "incomplete"
    if any(_is_required_health_warning(warning) for warning in warnings):
        state = "incomplete"

    return {
        "manifest_version": MODEL_STATE_MANIFEST_VERSION,
        "manifest_readable": True,
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
            "config_hash": config_hash,
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
        f"  parent_refresh_id: {parent if parent else '(none)'}",
    ]
    alignment = payload.get("alignment") if isinstance(payload.get("alignment"), dict) else {}
    if alignment:
        lines.append(f"  alignment: {alignment.get('status', 'UNKNOWN')}")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    for warning in warnings:
        lines.append(f"  - {warning}")
    return lines


def summarize_model_state_alignment(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the authoritative refresh-alignment verdict from model state.

    ``None`` means either no model-state manifest exists yet, or the manifest is
    incomplete but does not carry an alignment warning. In those cases legacy
    callers may still fall back to their old local checks. Any readable manifest
    with an explicit alignment warning is treated as authoritative.
    """

    if payload is None:
        return None

    if payload.get("manifest_readable") is False:
        warnings = _manifest_warning_messages(payload)
        message = warnings[0] if warnings else "Model-state manifest could not be read."
        return {
            "status": "UNKNOWN",
            "message": message,
            "warnings": tuple(warnings or [message]),
        }

    alignment = payload.get("alignment")
    alignment = alignment if isinstance(alignment, dict) else {}
    raw_status = str(alignment.get("status") or "").strip().upper()
    status = raw_status if raw_status in {"OK", "WARN"} else "UNKNOWN"
    alignment_warnings = _message_list(alignment.get("warnings"))
    if status == "OK" and str(payload.get("state") or "").strip().lower() != "complete":
        return None
    messages = _dedupe_messages(alignment_warnings)
    if status != "OK" and not messages:
        messages = [f"Model-state manifest reports alignment status {status}."]
    return {
        "status": status,
        "message": messages[0] if messages else None,
        "warnings": tuple(messages),
    }


def _artifact_map(
    paths: ProjectPaths,
    *,
    artifact_stamp: str | None = None,
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {
        "foundation": _foundation_artifact(paths, artifact_stamp=artifact_stamp),
        "options": _options_artifact(paths, artifact_stamp=artifact_stamp),
        "tool_a": _parquet_artifact(
            paths=paths,
            name="tool_a",
            path=paths.latest_tool_a_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_a_structural_metrics": _tool_a_structural_metrics_artifact(paths),
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
        "portfolio_lines": _parquet_artifact(
            paths=paths,
            name="portfolio_lines",
            path=paths.latest_portfolio_lines_path,
            required_for_complete=False,
        ),
        "portfolio_positions": _parquet_artifact(
            paths=paths,
            name="portfolio_positions",
            path=paths.latest_portfolio_positions_path,
            required_for_complete=False,
        ),
        "portfolio_summary": _parquet_artifact(
            paths=paths,
            name="portfolio_summary",
            path=paths.latest_portfolio_summary_path,
            required_for_complete=False,
        ),
        "benchmark_betas": _parquet_artifact(
            paths=paths,
            name="benchmark_betas",
            path=paths.latest_benchmark_betas_path,
            required_for_complete=False,
        ),
        "portfolio_reconciliation": _parquet_artifact(
            paths=paths,
            name="portfolio_reconciliation",
            path=paths.latest_portfolio_reconciliation_path,
            required_for_complete=False,
        ),
        "portfolio_hedge_sizing": _parquet_artifact(
            paths=paths,
            name="portfolio_hedge_sizing",
            path=paths.latest_portfolio_hedge_sizing_path,
            required_for_complete=False,
        ),
        "portfolio_correlations": _parquet_artifact(
            paths=paths,
            name="portfolio_correlations",
            path=paths.latest_portfolio_correlations_path,
            required_for_complete=False,
        ),
        "portfolio_value_history": _parquet_artifact(
            paths=paths,
            name="portfolio_value_history",
            path=paths.latest_portfolio_value_history_path,
            required_for_complete=False,
        ),
        "portfolio_reconciliation_export": _parquet_artifact(
            paths=paths,
            name="portfolio_reconciliation_export",
            path=paths.latest_portfolio_reconciliation_export_path,
            required_for_complete=False,
        ),
        "portfolio_reconciliation_export_csv": _csv_artifact(
            paths=paths,
            name="portfolio_reconciliation_export_csv",
            path=paths.latest_portfolio_reconciliation_export_csv_path,
            required_for_complete=False,
        ),
    }
    for name in PLANNED_I3_ARTIFACTS:
        artifacts[name] = _optional_i3_parquet_artifact(paths=paths, name=name)
    return artifacts


def _optional_i3_parquet_artifact(
    *,
    paths: ProjectPaths,
    name: str,
) -> dict[str, Any]:
    artifact = _parquet_artifact(
        paths=paths,
        name=name,
        path=option_artifact_latest_path(paths, name),
        required_for_complete=name in REQUIRED_OPTION_ARTIFACT_NAMES,
    )
    if not artifact["present"]:
        artifact["planned_phase"] = "I3"
    return artifact


def _foundation_artifact(
    paths: ProjectPaths,
    *,
    artifact_stamp: str | None,
) -> dict[str, Any]:
    artifact = _json_artifact(
        paths=paths,
        name="foundation",
        path=paths.latest_foundation_manifest_path,
        required_for_complete=True,
    )
    payload = artifact.pop("_payload", None)
    if isinstance(payload, dict):
        _snapshot_json_artifact(
            paths=paths,
            artifact=artifact,
            source_path=paths.latest_foundation_manifest_path,
            file_prefix="foundation_manifest",
            stamp=artifact_stamp or _clean_string(payload.get("refresh_run_id")),
        )
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


def _options_artifact(
    paths: ProjectPaths,
    *,
    artifact_stamp: str | None,
) -> dict[str, Any]:
    artifact = _json_artifact(
        paths=paths,
        name="options",
        path=paths.latest_options_manifest_path,
        required_for_complete=True,
    )
    payload = artifact.pop("_payload", None)
    if isinstance(payload, dict):
        _snapshot_json_artifact(
            paths=paths,
            artifact=artifact,
            source_path=paths.latest_options_manifest_path,
            file_prefix="options_manifest",
            stamp=artifact_stamp or _clean_string(payload.get("refresh_run_id")),
        )
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
        artifact["readable"] = False
        artifact["usable"] = False
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
    alias_artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="parquet",
        required_for_complete=required_for_complete,
    )
    if not alias_artifact["present"]:
        return alias_artifact
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        alias_artifact["read_error"] = str(exc)
        alias_artifact["readable"] = False
        alias_artifact["usable"] = False
        return alias_artifact
    alias_metadata = parquet_context_metadata(path)

    source_ids = _unique_strings(frame, "source_run_id")
    if not source_ids:
        source_ids = _frame_attr_strings(frame, "source_run_id")
    if not source_ids:
        source_ids = _metadata_strings(alias_metadata, "source_run_id")
    immutable_path = _resolve_run_stamped_parquet(
        paths=paths,
        name=name,
        source_run_ids=source_ids,
    )
    artifact = alias_artifact
    if immutable_path is not None:
        artifact = _file_artifact(
            paths=paths,
            name=name,
            path=immutable_path,
            kind="parquet",
            required_for_complete=required_for_complete,
        )
        artifact["source_alias_path"] = _repo_relative(paths, path)
        artifact["immutable"] = True
        try:
            frame = pd.read_parquet(immutable_path)
        except Exception as exc:
            artifact["read_error"] = str(exc)
            artifact["readable"] = False
            artifact["usable"] = False
            return artifact
        alias_metadata = parquet_context_metadata(immutable_path)
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(
        _first_present(frame, "schema_version")
    ) or _clean_string(alias_metadata.get("schema_version")) or _clean_string(
        frame.attrs.get("schema_version")
    )
    snapshot_ids = _unique_strings(frame, "snapshot_refresh_run_id")
    if not snapshot_ids:
        snapshot_ids = _frame_attr_strings(frame, "snapshot_refresh_run_id")
    if not snapshot_ids:
        snapshot_ids = _metadata_strings(alias_metadata, "snapshot_refresh_run_id")
    artifact["snapshot_refresh_run_ids"] = snapshot_ids
    artifact["source_run_ids"] = source_ids
    return artifact


def _csv_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    required_for_complete: bool,
) -> dict[str, Any]:
    alias_artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="csv",
        required_for_complete=required_for_complete,
    )
    if not alias_artifact["present"]:
        return alias_artifact
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        alias_artifact["read_error"] = str(exc)
        alias_artifact["readable"] = False
        alias_artifact["usable"] = False
        return alias_artifact

    source_ids = _unique_strings(frame, "source_run_id")
    immutable_path = _resolve_run_stamped_artifact(
        paths=paths,
        name=name,
        source_run_ids=source_ids,
        suffix=".csv",
    )
    if immutable_path is None:
        immutable_path = _resolve_run_stamped_artifact_by_alias_hash(
            paths=paths,
            name=name,
            alias_path=path,
            suffix=".csv",
        )
    artifact = alias_artifact
    if immutable_path is not None:
        artifact = _file_artifact(
            paths=paths,
            name=name,
            path=immutable_path,
            kind="csv",
            required_for_complete=required_for_complete,
        )
        artifact["source_alias_path"] = _repo_relative(paths, path)
        artifact["immutable"] = True
        try:
            frame = pd.read_csv(immutable_path)
        except Exception as exc:
            artifact["read_error"] = str(exc)
            artifact["readable"] = False
            artifact["usable"] = False
            return artifact
        source_ids = _unique_strings(frame, "source_run_id")
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(_first_present(frame, "schema_version"))
    artifact["snapshot_refresh_run_ids"] = _unique_strings(frame, "snapshot_refresh_run_id")
    artifact["source_run_ids"] = source_ids
    return artifact


def _tool_a_structural_metrics_artifact(paths: ProjectPaths) -> dict[str, Any]:
    path = paths.latest_tool_a_structural_metrics_path
    alias_artifact = _file_artifact(
        paths=paths,
        name="tool_a_structural_metrics",
        path=path,
        kind="parquet",
        required_for_complete=False,
    )
    if not alias_artifact["present"]:
        return alias_artifact
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        alias_artifact["read_error"] = str(exc)
        alias_artifact["readable"] = False
        alias_artifact["usable"] = False
        return alias_artifact

    source_ids = _unique_strings(frame, "source_run_id")
    if not source_ids:
        source_ids = _metadata_strings(parquet_context_metadata(path), "source_run_id")
    immutable_path = _resolve_tool_a_structural_metrics_path(
        paths=paths,
        source_run_ids=source_ids,
    )
    artifact = alias_artifact
    if immutable_path is not None:
        artifact = _file_artifact(
            paths=paths,
            name="tool_a_structural_metrics",
            path=immutable_path,
            kind="parquet",
            required_for_complete=False,
        )
        artifact["source_alias_path"] = _repo_relative(paths, path)
        artifact["immutable"] = True
        try:
            frame = pd.read_parquet(immutable_path)
        except Exception as exc:
            artifact["read_error"] = str(exc)
            artifact["readable"] = False
            artifact["usable"] = False
            return artifact
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(_first_present(frame, "schema_version"))
    artifact["source_run_ids"] = source_ids
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
        "source_alias_path": None,
        "immutable": False,
        "present": present,
        "readable": False,
        "usable": False,
        "required_for_complete": required_for_complete,
        "schema_version": None,
    }
    if present:
        try:
            stat = path.stat()
            artifact.update(
                {
                    "sha256": _sha256_file(path),
                    "modified_at_utc": _mtime_iso(path),
                    "size_bytes": stat.st_size,
                    "readable": True,
                    "usable": True,
                }
            )
        except Exception as exc:
            artifact["read_error"] = str(exc)
    return artifact


def _alignment(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    warnings: list[str] = []
    foundation_id = _clean_string(artifacts["foundation"].get("refresh_run_id"))
    options_id = _clean_string(artifacts["options"].get("refresh_run_id"))
    if artifacts["foundation"].get("usable") and not foundation_id:
        warnings.append("foundation does not carry refresh_run_id.")
    if artifacts["options"].get("usable") and not options_id:
        warnings.append("options does not carry refresh_run_id.")
    if foundation_id and options_id and foundation_id != options_id:
        warnings.append(
            f"Foundation refresh {foundation_id} does not match options refresh {options_id}."
        )
    tool_ids, tool_warnings = _refresh_alignment(
        artifacts,
        names=("tool_a", "tool_b", "tool_c", "tool_d"),
        expected_run_id=foundation_id,
        expected_label="foundation",
    )
    option_ids, option_warnings = _refresh_alignment(
        artifacts,
        names=REQUIRED_OPTION_ARTIFACT_NAMES,
        expected_run_id=options_id,
        expected_label="options",
    )
    portfolio_ids, portfolio_warnings = _refresh_alignment(
        artifacts,
        names=PORTFOLIO_ALIGNMENT_ARTIFACTS,
        expected_run_id=foundation_id,
        expected_label="foundation",
    )
    warnings.extend(tool_warnings)
    warnings.extend(option_warnings)
    warnings.extend(portfolio_warnings)
    status = "OK" if not warnings else "WARN"
    return {
        "status": status,
        "foundation_refresh_run_id": foundation_id,
        "options_refresh_run_id": options_id,
        "tool_refresh_run_ids": tool_ids,
        "option_artifact_refresh_run_ids": option_ids,
        "portfolio_artifact_refresh_run_ids": portfolio_ids,
        "warnings": warnings,
    }


def _refresh_alignment(
    artifacts: dict[str, dict[str, Any]],
    *,
    names: tuple[str, ...],
    expected_run_id: str | None,
    expected_label: str,
) -> tuple[dict[str, list[str]], list[str]]:
    ids_by_name: dict[str, list[str]] = {}
    warnings: list[str] = []
    for name in names:
        artifact = artifacts[name]
        run_ids = list(artifact.get("snapshot_refresh_run_ids") or [])
        ids_by_name[name] = run_ids
        if not artifact.get("present"):
            continue
        if not run_ids:
            warnings.append(f"{name} does not carry snapshot_refresh_run_id.")
            continue
        if len(run_ids) > 1:
            warnings.append(
                f"{name} carries multiple snapshot_refresh_run_id values: {', '.join(run_ids)}."
            )
        if expected_run_id and expected_run_id not in run_ids:
            warnings.append(
                f"{name} references {', '.join(run_ids)} while "
                f"{expected_label} is {expected_run_id}."
            )
    return ids_by_name, warnings


def _artifact_health_warnings(artifacts: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    foundation_status = _clean_string(artifacts["foundation"].get("foundation_status"))
    if artifacts["foundation"].get("usable") and not foundation_status:
        warnings.append("Foundation status is missing.")
    if foundation_status and foundation_status not in {"PASS", "WARN"}:
        warnings.append(f"Foundation status is not usable: {foundation_status}.")
    options_status = _clean_string(artifacts["options"].get("options_phase_status"))
    if artifacts["options"].get("usable") and not options_status:
        warnings.append("Options phase status is missing.")
    if options_status and options_status == "FAIL":
        warnings.append("Options phase status is FAIL.")
    for name in REQUIRED_ARTIFACTS:
        artifact = artifacts[name]
        if (
            artifact.get("kind") == "parquet"
            and artifact.get("readable")
            and int(artifact.get("row_count") or 0) == 0
        ):
            warnings.append(f"{name} has zero rows.")
        if artifact.get("usable") and not artifact.get("immutable"):
            warnings.append(f"Required artifact is not immutable: {name}.")
    return warnings


def _manifest_warning_messages(payload: dict[str, Any]) -> list[str]:
    messages = _message_list(payload.get("warnings"))
    read_error = _clean_string(payload.get("read_error"))
    if read_error:
        messages.append(read_error)
    return _dedupe_messages(messages)


def _message_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        for text in (_clean_string(item),)
        if text
    ]


def _dedupe_messages(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _is_required_health_warning(warning: str) -> bool:
    return (
        warning.startswith("Foundation status is not usable:")
        or warning == "Foundation status is missing."
        or warning == "Options phase status is missing."
        or warning == "Options phase status is FAIL."
        or warning.endswith(" has zero rows.")
        or warning.startswith("Required artifact is not immutable:")
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
    return _common_unique_strings(frame, column)


def _frame_attr_strings(frame: pd.DataFrame, key: str) -> list[str]:
    value = _clean_string(frame.attrs.get(key))
    return [value] if value else []


def _metadata_strings(metadata: dict[str, str], key: str) -> list[str]:
    value = _clean_string(metadata.get(key))
    return [value] if value else []


def _clean_string(value: object) -> str | None:
    return _common_clean_string(value)


def _manifest_artifact(
    payload: dict[str, Any],
    artifact_name: str,
) -> dict[str, Any] | None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    artifact = artifacts.get(artifact_name)
    return artifact if isinstance(artifact, dict) else None


def _unreadable_manifest_payload(
    *,
    paths: ProjectPaths,
    path: Path,
    error: str,
) -> dict[str, Any]:
    return {
        "manifest_version": MODEL_STATE_MANIFEST_VERSION,
        "manifest_readable": False,
        "generated_at_utc": None,
        "parent_refresh_id": None,
        "build_kind": "full_model",
        "state": "incomplete",
        "publish": {
            "atomic_pointer": True,
            "path": _repo_relative(paths, path),
            "latest_aliases_authoritative": False,
        },
        "artifacts": {},
        "alignment": {"status": "WARN", "warnings": []},
        "read_error": error,
        "warnings": [error],
        "stage_timings": {},
    }


def _existing_path_or_none(path: Path | None) -> Path | None:
    return path if path is not None and path.exists() else None


def _snapshot_json_artifact(
    *,
    paths: ProjectPaths,
    artifact: dict[str, Any],
    source_path: Path,
    file_prefix: str,
    stamp: str | None,
) -> None:
    if not artifact.get("usable") or not stamp:
        return
    target = paths.intermediate_status_dir / f"{file_prefix}_{_safe_file_fragment(stamp)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write_bytes(target, source_path.read_bytes())
        artifact["source_alias_path"] = _repo_relative(paths, source_path)
        artifact["path"] = _repo_relative(paths, target)
        artifact["immutable"] = True
        _refresh_file_metadata(artifact, target)
    except Exception as exc:
        artifact["read_error"] = str(exc)
        artifact["usable"] = False
        artifact["readable"] = False


def _resolve_run_stamped_parquet(
    *,
    paths: ProjectPaths,
    name: str,
    source_run_ids: list[str],
) -> Path | None:
    return _resolve_run_stamped_artifact(
        paths=paths,
        name=name,
        source_run_ids=source_run_ids,
        suffix=".parquet",
    )


def _resolve_run_stamped_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    source_run_ids: list[str],
    suffix: str,
) -> Path | None:
    directory, prefix = _tool_latest_directory_and_prefix(paths, name)
    for run_id in source_run_ids:
        candidate = directory / f"{prefix}_latest_{_safe_file_fragment(run_id)}{suffix}"
        if _is_run_stamped_tool_latest(candidate, prefix, suffix=suffix):
            return candidate
    return None


def _resolve_run_stamped_artifact_by_alias_hash(
    *,
    paths: ProjectPaths,
    name: str,
    alias_path: Path,
    suffix: str,
) -> Path | None:
    if not alias_path.exists() or not alias_path.is_file():
        return None
    try:
        alias_hash = _sha256_file(alias_path)
    except Exception:
        return None
    directory, prefix = _tool_latest_directory_and_prefix(paths, name)
    for candidate in sorted(directory.glob(f"{prefix}_latest_*{suffix}"), reverse=True):
        if not _is_run_stamped_tool_latest(candidate, prefix, suffix=suffix):
            continue
        try:
            if _sha256_file(candidate) == alias_hash:
                return candidate
        except Exception:
            continue
    return None


def _resolve_tool_a_structural_metrics_path(
    *,
    paths: ProjectPaths,
    source_run_ids: list[str],
) -> Path | None:
    for run_id in source_run_ids:
        candidate = (
            paths.intermediate_tool_a_structural_dir
            / f"tool_a_structural_{_safe_file_fragment(run_id)}.parquet"
        )
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _tool_latest_directory_and_prefix(paths: ProjectPaths, name: str) -> tuple[Path, str]:
    if name == "tool_a":
        return paths.output_tool_a_dir, "tool_a"
    if name == "tool_b":
        return paths.output_tool_b_dir, "tool_b"
    if name == "tool_c":
        return paths.output_tool_c_dir, "tool_c"
    if name in {"tool_d", "tool_d_spot"}:
        return paths.output_tool_d_dir, "tool_d"
    if name in OPTION_ARTIFACT_PREFIXES:
        return paths.output_options_dir, OPTION_ARTIFACT_PREFIXES[name]
    if name in PORTFOLIO_ARTIFACTS:
        return paths.output_portfolio_dir, name
    if name == "portfolio_reconciliation_export_csv":
        return paths.output_portfolio_dir, "portfolio_reconciliation_export"
    raise ValueError(f"Unsupported model artifact for immutable lookup: {name}")


def _is_run_stamped_tool_latest(candidate: Path, prefix: str, *, suffix: str) -> bool:
    return (
        candidate.exists()
        and candidate.is_file()
        and _has_run_stamped_tool_latest_name(candidate.name, prefix, suffix=suffix)
    )


def _has_run_stamped_tool_latest_name(file_name: str, prefix: str, *, suffix: str) -> bool:
    pattern = rf"^{re.escape(prefix)}_latest_\d{{8}}T\d{{6}}Z-.+{re.escape(suffix)}$"
    return re.match(pattern, file_name) is not None


def _refresh_file_metadata(artifact: dict[str, Any], path: Path) -> None:
    stat = path.stat()
    artifact.update(
        {
            "sha256": _sha256_file(path),
            "modified_at_utc": _mtime_iso(path),
            "size_bytes": stat.st_size,
            "readable": True,
            "usable": True,
        }
    )


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_state_snapshot_path(paths: ProjectPaths, payload: dict[str, Any]) -> Path:
    stamp = (
        _clean_string(payload.get("parent_refresh_id"))
        or _clean_string(payload.get("generated_at_utc"))
        or "unknown"
    )
    return paths.model_state_manifests_dir / f"model_state_{_safe_file_fragment(stamp)}.json"
