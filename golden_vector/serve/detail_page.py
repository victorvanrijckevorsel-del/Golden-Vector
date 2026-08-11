"""Ticker detail page rendering for the workspace UI."""

from __future__ import annotations

from html import escape
from typing import Mapping
from urllib.parse import quote

from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge.option_trading import OptionTradingDetailData
from golden_vector.serve.detail_forms import (
    _render_company_form,
    _render_note_section,
    _render_reporting_form,
    _render_verification_section,
)
from golden_vector.serve.detail_panels import (
    _detail_alignment,
    _render_latest_panels,
    _render_option_trading_link_panel,
    _render_option_trading_panel,
    _render_window_switcher,
)
from golden_vector.serve.format_helpers import _frame_index_by_ticker, _ticker_rows
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import page_header, section_nav
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ticker_page import (
    TickerPageData,
    render_cost_downside_card,
    render_currency_attribution_block,
    render_performance_section,
)
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.serve.workspace_state import ToolADetailState, WorkspaceState


DETAIL_DEFAULT_LENS_ID = "tool-a"
DETAIL_OPTION_TRADING_LENS_ID = "option-trading"
DETAIL_LENS_IDS = frozenset({DETAIL_DEFAULT_LENS_ID, DETAIL_OPTION_TRADING_LENS_ID})


def resolve_detail_lens(raw_lens: str | None) -> str:
    normalized = str(raw_lens or "").strip().lower()
    if normalized in DETAIL_LENS_IDS:
        return normalized
    return DETAIL_DEFAULT_LENS_ID


