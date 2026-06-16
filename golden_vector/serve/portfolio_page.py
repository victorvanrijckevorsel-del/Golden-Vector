"""Portfolio page rendering and form helpers."""

from __future__ import annotations

import json
from html import escape
from typing import Any

import pandas as pd

from golden_vector.app.model_state import load_current_model_state_manifest
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.portfolio.models import ALLOWED_PORTFOLIO_CURRENCIES
from golden_vector.portfolio.pipeline import build_ticker_info
from golden_vector.portfolio.reader import PortfolioData, load_portfolio_data
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    collapsible_text_td,
)
from golden_vector.serve.column_help import help_term, help_th
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.page_shell import _page_shell


def render_portfolio_page(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    flash: str | None = None,
    error: str | None = None,
) -> str:
    if not app_config.portfolio.enabled:
        return _page_shell(
            "Portfolio",
            (
                "<h1>Portfolio</h1>"
                "<section class=\"panel\">"
                "<p>Portfolio tracking is disabled in local config.</p>"
                "<p class=\"hint\">Enable portfolio.enabled locally before entering holdings.</p>"
                "</section>"
            ),
            active_nav="portfolio",
        )
    data = load_portfolio_data(paths)
    body: list[str] = ["<h1>Portfolio</h1>"]
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if error:
        body.append(f"<div class=\"flash flash-error\">{escape(error)}</div>")
    body.append(render_model_state_banner(load_current_model_state_manifest(paths)))
    body.append(_render_summary(data))
    body.append(_render_data_issues(data))
    body.append(_render_composition(data))
    body.append(_render_hedge_sizing(data))
    body.append(_render_correlations(data))
    body.append(_render_value_history(data))
    body.append(_render_reconciliation_export(data))
    body.append(_render_positions(data))
    body.append(_render_lot_forms(data, app_config=app_config))
    return _page_shell("Portfolio", "".join(body), active_nav="portfolio")


def portfolio_form_payload(form_data: dict[str, list[str]]) -> dict[str, object]:
    return {
        "ticker": _first(form_data, "ticker"),
        "shares": _first(form_data, "shares"),
        "buy_price": _first(form_data, "buy_price"),
        "buy_currency": _first(form_data, "buy_currency"),
        "buy_date": _first(form_data, "buy_date"),
        "note": _first(form_data, "note"),
    }


def _render_summary(data: PortfolioData) -> str:
    if data.artifacts_missing:
        return (
            "<section class=\"panel\">"
            "<h2>Current Book</h2>"
            "<p class=\"hint\">No portfolio artifacts exist yet. "
            "Add a position to build them from the current local snapshot.</p>"
            "</section>"
        )
    summary = _first_row(data.summary)
    return (
        "<section class=\"metric-grid\">"
        f"{_metric_card('NAV', _fmt_money(summary.get('nav_value_usd'), 'USD'))}"
        f"{_metric_card('Total P&L at current FX', _fmt_money(summary.get('total_pnl_usd_at_current_fx'), 'USD'), help_text='Unrealized profit/loss on entered positions, valued at current prices and FX.')}"
        f"{_metric_card('Estimated linear loss if gold -10%', _fmt_money(summary.get('modeled_gold_down_10_loss_usd'), 'USD'), help_text='Modeled book loss if gold fell 10 percent, using each holding measured down-beta. Covers only positions with a measured beta.')}"
        f"{_metric_card('Beta coverage', _fmt_percent(summary.get('tool_a_coverage_fraction')), help_text='Share of book value that has a measured gold beta. The loss estimate only covers this part.')}"
        f"{_metric_card('Resilience coverage', _fmt_percent(summary.get('resilience_coverage_fraction')), help_text='Share of book value with a Tool D resilience reading.')}"
        f"{_metric_card('Largest NAV weight', _fmt_percent(summary.get('largest_position_weight_fraction')), help_text='The single biggest position as a share of net asset value — a concentration check.')}"
        f"{_metric_card('Top 3 NAV weight', _fmt_percent(summary.get('top3_position_weight_fraction')), help_text='The three biggest positions combined, as a share of net asset value.')}"
        f"{_metric_card('Price date', _fmt_text(summary.get('as_of_date')))}"
        "<p class=\"hint\">NAV = entered stock positions; broker cash is added at import.</p>"
        "<p class=\"hint\">Gold -10% loss is a simple linear beta estimate; real selloffs can be worse.</p>"
        "<p class=\"hint\">Total USD P&L blends stock movement and FX movement; local P&L is shown by position.</p>"
        "</section>"
    )


