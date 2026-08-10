"""Accessible table-scroll region (plan sections 10.3, 11.1).

The region owns horizontal overflow so the page body never scrolls sideways;
CSS provides the edge affordance and touch momentum. ``tabindex=\"0\"`` plus
``role=\"region\"`` with a label makes the scrollable area keyboard reachable.
"""

from __future__ import annotations

import re
from html import escape

_REGION_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


def table_region(table_html: str, *, region_id: str, label: str) -> str:
    """Wrap an analytical table (plus optional caption markup) in the shared
    horizontal-scroll region. ``region_id`` must be a page-unique id token.

    The server-rendered ``tabindex="0"`` is the no-JavaScript-safe default so
    an overflowing region is always keyboard-scrollable; the shell script
    removes the tab stop while a region does not actually overflow
    (GV-RD-P34-1)."""
    if not _REGION_ID_RE.fullmatch(region_id or ""):
        raise ValueError(f"region_id must be an id token: {region_id!r}")
    if not (label or "").strip():
        raise ValueError("table_region requires a non-empty accessible label")
    return (
        f"<div class=\"table-region\" id=\"{escape(region_id)}\" role=\"region\" "
        f"aria-label=\"{escape(label)}\" tabindex=\"0\">{table_html}</div>"
    )
