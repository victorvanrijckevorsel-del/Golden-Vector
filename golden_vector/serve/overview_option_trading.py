"""Option Trading overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

import pandas as pd

from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge._helpers import rows_by_ticker_dict
from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingOverviewData,
    OptionTradingRow,
)
from golden_vector.serve.column_help import help_th
from golden_vector.serve.model_state_banner import (
    render_model_state_banner,
    render_option_freshness_box,
)
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_numeric_td,
    _fmt_percent,
    _fmt_text,
)
from golden_vector.serve.overview_helpers import _collect_filter_options, _render_filter_bar
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.option_signal_render import (
    option_signal_skew_display_value,
    option_signal_skew_hover,
    render_option_signal_badge,
)


def _render_option_trading_overview_page(
    overview: OptionTradingOverviewData,
    *,
    option_signal_summary: pd.DataFrame | None = None,
    model_state_manifest: dict[str, object] | None = None,
    app_config: AppConfig | None = None,
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
        render_option_freshness_box(model_state_manifest),
        _render_most_liquid_indicator(overview),
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
    body.append(
        _render_liquidity_measurements(
            overview.liquidity_measurements,
            app_config=app_config,
        )
    )
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

    signals = _signal_by_ticker(option_signal_summary)
    row_dicts = [_row_filter_dict(row, signal=signals.get(row.ticker)) for row in overview.rows]
    body.append(
        _render_filter_bar(
            target_table_id="option-trading-table",
            options=_collect_filter_options(
                row_dicts,
                [
                    ("direction", "direction_label"),
                    ("data_quality", "data_quality_label"),
                    ("put_status", "put_status"),
                    ("call_status", "call_status"),
                    ("confidence", "confidence_label"),
                ],
            ),
            column_labels={
                "direction": "Option Signal",
                "data_quality": "Option Signal Quality",
                "put_status": "Put Candidates",
                "call_status": "Call Candidates",
                "confidence": "Gold Sensitivity Confidence",
            },
        )
    )
    rows_html = "".join(
        _render_row(row, snapshot_date=snapshot_date, signal=signals.get(row.ticker))
        for row in overview.rows
    )
    body.append(
        "<table id=\"option-trading-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"stock_price\" data-sort-numeric>Stock Price</th>"
        "<th data-col-name=\"down_beta\" data-sort-numeric>Down Beta</th>"
        "<th data-col-name=\"up_beta\" data-sort-numeric>Up Beta</th>"
        "<th data-col-name=\"confidence\">Gold Sensitivity Confidence</th>"
        "<th data-col-name=\"direction\">Signal</th>"
        + help_th(
            "Skew vs Benchmark",
            key="skew_vs_benchmark",
            app_config=app_config,
            col_name="skew",
            sort_numeric=True,
        )
        + "<th data-col-name=\"activity\">Activity</th>"
        + help_th(
            "Option Cost Signal",
            key="option_cost_signal",
            app_config=app_config,
            col_name="cost",
        )
        + help_th(
            "Option Signal Quality",
            key="option_signal_quality",
            app_config=app_config,
            col_name="data_quality",
        )
        + help_th(
            "IV %ile",
            key="iv_percentile",
            app_config=app_config,
            col_name="iv",
            sort_numeric=True,
        )
        + "<th data-col-name=\"put_status\">Put Status</th>"
        "<th data-col-name=\"call_status\">Call Status</th>"
        + help_th(
            "Option Snapshot Date",
            key="option_snapshot_date",
            app_config=app_config,
            col_name="snapshot",
        )
        + "<th data-col-name=\"notes\">Notes</th>"
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
    *,
    app_config: AppConfig | None = None,
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
        "<p class=\"hint\">Informational only: the medians cover tradable contracts only - "
        "the contracts you could realistically trade - while the Tradable/Watch/No-trade "
        "counts cover every measured contract. A dash means the group has no tradable "
        "contracts in the cached snapshot. "
        "If Benchmark ETFs show zero contracts, GDX/GDXJ option chains are not measured in "
        "the latest snapshot yet. Proxy alternatives stay hidden unless this cached check supports them.</p>"
        "<table><thead><tr>"
        "<th>Group</th><th>Tickers</th>"
        + help_th("Measured Contracts", key="measured_contracts", app_config=app_config)
        + help_th("Tradable", key="tradable_count", app_config=app_config)
        + help_th("Watch", key="watch_count", app_config=app_config)
        + help_th("No-trade", key="no_trade_count", app_config=app_config)
        + help_th("Median Tradable Spread", key="median_tradable_spread", app_config=app_config)
        + help_th("Median Tradable OI", key="median_tradable_oi", app_config=app_config)
        + help_th("Median Tradable Volume", key="median_tradable_volume", app_config=app_config)
        + help_th(
            "Median Tradable Near-Spot Depth",
            key="median_tradable_near_spot_depth",
            app_config=app_config,
        )
        + "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_most_liquid_indicator(overview: OptionTradingOverviewData) -> str:
    """Show the backend-selected most-liquid windows for the miners group.

    The values are stamped on the persisted overview artifact at build time
    (per-ticker vote, benchmarks excluded); serve only renders them. Ticker
    detail pages open on each name's own side-aware most-liquid expiry.
    """

    put_default = overview.group_default_put_horizon_days
    call_default = overview.group_default_call_horizon_days
    if put_default is None and call_default is None:
        return ""
    parts = []
    if put_default is not None:
        parts.append(f"puts ~{put_default}d")
    if call_default is not None:
        parts.append(f"calls ~{call_default}d")
    return (
        "<p class=\"hint most-liquid-indicator\">"
        f"Most liquid windows right now (miners, backend-selected): {' · '.join(parts)}. "
        "Ticker pages open on each name's own most-liquid expiry."
        "</p>"
    )


def _render_context_warnings(context: object | None) -> str:
    warnings = tuple(getattr(context, "context_warnings", ()) or ())
    if not warnings:
        return ""
    paragraphs = "".join(f"<p>{escape(str(warning))}</p>" for warning in warnings)
    return f"<div class=\"flash option-context-warning\">{paragraphs}</div>"


def _render_row(
    row: OptionTradingRow,
    *,
    snapshot_date: str | None,
    signal: dict[str, object] | None,
) -> str:
    detail_href = f"/ticker/{quote(row.ticker, safe='')}?lens=option-trading#option-trading"
    return (
        "<tr>"
        f"<td><a href=\"{escape(detail_href)}\">{escape(row.ticker)}</a></td>"
        f"{_fmt_numeric_td(row.current_stock_price, decimals=2)}"
        f"{_fmt_numeric_td(row.down_beta_core, decimals=2)}"
        f"{_fmt_numeric_td(row.up_beta_core, decimals=2)}"
        f"<td>{_fmt_text(row.confidence_label)}</td>"
        f"<td>{_signal_badge(signal, 'direction_label')}</td>"
        f"{_vol_points_td(option_signal_skew_display_value(signal), title=option_signal_skew_hover(signal))}"
        f"<td>{_signal_badge(signal, 'activity_label')}</td>"
        f"<td>{_signal_badge(signal, 'cost_label')}</td>"
        f"<td>{_signal_badge(signal, 'data_quality_label')}</td>"
        f"{_fmt_numeric_td(row.iv_percentile_cross_sectional, decimals=1)}"
        f"<td>{_status_label(row.put_status)}</td>"
        f"<td>{_status_label(row.call_status)}</td>"
        f"<td>{_fmt_text(snapshot_date)}</td>"
        f"<td>{escape('; '.join(row.notes)) if row.notes else '-'}</td>"
        "</tr>"
    )


def _row_filter_dict(
    row: OptionTradingRow,
    *,
    signal: dict[str, object] | None,
) -> dict[str, str]:
    return {
        "direction_label": str(_signal_value(signal, "direction_label") or ""),
        "data_quality_label": str(_signal_value(signal, "data_quality_label") or ""),
        "put_status": _status_text(row.put_status),
        "call_status": _status_text(row.call_status),
        "confidence_label": row.confidence_label,
    }


def _signal_by_ticker(frame: pd.DataFrame | None) -> dict[str, dict[str, object]]:
    if frame is None:
        return {}
    return rows_by_ticker_dict(frame, strip=True)


def _signal_value(signal: dict[str, object] | None, key: str) -> object | None:
    if not signal:
        return None
    return signal.get(key)


def _signal_badge(signal: dict[str, object] | None, key: str) -> str:
    value = _signal_value(signal, key)
    if value is None:
        return "-"
    return render_option_signal_badge(value)


def _vol_points_td(value: object | None, *, title: str | None = None) -> str:
    title_attr = f" title=\"{escape(title)}\"" if title else ""
    try:
        numeric = float(value) if value is not None else None
    except (TypeError, ValueError):
        numeric = None
    if numeric is None or pd.isna(numeric):
        return f"<td data-order=\"9000000000000000\"{title_attr}>-</td>"
    return (
        f"<td data-order=\"{numeric:.8f}\"{title_attr}>"
        f"{escape(f'{numeric * 100:.1f} vol pts')}</td>"
    )


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
