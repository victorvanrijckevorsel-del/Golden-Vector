"""ONE source of truth for structural beta windows (horizons).

Before this module, the window topology was copy-pasted across ~6 places (serve/windows.py,
serve/workspace_state._WINDOW_WEEKS, model/structural._window_offset,
model/benchmark_comparison._WINDOW_COLUMN_SUFFIX/_WINDOW_LABEL, …) and drifted — e.g. the
volatility panel only knew 6M/12M/3Y, so a 2Y/5Y selection silently fell back to 52 weeks.
This is the canonical registry every layer imports from.

Scope: this holds the window TOPOLOGY only — id, scoring-vs-display split, display label,
query aliases, column suffix, observation-count (weeks), and calendar offset. Tunable
THRESHOLDS (per-window ``minimum_observations``) stay in config (``ConfidenceThresholds``),
keyed by these ids — one threshold lives in one place.

Lives in ``common`` (the lowest layer) so model, contracts, and serve can all import it
without a layering violation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Window:
    """Canonical metadata for one structural window."""

    id: str  # canonical id as stored by the model (column suffix = id.lower())
    label: str  # display label (12M renders as "1Y")
    scored: bool  # part of the score / rank / confidence (6M/12M/3Y); 2Y/5Y are display-only
    weeks: int  # trailing weekly-observation count for week-based slices
    offset_kind: str  # "months" or "years" — preserves the exact legacy DateOffset behavior
    offset_n: int  # magnitude for the calendar offset


# Order = selector display order. 6M/12M/3Y are the SCORING windows; 2Y/5Y are display-only
# longer lookbacks. Weeks: ~0.77 obs/week (12M=52, 2Y=104, 3Y=156, 5Y=260). Offsets preserve
# the legacy parser exactly (``…M`` -> DateOffset(months=N), ``…Y`` -> DateOffset(years=N)).
_WINDOWS: tuple[Window, ...] = (
    Window("6M", "6M", True, 26, "months", 6),
    Window("12M", "1Y", True, 52, "months", 12),
    Window("2Y", "2Y", False, 104, "years", 2),
    Window("3Y", "3Y", True, 156, "years", 3),
    Window("5Y", "5Y", False, 260, "years", 5),
)

_BY_ID: dict[str, Window] = {w.id: w for w in _WINDOWS}

# Display-label aliases accepted from the query string (plus the canonical ids themselves).
# "1Y" maps back to the 12M id.
_LABEL_ALIASES: dict[str, str] = {w.label.upper(): w.id for w in _WINDOWS}

# Ordered id tuples — the ONE definition other modules import instead of re-hardcoding.
ALL_WINDOWS: tuple[str, ...] = tuple(w.id for w in _WINDOWS)
SCORING_WINDOWS: tuple[str, ...] = tuple(w.id for w in _WINDOWS if w.scored)
DISPLAY_WINDOWS: tuple[str, ...] = tuple(w.id for w in _WINDOWS if not w.scored)
DEFAULT_WINDOW: str = "12M"  # the canonical anchor / detail-page default

# id -> display label (e.g. {"12M": "1Y"}).
WINDOW_LABELS: dict[str, str] = {w.id: w.label for w in _WINDOWS}


def _normalize(window_id: str) -> str:
    return str(window_id).strip().upper()


def is_window(window_id: str) -> bool:
    return _normalize(window_id) in _BY_ID


def get_window(window_id: str) -> Window:
    """The ``Window`` record for an id; raises on an unknown window (fail loud)."""
    normalized = _normalize(window_id)
    window = _BY_ID.get(normalized)
    if window is None:
        raise ValueError(f"Unsupported structural window: {window_id}")
    return window


def resolve_window_or_none(requested: str | None) -> str | None:
    """Canonical id for a requested window id OR display alias ('1y' -> '12M'), or None
    when unrecognised. Lets callers distinguish 'recognised alias' from 'invalid' so they
    can choose their own fallback (e.g. the detail page falls back to the ticker's anchor)."""
    normalized = _normalize(requested or "")
    if normalized in _BY_ID:
        return normalized
    return _LABEL_ALIASES.get(normalized)


def resolve_window(requested: str | None) -> str:
    """Normalise a query-string window ('1y', '12M', '3Y', …) to a canonical id; anything
    unrecognised falls back to ``DEFAULT_WINDOW``."""
    return resolve_window_or_none(requested) or DEFAULT_WINDOW


def window_suffix(window_id: str) -> str:
    """Per-window column suffix (e.g. '12m' for ``structural_delta_12m``)."""
    return str(window_id).lower()


def window_label(window_id: str) -> str:
    """Display label for a window id (12M -> '1Y'); echoes the id if unknown."""
    window = _BY_ID.get(_normalize(window_id))
    return window.label if window is not None else str(window_id)


def window_weeks(window_id: str) -> int:
    """Trailing weekly-observation count for a window (6M=26 … 5Y=260)."""
    return get_window(window_id).weeks


def is_scored(window_id: str) -> bool:
    """Whether a window is part of the score/rank/confidence (vs display-only)."""
    return get_window(window_id).scored


def window_offset(window_id: str) -> pd.DateOffset:
    """Calendar offset for a window. Registry windows use their stored offset; arbitrary
    ``<n>M`` / ``<n>Y`` horizon strings (e.g. the '1Y' alias, exploratory horizons) fall
    back to the general parser — preserving the legacy ``_window_offset`` behavior exactly:
    ``…M`` -> DateOffset(months=N), ``…Y`` -> DateOffset(years=N)."""
    normalized = _normalize(window_id)
    window = _BY_ID.get(normalized)
    if window is not None:
        return pd.DateOffset(**{window.offset_kind: window.offset_n})
    if normalized.endswith("M") and normalized[:-1].isdigit():
        return pd.DateOffset(months=int(normalized[:-1]))
    if normalized.endswith("Y") and normalized[:-1].isdigit():
        return pd.DateOffset(years=int(normalized[:-1]))
    raise ValueError(f"Unsupported structural window: {window_id}")
