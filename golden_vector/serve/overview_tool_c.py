"""Tool C overview rendering for the workspace UI."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any
from urllib.parse import quote

from golden_vector.serve.format_helpers import _fmt_numeric_td, collapsible_text_td
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.overview_helpers import (
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.column_help import help_th
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import empty_state, page_header, terminal_density
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.contracts.config_models import ConfidenceThresholds
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


def _render_tool_c_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
    window: str = "",
    app_config: Any = None,
    current_query: Mapping[str, str] | None = None,
) -> str:
    """Render the persisted Tool C symmetric gold-downside rankings.

    The beta window selector (6M / 1Y / 2Y / 3Y / 5Y) switches the displayed up/down gold
    beta + Gold-link (R²) per lookback — a pure read of persisted columns. The downside/
    upside RANK stays on the validated cross-window *_core betas (display windows never
    change the rank; 6M/1Y/3Y are the scoring windows, 2Y/5Y display-only)."""

    active_window = resolve_window(window)
    search_term = str(search or "").strip().upper()
    frame = state.latest_tool_c.copy()
    if not frame.empty and search_term and "ticker" in frame.columns:
        frame = frame.loc[
            frame["ticker"].astype(str).str.upper().str.contains(search_term, na=False)
        ].copy()
    # Row order is owned by the writer: golden_vector/model/tool_c.py sorts the
    # persisted output by (tool_c_downside_rank desc, tool_c_upside_rank desc,
    # ticker asc). Serve must not re-sort — a coarser re-sort here can only
    # scramble the writer's tie-breaks.

    # Gold-link bands live once, in config (deep-review F3).
    bands = (
        app_config.scoring.confidence_thresholds
        if app_config is not None
        else ConfidenceThresholds()
    )
    rows_html: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        # Windowed up/down beta + Gold-link for the selected lookback (muted when the
        # window's gold-link is weak/thin). The rank columns stay on the *_core scores.
        m = window_metrics(row, active_window)
        reliable = window_is_reliable(m, thresholds=bands)
        ticker_href = build_page_url(
            f"/ticker/{quote(ticker, safe='')}",
            {},
            set_params={"window": window_suffix(active_window)},
        )
        rows_html.append(
            "<tr>"
            f'<td><a href="{escape(ticker_href, quote=True)}">{escape(ticker)}</a></td>'
            f"{_fmt_numeric_td(row.get('tool_c_downside_rank'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('tool_c_upside_rank'), decimals=1)}"
            + win_num_td(m["down_beta"], reliable=reliable)
            + win_num_td(m["up_beta"], reliable=reliable)
            + gold_link_td(m["r_squared"], thresholds=bands)
            + f"{_fmt_numeric_td(row.get('downside_hit_rate_10pct'), decimals=1, as_percent=True)}"
            + f"{_fmt_numeric_td(row.get('upside_hit_rate_10pct'), decimals=1, as_percent=True)}"
            + collapsible_text_td(row.get("tool_c_downside_tags"))
            + collapsible_text_td(row.get("tool_c_upside_tags"))
            + "</tr>"
        )
    body = [
        page_header(
            "Gold Downside",
            lead_html=(
                "<p>Ranks symmetric gold-downside and gold-upside behavior "
                "from persisted outputs.</p>"
            ),
        )
    ]
    if flash:
        body.append(notice("success", escape(flash)))
    if not state.tool_c_alias_present:
        body.append(
            notice(
                "warning",
                "Gold Downside output is missing. "
                "Run <code>python main.py tool-c</code> after a refresh.",
            )
        )
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        render_window_selector(
            active_window,
            search=search,
            target="/tool-c",
            current_query=current_query,
        )
    )
    reset_href = build_page_url(
        "/tool-c",
        dict(current_query or {}),
        set_params={"search": None, "window": active_window},
    )
    body.append(
        '<section class="panel">'
        '<form method="get" action="/tool-c" class="overview-filters-form">'
        f'<input type="hidden" name="window" value="{escape(active_window)}">'
        f'<label><span>Search ticker</span><input class="form-control" name="search" type="text" value="{escape(search)}" placeholder="NEM"></label>'
        '<div class="overview-filters-actions">'
        f'<span class="hint">{len(frame.index)} rows shown · {escape(WINDOW_LABELS[active_window])} beta window.</span>'
        '<button type="submit" class="control control--primary">Apply</button>'
        f'<a class="control control--quiet" href="{escape(reset_href, quote=True)}">Reset</a>'
        "</div>"
        "</form>"
        "</section>"
    )
    if rows_html:
        body.append(
            table_region(
                '<table id="tool-c-table" class="js-datatable">'
                "<thead><tr>"
                + help_th("Ticker", key="ticker_symbol", app_config=app_config, col_name="ticker")
                + help_th(
                    "Downside Score",
                    key="tool_c_downside_rank",
                    app_config=app_config,
                    col_name="downside_rank",
                    sort_numeric=True,
                )
                + help_th(
                    "Upside Score",
                    key="tool_c_upside_rank",
                    app_config=app_config,
                    col_name="upside_rank",
                    sort_numeric=True,
                )
                + help_th(
                    "Down Beta",
                    key="tool_c_down_beta",
                    app_config=app_config,
                    col_name="down_beta",
                    sort_numeric=True,
                )
                + help_th(
                    "Up Beta",
                    key="tool_c_up_beta",
                    app_config=app_config,
                    col_name="up_beta",
                    sort_numeric=True,
                )
                + help_th(
                    "Gold-link",
                    key="tool_a_gold_link",
                    app_config=app_config,
                    col_name="gold_link",
                    sort_numeric=True,
                )
                # Named for the weeks they count, matching the ticker page's
                # grouping ("When gold was weakest" / "…strongest"). The old
                # "Down Hit Rate" / "Up Hit Rate" gave the same persisted metric
                # a third vocabulary and said nothing about the conditioning.
                + help_th(
                    "Big down week (gold weak)",
                    key="tool_c_down_hit_rate",
                    app_config=app_config,
                    col_name="down_hit",
                    sort_numeric=True,
                )
                + help_th(
                    "Big up week (gold strong)",
                    key="tool_c_up_hit_rate",
                    app_config=app_config,
                    col_name="up_hit",
                    sort_numeric=True,
                )
                + help_th(
                    "Down Tags",
                    key="tool_c_downside_tags",
                    app_config=app_config,
                    col_name="down_tags",
                )
                + help_th(
                    "Up Tags", key="tool_c_upside_tags", app_config=app_config, col_name="up_tags"
                )
                + "</tr></thead>"
                f"<tbody>{''.join(rows_html)}</tbody>"
                "</table>",
                region_id="tool-c-table-region",
                label="Gold Downside comparison",
            )
        )
    else:
        empty_title = (
            "No Gold Downside rows are available."
            if state.latest_tool_c.empty
            else "No tickers match this search."
        )
        body.append(
            empty_state(
                empty_title,
                body_html=(
                    '<p class="hint">Change the ticker search or reset it '
                    "to show the full persisted view.</p>"
                ),
            )
        )
    return _page_shell(
        "Gold Downside - Golden Vector Workspace",
        terminal_density("".join(body)),
        active_nav="tool_c",
    )
