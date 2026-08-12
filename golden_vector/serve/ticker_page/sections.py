"""M3 section renderers for the redesigned ticker page.

Render-only: every value below is read 1:1 from a persisted artifact row.
The ONLY transformations are display formatting (percent/date formatting) —
no arithmetic, no fallback resolution, no eligibility decisions.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd

from golden_vector.serve.charts import _build_multiline_overlay_svg, _build_scatter_svg
from golden_vector.serve.column_help import help_icon
from golden_vector.serve.ui.tables import table_region


# ---------------------------------------------------------------------------
# Formatting helpers (display only)
# ---------------------------------------------------------------------------


def _fmt_pct(value: Any, *, decimals: int = 1, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    sign = "+" if signed and float(value) >= 0 else ""
    return f"{sign}{float(value) * 100:.{decimals}f}%"


def _fmt_pp(value: Any, *, decimals: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):+.{decimals}f} percentage points"


def _fmt_date(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return str(pd.Timestamp(value).date())


def _fmt_share(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) * 100:.0f}%"


# ---------------------------------------------------------------------------
# Performance section (M3a)
# ---------------------------------------------------------------------------

_SERIES_LABELS = {"stock": "Stock", "gold": "Gold", "gdx": "GDX", "gdxj": "GDXJ"}


def render_performance_section(
    performance_rows: pd.DataFrame,
    *,
    ticker: str,
    horizon: str,
    view: str = "rebased",
) -> str:
    """The performance chart from the v2 artifact — actual dates, one shared

    anchor, series markers for omitted/missing lines. ``view`` is
    ``rebased`` (Compare, indexed to 100) or ``price`` (the stock alone, USD).
    """

    if performance_rows is None or performance_rows.empty:
        return (
            '<section class="panel" id="performance"><h2>Performance'
            + help_icon(
                "Performance", key="ticker_performance_chart", app_config=None
            )
            + "</h2>"
            '<p class="hint">No performance data has been published for this ticker.</p>'
            "</section>"
        )

    horizon_rows = performance_rows.loc[performance_rows["horizon"].eq(horizon)]
    ok_rows = horizon_rows.loc[
        horizon_rows["series_status"].eq("OK") & horizon_rows["view"].eq(view)
    ]
    if view == "price":
        ok_rows = ok_rows.loc[ok_rows["series"].eq("stock")]

    series_by_label: dict[str, tuple[list[pd.Timestamp], list[float | None]]] = {}
    for series_name, group in ok_rows.groupby("series"):
        ordered = group.sort_values("date")
        label = _SERIES_LABELS.get(str(series_name), str(series_name).upper())
        series_by_label[label] = (
            [pd.Timestamp(value) for value in ordered["date"]],
            [None if pd.isna(value) else float(value) for value in ordered["value"]],
        )

    marker_rows = horizon_rows.loc[
        ~horizon_rows["series_status"].isin(["OK"]) & horizon_rows["view"].eq(view)
    ]
    notices = [
        (
            f'<p class="hint">{escape(_SERIES_LABELS.get(str(row["series"]), str(row["series"]).upper()))}: '
            f'{escape(str(row["series_reason"] or row["series_status"]))}</p>'
        )
        for _, row in marker_rows.drop_duplicates(subset=["series"]).iterrows()
    ]

    basis_bits: list[str] = []
    if not ok_rows.empty:
        first = ok_rows.iloc[0]
        anchor = first.get("rebase_date")
        if view == "rebased" and anchor is not None and not pd.isna(anchor):
            basis_bits.append(f"indexed to 100 on {_fmt_date(anchor)}")
        common_end = first.get("common_end_date")
        if common_end is not None and not pd.isna(common_end):
            basis_bits.append(f"through {_fmt_date(common_end)}")
        price_basis = first.get("price_basis")
        if price_basis is not None and not pd.isna(price_basis):
            basis_bits.append(f"basis: {escape(str(price_basis))}")
    trim_notes = {
        str(reason)
        for reason in horizon_rows["trim_reason"].dropna().unique()
        if str(reason).strip()
    }

    chart_html = (
        _build_multiline_overlay_svg(series_by_label=series_by_label)
        if series_by_label
        else '<p class="hint">No drawable series in this window.</p>'
    )

    view_label = "Compare (indexed to 100)" if view == "rebased" else "Share price (USD)"
    return (
        f'<section class="panel" id="performance"><h2>Performance — {escape(ticker)}'
        + help_icon("Performance", key="ticker_performance_chart", app_config=None)
        + "</h2>"
        f'<p class="hint">{escape(view_label)} · horizon {escape(horizon)}'
        + (" · " + escape("; ".join(basis_bits)) if basis_bits else "")
        + "</p>"
        + chart_html
        + "".join(notices)
        + "".join(f'<p class="hint">{escape(note)}</p>' for note in sorted(trim_notes))
        + "</section>"
    )


# ---------------------------------------------------------------------------
# Currency attribution block (Feature A UI)
# ---------------------------------------------------------------------------


def _attribution_headline(row: pd.Series, *, ticker: str) -> str:
    relationship = str(row.get("relationship") or "")
    currency = str(row.get("quote_currency") or "")
    local_return = row.get("local_return")
    usd_return = row.get("usd_return")
    if relationship == "SAME_DIRECTION":
        direction = "gain" if (usd_return is not None and not pd.isna(usd_return) and float(usd_return) >= 0) else "loss"
        return (
            f"FX accounted for {_fmt_share(row.get('share_of_usd_move'))} "
            f"of the total USD {direction}."
        )
    if relationship == "OFFSET":
        fx_up = row.get("fx_return")
        strength = "strength" if (fx_up is not None and not pd.isna(fx_up) and float(fx_up) >= 0) else "weakness"
        local_word = "decline" if (local_return is not None and not pd.isna(local_return) and float(local_return) < 0) else "gain"
        return (
            f"{currency} {strength} offset about "
            f"{_fmt_share(row.get('offset_of_local_move'))} of {ticker}'s "
            f"local-currency {local_word}."
        )
    if relationship == "REVERSAL":
        return "FX more than offset the local move and reversed the USD result."
    if relationship == "LOCAL_FLAT":
        return "The result was primarily currency-driven."
    return "Currency attribution is unavailable for this window."


def render_currency_attribution_block(
    fx_rows: pd.DataFrame,
    *,
    ticker: str,
    horizon: str,
) -> str:
    """The Currency attribution block below the Performance chart (Feature A).

    Hidden entirely for USD listings (explicit NOT_APPLICABLE_USD rows);
    UNAVAILABLE windows explain themselves instead of fabricating attribution.
    """

    if fx_rows is None or fx_rows.empty:
        return ""
    match = fx_rows.loc[fx_rows["horizon"].eq(horizon)]
    if match.empty:
        return ""
    row = match.iloc[0]
    status = str(row.get("attribution_status") or "")
    if status == "NOT_APPLICABLE_USD":
        return ""  # the UI hides USD listings — there is no FX leg

    explainer = help_icon(
        "Currency attribution", key="ticker_fx_attribution", app_config=None
    )

    if status != "OK":
        reason = str(row.get("attribution_reason") or "attribution unavailable")
        return (
            '<div class="fx-attribution" id="currency-attribution">'
            "<h3>Currency attribution"
            f"{explainer}</h3>"
            f'<p class="hint">{escape(reason)}</p>'
            "</div>"
        )

    headline = _attribution_headline(row, ticker=ticker)
    universal = f"FX changed the USD return by {_fmt_pp(row.get('fx_contribution_pp'))}."
    currency = escape(str(row.get("quote_currency") or ""))
    table_html = (
        '<table class="compact-table"><tbody>'
        f"<tr><th scope=\"row\">Local share return ({currency})</th>"
        f"<td>{_fmt_pct(row.get('local_return'), signed=True)}</td></tr>"
        f"<tr><th scope=\"row\">{currency}/USD rate return</th>"
        f"<td>{_fmt_pct(row.get('fx_return'), signed=True)}</td></tr>"
        "<tr><th scope=\"row\">FX contribution to the USD return</th>"
        f"<td>{escape(_fmt_pp(row.get('fx_contribution_pp')))}</td></tr>"
        "<tr><th scope=\"row\">USD-investor return</th>"
        f"<td>{_fmt_pct(row.get('usd_return'), signed=True)}</td></tr>"
        "</tbody></table>"
    )
    period = (
        f"Exact period: {_fmt_date(row.get('start_date'))} to {_fmt_date(row.get('end_date'))} "
        f"(chart endpoints) · FX source {escape(str(row.get('fx_source_symbol') or 'n/a'))} "
        f"· price basis {escape(str(row.get('price_basis') or 'n/a'))}"
    )
    return (
        '<div class="fx-attribution" id="currency-attribution">'
        f"<h3>Currency attribution{explainer}</h3>"
        f"<p><strong>{escape(universal)}</strong></p>"
        f"<p>{escape(headline)}</p>"
        + table_region(
            table_html,
            region_id=f"fx-attribution-{horizon.lower()}",
            label="Currency attribution components",
        )
        + f'<p class="hint">{escape(period)}</p>'
        "</div>"
    )


# ---------------------------------------------------------------------------
# Cost position and downside record card (Feature B UI)
# ---------------------------------------------------------------------------

def format_hit_evidence(row: pd.Series, *, hit_noun: str, window_noun: str) -> str:
    """The ONE evidence sentence for every counted-hit metric on this page.

    "N large falls in M qualifying weak-gold weeks" — the persisted counts read
    verbatim, never a rate re-expressed as a count. Both the cost/downside card
    and the Market-behaviour relative record render through this, so the two can
    never word the same evidence differently.
    """

    hits = row.get("hit_count")
    count = row.get("eligible_observation_count")
    return (
        f"{'' if hits is None or pd.isna(hits) else int(hits)} {hit_noun} in "
        f"{'' if count is None or pd.isna(count) else int(count)} {window_noun}"
    )


def format_evidence_period(row: pd.Series) -> str:
    """"Period <start> to <end>" from the persisted evidence window."""

    return (
        f"Period {_fmt_date(row.get('source_period_start'))} to "
        f"{_fmt_date(row.get('source_period_end'))}"
    )


_DOWNSIDE_CAVEAT = (
    "Current reported AISC is compared with historical share-price behavior in "
    "today's surviving eligible universe. The association does not establish "
    "causation."
)


def render_cost_downside_card(
    *,
    ticker: str,
    aisc_row: pd.Series | None,
    downside_row: pd.Series | None,
    aisc_peers: pd.DataFrame,
    downside_peers: pd.DataFrame,
) -> str:
    """The open 'Cost position and downside record' card (Market Behaviour).

    Two pieces of evidence side by side — no composite score, no causation.
    Peer scatter behind a closed disclosure with its accessible table twin.
    """

    explainer = help_icon(
        "Cost position and downside record", key="ticker_cost_downside", app_config=None
    )
    pieces: list[str] = [
        '<section class="panel" id="cost-downside">',
        f"<h2>Cost position and downside record{explainer}</h2>",
    ]

    # -- current reported AISC ------------------------------------------------
    if aisc_row is not None and bool(aisc_row.get("metric_available")):
        aisc_value = aisc_row.get("raw_value")
        aisc_text = (
            "n/a" if aisc_value is None or pd.isna(aisc_value) else f"${float(aisc_value):,.0f}/oz"
        )
        verification = str(aisc_row.get("source_verification_status") or "").strip()
        verification_date = str(aisc_row.get("source_verification_date") or "").strip()
        source_bits = [str(aisc_row.get("basis") or "")]
        if verification:
            source_bits.append(
                f"verification: {verification}"
                + (f" ({verification_date})" if verification_date else "")
            )
        low_good_pct = aisc_row.get("pct_low_good")
        standing = (
            f"Lower-cost than {_fmt_share(pd.NA) if low_good_pct is None or pd.isna(low_good_pct) else f'{float(low_good_pct):.0f}%'} "
            "of eligible producers."
            if low_good_pct is not None and not pd.isna(low_good_pct)
            else "Peer standing unavailable."
        )
        pieces.append(
            "<div class=\"cost-downside-aisc\"><h3>Current reported AISC"
            + help_icon("Current reported AISC", key="tool_b_aisc", app_config=None)
            + "</h3>"
            f"<p><strong>{escape(aisc_text)}</strong> · {escape(' · '.join(bit for bit in source_bits if bit))}</p>"
            f"<p class=\"hint\">{escape(standing)}</p></div>"
        )
    else:
        reason = (
            str(aisc_row.get("metric_reason")) if aisc_row is not None else "no AISC row"
        )
        pieces.append(
            "<div class=\"cost-downside-aisc\"><h3>Current reported AISC"
            + help_icon("Current reported AISC", key="tool_b_aisc", app_config=None)
            + "</h3>"
            f"<p class=\"hint\">AISC is unavailable: {escape(reason)}</p></div>"
        )

    # -- historical large-fall record -----------------------------------------
    if downside_row is not None and bool(downside_row.get("metric_available")):
        rate = downside_row.get("raw_value")
        period_start = downside_row.get("source_period_start")
        period_end = downside_row.get("source_period_end")
        evidence = format_hit_evidence(
            downside_row,
            hit_noun="large falls",
            window_noun="qualifying weak-gold weeks",
        )
        low_good_pct = downside_row.get("pct_low_good")
        standing = (
            f"A lower large-fall rate than {float(low_good_pct):.0f}% of eligible producers."
            if low_good_pct is not None and not pd.isna(low_good_pct)
            else "Peer standing unavailable."
        )
        pieces.append(
            "<div class=\"cost-downside-record\"><h3>Historical large-fall record"
            + help_icon(
                "Historical large-fall record",
                key="ticker_downside_hit_rate",
                app_config=None,
            )
            + "</h3>"
            f"<p><strong>{_fmt_pct(rate)}</strong> — {escape(evidence)}</p>"
            f"<p class=\"hint\">Period {_fmt_date(period_start)} to {_fmt_date(period_end)}. "
            "A large fall is an ordinary weekly price return of −10% or worse during a week "
            "in gold's rolling weakest 20%.</p>"
            f"<p class=\"hint\">{escape(standing)}</p></div>"
        )
    else:
        reason = (
            str(downside_row.get("metric_reason"))
            if downside_row is not None
            else "no downside row"
        )
        pieces.append(
            "<div class=\"cost-downside-record\"><h3>Historical large-fall record"
            + help_icon(
                "Historical large-fall record",
                key="ticker_downside_hit_rate",
                app_config=None,
            )
            + "</h3>"
            f"<p class=\"hint\">The downside record is unavailable: {escape(reason)}</p></div>"
        )

    # -- peer relationship disclosure -----------------------------------------
    pieces.append(_render_peer_disclosure(ticker=ticker, aisc_peers=aisc_peers, downside_peers=downside_peers))
    pieces.append(f'<p class="hint">{escape(_DOWNSIDE_CAVEAT)}</p>')
    pieces.append("</section>")
    return "".join(pieces)


def _render_peer_disclosure(
    *, ticker: str, aisc_peers: pd.DataFrame, downside_peers: pd.DataFrame
) -> str:
    """Closed disclosure: AISC (x) vs large-fall rate (y) scatter for eligible

    paired producers + the accessible table twin. Pure pairing of persisted
    rows — the serve layer computes no correlation, cohort statistic, or
    eligibility rule (those live in the model layer or nowhere).
    """

    peer_help = help_icon(
        "Peer relationship", key="ticker_peer_relationship", app_config=None
    )
    pairs: list[tuple[str, float, float]] = []
    if (
        aisc_peers is not None
        and downside_peers is not None
        and not aisc_peers.empty
        and not downside_peers.empty
    ):
        aisc_by_ticker = {
            str(row["ticker"]): row
            for _, row in aisc_peers.iterrows()
            if bool(row.get("metric_available")) and not pd.isna(row.get("raw_value"))
        }
        for _, row in downside_peers.iterrows():
            peer = str(row["ticker"])
            if peer not in aisc_by_ticker:
                continue
            if not bool(row.get("metric_available")) or pd.isna(row.get("raw_value")):
                continue
            pairs.append(
                (
                    peer,
                    float(aisc_by_ticker[peer]["raw_value"]),
                    float(row["raw_value"]),
                )
            )

    if not pairs:
        return (
            f'<details class="disclosure"><summary>Peer relationship{peer_help}</summary>'
            '<p class="hint">No eligible paired producers to plot.</p></details>'
        )

    table_rows = "".join(
        (
            "<tr"
            + (' class="is-selected"' if peer == str(ticker).upper() else "")
            + f"><td>{escape(peer)}</td><td>${aisc_value:,.0f}/oz</td>"
            + f"<td>{aisc_rate * 100:.1f}%</td></tr>"
        )
        for peer, aisc_value, aisc_rate in sorted(pairs)
    )
    table_html = (
        '<table class="compact-table"><thead><tr>'
        "<th scope=\"col\">Ticker</th><th scope=\"col\">Reported AISC</th>"
        "<th scope=\"col\">Large-fall rate</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table>"
    )
    scatter = _build_scatter_svg(
        x_values=[value for _, value, _ in pairs],
        y_values=[value for _, _, value in pairs],
        regression_beta=None,
        regression_alpha=None,
    )
    return (
        f'<details class="disclosure"><summary>Peer relationship{peer_help}</summary>'
        '<p class="hint">x = current reported AISC · y = historical large-fall rate · '
        "eligible paired producers only · no fitted line</p>"
        + scatter
        + table_region(
            table_html,
            region_id="cost-downside-peers",
            label="AISC vs large-fall rate peers",
        )
        + "</details>"
    )
