"""Portfolio page rendering and form helpers."""

from __future__ import annotations

import json
from html import escape
from typing import Any

import pandas as pd

from golden_vector.app.model_state import load_current_model_state_manifest
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.numeric import optional_finite_float
from golden_vector.contracts.config_models import AppConfig
from golden_vector.portfolio.models import ALLOWED_PORTFOLIO_CURRENCIES
from golden_vector.portfolio.pipeline import build_ticker_info
from golden_vector.portfolio.reader import PortfolioData, load_portfolio_data
from golden_vector.serve.column_help import help_icon, help_th
from golden_vector.serve.format_helpers import (
    _MISSING_SORT_SENTINEL,
    _fmt_number,
    _fmt_numeric_td,
    _fmt_percent,
    _fmt_text,
    collapsible_text_td,
    # ONE slug rule for element ids / in-page anchors, shared with the detail page.
    # Kept importable under the old local name so existing call sites and pins hold.
    id_token as _ticker_slug,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import (
    data_card,
    empty_state,
    page_header,
    section_heading,
    section_tabs,
    terminal_density,
)
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region


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
            terminal_density(
                page_header("Portfolio")
                + empty_state(
                    "Portfolio tracking is disabled in local config.",
                    body_html=(
                        "<p class=\"hint\">Enable portfolio.enabled locally "
                        "before entering holdings.</p>"
                    ),
                )
            ),
            active_nav="portfolio",
        )
    data = load_portfolio_data(paths)
    body: list[str] = [page_header("Portfolio")]
    if flash:
        body.append(notice("success", escape(flash)))
    if error:
        body.append(notice("danger", escape(error)))
    body.append(render_model_state_banner(load_current_model_state_manifest(paths)))
    # Anchors list only the sections this request actually renders; each condition
    # mirrors the early-return guard in the matching _render_* helper below.
    nav_links: list[tuple[str, str]] = [("summary", "Summary")]
    if not data.summary.empty:
        nav_links.append(("data-issues", "Data issues"))
        nav_links.append(("composition", "Composition"))
        # Blueprint 15.7 asks for Gold-beta exposure and Currency as distinct
        # targets; both live inside the composition section (GV-RD-FINAL-012).
        nav_links.append(("gold-beta", "Gold-beta exposure"))
        nav_links.append(("currency", "Currency"))
    nav_links.append(("hedge-sizing", "Hedge sizing"))
    nav_links.append(("correlations", "Correlations"))
    nav_links.append(("history", "History"))
    if not data.reconciliation_export.empty:
        nav_links.append(("reconciliation", "Reconciliation"))
    nav_links.append(("positions", "Positions"))
    nav_links.append(("lots", "Lots"))
    body.append(section_tabs(nav_links, label="Portfolio sections"))
    body.append(_render_summary(data))
    body.append(_render_data_issues(data))
    body.append(_render_composition(data))
    body.append(_render_hedge_sizing(data))
    body.append(_render_correlations(data))
    body.append(_render_value_history(data))
    body.append(_render_reconciliation_export(data))
    body.append(_render_positions(data))
    body.append(_render_lot_forms(data, app_config=app_config))
    return _page_shell(
        "Portfolio",
        terminal_density("".join(body)),
        active_nav="portfolio",
    )


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
            "<section class=\"panel\" id=\"summary\">"
            + section_heading("Current Book")
            + empty_state(
                "No portfolio artifacts exist yet.",
                body_html=(
                    "<p class=\"hint\">Add a position to build them from the "
                    "current local snapshot.</p>"
                ),
            )
            + "</section>"
        )
    summary = _first_row(data.summary)
    return (
        "<section id=\"summary\">"
        + section_heading("Current Book")
        + "<div class=\"metric-grid\">"
        + data_card("NAV", _fmt_money(summary.get("nav_value_usd"), "USD"))
        + data_card(
            "Total P&L at current FX",
            _fmt_money(summary.get("total_pnl_usd_at_current_fx"), "USD"),
            help_html=help_icon(
                "Total P&L at current FX",
                text=(
                    "Unrealized profit/loss on entered positions, valued at "
                    "current prices and FX."
                ),
            ),
        )
        + data_card(
            "Estimated linear loss if gold -10%",
            _fmt_money(summary.get("modeled_gold_down_10_loss_usd"), "USD"),
            help_html=help_icon(
                "Estimated linear loss if gold -10%",
                text=(
                    "Modeled book loss if gold fell 10 percent, using each "
                    "holding measured down-beta. Covers only positions with a "
                    "measured beta."
                ),
            ),
        )
        + data_card(
            "Beta coverage",
            _fmt_percent(summary.get("tool_a_coverage_fraction")),
            help_html=help_icon(
                "Beta coverage",
                text=(
                    "Share of book value that has a measured gold beta. The "
                    "loss estimate only covers this part."
                ),
            ),
        )
        + data_card(
            "Resilience coverage",
            _fmt_percent(summary.get("resilience_coverage_fraction")),
            help_html=help_icon(
                "Resilience coverage",
                text="Share of book value with a Tool D resilience reading.",
            ),
        )
        + data_card(
            "Largest NAV weight",
            _fmt_percent(summary.get("largest_position_weight_fraction")),
            help_html=help_icon(
                "Largest NAV weight",
                text=(
                    "The single biggest position as a share of net asset "
                    "value - a concentration check."
                ),
            ),
        )
        + data_card(
            "Top 3 NAV weight",
            _fmt_percent(summary.get("top3_position_weight_fraction")),
            help_html=help_icon(
                "Top 3 NAV weight",
                text=(
                    "The three biggest positions combined, as a share of net "
                    "asset value."
                ),
            ),
        )
        + data_card("Price date", _fmt_text(summary.get("as_of_date")))
        + "</div>"
        + "<p class=\"hint\">NAV = entered stock positions; broker cash is added at import.</p>"
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
            "<section class=\"panel\" id=\"data-issues\">"
            + section_heading("Data issues to fix")
            + notice(
                "success",
                "No portfolio data issues detected in the current artifacts.",
            )
            + "</section>"
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
        "<section class=\"panel\" id=\"data-issues\">"
        + section_heading("Data issues to fix")
        + f"<p class=\"hint\">Showing all {len(issues)} current data issues.</p>"
        + table_region(
            "<table><thead><tr>"
            + help_th("Ticker", key="ticker_symbol")
            + help_th("Issue", key="portfolio_data_issue_code")
            + help_th("Why it matters", key="portfolio_data_issue_message")
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="portfolio-issues-table-region",
            label="Portfolio data issues",
        )
        + "</section>"
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
        f"{_fmt_numeric_td(row.get('position_count'), decimals=0)}"
        f"{_numeric_display_td(row.get('value_usd'), _fmt_money(row.get('value_usd'), 'USD'))}"
        f"{_fmt_numeric_td(row.get('nav_weight_fraction'), decimals=1, as_percent=True)}"
        "</tr>"
        for row in exposure
    ]
    currency_rows = [
        "<tr>"
        f"<td>{escape(str(currency))}</td>"
        f"{_numeric_display_td(values.get('value_usd'), _fmt_money(values.get('value_usd'), 'USD'))}"
        f"{_numeric_display_td(values.get('pnl_usd_at_current_fx'), _fmt_money(values.get('pnl_usd_at_current_fx'), 'USD'))}"
        "</tr>"
        for currency, values in sorted(currency_split.items())
        if isinstance(values, dict)
    ]
    exposure_content = (
        table_region(
            "<table><thead><tr>"
            + help_th("Bucket", key="portfolio_exposure_bucket")
            + help_th(
                "Positions",
                key="portfolio_exposure_position_count",
                sort_numeric=True,
            )
            + help_th(
                "Value",
                key="portfolio_exposure_value_usd",
                sort_numeric=True,
            )
            + help_th(
                "NAV weight",
                key="portfolio_exposure_nav_weight",
                sort_numeric=True,
            )
            + "</tr></thead>"
            f"<tbody>{''.join(exposure_rows)}</tbody></table>",
            region_id="portfolio-exposure-table-region",
            label="Gold-beta exposure",
        )
        if exposure_rows
        else empty_state("No gold-beta exposure breakdown is available.")
    )
    currency_content = (
        table_region(
            "<table><thead><tr>"
            + help_th("Currency", key="portfolio_currency_code")
            + help_th(
                "Value",
                key="portfolio_currency_value_usd",
                sort_numeric=True,
            )
            + help_th(
                "P&L at current FX",
                key="portfolio_currency_pnl_usd",
                sort_numeric=True,
            )
            + "</tr></thead>"
            f"<tbody>{''.join(currency_rows)}</tbody></table>",
            region_id="portfolio-currency-table-region",
            label="Currency split",
        )
        if currency_rows
        else empty_state("No currency breakdown is available.")
    )
    return (
        "<section class=\"panel\" id=\"composition\">"
        + section_heading("Composition and coverage")
        + "<p class=\"hint\">Corporate resilience coverage shows how much of NAV has a usable Tool D row. "
        f"Current coverage: {_fmt_percent(summary.get('resilience_coverage_fraction'))}.</p>"
        "<div class=\"two-column\">"
        "<div id=\"gold-beta\"><h3>Gold-beta exposure</h3>"
        + exposure_content
        + "</div>"
        "<div id=\"currency\"><h3>Currency split</h3>"
        "<p class=\"hint\">USD P&L at current FX blends security moves and currency moves.</p>"
        + currency_content
        + "</div>"
        "</div>"
        "</section>"
    )


