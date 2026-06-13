"""Lab page: browse the Conditional Dial analog table (multi-horizon, GDX+GDXJ).

Render-only surface: every number, label, and the rank order come from the
persisted lab artifact. This page formats and escapes — it never counts, shrinks,
or ranks. Longer horizons whose cells are all insufficient render a dedicated
evidence-collapse panel, never a normal sortable table with hidden numbers.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from golden_vector.serve.column_help import help_term, help_th
from golden_vector.serve.format_helpers import _fmt_numeric_td, _fmt_text
from golden_vector.serve.lab_curve_data import LabCellsData
from golden_vector.serve.page_shell import _page_shell


def _render_lab_overview_page(
    data: LabCellsData,
    *,
    selected_bucket: str,
    selected_horizon: int = 13,
) -> str:
    body = ["<h1>Lab — Gold Scenario Analogs</h1>"]
    body.append(
        "<p>Pick a hypothetical gold move and a look-ahead window. The table counts "
        "every historical episode where gold did that, and shows how often each miner "
        "beat the benchmark in those episodes — counted history, not a prediction. "
        "Click a ticker to see which weeks it happened.</p>"
    )

    if not data.available:
        if data.error_status == "CORRUPT":
            body.append(
                "<div class=\"flash flash-warning\">Lab artifact is corrupt and "
                "could not be read. Rebuild it: "
                "<code>python -m golden_vector.lab.conditional_dial</code>.</div>"
            )
        elif data.error_status == "STALE":
            body.append(
                "<div class=\"flash flash-warning\">Lab artifact was built by an older "
                "version and is missing the multi-horizon / GDXJ columns. Rebuild it: "
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

    horizon = int(data.horizon)
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

    body.append(_render_filters(data, selected_bucket=selected_bucket, horizon=horizon))

    usable = int(
        data.bucket_availability.get(str(horizon), {}).get(selected_bucket, 0)
    )
    if usable <= 0:
        body.append(_render_empty_state(data, selected_bucket=selected_bucket, horizon=horizon))
        return _page_shell(
            "Lab - Golden Vector Workspace", "".join(body), active_nav="lab"
        )

    rows_html = [_render_dial_row(row, selected_bucket=selected_bucket, horizon=horizon) for row in data.rows]
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"10\" class=\"hint\">No rows for this scenario.</td></tr>"
        )
    body.append(
        "<table id=\"lab-dial-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"rank\" data-sort-numeric>Rank</th>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        + help_th("P(beat GDX), shrunk", key="lab_p_beat_shrunk", col_name="p_beat", sort_numeric=True)
        + help_th("P(beat GDX), raw", key="lab_p_beat_raw", col_name="p_beat_raw", sort_numeric=True)
        + help_th("P(beat GDXJ), shrunk", key="lab_p_beat_gdxj", col_name="p_beat_gdxj", sort_numeric=True)
        + help_th("95% range (GDX)", key="lab_wilson", col_name="wilson")
        + help_th("Median alpha vs GDX", key="lab_median_alpha", col_name="median_alpha", sort_numeric=True)
        + help_th("Alpha 10–90% (GDX)", key="lab_alpha_range", col_name="alpha_range")
        + help_th("Weeks (effective)", key="lab_episodes", col_name="episodes", sort_numeric=True)
        + help_th("History", key="lab_history", col_name="history")
        + "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell(
        "Lab - Golden Vector Workspace", "".join(body), active_nav="lab"
    )


def _render_filters(data: LabCellsData, *, selected_bucket: str, horizon: int) -> str:
    horizon_options = []
    per_bucket_avail = {
        str(hz): data.bucket_availability.get(str(hz), {}).get(selected_bucket, 0)
        for hz in data.horizons
    }
    for hz in data.horizons:
        avail = per_bucket_avail.get(str(hz), 0)
        suffix = "" if avail > 0 else " — no usable cells"
        selected_attr = " selected" if int(hz) == int(horizon) else ""
        horizon_options.append(
            f"<option value=\"{int(hz)}\"{selected_attr}>{int(hz)}w{escape(suffix)}</option>"
        )
    bucket_options = []
    for bucket_key, bucket_label in data.buckets:
        selected_attr = " selected" if bucket_key == selected_bucket else ""
        bucket_options.append(
            f"<option value=\"{escape(bucket_key)}\"{selected_attr}>"
            f"{escape(bucket_label)}</option>"
        )
    horizon_help = help_term("Look-ahead", key="lab_horizon")
    return (
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/lab\" class=\"overview-filters-form\">"
        f"<label><span>{horizon_help}</span>"
        f"<select name=\"horizon\">{''.join(horizon_options)}</select></label>"
        f"<label><span>Gold scenario</span>"
        f"<select name=\"bucket\">{''.join(bucket_options)}</select></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(data.rows)} tickers.</span>"
        "<button type=\"submit\">Apply</button>"
        "</div>"
        "</form>"
        "</section>"
    )


def _render_empty_state(data: LabCellsData, *, selected_bucket: str, horizon: int) -> str:
    """Evidence-collapse view: no rank, no sortable table — explain WHY it's blank."""

    scenario_label = dict(data.buckets).get(selected_bucket, selected_bucket)
    rows = []
    for hz in data.horizons:
        count = data.bucket_availability.get(str(hz), {}).get(selected_bucket, 0)
        rows.append(
            f"<tr><td>{int(hz)} weeks</td>"
            f"<td>{int(count)} of {len(data.rows) or '—'} miners have enough independent history</td></tr>"
        )
    return (
        "<section class=\"panel lab-empty-state\">"
        f"<h2>No countable history at {int(horizon)} weeks for "
        f"&ldquo;{escape(str(scenario_label))}&rdquo;</h2>"
        "<p>Over a longer look-ahead window, about three years of weekly history leaves "
        "too few <em>independent</em> episodes to count anything reliably, so every cell "
        "here would be a guess. That is why the dial judges over 13 weeks by default. "
        "Whether a longer holding period actually predicts better is a separate, "
        "out-of-sample question — not something to read off this table.</p>"
        "<table><thead><tr><th>Look-ahead</th><th>Usable miners in this scenario</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "<p class=\"hint\">Switch the look-ahead back to 13 weeks (or pick another gold "
        "scenario) to see counted results.</p>"
        "</section>"
    )


