"""Shared structural-window resolver for the gold-beta surfaces — ONE copy.

Maps a requested beta window to a canonical Tool A window id and reads that window's
PERSISTED up/down beta + fit (R²) + sample size + status from a tool_a row. Centralised
so the window→column mapping lives in one place (no hard-coded ``_6m/_12m/_3y`` suffix
lists scattered across the overview, the detail page, and benchmark comparison).

Serve-only: it resolves persisted columns for display; it never computes a beta in the
request path. The window set is 6M / 12M / 2Y / 3Y / 5Y: 6M/12M/3Y are the SCORING
windows; 2Y/5Y are DISPLAY-ONLY longer lookbacks (never part of the score/rank). The
12M window renders under the "1Y" label.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from golden_vector.common.numeric import is_missing
# Window topology comes from the ONE registry (golden_vector/common/windows.py). This module
# re-exports the names serve surfaces already import from here, and keeps the serve-only
# render helpers (selector, cells, reliability) below.
from golden_vector.common.windows import (
    ALL_WINDOWS as STRUCTURAL_WINDOWS,
    DEFAULT_WINDOW,
    DISPLAY_WINDOWS,
    SCORING_WINDOWS,
    WINDOW_LABELS,
    resolve_window,
    window_suffix,
)
from golden_vector.serve.format_helpers import _MISSING_SORT_SENTINEL, _optional_float

__all__ = [
    "STRUCTURAL_WINDOWS",
    "SCORING_WINDOWS",
    "DISPLAY_WINDOWS",
    "DEFAULT_WINDOW",
    "WINDOW_LABELS",
    "resolve_window",
    "window_suffix",
    "window_metrics",
    "r2_band",
    "window_is_reliable",
    "win_num_td",
    "gold_link_td",
    "render_window_selector",
]


def window_metrics(row: dict[str, Any], window_id: str) -> dict[str, Any]:
    """The selected window's persisted gold-beta metrics from one tool_a row."""
    s = window_suffix(window_id)
    return {
        "up_beta": _optional_float(row.get(f"up_beta_{s}")),
        "down_beta": _optional_float(row.get(f"down_beta_{s}")),
        "delta": _optional_float(row.get(f"structural_delta_{s}")),
        "gamma": _optional_float(row.get(f"gamma_{s}")),
        "asymmetry": _optional_float(row.get(f"asymmetry_ratio_{s}")),
        "r_squared": _optional_float(row.get(f"r_squared_{s}")),
        "weeks": _optional_float(row.get(f"weeks_{s}")),
        "status": row.get(f"window_status_{s}"),
    }


def r2_band(r_squared: float | None) -> tuple[str, bool]:
    """How much of the stock's moves gold explains in this window → (label, reliable).

    Bands: strong ≥0.40, moderate ≥0.25 (both reliable); weak ≥0.10, none <0.10 (NOT
    reliable — the beta is barely meaningful, e.g. a name that doesn't really track gold).
    """
    if r_squared is None:
        return ("—", False)
    if r_squared >= 0.40:
        return ("strong", True)
    if r_squared >= 0.25:
        return ("moderate", True)
    if r_squared >= 0.10:
        return ("weak", False)
    return ("none", False)


# Window statuses the model writes for a USABLE window. Tool A emits "ELIGIBLE" (not
# "OK") for good windows — treating only ("","OK") as usable silently muted every beta
# (Codex Phase-2 review P2). The empty string is kept only for explicit legacy blank
# statuses; missing/null status stays muted.
_USABLE_WINDOW_STATUSES = ("", "OK", "ELIGIBLE")


def window_is_reliable(metrics: dict[str, Any]) -> bool:
    """A window's betas are trustworthy only when the window status is usable
    (ELIGIBLE/OK) and the fit is at least moderate.

    Sample-size adequacy lives ONCE in config (per-window ``minimum_observations``:
    6M=20 … 5Y=200) and is enforced upstream — a window with too few weeks is written
    as LOW_OBSERVATION (not ELIGIBLE), so the status gate already excludes it. A
    serve-side week floor would be a hardcoded twin of that config value, and a single
    flat floor is wrong per-window (20 weeks is fine for 6M but far below the 200 a 5Y
    window needs). So reliability defers to the backend status, never a literal here."""
    _band, fit_ok = r2_band(metrics.get("r_squared"))
    raw_status = metrics.get("status") if "status" in metrics else None
    status_ok = (
        raw_status is not None
        and not is_missing(raw_status)
        and str(raw_status).strip().upper() in _USABLE_WINDOW_STATUSES
    )
    return fit_ok and status_ok


def win_num_td(value: float | None, *, reliable: bool, decimals: int = 2) -> str:
    """A window-specific numeric cell, shared by the Gold Sensitivity (A) and Gold
    Downside (C) overviews. Sorts by ``data-order``; when the selected window's gold-link
    is weak/thin the number is muted (weak evidence must DISPLAY as weak, not just warn)."""
    if value is None or value != value:
        # One missing-value sort convention product-wide (deep-review M3): the
        # shared sentinel sorts missing rows last, matching every other table.
        return f"<td data-order=\"{_MISSING_SORT_SENTINEL}\"><span class=\"hint\">—</span></td>"
    txt = f"{value:.{decimals}f}"
    if reliable:
        return f"<td data-order=\"{value:.4f}\">{txt}</td>"
    # Degraded evidence is EXCLUDED from ordering, not just muted (deep-review
    # M4, per the exclusion canon): the number stays visible but sorts with the
    # missing rows so a weak-gold-link name can't interleave with trusted ones.
    return (
        f"<td data-order=\"{_MISSING_SORT_SENTINEL}\">"
        f"<span class=\"hint\" title=\"weak gold-link — treat with caution\">{txt}</span></td>"
    )


def gold_link_td(r_squared: float | None) -> str:
    """The trust column: how much of the stock's moves gold explains in this window.
    Sortable by R² via ``data-order``; weak/none is muted. Shared by the A and C overviews."""
    band, fit_ok = r2_band(r_squared)
    if r_squared is None:
        return f"<td data-order=\"{_MISSING_SORT_SENTINEL}\"><span class=\"hint\">—</span></td>"
    inner = f"{band} · {r_squared * 100:.0f}%"
    body = inner if fit_ok else f"<span class=\"hint\">{inner}</span>"
    return f"<td data-order=\"{r_squared:.4f}\">{body}</td>"


def render_window_selector(active: str, *, search: str = "", target: str = "/tool-a") -> str:
    """The beta-window toggle for an overview page — navigates to ``?window=<id>`` (the
    toggle IS the 'is it changing?' mechanism). Reuses the existing ``.window-switcher`` /
    ``.window-tabs`` / ``.window-tab`` CSS from the detail page (no new styles)."""
    tabs: list[str] = []
    for window in STRUCTURAL_WINDOWS:
        cls = "window-tab active" if window == active else "window-tab"
        parts = [f"window={window}"]
        if search:
            parts.append(f"search={quote(search, safe='')}")
        href = f"{target}?{'&'.join(parts)}"
        tabs.append(
            f"<a class=\"{cls}\" href=\"{escape(href, quote=True)}\">{escape(WINDOW_LABELS[window])}</a>"
        )
    return (
        "<section class=\"panel window-switcher\">"
        "<div class=\"window-tabs\">" + "".join(tabs) + "</div>"
        "<p class=\"hint\">Beta window — how far back the gold beta is measured. Toggle to see how a "
        "miner's gold sensitivity has changed over different lookbacks.</p>"
        "</section>"
    )