def _render_hedge_sizing(data: PortfolioData) -> str:
    if data.hedge_sizing.empty:
        return (
            "<section class=\"panel\" id=\"hedge-sizing\">"
            + section_heading("Modeled GDX/GDXJ hedge size")
            + empty_state(
                "GDX hedge size unavailable.",
                body_html=(
                    "<p class=\"hint\">Benchmark beta artifacts are missing. "
                    "Run <code>python main.py refresh</code>.</p>"
                ),
            )
            + "</section>"
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
            f"{_fmt_numeric_td(row.get('benchmark_down_beta'), decimals=2)}"
            f"{_numeric_display_td(row.get('benchmark_price_usd'), _fmt_money(row.get('benchmark_price_usd'), 'USD'))}"
            f"{_numeric_display_td(row.get('effective_gold_exposure_usd'), _fmt_money(row.get('effective_gold_exposure_usd'), 'USD'))}"
            f"{_numeric_display_td(row.get('modeled_short_notional_usd'), size_text)}"
            f"{_numeric_display_td(row.get('modeled_put_contracts'), contracts)}"
            f"{collapsible_text_td(reason)}"
            "</tr>"
        )
    return (
        "<section class=\"panel\" id=\"hedge-sizing\">"
        + section_heading("Modeled GDX/GDXJ hedge size")
        + table_region(
            "<table><thead><tr>"
            + help_th("Proxy", key="portfolio_hedge_proxy")
        + help_th("Label", key="portfolio_hedge_proxy_label")
        + help_th("Status", key="portfolio_hedge_status")
        + help_th("Down beta", key="tool_c_down_beta_blend", sort_numeric=True)
        + help_th("Proxy price", key="portfolio_hedge_proxy_price", sort_numeric=True)
        + help_th(
            "Effective exposure",
            key="portfolio_hedge_effective_exposure",
            sort_numeric=True,
        )
        + help_th(
            "Short notional",
            key="portfolio_hedge_short_notional",
            sort_numeric=True,
        )
        + help_th("Modeled puts", key="portfolio_hedge_modeled_puts", sort_numeric=True)
            + help_th("Note", key="portfolio_hedge_basis_note")
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="portfolio-hedge-table-region",
            label="Modeled hedge size",
        )
        + f"<p class=\"hint\">{_fmt_text(note)}</p>"
        "</section>"
    )


