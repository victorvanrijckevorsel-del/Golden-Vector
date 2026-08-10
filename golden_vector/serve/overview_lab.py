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

from golden_vector.lab.conditional_dial import DIAL_HORIZONS_WEEKS
from golden_vector.serve.column_help import help_term, help_th
from golden_vector.serve.format_helpers import (
    _MISSING_SORT_SENTINEL,
    _fmt_numeric_td,
    _fmt_text,
)
from golden_vector.serve.lab_curve_data import LabCellsData
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import page_header
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region

_DEFAULT_HORIZON = 13 if 13 in DIAL_HORIZONS_WEEKS else DIAL_HORIZONS_WEEKS[0]


def _render_lab_overview_page(
    data: LabCellsData,
    *,
    selected_bucket: str,
) -> str:
    body = [
        page_header(
            "Lab — Gold Scenario Analogs",
            lead_html=(
                "<p>Pick a hypothetical gold move and a look-ahead window. The table counts "
                "every historical episode where gold did that, and shows how often each miner "
                "beat the benchmark in those episodes — counted history, not a prediction. "
                "Click a ticker to see which weeks it happened.</p>"
            ),
        )
    ]

    if not data.available:
        rebuild = "<code>python -m golden_vector.lab.conditional_dial</code>"
        status = data.error_status
        if status == "CORRUPT":
            msg = f"Lab artifact is corrupt and could not be read. Rebuild it: {rebuild}."
        elif status in ("META_MISSING", "META_CORRUPT"):
            # Data is intact; only the metadata sidecar is bad — not a stale shape.
            msg = (
                "Lab data is present but its metadata is missing or unreadable, so "
                f"freshness can't be verified. Rebuild it: {rebuild}."
            )
        elif status == "STALE":
            msg = (
                "Lab artifact is out of date (older schema, or the configured "
                f"look-aheads/benchmarks changed). Rebuild it: {rebuild}."
            )
        elif status == "EMPTY":
            msg = (
                "The Lab built but found no countable miners (empty universe). "
                f"Check the input data, then rebuild: {rebuild}."
            )
        else:
            msg = f"Lab artifacts are not built yet. Run {rebuild} first."
        # Plan 10.5 mapping: corrupt/unreadable-metadata artifacts are danger;
        # STALE (older schema/config) is a freshness state and stays warning,
        # as do absent and empty builds — all with the rebuild action.
        tone = (
            "danger"
            if status in ("CORRUPT", "META_MISSING", "META_CORRUPT")
            else "warning"
        )
        body.append(notice(tone, msg))
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
            notice(
                "info",
                f"{' '.join(banner_bits)} "
                "Confidence ranges use episode-adjusted sample counts (overlapping "
                "weekly windows are not independent observations).",
            )
        )

    body.append(_render_filters(data, selected_bucket=selected_bucket, horizon=horizon))

    # Derive usable/total from the SAME rows the table renders (NOT from meta), so
    # the banner can never contradict the table (e.g. claim "no countable history"
    # above ranked, clickable rows). bucket_availability stays a selector-label hint.
    total = len(data.rows)
    usable = sum(1 for r in data.rows if not bool(r.get("gdx_insufficient_history")))
    # Always show the table. When some/all miners lack countable history, a slim
    # banner explains it; those rows render greyed + non-clickable (below).
    if usable < total:
        body.append(
            _render_thin_banner(
                data,
                selected_bucket=selected_bucket,
                horizon=horizon,
                usable=usable,
                total=total,
            )
        )

    rows_html = [_render_dial_row(row, selected_bucket=selected_bucket, horizon=horizon) for row in data.rows]
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"10\" class=\"hint\">No rows for this scenario.</td></tr>"
        )
    body.append(table_region(
        "<table id=\"lab-dial-table\" class=\"js-datatable\">"
        "<thead><tr>"
        + help_th("Rank", key="lab_rank", col_name="rank", sort_numeric=True)
        + help_th("Ticker", key="ticker_symbol", col_name="ticker")
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
        "</table>",
        region_id="lab-dial-table-region",
        label="Gold scenario analog ranking",
    ))
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
        "<button type=\"submit\" class=\"btn btn-primary\">Apply</button>"
        "</div>"
        "</form>"
        "</section>"
    )


