"""Detail-panel rendering helpers for the workspace ticker page."""

from __future__ import annotations

import re
from datetime import datetime, time, timezone
from html import escape
from typing import Any
from urllib.parse import quote

import pandas as pd

from golden_vector.common.eligibility import is_score_eligible
from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.disclosures import (
    TOOL_A_BETA_FORMULA,
)
from golden_vector.hedge.option_trading import OptionSizingResult, OptionTradingDetailData
from golden_vector.hedge.options_liquidity import bucket_label, slot_tier_counts
from golden_vector.hedge.scenarios import scenario_model_note
from golden_vector.model.structural import build_trailing_window_rows
from golden_vector.serve.charts import (
    _build_beta_history_svg,
    _build_dual_bar_svg,
    _build_scatter_svg,
)
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _is_na,
    _metric_card,
    _optional_float,
    _render_small_table,
    format_dte_suffix as _dte_suffix,
)
from golden_vector.serve.column_help import help_term, help_th
from golden_vector.serve.model_state_banner import render_option_freshness_box
from golden_vector.serve.option_signal_charts import render_option_signal_charts
from golden_vector.serve.option_signal_render import (
    format_vol_points,
    option_signal_skew_display_value,
    option_signal_skew_hover,
    render_option_signal_badge,
    signal_horizon_from_row,
)
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD,
    DETAIL_ALIGNMENT_FOUNDATION_MISSING,
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH,
    StructuralHistoryLoad,
    ToolADetailState,
    _STRUCTURAL_WINDOWS,
    _WINDOW_WEEKS,
    _structural_history_matches_tool_a,
)

def _sizing_query_parts(sizing_request: object | None) -> list[str]:
    """Serialize the option sizing request into URL query parts so window-tab
    navigation preserves the user's calculator state (audit L3). Only meaningful,
    non-default values are emitted to keep URLs clean."""

    if sizing_request is None:
        return []
    parts: list[str] = []
    side = str(getattr(sizing_request, "side", "") or "").strip()
    if side and side != "put":  # "put" is the default landing side; omit it
        parts.append(f"side={quote(side, safe='')}")
    if getattr(sizing_request, "horizon_explicit", False):
        parts.append(f"horizon={int(getattr(sizing_request, 'horizon_days', 0))}")
    bucket = getattr(sizing_request, "bucket", None)
    if bucket:
        parts.append(f"bucket={quote(str(bucket), safe='')}")
    if getattr(sizing_request, "size_explicit", False):
        size_mode = str(getattr(sizing_request, "size_mode", "") or "").strip()
        if size_mode == "budget":
            parts.append("size_mode=budget")
            budget = getattr(sizing_request, "budget", None)
            if budget is not None:
                parts.append(f"budget={quote(f'{float(budget):g}', safe='')}")
        elif size_mode == "contracts":
            quantity = getattr(sizing_request, "quantity", None)
            if quantity is not None:
                parts.append(f"quantity={int(quantity)}")
    return parts


def _render_window_switcher(
    *,
    ticker: str,
    active: str,
    canonical: str,
    lens: str | None = None,
    anchor: str | None = None,
    sizing_request: object | None = None,
) -> str:
    """Three-tab switcher at the top of the detail page: 6M / 12M / 3Y.

    Clicking a tab navigates to the same ticker with `?window=<id>`. Optional
    lens/anchor values keep tool-specific detail views stable while the user
    switches structural windows; sizing_request preserves the Option Trading
    calculator state (side/horizon/bucket/size_mode/quantity/budget).
    """
    tabs: list[str] = []
    base = f"/ticker/{quote(str(ticker), safe='')}"
    lens_value = str(lens or "").strip()
    anchor_value = str(anchor or "").strip()
    sizing_parts = _sizing_query_parts(sizing_request)
    for window in _STRUCTURAL_WINDOWS:
        is_active = window == active
        is_canonical = window == canonical
        cls = "window-tab active" if is_active else "window-tab"
        query_parts = []
        if window != canonical:
            query_parts.append(f"window={window.lower()}")
        if lens_value:
            query_parts.append(f"lens={quote(lens_value, safe='')}")
        query_parts.extend(sizing_parts)
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        fragment = f"#{quote(anchor_value, safe='')}" if anchor_value else ""
        href = f"{base}{query}{fragment}"
        canonical_marker = (
            " <span class=\"window-canonical\">anchor</span>" if is_canonical else ""
        )
        tabs.append(
            f"<a class=\"{cls}\" href=\"{escape(href, quote=True)}\">{escape(window)}{canonical_marker}</a>"
        )
    mismatch_note = ""
    if active != canonical:
        mismatch_note = (
            f"<p class=\"hint window-mismatch\">Viewing {escape(active)} — canonical anchor for "
            f"this ticker is {escape(canonical)}. Cross-window aggregates (Confidence, Gold Sensitivity "
            "Score, Profile) are unchanged.</p>"
        )
    return (
        "<section class=\"panel window-switcher\">"
        "<div class=\"window-tabs\">"
        + "".join(tabs)
        + "</div>"
        + mismatch_note
        + "</section>"
    )


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


def _render_detail_alignment_notice(alignment: str) -> str:
    if alignment == DETAIL_ALIGNMENT_ALIGNED:
        return ""
    messages = {
        DETAIL_ALIGNMENT_FOUNDATION_AHEAD: (
            "The current foundation snapshot has moved ahead of the published Gold Sensitivity row. "
            "Foundation-backed panels below are suppressed to avoid mixing data from different refreshes. "
            "Re-run <code>python main.py tool-a</code> to realign."
        ),
        DETAIL_ALIGNMENT_FOUNDATION_MISSING: (
            "No validated foundation snapshot is available for provenance alignment. "
            "Run <code>python main.py update-data</code>, then <code>python main.py tool-a</code>."
        ),
        DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: (
            "The published Gold Sensitivity row does not carry a snapshot refresh identifier, "
            "so provenance cannot be confirmed. Re-run <code>python main.py tool-a</code>."
        ),
    }
    return f"<div class=\"flash\"><p>{messages[alignment]}</p></div>"