def _render_correlations(data: PortfolioData) -> str:
    if data.correlations.empty:
        return (
            "<section class=\"panel\" id=\"correlations\">"
            + section_heading("Correlation map")
            + empty_state("No covered position history is available yet.")
            + "</section>"
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
        cells = [f"<th scope=\"row\">{escape(left)}</th>"]
        for right in tickers:
            row = lookup.get((left, right), {})
            bucket = escape(str(row.get("correlation_heat_bucket") or "unavailable"))
            value = _fmt_number(row.get("correlation"), decimals=2)
            cells.append(
                _numeric_display_td(
                    row.get("correlation"),
                    value,
                    class_name=f"corr-{bucket}",
                )
            )
        heat_rows.append(f"<tr>{''.join(cells)}</tr>")
    pair_rows = []
    ranked = matrix[matrix["pair_rank"].notna()].sort_values("pair_rank")
    for row in ranked.to_dict(orient="records"):
        pair_rows.append(
            "<tr>"
            f"<td>{_fmt_text(row.get('row_ticker'))} / {_fmt_text(row.get('column_ticker'))}</td>"
            f"{_fmt_numeric_td(row.get('pair_exposure_fraction'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('correlation'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('overlap_days'), decimals=0)}"
            f"<td>{_fmt_text(row.get('correlation_status'))}</td>"
            "</tr>"
        )
    heatmap_header_cells = "".join(
        f"<th scope=\"col\">{escape(ticker)}</th>" for ticker in tickers
    )
    pair_content = (
        "<details><summary>"
        f"Show all {len(ranked.index)} paired exposures</summary>"
        + table_region(
            "<table><thead><tr>"
            + help_th("Pair", key="portfolio_corr_pair")
            + help_th(
                "Book weight",
                key="portfolio_corr_pair_weight",
                sort_numeric=True,
            )
            + help_th(
                "Correlation",
                key="portfolio_corr_correlation",
                sort_numeric=True,
            )
            + help_th(
                "Overlap days",
                key="portfolio_corr_overlap_days",
                sort_numeric=True,
            )
            + help_th("Status", key="portfolio_corr_status")
            + "</tr></thead>"
            f"<tbody>{''.join(pair_rows)}</tbody></table>",
            region_id="portfolio-pairs-table-region",
            label="Largest paired exposures",
        )
        + "</details>"
        if pair_rows
        else empty_state("No paired covered exposures yet.")
    )
    return (
        "<section class=\"panel\" id=\"correlations\">"
        + section_heading("Correlation map")
        + "<p class=\"hint\">In a gold selloff, correlations often move toward 1.0. "
        "This is a normal-market history view, not a crash guarantee.</p>"
        "<div class=\"two-column\">"
        "<div><h3>Covered names heatmap</h3>"
        + table_region(
            "<table class=\"correlation-heatmap\"><thead><tr><th></th>"
            + heatmap_header_cells
            + "</tr></thead>"
            f"<tbody>{''.join(heat_rows)}</tbody></table>",
            region_id="portfolio-correlation-heatmap-region",
            label="Correlation heatmap",
        )
        + "</div>"
        "<div><h3>Largest paired exposures</h3>"
        + pair_content
        + "</div>"
        "</div>"
        "</section>"
    )


def _render_value_history(data: PortfolioData) -> str:
    if data.value_history.empty:
        return (
            "<section class=\"panel\" id=\"history\">"
            + section_heading("Market value over time")
            + empty_state("No covered position history is available yet.")
            + "</section>"
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
            f"{_numeric_display_td(row.get('covered_market_value_usd'), _fmt_money(row.get('covered_market_value_usd'), 'USD'))}"
            f"{_fmt_numeric_td(row.get('covered_book_weight_fraction'), decimals=1, as_percent=True)}"
            "</tr>"
        )
    return (
        "<section class=\"panel\" id=\"history\">"
        + section_heading("Market value over time")
        + "<p class=\"hint\">Market value of today's holdings, covered names "
        f"({_fmt_percent(latest.get('covered_book_weight_fraction'))} of book) - not profit/loss. "
        "The window starts where all included holdings have price history.</p>"
        "<svg class=\"portfolio-line-chart\" viewBox=\"0 0 100 40\" role=\"img\" "
        "aria-label=\"Covered portfolio market value over time\">"
        f"<polyline points=\"{escape(points)}\"></polyline>"
        "</svg>"
        + table_region(
            "<table><thead><tr>"
            + help_th("Date", key="portfolio_value_history_date")
            + help_th(
                "Covered value",
                key="portfolio_covered_market_value",
                sort_numeric=True,
            )
            + help_th(
                "Book weight",
                key="portfolio_covered_book_weight",
                sort_numeric=True,
            )
            + "</tr></thead>"
            f"<tbody>{''.join(recent_rows)}</tbody></table>",
            region_id="portfolio-history-table-region",
            label="Market value over time",
        )
        + "</section>"
    )


def _render_reconciliation_export(data: PortfolioData) -> str:
    if data.reconciliation_export.empty:
        return ""
    return (
        "<section class=\"panel\" id=\"reconciliation\">"
        + section_heading("Reconciliation export")
        + "<p class=\"hint\">Raw manual lots mapped to the canonical positions used by this page.</p>"
        "<p><a class=\"control\" href=\"/portfolio/reconciliation.csv\">Download reconciliation CSV</a></p>"
        "</section>"
    )


def _render_positions(data: PortfolioData) -> str:
    if data.positions.empty:
        return (
            "<section class=\"panel\" id=\"positions\">"
            + section_heading("Positions")
            + empty_state(
                "No positions yet.",
                body_html=(
                    "<p>Add your first position below. P&L uses the latest local "
                    "snapshot price after artifacts are built.</p>"
                ),
            )
            + "</section>"
        )
    lines_by_ticker = {
        ticker: group.sort_values(["buy_date", "lot_id"]).to_dict(orient="records")
        for ticker, group in data.lines.groupby("ticker", dropna=False)
    }
    rows = []
    lot_blocks: list[str] = []
    for row in data.positions.sort_values("ticker").to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        lot_rows = lines_by_ticker.get(ticker, [])
        rows.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"<td>{_fmt_text(row.get('company'))}</td>"
            f"{_fmt_numeric_td(row.get('total_shares'), decimals=3)}"
            # Cost and P&L render in GBP (the reporting currency) for every row, so a
            # GBP-cost / AUD-quoted .AX holding shows its cost and P&L instead of a dash;
            # value and current price stay in the stock's trading currency. The backend
            # resolves the GBP figures (avg_cost_gbp / pnl_gbp / pnl_fraction_gbp) — serve
            # only formats them.
            f"{_numeric_display_td(row.get('avg_cost_gbp'), _fmt_money(row.get('avg_cost_gbp'), 'GBP'))}"
            f"{_numeric_display_td(row.get('current_price_local'), _fmt_money(row.get('current_price_local'), row.get('currency')))}"
            f"{_numeric_display_td(row.get('value_local'), _fmt_money(row.get('value_local'), row.get('currency')))}"
            f"{_numeric_display_td(row.get('pnl_gbp_at_current_fx'), _fmt_money(row.get('pnl_gbp_at_current_fx'), 'GBP'))}"
            f"{_fmt_numeric_td(row.get('pnl_fraction_gbp'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('equity_weight_fraction'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('nav_weight_fraction'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('down_beta_core'), decimals=2)}"
            f"{_numeric_display_td(row.get('gold_down_10_loss_usd'), _fmt_money(row.get('gold_down_10_loss_usd'), 'USD'))}"
            f"{_fmt_numeric_td(row.get('beta_contribution_fraction'), decimals=1, as_percent=True)}"
            f"<td>{_fmt_text(row.get('resilience_bucket'))}</td>"
            f"<td>{_fmt_text(row.get('position_status'))}</td>"
            f"<td>{_render_lots_link(ticker, len(lot_rows))}</td>"
            "</tr>"
        )
        if lot_rows:
            lot_blocks.append(_render_lot_breakdown_block(ticker, lot_rows))
    breakdown = (
        "<h3>Lot breakdown</h3>" + "".join(lot_blocks) if lot_blocks else ""
    )
    return (
        "<section class=\"panel\" id=\"positions\">"
        + section_heading("Positions")
        + table_region(
            "<table class=\"js-datatable\" id=\"portfolio-positions-table\"><thead><tr>"
            + help_th("Ticker", key="ticker_symbol")
        + help_th("Company")
        + help_th("Shares", sort_numeric=True)
        + help_th("Avg Cost", key="portfolio_avg_cost", sort_numeric=True)
        + help_th(
            "Current Price",
            key="portfolio_current_price_local",
            sort_numeric=True,
        )
        + help_th("Value", key="portfolio_value_local", sort_numeric=True)
        + help_th("P&L", key="portfolio_pnl_local", sort_numeric=True)
        + help_th("P&L %", key="portfolio_pnl_pct", sort_numeric=True)
        + help_th(
            "Equity Weight",
            key="portfolio_equity_weight",
            sort_numeric=True,
        )
        + help_th("NAV Weight", key="portfolio_nav_weight", sort_numeric=True)
        + help_th("Down Beta", key="tool_c_down_beta_blend", sort_numeric=True)
        + help_th(
            "Linear Loss @ Gold -10%",
            key="portfolio_gold_down_loss",
            sort_numeric=True,
        )
        + help_th("Loss Share", key="portfolio_loss_share", sort_numeric=True)
        + help_th("Resilience", key="portfolio_resilience")
        + help_th("Status", key="portfolio_position_status")
            + help_th("Lots")
            + "</tr></thead><tbody>"
            f"{''.join(rows)}"
            "</tbody></table>",
            region_id="portfolio-positions-table-region",
            label="Positions",
        )
        + "<p class=\"hint\">Cost and P&L are shown in GBP (the reporting currency); value and "
        "current price are in each stock's trading currency (e.g. AUD for .AX). The gold-loss "
        "column is a positive USD loss estimate.</p>"
        + breakdown
        + "</section>"
    )


