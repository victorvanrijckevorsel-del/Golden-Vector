"""Option Trading overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingOverviewData,
    OptionTradingRow,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_numeric_td,
    _fmt_percent,
    _fmt_text,
)
from golden_vector.serve.overview_combined import _collect_filter_options, _render_filter_bar
from golden_vector.serve.page_shell import _page_shell


def _render_option_trading_overview_page(
    overview: OptionTradingOverviewData,
    *,
    model_state_manifest: dict[str, object] | None = None,
) -> str:
    snapshot_date = (
        overview.source_context.as_of_date
        if overview.source_context is not None
        else None
    )
    snapshot_note = (
        f"Cached options snapshot: {escape(snapshot_date)}; screening only - live prices may differ."
        if snapshot_date
        else "Cached options snapshot unavailable; screening only - live prices may differ."
    )
    body = [
        "<h1>Option Trading</h1>",
        f"<p class=\"hint\">{snapshot_note}</p>",
        render_model_state_banner(model_state_manifest),
        _render_context_warnings(overview.source_context),
        "<details class=\"method-disclosure\"><summary>Method</summary>"
        "<p>Contracts are selected from cached Yahoo Finance option-chain data. "
        "Last is informational only; bid, ask, spread, open interest, premium, "
        "DTE, moneyness, and delta drive the screening labels.</p>"
        "</details>",
    ]
    if overview.risk_free_rate_is_fallback:
        body.append(
            "<p class=\"hint\">Risk-free rate was missing from the options manifest; "
            "scenario values use a 0% rate fallback.</p>"
        )
    body.append(_render_liquidity_measurements(overview.liquidity_measurements))
    if not overview.rows:
        reason = overview.reason or "No optionable tickers are available."
        body.append(
            "<section class=\"panel\">"
            f"<p>{escape(reason)}</p>"
            "<p class=\"hint\">Run <code>python main.py update-data</code> to refresh options data.</p>"
            "</section>"
        )
        return _page_shell(
            "Option Trading - Golden Vector Workspace",
            "".join(body),
            active_nav="option_trading",
        )

    row_dicts = [_row_filter_dict(row) for row in overview.rows]
    body.append(
        _render_filter_bar(
            target_table_id="option-trading-table",
            options=_collect_filter_options(
                row_dicts,
                [
                    ("put_status", "put_status"),
                    ("call_status", "call_status"),
                    ("confidence", "confidence_label"),
                ],
            ),
            column_labels={
                "put_status": "Put Candidates",
                "call_status": "Call Candidates",
                "confidence": "Tool A Confidence",
            },
        )
    )
    rows_html = "".join(
        _render_row(row, snapshot_date=snapshot_date) for row in overview.rows
    )
    body.append(
        "<table id=\"option-trading-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"stock_price\" data-sort-numeric>Stock Price</th>"
        "<th data-col-name=\"down_beta\" data-sort-numeric>Down Beta</th>"
        "<th data-col-name=\"up_beta\" data-sort-numeric>Up Beta</th>"
        "<th data-col-name=\"confidence\">Tool A Confidence</th>"
        "<th data-col-name=\"iv\" data-sort-numeric>IV %ile</th>"
        "<th data-col-name=\"put_status\">Put Status</th>"
        "<th data-col-name=\"call_status\">Call Status</th>"
        "<th data-col-name=\"snapshot\">Snapshot Date</th>"
        "<th data-col-name=\"notes\">Notes</th>"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
    )
    return _page_shell(
        "Option Trading - Golden Vector Workspace",
        "".join(body),
        active_nav="option_trading",
    )


def _render_liquidity_measurements(
    measurements: tuple[OptionLiquidityMeasurement, ...],
) -> str:
    if not measurements:
        return ""
    rows = []
    for measurement in measurements:
        rows.append(
            "<tr>"
            f"<td>{escape(measurement.group_label)}</td>"
            f"<td>{_fmt_number(measurement.ticker_count, decimals=0)}</td>"
            f"<td>{_fmt_number(measurement.contract_count, decimals=0)}</td>"
            f"<td>{_fmt_number(measurement.tradable_count, decimals=0)}</td>"
            f"<td>{_fmt_number(measurement.watch_count, decimals=0)}</td>"
            f"<td>{_fmt_number(measurement.no_trade_count, decimals=0)}</td>"
            f"<td>{_fmt_percent(measurement.median_rel_spread, decimals=1)}</td>"
            f"<td>{_fmt_number(measurement.median_open_interest, decimals=0)}</td>"
            f"<td>{_fmt_number(measurement.median_volume, decimals=0)}</td>"
            f"<td>{_fmt_number(measurement.median_near_spot_depth, decimals=0)}</td>"
            "</tr>"
        )
    return (
        "<section class=\"nested-panel\">"
        "<h2>Cached Liquidity Check</h2>"
        "<p class=\"hint\">Informational only: medians use cached contracts with usable bid/ask/mid. "
        "They measure whether benchmark ETFs are actually liquid in the snapshot. "
        "If Benchmark ETFs show zero contracts, GDX/GDXJ option chains are not measured in "
        "the latest snapshot yet. Proxy alternatives stay hidden unless this cached check supports them.</p>"
        "<table><thead><tr>"
        "<th>Group</th><th>Tickers</th><th>Measured Contracts</th>"
        "<th>Tradable</th><th>Watch</th><th>No-trade</th>"
        "<th>Median Spread</th><th>Median OI</th><th>Median Volume</th>"
        "<th>Median Near-Spot Depth</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_context_warnings(context: object | None) -> str:
    warnings = tuple(getattr(context, "context_warnings", ()) or ())
    if not warnings:
        return ""
    paragraphs = "".join(f"<p>{escape(str(warning))}</p>" for warning in warnings)
    return f"<div class=\"flash option-context-warning\">{paragraphs}</div>"


def _render_row(row: OptionTradingRow, *, snapshot_date: str | None) -> str:
    detail_href = f"/ticker/{quote(row.ticker, safe='')}?lens=option-trading#option-trading"
    return (
        "<tr>"
        f"<td><a href=\"{escape(detail_href)}\">{escape(row.ticker)}</a></td>"
        f"{_fmt_numeric_td(row.current_stock_price, decimals=2)}"
        f"{_fmt_numeric_td(row.down_beta_core, decimals=2)}"
        f"{_fmt_numeric_td(row.up_beta_core, decimals=2)}"
        f"<td>{_fmt_text(row.confidence_label)}</td>"
        f"{_fmt_numeric_td(row.iv_percentile_cross_sectional, decimals=1)}"
        f"<td>{_status_label(row.put_status)}</td>"
        f"<td>{_status_label(row.call_status)}</td>"
        f"<td>{_fmt_text(snapshot_date)}</td>"
        f"<td>{escape('; '.join(row.notes)) if row.notes else '-'}</td>"
        "</tr>"
    )


def _row_filter_dict(row: OptionTradingRow) -> dict[str, str]:
    return {
        "put_status": _status_text(row.put_status),
        "call_status": _status_text(row.call_status),
        "confidence_label": row.confidence_label,
    }


def _status_label(status: str) -> str:
    css_class = {
        "tradable": "badge-verified",
        "watch": "badge-estimated",
        "none": "badge-missing",
        "available": "badge-verified",
        "thin": "badge-missing",
    }.get(status, "badge")
    label = _status_text(status)
    return f"<span class=\"badge {css_class}\">{escape(label)}</span>"


def _status_text(status: str) -> str:
    return {
        "tradable": "Tradable candidate",
        "watch": "Watch candidate",
        "none": "No liquid candidate",
        "available": "Tradable candidate",
        "thin": "No liquid candidate",
    }.get(status, status)