def _drilldown_href(ticker: str, *, bucket: str, horizon: int) -> str:
    return (
        f"/lab/dial/{quote(str(ticker), safe='')}"
        f"?scenario={quote(str(bucket), safe='')}&horizon={int(horizon)}&benchmark=GDX"
    )


def _render_dial_row(row: dict[str, Any], *, selected_bucket: str = "", horizon: int = 13) -> str:
    ticker = str(row.get("ticker") or "")
    bucket = str(row.get("bucket") or selected_bucket)
    href = _drilldown_href(ticker, bucket=bucket, horizon=horizon)
    ticker_cell = f"<td><a href=\"{escape(href, quote=True)}\">{escape(ticker)}</a></td>"
    if bool(row.get("gdx_insufficient_history")):
        # One <td> per header column (no colspan): DataTables counts cells. The
        # six stat columns show a muted dash; History carries the reason.
        dash = "<td class=\"hint\">—</td>"
        return (
            "<tr>"
            f"{_fmt_numeric_td(row.get('rank_in_bucket'), decimals=0)}"
            f"{ticker_cell}"
            f"{dash * 6}"
            f"<td>{_fmt_text(_episodes_text(row))}</td>"
            "<td class=\"hint\">insufficient history</td>"
            "</tr>"
        )
    return (
        "<tr>"
        f"{_fmt_numeric_td(row.get('rank_in_bucket'), decimals=0)}"
        f"{ticker_cell}"
        f"{_fmt_numeric_td(row.get('p_beat_gdx_shrunk'), decimals=1, as_percent=True)}"
        f"{_fmt_numeric_td(row.get('p_beat_gdx'), decimals=1, as_percent=True)}"
        f"{_gdxj_cell(row)}"
        f"<td>{_fmt_text(_range_text(row.get('gdx_wilson_low'), row.get('gdx_wilson_high'), as_percent=True))}</td>"
        f"{_fmt_numeric_td(row.get('median_alpha_gdx'), decimals=1, as_percent=True)}"
        f"<td>{_fmt_text(_range_text(row.get('alpha_q10_gdx'), row.get('alpha_q90_gdx'), as_percent=True))}</td>"
        f"<td>{_fmt_text(_episodes_text(row))}</td>"
        "<td>ok</td>"
        "</tr>"
    )


def _gdxj_cell(row: dict[str, Any]) -> str:
    """P(beat GDXJ) shrunk, or a dash when GDXJ has too little history."""

    if bool(row.get("gdxj_insufficient_history")):
        return "<td class=\"hint\">—</td>"
    value = row.get("p_beat_gdxj_shrunk")
    if value is None or value != value:  # None / NaN -> no GDXJ data
        return "<td class=\"hint\">—</td>"
    return _fmt_numeric_td(value, decimals=1, as_percent=True)


def _episodes_text(row: dict[str, Any]) -> str:
    n_weeks = row.get("gdx_n_weeks")
    effective = row.get("gdx_effective_n")
    if n_weeks is None or (isinstance(n_weeks, float) and n_weeks != n_weeks):
        return ""
    if effective is None or (isinstance(effective, float) and effective != effective):
        return f"{int(n_weeks)}"
    return f"{int(n_weeks)} ({effective})"


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
