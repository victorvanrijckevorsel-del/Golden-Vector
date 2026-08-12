"""Shared per-substep timing recorder for pipeline stages.

Stages self-report per-step seconds and row counts (see ``soul.md`` #4:
measure the real run). One implementation lives here so every stage's timing
payload has the same shape.
"""

from __future__ import annotations

from time import perf_counter


def record_step_timing(
    timings: dict[str, dict[str, object]],
    step: str,
    started_at: float,
    *,
    rows_built: int | None = None,
    rows_persisted: int | None = None,
    extra: dict[str, object] | None = None,
) -> None:
    """Record elapsed seconds since ``started_at`` under ``step`` in ``timings``."""
    entry: dict[str, object] = {
        "duration_seconds": round(perf_counter() - started_at, 3),
    }
    if rows_built is not None:
        entry["rows_built"] = int(rows_built)
    if rows_persisted is not None:
        entry["rows_persisted"] = int(rows_persisted)
    if extra:
        entry.update(extra)
    timings[step] = entry