def _render_lots_link(ticker: str, count: int) -> str:
    if count == 0:
        return "0 lots"
    slug = _ticker_slug(ticker)
    return f"<a href=\"#lots-{escape(slug)}\">{count} lots</a>"


def _render_lot_breakdown_block(ticker: str, lot_rows: list[dict[str, object]]) -> str:
    slug = _ticker_slug(ticker)
    return (
        f"<details id=\"lots-{escape(slug)}\">"
        f"<summary>{escape(ticker)} - {len(lot_rows)} lots</summary>"
        + table_region(
            _render_lot_table(lot_rows),
            region_id=f"portfolio-lots-{slug}",
            label=f"{ticker} lots",
        )
        + "</details>"
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
        + section_heading("Add Position Lot")
        + "<p class=\"hint\">M1 records each buy in the selected ticker's configured currency. "
        "Dual-listing broker lines come later. For LSE/GBP tickers, enter buy prices in pounds; "
        "Yahoo GBp quotes are converted by the data pipeline.</p>"
        "<form method=\"post\" action=\"/portfolio/lots\" class=\"portfolio-lot-form form-grid\">"
        f"{_ticker_select(active_tickers, ticker_info=ticker_info, selected=default_ticker)}"
        f"{_number_input('shares', 'Shares')}"
        f"{_number_input('buy_price', 'Buy price')}"
        f"{_currency_select(default_currency)}"
        "<label><span>Buy date</span><input class=\"form-control\" name=\"buy_date\" type=\"date\" required></label>"
        "<label><span>Note</span><input class=\"form-control\" name=\"note\" type=\"text\" maxlength=\"200\"></label>"
        "<div class=\"form-actions\"><button type=\"submit\" class=\"control control--primary\">Add lot</button></div>"
        "</form>"
        "</section>"
    )
    # Blueprint 15.7: one "Lot management" region so the #lots anchor reaches
    # BOTH Add Position Lot and Edit Lots (GV-RD-FINAL-012).
    region_open = "<div id=\"lots\">"
    if data.lines.empty:
        return region_open + add_form + "</div>" + _portfolio_currency_script()
    edit_forms = ["<section class=\"panel\">" + section_heading("Edit Lots")]
    for row in data.lines.sort_values(["ticker", "buy_date", "lot_id"]).to_dict(orient="records"):
        lot_id = str(row.get("lot_id") or "")
        edit_forms.append(
            "<details class=\"portfolio-edit-lot\">"
            f"<summary>{escape(str(row.get('ticker') or 'Lot'))} - {escape(str(row.get('buy_date') or ''))}</summary>"
            f"<form method=\"post\" action=\"/portfolio/lots/{escape(lot_id)}/edit\" class=\"portfolio-lot-form form-grid\">"
            f"{_ticker_select(active_tickers, ticker_info=ticker_info, selected=str(row.get('ticker') or ''))}"
            f"{_number_input('shares', 'Shares', row.get('shares'))}"
            f"{_number_input('buy_price', 'Buy price', row.get('buy_price'))}"
            f"{_currency_select(str(row.get('buy_currency') or ''))}"
            f"{_date_input(row.get('buy_date'))}"
            f"{_text_input('note', 'Note', row.get('note'), maxlength=200)}"
            "<div class=\"form-actions\"><button type=\"submit\" class=\"control\">Save lot</button></div>"
            "</form>"
            f"<form method=\"post\" action=\"/portfolio/lots/{escape(lot_id)}/delete\">"
            "<button type=\"submit\" class=\"control control--danger\">Delete lot</button>"
            "</form>"
            "</details>"
        )
    edit_forms.append("</section>")
    return (
        region_open + add_form + "".join(edit_forms) + "</div>" + _portfolio_currency_script()
    )


