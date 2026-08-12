"""Detail-panel rendering helpers for the workspace ticker page."""

from __future__ import annotations

import re
from datetime import datetime, time, timezone
from html import escape
from typing import Any, Mapping
from urllib.parse import quote

import pandas as pd

from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_trading import OptionSizingResult, OptionTradingDetailData
from golden_vector.hedge.options_liquidity import bucket_label, slot_tier_counts
from golden_vector.hedge.scenarios import scenario_model_note
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _metric_card,
    _optional_float,
    format_dte_suffix as _dte_suffix,
)
from golden_vector.serve.column_help import help_term, help_th
from golden_vector.serve.fundamentals_provenance import (
    ticker_provenance_icon,
)
from golden_vector.serve.model_state_banner import render_option_freshness_box
from golden_vector.serve.option_signal_charts import render_option_signal_charts
from golden_vector.serve.option_signal_render import (
    format_vol_points,
    option_signal_skew_display_value,
    option_signal_skew_hover,
    render_option_signal_badge,
    signal_horizon_from_row,
)
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD,
    DETAIL_ALIGNMENT_FOUNDATION_MISSING,
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH,
    _STRUCTURAL_WINDOWS,
)
from golden_vector.common.windows import resolve_window_or_none


def _detail_alignment(
    tool_a_row: dict[str, Any],
    foundation_manifest: dict[str, Any] | None,
) -> str:
    """Decide whether the foundation-backed detail panels can render safely.

    Returns one of the DETAIL_ALIGNMENT_* constants. ALIGNED means the Tool A
    row and the current foundation manifest reference the same refresh run id.
    """

    if not foundation_manifest:
        return DETAIL_ALIGNMENT_FOUNDATION_MISSING
    foundation_refresh = str(foundation_manifest.get("refresh_run_id") or "").strip()
    if not foundation_refresh:
        return DETAIL_ALIGNMENT_FOUNDATION_MISSING
    tool_a_refresh = str(tool_a_row.get("snapshot_refresh_run_id") or "").strip()
    if not tool_a_refresh or tool_a_refresh.lower() == "nan":
        return DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH
    if tool_a_refresh != foundation_refresh:
        return DETAIL_ALIGNMENT_FOUNDATION_AHEAD
    return DETAIL_ALIGNMENT_ALIGNED


def _render_financials_source_switcher(
    *,
    ticker: str,
    financials_source: str,
    query_params: Mapping[str, str],
    fundamentals_provenance: dict[tuple[str, str], str],
) -> str:
    source = str(financials_source or "our").strip().lower()
    source = "yahoo" if source == "yahoo" else "our"
    base_path = f"/ticker/{quote(str(ticker), safe='')}"
    our_href = build_page_url(
        base_path,
        query_params,
        set_params={"fundamentals_source": None},
    )
    yahoo_href = build_page_url(
        base_path,
        query_params,
        set_params={"fundamentals_source": "yahoo"},
    )
    our_class = "button-like active" if source == "our" else "button-like"
    yahoo_class = "button-like active" if source == "yahoo" else "button-like"
    hint = (
        "<p class=\"hint\">Yahoo Fundamentals changes dual-source financial "
        "fields and derived checks; mining assumptions remain Our View.</p>"
        if source == "yahoo"
        else ""
    )
    icon = ticker_provenance_icon(ticker, fundamentals_provenance) if source == "yahoo" else ""
    return (
        "<div class=\"overview-filters-actions source-switcher\">"
        f"<span class=\"hint\">Financials source</span>"
        f"<a class=\"{our_class}\" href=\"{escape(our_href, quote=True)}\">Our View</a>"
        f"<a class=\"{yahoo_class}\" href=\"{escape(yahoo_href, quote=True)}\">Yahoo Fundamentals</a>"
        f"{icon}"
        "</div>"
        f"{hint}"
    )


def _render_option_trading_link_panel(
    ticker: str,
    *,
    financials_source: str = "our",
    active_window: str | None = None,
    canonical_anchor: str | None = None,
) -> str:
    # Preserve the selected horizon so opening the lens never silently reverts to the
    # canonical anchor. Mirror the window switcher: the param is omitted only for the
    # canonical default (which needs no ?window=), and carried for every other window.
    extra_params: dict[str, str] = {}
    if (
        active_window
        and canonical_anchor
        and str(active_window).upper() != str(canonical_anchor).upper()
    ):
        extra_params["window"] = str(active_window).lower()
    href = (
        build_page_url(
            f"/ticker/{quote(str(ticker), safe='')}",
            {},
            set_params=_source_set_params(
                financials_source,
                lens="option-trading",
                **extra_params,
            ),
        )
        + "#option-trading"
    )
    return (
        "<section id=\"option-trading\" class=\"panel\">"
        "<h2>Option Trading</h2>"
        "<p class=\"hint\">The full Option Trading lens loads Hedge Readiness "
        "optionable put candidates plus call context only when opened.</p>"
        f"<p><a href=\"{escape(href, quote=True)}\">Open Option Trading for "
        f"{escape(str(ticker))}</a></p>"
        "</section>"
    )


