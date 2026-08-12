"""Ticker detail page rendering for the workspace UI."""

from __future__ import annotations

from datetime import date, datetime
from html import escape
from typing import Mapping
from urllib.parse import quote

import pandas as pd

from golden_vector.common.numeric import optional_finite_float
from golden_vector.common.strings import clean_string, normalize_ticker
from golden_vector.contracts.config_models import AppConfig, UniverseTicker
from golden_vector.common.frames import latest_records_by_key
from golden_vector.hedge.option_trading import OptionTradingDetailData
from golden_vector.serve.detail_forms import (
    _render_company_form,
    _render_note_section,
    _render_reporting_form,
    _render_inputs_workspace,
    _render_verification_section,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.serve.detail_panels import (
    _detail_alignment,
    _render_financials_source_switcher,
)
from golden_vector.serve.option_trading_data import OptionPageArtifacts
from golden_vector.serve.format_helpers import _frame_index_by_ticker, _ticker_rows
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import command_bar, section_tabs, terminal_density
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ticker_page import (
    COMPARE_SECTION_ID,
    LabRequest,
    TickerPageData,
    render_compare_section,
    render_corporate_finance_section,
    render_currency_attribution_block,
    render_gold_dial_control,
    render_market_behaviour_section,
    render_options_section,
    render_performance_section,
)
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.serve.workspace_state import (
    ToolADetailState,
    WorkspaceState,
    select_tool_d_source_rows,
)


DETAIL_DEFAULT_LENS_ID = "tool-a"
DETAIL_OPTION_TRADING_LENS_ID = "option-trading"
DETAIL_LENS_IDS = frozenset({DETAIL_DEFAULT_LENS_ID, DETAIL_OPTION_TRADING_LENS_ID})


def resolve_detail_lens(raw_lens: str | None) -> str:
    normalized = str(raw_lens or "").strip().lower()
    if normalized in DETAIL_LENS_IDS:
        return normalized
    return DETAIL_DEFAULT_LENS_ID


def _detail_section_nav(
    *,
    has_page_sections: bool,
    has_behaviour: bool,
    has_options: bool,
    has_compare: bool,
    has_manual: bool,
) -> str:
    """The redesigned in-page nav (requirements §2 order, M3b/M3e).

    Six entries, in page order, and each is listed ONLY when the section it
    points at is actually rendered — a nav link to a section that does not
    exist is a broken promise, not a placeholder. "Compare" follows the same
    rule as the others: it is listed whenever the section renders, including
    when the section is showing a degraded-artifact notice.
    """
    anchors: list[tuple[str, str]] = []
    if has_page_sections:
        anchors.append(("performance", "Performance"))
        anchors.append(("corporate-finance", "Corporate finance"))
    if has_behaviour:
        anchors.append(("market-behaviour", "Market behaviour"))
    if has_options:
        anchors.append(("options", "Options"))
    if has_compare:
        anchors.append((COMPARE_SECTION_ID, "Compare"))
    if has_manual:
        anchors.append(("inputs", "Inputs & notes"))
    return section_tabs(anchors, label="Ticker sections")


def _configured_company(app_config: AppConfig | None, ticker: str) -> UniverseTicker | None:
    if app_config is None:
        return None
    normalized = normalize_ticker(ticker)
    return next(
        (
            configured
            for configured in app_config.universe.tickers
            if configured.active and configured.ticker == normalized
        ),
        None,
    )


def _ticker_identity_html(ticker: str, configured: UniverseTicker | None) -> str:
    symbol = normalize_ticker(ticker) or str(ticker).strip()
    meta: list[str] = []
    company = clean_string(configured.company) if configured is not None else None
    if company:
        meta.append(company)
    if configured is not None and clean_string(configured.currency):
        meta.append(f"{configured.currency} listing")
    if configured is not None and configured.jurisdiction_tier is not None:
        meta.append(f"Jurisdiction tier {configured.jurisdiction_tier}")
    metadata = (
        '<p class="ticker-identity__meta">' + " · ".join(escape(item) for item in meta) + "</p>"
        if meta
        else ""
    )
    return (
        '<div class="ticker-identity">'
        f'<h1 class="ticker-identity__symbol">{escape(symbol)}</h1>'
        f"{metadata}</div>"
    )


def _ticker_quote_html(tool_b_row: Mapping[str, object]) -> str:
    price = optional_finite_float(tool_b_row.get("share_price_usd"))
    if price is None:
        return ""
    # The persisted field is explicitly USD-normalized. A configured listing
    # currency (AUD/CAD/GBP) describes the security, not this number's unit.
    prefix = "US$"
    raw_date = tool_b_row.get("snapshot_as_of_date")
    if clean_string(raw_date) is None:
        raw_date = tool_b_row.get("as_of_date")
    market_date = _command_date(raw_date)
    date_html = (
        f'<span class="ticker-quote__date">Market date {escape(market_date)}</span>'
        if market_date
        else ""
    )
    return (
        '<p class="ticker-quote">'
        f'<span class="ticker-quote__value">{escape(prefix)}{price:,.2f}</span>'
        f"{date_html}</p>"
    )


def _command_date(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime, pd.Timestamp)):
        parsed = pd.Timestamp(value)
    else:
        parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return pd.Timestamp(parsed).strftime("%d %b %Y")


