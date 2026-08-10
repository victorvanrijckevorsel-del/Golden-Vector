"""Semantic notice shell (plan sections 10.3, 10.5).

Call sites pass an already-resolved tone — the mapping from backend/user
state to tone is decided where the state is known (plan 10.5 table). This
renderer never creates new state thresholds.
"""

from __future__ import annotations

NOTICE_TONES = ("success", "info", "warning", "danger", "degraded", "neutral")

_ASSERTIVE_TONES = {"warning", "danger", "degraded"}


def notice(tone: str, body_html: str) -> str:
    """One notice/banner shell for every flash, warning, and status message.

    Emits the legacy ``flash`` class alongside the semantic classes during
    migration so existing styling, tests, and the semantic-contract extractor
    keep matching; the bare legacy class is removed in Phase 7.
    """
    if tone not in NOTICE_TONES:
        raise ValueError(f"unknown notice tone: {tone!r}")
    role = "alert" if tone in _ASSERTIVE_TONES else "status"
    return (
        f"<div class=\"flash notice notice-{tone}\" role=\"{role}\">"
        f"{body_html}</div>"
    )
