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
from golden_vector.serve.windows import (
    WINDOW_LABELS,
    r2_band,
    render_window_selector,
    resolve_window,
    window_is_reliable,
    window_metrics,
)
from golden_vector.serve.workspace_state import WorkspaceState


def _win_num_td(value: float | None, *, reliable: bool, decimals: int = 2) -> str:
    """A window-specific numeric cell. Sorts by ``data-order``; when the selected
    window's gold-link is weak/thin the number is muted (Codex: weak evidence must
    DISPLAY as weak, not just carry a warning)."""
    if value is None or value != value:
        return "<td data-order=\"-999\"><span class=\"hint\">—</span></td>"
    txt = f"{value:.{decimals}f}"
    body = txt if reliable else f"<span class=\"hint\" title=\"weak gold-link — treat with caution\">{txt}</span>"
    return f"<td data-order=\"{value:.4f}\">{body}</td>"


def _gold_link_td(r_squared: float | None) -> str:
    """The trust column: how much of the stock's moves gold explains in this window.
    Sortable by R² via ``data-order``; weak/none is muted."""
    band, fit_ok = r2_band(r_squared)
    if r_squared is None:
        return "<td data-order=\"-1\"><span class=\"hint\">—</span></td>"
    inner = f"{band} · {r_squared * 100:.0f}%"
    body = inner if fit_ok else f"<span class=\"hint\">{inner}</span>"
    return f"<td data-order=\"{r_squared:.4f}\">{body}</td>"


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
    The beta window selector (6M / 1Y / 3Y) chooses which window's up/down beta, Gamma,
    Asymmetry and Gold-link (R²) are shown — a pure read of persisted Tool A columns.
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
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            + _win_num_td(m["up_beta"], reliable=reliable)
            + _win_num_td(m["down_beta"], reliable=reliable)
            + _gold_link_td(m["r_squared"])
            + _win_num_td(m["delta"], reliable=reliable)
            + _win_num_td(m["gamma"], reliable=reliable)
            + _win_num_td(m["asymmetry"], reliable=reliable)
            + help_value(ta.get("confidence_label"), app_config=app_config)
            + help_value(ta.get("profile_label"), app_config=app_config)
            + help_value(ta.get("volatility_context"), app_config=app_config)
            + _fmt_numeric_td(row["tool_a_rank"], decimals=0)
            + _fmt_numeric_td(row["note_count"], decimals=0)
            + "</tr>"
        )
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

    body = ["<h1>Gold Sensitivity</h1>"]
    body.append(
        "<p>Which miners react strongly or weakly to the gold price — split by direction "
        "(up vs down). Ranked by the cross-window gold-sensitivity rank; low-confidence names "
        "are held out. <strong>Gold-link</strong> shows how much of each stock's movement gold "
        "actually explains in the chosen window — a 'weak'/'none' beta barely tracks gold, so "
        "treat it with caution. Click a ticker for the full breakdown and beta-history chart.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
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
        "<button type=\"submit\">Apply</button>"
        f"<a class=\"hint\" href=\"/tool-a?window={escape(active_window)}\">Reset</a>"
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
        "</table>"
    )
    return _page_shell("Gold Sensitivity - Golden Vector Workspace", "".join(body), active_nav="tool_a")
