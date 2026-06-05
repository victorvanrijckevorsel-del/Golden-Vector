"""Safe retention pruning for run-stamped Golden Vector artifacts."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from golden_vector.app.paths import ProjectPaths


@dataclass(frozen=True)
class PruneCandidate:
    """One file or directory that can be pruned if not protected."""

    path: Path
    kind: str
    is_dir: bool = False

    def display(self, paths: ProjectPaths) -> str:
        try:
            return self.path.relative_to(paths.repo_root).as_posix()
        except ValueError:
            return self.path.as_posix()


@dataclass(frozen=True)
class PruneReport:
    """Dry-run/apply report for retention pruning."""

    dry_run: bool
    keep_model_states: int
    retained_model_state_paths: tuple[Path, ...]
    pruned_model_state_paths: tuple[Path, ...]
    protected_paths: frozenset[Path]
    protected_run_ids: frozenset[str]
    candidates: tuple[PruneCandidate, ...]
    deleted_paths: tuple[Path, ...]
    warnings: tuple[str, ...] = ()

    @property
    def delete_count(self) -> int:
        return len(self.candidates)


def prune_runs(
    paths: ProjectPaths,
    *,
    keep_model_states: int = 10,
    apply: bool = False,
) -> PruneReport:
    """Plan and optionally apply safe retention pruning.

    Safety contract:
    - dry-run is the default
    - latest_model_state.json is always kept
    - every artifact path referenced by every retained model-state manifest is protected
    - every run id referenced by retained model-state artifacts is protected
    """

    if keep_model_states <= 0:
        raise ValueError("keep_model_states must be positive")

    model_states = _load_model_state_records(paths)
    retained_snapshots = model_states[:keep_model_states]
    pruned_snapshots = model_states[keep_model_states:]
    retained_paths, retained_warnings = _retained_model_state_paths(
        paths,
        retained_snapshots,
    )
    warnings: list[str] = []
    warnings.extend(retained_warnings)
    if not retained_paths:
        warnings.append(
            "No readable retained model-state manifests with artifacts were found; pruning is a no-op."
        )
        return PruneReport(
            dry_run=not apply,
            keep_model_states=keep_model_states,
            retained_model_state_paths=(),
            pruned_model_state_paths=tuple(record.path for record in pruned_snapshots),
            protected_paths=frozenset(),
            protected_run_ids=frozenset(),
            candidates=(),
            deleted_paths=(),
            warnings=tuple(warnings),
        )
    protected_paths, protected_run_ids = _protection_sets(paths, retained_paths)
    candidates = _prune_candidates(
        paths=paths,
        pruned_model_state_paths=tuple(record.path for record in pruned_snapshots),
        protected_paths=protected_paths,
        protected_run_ids=protected_run_ids,
    )
    deleted_paths: list[Path] = []
    if apply:
        for candidate in candidates:
            _delete_candidate(paths, candidate)
            deleted_paths.append(candidate.path)

    return PruneReport(
        dry_run=not apply,
        keep_model_states=keep_model_states,
        retained_model_state_paths=tuple(retained_paths),
        pruned_model_state_paths=tuple(record.path for record in pruned_snapshots),
        protected_paths=frozenset(protected_paths),
        protected_run_ids=frozenset(protected_run_ids),
        candidates=tuple(candidates),
        deleted_paths=tuple(deleted_paths),
        warnings=tuple(warnings),
    )


@dataclass(frozen=True)
class _ModelStateRecord:
    path: Path
    payload: dict[str, Any]
    generated_at_utc: str


def _load_model_state_records(paths: ProjectPaths) -> list[_ModelStateRecord]:
    records: list[_ModelStateRecord] = []
    for path in sorted(paths.model_state_manifests_dir.glob("model_state_*.json")):
        payload = _read_json_object(path)
        if payload is None:
            continue
        records.append(
            _ModelStateRecord(
                path=path,
                payload=payload,
                generated_at_utc=str(payload.get("generated_at_utc") or ""),
            )
        )
    return sorted(
        records,
        key=lambda record: (record.generated_at_utc, record.path.stat().st_mtime),
        reverse=True,
    )


def _retained_model_state_paths(
    paths: ProjectPaths,
    retained_snapshots: list[_ModelStateRecord],
) -> tuple[list[Path], list[str]]:
    retained: list[Path] = []
    warnings: list[str] = []
    if paths.latest_model_state_manifest_path.exists():
        retained.append(paths.latest_model_state_manifest_path)
    retained.extend(record.path for record in retained_snapshots)
    readable: list[Path] = []
    for path in _unique_paths(retained):
        payload = _read_json_object(path)
        if payload is None:
            warnings.append(f"Skipped unreadable model-state manifest: {path}")
            continue
        if not isinstance(payload.get("artifacts"), dict) or not payload["artifacts"]:
            warnings.append(f"Skipped non-protectable model-state manifest: {path}")
            continue
        readable.append(path)
    return readable, warnings


def _protection_sets(
    paths: ProjectPaths,
    model_state_paths: list[Path],
) -> tuple[set[Path], set[str]]:
    protected_paths: set[Path] = set(_resolve_path(path) for path in model_state_paths)
    protected_run_ids: set[str] = set()
    for model_state_path in model_state_paths:
        payload = _read_json_object(model_state_path)
        if payload is None:
            continue
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, dict):
            continue
        for raw_artifact in artifacts.values():
            if not isinstance(raw_artifact, dict):
                continue
            for field_name in ("path", "source_alias_path"):
                raw_path = str(raw_artifact.get(field_name) or "").strip()
                if not raw_path:
                    continue
                artifact_path = _resolve_repo_path(paths, raw_path)
                protected_paths.add(_resolve_path(artifact_path))
                run_dir = _run_dir_for_path(paths, artifact_path)
                if run_dir is not None:
                    protected_run_ids.add(run_dir.name)
            for field_name in (
                "refresh_run_id",
                "source_run_ids",
                "snapshot_refresh_run_ids",
            ):
                protected_run_ids.update(_run_ids(raw_artifact.get(field_name)))
    return protected_paths, protected_run_ids


def _prune_candidates(
    *,
    paths: ProjectPaths,
    pruned_model_state_paths: tuple[Path, ...],
    protected_paths: set[Path],
    protected_run_ids: set[str],
) -> list[PruneCandidate]:
    candidates: list[PruneCandidate] = []
    for path in pruned_model_state_paths:
        candidates.append(PruneCandidate(path=path, kind="model_state"))

    candidates.extend(_artifact_file_candidates(paths))
    candidates.extend(_run_dir_candidates(paths, protected_run_ids=protected_run_ids))

    filtered: list[PruneCandidate] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = _resolve_path(candidate.path)
        if resolved in seen:
            continue
        seen.add(resolved)
        if _candidate_protected(
            paths=paths,
            candidate=candidate,
            protected_paths=protected_paths,
            protected_run_ids=protected_run_ids,
        ):
            continue
        filtered.append(candidate)
    return sorted(filtered, key=lambda item: item.path.as_posix())


def _artifact_file_candidates(paths: ProjectPaths) -> list[PruneCandidate]:
    candidates: list[PruneCandidate] = []
    # The manifest protects immutable *_latest_<runid> artifacts. Older bulky
    # *_output_<runid> archives are still candidates unless another retained
    # model state references them explicitly.
    for directory, patterns in (
        (
            paths.output_tool_a_dir,
            ("tool_a_output_*.*", "tool_a_latest_*.*"),
        ),
        (
            paths.output_tool_b_dir,
            ("tool_b_output_*.*", "tool_b_latest_*.*"),
        ),
        (
            paths.output_tool_c_dir,
            ("tool_c_output_*.*", "tool_c_latest_*.*"),
        ),
        (
            paths.output_tool_d_dir,
            ("tool_d_output_*.*", "tool_d_latest_*.*"),
        ),
        (
            paths.output_options_dir,
            ("*_output_*.*", "*_latest_*.*"),
        ),
        (
            paths.intermediate_status_dir,
            ("foundation_manifest_*.json", "options_manifest_*.json"),
        ),
        (
            paths.intermediate_tool_a_structural_dir,
            ("tool_a_structural_*.parquet",),
        ),
        (
            paths.intermediate_tool_a_profiles_dir,
            ("tool_a_profiles_*.parquet",),
        ),
        (
            paths.intermediate_tool_b_dir,
            ("tool_b_output_*.parquet",),
        ),
        (
            paths.intermediate_tool_c_dir,
            ("tool_c_output_*.parquet",),
        ),
        (
            paths.intermediate_tool_d_dir,
            ("tool_d_output_*.parquet",),
        ),
    ):
        for pattern in patterns:
            for path in directory.glob(pattern):
                if path.is_file() and _has_retention_stamp(path):
                    candidates.append(PruneCandidate(path=path, kind="artifact"))
    return candidates


def _run_dir_candidates(
    paths: ProjectPaths,
    *,
    protected_run_ids: set[str],
) -> list[PruneCandidate]:
    if not paths.runs_dir.exists():
        return []
    candidates: list[PruneCandidate] = []
    for path in paths.runs_dir.iterdir():
        if not path.is_dir() or path.name in protected_run_ids:
            continue
        candidates.append(PruneCandidate(path=path, kind="run_dir", is_dir=True))
    return candidates


def _candidate_protected(
    *,
    paths: ProjectPaths,
    candidate: PruneCandidate,
    protected_paths: set[Path],
    protected_run_ids: set[str],
) -> bool:
    resolved = _resolve_path(candidate.path)
    if resolved in protected_paths:
        return True
    if candidate.is_dir and candidate.path.name in protected_run_ids:
        return True
    run_dir = _run_dir_for_path(paths, candidate.path)
    return run_dir is not None and run_dir.name in protected_run_ids


def _delete_candidate(paths: ProjectPaths, candidate: PruneCandidate) -> None:
    root = paths.runs_dir if candidate.is_dir else paths.repo_root
    if not _is_within(candidate.path, root):
        raise ValueError(f"Refusing to prune outside expected root: {candidate.path}")
    if candidate.is_dir:
        shutil.rmtree(candidate.path)
    else:
        candidate.path.unlink(missing_ok=True)


def _run_ids(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        text = value.strip()
        return {text} if text else set()
    if isinstance(value, list):
        return {
            str(item).strip()
            for item in value
            if str(item).strip()
        }
    return set()


def _run_dir_for_path(paths: ProjectPaths, path: Path) -> Path | None:
    try:
        relative = _resolve_path(path).relative_to(_resolve_path(paths.runs_dir))
    except ValueError:
        return None
    parts = relative.parts
    if not parts:
        return None
    return paths.runs_dir / parts[0]


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve_repo_path(paths: ProjectPaths, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else paths.repo_root / path


def _resolve_path(path: Path) -> Path:
    return path.resolve(strict=False)


def _has_retention_stamp(path: Path) -> bool:
    return re.search(r"_\d{8}T\d{6}Z-[A-Za-z0-9_.-]+", path.name) is not None


def _unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = _resolve_path(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolve_path(path).relative_to(_resolve_path(root))
        return True
    except ValueError:
        return False
