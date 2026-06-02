"""Option Trading overview rendering for the workspace UI."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

from golden_vector.hedge.option_trading import OptionTradingOverviewData, OptionTradingRow
from golden_vector.serve.format_helpers import _fmt_numeric_td, _fmt_text
from golden_vector.serve.overview_combined import _collect_filter_options, _render_filter_bar
from golden_vector.serve.page_shell import _page_shell


def _render_option_trading_overview_page(
    overview: OptionTradingOverviewData,
) -> str:
    body = [
        "<h1>Option Trading</h1>",
        "<p>Optionable gold stocks ranked by gold-downside sensitivity. "
        "The put scenario column is computed server-side from the same candidate grid "
        "used by the ticker detail page.</p>",
        "<p class=\"hint\"><a class=\"raw-report-download\" href=\"/hedge-readiness/latest.md\">"
        "Download latest raw hedge-readiness markdown report</a></p>",
    ]
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
                    ("optionability", "optionability_tier"),
                    ("put_status", "put_status"),
                    ("call_status", "call_status"),
                    ("confidence", "confidence_label"),
                ],
            ),
            column_labels={
                "optionability": "Optionability",
                "put_status": "Put Status",
                "call_status": "Call Status",
                "confidence": "Confidence",
            },
        )
    )
    rows_html = "".join(_render_row(row) for row in overview.rows)
    body.append(
        "<table id=\"option-trading-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"down_beta\" data-sort-numeric>Down Beta</th>"
        "<th data-col-name=\"up_beta\" data-sort-numeric>Up Beta</th>"
        "<th data-col-name=\"confidence\">Confidence</th>"
        "<th data-col-name=\"iv\" data-sort-numeric>IV Percentile</th>"
        "<th data-col-name=\"optionability\">Optionability</th>"
        "<th data-col-name=\"put_status\">Put Status</th>"
        "<th data-col-name=\"call_status\">Call Status</th>"
        "<th data-col-name=\"put_pnl\" data-sort-numeric>Put P&amp;L/share @ Gold -10% (60d)</th>"
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


def _render_row(row: OptionTradingRow) -> str:
    detail_href = f"/ticker/{quote(row.ticker, safe='')}?lens=option-trading#option-trading"
    return (
        "<tr>"
        f"<td><a href=\"{escape(detail_href)}\">{escape(row.ticker)}</a></td>"
        f"{_fmt_numeric_td(row.down_beta_core, decimals=2)}"
        f"{_fmt_numeric_td(row.up_beta_core, decimals=2)}"
        f"<td>{_fmt_text(row.confidence_label)}</td>"
        f"{_fmt_numeric_td(row.iv_percentile_cross_sectional, decimals=1)}"
        f"<td>{_fmt_text(row.optionability_tier)}</td>"
        f"<td>{_status_label(row.put_status)}</td>"
        f"<td>{_status_label(row.call_status)}</td>"
        f"{_fmt_numeric_td(row.pnl_put_at_minus10_60d, decimals=2)}"
        f"<td>{escape('; '.join(row.notes)) if row.notes else '-'}</td>"
        "</tr>"
    )


def _row_filter_dict(row: OptionTradingRow) -> dict[str, str]:
    return {
        "optionability_tier": row.optionability_tier,
        "put_status": row.put_status,
        "call_status": row.call_status,
        "confidence_label": row.confidence_label,
    }


def _status_label(status: str) -> str:
    css_class = {
        "available": "badge-verified",
        "thin": "badge-estimated",
        "none": "badge-missing",
    }.get(status, "badge")
    return f"<span class=\"badge {css_class}\">{escape(status)}</span>"