def _render_data_issues(data: PortfolioData) -> str:
    if data.summary.empty:
        return ""
    issues = _json_list(_first_row(data.summary).get("data_issues_json"))
    if not issues:
        return (
            "<section class=\"panel\">"
            "<h2>Data issues to fix</h2>"
            "<p>No portfolio data issues detected in the current artifacts.</p>"
            "</section>"
        )
    rows = []
    for issue in issues:
        rows.append(
            "<tr>"
            f"<td>{_fmt_text(issue.get('ticker'))}</td>"
            f"<td>{_fmt_text(issue.get('issue'))}</td>"
            f"<td>{_fmt_text(issue.get('message'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel\">"
        "<h2>Data issues to fix</h2>"
        f"<p class=\"hint\">Showing all {len(issues)} current data issues.</p>"
        "<table><thead><tr>"
        + help_th("Ticker", key="ticker_symbol")
        + help_th("Issue", key="portfolio_data_issue_code")
        + help_th("Why it matters", key="portfolio_data_issue_message")
        + "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_composition(data: PortfolioData) -> str:
    if data.summary.empty:
        return ""
    summary = _first_row(data.summary)
    exposure = _json_list(summary.get("effective_exposure_json"))
    currency_split = _json_object(summary.get("currency_split_json"))
    exposure_rows = [
        "<tr>"
        f"<td>{_fmt_text(row.get('bucket'))}</td>"
        f"<td>{_fmt_number(row.get('position_count'), decimals=0)}</td>"
        f"<td>{_fmt_money(row.get('value_usd'), 'USD')}</td>"
        f"<td>{_fmt_percent(row.get('nav_weight_fraction'))}</td>"
        "</tr>"
        for row in exposure
    ]
    currency_rows = [
        "<tr>"
        f"<td>{escape(str(currency))}</td>"
        f"<td>{_fmt_money(values.get('value_usd'), 'USD')}</td>"
        f"<td>{_fmt_money(values.get('pnl_usd_at_current_fx'), 'USD')}</td>"
        "</tr>"
        for currency, values in sorted(currency_split.items())
        if isinstance(values, dict)
    ]
    return (
        "<section class=\"panel\">"
        "<h2>Composition and coverage</h2>"
        "<p class=\"hint\">Corporate resilience coverage shows how much of NAV has a usable Tool D row. "
        f"Current coverage: {_fmt_percent(summary.get('resilience_coverage_fraction'))}.</p>"
        "<div class=\"two-column\">"
        "<div><h3>Gold-beta exposure</h3>"
        "<table><thead><tr>"
        + help_th("Bucket", key="portfolio_exposure_bucket")
        + help_th("Positions", key="portfolio_exposure_position_count")
        + help_th("Value", key="portfolio_exposure_value_usd")
        + help_th("NAV weight", key="portfolio_exposure_nav_weight")
        + "</tr></thead>"
        f"<tbody>{''.join(exposure_rows)}</tbody></table></div>"
        "<div><h3>Currency split</h3>"
        "<p class=\"hint\">USD P&L at current FX blends security moves and currency moves.</p>"
        "<table><thead><tr>"
        + help_th("Currency", key="portfolio_currency_code")
        + help_th("Value", key="portfolio_currency_value_usd")
        + help_th("P&L at current FX", key="portfolio_currency_pnl_usd")
        + "</tr></thead>"
        f"<tbody>{''.join(currency_rows)}</tbody></table></div>"
        "</div>"
        "</section>"
    )


def _render_hedge_sizing(data: PortfolioData) -> str:
    if data.hedge_sizing.empty:
        return (
            "<section class=\"panel\">"
            "<h2>Modeled GDX/GDXJ hedge size</h2>"
            "<p>GDX hedge size unavailable.</p>"
            "<p class=\"hint\">Benchmark beta artifacts are missing. Run python main.py refresh.</p>"
            "</section>"
        )
    rows = []
    note = None
    for row in data.hedge_sizing.sort_values("benchmark_ticker").to_dict(orient="records"):
        note = note or row.get("basis_risk_note")
        status = str(row.get("hedge_status") or "")
        if status == "NO_MEASURED_EXPOSURE":
            size_text = "No measured gold exposure to hedge"
            contracts = "-"
            reason = row.get("hedge_status_reason") or "No measured gold exposure to hedge."
        elif status != "OK":
            size_text = "GDX hedge size unavailable"
            contracts = "-"
            reason = row.get("hedge_status_reason")
        else:
            size_text = _fmt_money(row.get("modeled_short_notional_usd"), "USD")
            contracts = _fmt_number(row.get("modeled_put_contracts"), decimals=0)
            reason = "Modeled hedge size only."
        rows.append(
            "<tr>"
            f"<td>{_fmt_text(row.get('benchmark_ticker'))}</td>"
            f"<td>{_fmt_text(row.get('benchmark_label'))}</td>"
            f"<td>{_fmt_text(status)}</td>"
            f"<td>{_fmt_number(row.get('benchmark_down_beta'), decimals=2)}</td>"
            f"<td>{_fmt_money(row.get('benchmark_price_usd'), 'USD')}</td>"
            f"<td>{_fmt_money(row.get('effective_gold_exposure_usd'), 'USD')}</td>"
            f"<td>{size_text}</td>"
            f"<td>{contracts}</td>"
            f"{collapsible_text_td(reason)}"
            "</tr>"
        )
    return (
        "<section class=\"panel\">"
        "<h2>Modeled GDX/GDXJ hedge size</h2>"
        "<table><thead><tr>"
        + help_th("Proxy", key="portfolio_hedge_proxy")
        + help_th("Label", key="portfolio_hedge_proxy_label")
        + help_th("Status", key="portfolio_hedge_status")
        + help_th("Down beta", key="tool_c_down_beta")
        + help_th("Proxy price", key="portfolio_hedge_proxy_price")
        + help_th("Effective exposure", key="portfolio_hedge_effective_exposure")
        + help_th("Short notional", key="portfolio_hedge_short_notional")
        + help_th("Modeled puts", key="portfolio_hedge_modeled_puts")
        + help_th("Note", key="portfolio_hedge_basis_note")
        + "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<p class=\"hint\">{_fmt_text(note)}</p>"
        "</section>"
    )


def _render_correlations(data: PortfolioData) -> str:
    if data.correlations.empty:
        return (
            "<section class=\"panel\">"
            "<h2>Correlation map</h2>"
            "<p class=\"hint\">No covered position history is available yet.</p>"
            "</section>"
        )
    matrix = data.correlations
    tickers = sorted(
        {
            str(value)
            for value in pd.concat([matrix["row_ticker"], matrix["column_ticker"]]).dropna().unique()
        }
    )
    lookup = {
        (str(row.get("row_ticker")), str(row.get("column_ticker"))): row
        for row in matrix.to_dict(orient="records")
    }
    heat_rows = []
    for left in tickers:
        cells = [f"<th>{escape(left)}</th>"]
        for right in tickers:
            row = lookup.get((left, right), {})
            bucket = escape(str(row.get("correlation_heat_bucket") or "unavailable"))
            value = _fmt_number(row.get("correlation"), decimals=2)
            cells.append(f"<td class=\"corr-{bucket}\">{value}</td>")
        heat_rows.append(f"<tr>{''.join(cells)}</tr>")
    pair_rows = []
    ranked = matrix[matrix["pair_rank"].notna()].sort_values("pair_rank")
    for row in ranked.to_dict(orient="records"):
        pair_rows.append(
            "<tr>"
            f"<td>{_fmt_text(row.get('row_ticker'))} / {_fmt_text(row.get('column_ticker'))}</td>"
            f"<td>{_fmt_percent(row.get('pair_exposure_fraction'))}</td>"
            f"<td>{_fmt_number(row.get('correlation'), decimals=2)}</td>"
            f"<td>{_fmt_number(row.get('overlap_days'), decimals=0)}</td>"
            f"<td>{_fmt_text(row.get('correlation_status'))}</td>"
            "</tr>"
        )
    if not pair_rows:
        pair_rows.append("<tr><td colspan=\"5\">No paired covered exposures yet.</td></tr>")
    return (
        "<section class=\"panel\">"
        "<h2>Correlation map</h2>"
        "<p class=\"hint\">In a gold selloff, correlations often move toward 1.0. "
        "This is a normal-market history view, not a crash guarantee.</p>"
        "<div class=\"two-column\">"
        "<div><h3>Covered names heatmap</h3>"
        "<table class=\"correlation-heatmap\"><thead><tr><th></th>"
        f"{''.join(f'<th>{escape(ticker)}</th>' for ticker in tickers)}</tr></thead>"
        f"<tbody>{''.join(heat_rows)}</tbody></table></div>"
        "<div><h3>Largest paired exposures</h3>"
        f"<details><summary>Show all {len(ranked.index)} paired exposures</summary>"
        "<table><thead><tr>"
        + help_th("Pair", key="portfolio_corr_pair")
        + help_th("Book weight", key="portfolio_corr_pair_weight")
        + help_th("Correlation", key="portfolio_corr_correlation")
        + help_th("Overlap days", key="portfolio_corr_overlap_days")
        + help_th("Status", key="portfolio_corr_status")
        + "</tr></thead>"
        f"<tbody>{''.join(pair_rows)}</tbody></table>"
        "</details></div>"
        "</div>"
        "</section>"
    )


def _render_value_history(data: PortfolioData) -> str:
    if data.value_history.empty:
        return (
            "<section class=\"panel\">"
            "<h2>Market value over time</h2>"
            "<p class=\"hint\">No covered position history is available yet.</p>"
            "</section>"
        )
    history = data.value_history.sort_values("date")
    latest = history.iloc[-1].to_dict()
    points = " ".join(
        f"{_input_number(row.get('chart_x'))},{_input_number(row.get('chart_y'))}"
        for row in history.to_dict(orient="records")
        if _input_number(row.get("chart_x")) and _input_number(row.get("chart_y"))
    )
    recent_rows = []
    for row in history.tail(8).to_dict(orient="records"):
        recent_rows.append(
            "<tr>"
            f"<td>{_fmt_text(row.get('date'))}</td>"
            f"<td>{_fmt_money(row.get('covered_market_value_usd'), 'USD')}</td>"
            f"<td>{_fmt_percent(row.get('covered_book_weight_fraction'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel\">"
        "<h2>Market value over time</h2>"
        "<p class=\"hint\">Market value of today's holdings, covered names "
        f"({_fmt_percent(latest.get('covered_book_weight_fraction'))} of book) - not profit/loss. "
        "The window starts where all included holdings have price history.</p>"
        "<svg class=\"portfolio-line-chart\" viewBox=\"0 0 100 40\" role=\"img\" "
        "aria-label=\"Covered portfolio market value over time\">"
        f"<polyline points=\"{escape(points)}\"></polyline>"
        "</svg>"
        "<table><thead><tr>"
        + help_th("Date", key="portfolio_value_history_date")
        + help_th("Covered value", key="portfolio_covered_market_value")
        + help_th("Book weight", key="portfolio_covered_book_weight")
        + "</tr></thead>"
        f"<tbody>{''.join(recent_rows)}</tbody></table>"
        "</section>"
    )


def _render_reconciliation_export(data: PortfolioData) -> str:
    if data.reconciliation_export.empty:
        return ""
    return (
        "<section class=\"panel\">"
        "<h2>Reconciliation export</h2>"
        "<p class=\"hint\">Raw manual lots mapped to the canonical positions used by this page.</p>"
        "<p><a href=\"/portfolio/reconciliation.csv\">Download reconciliation CSV</a></p>"
        "</section>"
    )


def _render_positions(data: PortfolioData) -> str:
    if data.positions.empty:
        return (
            "<section class=\"panel\">"
            "<h2>Positions</h2>"
            "<p>Add your first position below. P&L uses the latest local snapshot price after artifacts are built.</p>"
            "</section>"
        )
    lines_by_ticker = {
        ticker: group.sort_values(["buy_date", "lot_id"]).to_dict(orient="records")
        for ticker, group in data.lines.groupby("ticker", dropna=False)
    }
    rows = []
    for row in data.positions.sort_values("ticker").to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        lot_rows = lines_by_ticker.get(ticker, [])
        rows.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"<td>{_fmt_text(row.get('company'))}</td>"
            f"<td>{_fmt_number(row.get('total_shares'), decimals=3)}</td>"
            # Cost and P&L render in GBP (the reporting currency) for every row, so a
            # GBP-cost / AUD-quoted .AX holding shows its cost and P&L instead of a dash;
            # value and current price stay in the stock's trading currency. The backend
            # resolves the GBP figures (avg_cost_gbp / pnl_gbp / pnl_fraction_gbp) — serve
            # only formats them.
            f"<td>{_fmt_money(row.get('avg_cost_gbp'), 'GBP')}</td>"
            f"<td>{_fmt_money(row.get('current_price_local'), row.get('currency'))}</td>"
            f"<td>{_fmt_money(row.get('value_local'), row.get('currency'))}</td>"
            f"<td>{_fmt_money(row.get('pnl_gbp_at_current_fx'), 'GBP')}</td>"
            f"<td>{_fmt_percent(row.get('pnl_fraction_gbp'))}</td>"
            f"<td>{_fmt_percent(row.get('equity_weight_fraction'))}</td>"
            f"<td>{_fmt_percent(row.get('nav_weight_fraction'))}</td>"
            f"<td>{_fmt_number(row.get('down_beta_core'), decimals=2)}</td>"
            f"<td>{_fmt_money(row.get('gold_down_10_loss_usd'), 'USD')}</td>"
            f"<td>{_fmt_percent(row.get('beta_contribution_fraction'))}</td>"
            f"<td>{_fmt_text(row.get('resilience_bucket'))}</td>"
            f"<td>{_fmt_text(row.get('position_status'))}</td>"
            f"<td><details><summary>{len(lot_rows)} lots</summary>{_render_lot_table(lot_rows)}</details></td>"
            "</tr>"
        )
    return (
        "<section class=\"panel\">"
        "<h2>Positions</h2>"
        "<table class=\"js-datatable\"><thead><tr>"
        + help_th("Ticker", key="ticker_symbol")
        + help_th("Company")
        + help_th("Shares")
        + help_th("Avg Cost", key="portfolio_avg_cost")
        + help_th("Current Price", key="portfolio_current_price_local")
        + help_th("Value", key="portfolio_value_local")
        + help_th("P&L", key="portfolio_pnl_local")
        + help_th("P&L %", key="portfolio_pnl_pct")
        + help_th("Equity Weight", key="portfolio_equity_weight")
        + help_th("NAV Weight", key="portfolio_nav_weight")
        + help_th("Down Beta", key="tool_c_down_beta")
        + help_th("Linear Loss @ Gold -10%", key="portfolio_gold_down_loss")
        + help_th("Loss Share", key="portfolio_loss_share")
        + help_th("Resilience", key="portfolio_resilience")
        + help_th("Status", key="portfolio_position_status")
        + help_th("Lots")
        + "</tr></thead><tbody>"
        f"{''.join(rows)}"
        "</tbody></table>"
        "<p class=\"hint\">Cost and P&L are shown in GBP (the reporting currency); value and "
        "current price are in each stock's trading currency (e.g. AUD for .AX). The gold-loss "
        "column is a positive USD loss estimate.</p>"
        "</section>"
    )


