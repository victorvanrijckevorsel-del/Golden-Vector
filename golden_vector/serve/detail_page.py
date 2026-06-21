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
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    verification_rows = _ticker_rows(state.source_verification, ticker)
    note_rows = _ticker_rows(state.stock_notes, ticker)
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
        f"<p><a href=\"{escape(back_href, quote=True)}\">Back to workspace</a></p>",
        f"<h1>{escape(ticker)}</h1>",
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
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if error:
        body.append(f"<div class=\"flash\">{escape(error)}</div>")
    alignment = _detail_alignment(tool_a_row, state.foundation_manifest)
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
    body.append(
        _render_option_trading_panel(
            option_trading_detail,
            model_state_manifest=model_state_manifest,
            app_config=app_config,
            financials_source=financials_source,
        )
        if option_lens_active
        else _render_option_trading_link_panel(
            ticker,
            financials_source=financials_source,
        )
    )
    if show_manual_sections:
        body.append(
            _render_company_form(
                ticker=ticker,
                company_row=company_row,
                verification_rows=verification_rows,
                return_to=return_to,
            )
        )
        body.append(
            _render_reporting_form(
                ticker=ticker,
                reporting_row=reporting_row,
                return_to=return_to,
            )
        )
        body.append(
            _render_verification_section(
                ticker=ticker,
                verification_rows=verification_rows,
                return_to=return_to,
            )
        )
        body.append(_render_note_section(ticker=ticker, note_rows=note_rows, return_to=return_to))
    active_nav = "option_trading" if option_lens_active else "candidate_finder"
    return _page_shell(
        f"Golden Vector Workspace - {ticker}",
        "".join(body),
        active_nav=active_nav,
    )
