"""Ticker detail page rendering for the workspace UI."""

from __future__ import annotations

from html import escape

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
    _render_option_trading_panel,
    _render_window_switcher,
)
from golden_vector.serve.format_helpers import _frame_index_by_ticker, _ticker_rows
from golden_vector.serve.page_shell import _page_shell
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
    visible_windows: list[str] | None = None,
    lens: str = DETAIL_DEFAULT_LENS_ID,
    app_config: AppConfig | None = None,
    option_trading_detail: OptionTradingDetailData | None = None,
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    verification_rows = _ticker_rows(state.source_verification, ticker)
    note_rows = _ticker_rows(state.stock_notes, ticker)
    if visible_windows is None:
        visible_windows = [active_window]

    body = [f"<p><a href=\"/\">Back to workspace</a></p>", f"<h1>{escape(ticker)}</h1>"]
    body.append(_render_window_switcher(ticker=ticker, active=active_window, canonical=canonical_anchor))
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if error:
        body.append(f"<div class=\"flash\">{escape(error)}</div>")
    alignment = _detail_alignment(tool_a_row, state.foundation_manifest)
    body.append(
        _render_latest_panels(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_b_row=tool_b_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            visible_windows=visible_windows,
            app_config=app_config,
        )
    )
    body.append(_render_option_trading_panel(option_trading_detail))
    body.append(
        _render_company_form(
            ticker=ticker,
            company_row=company_row,
            verification_rows=verification_rows,
        )
    )
    body.append(_render_reporting_form(ticker=ticker, reporting_row=reporting_row))
    body.append(_render_verification_section(ticker=ticker, verification_rows=verification_rows))
    body.append(_render_note_section(ticker=ticker, note_rows=note_rows))
    active_nav = "option_trading" if lens == DETAIL_OPTION_TRADING_LENS_ID else "combined"
    return _page_shell(
        f"Golden Vector Workspace - {ticker}",
        "".join(body),
        active_nav=active_nav,
    )