def _render_suppressed_panel(title: str, reason: str, command: str) -> str:
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Out of Sync</h3>"
        f"<p>{reason}</p>"
        f"<p class=\"hint\">Run <code>{escape(command)}</code> to realign.</p>"
        "</section>"
    )


def _render_latest_panels(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_b_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
    app_config: AppConfig | None = None,
) -> str:
    return (
        _render_tool_a_panel(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            visible_windows=visible_windows,
            app_config=app_config,
        )
        + "<div class=\"two-up\">"
        f"{_render_small_table('Latest Corporate Finance Snapshot', tool_b_row, ['as_of_date', 'gold_price_assumption', 'fundamental_check_summary', 'fundamental_check_rank', 'screening_verdict', 'confidence', 'share_price_usd', 'market_cap_musd', 'cash_margin_usd_per_oz', 'margin_pct', 'fcf_yield', 'leverage', 'forward_pe', 'ev_ebitda', 'snapshot_refresh_run_id', 'snapshot_as_of_date', 'snapshot_normalization_status', 'fx_staleness_days'])}"
        "</div>"
    )


def _render_option_trading_link_panel(ticker: str) -> str:
    href = f"/ticker/{quote(str(ticker), safe='')}?lens=option-trading#option-trading"
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
    body.append(_render_option_candidate_matrix(detail))
    if detail.risk_free_rate_is_fallback:
        body.append(
            "<p class=\"hint\">Risk-free rate was missing from the options manifest; "
            "scenario values use a 0% rate fallback.</p>"
        )
    body.append(_render_option_sizing_calculator(detail))
    body.append(_render_option_proxy_fallback(detail))
    chain_detail = "".join(
        [
            _render_option_skew_overlay(detail),
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
            "Tradable rows passed stricter spread and open-interest checks. Watch rows "
            "passed one relaxed check and can be expensive to enter or exit.</p>"
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


def _render_option_skew_overlay(detail: OptionTradingDetailData) -> str:
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
        "<table><thead><tr><th>Horizon</th><th>Name</th><th>Sector</th><th>Residual</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _activity_text(signal: dict[str, object]) -> str:
    put_ratio = _optional_float(signal.get("volume_to_oi_put"))
    call_ratio = _optional_float(signal.get("volume_to_oi_call"))
    put = "-" if put_ratio is None else f"P {_fmt_percent(put_ratio, decimals=0)}"
    call = "-" if call_ratio is None else f"C {_fmt_percent(call_ratio, decimals=0)}"
    return f"{put} / {call}"


def _render_option_proxy_fallback(detail: OptionTradingDetailData) -> str:
    if not detail.proxy_fallbacks and not detail.proxy_fallback_note:
        return ""
    rows = []
    for fallback in detail.proxy_fallbacks:
        candidate = fallback.candidate
        href = (
            f"/ticker/{quote(fallback.ticker, safe='')}?lens=option-trading"
            f"&side={quote(fallback.side, safe='')}&horizon={fallback.horizon_days}"
            f"&bucket={quote(str(candidate.bucket or ''), safe='')}#option-sizing"
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
        table = (
            "<table><thead><tr>"
            "<th>Vehicle</th><th>Candidate</th><th>Expiry / DTE</th>"
            "<th>Strike</th><th>Mid</th><th>Spread</th><th>OI</th><th>Basis Risk</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
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
    return f"<div class=\"flash option-context-warning\">{paragraphs}</div>"


def _render_option_trading_context_table(detail: OptionTradingDetailData) -> str:
    context = detail.source_context
    stock_price = _option_panel_stock_price(detail)
    risk_free_rate = (
        context.risk_free_rate
        if context is not None and context.risk_free_rate is not None
        else None
    )
    risk_free_label = _fmt_percent(risk_free_rate, decimals=2)
    if detail.risk_free_rate_is_fallback or (
        context is not None and context.risk_free_rate_is_fallback
    ):
        risk_free_label = f"{risk_free_label} fallback"
    source = (
        context.source_label
        if context is not None
        else "Cached Yahoo Finance data via yfinance"
    )
    snapshot_date = context.as_of_date if context is not None else None
    refresh_run = context.refresh_run_id if context is not None else None
    return (
        "<table><tbody>"
        "<tr><th>Stock Price</th>"
        f"<td>{_fmt_number(stock_price, decimals=2)}</td></tr>"
        "<tr><th>Option Snapshot Date</th>"
        f"<td>{_fmt_text(snapshot_date)}</td></tr>"
        "<tr><th>Source</th>"
        f"<td>{escape(source)}</td></tr>"
        "<tr><th>Risk-Free Rate</th>"
        f"<td>{risk_free_label}</td></tr>"
        "<tr><th>Run</th>"
        f"<td>{_fmt_text(refresh_run)}</td></tr>"
        "</tbody></table>"
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


def _render_option_candidate_matrix(detail: OptionTradingDetailData) -> str:
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
        f"{_render_option_candidate_side_section('Puts', put_slots, ticker=detail.ticker)}"
        f"{_render_option_candidate_side_section('Calls', call_slots, ticker=detail.ticker)}"
        "</section>"
    )


def _render_option_candidate_side_section(
    title: str,
    slots: list[OptionCandidateSlot],
    *,
    ticker: str,
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
            f"<th colspan=\"7\">{header}</th>"
            "</tr>"
        )
        for slot in grouped[horizon]:
            rows.append(_render_option_candidate_matrix_row(slot=slot, ticker=ticker))
    return (
        "<section class=\"option-side-candidates\">"
        f"<h4>{escape(title)}</h4>"
        "<table>"
        "<thead><tr>"
        "<th>Candidate</th><th>Strike &middot; Expiry (DTE)</th>"
        f"{help_th('Delta', key='option_candidate_delta')}"
        "<th>Mid</th><th>Spread</th><th>Liquidity</th><th>Actions</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
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
) -> str:
    bucket_value = quote(str(bucket or ""), safe="")
    href = (
        f"/ticker/{quote(ticker, safe='')}?lens=option-trading"
        f"&side={quote(side, safe='')}&horizon={horizon_days}"
        f"&bucket={bucket_value}#option-sizing"
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


def _render_option_sizing_calculator(detail: OptionTradingDetailData) -> str:
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
        "<table>"
        "<thead><tr><th>Gold Move</th><th>Modeled Stock</th>"
        f"{help_th('P&L/share Now', key='option_scenario_pnl')}"
        f"{help_th('P&L/share Expiry', key='option_scenario_pnl')}"
        "<th>Net P&amp;L Now</th><th>Net P&amp;L Expiry</th>"
        "<th>Model Note</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def _render_tool_a_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
    app_config: AppConfig | None = None,
) -> str:
    if not tool_a_row:
        message = "No latest Gold Sensitivity output is available yet."
        if tool_a_detail.foundation_error:
            message += f" {escape(tool_a_detail.foundation_error)}"
        return (
            "<section class=\"panel\">"
            "<h2>Gold Sensitivity</h2>"
            f"<p>{message}</p>"
            "</section>"
        )

    win = active_window.lower()
    scoring_config = app_config.scoring if app_config is not None else None
    volatility_diag = _compute_window_volatility(
        tool_a_row=tool_a_row,
        active_window=active_window,
        weekly_series=tool_a_detail.weekly_series,
        scoring_config=scoring_config,
    )
    vol_context_display = volatility_diag.get("volatility_context") or tool_a_row.get("volatility_context")

    body = [
        "<section class=\"panel\">",
        "<h2>Gold Sensitivity</h2>",
        "<p class=\"hint\">Gold Sensitivity uses weekly structural delta, regime-split gamma, explicit asymmetry, "
        "confidence, and volatility diagnostics. "
        f"{TOOL_A_BETA_FORMULA} The horizon-return ladder below is exploratory only.</p>",
        _render_signal_notice(tool_a_row),
        _render_detail_alignment_notice(alignment),
        _render_structural_metrics_load_notice(tool_a_detail.structural_metrics_load),
        # Window-specific metrics (recompute with switcher).
        f"<h3>Active window: {escape(active_window)}</h3>",
        "<div class=\"metric-grid\">",
        _metric_card("As Of", _fmt_text(tool_a_row.get("as_of_date"))),
        _metric_card(f"Structural Delta ({active_window})", _fmt_number(tool_a_row.get(f"structural_delta_{win}"), decimals=2)),
        _metric_card(f"Gamma Down-Up ({active_window})", _fmt_number(tool_a_row.get(f"gamma_{win}"), decimals=2)),
        _metric_card(f"Asymmetry ({active_window})", _fmt_number(tool_a_row.get(f"asymmetry_ratio_{win}"), decimals=2)),
        _metric_card(f"R² ({active_window})", _fmt_percent(tool_a_row.get(f"r_squared_{win}"), decimals=1)),
        _metric_card(f"Weeks ({active_window})", _fmt_number(tool_a_row.get(f"weeks_{win}"), decimals=0)),
        _metric_card(f"Volatility Context ({active_window})", _fmt_text(vol_context_display)),
        "</div>",
        # Aggregate (cross-window) metrics — stable regardless of switcher.
        "<h3>Aggregate across all windows</h3>",
        "<div class=\"metric-grid\">",
        _metric_card("Confidence", _fmt_text(tool_a_row.get("confidence_label"))),
        _metric_card("Gold Sensitivity Score", _fmt_number(tool_a_row.get("tool_a_score"), decimals=1)),
        _metric_card("Profile", _fmt_text(tool_a_row.get("profile_label"))),
        _metric_card("Canonical Anchor", _fmt_text(tool_a_row.get("anchor_window_id"))),
        "</div>",
        _render_explanation_cards(
            tool_a_row,
            active_window=active_window,
            scoring_config=scoring_config,
            volatility_diag=volatility_diag,
        ),
        _render_structural_window_table(tool_a_row, active_window=active_window),
        _render_visual_panels(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            visible_windows=visible_windows,
            scoring_config=scoring_config,
        ),
        "</section>",
    ]
    return "".join(body)


def _render_structural_metrics_load_notice(
    metrics_load: "StructuralHistoryLoad",
) -> str:
    """Surface a corrupt or missing structural-metrics file at the page level.

    Codex follow-up to Fix #5: previously, `_load_published_structural_metrics` swallowed
    parquet read errors silently, so a corrupted file would show "Could not read" inside
    the chart panel but silently degrade the scatter / up-down panels. Now every consumer
    sees one consistent file-health story.
    """
    if metrics_load.status == "ok":
        return ""
    if metrics_load.status == "missing":
        message = (
            "Structural metrics file is missing. The scatter, up/down beta, and "
            "structural windows panels below cannot draw their anchor metrics. "
            "Run <code>python main.py tool-a</code> to generate it."
        )
    elif metrics_load.status == "corrupt":
        detail = (
            f" Underlying error: {escape(metrics_load.error_message)}"
            if metrics_load.error_message
            else ""
        )
        message = (
            "Could not read the structural metrics file." + detail
            + " Re-run <code>python main.py tool-a</code> to regenerate it."
        )
    elif metrics_load.status == "no_rows":
        message = (
            "Structural metrics file exists but has no rows for this ticker. "
            "Re-run <code>python main.py tool-a</code> after a fresh data refresh."
        )
    else:
        return ""
    return f"<div class=\"flash\"><p>{message}</p></div>"


def _render_signal_notice(tool_a_row: dict[str, Any]) -> str:
    score_eligible = is_score_eligible(tool_a_row.get("score_eligible"))
    score_reason = str(tool_a_row.get("score_eligibility_reason") or "").strip()
    normalization_issue_summary = _fmt_text(tool_a_row.get("normalization_issue_summary"))
    notices: list[str] = []
    if not score_eligible:
        if score_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
            notices.append(
                "Gold Sensitivity score is withheld because trailing FX or return-basis issues block a trustworthy structural read."
            )
        elif score_reason:
            notices.append(
                f"Gold Sensitivity score is currently withheld: {escape(score_reason.replace('_', ' ').title())}."
            )
    if normalization_issue_summary != "-":
        notices.append(f"Observed normalization issues in the trailing sample: {normalization_issue_summary}.")
    if not notices:
        return ""
    return (
        "<div class=\"flash\">"
        + "".join(f"<p>{notice}</p>" for notice in notices)
        + "</div>"
    )


def _render_explanation_cards(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
    scoring_config: Any = None,
    volatility_diag: dict[str, Any] | None = None,
) -> str:
    """Render the 7 narrative cards for the active window.

    Reuses `golden_vector/model/explanations.py` so we have ONE source of
    truth for narrative semantics across the pipeline and the workspace
    (per Codex's horizon-plan review). The pipeline bakes explanations
    for the ticker's canonical anchor; the workspace regenerates them
    live using the active window's numbers.
    """
    cards = _build_active_window_explanations(
        tool_a_row=tool_a_row,
        active_window=active_window,
        scoring_config=scoring_config,
        volatility_diag=volatility_diag or {},
    )
    return (
        "<div class=\"explanation-grid\">"
        + "".join(
            "<article class=\"panel explanation-card\">"
            f"<h3>{escape(title)}</h3><p>{_fmt_text(text)}</p>"
            "</article>"
            for title, text in cards
        )
        + "</div>"
    )


def _build_active_window_explanations(
    *,
    tool_a_row: dict[str, Any],
    active_window: str,
    scoring_config: Any,
    volatility_diag: dict[str, Any],
) -> list[tuple[str, str]]:
    """Call each model/explanations.py builder with the active window's
    numeric inputs. Returns ordered (title, text) tuples.
    """
    from golden_vector.model.explanations import (
        build_asymmetry_explanation,
        build_confidence_explanation,
        build_delta_explanation,
        build_gamma_explanation,
        build_interaction_explanation,
        build_summary_explanation,
        build_volatility_explanation,
    )
    win = active_window.lower()
    anchor_delta = _optional_float(tool_a_row.get(f"structural_delta_{win}"))
    anchor_gamma = _optional_float(tool_a_row.get(f"gamma_{win}"))
    anchor_up_beta = _optional_float(tool_a_row.get(f"up_beta_{win}"))
    anchor_down_beta = _optional_float(tool_a_row.get(f"down_beta_{win}"))
    anchor_asym = _optional_float(tool_a_row.get(f"asymmetry_ratio_{win}"))

    # Aggregate (cross-window) values used by some builders.
    structural_delta_core = _optional_float(tool_a_row.get("structural_delta_core"))
    asymmetry_core = _optional_float(tool_a_row.get("asymmetry_ratio_core"))
    structural_gamma_core = _optional_float(tool_a_row.get("structural_gamma_core"))
    score_eligible = is_score_eligible(tool_a_row.get("score_eligible"))
    score_eligibility_reason = str(tool_a_row.get("score_eligibility_reason") or "").strip()
    profile_label = str(tool_a_row.get("profile_label") or "").strip().upper()
    confidence_label = str(tool_a_row.get("confidence_label") or "").strip().upper()
    confidence_score = _optional_float(tool_a_row.get("confidence_score"))
    # Volatility fields: prefer the active-window values from the
    # workspace recompute; fall back to pipeline-published 52w fields.
    # None-checks (not truthiness): a legitimate 0.0 must not fall through.
    vol_context = (
        volatility_diag.get("volatility_context")
        or str(tool_a_row.get("volatility_context") or "").strip().upper()
    )
    diag_residual = volatility_diag.get("residual_volatility")
    residual_vol = (
        diag_residual
        if diag_residual is not None
        else tool_a_row.get("residual_volatility_52w")
    )
    diag_downside = volatility_diag.get("downside_volatility")
    downside_vol = (
        diag_downside
        if diag_downside is not None
        else tool_a_row.get("downside_volatility_52w")
    )

    delta_text = build_delta_explanation(
        anchor_delta=anchor_delta,
        anchor_window_id=active_window,
        structural_delta_core=structural_delta_core,
        score_eligible=score_eligible,
        score_eligibility_reason=score_eligibility_reason,
        scoring_config=scoring_config,
    )
    gamma_text = build_gamma_explanation(
        gamma_core=anchor_gamma,
        up_beta_anchor=anchor_up_beta,
        down_beta_anchor=anchor_down_beta,
        anchor_window_id=active_window,
        score_eligible=score_eligible,
        score_eligibility_reason=score_eligibility_reason,
        scoring_config=scoring_config,
    )
    asymmetry_text = build_asymmetry_explanation(
        asymmetry_ratio_anchor=anchor_asym,
        up_beta_anchor=anchor_up_beta,
        down_beta_anchor=anchor_down_beta,
        score_eligibility_reason=score_eligibility_reason,
        scoring_config=scoring_config,
    )
    volatility_text = build_volatility_explanation(
        volatility_context=vol_context,
        residual_volatility_52w=residual_vol,
        downside_volatility_52w=downside_vol,
    )
    confidence_text = build_confidence_explanation(
        confidence_label=confidence_label,
        confidence_score=confidence_score,
        score_eligibility_reason=score_eligibility_reason,
    )
    interaction_text = build_interaction_explanation(
        score_eligible=score_eligible,
        score_eligibility_reason=score_eligibility_reason,
        profile_label=profile_label,
        structural_delta_core=structural_delta_core,
        structural_gamma_core=structural_gamma_core,
        asymmetry_ratio_core=asymmetry_core,
        volatility_context=vol_context,
        confidence_label=confidence_label,
        scoring_config=scoring_config,
    )
    summary_text = build_summary_explanation(
        profile_label=profile_label,
        confidence_label=confidence_label,
        score_eligibility_reason=score_eligibility_reason,
        interaction_explanation=interaction_text,
    )
    return [
        ("Delta", delta_text),
        ("Gamma", gamma_text),
        ("Asymmetry", asymmetry_text),
        ("Volatility", volatility_text),
        ("Confidence", confidence_text),
        ("Interaction", interaction_text),
        ("Summary", summary_text),
    ]


def _render_structural_window_table(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
) -> str:
    window_rows = []
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    for window_id in ("6M", "12M", "3Y"):
        normalized = window_id.lower()
        markers = []
        if window_id == anchor_window_id:
            markers.append("Anchor")
        if window_id == active_window:
            markers.append("Active")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        row_class = " class=\"active-row\"" if window_id == active_window else ""
        window_rows.append(
            f"<tr{row_class}>"
            f"<td>{window_id}{marker_text}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'structural_delta_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'gamma_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'up_beta_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'down_beta_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'asymmetry_ratio_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_percent(tool_a_row.get(f'r_squared_{normalized}'), decimals=1)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'weeks_{normalized}'), decimals=0)}</td>"
            f"<td>{_fmt_text(tool_a_row.get(f'window_status_{normalized}'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Official Structural Windows</h3>"
        "<table>"
        "<thead><tr><th>Window</th><th>Delta</th><th>Gamma</th><th>Up Beta</th><th>Down Beta</th>"
        "<th>Asymmetry</th><th>R^2</th><th>Weeks</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(window_rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _render_visual_panels(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
    scoring_config: Any = None,
) -> str:
    if visible_windows is None:
        visible_windows = [active_window]
    # Alignment check fires first so every documented non-aligned state — including
    # FOUNDATION_MISSING, where load_latest_foundation_snapshot raises and sets
    # tool_a_detail.foundation_error — gets the per-panel suppressed-card treatment
    # promised by plan v3 §1, instead of falling through to a single generic error.
    if alignment != DETAIL_ALIGNMENT_ALIGNED:
        suppression_reasons = {
            DETAIL_ALIGNMENT_FOUNDATION_AHEAD: (
                "The foundation snapshot on disk differs from the published Gold Sensitivity row, so this panel is "
                "suppressed to avoid mixing data from different refreshes."
            ),
            DETAIL_ALIGNMENT_FOUNDATION_MISSING: (
                "No validated foundation snapshot is available, so this panel cannot be rebuilt safely "
                "from the published Gold Sensitivity row's refresh context."
            ),
            DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: (
                "The published Gold Sensitivity row does not carry a snapshot refresh identifier, so this panel "
                "cannot be matched to a foundation snapshot and is suppressed for safety."
            ),
        }
        suppression_commands = {
            DETAIL_ALIGNMENT_FOUNDATION_AHEAD: "python main.py tool-a",
            DETAIL_ALIGNMENT_FOUNDATION_MISSING: "python main.py update-data",
            DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: "python main.py tool-a",
        }
        reason = suppression_reasons.get(alignment, suppression_reasons[DETAIL_ALIGNMENT_FOUNDATION_AHEAD])
        command = suppression_commands.get(alignment, "python main.py tool-a")
        # The beta-history chart has its own provenance check (source_run_id).
        # It still renders when its own provenance is OK even if foundation is
        # misaligned. The rebased gold overlay was removed in the post-deep-review
        # fix pass, so there's nothing extra to suppress here.
        beta_history_panel = _render_beta_history_panel(
            ticker=ticker,
            tool_a_row=tool_a_row,
            structural_history_load=tool_a_detail.structural_history_load,
            active_window=active_window,
            visible_windows=visible_windows,
        )
        # Mirror the aligned branch's ordering (Fix #10 follow-up): chart sits
        # between the scatter row and the volatility row in BOTH branches so the
        # detail page has consistent visual rhythm regardless of alignment state.
        return (
            "<div class=\"two-up\">"
            + _render_suppressed_panel("Weekly Return Scatter", reason, command)
            + _render_suppressed_panel("Up vs Down Beta", reason, command)
            + "</div>"
            + beta_history_panel
            + "<div class=\"two-up\">"
            + _render_volatility_panel(
                tool_a_row,
                active_window=active_window,
                weekly_series=tool_a_detail.weekly_series,
                scoring_config=scoring_config,
            )
            + _render_suppressed_panel("Exploratory Horizon Ladder", reason, command)
            + "</div>"
        )
    if tool_a_detail.foundation_error:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Gold Sensitivity Detail</h3>"
            f"<p>{escape(tool_a_detail.foundation_error)}</p>"
            "</section>"
        )
    # Use the active window's metrics + sample (not the ticker's canonical anchor).
    active_metric = _active_window_metric(tool_a_detail, active_window)
    active_sample = _active_window_sample(tool_a_row, tool_a_detail, active_window)
    # Rolling chart now shows all three windows as separate lines;
    # structural_history_load provides the full per-window history.
    beta_history_panel = _render_beta_history_panel(
        ticker=ticker,
        tool_a_row=tool_a_row,
        structural_history_load=tool_a_detail.structural_history_load,
        active_window=active_window,
        visible_windows=visible_windows,
    )
    # Chart placement (post-deep-review): the rolling-delta chart is the most
    # paper-aligned visual on the detail page, so it sits immediately under the
    # scatter / up-down-beta row, above the volatility and exploratory panels.
    return (
        "<div class=\"two-up\">"
        f"{_render_scatter_panel(ticker=ticker, tool_a_row=tool_a_row, anchor_metric=active_metric, anchor_sample=active_sample, active_window=active_window)}"
        f"{_render_up_down_beta_panel(tool_a_row, anchor_metric=active_metric, active_window=active_window)}"
        "</div>"
        f"{beta_history_panel}"
        "<div class=\"two-up\">"
        f"{_render_volatility_panel(tool_a_row, active_window=active_window, weekly_series=tool_a_detail.weekly_series, scoring_config=scoring_config)}"
        f"{_render_exploratory_horizon_panel(tool_a_detail.exploratory_horizons)}"
        "</div>"
    )


def _active_window_metric(
    tool_a_detail: ToolADetailState,
    active_window: str,
) -> dict[str, Any]:
    """Return the structural_window_metrics row for the active window.

    Replaces _anchor_window_metric which keyed on the ticker's canonical
    anchor. Looking up by active_window lets the scatter + beta-bar
    panels follow the switcher.
    """
    metrics = tool_a_detail.structural_window_metrics
    if metrics.empty or not active_window:
        return {}
    matches = metrics.loc[
        metrics["window_id"].astype(str).str.upper().eq(active_window.upper())
    ]
    if matches.empty:
        return {}
    return matches.sort_values("as_of_date").iloc[-1].to_dict()


def _active_window_sample(
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    active_window: str,
) -> pd.DataFrame:
    """Trailing weekly-returns sample for the active window."""
    if not active_window or tool_a_detail.weekly_series.empty:
        return pd.DataFrame()
    as_of_date = pd.to_datetime(tool_a_row.get("as_of_date"), errors="coerce")
    if pd.isna(as_of_date):
        return pd.DataFrame()
    return build_trailing_window_rows(
        weekly_series=tool_a_detail.weekly_series,
        as_of_date=pd.Timestamp(as_of_date),
        window_id=active_window,
    )


def _anchor_window_metric(
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
) -> dict[str, Any]:
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    metrics = tool_a_detail.structural_window_metrics
    if not anchor_window_id or metrics.empty:
        return {}
    window_rows = metrics.loc[
        metrics["window_id"].astype(str).str.upper().eq(anchor_window_id)
    ].copy()
    if window_rows.empty:
        return {}
    return window_rows.sort_values("as_of_date").iloc[-1].to_dict()


def _anchor_window_sample(
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
) -> pd.DataFrame:
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    if not anchor_window_id or tool_a_detail.weekly_series.empty:
        return pd.DataFrame()
    as_of_date = pd.to_datetime(tool_a_row.get("as_of_date"), errors="coerce")
    if pd.isna(as_of_date):
        return pd.DataFrame()
    return build_trailing_window_rows(
        weekly_series=tool_a_detail.weekly_series,
        as_of_date=pd.Timestamp(as_of_date),
        window_id=anchor_window_id,
    )


def _render_scatter_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    anchor_metric: dict[str, Any],
    anchor_sample: pd.DataFrame,
    active_window: str = "12M",
) -> str:
    if anchor_sample.empty:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Weekly Return Scatter</h3>"
            f"<p>No weekly return detail is available yet for the {escape(active_window)} window.</p>"
            "</section>"
        )
    regression_beta = _optional_float(anchor_metric.get("structural_delta"))
    regression_alpha = _optional_float(anchor_metric.get("intercept_alpha"))
    svg = _build_scatter_svg(
        x_values=anchor_sample["gold_weekly_log_return"].tolist(),
        y_values=anchor_sample["stock_weekly_log_return"].tolist(),
        regression_beta=regression_beta,
        regression_alpha=regression_alpha,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Weekly Return Scatter</h3><p class=\"hint\">{escape(ticker)} weekly log returns vs gold weekly log returns over the {escape(active_window)} trailing sample.</p>"
        f"{svg}"
        "</section>"
    )


def _render_up_down_beta_panel(
    tool_a_row: dict[str, Any],
    *,
    anchor_metric: dict[str, Any],
    active_window: str = "12M",
) -> str:
    up_beta = _optional_float(anchor_metric.get("up_beta"))
    down_beta = _optional_float(anchor_metric.get("down_beta"))
    if up_beta is None and down_beta is None:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Up vs Down Beta</h3><p>No {escape(active_window)} regime split is available yet.</p>"
            "</section>"
        )
    svg = _build_dual_bar_svg(
        left_label="Up-Gold",
        left_value=up_beta or 0.0,
        right_label="Down-Gold",
        right_value=down_beta or 0.0,
    )
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Up vs Down Beta</h3>"
        f"<p class=\"hint\">This shows the {escape(active_window)} regime split. Positive gamma means down-gold sensitivity is stronger than up-gold sensitivity.</p>"
        f"{svg}"
        "</section>"
    )


