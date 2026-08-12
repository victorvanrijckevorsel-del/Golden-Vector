"""Detail-panel rendering helpers for the workspace ticker page."""

from __future__ import annotations

import re
from datetime import datetime, time, timezone
from html import escape
from typing import Any, Mapping
from urllib.parse import quote

import numpy as np
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
    _STOCK_SERIES,
    _benchmark_series,
    _build_multiline_overlay_svg,
    _build_beta_strip_svg,
    _build_dual_bar_svg,
    _build_grouped_beta_bar_svg,
    _build_scatter_svg,
)
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _is_na,
    _metric_card,
    _optional_float,
    format_dte_suffix as _dte_suffix,
    id_token as _id_token,
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
    StructuralHistoryLoad,
    ToolADetailState,
    _STRUCTURAL_WINDOWS,
    _structural_history_matches_tool_a,
)
from golden_vector.common.strings import ordinal_percentile as _ordinal_percentile
from golden_vector.common.windows import resolve_window_or_none, window_label
from golden_vector.serve.windows import SCORING_WINDOWS, WINDOW_LABELS


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
    financials_source: str = "our",
) -> str:
    """Window switcher at the top of the detail page: all structural lookbacks
    (6M / 1Y / 2Y / 3Y / 5Y; 12M renders as "1Y"). Every descriptive metric below
    follows the selected tab; Score/Confidence/Profile are a cross-window summary.

    Clicking a tab navigates to the same ticker with `?window=<id>`. Optional
    lens/anchor values keep tool-specific detail views stable while the user
    switches structural windows; sizing_request preserves the Option Trading
    calculator state (side/horizon/bucket/size_mode/quantity/budget).
    """
    tabs: list[str] = []
    base = f"/ticker/{quote(str(ticker), safe='')}"
    lens_value = str(lens or "").strip()
    anchor_value = str(anchor or "").strip()
    source_value = str(financials_source or "our").strip().lower()
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
        if source_value == "yahoo":
            query_parts.append("fundamentals_source=yahoo")
        query_parts.extend(sizing_parts)
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        fragment = f"#{quote(anchor_value, safe='')}" if anchor_value else ""
        href = f"{base}{query}{fragment}"
        canonical_marker = (
            " <span class=\"window-canonical\">anchor</span>" if is_canonical else ""
        )
        tabs.append(
            f"<a class=\"{cls}\" href=\"{escape(href, quote=True)}\">"
            f"{escape(WINDOW_LABELS.get(window, window))}{canonical_marker}</a>"
        )
    mismatch_note = ""
    if active != canonical:
        mismatch_note = (
            f"<p class=\"hint window-mismatch\">Viewing {escape(WINDOW_LABELS.get(active, active))} — "
            f"canonical anchor for this ticker is {escape(WINDOW_LABELS.get(canonical, canonical))}. "
            "Cross-window aggregates (Confidence, Gold Sensitivity Score, Profile) are unchanged.</p>"
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
    return notice("warning", f"<p>{messages[alignment]}</p>")


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
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    app_config: AppConfig | None = None,
) -> str:
    """The Tool A (market behaviour) panel.

    M3b: the old "Latest Corporate Finance Snapshot" table that used to sit
    beside it is GONE, not moved — it carried `fundamental_check_summary`,
    `fundamental_check_rank`, `screening_verdict` and `confidence`, and the
    locked requirements (§3 "Verdicts and scores") ban every compiled verdict
    from this page. Corporate finance is now its own section rendered from the
    persisted gold-response artifact, and the financials-source switcher moved
    to the global control bar.
    """
    return _render_tool_a_panel(
        ticker=ticker,
        tool_a_row=tool_a_row,
        tool_a_detail=tool_a_detail,
        alignment=alignment,
        active_window=active_window,
        app_config=app_config,
    )


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