def _render_option_trading_panel(
    detail: OptionTradingDetailData | None,
    *,
    model_state_manifest: dict[str, object] | None = None,
    app_config: AppConfig | None = None,
    financials_source: str = "our",
    active_window: str | None = None,
    canonical_anchor: str | None = None,
) -> str:
    body = [
        "<section id=\"option-trading\" class=\"panel\">",
        "<h2>Option Trading</h2>",
        render_option_freshness_box(model_state_manifest),
    ]
    if detail is None:
        body.append(
            "<p>No option-trading data is available yet. Run "
            "<code>python main.py refresh</code> to refresh the model data.</p>"
        )
        body.append("</section>")
        return "".join(body)
    if detail.row is None:
        reason = detail.reason or "This ticker is not optionable in the latest snapshot."
        body.append(f"<p>{escape(reason)}</p>")
        body.append("</section>")
        return "".join(body)

    row = detail.row
    snapshot_date = (
        detail.source_context.as_of_date
        if detail.source_context is not None
        else None
    )
    body.append(
        "<p class=\"hint\">"
        f"Cached options snapshot: {_fmt_text(snapshot_date)}; screening only - live prices may differ."
        "</p>"
    )
    body.append(_render_option_context_warnings(detail.source_context))
    body.append(_render_option_signal_card(detail))
    # Hero: the tradable candidates, then the sizing calculator for a selected
    # contract. Everything else is reference detail, collapsed below.
    body.append(
        _render_option_candidate_matrix(
            detail,
            app_config=app_config,
            financials_source=financials_source,
        )
    )
    if detail.risk_free_rate_is_fallback:
        body.append(
            "<p class=\"hint\">Risk-free rate was missing from the options manifest; "
            "scenario values use a 0% rate fallback.</p>"
        )
    body.append(
        _render_option_sizing_calculator(
            detail,
            financials_source=financials_source,
            active_window=active_window,
            canonical_anchor=canonical_anchor,
        )
    )
    body.append(_render_option_proxy_fallback(detail, financials_source=financials_source))
    chain_detail = "".join(
        [
            _render_option_skew_overlay(detail, app_config=app_config),
            render_option_signal_charts(
                detail.skew_curve_points,
                detail.oi_strike_points,
                detail.signal_history_points,
                signal_horizon_days=signal_horizon_from_row(detail.signal_row),
                underlying_price=_option_panel_stock_price(detail),
            ),
            _render_option_trading_context_table(detail),
            _render_option_liquidity_summary(detail),
            "<details class=\"method-disclosure\"><summary>Method</summary>"
            "<p>Contracts are selected during refresh from cached Yahoo Finance "
            "option-chain artifacts. "
            "Tradable rows passed the stricter spread and open-interest checks. Watch rows "
            "passed the relaxed checks and can be expensive to enter or exit.</p>"
            "<p>Open interest is existing open contracts. Volume is today's trading. "
            "Spread is ask minus bid divided by mid; lower is usually better.</p>"
            "</details>",
            "<details class=\"method-disclosure\"><summary>Glossary</summary>"
            "<p>Bid is the price buyers currently show. Ask is the price sellers show. "
            "Mid is the midpoint of bid and ask. Last is the most recent reported trade, "
            "not necessarily executable now. Delta is shown as context, not as the bucket rule.</p>"
            "</details>",
        ]
    )
    body.append(
        "<details class=\"option-chain-detail\">"
        "<summary>Show chain detail (skew curve, open interest by strike, liquidity, method)</summary>"
        f"{chain_detail}"
        "</details>"
    )
    if row.notes:
        notes = "".join(f"<li>{escape(note)}</li>" for note in row.notes)
        body.append(f"<ul class=\"hint\">{notes}</ul>")
    body.append("</section>")
    return "".join(body)


def _render_option_signal_card(detail: OptionTradingDetailData) -> str:
    signal = detail.signal_row or {}
    if not signal:
        return (
            "<section class=\"nested-panel\">"
            "<h3>Option Signal</h3>"
            "<p class=\"hint\">No persisted option signal is available yet. Run "
            "<code>python main.py refresh</code> after the signal migration.</p>"
            "</section>"
        )
    lanes = (
        (
            "Direction",
            signal.get("direction_label"),
            signal.get("direction_reason"),
            format_vol_points(option_signal_skew_display_value(signal)),
            option_signal_skew_hover(signal),
        ),
        (
            "Activity",
            signal.get("activity_label"),
            signal.get("activity_reason"),
            _activity_text(signal),
            None,
        ),
        (
            "Option Cost Signal",
            signal.get("cost_label"),
            signal.get("cost_reason"),
            _fmt_number(signal.get("iv_rv_ratio"), decimals=2),
            None,
        ),
        (
            "Option Signal Quality",
            signal.get("data_quality_label"),
            signal.get("data_quality_reason"),
            _fmt_percent(signal.get("signal_area_quote_coverage"), decimals=0),
            None,
        ),
    )
    lane_html = []
    for title, label, reason, value, hover in lanes:
        value_text = str(value or "-")
        value_html = help_term(value_text, text=hover) if hover else escape(value_text)
        lane_html.append(
            "<article class=\"option-signal-lane\">"
            f"<h4>{escape(title)}</h4>"
            f"<p>{render_option_signal_badge(label)} <strong>{value_html}</strong></p>"
            f"<p class=\"hint\">{_fmt_text(reason)}</p>"
            "</article>"
        )
    headline = _fmt_text(signal.get("headline"))
    return (
        "<section class=\"nested-panel option-signal-card\">"
        "<h3>Option Signal</h3>"
        f"<p>{headline}</p>"
        f"<div class=\"option-signal-grid\">{''.join(lane_html)}</div>"
        "</section>"
    )


