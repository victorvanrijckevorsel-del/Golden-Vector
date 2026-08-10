"""Semantic notice shell (plan sections 10.3, 10.5).

Call sites pass an already-resolved tone — the mapping from backend/user
state to tone is decided where the state is known (plan 10.5 table). This
renderer never creates new state thresholds.
"""

from __future__ import annotations

import re
from html import escape

NOTICE_TONES = ("success", "info", "warning", "danger", "degraded", "neutral")

_ASSERTIVE_TONES = {"warning", "danger", "degraded"}

# extra_classes is code-authored CSS tokens, never data: fail loud on anything
# that could break out of the class attribute (GV-RD-P34-4).
_CLASS_TOKENS_RE = re.compile(r"[A-Za-z0-9_-]+(?: [A-Za-z0-9_-]+)*")


def notice(tone: str, body_html: str, *, extra_classes: str = "") -> str:
    """One notice/banner shell for every flash, warning, and status message.

    ``extra_classes`` preserves purpose-specific hooks (e.g. option-freshness).
    """
    if tone not in NOTICE_TONES:
        raise ValueError(f"unknown notice tone: {tone!r}")
    stripped = extra_classes.strip()
    if stripped and not _CLASS_TOKENS_RE.fullmatch(stripped):
        raise ValueError(f"extra_classes must be CSS class tokens: {extra_classes!r}")
    role = "alert" if tone in _ASSERTIVE_TONES else "status"
    extra = f" {stripped}" if stripped else ""
    return (
        f"<div class=\"notice notice-{tone}{extra}\" role=\"{role}\">"
        f"{body_html}</div>"
    )


def status_strip(items, *, label: str = "Data status") -> str:
    """Compact data-status strip (plan 10.4): ``(label, value_html)`` pairs from
    already-resolved manifest summaries. Labels are escaped here; each
    ``value_html`` is a TRUSTED pre-escaped fragment (the package's ``*_html``
    convention — ``_fmt_text`` output qualifies). No interpretation happens here.
    """
    parts = "".join(
        "<span class=\"status-item\">"
        f"<span class=\"status-item-label\">{escape(str(item_label))}</span>"
        f"<span class=\"status-item-value\">{value_html}</span>"
        "</span>"
        for item_label, value_html in items
    )
    return (
        f"<div class=\"status-strip\" role=\"group\" aria-label=\"{escape(label)}\">"
        f"{parts}</div>"
    )