def _render_volatility_panel(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
    weekly_series: pd.DataFrame | None = None,
    scoring_config: Any = None,
) -> str:
    """Render the volatility card group for the active window.

    When active_window is the ticker's canonical 52w basis (derived from
    the anchor-window selection baked into the pipeline), we show the
    pre-computed `*_52w` fields. When the user selects a non-canonical
    window, we recompute from the weekly_series slice. If the window
    isn't ELIGIBLE for that ticker, we show "not eligible" instead of
    rendering numbers built on thin observations.
    """
    window_status = _window_status(tool_a_row, active_window)
    # If the active window isn't ELIGIBLE, suppress numbers entirely.
    # Codex flagged in review: a structural page showing low-obs vol
    # with just a sample-size asterisk implies more trust than it should.
    if window_status != "ELIGIBLE":
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Volatility Diagnostics ({escape(active_window)})</h3>"
            f"<p class=\"hint\">The {escape(active_window)} window is not eligible for this ticker "
            f"(status: {escape(str(window_status))}). Volatility is not shown.</p>"
            "</section>"
        )

    diag = _compute_window_volatility(
        tool_a_row=tool_a_row,
        active_window=active_window,
        weekly_series=weekly_series,
        scoring_config=scoring_config,
    )
    context_label = diag.get("volatility_context") or "UNKNOWN"
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Volatility Diagnostics ({escape(active_window)})</h3>"
        "<div class=\"metric-grid\">"
        f"{_metric_card('Total Volatility (Annualized Log Vol)', _fmt_percent(diag.get('total_volatility'), decimals=1))}"
        f"{_metric_card('Residual Volatility (Annualized Log Vol)', _fmt_percent(diag.get('residual_volatility'), decimals=1))}"
        f"{_metric_card('Downside Volatility (Annualized Log Vol)', _fmt_percent(diag.get('downside_volatility'), decimals=1))}"
        f"{_metric_card('Volatility Context', _fmt_text(context_label))}"
        "</div>"
        "</section>"
    )