def render_detail_page(
    state: WorkspaceState,
    *,
    ticker: str,
    tool_a_detail: ToolADetailState,
    flash: str | None,
    error: str | None = None,
    active_window: str = "12M",
    canonical_anchor: str = "12M",
    lens: str = DETAIL_DEFAULT_LENS_ID,
    app_config: AppConfig | None = None,
    option_trading_detail: OptionTradingDetailData | None = None,
    show_workspace_panels: bool = True,
    show_manual_sections: bool = True,
    model_state_manifest: dict[str, object] | None = None,
    financials_source: str = "our",
    query_params: Mapping[str, str] | None = None,
    fundamentals_provenance: dict[tuple[str, str], str] | None = None,
    form_overrides: Mapping[str, Mapping[str, str]] | None = None,
    ticker_page_data: TickerPageData | None = None,
    chart_horizon: str = "1Y",
    chart_view: str = "rebased",
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    verification_rows = _ticker_rows(state.source_verification, ticker)
    note_rows = _ticker_rows(state.stock_notes, ticker)
    # Rejected-POST echo: hand the raw submitted strings to the form renderers
    # as display-verbatim overrides. They must NEVER be overlaid onto the row
    # dicts — _format_form_value would reinterpret them (it multiplies stored
    # rate FRACTIONS by 100 for display, so an echoed "5" became "500" and a
    # re-save silently persisted a 500% rate — deep-review H1).
    overrides_by_section = dict(form_overrides or {})
    company_overrides = dict(overrides_by_section.get("company") or {})
    reporting_overrides = dict(overrides_by_section.get("reporting") or {})
    note_overrides = dict(overrides_by_section.get("note") or {})
    verification_overrides = dict(overrides_by_section.get("verification") or {})
    verification_field = str(verification_overrides.get("field_name") or "").strip()
    if verification_field:
        echoed = {
            key: value
            for key, value in verification_overrides.items()
            if key in {"source_date", "source_url", "notes", "verification_status"}
        }
        matched = False
        merged_rows = []
        for row in verification_rows:
            if str(row.get("field_name") or "").strip() == verification_field:
                merged_rows.append({**row, **echoed})
                matched = True
            else:
                merged_rows.append(row)
        if not matched:
            merged_rows.append({"field_name": verification_field, **echoed})
        verification_rows = merged_rows
    current_query = dict(query_params or {})
    current_query.pop("saved", None)
    ticker_path = f"/ticker/{quote(str(ticker), safe='')}"
    return_to = build_page_url(ticker_path, current_query, set_params={})

    option_lens_active = str(lens or "").strip().lower() == DETAIL_OPTION_TRADING_LENS_ID
    back_href = build_page_url(
        "/",
        {},
        set_params=(
            {"fundamentals_source": "yahoo"}
            if str(financials_source).strip().lower() == "yahoo"
            else {}
        ),
    )
    body = [
        f"<p class=\"back-link\"><a href=\"{escape(back_href, quote=True)}\">Back to workspace</a></p>",
        page_header(ticker),
    ]
    if show_workspace_panels:
        body.append(
            _render_window_switcher(
                ticker=ticker,
                active=active_window,
                canonical=canonical_anchor,
                lens=DETAIL_OPTION_TRADING_LENS_ID if option_lens_active else None,
                anchor="option-trading" if option_lens_active else None,
                sizing_request=(
                    option_trading_detail.sizing.request
                    if option_lens_active
                    and option_trading_detail is not None
                    and option_trading_detail.sizing is not None
                    else None
                ),
                financials_source=financials_source,
            )
        )
    elif option_lens_active:
        body.append(
            "<p class=\"hint\">Option vehicle page. This ticker is used for listed "
            "option liquidity and scenarios, not as a Gold Sensitivity / Corporate Finance mining-company row.</p>"
        )
    # Sticky in-page anchors (plan 15/23): only sections that exist for the
    # current lens/vehicle. All targets are ids rendered by the panels/forms.
    anchors: list[tuple[str, str]] = []
    if show_workspace_panels:
        anchors += [
            ("gold-sensitivity", "Gold Sensitivity"),
            ("charts", "Charts"),
            ("corporate-finance", "Corporate Finance"),
        ]
    anchors.append(("option-trading", "Option Trading"))
    if show_manual_sections:
        anchors += [
            ("inputs", "Inputs"),
            ("reporting", "Reporting"),
            ("verification", "Verification"),
            ("notes", "Notes"),
        ]
    body.append(section_nav(anchors))
    if flash:
        body.append(notice("success", escape(flash)))
    if error:
        body.append(notice("danger", escape(error)))
    alignment = _detail_alignment(tool_a_row, state.foundation_manifest)
    if show_workspace_panels and ticker_page_data is not None:
        # Redesign M3a: the persisted-performance chart + Currency attribution
        # (Feature A) render ABOVE the legacy panels; the artifact rows are the
        # only source — nothing recomputes here.
        body.append(
            render_performance_section(
                ticker_page_data.performance_rows(ticker),
                ticker=ticker,
                horizon=chart_horizon,
                view=chart_view,
            )
        )
        body.append(
            render_currency_attribution_block(
                ticker_page_data.fx_attribution_rows(ticker),
                ticker=ticker,
                horizon=chart_horizon,
            )
        )
    if show_workspace_panels:
        body.append(
            _render_latest_panels(
                ticker=ticker,
                tool_a_row=tool_a_row,
                tool_b_row=tool_b_row,
                tool_a_detail=tool_a_detail,
                alignment=alignment,
                active_window=active_window,
                app_config=app_config,
                financials_source=financials_source,
                query_params=query_params,
                fundamentals_provenance=fundamentals_provenance,
            )
        )
    if show_workspace_panels and ticker_page_data is not None:
        # Feature B: Cost position and downside record (Market Behaviour).
        body.append(
            render_cost_downside_card(
                ticker=ticker,
                aisc_row=ticker_page_data.metric_row(
                    ticker, metric_key="aisc", finance_source=financials_source
                ),
                downside_row=ticker_page_data.metric_row(
                    ticker, metric_key="downside_hit_rate", finance_source=financials_source
                ),
                aisc_peers=ticker_page_data.metric_peers(
                    metric_key="aisc", finance_source=financials_source
                ),
                downside_peers=ticker_page_data.metric_peers(
                    metric_key="downside_hit_rate", finance_source=financials_source
                ),
            )
        )
    body.append(
        _render_option_trading_panel(
            option_trading_detail,
            model_state_manifest=model_state_manifest,
            app_config=app_config,
            financials_source=financials_source,
            active_window=active_window,
            canonical_anchor=canonical_anchor,
        )
        if option_lens_active
        else _render_option_trading_link_panel(
            ticker,
            financials_source=financials_source,
            active_window=active_window,
            canonical_anchor=canonical_anchor,
        )
    )
    if show_manual_sections:
        body.append(
            _render_company_form(
                ticker=ticker,
                company_row=company_row,
                verification_rows=verification_rows,
                return_to=return_to,
                raw_overrides=company_overrides or None,
            )
        )
        body.append(
            _render_reporting_form(
                ticker=ticker,
                reporting_row=reporting_row,
                return_to=return_to,
                raw_overrides=reporting_overrides or None,
            )
        )
        body.append(
            _render_verification_section(
                ticker=ticker,
                verification_rows=verification_rows,
                return_to=return_to,
            )
        )
        body.append(
            _render_note_section(
                ticker=ticker,
                note_rows=note_rows,
                return_to=return_to,
                raw_overrides=note_overrides or None,
            )
        )
    active_nav = "option_trading" if option_lens_active else "candidate_finder"
    return _page_shell(
        f"Golden Vector Workspace - {ticker}",
        "".join(body),
        active_nav=active_nav,
    )
