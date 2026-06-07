"""Tool C overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape

from golden_vector.serve.format_helpers import _fmt_numeric_td, _fmt_text
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.overview_helpers import (
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.workspace_state import WorkspaceState


def _render_tool_c_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
) -> str:
    """Render the persisted Tool C symmetric gold-downside rankings."""

    search_term = str(search or "").strip().upper()
    frame = state.latest_tool_c.copy()
    if not frame.empty and search_term and "ticker" in frame.columns:
        frame = frame.loc[
            frame["ticker"].astype(str).str.upper().str.contains(search_term, na=False)
        ].copy()
    if not frame.empty and {"tool_c_downside_rank", "ticker"}.issubset(frame.columns):
        frame = frame.sort_values(
            ["tool_c_downside_rank", "ticker"],
            ascending=[False, True],
            na_position="last",
        )

    rows_html: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"{_fmt_numeric_td(row.get('tool_c_downside_rank'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('tool_c_downside_score'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('tool_c_upside_rank'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('tool_c_upside_score'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('down_beta_core'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('up_beta_core'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('downside_hit_rate_10pct'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('upside_hit_rate_10pct'), decimals=1, as_percent=True)}"
            f"<td>{_fmt_text(row.get('tool_c_downside_tags'))}</td>"
            f"<td>{_fmt_text(row.get('tool_c_upside_tags'))}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html.append("<tr><td colspan=\"11\" class=\"hint\">No Gold Downside rows found.</td></tr>")

    body = ["<h1>Gold Downside</h1>"]
    body.append(
        "<p>Ranks symmetric gold-downside and gold-upside behavior from persisted outputs.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if not state.tool_c_alias_present:
        body.append(
            "<div class=\"flash flash-warning\">Gold Downside output is missing. "
            "Run <code>python main.py tool-c</code> after a refresh.</div>"
        )
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-c\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(frame.index)} rows shown.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/tool-c\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(
        "<table id=\"tool-c-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"downside_rank\" data-sort-numeric>Downside Rank</th>"
        "<th data-col-name=\"downside_score\" data-sort-numeric>Downside Score</th>"
        "<th data-col-name=\"upside_rank\" data-sort-numeric>Upside Rank</th>"
        "<th data-col-name=\"upside_score\" data-sort-numeric>Upside Score</th>"
        "<th data-col-name=\"down_beta\" data-sort-numeric>Down Beta</th>"
        "<th data-col-name=\"up_beta\" data-sort-numeric>Up Beta</th>"
        "<th data-col-name=\"down_hit\" data-sort-numeric>Down Hit Rate</th>"
        "<th data-col-name=\"up_hit\" data-sort-numeric>Up Hit Rate</th>"
        "<th data-col-name=\"down_tags\">Down Tags</th>"
        "<th data-col-name=\"up_tags\">Up Tags</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell(
        "Gold Downside - Golden Vector Workspace",
        "".join(body),
        active_nav="tool_c",
    )
