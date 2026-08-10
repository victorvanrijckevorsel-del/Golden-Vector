"""Gold Sensitivity (Tool A) overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape
from typing import Any

from golden_vector.serve.column_help import help_th, help_value
from golden_vector.serve.format_helpers import (
    _fmt_numeric_td,
    _frame_index_by_ticker,
    _optional_float,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.overview_helpers import (
    _collect_filter_options,
    _render_filter_bar,
    _render_provenance_warnings,
    _render_refresh_summary,
    note_counts_by_ticker,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import page_header
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.windows import (
    WINDOW_LABELS,
    gold_link_td,
    render_window_selector,
    resolve_window,
    win_num_td,
    window_is_reliable,
    window_metrics,
    window_suffix,
)
from golden_vector.serve.workspace_state import WorkspaceState


def _benchmark_reference_rows(benchmark_df: Any, active_window: str) -> str:
    """GDX / GDXJ reference rows for the selected window, rendered in <tfoot> so
    DataTables excludes them from the miner ranking / sort / filter (Codex). Each is the
    same-window benchmark beta from the persisted benchmark file; a benchmark whose status
    is not OK (or has no beta for this window) is dropped."""
    if benchmark_df is None or getattr(benchmark_df, "empty", True):
        return ""
    suffix = window_suffix(active_window)  # ONE window->column suffix map (serve/windows.py)
    rows: list[str] = []
    for _, r in benchmark_df.iterrows():
        if str(r.get("benchmark_status") or "").upper() not in ("", "OK"):
            continue
        up = _optional_float(r.get(f"up_beta_{suffix}"))
        down = _optional_float(r.get(f"down_beta_{suffix}"))
        if up is None and down is None:
            continue
        ticker = str(r.get("benchmark_ticker") or "")
        rows.append(
            "<tr class=\"reference-row\">"
            f"<td>{escape(ticker)} <span class=\"hint\">· benchmark</span></td>"
            + win_num_td(up, reliable=True)
            + win_num_td(down, reliable=True)
            + "<td class=\"hint\">—</td>"  # gold-link (n/a for the benchmark itself)
            + "<td class=\"hint\">—</td>"  # delta
            + "<td class=\"hint\">—</td>"  # gamma
            + "<td class=\"hint\">—</td>"  # asymmetry
            + f"<td>{escape(str(r.get('confidence_label') or '—'))}</td>"
            + "<td class=\"hint\">ETF</td>"  # profile
            + "<td class=\"hint\">—</td>"  # volatility
            + "<td class=\"hint\">—</td>"  # rank (benchmarks are not ranked)
            + "<td class=\"hint\">—</td>"  # notes
            + "</tr>"
        )
    if rows:
        return f"<tfoot>{''.join(rows)}</tfoot>"
    # No benchmark carries a beta for this window yet (e.g. GDX/GDXJ at 2Y/5Y before the
    # benchmark artifact is rebuilt with those columns). Show an explicit muted cue rather
    # than silently dropping the whole reference footer (an empty footer reads as a bug).
    label = WINDOW_LABELS.get(active_window, active_window)
    return (
        "<tfoot><tr class=\"reference-row\">"
        f"<td colspan=\"12\" class=\"hint\">GDX / GDXJ benchmark · n/a for the "
        f"{escape(label)} window yet</td></tr></tfoot>"
    )


def _render_tool_a_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
    window: str = "",
    app_config: Any = None,
) -> str:
    """Gold Sensitivity overview: which miners react strongly/weakly to gold, up vs down.

    Ranked by the cross-window gold-sensitivity rank (low-confidence names are held out).
    The beta window selector (6M / 1Y / 2Y / 3Y / 5Y) chooses which window's up/down beta,
    Gamma, Asymmetry and Gold-link (R²) are shown — a pure read of persisted Tool A columns.
    6M/1Y/3Y are the scoring windows; 2Y/5Y are display-only longer lookbacks.
    """
    active_window = resolve_window(window)
    note_counts = note_counts_by_ticker(state.stock_notes)
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
        m = window_metrics(ta, active_window)
        reliable = window_is_reliable(m)
        # Carry the active window through to the detail page so the selection isn't lost on
        # click-through (the detail page honours scoring windows and falls back gracefully
        # for the display-only 2Y/5Y). Reuse the shared suffix helper — no inline .lower().
        ticker_href = f"/ticker/{escape(row['ticker'])}?window={window_suffix(active_window)}"
        rows_html.append(
            "<tr>"
            f"<td><a href=\"{ticker_href}\">{escape(row['ticker'])}</a></td>"
            + win_num_td(m["up_beta"], reliable=reliable)
            + win_num_td(m["down_beta"], reliable=reliable)
            + gold_link_td(m["r_squared"])
            + win_num_td(m["delta"], reliable=reliable)
            + win_num_td(m["gamma"], reliable=reliable)
            + win_num_td(m["asymmetry"], reliable=reliable)
            + help_value(ta.get("confidence_label"), app_config=app_config)
            + help_value(ta.get("profile_label"), app_config=app_config)
            + help_value(ta.get("volatility_context"), app_config=app_config)
            + _fmt_numeric_td(row["tool_a_rank"], decimals=0)
            + _fmt_numeric_td(row["note_count"], decimals=0)
            + "</tr>"
        )
    # Empty state: the colspan row does not match the explicit column model that
    # workspace-tables.js hands DataTables, so drop js-datatable when there are no
    # data rows (same pattern as candidate_finder_page.py).
    table_class = "js-datatable" if rows_html else "empty-table"
    if not rows_html:
        rows_html.append("<tr><td colspan=\"12\" class=\"hint\">No tickers match.</td></tr>")

    filter_options = _collect_filter_options(
        [r["tool_a_row"] for r in derived],
        [
            ("profile", "profile_label"),
            ("confidence", "confidence_label"),
            ("volatility", "volatility_context"),
        ],
    )

    body = [page_header(
        "Gold Sensitivity",
        lead_html=(
        "<p>Which miners react strongly or weakly to the gold price — split by direction "
        "(up vs down). The beta columns (up/down beta, delta, gamma, asymmetry, gold-link) "
        "follow the window selector below; <strong>Confidence, Profile and Rank are computed "
        "across the scoring windows (6M / 1Y / 3Y) and do not change with the selector</strong> "
        "(low-confidence names are held out of the rank). <strong>Gold-link</strong> shows how "
        "much of each stock's movement gold actually explains in the chosen window — a "
        "'weak'/'none' beta barely tracks gold, so treat it with caution. Click a ticker for "
        "the full breakdown and the gold / stock / ETF overlay.</p>"
        ),
    )]
    if flash:
        body.append(notice("success", escape(flash)))
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(render_window_selector(active_window, search=search))
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-a\" class=\"overview-filters-form\">"
        f"<input type=\"hidden\" name=\"window\" value=\"{escape(active_window)}\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(derived)} tickers shown · {escape(WINDOW_LABELS[active_window])} beta window.</span>"
        "<button type=\"submit\" class=\"btn btn-primary\">Apply</button>"
        f"<a class=\"btn btn-tertiary\" href=\"/tool-a?window={escape(active_window)}\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(_render_filter_bar(
        target_table_id="tool-a-table",
        options=filter_options,
        column_labels={"profile": "Profile", "confidence": "Confidence", "volatility": "Volatility"},
    ))
    body.append(table_region(
        f"<table id=\"tool-a-table\" class=\"{table_class}\">"
        "<thead><tr>"
        + help_th("Ticker", key="ticker_symbol", app_config=app_config, col_name="ticker")
        + help_th("Up-β", key="tool_a_up_beta", app_config=app_config, col_name="up_beta", sort_numeric=True)
        + help_th("Down-β", key="tool_a_down_beta", app_config=app_config, col_name="down_beta", sort_numeric=True)
        + help_th("Gold-link", key="tool_a_gold_link", app_config=app_config, col_name="gold_link", sort_numeric=True)
        + help_th("Δ Core", key="tool_a_delta", app_config=app_config, col_name="delta", sort_numeric=True)
        + help_th("Gamma", key="tool_a_gamma", app_config=app_config, col_name="gamma", sort_numeric=True)
        + help_th("Asymmetry", key="tool_a_asymmetry", app_config=app_config, col_name="asymmetry", sort_numeric=True)
        + help_th("Confidence", key="tool_a_confidence", app_config=app_config, col_name="confidence")
        + help_th("Profile", key="tool_a_profile", app_config=app_config, col_name="profile")
        + help_th("Volatility", key="tool_a_volatility", app_config=app_config, col_name="volatility")
        + help_th("Rank", key="tool_a_rank", app_config=app_config, col_name="rank", sort_numeric=True)
        + help_th("Notes", key="user_notes_count", app_config=app_config, col_name="notes", sort_numeric=True)
        + "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        + _benchmark_reference_rows(state.latest_benchmark_betas, active_window)
        + "</table>",
        region_id="tool-a-table-region",
        label="Gold Sensitivity comparison",
    ))
    return _page_shell("Gold Sensitivity - Golden Vector Workspace", "".join(body), active_nav="tool_a")
