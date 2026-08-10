"""Shared pure-presentation primitives (plan section 10.3).

Helpers accept already-resolved text, state names, and trusted pre-escaped
HTML fragments (``*_html`` parameters) and return escaped markup. No data
awareness lives here.
"""

from __future__ import annotations

from html import escape

_HEADING_LEVELS = (2, 3, 4)


def page_header(title: str, *, lead_html: str = "", actions_html: str = "") -> str:
    """Standard page header: one ``h1``, optional lead copy, optional actions.

    ``lead_html`` carries the page's existing intro copy unchanged (typically
    ``<p>`` fragments); ``actions_html`` holds header-level controls.
    """
    lead = f"<div class=\"page-lead\">{lead_html}</div>" if lead_html else ""
    actions = f"<div class=\"page-actions\">{actions_html}</div>" if actions_html else ""
    return (
        "<header class=\"page-header\">"
        f"<div class=\"page-header-main\"><h1>{escape(title)}</h1>{lead}</div>"
        f"{actions}"
        "</header>"
    )


def section_heading(
    title: str,
    *,
    level: int = 2,
    help_html: str = "",
    actions_html: str = "",
) -> str:
    """Section header with optional help affordance and right-aligned actions.

    ``help_html`` is the standard click-to-explain markup (``column_help``)
    rendered inside the heading, matching the existing pattern.
    """
    if level not in _HEADING_LEVELS:
        raise ValueError(f"unsupported heading level: {level!r}")
    actions = f"<div class=\"section-actions\">{actions_html}</div>" if actions_html else ""
    return (
        "<div class=\"section-heading\">"
        f"<h{level}>{escape(title)}{help_html}</h{level}>"
        f"{actions}"
        "</div>"
    )


def section_nav(links, *, label: str = "On this page") -> str:
    """In-page anchor navigation (plan 10.3): ``(fragment_id, text)`` pairs.

    Anchors only — never routes. Callers include only the sections that exist
    for the current lens/vehicle (plan 15/23 ticker-detail + Portfolio rules).
    """
    items = "".join(
        f"<a class=\"section-nav-link\" href=\"#{escape(fragment)}\">{escape(text)}</a>"
        for fragment, text in links
    )
    return (
        f"<nav class=\"section-nav\" aria-label=\"{escape(label)}\">{items}</nav>"
    )


def toolbar(content_html: str, *, label: str) -> str:
    """Action/scenario toolbar shell grouping related controls."""
    return (
        f"<div class=\"toolbar\" role=\"group\" aria-label=\"{escape(label)}\">"
        f"{content_html}</div>"
    )


def empty_state(title: str, *, body_html: str = "") -> str:
    """Empty/unavailable state shell: what is missing plus optional next step."""
    return (
        "<div class=\"empty-state\">"
        f"<p class=\"empty-state-title\">{escape(title)}</p>"
        f"{body_html}"
        "</div>"
    )


def disclosure(
    summary_html: str,
    body_html: str,
    *,
    expanded: bool = False,
    class_name: str = "",
) -> str:
    """Generic ``details`` disclosure with the shared visual treatment.

    Existing purpose-built disclosures (``cell-notes``, chart details) keep
    their own markup; this shell is for migrated generic sections.
    """
    classes = f"disclosure {class_name}".strip()
    open_attr = " open" if expanded else ""
    return (
        f"<details class=\"{escape(classes)}\"{open_attr}>"
        f"<summary>{summary_html}</summary>"
        f"<div class=\"disclosure-body\">{body_html}</div>"
        "</details>"
    )
