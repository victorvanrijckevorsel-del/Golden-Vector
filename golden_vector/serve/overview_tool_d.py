"""Tool D overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape

from golden_vector.serve.format_helpers import _fmt_numeric_td, _fmt_text
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.overview_combined import (
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.workspace_state import WorkspaceState


def _render_tool_d_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
) -> str:
    """Render the persisted Tool D corporate-resilience scorecard."""

    search_term = str(search or "").strip().upper()
    frame = state.latest_tool_d.copy()
    if not frame.empty and search_term and "ticker" in frame.columns:
        frame = frame.loc[
            frame["ticker"].astype(str).str.upper().str.contains(search_term, na=False)
        ].copy()
    if not frame.empty and {"tool_d_quality_rank", "ticker"}.issubset(frame.columns):
        frame = frame.sort_values(
            ["tool_d_quality_rank", "ticker"],
            ascending=[False, True],
            na_position="last",
        )

    rows_html: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"{_fmt_numeric_td(row.get('tool_d_quality_rank'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('tool_d_quality_score'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('gold_price_used'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('headroom_to_breakeven_pct_at_g'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('leverage_stressed_at_g'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('ev_ebitda_at_g'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('margin_per_oz_at_g'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('fcf_yield'), decimals=1, as_percent=True)}"
            f"<td>{_fmt_text(row.get('screening_verdict'))}</td>"
            f"<td>{_fmt_text(row.get('tool_d_tags'))}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html.append("<tr><td colspan=\"11\" class=\"hint\">No Corporate Resilience rows found.</td></tr>")

    body = ["<h1>Corporate Resilience</h1>"]
    body.append(
        "<p>Ranks corporate resilience from persisted outputs at the current spot-gold run.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if not state.tool_d_alias_present:
        body.append(
            "<div class=\"flash flash-warning\">Corporate Resilience output is missing. "
            "Run <code>python main.py tool-d</code> after Corporate Finance.</div>"
        )
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-d\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(frame.index)} rows shown.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/tool-d\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(
        "<table id=\"tool-d-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"quality_rank\" data-sort-numeric>Quality Rank</th>"
        "<th data-col-name=\"quality_score\" data-sort-numeric>Quality Score</th>"
        "<th data-col-name=\"gold_price\" data-sort-numeric>Gold Price</th>"
        "<th data-col-name=\"headroom\" data-sort-numeric>Headroom</th>"
        "<th data-col-name=\"leverage\" data-sort-numeric>Stressed Leverage</th>"
        "<th data-col-name=\"ev_ebitda\" data-sort-numeric>EV/EBITDA</th>"
        "<th data-col-name=\"margin\" data-sort-numeric>Margin/Oz</th>"
        "<th data-col-name=\"fcf_yield\" data-sort-numeric>FCF Yield</th>"
        "<th data-col-name=\"verdict\">Verdict</th>"
        "<th data-col-name=\"tags\">Tags</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell(
        "Corporate Resilience - Golden Vector Workspace",
        "".join(body),
        active_nav="tool_d",
    )
