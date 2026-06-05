"""Shared PASS/WARN/FAIL status precedence helpers."""

from __future__ import annotations

DEFAULT_NEUTRAL_STATUSES = frozenset({"SKIPPED"})
VALID_PIPELINE_STATUSES = frozenset({"PASS", "WARN", "FAIL"}) | DEFAULT_NEUTRAL_STATUSES


def combine_statuses(
    *statuses: str | None,
    neutral_statuses: frozenset[str] = DEFAULT_NEUTRAL_STATUSES,
) -> str:
    """Combine pipeline statuses with FAIL > WARN > PASS precedence.

    Neutral statuses such as ``SKIPPED`` are allowed and ignored. Unknown
    statuses raise rather than silently being treated as PASS.
    """

    normalized = [
        str(status).strip().upper()
        for status in statuses
        if str(status or "").strip()
    ]
    unknown = sorted(
        status
        for status in set(normalized)
        if status not in VALID_PIPELINE_STATUSES and status not in neutral_statuses
    )
    if unknown:
        raise ValueError("Unsupported pipeline statuses: " + ", ".join(unknown))
    active = [status for status in normalized if status not in neutral_statuses]
    if any(status == "FAIL" for status in active):
        return "FAIL"
    if any(status == "WARN" for status in active):
        return "WARN"
    return "PASS"