def _render_tool_a_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    app_config: AppConfig | None = None,
) -> str:
    if not tool_a_row:
        message = "No latest Gold Sensitivity output is available yet."
        if tool_a_detail.foundation_error:
            message += f" {escape(tool_a_detail.foundation_error)}"
        return (
            "<section id=\"gold-sensitivity\" class=\"panel\">"
            "<h2>Gold Sensitivity</h2>"
            f"<p>{message}</p>"
            "</section>"
        )

    win = active_window.lower()
    # Visible label uses the registry display name (12M -> "1Y") so the page never shows two
    # names for one horizon; the canonical id (`active_window` / `win`) stays for lookups.
    win_label = WINDOW_LABELS.get(active_window, active_window)
    scoring_config = app_config.scoring if app_config is not None else None
    volatility_diag = _compute_window_volatility(
        tool_a_row=tool_a_row,
        active_window=active_window,
        weekly_series=tool_a_detail.weekly_series,
        scoring_config=scoring_config,
    )
    # The metric-grid card must obey the SAME eligibility gate as the Volatility
    # Diagnostics panel below (item 3): an ineligible window shows "not eligible",
    # never a number/label built on thin observations. And when the per-window
    # recompute yields nothing we fall back to the PUBLISHED 52-week value — which
    # must be labelled with its true basis (item 4), exactly like the Interaction /
    # Summary cards, instead of hiding under the active window's name.
    active_window_status = _window_status(tool_a_row, active_window)
    if active_window_status != "ELIGIBLE":
        volatility_context_card = _metric_card(
            f"Volatility Context ({win_label})",
            f"Not eligible ({escape(str(active_window_status))})",
        )
    elif volatility_diag.get("volatility_context"):
        volatility_context_card = _metric_card(
            f"Volatility Context ({win_label})",
            _fmt_text(volatility_diag.get("volatility_context")),
        )
    else:
        volatility_context_card = _metric_card(
            "Volatility Context (52w, published)",
            _fmt_text(tool_a_row.get("volatility_context")),
        )

    # The narrative cards split by horizon-dependence: Delta/Gamma/Asymmetry/Volatility track
    # the selected window, while Confidence/Interaction/Summary are cross-window aggregates.
    # We render them under their matching heading so the "does not change with the horizon
    # switcher" hint can never apply to per-window prose (it sat under that hint before).
    explanation_cards = _build_active_window_explanations(
        tool_a_row=tool_a_row,
        active_window=active_window,
        scoring_config=scoring_config,
        volatility_diag=volatility_diag,
    )
    per_window_explanations = [
        card for card in explanation_cards if card[0] in _PER_WINDOW_EXPLANATION_TITLES
    ]
    cross_window_explanations = [
        card for card in explanation_cards if card[0] in _CROSS_WINDOW_EXPLANATION_TITLES
    ]

    body = [
        "<section id=\"gold-sensitivity\" class=\"panel\">",
        "<h2>Gold Sensitivity</h2>",
        "<p class=\"hint\">Gold Sensitivity uses weekly structural delta, regime-split gamma, explicit asymmetry, "
        "confidence, and volatility diagnostics. "
        f"{TOOL_A_BETA_FORMULA} The horizon-return ladder below is exploratory only.</p>",
        _render_signal_notice(tool_a_row),
        _render_detail_alignment_notice(alignment),
        _render_structural_metrics_load_notice(
            tool_a_detail.structural_metrics_load, tool_a_row=tool_a_row
        ),
        # Window-specific metrics (recompute with switcher).
        f"<h3>Active window: {escape(win_label)}</h3>",
        "<div class=\"metric-grid\">",
        _metric_card("As Of", _fmt_text(tool_a_row.get("as_of_date"))),
        _metric_card(f"Structural Delta ({win_label})", _fmt_number(tool_a_row.get(f"structural_delta_{win}"), decimals=2)),
        _metric_card(f"Gamma Down-Up ({win_label})", _fmt_number(tool_a_row.get(f"gamma_{win}"), decimals=2)),
        _metric_card(f"Asymmetry ({win_label})", _fmt_number(tool_a_row.get(f"asymmetry_ratio_{win}"), decimals=2)),
        _metric_card(f"R² ({win_label})", _fmt_percent(tool_a_row.get(f"r_squared_{win}"), decimals=1)),
        _metric_card(f"Weeks ({win_label})", _fmt_number(tool_a_row.get(f"weeks_{win}"), decimals=0)),
        volatility_context_card,
        "</div>",
        # Per-window narrative (tracks the switcher) sits under the active-window block, so the
        # cross-window "does not change" hint below can never be misread as applying to it.
        f"<p class=\"hint\">These read-outs describe the active window ({escape(win_label)}) and "
        "update when you switch the horizon above.</p>",
        _render_explanation_grid(per_window_explanations),
        # Cross-window summary — the Score/Confidence/Profile are computed ACROSS the
        # scoring windows (a robustness blend), NOT for the selected horizon, so they are
        # stable regardless of the switcher. Labelled explicitly so nothing reads as mixed:
        # the descriptive cards above are the selected window; these are the across-windows view.
        f"<h3>Across scoring windows ({' / '.join(WINDOW_LABELS[w] for w in SCORING_WINDOWS)})</h3>",
        "<p class=\"hint\">The Gold Sensitivity Score, Confidence, and Profile are computed "
        "across the scoring windows (a robustness blend) and do not change with the horizon "
        "switcher above. 2Y / 5Y are display-only lookbacks and are never scored.</p>",
        "<div class=\"metric-grid\">",
        _metric_card("Confidence", _fmt_text(tool_a_row.get("confidence_label"))),
        _metric_card("Gold Sensitivity Score", _fmt_number(tool_a_row.get("tool_a_score"), decimals=1)),
        _metric_card("Profile", _fmt_text(tool_a_row.get("profile_label"))),
        _metric_card(
            "Canonical Anchor",
            _fmt_text(window_label(tool_a_row.get("anchor_window_id"))),
        ),
        "</div>",
        _render_explanation_grid(cross_window_explanations),
        _render_structural_window_table(tool_a_row, active_window=active_window),
        _render_visual_panels(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            scoring_config=scoring_config,
            volatility_diag=volatility_diag,
        ),
        "</section>",
    ]
    return "".join(body)


