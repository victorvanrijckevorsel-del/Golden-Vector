"""Validated readers for the ticker-page artifacts (plan §5, §5.4).

Each loader returns an explicit state object so a bad artifact renders a
degraded section with a reason and never a valid-looking empty section.

Resolution is **manifest-first**, mirroring ``read_current_model_parquet``: the
authority is the model-state manifest's run-stamped immutable path, sha-verified
against the manifest entry. The mutable ``*_latest.parquet`` alias is never the
loading authority — it only distinguishes "never built" (MISSING) from "built by
a standalone run that no refresh has published yet" (PENDING_FIRST_PUBLISH).

These loaders are deliberately cache-free; caching is M2's (the detail loader
keys from the manifest pointer plus the resolved immutable paths).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.model_state import load_current_model_state_manifest
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import sha256_file
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_COLUMNS,
    GOLD_RESPONSE_KEY_COLUMNS,
    PERCENTILES_COLUMNS,
    PERCENTILES_KEY_COLUMNS,
    PERFORMANCE_COLUMNS,
    PERFORMANCE_KEY_COLUMNS,
    RESEARCH_KINDS,
    RESEARCH_SERIES_COLUMNS,
    RESEARCH_SERIES_KEY_COLUMNS,
    RESEARCH_SERIES_KIND_KEY_COLUMNS,
    validate_frame_schema,
)

STATUS_MISSING = "MISSING"
STATUS_PENDING_FIRST_PUBLISH = "PENDING_FIRST_PUBLISH"
STATUS_OK = "OK"
STATUS_STALE = "STALE"
STATUS_CORRUPT = "CORRUPT"

TICKER_PAGE_ARTIFACT_STATUSES: tuple[str, ...] = (
    STATUS_MISSING,
    STATUS_PENDING_FIRST_PUBLISH,
    STATUS_OK,
    STATUS_STALE,
    STATUS_CORRUPT,
)


@dataclass(frozen=True)
class TickerPageArtifactState:
    """Resolved state of one ticker-page artifact."""

    status: str
    reason: str | None
    frame: pd.DataFrame


def _empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _manifest_entry(paths: ProjectPaths, name: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return ``(manifest, artifact_entry)`` for ``name`` from current model state."""

    manifest = load_current_model_state_manifest(paths)
    if not isinstance(manifest, dict) or manifest.get("manifest_readable") is False:
        return None, None
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        return manifest, None
    entry = artifacts.get(name)
    return manifest, entry if isinstance(entry, dict) else None


def _alignment_reason(manifest: dict[str, Any] | None, name: str) -> str | None:
    if not isinstance(manifest, dict):
        return None
    alignment = manifest.get("alignment")
    if not isinstance(alignment, dict):
        return None
    for warning in alignment.get("ticker_page_artifact_warnings") or []:
        if str(warning).startswith(name):
            return str(warning)
    return None


def _resolve_artifact_path(
    paths: ProjectPaths,
    *,
    name: str,
    alias_path: Path,
) -> tuple[Path | None, TickerPageArtifactState | None]:
    """Manifest-first resolution. Returns ``(path, terminal_state)``."""

    manifest, entry = _manifest_entry(paths, name)
    if entry is None:
        if alias_path.exists():
            return None, TickerPageArtifactState(
                status=STATUS_PENDING_FIRST_PUBLISH,
                reason=(
                    f"{name} exists on disk at {alias_path} but the current model-state "
                    "manifest has no entry for it — awaiting first refresh publication. "
                    "A standalone `python main.py ticker-page` run is non-authoritative."
                ),
                frame=_empty_frame(()),
            )
        return None, TickerPageArtifactState(
            status=STATUS_MISSING,
            reason=(
                f"{name} artifact has not been built yet (expected at {alias_path}); "
                "it is produced by the ticker-page stage."
            ),
            frame=_empty_frame(()),
        )

    misalignment = _alignment_reason(manifest, name)
    if misalignment is not None:
        return None, TickerPageArtifactState(
            status=STATUS_STALE,
            reason=f"{name} is misaligned with the current generation: {misalignment}",
            frame=_empty_frame(()),
        )
    if not entry.get("usable") or entry.get("immutable") is not True:
        return None, TickerPageArtifactState(
            status=STATUS_STALE,
            reason=(
                f"{name} has no usable run-stamped immutable file in the current "
                "model state; a mutable alias is never the loading authority."
            ),
            frame=_empty_frame(()),
        )
    raw_path = str(entry.get("path") or "").strip()
    resolved = paths.resolve_repo_relative(raw_path) if raw_path else None
    if resolved is None or not resolved.exists():
        return None, TickerPageArtifactState(
            status=STATUS_STALE,
            reason=f"{name} immutable file named by the manifest is missing: {raw_path}",
            frame=_empty_frame(()),
        )
    expected_sha = str(entry.get("sha256") or "").strip()
    if expected_sha:
        try:
            actual_sha = sha256_file(resolved)
        except Exception as error:  # noqa: BLE001 - unreadable file is CORRUPT
            return None, TickerPageArtifactState(
                status=STATUS_CORRUPT,
                reason=f"{name} could not be hashed at {resolved}: {error}",
                frame=_empty_frame(()),
            )
        if actual_sha != expected_sha:
            return None, TickerPageArtifactState(
                status=STATUS_STALE,
                reason=(
                    f"{name} content at {resolved} does not match the sha256 recorded "
                    "in the current model state."
                ),
                frame=_empty_frame(()),
            )
    return resolved, None