def _signal_row_horizons(signal: dict[str, object]) -> list[int]:
    """Horizons the persisted signal row actually carries (config-driven)."""

    horizons = set()
    for key in signal:
        match = re.match(r"^name_skew_(\d+)d$", str(key))
        if match is not None:
            horizons.add(int(match.group(1)))
    return sorted(horizons)


def _render_option_skew_overlay(
    detail: OptionTradingDetailData, *, app_config: AppConfig | None = None
) -> str:
    signal = detail.signal_row or {}
    if not signal:
        return ""
    rows = []
    for horizon in _signal_row_horizons(signal):
        rows.append(
            "<tr>"
            f"<td>{horizon}d</td>"
            f"<td>{format_vol_points(signal.get(f'name_skew_{horizon}d'))}</td>"
            f"<td>{format_vol_points(signal.get(f'sector_skew_{horizon}d'))}</td>"
            f"<td>{format_vol_points(signal.get(f'skew_residual_{horizon}d'))}</td>"
            "</tr>"
        )
    benchmark = _fmt_text(signal.get("benchmark_symbol"))
    return (
        "<section class=\"nested-panel\">"
        f"<h3>Name vs Sector 25-Delta Skew ({benchmark})</h3>"
        + table_region(
            "<table><thead><tr>"
            + help_th("Horizon", key="option_signal_horizon")
            + help_th("Name", key="option_name_skew")
            + help_th("Sector", key="option_sector_skew")
            + help_th("Residual", key="skew_vs_benchmark", app_config=app_config)
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="detail-skew-table-region",
            label="Name vs sector 25-delta skew",
        )
        + "</section>"
    )


def _activity_text(signal: dict[str, object]) -> str:
    put_ratio = _optional_float(signal.get("volume_to_oi_put"))
    call_ratio = _optional_float(signal.get("volume_to_oi_call"))
    put = "-" if put_ratio is None else f"P {_fmt_percent(put_ratio, decimals=0)}"
    call = "-" if call_ratio is None else f"C {_fmt_percent(call_ratio, decimals=0)}"
    return f"{put} / {call}"


def _render_option_proxy_fallback(
    detail: OptionTradingDetailData,
    *,
    financials_source: str = "our",
) -> str:
    if not detail.proxy_fallbacks and not detail.proxy_fallback_note:
        return ""
    rows = []
    for fallback in detail.proxy_fallbacks:
        candidate = fallback.candidate
        href = (
            build_page_url(
                f"/ticker/{quote(fallback.ticker, safe='')}",
                {},
                set_params=_source_set_params(
                    financials_source,
                    lens="option-trading",
                    side=fallback.side,
                    horizon=str(fallback.horizon_days),
                    bucket=str(candidate.bucket or ""),
                ),
            )
            + "#option-sizing"
        )
        rows.append(
            "<tr>"
            f"<td><a href=\"{escape(href, quote=True)}\">{escape(fallback.ticker)}</a></td>"
            f"<td>{escape(fallback.side.title())} {escape(bucket_label(candidate.bucket))}</td>"
            f"<td>{_fmt_text(candidate.expiration)}{_dte_suffix(candidate.days_to_expiry)}</td>"
            f"<td>{_fmt_number(candidate.strike, decimals=2)}</td>"
            f"<td>{_fmt_number(candidate.mid, decimals=2)}</td>"
            f"<td>{_fmt_percent(candidate.rel_spread, decimals=1)}</td>"
            f"<td>{_fmt_number(candidate.open_interest, decimals=0)}</td>"
            f"<td>{escape(fallback.reason)}</td>"
            "</tr>"
        )
    note = ""
    if detail.proxy_fallback_note:
        note = f"<p class=\"hint\">{escape(detail.proxy_fallback_note)}</p>"
    table = ""
    if rows:
        table = table_region(
            "<table><thead><tr>"
            + help_th("Vehicle", key="ticker_symbol")
            + help_th("Candidate", key="option_candidate_label")
            + help_th("Expiry / DTE", key="option_expiry_dte")
            + help_th("Strike", key="option_strike")
            + help_th("Mid", key="option_mid_price")
            + help_th("Spread", key="option_rel_spread")
            + help_th("OI", key="option_open_interest")
            + help_th("Basis Risk", key="option_proxy_basis_risk")
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="detail-vehicles-table-region",
            label="ETF proxy alternatives",
        )
    heading = "ETF Proxy Alternatives" if rows else "ETF Proxy Check"
    intro = (
        "Shown only when the selected single-name contract is missing and cached "
        "GDX/GDXJ liquidity supports showing a sector proxy. These are not "
        f"{escape(detail.ticker)} contracts and do not track it one-for-one."
        if rows
        else (
            "Checked because the selected single-name contract is missing. "
            "Proxy alternatives remain hidden unless cached GDX/GDXJ liquidity "
            "supports showing a sector proxy."
        )
    )
    return (
        "<section class=\"nested-panel option-proxy-fallback\">"
        f"<h3>{heading}</h3>"
        f"<p class=\"hint\">{intro}</p>"
        f"{note}{table}"
        "</section>"
    )