def _render_structural_metrics_load_notice(
    metrics_load: "StructuralHistoryLoad",
    *,
    tool_a_row: dict[str, Any] | None = None,
) -> str:
    """Surface a corrupt / missing / out-of-sync structural-metrics file at the page level.

    Codex follow-up to Fix #5: previously, `_load_published_structural_metrics` swallowed
    parquet read errors silently, so a corrupted file would show "Could not read" inside
    the chart panel but silently degrade the scatter / up-down panels. Now every consumer
    sees one consistent file-health story.

    The price-overlay chart no longer carries the structural-file provenance gate it used to
    (it draws prices, not the scored betas). So the ``source_run_id`` mismatch check moved
    here: the scatter / up-down beta / structural-window panels below read these metrics, and
    a file from a different ``tool-a`` run must not be presented as the published row's betas.
    """
    if metrics_load.status == "ok":
        if tool_a_row is not None and not _structural_history_matches_tool_a(
            metrics_load.history, tool_a_row
        ):
            message = (
                "Structural metrics file is out of sync with the published Gold Sensitivity row "
                "(produced by a different tool-a run). The scatter, up/down beta, and structural "
                "windows panels below may not match the headline row. "
                "Re-run <code>python main.py tool-a</code> to realign."
            )
            return notice("warning", f"<p>{message}</p>")
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
    return notice("warning", f"<p>{message}</p>")


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
    return notice("warning", "".join(f"<p>{item}</p>" for item in notices))


# Narrative cards split by horizon-dependence. Delta/Gamma/Asymmetry/Volatility are computed
# from the ACTIVE window's numbers (they track the switcher); Confidence/Interaction/Summary
# read only cross-window aggregates (confidence_label / profile_label / *_core / the published
# cross-window volatility_context) and never change with the switcher. The page renders each
# group under its matching heading so the cross-window "does not change with the horizon
# switcher" hint can never apply to per-window prose.
_PER_WINDOW_EXPLANATION_TITLES = ("Delta", "Gamma", "Asymmetry", "Volatility")
_CROSS_WINDOW_EXPLANATION_TITLES = ("Confidence", "Interaction", "Summary")


