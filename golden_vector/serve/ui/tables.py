"""Accessible table-scroll region (plan sections 10.3, 11.1).

The region owns horizontal overflow so the page body never scrolls sideways;
CSS provides the edge affordance and touch momentum. ``tabindex=\"0\"`` plus
``role=\"region\"`` with a label makes the scrollable area keyboard reachable.
"""

from __future__ import annotations

from html import escape


def table_region(table_html: str, *, region_id: str, label: str) -> str:
    """Wrap an analytical table (plus optional caption markup) in the shared
    horizontal-scroll region. ``region_id`` must be page-unique."""
    return (
        f"<div class=\"table-region\" id=\"{escape(region_id)}\" role=\"region\" "
        f"aria-label=\"{escape(label)}\" tabindex=\"0\">{table_html}</div>"
    )