def _render_lot_forms(data: PortfolioData, *, app_config: AppConfig) -> str:
    ticker_info = build_ticker_info(app_config)
    active_tickers = [
        ticker
        for ticker, info in sorted(ticker_info.items())
        if info.active
    ]
    default_ticker = active_tickers[0] if active_tickers else None
    default_currency = (
        ticker_info[default_ticker].currency
        if default_ticker is not None
        else None
    )
    add_form = (
        "<section class=\"panel\">"
        "<h2>Add Position Lot</h2>"
        "<p class=\"hint\">M1 records each buy in the selected ticker's configured currency. "
        "Dual-listing broker lines come later. For LSE/GBP tickers, enter buy prices in pounds; "
        "Yahoo GBp quotes are converted by the data pipeline.</p>"
        "<form method=\"post\" action=\"/portfolio/lots\" class=\"portfolio-lot-form\">"
        f"{_ticker_select(active_tickers, ticker_info=ticker_info, selected=default_ticker)}"
        f"{_number_input('shares', 'Shares')}"
        f"{_number_input('buy_price', 'Buy price')}"
        f"{_currency_select(default_currency)}"
        "<label><span>Buy date</span><input name=\"buy_date\" type=\"date\" required></label>"
        "<label><span>Note</span><input name=\"note\" type=\"text\" maxlength=\"200\"></label>"
        "<button type=\"submit\">Add lot</button>"
        "</form>"
        "</section>"
    )
    if data.lines.empty:
        return add_form + _portfolio_currency_script()
    edit_forms = ["<section class=\"panel\"><h2>Edit Lots</h2>"]
    for row in data.lines.sort_values(["ticker", "buy_date", "lot_id"]).to_dict(orient="records"):
        lot_id = str(row.get("lot_id") or "")
        edit_forms.append(
            "<details class=\"portfolio-edit-lot\">"
            f"<summary>{escape(str(row.get('ticker') or 'Lot'))} - {escape(str(row.get('buy_date') or ''))}</summary>"
            f"<form method=\"post\" action=\"/portfolio/lots/{escape(lot_id)}/edit\" class=\"portfolio-lot-form\">"
            f"{_ticker_select(active_tickers, ticker_info=ticker_info, selected=str(row.get('ticker') or ''))}"
            f"{_number_input('shares', 'Shares', row.get('shares'))}"
            f"{_number_input('buy_price', 'Buy price', row.get('buy_price'))}"
            f"{_currency_select(str(row.get('buy_currency') or ''))}"
            f"{_date_input(row.get('buy_date'))}"
            f"{_text_input('note', 'Note', row.get('note'), maxlength=200)}"
            "<button type=\"submit\">Save lot</button>"
            "</form>"
            f"<form method=\"post\" action=\"/portfolio/lots/{escape(lot_id)}/delete\">"
            "<button type=\"submit\">Delete lot</button>"
            "</form>"
            "</details>"
        )
    edit_forms.append("</section>")
    return add_form + "".join(edit_forms) + _portfolio_currency_script()