def _window_status(tool_a_row: dict[str, Any], window: str) -> str:
    """Extract the ELIGIBLE / INELIGIBLE_* status for a window."""
    key = f"window_status_{window.lower()}"
    raw = tool_a_row.get(key)
    if raw is None:
        return "UNKNOWN"
    try:
        if pd.isna(raw):
            return "UNKNOWN"
    except TypeError:
        pass
    return str(raw).strip().upper() or "UNKNOWN"


def _compute_window_volatility(
    *,
    tool_a_row: dict[str, Any],
    active_window: str,
    weekly_series: pd.DataFrame | None,
    scoring_config: Any,
) -> dict[str, Any]:
    """Compute total/residual/downside volatility for the active window.

    If the active window matches the pipeline's canonical 52w basis
    (volatility_anchor_window_id), we reuse the pre-computed values to
    avoid tiny floating-point drift. Otherwise we recompute from the
    weekly_series slice.
    """
    anchor_win_raw = tool_a_row.get("volatility_anchor_window_id")
    anchor_basis = (
        str(anchor_win_raw).strip().upper()
        if anchor_win_raw is not None and not _is_na(anchor_win_raw)
        else None
    )
    if anchor_basis == active_window and tool_a_row.get("total_volatility_52w") is not None:
        # Reuse pipeline-published numbers for the canonical window.
        return {
            "total_volatility": tool_a_row.get("total_volatility_52w"),
            "residual_volatility": tool_a_row.get("residual_volatility_52w"),
            "downside_volatility": tool_a_row.get("downside_volatility_52w"),
            "volatility_context": tool_a_row.get("volatility_context"),
        }

    # Non-canonical window: recompute from the window's weekly slice.
    if weekly_series is None or weekly_series.empty:
        return {}
    from golden_vector.model.structural import (
        annualize_weekly_volatility,
        annualize_downside_volatility,
    )
    weeks = _WINDOW_WEEKS.get(active_window, 52)
    ordered = weekly_series.sort_values("as_of_date").reset_index(drop=True)
    trailing = ordered.tail(weeks)
    stock_returns = pd.to_numeric(
        trailing.get("stock_weekly_log_return"), errors="coerce"
    )
    gold_returns = pd.to_numeric(
        trailing.get("gold_weekly_log_return"), errors="coerce"
    )
    total_vol = annualize_weekly_volatility(stock_returns)
    downside_vol = annualize_downside_volatility(stock_returns)
    # Residual vol needs the window's alpha + beta. The _latest row has
    # delta per window but not alpha per window — alpha lives in the
    # structural_window_metrics history. Approximate via OLS over the
    # trailing slice to keep things simple; drift vs the pipeline is tiny.
    residual_vol = None
    import numpy as np
    x = gold_returns.to_numpy(dtype=float)
    y = stock_returns.to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if len(x) >= 2 and x.std() > 0:
        beta_fit, alpha_fit = np.polyfit(x, y, 1)
        residual_vol = annualize_weekly_volatility(y - (alpha_fit + beta_fit * x))

    # Categorical context label: the ONE pipeline classifier. The previous
    # serve-side fork read a misspelled config attribute, swallowed the
    # AttributeError, and rendered UNKNOWN ("moderate" copy) for every
    # non-canonical window regardless of the data.
    from golden_vector.model.labels import determine_volatility_context

    if residual_vol is None or _is_na(residual_vol):
        context = "UNKNOWN"
    else:
        context = determine_volatility_context(
            total_volatility_52w=total_vol,
            residual_volatility_52w=residual_vol,
            downside_volatility_52w=downside_vol,
            scoring_config=scoring_config,
        )
    return {
        "total_volatility": total_vol,
        "residual_volatility": residual_vol,
        "downside_volatility": downside_vol,
        "volatility_context": context,
    }