def _render_thin_banner(
    data: LabCellsData,
    *,
    selected_bucket: str,
    horizon: int,
    usable: int,
    total: int,
) -> str:
    """Slim banner shown above the table when some/all miners lack history.

    The table still renders every miner; rows without enough history are greyed
    and non-clickable. This explains why without taking over the page."""

    scenario_label = dict(data.buckets).get(selected_bucket, selected_bucket)
    if usable <= 0:
        if int(horizon) != _DEFAULT_HORIZON:
            switch = (
                f"Switch the look-ahead to {_DEFAULT_HORIZON} weeks (or pick another "
                "gold scenario)"
            )
        else:
            switch = "Pick another gold scenario"
        return notice(
            "warning",
            f"<strong>No miner has countable history against GDX at {int(horizon)} weeks "
            f"for &ldquo;{escape(str(scenario_label))}&rdquo;.</strong> About three years "
            "of weekly data leaves too few <em>independent</em> episodes over a window "
            "this long to count anything reliably, so the rows below are shown for "
            f"completeness but can't be ranked or opened. {switch} for counted, "
            "clickable results.",
        )
    return notice(
        "info",
        f"{usable} of {total} miners have enough independent history against GDX at "
        f"{int(horizon)} weeks for this scenario. The greyed rows below don't, so they "
        "can't be ranked or opened.",
    )


def _drilldown_href(ticker: str, *, bucket: str, horizon: int) -> str:
    return (
        f"/lab/dial/{quote(str(ticker), safe='')}"
        f"?scenario={quote(str(bucket), safe='')}&horizon={int(horizon)}&benchmark=GDX"
    )


def _render_dial_row(row: dict[str, Any], *, selected_bucket: str = "", horizon: int = 13) -> str:
    ticker = str(row.get("ticker") or "")
    bucket = str(row.get("bucket") or selected_bucket)
    if bool(row.get("gdx_insufficient_history")):
        # No countable history -> the ticker is NOT a link (nothing to rank/open),
        # shown greyed with a non-colour "(no data)" cue. One <td> per header column
        # (no colspan): DataTables counts cells. The 4 numeric stat columns use the
        # sort-last sentinel so they can't interleave with ranked rows on re-sort;
        # the 2 text range columns show a plain dash. History carries the reason.
        ticker_plain = (
            f"<td class=\"hint lab-no-data\">{escape(ticker)} "
            "<span class=\"hint\">(no data)</span></td>"
        )
        num_dash = _fmt_numeric_td(None, decimals=1)  # data-order = sort-last sentinel
        text_dash = "<td class=\"hint\">—</td>"
        return (
            "<tr class=\"lab-row-insufficient\">"
            f"{_fmt_numeric_td(row.get('rank_in_bucket'), decimals=0)}"
            f"{ticker_plain}"
            f"{num_dash}{num_dash}{num_dash}"  # P(beat shrunk), P(beat raw), P(beat GDXJ)
            f"{text_dash}"  # 95% range
            f"{num_dash}"  # Median alpha
            f"{text_dash}"  # Alpha 10-90%
            f"{_episodes_cell(row)}"
            "<td class=\"hint\">insufficient history</td>"
            "</tr>"
        )
    href = _drilldown_href(ticker, bucket=bucket, horizon=horizon)
    ticker_cell = f"<td><a href=\"{escape(href, quote=True)}\">{escape(ticker)}</a></td>"
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
        f"{_episodes_cell(row)}"
        "<td>ok</td>"
        "</tr>"
    )


def _episodes_cell(row: dict[str, Any]) -> str:
    """Weeks (effective) cell with a numeric sort key (effective N), so the
    `sort_numeric` header actually sorts. NA -> sort-last sentinel."""

    effective = row.get("gdx_effective_n")
    has_eff = effective is not None and not (
        isinstance(effective, float) and effective != effective
    )
    order = effective if has_eff else _MISSING_SORT_SENTINEL
    return f"<td data-order=\"{order}\">{_fmt_text(_episodes_text(row))}</td>"


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