def _render_lot_table(lots: list[dict[str, object]]) -> str:
    rows = [
        "<tr>"
        f"<td>{_fmt_text(row.get('buy_date'))}</td>"
        f"{_fmt_numeric_td(row.get('shares'), decimals=3)}"
        f"{_numeric_display_td(row.get('buy_price'), _fmt_money(row.get('buy_price'), row.get('buy_currency')))}"
        f"{_numeric_display_td(row.get('cost_local'), _fmt_money(row.get('cost_local'), row.get('cost_currency') or row.get('buy_currency')))}"
        f"<td>{_fmt_text(row.get('note'))}</td>"
        "</tr>"
        for row in lots
    ]
    return (
        "<table><thead><tr>"
        + help_th("Date", key="portfolio_lot_buy_date")
        + help_th("Shares", key="portfolio_lot_shares", sort_numeric=True)
        + help_th("Buy Price", key="portfolio_lot_buy_price", sort_numeric=True)
        + help_th("Cost", key="portfolio_lot_cost", sort_numeric=True)
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
        "<label><span>Ticker</span><select class=\"form-control\" name=\"ticker\" required>"
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
        "<label><span>Currency</span><select class=\"form-control\" name=\"buy_currency\" required>"
        f"{''.join(options)}"
        "</select></label>"
    )