def _render_explanation_grid(cards: list[tuple[str, str]]) -> str:
    """Render a set of (title, text) narrative cards as one explanation grid.

    Cards are built once by `_build_active_window_explanations`, which reuses
    `golden_vector/model/explanations.py` so narrative semantics have ONE source of
    truth across the pipeline and the workspace (per Codex's horizon-plan review).
    The pipeline bakes explanations for the ticker's canonical anchor; the workspace
    regenerates them live using the active window's numbers.
    """
    if not cards:
        return ""
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
    # Interaction/Summary are CROSS-WINDOW cards (rendered under the "does not change with the
    # horizon switcher" block), so they must read the PUBLISHED cross-window volatility context,
    # never the active-window recompute — otherwise their prose flips per window for tickers
    # whose volatility band crosses between windows (e.g. a CONVEX name LOW_NOISE@1Y, HIGH@5Y).
    cross_window_vol_context = str(tool_a_row.get("volatility_context") or "").strip().upper()
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
        volatility_context=cross_window_vol_context,
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
    for window_id in _STRUCTURAL_WINDOWS:
        normalized = window_id.lower()
        markers = []
        if window_id == anchor_window_id:
            markers.append("Anchor")
        if window_id == active_window:
            markers.append("Active")
        if window_id not in SCORING_WINDOWS:
            markers.append("display-only")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        row_class = " class=\"active-row\"" if window_id == active_window else ""
        window_rows.append(
            f"<tr{row_class}>"
            f"<td>{WINDOW_LABELS.get(window_id, window_id)}{marker_text}</td>"
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
        "<h3>Structural windows — all lookbacks</h3>"
        "<p class=\"hint\">Cross-window reference: 6M / 1Y / 3Y are the scoring windows; "
        "2Y / 5Y are display-only longer lookbacks (computed but never scored or ranked).</p>"
        + table_region(
            "<table>"
            "<thead><tr>"
            + help_th("Window", key="tool_a_structural_window")
            + help_th("Delta", key="tool_a_delta")
            + help_th("Gamma", key="tool_a_gamma")
            + help_th("Up Beta", key="tool_c_up_beta")
            + help_th("Down Beta", key="tool_c_down_beta")
            + help_th("Asymmetry", key="tool_a_asymmetry")
            + help_th("R^2", key="tool_a_r_squared")
            + help_th("Weeks", key="tool_a_window_weeks")
            + help_th("Status", key="tool_a_window_status")
            + "</tr></thead>"
            f"<tbody>{''.join(window_rows)}</tbody>"
            "</table>",
            region_id="detail-windows-table-region",
            label="Beta windows",
        )
        + "</section>"
    )