def _render_exploratory_horizon_panel(exploratory_horizons: pd.DataFrame) -> str:
    if exploratory_horizons.empty:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Exploratory Horizon Ladder</h3>"
            "<p>No exploratory horizon data is available yet.</p>"
            "</section>"
        )
    rows = []
    for row in exploratory_horizons.sort_values(["horizon_value", "horizon_unit"]).itertuples(index=False):
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.horizon_id))}</td>"
            f"<td>{_fmt_percent(getattr(row, 'equity_return', None), decimals=1)}</td>"
            f"<td>{_fmt_percent(getattr(row, 'gold_return', None), decimals=1)}</td>"
            f"<td>{_fmt_number(getattr(row, 'gold_delta', None), decimals=2)}</td>"
            f"<td>{_fmt_text(getattr(row, 'coverage_flag', None))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Exploratory Horizon Ladder</h3>"
        "<p class=\"hint\">This preserves the older horizon-return lens for tactical context only. The ratio below is a single-period return ratio, not a structural beta, and it does not drive the Gold Sensitivity score.</p>"
        "<table>"
        "<thead><tr><th>Horizon</th><th>Equity Return</th><th>Gold Return</th><th>Single-Period Ratio</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
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

    Invalid / missing params fall back to the ticker's canonical anchor.
    Case-insensitive.
    """
    normalized = str(raw_param or "").strip().upper()
    if normalized in _STRUCTURAL_WINDOWS:
        return normalized
    return canonical_anchor if canonical_anchor in _STRUCTURAL_WINDOWS else "12M"


def _resolve_visible_windows(raw_param: str, active_window: str) -> list[str]:
    """Map a URL `show=` value to an ordered list of windows to draw.

    The active window is always included — the switcher tab is the "primary"
    line the user picked, so hiding it would make the chart meaningless.
    Additional windows can be layered in via `?show=6m` or `?show=6m,3y`.
    Tokens are case-insensitive; invalid tokens are silently dropped.

    Return order mirrors `_STRUCTURAL_WINDOWS` so the legend is always
    displayed 6M / 12M / 3Y regardless of what the user clicked first.
    """
    tokens = {
        token.strip().upper()
        for token in str(raw_param or "").split(",")
        if token.strip()
    }
    tokens.add(active_window.upper())
    return [window for window in _STRUCTURAL_WINDOWS if window.upper() in tokens]


def _render_beta_history_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    structural_history_load: "StructuralHistoryLoad",
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
) -> str:
    """Render the rolling structural-delta panel with one line per window.

    Per plan v3 §5 and the post-deep-review fix pass:
    - The chart uses only ``source_run_id`` for its provenance gate. The rebased
      gold overlay was removed because it wasn't numerically interpretable.
    - The four empty states are now distinguished by the structured load result
      (missing / corrupt / no_rows / ok), not by checking ``DataFrame.empty`` alone.
    - The horizon-switcher version draws 6M / 12M / 3Y as three lines on one shared
      y-axis; the active window is thicker and fully opaque, the other two muted.
    """

    title = "Rolling Structural Delta"

    if structural_history_load.status == "missing":
        return _render_chart_unavailable_panel(
            title,
            "Structural history file has not been generated yet. "
            "Run <code>python main.py tool-a</code> to generate it.",
        )

    if structural_history_load.status == "corrupt":
        detail = (
            f" Underlying error: {escape(structural_history_load.error_message)}"
            if structural_history_load.error_message
            else ""
        )
        return _render_chart_unavailable_panel(
            title,
            "Could not read the structural history file."
            + detail
            + " Re-run <code>python main.py tool-a</code> to regenerate it.",
        )

    structural_history = structural_history_load.history

    if structural_history is None or structural_history.empty:
        return _render_chart_unavailable_panel(
            title,
            "This ticker does not have enough clean structural history to plot yet. "
            "Run <code>python main.py tool-a</code> after a fresh data refresh.",
        )

    if not _structural_history_matches_tool_a(structural_history, tool_a_row):
        return _render_chart_fallback_panel(
            title,
            "Structural history file is out of sync with the published Gold Sensitivity row.",
            "python main.py tool-a",
        )

    # Split the combined history back into per-window (dates, deltas) tuples.
    series_by_window: dict[str, tuple[list[pd.Timestamp], list[float]]] = {}
    window_series = structural_history["window_id"].astype(str).str.upper()
    for window_id in _STRUCTURAL_WINDOWS:
        mask = window_series == window_id.upper()
        slice_df = structural_history.loc[mask].copy()
        if slice_df.empty:
            continue
        slice_df = slice_df.sort_values("as_of_date")
        series_by_window[window_id] = (
            list(slice_df["as_of_date"]),
            slice_df["structural_delta"].astype(float).tolist(),
        )

    if not series_by_window:
        return _render_chart_unavailable_panel(
            title,
            "This ticker does not have enough clean structural history in any window to plot yet. "
            "Run <code>python main.py tool-a</code> after a fresh data refresh.",
        )

    current_delta_core = _optional_float(tool_a_row.get("structural_delta_core"))
    score_eligible = is_score_eligible(tool_a_row.get("score_eligible"))
    watermark = ""
    if not score_eligible:
        watermark = (
            "<p class=\"hint\"><em>Current snapshot score for this stock is withheld; "
            "historical series shown for context only.</em></p>"
        )

    # Default: only the active window's line is drawn. The user opts-in to
    # additional windows by clicking their legend items (which toggle via the
    # `?show=` URL param).
    if visible_windows is None:
        visible_windows = [active_window]

    svg = _build_beta_history_svg(
        series_by_window=series_by_window,
        active_window=active_window,
        visible_windows=visible_windows,
        current_delta_core=current_delta_core,
        ticker=ticker,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)}</h3>"
        f"<p class=\"hint\">How {escape(ticker)}'s weekly structural beta to gold has moved over time, "
        f"with the {escape(active_window)} window highlighted. Click a window below to add or remove its line. "
        "Drawn from <code>tool_a_structural_latest.parquet</code>.</p>"
        f"{watermark}{svg}"
        "</section>"
    )


def _render_chart_fallback_panel(title: str, reason: str, command: str) -> str:
    """Out-of-sync (provenance mismatch) fallback panel. Reserved for the
    source_run_id mismatch case so the 'Out of Sync' wording is unambiguous.
    """
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Out of Sync</h3>"
        f"<p>{reason}</p>"
        f"<p class=\"hint\">Run <code>{escape(command)}</code> to realign.</p>"
        "</section>"
    )


def _render_chart_unavailable_panel(title: str, reason_html: str) -> str:
    """Generic "not available yet" panel used when the structural file is missing
    or has no eligible rows for this ticker. Distinct from the out-of-sync state.
    """
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Not Available Yet</h3>"
        f"<p>{reason_html}</p>"
        "</section>"
    )