def _render_lot_table(lots: list[dict[str, object]]) -> str:
    rows = [
        "<tr>"
        f"<td>{_fmt_text(row.get('buy_date'))}</td>"
        f"<td>{_fmt_number(row.get('shares'), decimals=3)}</td>"
        f"<td>{_fmt_money(row.get('buy_price'), row.get('buy_currency'))}</td>"
        f"<td>{_fmt_money(row.get('cost_local'), row.get('cost_currency') or row.get('buy_currency'))}</td>"
        f"<td>{_fmt_text(row.get('note'))}</td>"
        "</tr>"
        for row in lots
    ]
    return (
        "<table><thead><tr>"
        + help_th("Date", key="portfolio_lot_buy_date")
        + help_th("Shares", key="portfolio_lot_shares")
        + help_th("Buy Price", key="portfolio_lot_buy_price")
        + help_th("Cost", key="portfolio_lot_cost")
        + help_th("Note", key="portfolio_lot_note")
        + "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _ticker_select(
    active_tickers: list[str],
    *,
    ticker_info: dict[str, Any],
    selected: str | None = None,
) -> str:
    selected = str(selected or "").upper()
    options = []
    for ticker in active_tickers:
        info = ticker_info[ticker]
        label = f"{ticker} ({info.currency})"
        selected_attr = " selected" if ticker == selected else ""
        value = escape(ticker)
        currency = escape(info.currency)
        text = escape(label)
        options.append(
            f"<option value=\"{value}\" data-currency=\"{currency}\"{selected_attr}>{text}</option>"
        )
    return (
        "<label><span>Ticker</span><select name=\"ticker\" required>"
        f"{''.join(options)}"
        "</select></label>"
    )


