"""Resolve the newest complete model-state publication."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from golden_vector.app.model_state import load_current_model_state_manifest
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.datetimes import parse_iso_datetime


@dataclass(frozen=True)
class SuccessfulModelRefresh:
    generated_at: datetime
    generated_at_utc: str
    parent_refresh_id: str | None
    source_path: Path


def load_latest_successful_model_refresh(
    paths: ProjectPaths,
) -> SuccessfulModelRefresh | None:
    """Return the newest readable, complete model-state manifest.

    Normally the atomic current pointer is complete. If a later failed build
    published an incomplete diagnostic pointer, retained immutable manifests
    still let the UI and scheduler identify the last known-good publication.

    The pointer is written by the same atomic publish that writes the retained
    snapshot, so a complete, dated pointer IS the newest known-good
    publication and nothing older can beat it. That case returns immediately:
    ``/api/data-status`` polls this every 60 seconds per open tab against a
    single-threaded server, and reading every retained manifest on each poll
    measured 1.8s at 400 retained files. Only an unreadable or incomplete
    pointer pays for the retained-snapshot scan.
    """

    current_path = paths.latest_model_state_manifest_path
    current = load_current_model_state_manifest(paths)
    pointer = _resolve_refresh(current_path, current)
    if pointer is not None:
        return pointer

    resolved: list[SuccessfulModelRefresh] = []
    if paths.model_state_manifests_dir.exists():
        for path in paths.model_state_manifests_dir.glob("model_state_*.json"):
            if path == current_path:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            retained = _resolve_refresh(path, payload)
            if retained is not None:
                resolved.append(retained)
    return max(resolved, key=lambda item: item.generated_at) if resolved else None


def _resolve_refresh(path: Path, payload: Any) -> SuccessfulModelRefresh | None:
    """Read one manifest as a completed refresh, or None when it is not one."""

    if not isinstance(payload, dict):
        return None
    if payload.get("manifest_readable") is False:
        return None
    if str(payload.get("state") or "").strip().lower() != "complete":
        return None
    # ``generated_at_utc`` is the model-state publication time. Manual
    # portfolio edits legitimately republish that pointer without fetching
    # market data, so freshness must follow the explicitly retained full
    # refresh time. Older manifests remain readable through the fallback.
    if "full_refresh_completed_at_utc" in payload:
        raw_generated = str(payload.get("full_refresh_completed_at_utc") or "").strip()
    else:
        # Backward compatibility for manifests written before refresh time
        # and publication time became separate fields.
        raw_generated = str(payload.get("generated_at_utc") or "").strip()
    generated = parse_iso_datetime(raw_generated)
    if generated is None:
        return None
    return SuccessfulModelRefresh(
        generated_at=generated,
        generated_at_utc=raw_generated,
        parent_refresh_id=str(payload.get("parent_refresh_id") or "").strip() or None,
        source_path=path,
    )