def _render_option_context_warnings(context: object | None) -> str:
    warnings = tuple(getattr(context, "context_warnings", ()) or ())
    if not warnings:
        return ""
    paragraphs = "".join(f"<p>{escape(str(warning))}</p>" for warning in warnings)
    return notice("warning", paragraphs)


def _render_option_trading_context_table(detail: OptionTradingDetailData) -> str:
    context = detail.source_context
    stock_price = _option_panel_stock_price(detail)
    risk_free_rate = (
        context.risk_free_rate
        if context is not None and context.risk_free_rate is not None
        else None
    )
    risk_free_label = _fmt_percent(risk_free_rate, decimals=2)
    is_fallback = detail.risk_free_rate_is_fallback or (
        context is not None and context.risk_free_rate_is_fallback
    )
    if is_fallback:
        # With no rate at all the label was the nonsense string "- fallback"; say
        # plainly that the rate is missing instead of qualifying an absent number.
        risk_free_label = (
            f"{risk_free_label} (fallback estimate)"
            if risk_free_rate is not None
            else "Not available"
        )
    source = (
        context.source_label
        if context is not None
        else "Cached Yahoo Finance data via yfinance"
    )
    snapshot_date = context.as_of_date if context is not None else None
    refresh_run = context.refresh_run_id if context is not None else None
    return table_region(
        "<table><tbody>"
        "<tr>"
        + help_th("Stock Price", key="option_stock_price", scope="row")
        + f"<td>{_fmt_number(stock_price, decimals=2)}</td></tr>"
        "<tr>"
        + help_th("Option Snapshot Date", key="option_snapshot_date", scope="row")
        + f"<td>{_fmt_text(snapshot_date)}</td></tr>"
        "<tr>"
        + help_th("Source", key="option_data_source", scope="row")
        + f"<td>{escape(source)}</td></tr>"
        "<tr>"
        + help_th("Risk-Free Rate", key="option_risk_free_rate", scope="row")
        + f"<td>{risk_free_label}</td></tr>"
        "<tr>"
        + help_th("Run", key="option_refresh_run", scope="row")
        + f"<td>{_fmt_text(refresh_run)}</td></tr>"
        "</tbody></table>",
        region_id="detail-option-context-table-region",
        label="Option data context",
    )