def _render_visual_panels(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    scoring_config: Any = None,
    volatility_diag: dict[str, Any] | None = None,
) -> str:
    # volatility_diag is computed ONCE per render by the caller and threaded down:
    # the estimator re-ran 2-3x per page before, and a live estimator must not be
    # a function of how many panels happen to ask for it.
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
        # The rebased price overlay draws gold / stock / GDX / GDXJ prices, not the
        # scored betas, so it carries no structural-file provenance gate. It renders
        # whenever there is enough price history, even when the foundation snapshot is
        # misaligned (the misalignment is surfaced by the page-level notice above).
        overlay_panel = (
            "<div id=\"charts\">"
            + _render_rebased_overlay_panel(
                ticker=ticker,
                rebased_overlay_by_window=tool_a_detail.rebased_overlay_by_window,
                active_window=active_window,
            )
            + "</div>"
        )
        # Mirror the aligned branch's ordering (Fix #10 follow-up): chart sits
        # between the scatter row and the volatility row in BOTH branches so the
        # detail page has consistent visual rhythm regardless of alignment state.
        return (
            "<div class=\"two-up\">"
            + _render_suppressed_panel("Weekly Return Scatter", reason, command)
            + _render_suppressed_panel("Up vs Down Beta", reason, command)
            + "</div>"
            + overlay_panel
            + "<div class=\"two-up\">"
            + _render_volatility_panel(
                tool_a_row,
                active_window=active_window,
                weekly_series=tool_a_detail.weekly_series,
                scoring_config=scoring_config,
                volatility_diag=volatility_diag,
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
    # Rebased price overlay (gold / stock / GDX / GDXJ indexed to 100 over the active
    # window). The beta NUMBERS live in the structural-window table above; this chart
    # answers co-movement — did the miner beat gold and the gold-miner ETFs?
    # The charts anchor wraps the overlay in BOTH alignment branches so the
    # in-page section navigation always resolves (plan 15/23).
    overlay_panel = (
        "<div id=\"charts\">"
        + _render_rebased_overlay_panel(
            ticker=ticker,
            rebased_overlay_by_window=tool_a_detail.rebased_overlay_by_window,
            active_window=active_window,
        )
        + "</div>"
    )
    # Chart placement: the overlay sits immediately under the scatter / up-down-beta
    # row, above the volatility and exploratory panels.
    comparison = tool_a_detail.benchmark_comparison_by_window.get(active_window)
    comparison_panel = _render_beta_comparison_panel(
        comparison, ticker=ticker, active_window=active_window
    )
    # The Up-vs-Down bar and the universe-rank strips are two views of the same up/down beta, so
    # they sit side by side (responsive — they stack on a narrow screen) instead of stacking and
    # reading as a repeat. The regression scatter pairs with the rebased overlay.
    return (
        "<div class=\"two-up\">"
        f"{_render_up_down_beta_panel(tool_a_row, anchor_metric=active_metric, active_window=active_window, comparison=comparison)}"
        f"{comparison_panel}"
        "</div>"
        "<div class=\"two-up\">"
        f"{_render_scatter_panel(ticker=ticker, tool_a_row=tool_a_row, anchor_metric=active_metric, anchor_sample=active_sample, active_window=active_window)}"
        f"{overlay_panel}"
        "</div>"
        "<div class=\"two-up\">"
        f"{_render_volatility_panel(tool_a_row, active_window=active_window, weekly_series=tool_a_detail.weekly_series, scoring_config=scoring_config, volatility_diag=volatility_diag)}"
        f"{_render_exploratory_horizon_panel(tool_a_detail.exploratory_horizons)}"
        "</div>"
    )


def _active_window_metric(
    tool_a_detail: ToolADetailState,
    active_window: str,
) -> dict[str, Any]:
    """Return the structural_window_metrics row for the active window.

    Keyed on the active window rather than the ticker's canonical
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
            f"<p>No weekly return detail is available yet for the {escape(WINDOW_LABELS.get(active_window, active_window))} window.</p>"
            "</section>"
        )
    regression_beta = _optional_float(anchor_metric.get("structural_delta"))
    regression_alpha = _optional_float(anchor_metric.get("intercept_alpha"))
    # A week missing either leg is not a plottable point — drop the pair before the
    # builder rather than letting NaN reach the axis scaling.
    plot_x = pd.to_numeric(anchor_sample["gold_weekly_log_return"], errors="coerce")
    plot_y = pd.to_numeric(anchor_sample["stock_weekly_log_return"], errors="coerce")
    # np.isfinite (not notna): +/-inf is just as unplottable as NaN.
    finite = np.isfinite(plot_x.to_numpy(dtype=float)) & np.isfinite(
        plot_y.to_numpy(dtype=float)
    )
    plot_x = plot_x[finite]
    plot_y = plot_y[finite]
    if plot_x.empty:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Weekly Return Scatter</h3>"
            f"<p>No weekly return detail is available yet for the {escape(WINDOW_LABELS.get(active_window, active_window))} window.</p>"
            "</section>"
        )
    svg = _build_scatter_svg(
        x_values=plot_x.tolist(),
        y_values=plot_y.tolist(),
        regression_beta=regression_beta,
        regression_alpha=regression_alpha,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Weekly Return Scatter</h3><p class=\"hint\">Each dot is one week over the "
        f"{escape(WINDOW_LABELS.get(active_window, active_window))} sample: x = gold's weekly return, y = {escape(ticker)}'s. The "
        "line's slope is the gold beta (how much the stock moves per 1% gold move); how tightly "
        "the dots hug the line is the R² (reliability). Top-right = both rose, bottom-left = both "
        "fell.</p>"
        f"{svg}"
        "</section>"
    )


def _grouped_beta_bars(comparison: Any, side: str) -> list[dict[str, Any]]:
    """One grouped-bar entry (stock + each benchmark) for the up/down side, from resolved values."""

    bars: list[dict[str, Any]] = []
    if comparison.subject is not None:
        bars.append(
            {
                "label": comparison.subject.label,
                "value": getattr(comparison.subject, f"{side}_beta"),
                "series": _STOCK_SERIES,
            }
        )
    for index, marker in enumerate(comparison.benchmarks):
        bars.append(
            {
                "label": marker.label,
                "value": getattr(marker, f"{side}_beta"),
                "series": _benchmark_series(marker.label, index),
            }
        )
    return bars


def _render_up_down_beta_panel(
    tool_a_row: dict[str, Any],
    *,
    anchor_metric: dict[str, Any],
    active_window: str = "12M",
    comparison: Any = None,
) -> str:
    up_beta = _optional_float(anchor_metric.get("up_beta"))
    down_beta = _optional_float(anchor_metric.get("down_beta"))
    if up_beta is None and down_beta is None:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Up vs Down Beta</h3><p>No {escape(WINDOW_LABELS.get(active_window, active_window))} regime split is available yet.</p>"
            "</section>"
        )
    # When the GDX/GDXJ comparison is available, show the stock AND the ETFs as grouped bars on the
    # SAME window, so the stock's up/down beta reads directly against the benchmarks.
    has_benchmarks = comparison is not None and getattr(comparison, "subject", None) is not None and comparison.benchmarks
    if has_benchmarks:
        svg = _build_grouped_beta_bar_svg(
            groups=[
                {"label": "Up-Gold (weeks gold rose)", "bars": _grouped_beta_bars(comparison, "up")},
                {"label": "Down-Gold (weeks gold fell)", "bars": _grouped_beta_bars(comparison, "down")},
            ],
        )
        # Swatch classes come from the SAME semantic series keys the bars use, so the legend
        # can never drift from the bars it labels (one copy of the palette, in css/tokens.css).
        # The legend enumerates the benchmarks that were ACTUALLY resolved into the
        # bars (same objects, same series keys), so it can never name a GDX/GDXJ the
        # chart did not draw.
        legend_items = [
            f"<span class=\"legend-swatch-{_STOCK_SERIES}\">■ this stock</span>"
        ]
        for index, marker in enumerate(comparison.benchmarks):
            legend_items.append(
                f"<span class=\"legend-swatch-{_benchmark_series(marker.label, index)}\">"
                f"■ {escape(str(marker.label))}</span>"
            )
        legend = (
            "<p class=\"hint\">Bars: "
            + ", ".join(legend_items)
            + " — all on the "
            + f"{escape(WINDOW_LABELS.get(active_window, active_window))} window, so they are directly comparable.</p>"
        )
    else:
        # Pass None through for a missing side: the builder draws an explicit n/a
        # marker. `up_beta or 0.0` used to draw a real-looking 0.00 bar, which reads
        # as "measured zero beta" rather than "not available".
        svg = _build_dual_bar_svg(
            left_label="Up-Gold",
            left_value=up_beta,
            right_label="Down-Gold",
            right_value=down_beta,
        )
        legend = ""
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Up vs Down Beta</h3>"
        f"<p class=\"hint\">Gold beta measured separately on weeks gold rose (up beta) vs weeks gold "
        f"fell (down beta), over the {escape(WINDOW_LABELS.get(active_window, active_window))} sample. A taller down bar than up bar "
        "(positive gamma) means it falls more with gold than it rises — a fragile, asymmetric "
        "profile. Either beta can be negative (moves opposite to gold).</p>"
        f"{legend}"
        f"{svg}"
        "</section>"
    )


def _subject_strip_label(ticker: str, beta: float | None, percentile: float | None) -> str:
    """Pre-format the one labelled marker on the universe strip (display only, no math)."""

    if beta is None:
        return ticker
    if percentile is None:
        return f"{ticker} {_fmt_number(beta, decimals=2)}"
    return f"{ticker} {_fmt_number(beta, decimals=2)} · {_ordinal_percentile(percentile)}"


def _render_beta_comparison_panel(
    comparison: Any,
    *,
    ticker: str,
    active_window: str = "12M",
) -> str:
    """Where this stock ranks within the 62-miner universe, on the SAME selected window.

    The strip shows the whole universe as a faint rug, the stock as the one labelled marker, and
    GDX/GDXJ as small context ticks (their values are on the Up-vs-Down bar above). Every position
    is resolved in the model layer; this renderer only formats text and places backend positions.
    """

    title = "Where its gold beta ranks vs the miner universe"
    if comparison is None or not getattr(comparison, "available", False):
        note = getattr(comparison, "note", None) if comparison is not None else None
        # Escaped once, at render (below) — pre-escaping here double-escaped the
        # window label into "&amp;" sequences for any label carrying punctuation.
        message = note or (
            f"No universe comparison is available for the {WINDOW_LABELS.get(active_window, active_window)} window yet."
        )
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>{escape(title)}</h3><p class=\"hint\">{escape(message)}</p>"
            "</section>"
        )

    window_label_text = escape(str(comparison.window_label))
    window_label_raw = str(comparison.window_label)
    subject = comparison.subject
    down_svg = _build_beta_strip_svg(
        axis_label=f"Down beta — weeks gold fell ({window_label_raw})",
        domain=comparison.down_domain,
        universe_marks=list(comparison.down_universe_marks),
        subject_pos=subject.down_pos if subject is not None else None,
        subject_label=_subject_strip_label(
            ticker, subject.down_beta if subject else None, subject.down_percentile if subject else None
        ),
        benchmark_positions=[m.down_pos for m in comparison.benchmarks if m.down_pos is not None],
        data_table_id=f"chart-data-downbeta-{_id_token(ticker)}-{_id_token(window_label_raw)}",
    )
    up_svg = _build_beta_strip_svg(
        axis_label=f"Up beta — weeks gold rose ({window_label_raw})",
        domain=comparison.up_domain,
        universe_marks=list(comparison.up_universe_marks),
        subject_pos=subject.up_pos if subject is not None else None,
        subject_label=_subject_strip_label(
            ticker, subject.up_beta if subject else None, subject.up_percentile if subject else None
        ),
        benchmark_positions=[m.up_pos for m in comparison.benchmarks if m.up_pos is not None],
        data_table_id=f"chart-data-upbeta-{_id_token(ticker)}-{_id_token(window_label_raw)}",
    )

    # Build the lead per side, so a stock with only one side available is described correctly
    # (keying off the down side alone would falsely call an up-only stock "not in the universe").
    if subject is None:
        lead = (
            f"{escape(ticker)} is not in the scored miner universe, so only the universe spread "
            f"and the GDX/GDXJ ticks are shown for the {window_label_text} window. "
        )
    else:
        side_phrases = []
        if subject.down_percentile is not None:
            side_phrases.append(
                f"its down beta sits at the {_ordinal_percentile(subject.down_percentile)} of the "
                f"{comparison.universe_down_n} scored miners (higher = falls more with gold)"
            )
        if subject.up_percentile is not None:
            side_phrases.append(
                f"its up beta at the {_ordinal_percentile(subject.up_percentile)} of "
                f"{comparison.universe_up_n}"
            )
        if side_phrases:
            lead = (
                f"Over the {window_label_text} window, {escape(ticker)}'s "
                + ", and ".join(side_phrases)
                + ". "
            )
        else:
            lead = (
                f"{escape(ticker)}'s gold beta is not available for the {window_label_text} window; "
                "the universe spread and GDX/GDXJ ticks are shown for context. "
            )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)}</h3>"
        f"<p class=\"hint\">{lead}Each light tick is one of the miners; the "
        f"<span class=\"legend-swatch-{_STOCK_SERIES}\">orange marker</span> is {escape(ticker)}; the dashed "
        "blue ticks are GDX/GDXJ (values on the chart above). Switch the window above to re-base all "
        "of them to the same period.</p>"
        f"{down_svg}{up_svg}"
        "</section>"
    )


def _render_volatility_panel(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
    weekly_series: pd.DataFrame | None = None,
    scoring_config: Any = None,
    volatility_diag: dict[str, Any] | None = None,
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
    win_label = WINDOW_LABELS.get(active_window, active_window)
    # If the active window isn't ELIGIBLE, suppress numbers entirely.
    # Codex flagged in review: a structural page showing low-obs vol
    # with just a sample-size asterisk implies more trust than it should.
    if window_status != "ELIGIBLE":
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Volatility Diagnostics ({escape(win_label)})</h3>"
            f"<p class=\"hint\">The {escape(win_label)} window is not eligible for this ticker "
            f"(status: {escape(str(window_status))}). Volatility is not shown.</p>"
            "</section>"
        )

    # Reuse the caller's single per-render computation when it was threaded in.
    diag = (
        volatility_diag
        if volatility_diag is not None
        else _compute_window_volatility(
            tool_a_row=tool_a_row,
            active_window=active_window,
            weekly_series=weekly_series,
            scoring_config=scoring_config,
        )
    )
    context_label = diag.get("volatility_context") or "UNKNOWN"
    # Label every number with its basis: for a non-canonical window these are a live
    # serve-side estimate off the weekly series, not the pipeline's published fields.
    basis_hint = (
        "<p class=\"hint\">Estimated live from the weekly series (published values "
        "are 52-week), so these can differ slightly from the pipeline numbers.</p>"
        if diag.get("estimated")
        else ""
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Volatility Diagnostics ({escape(win_label)})</h3>"
        f"{basis_hint}"
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
            "estimated": False,
        }

    # Non-canonical window: recompute from the window's weekly slice.
    if weekly_series is None or weekly_series.empty:
        return {}
    from golden_vector.model.structural import (
        annualize_weekly_volatility,
        annualize_downside_volatility,
    )
    # ONE definition of "the window's sample": the same date-masked model helper the
    # scatter panel uses (build_trailing_window_rows), not a private tail-by-count
    # slice. A count slice and a date mask disagree whenever the weekly series has
    # gaps, which would silently build the scatter and the volatility card on
    # different weeks. When the row carries no usable as_of_date we anchor on the
    # series' own last observation (the week a tail slice would have ended on).
    ordered = weekly_series.sort_values("as_of_date").reset_index(drop=True)
    as_of_date = pd.to_datetime(tool_a_row.get("as_of_date"), errors="coerce")
    if pd.isna(as_of_date):
        as_of_date = pd.to_datetime(ordered["as_of_date"], errors="coerce").max()
    if pd.isna(as_of_date):
        return {}
    trailing = build_trailing_window_rows(
        weekly_series=ordered,
        as_of_date=pd.Timestamp(as_of_date),
        window_id=active_window,
    )
    if trailing.empty:
        return {}
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
        # Basis flag: these came from a live serve-side estimate over the weekly
        # series, NOT from the published pipeline fields (which are 52-week). The
        # renderer must say so — an unlabelled number implies published provenance.
        "estimated": True,
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
            f"<td>{escape(window_label(str(row.horizon_id)))}</td>"
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
        + table_region(
            "<table>"
            "<thead><tr>"
            + help_th("Horizon", key="exploratory_horizon")
            + help_th("Equity Return", key="exploratory_equity_return")
            + help_th("Gold Return", key="exploratory_gold_return")
            + help_th("Single-Period Ratio", key="exploratory_single_period_ratio")
            + help_th("Status", key="exploratory_coverage_status")
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>",
            region_id="detail-exploratory-horizons-table-region",
            label="Exploratory horizon ladder",
        )
        + "</section>"
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


def _render_rebased_overlay_panel(
    *,
    ticker: str,
    rebased_overlay_by_window: dict[str, dict[str, tuple[list, list]]],
    active_window: str = "12M",
) -> str:
    """Rebased-to-100 overlay of the stock vs gold vs GDX/GDXJ over the active lookback window.

    Replaces the old rolling-beta line: the beta NUMBERS live in the windowed table above, so this
    chart's job is co-movement — "did the miner beat gold and the gold-miner ETFs?". The series are
    built in the backend (``workspace_state`` → ``build_rebased_comparison_series``); this only
    draws them. Needs at least two drawable series (gold + the stock); a missing GDX/GDXJ history
    simply omits that line (degrade per item)."""

    title = "Gold vs Stock vs Gold-Miner ETFs"
    overlay = rebased_overlay_by_window.get(active_window) or {}
    drawable = {
        label: series
        for label, series in overlay.items()
        if _has_drawable_overlay_line(series)
    }
    if len(drawable) < 2:
        return _render_chart_unavailable_panel(
            title,
            "Not enough price history to plot the comparison yet. "
            "Run <code>python main.py refresh</code> to fetch fresh prices.",
        )

    series_keys = {
        ticker: "overlay-stock",
        "Gold": "gold",
        "GDX": "overlay-gdx",
        "GDXJ": "overlay-gdxj",
    }
    svg = _build_multiline_overlay_svg(
        series_by_label=drawable,
        series_keys=series_keys,
        data_table_id=f"chart-data-overlay-{_id_token(ticker)}-{_id_token(active_window)}",
    )
    window_label_display = WINDOW_LABELS.get(active_window, active_window)
    # Caption names only the benchmarks that actually drew, so a missing GDX/GDXJ history
    # is never implied to be present (label every number with its real basis).
    gold_drawn = "Gold" in drawable
    drawn_benchmarks = [label for label in ("GDX", "GDXJ") if label in drawable]
    comparator_parts: list[str] = []
    if gold_drawn:
        comparator_parts.append("gold")
    if drawn_benchmarks:
        etf_word = "ETF" if len(drawn_benchmarks) == 1 else "ETFs"
        comparator_parts.append(
            f"the gold-miner {etf_word} (" + " / ".join(drawn_benchmarks) + ")"
        )
    benchmark_phrase = " and ".join(comparator_parts)
    if gold_drawn and not drawn_benchmarks:
        # Be explicit that the benchmarks are absent rather than implying they were compared.
        benchmark_phrase = (
            "gold (GDX / GDXJ benchmark history was unavailable, so only gold is shown)"
        )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)}</h3>"
        f"<p class=\"hint\">Each line is indexed to 100 at the start of the {escape(window_label_display)} "
        f"window (USD) — so you can see whether {escape(ticker)} outpaced {benchmark_phrase} "
        "over the lookback. Use the window toggle above to change the period.</p>"
        f"{svg}"
        "</section>"
    )


def _has_drawable_overlay_line(series: tuple[list, list] | object) -> bool:
    if not series:
        return False
    try:
        dates, values = series
    except (TypeError, ValueError):
        return False
    if not dates or not values or len(dates) != len(values):
        return False
    valid_date_keys: set[str] = set()
    for date_value, value in zip(dates, values):
        if value is None or pd.isna(date_value):
            continue
        timestamp = pd.Timestamp(date_value)
        if pd.notna(timestamp):
            valid_date_keys.add(timestamp.strftime("%Y-%m-%d"))
    return len(valid_date_keys) >= 2


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
