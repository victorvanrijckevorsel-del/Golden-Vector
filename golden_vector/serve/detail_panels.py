"""Detail-panel rendering helpers for the workspace ticker page."""

from __future__ import annotations

from html import escape
from typing import Any, Mapping
from urllib.parse import quote

import pandas as pd

from golden_vector.serve.fundamentals_provenance import (
    ticker_provenance_icon,
)
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD,
    DETAIL_ALIGNMENT_FOUNDATION_MISSING,
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH,
    _STRUCTURAL_WINDOWS,
)
from golden_vector.common.windows import resolve_window_or_none


def _detail_alignment(
    tool_a_row: dict[str, Any],
    foundation_manifest: dict[str, Any] | None,
) -> str:
    """Decide whether the foundation-backed detail panels can render safely.

    Returns one of the DETAIL_ALIGNMENT_* constants. ALIGNED means the Tool A
    row and the current foundation manifest reference the same refresh run id.
    """

    if not foundation_manifest:
        return DETAIL_ALIGNMENT_FOUNDATION_MISSING
    foundation_refresh = str(foundation_manifest.get("refresh_run_id") or "").strip()
    if not foundation_refresh:
        return DETAIL_ALIGNMENT_FOUNDATION_MISSING
    tool_a_refresh = str(tool_a_row.get("snapshot_refresh_run_id") or "").strip()
    if not tool_a_refresh or tool_a_refresh.lower() == "nan":
        return DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH
    if tool_a_refresh != foundation_refresh:
        return DETAIL_ALIGNMENT_FOUNDATION_AHEAD
    return DETAIL_ALIGNMENT_ALIGNED


def _render_financials_source_switcher(
    *,
    ticker: str,
    financials_source: str,
    query_params: Mapping[str, str],
    fundamentals_provenance: dict[tuple[str, str], str],
) -> str:
    source = str(financials_source or "our").strip().lower()
    source = "yahoo" if source == "yahoo" else "our"
    base_path = f"/ticker/{quote(str(ticker), safe='')}"
    our_href = build_page_url(
        base_path,
        query_params,
        set_params={"fundamentals_source": None},
    )
    yahoo_href = build_page_url(
        base_path,
        query_params,
        set_params={"fundamentals_source": "yahoo"},
    )
    our_class = "button-like active" if source == "our" else "button-like"
    yahoo_class = "button-like active" if source == "yahoo" else "button-like"
    hint = (
        "<p class=\"hint\">Yahoo Fundamentals changes dual-source financial "
        "fields and derived checks; mining assumptions remain Our View.</p>"
        if source == "yahoo"
        else ""
    )
    icon = ticker_provenance_icon(ticker, fundamentals_provenance) if source == "yahoo" else ""
    return (
        "<div class=\"overview-filters-actions source-switcher\">"
        f"<span class=\"hint\">Financials source</span>"
        f"<a class=\"{our_class}\" href=\"{escape(our_href, quote=True)}\">Our View</a>"
        f"<a class=\"{yahoo_class}\" href=\"{escape(yahoo_href, quote=True)}\">Yahoo Fundamentals</a>"
        f"{icon}"
        "</div>"
        f"{hint}"
    )


def _canonical_anchor_window(tool_a_row: dict[str, Any]) -> str:
    """Return the ticker's canonical anchor window id (always 6M / 12M / 3Y).

    Falls back to 12M when the field is missing or malformed so the
    detail page keeps working even on incomplete fixtures.
    """
    raw = tool_a_row.get("anchor_window_id") if tool_a_row else None
    if raw is None:
        return "12M"
    try:
        if pd.isna(raw):
            return "12M"
    except TypeError:
        pass
    normalized = str(raw).strip().upper()
    return normalized if normalized in _STRUCTURAL_WINDOWS else "12M"


def _resolve_active_window(raw_param: str, canonical_anchor: str) -> str:
    """Map a URL `window=` value to a valid structural window id.

    Recognises canonical ids AND display aliases via the registry (so `?window=1y`
    resolves to 12M, not the canonical anchor). Invalid / missing params fall back to
    the ticker's canonical anchor. Case-insensitive.
    """
    resolved = resolve_window_or_none(raw_param)
    if resolved is not None:
        return resolved
    return canonical_anchor if canonical_anchor in _STRUCTURAL_WINDOWS else "12M"