def _currency_select(selected: str | None) -> str:
    selected = str(selected or "").upper()
    options = []
    for currency in ALLOWED_PORTFOLIO_CURRENCIES:
        selected_attr = " selected" if currency == selected else ""
        options.append(
            f"<option value=\"{escape(currency)}\"{selected_attr}>{escape(currency)}</option>"
        )
    return (
        "<label><span>Currency</span><select name=\"buy_currency\" required>"
        f"{''.join(options)}"
        "</select></label>"
    )


def _metric_card(title: str, value: str, *, help_text: str | None = None) -> str:
    heading = help_term(title, text=help_text) if help_text else escape(title)
    return f"<article class=\"panel metric-card\"><h3>{heading}</h3><p>{value}</p></article>"


def _number_input(name: str, label: str, value: object | None = None) -> str:
    value_attr = ""
    if value is not None:
        value_attr = f" value=\"{escape(_input_number(value))}\""
    return (
        f"<label><span>{escape(label)}</span>"
        f"<input name=\"{escape(name)}\" type=\"number\" step=\"0.000001\" "
        f"min=\"0\" required{value_attr}></label>"
    )


def _date_input(value: object | None = None) -> str:
    value_attr = ""
    if value is not None:
        value_attr = f" value=\"{escape(str(value or ''))}\""
    return (
        "<label><span>Buy date</span>"
        f"<input name=\"buy_date\" type=\"date\" required{value_attr}></label>"
    )