def _ticker_jump_html(
    allowed_tickers: list[str],
    *,
    financials_source: str,
) -> str:
    options = "".join(
        f'<option value="{escape(value, quote=True)}">'
        for value in sorted({normalize_ticker(item) for item in allowed_tickers} - {None})
    )
    hidden_source = (
        '<input type="hidden" name="fundamentals_source" value="yahoo">'
        if str(financials_source).strip().lower() == "yahoo"
        else ""
    )
    return (
        '<form class="ticker-jump-form" method="get" action="/ticker">'
        '<label for="ticker-jump-input">Jump to ticker</label>'
        '<input class="ticker-jump-form__input" id="ticker-jump-input" '
        'name="ticker" list="ticker-jump-options" autocomplete="off" required>'
        f'<datalist id="ticker-jump-options">{options}</datalist>{hidden_source}'
        '<button type="submit" class="control">Go</button>'
        "</form>"
    )


def _error_summary(error: str | None) -> str:
    if not error:
        return ""
    return (
        '<div id="inputs-error-summary" tabindex="-1" data-focus-on-load '
        'class="notice notice-danger" role="alert">'
        f"<p><strong>Your changes were not saved.</strong> {escape(error)}</p></div>"
    )


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
    financials_source: str = "our",
    query_params: Mapping[str, str] | None = None,
    fundamentals_provenance: dict[tuple[str, str], str] | None = None,
    form_overrides: Mapping[str, Mapping[str, str]] | None = None,
    ticker_page_data: TickerPageData | None = None,
    chart_horizon: str = "1Y",
    chart_view: str = "rebased",
    paths: ProjectPaths | None = None,
    lab_request: LabRequest | None = None,
    option_page_artifacts: OptionPageArtifacts | None = None,
    option_candidate_slots_frame: object | None = None,
    target_window: int | None = None,
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    # Tool D is dual-source in one persisted frame. Resolve the exact
    # (ticker, selected source) key before any ticker-only lookup; otherwise
    # row order would choose the source. Never borrow the alternate source.
    tool_d_selection = select_tool_d_source_rows(
        state.latest_tool_d,
        finance_source=financials_source,
        ticker=ticker,
        label=f"ticker {str(ticker).upper()}",
    )
    tool_d_row = latest_records_by_key(tool_d_selection.frame, "ticker").get(
        str(ticker).upper(),
        {},
    )
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
    configured_company = _configured_company(app_config, ticker)
    identity_html = _ticker_identity_html(ticker, configured_company)
    identity_html += _ticker_quote_html(tool_b_row)
    jump_html = _ticker_jump_html(
        state.tool_b_tickers,
        financials_source=financials_source,
    )
    body = [
        f"<p class=\"back-link\"><a href=\"{escape(back_href, quote=True)}\">Back to workspace</a></p>",
    ]
    # --- global control bar (requirements §3 / D-6) ------------------------
    # The gold dial, the financials-source switcher (moved here out of the old
    # corporate snapshot panel) and the structural-window tabs are one control
    # region at the top of the page.
    # The beta-window switcher is NOT here any more: the beta window is a
    # market-behaviour concept, independent of the performance chart's horizon
    # (requirements §3), so it renders in that section's header instead.
    command_groups: list[tuple[str, str]] = []
    if show_workspace_panels:
        command_groups.append(
            (
                "Financials source",
                _render_financials_source_switcher(
                ticker=ticker,
                financials_source=financials_source,
                query_params=current_query,
                fundamentals_provenance=fundamentals_provenance or {},
                ),
            )
        )
        if ticker_page_data is not None:
            command_groups.append(
                (
                    "Gold price scenario",
                    render_gold_dial_control(
                        ticker_page_data,
                        ticker=ticker,
                        finance_source=financials_source,
                        app_config=app_config,
                        compact_label=True,
                    ),
                )
            )
    elif option_lens_active:
        command_groups.append(
            (
                "Page context",
                "<p class=\"hint\">Option vehicle page. This ticker is used for listed "
                "option liquidity and scenarios, not as a Gold Sensitivity / Corporate Finance mining-company row.</p>",
            )
        )
    body.append(
        command_bar(
            identity_html,
            navigation_html=jump_html,
            groups=command_groups,
            label="Company controls",
            class_name="ticker-command-bar",
        )
    )

    # --- 4. Options (rendered here, appended in page order below) ----------
    # The section resolves its own availability first, and returns "" for
    # exactly one reason: a current artifact saying the company has no listed
    # options. That empty string is what removes the nav anchor too — a missing
    # or old artifact still renders, with its reason (plan §8).
    options_html = render_options_section(
        ticker=ticker,
        detail=option_trading_detail,
        page_artifacts=option_page_artifacts,
        candidate_slots_frame=option_candidate_slots_frame,
        app_config=app_config,
        target_window=target_window,
        sizing_request=(
            option_trading_detail.sizing.request
            if option_trading_detail is not None and option_trading_detail.sizing is not None
            else None
        ),
        financials_source=financials_source,
        query_params=current_query,
    )
    has_page_sections = show_workspace_panels and ticker_page_data is not None

    # --- 5. Compare on your own terms (rendered here, appended in page order)
    # The section needs the percentiles artifact, so it exists exactly when the
    # rest of the redesigned page does. It renders even when that artifact is
    # degraded (as an honest notice), so the nav entry follows the same rule.
    compare_html = ""
    if has_page_sections:
        assert ticker_page_data is not None
        compare_html = render_compare_section(
            ticker_page_data,
            ticker=ticker,
            finance_source=financials_source,
            app_config=app_config,
        )
    body.append(
        _detail_section_nav(
            has_page_sections=has_page_sections,
            has_behaviour=show_workspace_panels,
            has_options=bool(options_html),
            has_compare=bool(compare_html),
            has_manual=show_manual_sections,
        )
    )
    if flash:
        body.append(notice("success", escape(flash)))
    if error and not show_manual_sections:
        body.append(notice("danger", escape(error)))
    alignment = _detail_alignment(tool_a_row, state.foundation_manifest)

    # --- 1. Performance ----------------------------------------------------
    if has_page_sections:
        assert ticker_page_data is not None
        currency_attribution_html = render_currency_attribution_block(
            ticker_page_data.fx_attribution_rows(ticker),
            ticker=ticker,
            horizon=chart_horizon,
            artifact_state=ticker_page_data.fx_attribution,
        )
        body.append(
            render_performance_section(
                ticker_page_data.performance_rows(ticker),
                ticker=ticker,
                horizon=chart_horizon,
                view=chart_view,
                app_config=app_config,
                artifact_state=ticker_page_data.performance,
                query_params=current_query,
                currency_attribution_html=currency_attribution_html,
            )
        )
        # --- 2. Corporate finance ------------------------------------------
        body.append(
            render_corporate_finance_section(
                ticker_page_data,
                ticker=ticker,
                finance_source=financials_source,
                tool_b_row=tool_b_row,
                tool_d_row=tool_d_row,
                tool_d_reason=tool_d_selection.reason,
                app_config=app_config,
            )
        )

    # --- 3. Market behaviour ----------------------------------------------
    if show_workspace_panels:
        body.append(
            render_market_behaviour_section(
                ticker=ticker,
                tool_a_row=tool_a_row,
                tool_a_detail=tool_a_detail,
                alignment=alignment,
                active_window=active_window,
                canonical_anchor=canonical_anchor,
                data=ticker_page_data,
                finance_source=financials_source,
                app_config=app_config,
                paths=paths,
                lab_request=lab_request,
                query_params=current_query,
                option_lens_active=option_lens_active,
                sizing_request=(
                    option_trading_detail.sizing.request
                    if option_lens_active
                    and option_trading_detail is not None
                    and option_trading_detail.sizing is not None
                    else None
                ),
            )
        )

    # --- 4. Options --------------------------------------------------------
    if options_html:
        body.append(options_html)

    # --- 5. Compare on your own terms --------------------------------------
    if compare_html:
        body.append(compare_html)

    # --- 6. Inputs and notes ----------------------------------------------
    if show_manual_sections:
        active_form = next(
            (
                section
                for section in ("company", "reporting", "verification", "note")
                if section in overrides_by_section
            ),
            "",
        )
        children = [
            _render_company_form(
                ticker=ticker,
                company_row=company_row,
                verification_rows=verification_rows,
                return_to=return_to,
                raw_overrides=company_overrides or None,
                expanded=active_form == "company",
            ),
            _render_reporting_form(
                ticker=ticker,
                reporting_row=reporting_row,
                return_to=return_to,
                raw_overrides=reporting_overrides or None,
                expanded=active_form == "reporting",
            ),
            _render_verification_section(
                ticker=ticker,
                verification_rows=verification_rows,
                return_to=return_to,
                expanded=active_form == "verification",
                expanded_field=verification_field if active_form == "verification" else "",
            ),
            _render_note_section(
                ticker=ticker,
                note_rows=note_rows,
                return_to=return_to,
                raw_overrides=note_overrides or None,
                expanded=active_form == "note",
            ),
        ]
        if error:
            children.insert(0, _error_summary(error))
        body.append(
            _render_inputs_workspace(
                "".join(children),
                expanded=bool(error),
            )
        )
    active_nav = "option_trading" if option_lens_active else ""
    symbol = normalize_ticker(ticker) or str(ticker).strip()
    company_name = clean_string(configured_company.company) if configured_company else None
    header_label = f"{symbol} · {company_name}" if company_name else symbol
    return _page_shell(
        f"Golden Vector Workspace - {ticker}",
        terminal_density("".join(body)),
        active_nav=active_nav,
        page_id="ticker_detail",
        header_label=header_label,
    )
