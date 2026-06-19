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

from golden_vector.serve.format_helpers import _optional_float

# Canonical window ids as stored by the model (suffix = ``.lower()``). 6M/12M/3Y are the
# scoring windows; 2Y/5Y are display-only extras (model Phase 2). Ordered for the selector.
STRUCTURAL_WINDOWS: tuple[str, ...] = ("6M", "12M", "2Y", "3Y", "5Y")
# The scoring vs display split, exported as the ONE source of truth so other serve
# surfaces (detail page, charts) import these instead of re-hardcoding window tuples.
SCORING_WINDOWS: tuple[str, ...] = ("6M", "12M", "3Y")
DISPLAY_WINDOWS: tuple[str, ...] = ("2Y", "5Y")
DEFAULT_WINDOW = "12M"  # the canonical anchor (matches the detail page default)
# Display label only — Victor asked to show the 12M window as "1Y" (same data).
WINDOW_LABELS: dict[str, str] = {"6M": "6M", "12M": "1Y", "2Y": "2Y", "3Y": "3Y", "5Y": "5Y"}
# Accept the display alias + lowercase forms from the query string.
_ALIASES: dict[str, str] = {"6M": "6M", "12M": "12M", "1Y": "12M", "2Y": "2Y", "3Y": "3Y", "5Y": "5Y"}


def resolve_window(requested: str | None) -> str:
    """Normalise a query-string window (e.g. '1y', '12M', '3Y') to a canonical id;
    anything unrecognised falls back to the default anchor."""
    return _ALIASES.get(str(requested or "").strip().upper(), DEFAULT_WINDOW)


def window_suffix(window_id: str) -> str:
    return str(window_id).lower()


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
# (Codex Phase-2 review P2). Problem statuses (LOW_OBSERVATION / INELIGIBLE / missing)
# stay muted.
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
    status_ok = str(metrics.get("status") or "").upper() in _USABLE_WINDOW_STATUSES
    return fit_ok and status_ok


def win_num_td(value: float | None, *, reliable: bool, decimals: int = 2) -> str:
    """A window-specific numeric cell, shared by the Gold Sensitivity (A) and Gold
    Downside (C) overviews. Sorts by ``data-order``; when the selected window's gold-link
    is weak/thin the number is muted (weak evidence must DISPLAY as weak, not just warn)."""
    if value is None or value != value:
        return "<td data-order=\"-999\"><span class=\"hint\">—</span></td>"
    txt = f"{value:.{decimals}f}"
    body = (
        txt
        if reliable
        else f"<span class=\"hint\" title=\"weak gold-link — treat with caution\">{txt}</span>"
    )
    return f"<td data-order=\"{value:.4f}\">{body}</td>"


def gold_link_td(r_squared: float | None) -> str:
    """The trust column: how much of the stock's moves gold explains in this window.
    Sortable by R² via ``data-order``; weak/none is muted. Shared by the A and C overviews."""
    band, fit_ok = r2_band(r_squared)
    if r_squared is None:
        return "<td data-order=\"-1\"><span class=\"hint\">—</span></td>"
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