def _load_artifact(
    paths: ProjectPaths,
    alias_path: Path,
    *,
    name: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    check_duplicate_keys: bool = True,
) -> TickerPageArtifactState:
    path, terminal = _resolve_artifact_path(paths, name=name, alias_path=alias_path)
    if terminal is not None:
        return TickerPageArtifactState(
            status=terminal.status,
            reason=terminal.reason,
            frame=_empty_frame(columns),
        )
    assert path is not None  # narrowed by _resolve_artifact_path
    try:
        frame = pd.read_parquet(path)
    except Exception as error:  # noqa: BLE001 - any read failure is CORRUPT
        return TickerPageArtifactState(
            status=STATUS_CORRUPT,
            reason=f"{name} artifact could not be read from {path}: {error}",
            frame=_empty_frame(columns),
        )

    violations = validate_frame_schema(
        frame,
        columns=columns,
        key_columns=key_columns if check_duplicate_keys else (),
        allow_extra=False,
    )
    if check_duplicate_keys is False:
        violations.extend(
            f"null values in key column {column}: {int(frame[column].isna().sum())} row(s)"
            for column in key_columns
            if column in frame.columns and int(frame[column].isna().sum())
        )
        violations.extend(
            f"missing key columns: {column}"
            for column in key_columns
            if column not in frame.columns
        )
    if violations:
        return TickerPageArtifactState(
            status=STATUS_CORRUPT,
            reason=f"{name} artifact failed schema validation: " + "; ".join(violations),
            frame=_empty_frame(columns),
        )
    return TickerPageArtifactState(status=STATUS_OK, reason=None, frame=frame)


def load_gold_response(paths: ProjectPaths) -> TickerPageArtifactState:
    return _load_artifact(
        paths,
        paths.latest_ticker_page_gold_response_path,
        name="ticker_page_gold_response",
        columns=GOLD_RESPONSE_COLUMNS,
        key_columns=GOLD_RESPONSE_KEY_COLUMNS,
    )


def load_score_percentiles(paths: ProjectPaths) -> TickerPageArtifactState:
    return _load_artifact(
        paths,
        paths.latest_ticker_page_percentiles_path,
        name="ticker_page_percentiles",
        columns=PERCENTILES_COLUMNS,
        key_columns=PERCENTILES_KEY_COLUMNS,
    )


def load_performance_series(paths: ProjectPaths) -> TickerPageArtifactState:
    return _load_artifact(
        paths,
        paths.latest_ticker_page_performance_path,
        name="ticker_page_performance",
        columns=PERFORMANCE_COLUMNS,
        key_columns=PERFORMANCE_KEY_COLUMNS,
    )


def load_research_series(paths: ProjectPaths) -> TickerPageArtifactState:
    """Research series uniqueness is per row-kind (§5.6), not on (ticker, kind)."""
    state = _load_artifact(
        paths,
        paths.latest_ticker_page_research_series_path,
        name="ticker_page_research_series",
        columns=RESEARCH_SERIES_COLUMNS,
        key_columns=RESEARCH_SERIES_KEY_COLUMNS,
        check_duplicate_keys=False,
    )
    if state.status != STATUS_OK:
        return state

    violations: list[str] = []
    for kind, kind_keys in RESEARCH_SERIES_KIND_KEY_COLUMNS.items():
        subset = state.frame[state.frame["kind"] == kind]
        if subset.empty:
            continue
        violations.extend(
            f"[kind={kind}] {message}"
            for message in validate_frame_schema(
                subset,
                columns=RESEARCH_SERIES_COLUMNS,
                key_columns=kind_keys,
                allow_extra=False,
            )
        )
    unknown_kinds = sorted(set(state.frame["kind"].dropna()) - set(RESEARCH_KINDS))
    if unknown_kinds:
        violations.append("unknown row kinds: " + ", ".join(unknown_kinds))
    if violations:
        return TickerPageArtifactState(
            status=STATUS_CORRUPT,
            reason=(
                "ticker_page_research_series artifact failed schema validation: "
                + "; ".join(violations)
            ),
            frame=_empty_frame(RESEARCH_SERIES_COLUMNS),
        )
    return state