def _number_input(name: str, label: str, value: object | None = None) -> str:
    value_attr = ""
    if value is not None:
        value_attr = f" value=\"{escape(_input_number(value))}\""
    return (
        f"<label><span>{escape(label)}</span>"
        f"<input class=\"form-control\" name=\"{escape(name)}\" type=\"number\" step=\"0.000001\" "
        f"min=\"0\" required{value_attr}></label>"
    )


def _date_input(value: object | None = None) -> str:
    value_attr = ""
    if value is not None:
        value_attr = f" value=\"{escape(str(value or ''))}\""
    return (
        "<label><span>Buy date</span>"
        f"<input class=\"form-control\" name=\"buy_date\" type=\"date\" required{value_attr}></label>"
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
        f"<input class=\"form-control\" name=\"{escape(name)}\" type=\"text\" maxlength=\"{maxlength}\"{value_attr}>"
        "</label>"
    )


def _fmt_money(value: object, currency: object) -> str:
    text = _fmt_number(value, decimals=2)
    if text == "-":
        return text
    return f"{escape(str(currency or '').upper())} {text}".strip()


def _numeric_display_td(
    value: object,
    display_html: str,
    *,
    class_name: str = "",
) -> str:
    """Render a pre-formatted numeric cell without changing its displayed value."""

    numeric = optional_finite_float(value)
    sort_key = _MISSING_SORT_SENTINEL if numeric is None else f"{numeric:.17g}"
    classes = "numeric"
    if class_name:
        classes += " " + " ".join(str(class_name).split())
    return (
        f'<td class="{escape(classes, quote=True)}" '
        f'data-order="{sort_key}">{display_html}</td>'
    )


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
