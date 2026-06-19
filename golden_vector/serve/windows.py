"""Shared structural-window resolver for the gold-beta surfaces — ONE copy.

Maps a requested beta window to a canonical Tool A window id and reads that window's
PERSISTED up/down beta + fit (R²) + sample size + status from a tool_a row. Centralised
so the window→column mapping lives in one place (no hard-coded ``_6m/_12m/_3y`` suffix
lists scattered across the overview, the detail page, and benchmark comparison).

Serve-only: it resolves persisted columns for display; it never computes a beta in the
request path. The window SET mirrors the model's ``_STRUCTURAL_WINDOWS`` (6M / 12M / 3Y);
2Y / 5Y are a separate model/schema extension (plan Phase 2).
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from golden_vector.serve.format_helpers import _optional_float

# Canonical window ids as stored by the model (suffix = ``.lower()``).
STRUCTURAL_WINDOWS: tuple[str, ...] = ("6M", "12M", "3Y")
DEFAULT_WINDOW = "12M"  # the canonical anchor (matches the detail page default)
# Display label only — Victor asked to show the 12M window as "1Y" (same data).
WINDOW_LABELS: dict[str, str] = {"6M": "6M", "12M": "1Y", "3Y": "3Y"}
# Accept the display alias + lowercase forms from the query string.
_ALIASES: dict[str, str] = {"6M": "6M", "12M": "12M", "1Y": "12M", "3Y": "3Y"}


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


def window_is_reliable(metrics: dict[str, Any], *, min_weeks: float = 20.0) -> bool:
    """A window's betas are trustworthy only when the window status is usable
    (ELIGIBLE/OK), the fit is at least moderate, and the sample is not thin (Codex:
    R² band + weeks + status together)."""
    _band, fit_ok = r2_band(metrics.get("r_squared"))
    status_ok = str(metrics.get("status") or "").upper() in _USABLE_WINDOW_STATUSES
    weeks = metrics.get("weeks")
    weeks_ok = weeks is None or weeks >= min_weeks
    return fit_ok and status_ok and weeks_ok


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
