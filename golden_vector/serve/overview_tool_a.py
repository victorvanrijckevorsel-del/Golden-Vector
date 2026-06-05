"""Tool A overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape
from typing import Any

from golden_vector.serve.format_helpers import (
    _fmt_numeric_td,
    _fmt_text,
    _frame_index_by_ticker,
    _optional_float,
)
from golden_vector.serve.overview_combined import (
    _collect_filter_options,
    _render_filter_bar,
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.workspace_state import WorkspaceState


def _render_tool_a_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
) -> str:
    """Tool A focused overview: ranked by gold-sensitivity score.

    Shows only Tool A-relevant columns (delta, gamma, asymmetry, confidence,
    volatility, score, rank, profile). No Tool B noise.
    """
    note_counts = (
        state.stock_notes.groupby("ticker").size().to_dict()
        if not state.stock_notes.empty and "ticker" in state.stock_notes.columns
        else {}
    )
    tool_a_index = _frame_index_by_ticker(state.latest_tool_a)
    search_term = str(search or "").strip().upper()

    derived: list[dict[str, Any]] = []
    for ticker in state.tool_b_tickers:
        if search_term and search_term not in ticker:
            continue
        tool_a_row = tool_a_index.get(ticker, {})
        derived.append({
            "ticker": ticker,
            "tool_a_row": tool_a_row,
            "tool_a_rank": _optional_float(tool_a_row.get("tool_a_rank")),
            "note_count": int(note_counts.get(ticker, 0)),
        })
    derived.sort(key=lambda r: (0 if r["tool_a_rank"] is not None else 1,
                                 r["tool_a_rank"] if r["tool_a_rank"] is not None else 0.0,
                                 r["ticker"]))

    rows_html: list[str] = []
    for row in derived:
        ta = row["tool_a_row"]
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            f"<td>{_fmt_text(ta.get('profile_label'))}</td>"
            f"{_fmt_numeric_td(ta.get('structural_delta_core'), decimals=2)}"
            f"{_fmt_numeric_td(ta.get('structural_gamma_core'), decimals=2)}"
            f"{_fmt_numeric_td(ta.get('asymmetry_ratio_core'), decimals=2)}"
            f"<td>{_fmt_text(ta.get('confidence_label'))}</td>"
            f"<td>{_fmt_text(ta.get('volatility_context'))}</td>"
            f"{_fmt_numeric_td(ta.get('tool_a_score'), decimals=1)}"
            f"{_fmt_numeric_td(row['tool_a_rank'], decimals=0)}"
            f"{_fmt_numeric_td(row['note_count'], decimals=0)}"
            "</tr>"
        )
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"10\" class=\"hint\">No tickers match.</td></tr>"
        )

    filter_options = _collect_filter_options(
        [r["tool_a_row"] for r in derived],
        [
            ("profile", "profile_label"),
            ("confidence", "confidence_label"),
            ("volatility", "volatility_context"),
        ],
    )

    body = ["<h1>Tool A — Gold Sensitivity Ranking</h1>"]
    body.append(
        "<p>Ranks the universe by structural sensitivity to the gold price. "
        "Lower rank is better. Negative gamma is favorable (up-gold sensitivity exceeds down-gold sensitivity). "
        "Click a ticker for the full structural breakdown and beta-history chart.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-a\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(derived)} tickers shown.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/tool-a\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(_render_filter_bar(
        target_table_id="tool-a-table",
        options=filter_options,
        column_labels={"profile": "Profile", "confidence": "Confidence", "volatility": "Volatility"},
    ))
    body.append(
        "<table id=\"tool-a-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"profile\">Profile</th>"
        "<th data-col-name=\"delta\" data-sort-numeric>Δ Core</th>"
        "<th data-col-name=\"gamma\" data-sort-numeric>Gamma</th>"
        "<th data-col-name=\"asymmetry\" data-sort-numeric>Asymmetry</th>"
        "<th data-col-name=\"confidence\">Confidence</th>"
        "<th data-col-name=\"volatility\">Volatility</th>"
        "<th data-col-name=\"score\" data-sort-numeric>Tool A Score</th>"
        "<th data-col-name=\"rank\" data-sort-numeric>Rank</th>"
        "<th data-col-name=\"notes\" data-sort-numeric>Notes</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell("Tool A — Gold Vector Workspace", "".join(body), active_nav="tool_a")