def _text_input(
    name: str,
    label: str,
    value: object | None = None,
    *,
    maxlength: int,
) -> str:
    value_attr = ""
    if value is not None:
        value_attr = f" value=\"{escape(str(value or ''))}\""
    return (
        f"<label><span>{escape(label)}</span>"
        f"<input name=\"{escape(name)}\" type=\"text\" maxlength=\"{maxlength}\"{value_attr}>"
        "</label>"
    )


def _fmt_money(value: object, currency: object) -> str:
    text = _fmt_number(value, decimals=2)
    if text == "-":
        return text
    return f"{escape(str(currency or '').upper())} {text}".strip()


def _first(form_data: dict[str, list[str]], key: str) -> str:
    values = form_data.get(key, [""])
    return values[0] if values else ""


def _first_row(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {}
    return frame.iloc[0].to_dict()


def _json_list(value: object) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _json_object(value: object) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _input_number(value: object) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{numeric:g}"


def _portfolio_currency_script() -> str:
    return """
<script>
document.querySelectorAll('.portfolio-lot-form').forEach((form) => {
  const ticker = form.querySelector('select[name="ticker"]');
  const currency = form.querySelector('select[name="buy_currency"]');
  if (!ticker || !currency) return;
  const syncCurrency = () => {
    const selected = ticker.options[ticker.selectedIndex];
    const configuredCurrency = selected ? selected.getAttribute('data-currency') : '';
    if (configuredCurrency) currency.value = configuredCurrency;
  };
  ticker.addEventListener('change', syncCurrency);
  syncCurrency();
});
</script>"""