def _render_option_liquidity_summary(detail: OptionTradingDetailData) -> str:
    put_counts = slot_tier_counts(detail.put_slots)
    call_counts = slot_tier_counts(detail.call_slots)
    thin_note = ""
    total_slots = len(detail.put_slots) + len(detail.call_slots)
    tradable_slots = len(
        [
            slot
            for slot in (*detail.put_slots, *detail.call_slots)
            if slot.candidate is not None and slot.candidate.liquidity_tier == "tradable"
        ]
    )
    if total_slots and tradable_slots < max(1, total_slots // 4):
        thin_note = "<p class=\"hint\">Options look thin here; most buckets did not pass the Tradable gate.</p>"
    return (
        "<div class=\"metric-grid option-liquidity-summary\">"
        f"{_metric_card('Put Tradable', _fmt_number(put_counts['tradable'], decimals=0))}"
        f"{_metric_card('Put Watch', _fmt_number(put_counts['watch'], decimals=0))}"
        f"{_metric_card('Put No-trade', _fmt_number(put_counts['no_trade'], decimals=0))}"
        f"{_metric_card('Call Tradable', _fmt_number(call_counts['tradable'], decimals=0))}"
        f"{_metric_card('Call Watch', _fmt_number(call_counts['watch'], decimals=0))}"
        f"{_metric_card('Call No-trade', _fmt_number(call_counts['no_trade'], decimals=0))}"
        "</div>"
        f"{thin_note}"
    )


def _render_option_candidate_matrix(
    detail: OptionTradingDetailData,
    *,
    app_config: AppConfig | None = None,
    financials_source: str = "our",
) -> str:
    put_slots = _ordered_side_slots(detail.put_slots)
    call_slots = _ordered_side_slots(detail.call_slots)
    if not put_slots and not call_slots:
        return (
            "<section id=\"option-candidates\" class=\"nested-panel\">"
            "<h3>Option Candidates</h3>"
            "<p>No option candidate slots are available for this ticker.</p>"
            "</section>"
        )
    return (
        "<section id=\"option-candidates\" class=\"nested-panel\">"
        "<h3>Option Candidates</h3>"
        "<p class=\"hint\">Each side shows near-ATM and directional candidates around the "
        "configured target horizons. The bold row is the tradable near-ATM pick. Hover a "
        "candidate name for bid/ask, open interest, and volume.</p>"
        f"{_render_option_candidate_side_section('Puts', put_slots, ticker=detail.ticker, app_config=app_config, financials_source=financials_source)}"
        f"{_render_option_candidate_side_section('Calls', call_slots, ticker=detail.ticker, app_config=app_config, financials_source=financials_source)}"
        "</section>"
    )


def _render_option_candidate_side_section(
    title: str,
    slots: list[OptionCandidateSlot],
    *,
    ticker: str,
    app_config: AppConfig | None = None,
    financials_source: str = "our",
) -> str:
    if not slots:
        return (
            "<section class=\"option-side-candidates\">"
            f"<h4>{escape(title)}</h4>"
            f"<p>No {escape(title.lower())} candidate slots are available.</p>"
            "</section>"
        )
    rows = []
    grouped = _slots_by_horizon(tuple(slots))
    for horizon in sorted(grouped):
        expiration = next(
            (str(slot.expiration) for slot in grouped[horizon] if slot.expiration),
            None,
        )
        header = f"~{escape(str(horizon))}d target"
        if expiration:
            header += f" · expiry {escape(expiration)}"
        rows.append(
            "<tr class=\"option-horizon-row\">"
            f"<th colspan=\"7\" scope=\"colgroup\">{header}</th>"
            "</tr>"
        )
        for slot in grouped[horizon]:
            rows.append(
                _render_option_candidate_matrix_row(
                    slot=slot,
                    ticker=ticker,
                    financials_source=financials_source,
                )
            )
    return (
        "<section class=\"option-side-candidates\">"
        f"<h4>{escape(title)}</h4>"
        + table_region(
            "<table>"
            "<thead><tr>"
            + help_th("Candidate", key="option_candidate_label")
            + help_th("Strike · Expiry (DTE)", key="option_strike_expiry")
            + help_th("Delta", key="option_candidate_delta")
            + help_th("Mid", key="option_mid_price")
            + help_th("Spread", key="option_rel_spread")
            + help_th("Liquidity", key="option_candidate_status", app_config=app_config)
            + help_th("Actions", key="option_actions")
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>",
            region_id=f"detail-option-candidates-{title.strip().lower()}-table-region",
            label=f"{title} candidates",
        )
        + "</section>"
    )


def _ordered_side_slots(slots: tuple[OptionCandidateSlot, ...]) -> list[OptionCandidateSlot]:
    bucket_order = {"near_atm": 0, "directional": 1}
    return sorted(
        slots,
        key=lambda slot: (
            slot.horizon_days,
            bucket_order.get(str(slot.bucket or ""), 9),
        ),
    )


def _render_option_candidate_matrix_row(
    *,
    slot: OptionCandidateSlot,
    ticker: str,
    financials_source: str = "our",
) -> str:
    candidate = slot.candidate
    side = "put" if slot.option_type == "P" else "call"
    label = _candidate_slot_label(slot)
    yahoo_icon = _yahoo_chain_link(slot.ticker, slot.expiration)
    if candidate is None:
        label_html = help_term(label, text=slot.reason) if slot.reason else escape(label)
        return (
            "<tr>"
            f"<td>{label_html}</td>"
            f"<td>{_fmt_text(slot.expiration)}{_dte_suffix(slot.days_to_expiry)}</td>"
            "<td>-</td><td>-</td><td>-</td>"
            f"<td>{_tier_label(slot)}</td>"
            f"<td>{yahoo_icon}</td>"
            "</tr>"
        )
    select_link = (
        _contract_select_link(
            ticker=ticker,
            side=side,
            horizon_days=slot.horizon_days,
            bucket=slot.bucket,
            financials_source=financials_source,
        )
        if candidate.liquidity_tier == "tradable"
        else ""
    )
    actions = " ".join(part for part in (select_link, yahoo_icon) if part) or "-"
    depth = _candidate_depth_hover(candidate, _candidate_note(slot, candidate))
    label_html = help_term(label, text=depth)
    if slot.bucket == "near_atm" and candidate.liquidity_tier == "tradable":
        label_html = f"<strong>{label_html}</strong>"
    strike_exp = (
        f"{_fmt_number(candidate.strike, decimals=2)} &middot; "
        f"{_fmt_text(candidate.expiration)}{_dte_suffix(candidate.days_to_expiry)}"
    )
    return (
        "<tr>"
        f"<td>{label_html}</td>"
        f"<td>{strike_exp}</td>"
        f"<td>{_fmt_number(candidate.delta, decimals=2)}</td>"
        f"<td>{_fmt_number(candidate.mid, decimals=2)}</td>"
        f"<td>{_fmt_percent(candidate.rel_spread, decimals=1)}</td>"
        f"<td>{_tier_label(slot)}</td>"
        f"<td>{actions}</td>"
        "</tr>"
    )


def _candidate_depth_hover(candidate: OptionCandidate, note: str) -> str:
    """Bid/ask, open interest, and volume folded into the candidate-name hover."""

    text = (
        f"Bid {_fmt_number(candidate.bid, decimals=2)} / "
        f"Ask {_fmt_number(candidate.ask, decimals=2)} · "
        f"OI {_fmt_number(candidate.open_interest, decimals=0)} · "
        f"Volume {_fmt_number(candidate.volume, decimals=0)}"
    )
    if note:
        text = f"{text}\n{note}"
    return text


def _candidate_slot_label(slot: OptionCandidateSlot) -> str:
    side = "Put" if slot.option_type == "P" else "Call"
    return f"{side} {bucket_label(slot.bucket)}"


def _candidate_note(slot: OptionCandidateSlot, candidate: OptionCandidate) -> str:
    if candidate.liquidity_tier == "watch":
        return "Watch: wide spread, midpoint may be optimistic."
    if "lottery_like" in candidate.quote_flags:
        return "Lottery-like: high IV, short DTE, low delta."
    return slot.reason


def _slots_by_horizon(
    slots: tuple[OptionCandidateSlot, ...],
) -> dict[int, list[OptionCandidateSlot]]:
    grouped: dict[int, list[OptionCandidateSlot]] = {}
    for slot in slots:
        grouped.setdefault(slot.horizon_days, []).append(slot)
    return grouped


def _tier_label(slot: OptionCandidateSlot) -> str:
    candidate = slot.display_candidate
    tier = (
        candidate.liquidity_tier
        if candidate is not None and candidate.liquidity_tier is not None
        else slot.liquidity_tier
    )
    if tier == "tradable" and slot.candidate is not None:
        return '<span class="badge badge-verified">Tradable</span>'
    if tier == "watch":
        return '<span class="badge badge-estimated">Watch</span>'
    if tier == "no_trade":
        return '<span class="badge badge-missing">No-trade</span>'
    if slot.status == "accepted":
        return '<span class="badge badge-verified">Tradable</span>'
    return '<span class="badge badge-missing">No candidate</span>'


def _contract_select_link(
    *,
    ticker: str,
    side: str,
    horizon_days: int,
    bucket: str | None,
    financials_source: str = "our",
) -> str:
    href = (
        build_page_url(
            f"/ticker/{quote(ticker, safe='')}",
            {},
            set_params=_source_set_params(
                financials_source,
                lens="option-trading",
                side=side,
                horizon=str(horizon_days),
                bucket=str(bucket or ""),
            ),
        )
        + "#option-sizing"
    )
    return f"<a class=\"button-link\" href=\"{escape(href, quote=True)}\">Select</a>"


def _option_panel_stock_price(detail: OptionTradingDetailData) -> float | None:
    """Best available underlying price: the row's, else the first slot's."""

    price = detail.row.current_stock_price if detail.row is not None else None
    return price or _first_slot_stock_price((*detail.put_slots, *detail.call_slots))


def _first_slot_stock_price(slots: tuple[OptionCandidateSlot, ...]) -> float | None:
    for slot in slots:
        candidate = slot.display_candidate
        if candidate is not None and candidate.underlying_price > 0:
            return candidate.underlying_price
    return None


def _yahoo_chain_link(ticker: str, expiration: str | None) -> str:
    if not expiration:
        return "-"
    try:
        expiry_date = datetime.strptime(expiration, "%Y-%m-%d").date()
    except ValueError:
        return "-"
    expiry_epoch = int(
        datetime.combine(expiry_date, time.min, tzinfo=timezone.utc).timestamp()
    )
    href = (
        f"https://finance.yahoo.com/quote/{quote(ticker, safe='')}/options"
        f"?date={expiry_epoch}"
    )
    return (
        f"<a class=\"yahoo-chain-icon\" href=\"{escape(href, quote=True)}\" target=\"_blank\" "
        "rel=\"noopener noreferrer\" title=\"Open Yahoo option chain for this expiry\" "
        "aria-label=\"Open Yahoo option chain for this expiry\">&#8599;</a>"
    )


def _render_option_sizing_calculator(
    detail: OptionTradingDetailData,
    *,
    financials_source: str = "our",
    active_window: str | None = None,
    canonical_anchor: str | None = None,
) -> str:
    sizing = detail.sizing
    if sizing is None:
        return ""
    request = sizing.request
    budget_value = "" if request.budget is None else f"{request.budget:.2f}"
    side_options = "".join(
        f"<option value=\"{side}\"{' selected' if request.side == side else ''}>{label}</option>"
        for side, label in (("put", "Downside puts"), ("call", "Upside calls"))
    )
    horizons = sorted(
        {
            slot.horizon_days
            for slot in (*detail.put_slots, *detail.call_slots)
        }
        or {request.horizon_days}
    )
    # Label horizons with the actual listed expiry chosen for that window —
    # options expire on real dates, not on abstract "230d" targets.
    expirations_by_horizon: dict[int, str] = {}
    for slot in (*detail.put_slots, *detail.call_slots):
        if slot.expiration and slot.horizon_days not in expirations_by_horizon:
            expirations_by_horizon[slot.horizon_days] = str(slot.expiration)
    horizon_options = "".join(
        (
            f"<option value=\"{horizon}\""
            f"{' selected' if request.horizon_days == horizon else ''}>"
            f"{horizon}d"
            + (
                f" · {escape(expirations_by_horizon[horizon])}"
                if horizon in expirations_by_horizon
                else ""
            )
            + "</option>"
        )
        for horizon in horizons
    )
    bucket_options = _bucket_options_for_request(detail, request)
    mode_contracts_checked = " checked" if request.size_mode == "contracts" else ""
    mode_budget_checked = " checked" if request.size_mode == "budget" else ""
    notes = list(sizing.notes)
    result = _render_option_sizing_result(sizing)
    source_input = (
        "<input type=\"hidden\" name=\"fundamentals_source\" value=\"yahoo\">"
        if str(financials_source).strip().lower() == "yahoo"
        else ""
    )
    # Preserve the selected structural window across the GET recompute. Mirrors the
    # window switcher: the param is omitted for the canonical anchor, carried otherwise.
    window_input = (
        f"<input type=\"hidden\" name=\"window\" value=\"{escape(str(active_window).lower(), quote=True)}\">"
        if (
            active_window
            and canonical_anchor
            and str(active_window).upper() != str(canonical_anchor).upper()
        )
        else ""
    )
    notes_html = (
        "<ul class=\"hint\">"
        + "".join(f"<li>{escape(note)}</li>" for note in notes)
        + "</ul>"
        if notes
        else ""
    )
    return (
        "<section id=\"option-sizing\" class=\"nested-panel option-sizing-calculator\">"
        "<h3>Scenario Table and Sizing Calculator</h3>"
        "<p class=\"hint\">Uses cached per-contract scenarios. Live option quotes may differ.</p>"
        f"<form method=\"get\" action=\"/ticker/{quote(detail.ticker, safe='')}#option-sizing\" class=\"option-sizing-form\">"
        "<input type=\"hidden\" name=\"lens\" value=\"option-trading\">"
        f"{source_input}"
        f"{window_input}"
        "<label>Side "
        f"<select name=\"side\">{side_options}</select>"
        "</label>"
        "<label>Horizon "
        f"<select name=\"horizon\">{horizon_options}</select>"
        "</label>"
        "<label>Bucket "
        f"<select name=\"bucket\">{bucket_options}</select>"
        "</label>"
        "<label class=\"radio-label\"><input type=\"radio\" name=\"size_mode\" value=\"contracts\""
        f"{mode_contracts_checked}> Contracts</label>"
        "<label>Qty "
        f"<input type=\"number\" name=\"quantity\" min=\"1\" step=\"1\" value=\"{request.quantity}\">"
        "</label>"
        "<label class=\"radio-label\"><input type=\"radio\" name=\"size_mode\" value=\"budget\""
        f"{mode_budget_checked}> Budget</label>"
        "<label>$ "
        f"<input type=\"number\" name=\"budget\" min=\"0\" step=\"0.01\" value=\"{escape(budget_value)}\">"
        "</label>"
        "<button type=\"submit\">Recompute</button>"
        "</form>"
        f"{notes_html}{result}"
        "</section>"
    )


def _source_set_params(financials_source: str, **params: str) -> dict[str, str | None]:
    result: dict[str, str | None] = dict(params)
    if str(financials_source).strip().lower() == "yahoo":
        result["fundamentals_source"] = "yahoo"
    return result


def _bucket_options_for_request(
    detail: OptionTradingDetailData,
    request: Any,
) -> str:
    slots = detail.put_slots if request.side == "put" else detail.call_slots
    buckets = [
        slot.bucket
        for slot in slots
        if slot.horizon_days == request.horizon_days
        and slot.candidate is not None
        and slot.candidate.liquidity_tier == "tradable"
    ]
    if request.bucket and request.bucket not in buckets:
        buckets.append(request.bucket)
    if not buckets:
        return '<option value="">First available</option>'
    options = ['<option value="">First available</option>']
    seen: set[str] = set()
    for bucket in buckets:
        if bucket is None or bucket in seen:
            continue
        seen.add(bucket)
        selected = " selected" if request.bucket == bucket else ""
        options.append(
            f"<option value=\"{escape(bucket, quote=True)}\"{selected}>"
            f"{escape(bucket_label(bucket))}</option>"
        )
    return "".join(options)


def _render_option_sizing_result(sizing: OptionSizingResult) -> str:
    request = sizing.request
    label = "put" if request.side == "put" else "call"
    bucket_text = f" {bucket_label(request.bucket)}" if request.bucket else ""
    if sizing.bundle is None:
        return (
            "<p>"
            f"Selected: {escape(str(request.horizon_days))}d{escape(bucket_text)} {escape(label)}. "
            "No scenario table is available for this selection."
            "</p>"
        )
    bundle = sizing.bundle
    selected_bucket = bucket_label(bundle.candidate.bucket)
    watch_warning = (
        " Watch candidate: spread is wide, so midpoint pricing may be optimistic."
        if bundle.candidate.liquidity_tier == "watch"
        else ""
    )
    leftover = (
        f" Leftover cash: {_fmt_number(sizing.leftover_cash, decimals=2)}."
        if sizing.leftover_cash is not None
        else ""
    )
    spend = (
        f" Premium spend: {_fmt_number(sizing.premium_spend, decimals=2)}."
        if sizing.premium_spend is not None
        else ""
    )
    if bundle.skipped_reason or not bundle.rows:
        reason = bundle.skipped_reason or "No modeled sizing scenarios are available for this selection."
        return (
            "<div class=\"option-sizing-result\">"
            f"<p>Selected: {escape(bundle.horizon)} {escape(selected_bucket)} {escape(label)}. "
            f"Contracts: {sizing.contracts}.{spend}{leftover}{escape(watch_warning)}</p>"
            f"<p>{escape(reason)}</p>"
            "</div>"
        )
    rows = []
    for row in bundle.rows:
        model_note = scenario_model_note(row.gold_pct_change)
        rows.append(
            "<tr>"
            f"<td>{_fmt_percent(row.gold_pct_change, decimals=1)}</td>"
            f"<td>{_fmt_number(row.implied_stock_price, decimals=2)}</td>"
            f"<td>{_fmt_number(row.pnl_per_contract_if_closed_today, decimals=2)}</td>"
            f"<td>{_fmt_number(row.pnl_per_contract_at_expiry, decimals=2)}</td>"
            f"<td>{_fmt_number(row.net_pnl_if_closed_today, decimals=0)}</td>"
            f"<td>{_fmt_number(row.net_pnl_at_expiry, decimals=0)}</td>"
            f"<td>{escape(model_note) if model_note else ''}</td>"
            "</tr>"
        )
    return (
        "<div class=\"option-sizing-result\">"
        f"<p>Selected: {escape(bundle.horizon)} {escape(selected_bucket)} {escape(label)}. "
        f"Contracts: {sizing.contracts}.{spend}{leftover}{escape(watch_warning)}</p>"
        + table_region(
            "<table>"
            "<thead><tr>"
            + help_th("Gold Move", key="option_scenario_gold_move")
            + help_th("Modeled Stock", key="option_scenario_modeled_stock")
            + help_th("P&L/share Now", key="option_scenario_pnl")
            + help_th("P&L/share Expiry", key="option_scenario_pnl")
            + help_th("Net P&L Now", key="option_scenario_pnl")
            + help_th("Net P&L Expiry", key="option_scenario_pnl")
            + help_th("Model Note", key="option_scenario_model_note")
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>",
            region_id="detail-option-sizing-scenarios-table-region",
            label="Option sizing scenarios",
        )
        + "</div>"
    )


def _canonical_anchor_window(tool_a_row: dict[str, Any]) -> str:
    """Return the ticker's canonical anchor window id (always 6M / 12M / 3Y).

    Falls back to 12M when the field is missing or malformed so the
    detail page keeps working even on incomplete fixtures.
    """
    raw = tool_a_row.get("anchor_window_id") if tool_a_row else None
    if raw is None:
        return "12M"
    try:
        if pd.isna(raw):
            return "12M"
    except TypeError:
        pass
    normalized = str(raw).strip().upper()
    return normalized if normalized in _STRUCTURAL_WINDOWS else "12M"


def _resolve_active_window(raw_param: str, canonical_anchor: str) -> str:
    """Map a URL `window=` value to a valid structural window id.

    Recognises canonical ids AND display aliases via the registry (so `?window=1y`
    resolves to 12M, not the canonical anchor). Invalid / missing params fall back to
    the ticker's canonical anchor. Case-insensitive.
    """
    resolved = resolve_window_or_none(raw_param)
    if resolved is not None:
        return resolved
    return canonical_anchor if canonical_anchor in _STRUCTURAL_WINDOWS else "12M"


