"""Lab page: browse the Conditional Dial analog table.

Render-only surface: every number, label, and the rank order come from the
persisted lab artifact. This page formats and escapes — nothing else.
"""

from __future__ import annotations

from html import escape
from typing import Any

from golden_vector.serve.format_helpers import _fmt_numeric_td, _fmt_text
from golden_vector.serve.lab_data import LabDialData
from golden_vector.serve.column_help import help_th
from golden_vector.serve.page_shell import _page_shell


def _render_lab_overview_page(data: LabDialData, *, selected_bucket: str) -> str:
    body = ["<h1>Lab — Gold Scenario Analogs</h1>"]
    body.append(
        "<p>Pick a hypothetical gold move over the next ~13 weeks (one quarter). "
        "The table counts every historical episode where gold did that, and shows "
        "how often each miner beat the GDX benchmark in those episodes — counted "
        "history, not a prediction.</p>"
    )

    if not data.available:
        if data.error_status == "CORRUPT":
            body.append(
                "<div class=\"flash flash-warning\">Lab artifact is corrupt and "
                "could not be read. Rebuild it: "
                "<code>python -m golden_vector.lab.conditional_dial</code>.</div>"
            )
        else:
            body.append(
                "<div class=\"flash flash-warning\">Lab artifacts are not built yet. "
                "Run <code>python -m golden_vector.lab.conditional_dial</code> first.</div>"
            )
        return _page_shell(
            "Lab - Golden Vector Workspace", "".join(body), active_nav="lab"
        )

    caveat = str(data.meta.get("caveat") or "")
    built_at = str(data.meta.get("built_at_utc") or "")
    banner_bits = []
    if caveat:
        banner_bits.append(escape(caveat))
    if built_at:
        banner_bits.append(f"Built {escape(built_at)}.")
    if banner_bits:
        body.append(
            f"<div class=\"flash\">{' '.join(banner_bits)} "
            "Confidence ranges use episode-adjusted sample counts (overlapping "
            "weekly windows are not independent observations).</div>"
        )

    options = []
    for bucket_key, bucket_label in data.buckets:
        selected_attr = " selected" if bucket_key == selected_bucket else ""
        options.append(
            f"<option value=\"{escape(bucket_key)}\"{selected_attr}>"
            f"{escape(bucket_label)}</option>"
        )
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/lab\" class=\"overview-filters-form\">"
        f"<label><span>Gold scenario</span><select name=\"bucket\">{''.join(options)}</select></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(data.rows)} tickers.</span>"
        "<button type=\"submit\">Apply</button>"
        "</div>"
        "</form>"
        "</section>"
    )

    rows_html: list[str] = []
    for row in data.rows:
        rows_html.append(_render_dial_row(row))
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"9\" class=\"hint\">No rows for this scenario.</td></tr>"
        )

    body.append(
        "<table id=\"lab-dial-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"rank\" data-sort-numeric>Rank</th>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        + help_th("P(beat GDX), shrunk", key="lab_p_beat_shrunk", col_name="p_beat", sort_numeric=True)
        + help_th("P(beat GDX), raw", key="lab_p_beat_raw", col_name="p_beat_raw", sort_numeric=True)
        + help_th("95% range", key="lab_wilson", col_name="wilson")
        + help_th("Median alpha vs GDX", key="lab_median_alpha", col_name="median_alpha", sort_numeric=True)
        + help_th("Alpha 10–90%", key="lab_alpha_range", col_name="alpha_range")
        + help_th("Weeks (effective)", key="lab_episodes", col_name="episodes", sort_numeric=True)
        + help_th("History", key="lab_history", col_name="history")
        + "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell(
        "Lab - Golden Vector Workspace", "".join(body), active_nav="lab"
    )


def _render_dial_row(row: dict[str, Any]) -> str:
    ticker = str(row.get("ticker") or "")
    if bool(row.get("insufficient_history")):
        # One <td> per header column (no colspan): DataTables counts cells,
        # not colspans, so a short row breaks the whole table. The five stat
        # columns show a muted dash; the History column carries the reason.
        dash = "<td class=\"hint\">—</td>"
        return (
            "<tr>"
            f"{_fmt_numeric_td(row.get('rank_in_bucket'), decimals=0)}"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"{dash * 5}"
            f"<td>{_fmt_text(_episodes_text(row))}</td>"
            "<td class=\"hint\">insufficient history</td>"
            "</tr>"
        )
    return (
        "<tr>"
        f"{_fmt_numeric_td(row.get('rank_in_bucket'), decimals=0)}"
        f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
        f"{_fmt_numeric_td(row.get('p_beat_gdx_shrunk'), decimals=1, as_percent=True)}"
        f"{_fmt_numeric_td(row.get('p_beat_gdx'), decimals=1, as_percent=True)}"
        f"<td>{_fmt_text(_range_text(row.get('wilson_low'), row.get('wilson_high'), as_percent=True))}</td>"
        f"{_fmt_numeric_td(row.get('median_alpha'), decimals=1, as_percent=True)}"
        f"<td>{_fmt_text(_range_text(row.get('alpha_q10'), row.get('alpha_q90'), as_percent=True))}</td>"
        f"<td>{_fmt_text(_episodes_text(row))}</td>"
        "<td>ok</td>"
        "</tr>"
    )


def _episodes_text(row: dict[str, Any]) -> str:
    n_weeks = row.get("n_weeks")
    effective = row.get("effective_n")
    if n_weeks is None:
        return ""
    if effective is None:
        return f"{n_weeks}"
    return f"{n_weeks} ({effective})"


def _range_text(low: Any, high: Any, *, as_percent: bool = False) -> str:
    if low is None or high is None:
        return ""
    try:
        low_value = float(low)
        high_value = float(high)
    except (TypeError, ValueError):
        return ""
    if low_value != low_value or high_value != high_value:  # NaN guard
        return ""
    if as_percent:
        return f"{low_value:+.1%} to {high_value:+.1%}"
    return f"{low_value:+.3f} to {high_value:+.3f}"
