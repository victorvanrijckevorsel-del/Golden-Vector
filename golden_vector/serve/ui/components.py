"""Shared pure-presentation primitives (plan section 10.3).

Helpers accept already-resolved text, state names, and trusted pre-escaped
HTML fragments (``*_html`` parameters) and return escaped markup. No data
awareness lives here.
"""

from __future__ import annotations

from html import escape

_HEADING_LEVELS = (2, 3, 4)
_DATA_CARD_STATES = ("positive", "negative", "warning", "neutral")


def _require_accessible_label(label: str, component: str) -> None:
    if not label.strip():
        raise ValueError(f"{component} requires a non-empty accessible label")


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


def section_nav(
    links,
    *,
    label: str = "On this page",
    compact: bool = False,
) -> str:
    """In-page anchor navigation (plan 10.3): ``(fragment_id, text)`` pairs.

    Anchors only — never routes. Callers include only the sections that exist
    for the current lens/vehicle (plan 15/23 ticker-detail + Portfolio rules).
    """
    items = "".join(
        f"<a class=\"section-nav-link\" href=\"#{escape(fragment)}\">{escape(text)}</a>"
        for fragment, text in links
    )
    classes = "section-nav section-nav--compact" if compact else "section-nav"
    return f'<nav class="{classes}" aria-label="{escape(label)}">{items}</nav>'


def section_tabs(links, *, label: str = "Sections") -> str:
    """Compact rectangular variant of :func:`section_nav`.

    These remain ordinary in-page anchors. The alias makes the visual intent
    explicit at migrated call sites without creating a second renderer.
    """
    return section_nav(links, label=label, compact=True)


def command_bar(
    identity_html: str,
    *,
    navigation_html: str = "",
    groups=(),
    label: str = "Company controls",
    class_name: str = "",
) -> str:
    """Render the professional command-bar shell from resolved fragments.

    ``identity_html`` and ``navigation_html`` are trusted, pre-escaped HTML.
    ``groups`` contains ``(label, content_html)`` pairs; group labels are plain
    text and escaped here while each content fragment is trusted HTML. Groups
    and navigation may be empty so callers can opt in one command-bar region at
    a time while migrating; identity remains the stable required slot.
    """
    _require_accessible_label(label, "command_bar")
    if not identity_html.strip():
        raise ValueError("command_bar requires identity_html")
    extra_classes = " ".join(str(class_name).split())
    if extra_classes and any(
        not part.replace("-", "").replace("_", "").isalnum()
        for part in extra_classes.split()
    ):
        raise ValueError("command_bar class_name must contain CSS class tokens")
    classes = "command-bar" + (f" {extra_classes}" if extra_classes else "")
    navigation = (
        f'<div class="command-bar__navigation">{navigation_html}</div>' if navigation_html else ""
    )
    group_markup = "".join(
        '<div class="command-bar__group">'
        f'<span class="command-bar__label">{escape(str(group_label))}</span>'
        f'<div class="command-bar__content">{content_html}</div>'
        "</div>"
        for group_label, content_html in groups
    )
    return (
        f'<div class="{classes}" role="region" aria-label="{escape(label)}">'
        f'<div class="command-bar__identity">{identity_html}</div>'
        f"{navigation}{group_markup}</div>"
    )


def segmented_control(items, *, label: str) -> str:
    """Render an accessible group of URL-backed choices.

    ``items`` contains ``(text, href, selected)`` triples. They stay ordinary
    links (not ARIA tabs), and exactly one carries ``aria-current=\"true\"``.
    Caller-built URLs are not rewritten; they are escaped only for safe use in
    the HTML attribute.
    """
    _require_accessible_label(label, "segmented_control")
    selected_seen = False
    links: list[str] = []
    for item_label, href, selected in items:
        current = ""
        if selected:
            if selected_seen:
                raise ValueError("segmented_control requires exactly one selected item")
            selected_seen = True
            current = ' aria-current="true"'
        links.append(
            '<a class="segmented-control__item" '
            f'href="{escape(str(href), quote=True)}"{current}>'
            f"{escape(str(item_label))}</a>"
        )
    if not selected_seen:
        raise ValueError("segmented_control requires exactly one selected item")
    return (
        f'<div class="segmented-control" role="group" aria-label="{escape(label)}">'
        f"{''.join(links)}</div>"
    )


def data_card(
    label: str,
    value_html: str,
    *,
    help_html: str = "",
    basis_html: str = "",
    state: str = "",
    state_label: str = "",
    gold_linked: bool = False,
) -> str:
    """Render one data card from already-resolved display fragments.

    ``label`` is escaped plain text. ``value_html``, ``help_html``, and
    ``basis_html`` are trusted, pre-escaped display fragments.

    ``gold_linked`` marks a figure that moves with the gold dial. It is a
    property of the metric, not a judgement about its value, so it composes
    with ``state`` rather than competing for the same slot; the CSS lets a
    state colour win the shared edge when a card is also degraded.
    """
    if not label.strip():
        raise ValueError("data_card requires a label")
    heading = escape(label)
    gold_class = " data-card--gold-linked" if gold_linked else ""
    state_class = ""
    if state:
        if state not in _DATA_CARD_STATES:
            raise ValueError(f"unknown data-card state: {state!r}")
        if not state_label.strip():
            raise ValueError("data_card state requires a visible state_label")
        state_class = f" data-card--{state}"
    elif state_label.strip():
        raise ValueError("data_card state_label requires a semantic state")
    basis = f'<p class="data-card__basis">{basis_html}</p>' if basis_html else ""
    state_markup = (
        f'<p class="data-card__state">{escape(state_label)}</p>'
        if state_label
        else ""
    )
    return (
        f'<article class="data-card{gold_class}{state_class}">'
        f'<h3 class="data-card__label">{heading}{help_html}</h3>'
        f'<p class="data-card__value">{value_html}</p>'
        f"{state_markup}{basis}</article>"
    )


def basis_strip(items, *, label: str = "Data basis") -> str:
    """Render compact source/date/basis facts without interpreting them.

    ``items`` contains ``(label, value_html)`` pairs. Labels are escaped text;
    values are trusted, pre-escaped display fragments resolved by the caller.
    """
    _require_accessible_label(label, "basis_strip")
    parts = "".join(
        '<span class="basis-strip__item">'
        f'<span class="basis-strip__label">{escape(str(item_label))}</span>'
        f'<span class="basis-strip__value">{value_html}</span>'
        "</span>"
        for item_label, value_html in items
    )
    if not parts:
        raise ValueError("basis_strip requires at least one item")
    return f'<div class="basis-strip" role="group" aria-label="{escape(label)}">{parts}</div>'


def terminal_density(content_html: str) -> str:
    """Opt a bounded surface into the tighter terminal-density presentation."""
    return f'<div class="terminal-density">{content_html}</div>'


def toolbar(
    content_html: str,
    *,
    label: str,
    visible_label: str = "",
) -> str:
    """Action/scenario toolbar shell grouping related controls."""
    visible = (
        f'<span class="toolbar__label">{escape(visible_label)}</span>'
        if visible_label
        else ""
    )
    return (
        f"<div class=\"toolbar\" role=\"group\" aria-label=\"{escape(label)}\">"
        f"{visible}{content_html}</div>"
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
