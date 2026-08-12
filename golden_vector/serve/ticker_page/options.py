"""M3d: the Options section of the redesigned ticker page.

What lives here (requirements §3 "Options", §4, §8 addendum D-3):

* **availability first** — the section is absent ONLY when the persisted
  ``option_availability`` artifact says the company has no listed options
  (``NONE_LISTED``). Every other unhappy path renders a visible, degraded
  section with the reason. "The artifact is missing" is never shown as "this
  company has no options" (plan §8);
* open: the market context (BOTH put/call open-interest ratios, the OI trend,
  IV vs its own history, implied move, daily volume) and the most liquid
  contracts per side under a "Target window" selector;
* closed: where the crowd is positioned (OI by strike + skew), "Work out a
  position" (the sizing tool), and greeks + full chain detail.

Render-only. Every number is a persisted column: the chain-level daily
quantities come from ``option_chain_history_daily``, the signal series from
``option_signal_history_points``, the contracts from the candidate/slot
artifacts, and the greeks from the persisted ``candidate_gamma/vega/theta``
columns. Nothing is computed here — in particular the old gold-scenario sizing
calculator is DELETED, not moved: it derived the share price from a gold beta,
which Victor rejected outright (Q40). The replacement is a share-price slider
whose only arithmetic (whole contracts, break-even, intrinsic value at expiry)
lives in the frozen, parity-locked ``static/option-sizing.js``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from html import escape
from typing import Any, Mapping, Sequence
from urllib.parse import quote

import pandas as pd

#: The ONE contract multiplier, shared with every backend option consumer — the
#: sizing payload must not carry a second hardcoded 100.
from golden_vector.common.numeric import optional_finite_float
from golden_vector.common.options import OPTION_CONTRACT_MULTIPLIER
from golden_vector.contracts.config_models import AppConfig, TickerPageSizingConfig
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_availability import (
    AVAILABILITY_FETCH_FAILED,
    AVAILABILITY_FILTERED_WINDOW_EMPTY,
    AVAILABILITY_NONE_LISTED,
    AVAILABILITY_UNKNOWN,
)
from golden_vector.hedge.option_trading import OptionTradingDetailData
from golden_vector.hedge.options_liquidity import bucket_label, slot_tier_counts
from golden_vector.serve.charts import (
    _build_multiline_overlay_svg,
    _chart_data_disclosure,
)
from golden_vector.serve.column_help import help_icon, help_term, help_th
from golden_vector.serve.embed import embed_json_payload
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _metric_card,
    _optional_float,
    _ticker_rows,
    format_dte_suffix as _dte_suffix,
)
from golden_vector.serve.option_signal_charts import (
    _render_oi_strike_chart,
    _render_signal_history_chart,
    _render_skew_curve_chart,
)
from golden_vector.serve.option_signal_render import signal_horizon_from_row
from golden_vector.serve.option_trading_data import (
    OPTION_PAGE_OK,
    OPTION_PAGE_UNAVAILABLE_PRE_V4,
    OptionPageArtifacts,
)
from golden_vector.serve.ui.components import disclosure, section_heading
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.url_helpers import build_page_url


SECTION_ID = "options"

#: Shared by the server (embed) and option-sizing.js (read). Frozen contract.
SIZING_PAYLOAD_ID = "option-sizing-payload"
SIZING_ROOT_ID = "option-sizing"
SIZING_SCRIPT_SRC = "/static/option-sizing.js"

#: Query-param name for the "Target window" control (plan §9.4, addendum D-3).
TARGET_WINDOW_PARAM = "tw"

# The three rendered modes. Only ABSENT removes the section AND its nav anchor.
MODE_ABSENT = "absent"
MODE_FULL = "full"
MODE_DEGRADED = "degraded"

_FRESHNESS_CARRIED_FORWARD = "CARRIED_FORWARD"
_FRESHNESS_MISALIGNED = "MISALIGNED"

_PRE_V4_REASON = "awaiting first v4 refresh"

#: The producer writes "COMPLETE" or "PARTIAL:<flag>,<flag>" (hedge/chain_history.py).
_CAPTURE_COMPLETE = "COMPLETE"

_INTRINSIC_ONLY_NOTE = (
    "Value at expiry is intrinsic value only — no time value is assumed, so selling "
    "before expiry would normally be worth more than these rows show."
)


# ---------------------------------------------------------------------------
# 1. availability resolution (plan §8 — the five-state matrix)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionsAvailability:
    """What the persisted availability artifact permits this page to claim."""

    mode: str
    status: str
    reason: str | None = None
    as_of_date: str | None = None
    #: True whenever the generation was carried forward, WITH OR WITHOUT a date.
    carried_forward: bool = False
    carried_forward_from: str | None = None

    @property
    def absent(self) -> bool:
        return self.mode == MODE_ABSENT


def resolve_options_availability(
    page_artifacts: OptionPageArtifacts | None,
    *,
    ticker: str,
) -> OptionsAvailability:
    """Map the persisted artifacts onto the plan §8 state matrix.

    The whole point of this function is that exactly ONE input can hide the
    section: a current, readable ``option_availability`` row that says
    ``NONE_LISTED``. Anything else — no artifact, an old generation, a corrupt
    file, a failed fetch, an unknown ticker — renders and explains itself.
    """

    if page_artifacts is None:
        return OptionsAvailability(
            mode=MODE_DEGRADED,
            status=AVAILABILITY_UNKNOWN,
            reason="the option availability artifact was not loaded for this page",
        )
    if page_artifacts.state == OPTION_PAGE_UNAVAILABLE_PRE_V4:
        return OptionsAvailability(
            mode=MODE_DEGRADED,
            status=AVAILABILITY_UNKNOWN,
            reason=_PRE_V4_REASON,
        )
    if page_artifacts.state != OPTION_PAGE_OK:
        return OptionsAvailability(
            mode=MODE_DEGRADED,
            status=AVAILABILITY_UNKNOWN,
            reason=page_artifacts.reason or "the option artifacts could not be read",
        )

    status = _availability_status_for(page_artifacts.availability, ticker)
    as_of = page_artifacts.freshness_as_of_date
    freshness = str(page_artifacts.freshness_status or "").strip().upper()

    # ORDER MATTERS. A misaligned generation is by definition NOT current, so
    # its NONE_LISTED row is not the "current artifact says so" the matrix
    # requires — a company that has since listed options would lose the whole
    # section off an artifact this very function calls untrustworthy. Misaligned
    # is therefore resolved BEFORE the one branch that can hide the section.
    if freshness == _FRESHNESS_MISALIGNED:
        return OptionsAvailability(
            mode=MODE_DEGRADED,
            status=status,
            reason=(
                page_artifacts.freshness_message
                or "the option artifacts reference a different refresh than the current model run"
            ),
            as_of_date=as_of,
        )
    if status == AVAILABILITY_NONE_LISTED:
        return OptionsAvailability(mode=MODE_ABSENT, status=status, as_of_date=as_of)
    if status == AVAILABILITY_FETCH_FAILED:
        return OptionsAvailability(
            mode=MODE_DEGRADED,
            status=status,
            reason=(
                "the last option capture for this ticker failed, so its chain could not "
                "be read. This is a data gap, not evidence that the company lacks "
                "listed options."
            ),
            as_of_date=as_of,
        )
    if status == AVAILABILITY_UNKNOWN:
        return OptionsAvailability(
            mode=MODE_DEGRADED,
            status=status,
            reason=(
                "the options stage never recorded a result for this ticker, so its option "
                "availability is unknown"
            ),
            as_of_date=as_of,
        )
    return OptionsAvailability(
        mode=MODE_FULL,
        status=status,
        as_of_date=as_of,
        # Keyed on the STATUS, never on the date: a carried-forward manifest is
        # allowed to omit as_of_date, and treating "no date" as "not stale"
        # would quietly re-enable position sizing on yesterday's asks.
        carried_forward=freshness == _FRESHNESS_CARRIED_FORWARD,
        carried_forward_from=as_of if freshness == _FRESHNESS_CARRIED_FORWARD else None,
    )


def _availability_status_for(frame: pd.DataFrame, ticker: str) -> str:
    rows = _rows_for(frame, ticker)
    if not rows or "availability_status" not in rows[0]:
        return AVAILABILITY_UNKNOWN
    status = str(rows[0].get("availability_status") or "").strip().upper()
    return status or AVAILABILITY_UNKNOWN


def _rows_for(frame: pd.DataFrame | None, ticker: str) -> list[dict[str, Any]]:
    """The ONE ticker lookup for this module — the shared serve helper."""

    if not isinstance(frame, pd.DataFrame):
        return []
    return _ticker_rows(frame, str(ticker or "").strip().upper())


# ---------------------------------------------------------------------------
# 2. the section
# ---------------------------------------------------------------------------


def render_options_section(
    *,
    ticker: str,
    detail: OptionTradingDetailData | None = None,
    page_artifacts: OptionPageArtifacts | None = None,
    candidate_slots_frame: pd.DataFrame | None = None,
    app_config: AppConfig | None = None,
    target_window: int | None = None,
    sizing_request: object | None = None,
    financials_source: str = "our",
    query_params: Mapping[str, str] | None = None,
) -> str:
    """Render the Options section, or ``""`` when the company has no options.

    An empty string is the ONLY way the section (and, through the caller, its
    nav anchor) disappears, and it happens for exactly one reason: a current
    artifact that says ``NONE_LISTED``.
    """

    availability = resolve_options_availability(page_artifacts, ticker=ticker)
    if availability.absent:
        return ""

    pieces: list[str] = [
        f"<section id=\"{SECTION_ID}\" class=\"panel ticker-section\">",
        section_heading(
            "Options",
            help_html=help_icon("Options", key="option_section"),
        ),
        _render_availability_banner(availability),
    ]

    if availability.mode == MODE_DEGRADED:
        pieces.append("</section>")
        return "".join(pieces)

    horizons = _display_horizons(app_config)
    window = resolve_target_window(target_window, app_config)
    # The third element (the skipped incomplete capture date) is deliberately
    # unused: nothing on this page states it, and threading a value no renderer
    # reads is how dead parameters are born. ``_chain_history_for`` still
    # returns it because that is where the exclusion decision is made.
    history_row, history_rows, _ = _chain_history_for(page_artifacts, ticker)

    pieces.append(
        _render_market_context(
            detail=detail,
            history_row=history_row,
            history_rows=history_rows,
            app_config=app_config,
        )
    )
    pieces.append(
        _render_contracts(
            detail=detail,
            availability=availability,
            ticker=ticker,
            window=window,
            horizons=horizons,
            app_config=app_config,
            financials_source=financials_source,
            query_params=query_params,
        )
    )
    pieces.append(_render_crowd_positioning(detail))
    pieces.append(
        _render_sizing_tool(
            detail=detail,
            availability=availability,
            app_config=app_config,
            sizing_request=sizing_request,
        )
    )
    pieces.append(
        _render_greeks_and_chain(
            detail=detail,
            candidate_slots_frame=candidate_slots_frame,
            ticker=ticker,
            app_config=app_config,
        )
    )
    pieces.append("</section>")
    return "".join(pieces)


def _render_availability_banner(availability: OptionsAvailability) -> str:
    if availability.mode == MODE_DEGRADED:
        reason = availability.reason or "the option data could not be read"
        body = (
            "Option data is unavailable right now: "
            f"{escape(reason)}. This is a data gap, not a statement about whether "
            "the company has listed options — the section stays visible so a missing "
            "file can never be mistaken for an absence of contracts."
        )
        return notice("warning", body)
    parts: list[str] = []
    if availability.carried_forward:
        origin = (
            f"Carried forward from {escape(availability.carried_forward_from)}"
            if availability.carried_forward_from
            else "Carried forward from an earlier snapshot"
        )
        parts.append(
            notice(
                "warning",
                f"{origin} — the latest refresh could not publish fresh option "
                "quotes, so every number below is that snapshot's, not today's.",
            )
        )
    elif availability.as_of_date:
        parts.append(
            "<p class=\"hint\">Option data as of "
            f"{escape(availability.as_of_date)}. Screening only — live prices differ.</p>"
        )
    if availability.status == AVAILABILITY_FILTERED_WINDOW_EMPTY:
        parts.append(
            "<p class=\"hint\">This ticker has listed options, but none of them fell "
            "inside the configured expiry window at the last capture, so the contract "
            "tables below can be empty while the market context is still real.</p>"
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# 3. market context (open)
# ---------------------------------------------------------------------------


def _render_market_context(
    *,
    detail: OptionTradingDetailData | None,
    history_row: Mapping[str, Any] | None,
    history_rows: list[dict[str, Any]],
    app_config: AppConfig | None,
) -> str:
    signal_horizon = _signal_horizon(detail, app_config)
    body = [
        "<div class=\"options-market-context\">",
        section_heading(
            "Market context",
            level=3,
            help_html=help_icon(
                "Market context", key="option_market_context", app_config=app_config
            ),
        ),
        _render_ratio_pair(history_row),
        _render_oi_trend(history_rows),
        _render_volume_cards(history_row),
        _render_signal_history(detail, signal_horizon=signal_horizon),
        "</div>",
    ]
    return "".join(body)


def _render_ratio_pair(history_row: Mapping[str, Any] | None) -> str:
    """BOTH put/call open-interest ratios, each read in words.

    Victor's requirement is that the two ratios DISAGREEING is the insight, so
    they are always shown together and, when they point opposite ways, a third
    sentence says so explicitly. Both ratios are persisted columns
    (``put_call_oi_ratio_total`` / ``put_call_oi_ratio_otm``); nothing here
    divides one number by another.
    """

    if not history_row:
        return notice(
            "info",
            "No daily option-chain history has been captured yet, so the put/call "
            "open-interest ratios cannot be shown. They appear after the first "
            "market-hours refresh.",
        )
    whole = _optional_float(history_row.get("put_call_oi_ratio_total"))
    otm = _optional_float(history_row.get("put_call_oi_ratio_otm"))
    as_of = _fmt_text(history_row.get("as_of_date"))
    puts = history_row.get("put_oi_total")
    calls = history_row.get("call_oi_total")
    total = history_row.get("total_open_interest")

    cards = (
        "<div class=\"metric-grid options-oi-cards\">"
        + _metric_card(
            "Put open interest",
            _fmt_number(puts, decimals=0),
            help_key="option_open_interest",
        )
        + _metric_card(
            "Call open interest",
            _fmt_number(calls, decimals=0),
            help_key="option_open_interest",
        )
        + _metric_card(
            "Total open interest",
            _fmt_number(total, decimals=0),
            help_key="option_open_interest",
        )
        + "</div>"
    )

    sentences: list[str] = []
    sentences.append(
        "<p><strong>Whole chain "
        f"{_fmt_number(whole, decimals=2)}</strong>"
        f"{help_icon('Whole-chain put/call ratio', key='option_put_call_ratio_total')} — "
        f"{_fmt_number(puts, decimals=0)} puts against {_fmt_number(calls, decimals=0)} calls. "
        f"{escape(_whole_chain_reading(whole))}</p>"
    )
    sentences.append(
        "<p><strong>Out-of-the-money only "
        f"{_fmt_number(otm, decimals=2)}</strong>"
        f"{help_icon('Out-of-the-money put/call ratio', key='option_put_call_ratio_otm')} — "
        f"{_fmt_number(history_row.get('put_oi_otm'), decimals=0)} puts against "
        f"{_fmt_number(history_row.get('call_oi_otm'), decimals=0)} calls. "
        f"{escape(_otm_reading(otm))}</p>"
    )
    disagreement = _disagreement_sentence(whole, otm)
    if disagreement:
        sentences.append(f"<p class=\"options-ratio-disagreement\">{escape(disagreement)}</p>")

    return (
        "<div class=\"options-ratio-pair\">"
        + section_heading("Put/call open interest", level=4)
        + f"<p class=\"hint\">As of {as_of}.</p>"
        + cards
        + "".join(sentences)
        + "</div>"
    )


def _whole_chain_reading(ratio: float | None) -> str:
    if ratio is None:
        return "The whole-chain ratio is not available for this snapshot."
    if ratio < 1.0:
        return "More calls than puts overall, so positioning leans bullish."
    if ratio > 1.0:
        return "More puts than calls overall, so positioning leans bearish or hedged."
    return "Puts and calls are evenly matched overall."


def _otm_reading(ratio: float | None) -> str:
    if ratio is None:
        return "The out-of-the-money ratio is not available for this snapshot."
    if ratio > 1.0:
        return (
            "Puts outnumber calls where speculation and hedging live — the "
            "out-of-the-money strikes."
        )
    if ratio < 1.0:
        return (
            "Calls outnumber puts where speculation and hedging live — the "
            "out-of-the-money strikes."
        )
    return "Out-of-the-money puts and calls are evenly matched."


def _disagreement_sentence(whole: float | None, otm: float | None) -> str:
    """The sentence Victor asked for when the two persisted ratios point apart.

    This is a display classification of two already-computed columns against
    the neutral 1.0 line, not a recomputation of either ratio.
    """

    if whole is None or otm is None:
        return ""
    if whole < 1.0 and otm > 1.0:
        return (
            "These two disagree, and the disagreement is the point: more calls overall, "
            "so positioning leans bullish; but puts outnumber calls where speculation "
            "and hedging live."
        )
    if whole > 1.0 and otm < 1.0:
        return (
            "These two disagree, and the disagreement is the point: more puts overall, "
            "so positioning leans bearish; but calls outnumber puts where speculation "
            "and hedging live."
        )
    return ""


_TREND_SERIES: tuple[tuple[str, str], ...] = (
    ("Put open interest", "put_oi_total"),
    ("Call open interest", "call_oi_total"),
    ("Total open interest", "total_open_interest"),
)


def _render_oi_trend(history_rows: list[dict[str, Any]]) -> str:
    """Puts, calls and total open interest as three separate lines over time.

    Days whose capture was not COMPLETE are rendered as GAPS — their values are
    withheld from both the line and the accessible twin, and the reason is
    listed. A partial capture undercounts the chain; drawing it would put a
    fake dip on the chart.
    """

    if not history_rows:
        return (
            "<p class=\"hint\">The open-interest trend needs at least one captured day "
            "of chain history; none has been published yet.</p>"
        )

    series_by_label: dict[str, tuple[list[pd.Timestamp], list[float | None]]] = {}
    dates = [pd.to_datetime(row.get("as_of_date"), errors="coerce") for row in history_rows]
    incomplete: list[tuple[str, str]] = []
    for row, date in zip(history_rows, dates):
        if not _capture_is_complete(row) and pd.notna(date):
            incomplete.append((str(row.get("as_of_date") or ""), _capture_reason(row)))
    for label, column in _TREND_SERIES:
        values: list[float | None] = []
        for row in history_rows:
            if not _capture_is_complete(row):
                values.append(None)
                continue
            values.append(_optional_float(row.get(column)))
        series_by_label[label] = (dates, values)

    table_id = "options-oi-trend-table"
    svg = _build_multiline_overlay_svg(
        series_by_label=series_by_label,
        base=0.0,
        data_table_id=table_id,
    )
    twin = _chart_data_disclosure(
        table_html=_oi_trend_table(history_rows),
        region_id=table_id,
        label="Open interest by day",
    )
    gap_note = ""
    if incomplete:
        listed = "; ".join(
            f"{escape(date)} ({escape(reason)})" for date, reason in incomplete
        )
        gap_note = (
            "<p class=\"hint\">Gaps in the lines are days whose chain capture was "
            f"incomplete, so their open interest is not shown: {listed}. An incomplete "
            "capture undercounts the chain — smoothing over it would invent a dip.</p>"
        )
    return (
        "<div class=\"options-oi-trend\">"
        + section_heading(
            "Open interest over time",
            level=4,
            help_html=help_icon("Open interest over time", key="option_oi_trend"),
        )
        + svg
        + gap_note
        + twin
        + "</div>"
    )


def _oi_trend_table(history_rows: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for row in history_rows:
        if _capture_is_complete(row):
            cells = "".join(
                f"<td>{_fmt_number(row.get(column), decimals=0)}</td>"
                for _, column in _TREND_SERIES
            )
        else:
            cells = f"<td colspan=\"3\">Not shown &mdash; {escape(_capture_reason(row))}</td>"
        rows.append(
            "<tr>"
            f"<td>{_fmt_text(row.get('as_of_date'))}</td>"
            f"{cells}"
            f"<td>{escape(_capture_reason(row))}</td>"
            f"<td>{_fmt_text(row.get('row_status'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Date</th><th>Put OI</th><th>Call OI</th><th>Total OI</th>"
        "<th>Capture</th><th>Row status</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _render_volume_cards(history_row: Mapping[str, Any] | None) -> str:
    if not history_row:
        return ""
    as_of = _fmt_text(history_row.get("as_of_date"))
    return (
        "<div class=\"options-volume\">"
        + section_heading(
            "Daily volume",
            level=4,
            help_html=help_icon("Daily option volume", key="option_daily_volume"),
        )
        + f"<p class=\"hint\">Contracts traded on {as_of}.</p>"
        + "<div class=\"metric-grid\">"
        + _metric_card(
            "Put volume",
            _fmt_number(history_row.get("put_volume"), decimals=0),
            help_key="option_contract_volume",
        )
        + _metric_card(
            "Call volume",
            _fmt_number(history_row.get("call_volume"), decimals=0),
            help_key="option_contract_volume",
        )
        + _metric_card(
            "Total volume",
            _fmt_number(history_row.get("total_volume"), decimals=0),
            help_key="option_contract_volume",
        )
        + "</div></div>"
    )


def _render_signal_history(
    detail: OptionTradingDetailData | None,
    *,
    signal_horizon: int | None,
) -> str:
    """Implied vol vs its own history, the implied move, and the IV/RV ratio.

    Reuses the persisted signal-history chart renderer so the ticker page and
    the Option Trading page cannot draw the same series two different ways.
    """

    points = tuple(detail.signal_history_points) if detail is not None else ()
    tenor = f"{signal_horizon}-day" if signal_horizon else "signal-horizon"
    heading = section_heading(
        f"Implied volatility, implied move and IV vs realised ({tenor} tenor)",
        level=4,
        help_html=help_icon("Option signal history", key="option_signal_history"),
    )
    if not points:
        return (
            "<div class=\"options-signal-history\">"
            + heading
            + "<p class=\"hint\">No persisted option-signal history is available for "
            "this ticker yet.</p></div>"
        )
    return (
        "<div class=\"options-signal-history\">"
        + heading
        + _render_signal_history_chart(points, signal_horizon_days=signal_horizon)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# 4. most liquid contracts (open) — "Target window", D-3
# ---------------------------------------------------------------------------


def _render_contracts(
    *,
    detail: OptionTradingDetailData | None,
    availability: OptionsAvailability,
    ticker: str,
    window: int | None,
    horizons: tuple[int, ...],
    app_config: AppConfig | None,
    financials_source: str,
    query_params: Mapping[str, str] | None,
) -> str:
    put_slots = _slots_for_window(detail.put_slots if detail else (), window)
    call_slots = _slots_for_window(detail.call_slots if detail else (), window)
    pieces = [
        "<div class=\"options-contracts\">",
        section_heading(
            "Most liquid contracts",
            level=3,
            help_html=help_icon("Most liquid contracts", key="option_most_liquid"),
            actions_html=_target_window_control(
                ticker=ticker,
                window=window,
                horizons=horizons,
                financials_source=financials_source,
                query_params=query_params,
            ),
        ),
        "<p class=\"hint\">Near-the-money and directional picks for each side. "
        "Puts and calls are selected independently, so the two tables can show "
        "different expiry dates inside the same target window — every row states "
        "its own expiry and days to expiry.</p>",
    ]
    if not put_slots and not call_slots:
        pieces.append(_no_candidates_notice(detail, availability, window))
    else:
        pieces.append(
            _render_side_table("Puts", put_slots, ticker=ticker, app_config=app_config)
        )
        pieces.append(
            _render_side_table("Calls", call_slots, ticker=ticker, app_config=app_config)
        )
    pieces.append("</div>")
    return "".join(pieces)


def _no_candidates_notice(
    detail: OptionTradingDetailData | None,
    availability: OptionsAvailability,
    window: int | None,
) -> str:
    """The plain candidate-selection reason for 'listed, but nothing eligible'."""

    reason = detail.reason if detail is not None else None
    if not reason and availability.status == AVAILABILITY_FILTERED_WINDOW_EMPTY:
        reason = (
            "no listed expiry fell inside the configured capture window at the last refresh"
        )
    if not reason:
        reason = (
            "no contract in this window passed the liquidity gates (spread, open "
            "interest and minimum premium)"
        )
    window_text = f"the {window}-day target window" if window else "this target window"
    return notice(
        "info",
        "This company has listed options, but no contract is offered for "
        f"{escape(window_text)}: {escape(str(reason))}. The market context above is "
        "still measured from the real chain.",
    )


def _target_window_control(
    *,
    ticker: str,
    window: int | None,
    horizons: tuple[int, ...],
    financials_source: str,
    query_params: Mapping[str, str] | None,
) -> str:
    if not horizons:
        return ""
    base_query = {
        key: value
        for key, value in dict(query_params or {}).items()
        if key not in {TARGET_WINDOW_PARAM, "saved"}
    }
    links: list[str] = []
    for horizon in horizons:
        href = (
            build_page_url(
                f"/ticker/{quote(str(ticker), safe='')}",
                base_query,
                set_params={TARGET_WINDOW_PARAM: str(horizon)},
            )
            + f"#{SECTION_ID}"
        )
        active = horizon == window
        links.append(
            f"<a class=\"chip{' chip-active' if active else ''}\" "
            f"href=\"{escape(href, quote=True)}\" "
            f"aria-current=\"{'true' if active else 'false'}\">{escape(str(horizon))}d</a>"
        )
    return (
        "<div class=\"options-target-window\" role=\"group\" aria-label=\"Target window\">"
        "<span class=\"control-label\">Target window"
        + help_icon("Target window", key="option_target_window")
        + "</span>"
        + "".join(links)
        + "</div>"
    )


def _render_side_table(
    title: str,
    slots: list[OptionCandidateSlot],
    *,
    ticker: str,
    app_config: AppConfig | None,
) -> str:
    if not slots:
        return (
            "<div class=\"options-side\">"
            + section_heading(title, level=4)
            + f"<p class=\"hint\">No {escape(title.lower())} are offered for this "
            "target window.</p></div>"
        )
    rows = "".join(_render_contract_row(slot, ticker=ticker) for slot in slots)
    return (
        "<div class=\"options-side\">"
        + section_heading(title, level=4)
        + table_region(
            "<table><thead><tr>"
            + help_th("Contract", key="option_candidate_label")
            + help_th("Strike", key="option_strike")
            + help_th("Expiry (DTE)", key="option_expiry_dte")
            + help_th("Delta", key="option_candidate_delta")
            + help_th("Bid / Ask", key="option_bid_ask")
            + help_th("Mid", key="option_mid_price")
            + help_th("Spread", key="option_rel_spread")
            + help_th("Open interest", key="option_open_interest")
            + help_th("Volume", key="option_contract_volume")
            + help_th("Liquidity", key="option_candidate_status", app_config=app_config)
            + help_th("Chain", key="option_actions")
            + "</tr></thead>"
            f"<tbody>{rows}</tbody></table>",
            region_id=f"options-contracts-{title.strip().lower()}-region",
            label=f"{title} contracts",
        )
        + "</div>"
    )


def _render_contract_row(slot: OptionCandidateSlot, *, ticker: str) -> str:
    candidate = slot.display_candidate
    label = _slot_label(slot)
    chain_link = _yahoo_chain_link(slot.ticker or ticker, _row_expiration(slot))
    if candidate is None:
        # No contract at all for this bucket: show the persisted reason, never a
        # blank row that reads like a rendering failure.
        label_html = help_term(label, text=slot.reason) if slot.reason else escape(label)
        return (
            "<tr class=\"options-row-empty\">"
            f"<td>{label_html}</td>"
            "<td>-</td>"
            f"<td>{_fmt_text(slot.expiration)}{_dte_suffix(slot.days_to_expiry)}</td>"
            "<td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td>"
            f"<td>{_tier_badge(slot)}</td>"
            f"<td>{chain_link}</td>"
            "</tr>"
        )
    depth = _depth_hover(candidate, _slot_note(slot, candidate))
    label_html = help_term(label, text=depth)
    if slot.bucket == "near_atm" and slot.candidate is not None:
        label_html = f"<strong>{label_html}</strong>"
    reason_row = ""
    if str(slot.status or "").strip().lower() != "accepted" and slot.reason:
        reason_row = (
            "<p class=\"hint options-row-reason\">"
            f"{escape(str(slot.reason))}</p>"
        )
    return (
        "<tr>"
        f"<td>{label_html}{reason_row}</td>"
        f"<td>{_fmt_number(candidate.strike, decimals=2)}</td>"
        f"<td>{_fmt_text(candidate.expiration)}{_dte_suffix(candidate.days_to_expiry)}</td>"
        f"<td>{_fmt_number(candidate.delta, decimals=2)}</td>"
        f"<td>{_fmt_number(candidate.bid, decimals=2)} / "
        f"{_fmt_number(candidate.ask, decimals=2)}</td>"
        f"<td>{_fmt_number(candidate.mid, decimals=2)}</td>"
        f"<td>{_fmt_percent(candidate.rel_spread, decimals=1)}</td>"
        f"<td>{_fmt_number(candidate.open_interest, decimals=0)}</td>"
        f"<td>{_fmt_number(candidate.volume, decimals=0)}</td>"
        f"<td>{_tier_badge(slot)}</td>"
        f"<td>{chain_link}</td>"
        "</tr>"
    )


def _row_expiration(slot: OptionCandidateSlot) -> str | None:
    candidate = slot.display_candidate
    if candidate is not None and candidate.expiration:
        return str(candidate.expiration)
    return str(slot.expiration) if slot.expiration else None


def _slot_label(slot: OptionCandidateSlot) -> str:
    side = "Put" if slot.option_type == "P" else "Call"
    return f"{side} {bucket_label(slot.bucket)}"


def _slot_note(slot: OptionCandidateSlot, candidate: OptionCandidate) -> str:
    if candidate.liquidity_tier == "watch":
        return "Watch: wide spread, midpoint may be optimistic."
    if "lottery_like" in candidate.quote_flags:
        return "Lottery-like: high IV, short DTE, low delta."
    return slot.reason


def _depth_hover(candidate: OptionCandidate, note: str) -> str:
    text = (
        f"Bid {_fmt_number(candidate.bid, decimals=2)} / "
        f"Ask {_fmt_number(candidate.ask, decimals=2)} · "
        f"OI {_fmt_number(candidate.open_interest, decimals=0)} · "
        f"Volume {_fmt_number(candidate.volume, decimals=0)}"
    )
    return f"{text}\n{note}" if note else text


def _tier_badge(slot: OptionCandidateSlot) -> str:
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
    if str(slot.status or "").strip().lower() == "accepted":
        return '<span class="badge badge-verified">Tradable</span>'
    return '<span class="badge badge-missing">No candidate</span>'


def _yahoo_chain_link(ticker: str, expiration: str | None) -> str:
    if not expiration:
        return "-"
    try:
        expiry_date = datetime.strptime(str(expiration), "%Y-%m-%d").date()
    except ValueError:
        return "-"
    expiry_epoch = int(
        datetime.combine(expiry_date, time.min, tzinfo=timezone.utc).timestamp()
    )
    href = (
        f"https://finance.yahoo.com/quote/{quote(str(ticker), safe='')}/options"
        f"?date={expiry_epoch}"
    )
    return (
        f"<a class=\"yahoo-chain-icon\" href=\"{escape(href, quote=True)}\" target=\"_blank\" "
        "rel=\"noopener noreferrer\" title=\"Open Yahoo option chain for this expiry\" "
        "aria-label=\"Open Yahoo option chain for this expiry\">&#8599;</a>"
    )


# ---------------------------------------------------------------------------
# 5. closed: where the crowd is positioned
# ---------------------------------------------------------------------------


def _render_crowd_positioning(detail: OptionTradingDetailData | None) -> str:
    oi_points = tuple(detail.oi_strike_points) if detail is not None else ()
    skew_points = tuple(detail.skew_curve_points) if detail is not None else ()
    if not oi_points and not skew_points:
        body = (
            "<p class=\"hint\">No persisted open-interest-by-strike or skew points are "
            "available for this ticker yet.</p>"
        )
    else:
        body = _render_oi_strike_chart(
            oi_points, underlying_price=_underlying_price(detail)
        ) + _render_skew_curve_chart(skew_points)
    return disclosure(
        "Where the crowd is positioned"
        + help_icon("Where the crowd is positioned", key="option_crowd_positioning"),
        body,
    )


# ---------------------------------------------------------------------------
# 6. closed: work out a position (the sizing tool)
# ---------------------------------------------------------------------------


def build_sizing_payload(
    *,
    detail: OptionTradingDetailData | None,
    availability: OptionsAvailability,
    app_config: AppConfig | None,
) -> dict[str, Any]:
    """The frozen option-sizing.js contract, built from persisted columns only.

    Every field is read off a candidate row or a config value. The backend owns
    the verdict on whether a quote is usable at all (``quote_ok`` /
    ``quote_reason``); the JS refuses to invent a substitute for a bad quote.
    """

    sizing = (
        app_config.ticker_page.sizing if app_config is not None else TickerPageSizingConfig()
    )
    max_contracts = int(sizing.max_contracts)
    stale_reason = _stale_quote_reason(availability)
    contracts: list[dict[str, Any]] = []
    for slot in _sizing_slots(detail):
        candidate = slot.display_candidate
        if candidate is None:
            continue
        quote_ok, quote_reason = _quote_verdict(slot, candidate, stale_reason=stale_reason)
        contracts.append(
            {
                "id": _contract_id(slot),
                "option_type": "P" if slot.option_type == "P" else "C",
                "label": _contract_label(slot, candidate),
                "strike": _payload_number(candidate.strike),
                "ask": _payload_number(candidate.ask),
                "bid": _payload_number(candidate.bid),
                "multiplier": OPTION_CONTRACT_MULTIPLIER,
                "expiration": str(candidate.expiration) if candidate.expiration else None,
                "dte": int(candidate.days_to_expiry)
                if candidate.days_to_expiry is not None
                else None,
                "quote_ok": quote_ok,
                "quote_reason": quote_reason,
            }
        )
    price, price_basis = _underlying_price_with_basis(detail)
    return {
        "current_price": _payload_number(price),
        "current_price_basis": price_basis,
        "max_contracts": max_contracts,
        "currency": "USD",
        "contracts": contracts,
    }


def _sizing_slots(detail: OptionTradingDetailData | None) -> list[OptionCandidateSlot]:
    if detail is None:
        return []
    slots = [*detail.put_slots, *detail.call_slots]
    bucket_order = {"near_atm": 0, "directional": 1}
    return sorted(
        [slot for slot in slots if slot.display_candidate is not None],
        key=lambda slot: (
            0 if slot.option_type == "P" else 1,
            slot.horizon_days,
            bucket_order.get(str(slot.bucket or ""), 9),
        ),
    )


def _contract_id(slot: OptionCandidateSlot) -> str:
    side = "put" if slot.option_type == "P" else "call"
    return f"{side}-{int(slot.horizon_days)}-{str(slot.bucket or 'slot')}"


def _contract_label(slot: OptionCandidateSlot, candidate: OptionCandidate) -> str:
    side = "Put" if slot.option_type == "P" else "Call"
    strike = _fmt_number(candidate.strike, decimals=2)
    expiry = str(candidate.expiration) if candidate.expiration else "expiry n/a"
    dte = (
        f" ({int(candidate.days_to_expiry)}d)"
        if candidate.days_to_expiry is not None
        else ""
    )
    return f"{side} ${strike} · {expiry}{dte}"


def _stale_quote_reason(availability: OptionsAvailability) -> str | None:
    """Generation-level staleness, the only staleness the artifacts record.

    There is no per-contract staleness column; when the whole option generation
    was carried forward, every quote in it is stale, so the tool disables rather
    than sizing a position off yesterday's ask.
    """

    if not availability.carried_forward:
        return None
    if availability.carried_forward_from:
        return f"quote stale (carried forward from {availability.carried_forward_from})"
    return "quote stale (carried forward from an earlier snapshot)"


def _quote_verdict(
    slot: OptionCandidateSlot,
    candidate: OptionCandidate,
    *,
    stale_reason: str | None,
) -> tuple[bool, str | None]:
    ask = candidate.ask
    bid = candidate.bid
    if ask is None or ask <= 0:
        return False, "ask missing"
    if bid is not None and bid > ask:
        return False, "crossed quote (bid above ask)"
    if stale_reason:
        return False, stale_reason
    # The backend already stamped its own verdict on the quote. Serve adds the
    # two specific reasons above (which the flag cannot distinguish) but must
    # never OVERRIDE a persisted "this quote is unusable".
    if "invalid_quote" in candidate.quote_flags:
        return False, "the captured quote was flagged unusable"
    if str(slot.status or "").strip().lower() != "accepted":
        return False, str(slot.reason) or "this contract was not accepted for trading"
    return True, None


def _payload_number(value: object) -> float | None:
    """Payload numbers must be JSON-representable.

    ``embed_json_payload`` uses ``allow_nan=False``, so a single non-finite
    persisted value would raise out of the render and take the WHOLE ticker
    page down with it. Non-finite reaches the payload as ``null``, which the JS
    already treats as an unusable quote.
    """

    return optional_finite_float(value)


def _render_sizing_tool(
    *,
    detail: OptionTradingDetailData | None,
    availability: OptionsAvailability,
    app_config: AppConfig | None,
    sizing_request: object | None,
) -> str:
    payload = build_sizing_payload(
        detail=detail, availability=availability, app_config=app_config
    )
    contracts = payload["contracts"]
    if not contracts or payload["current_price"] is None:
        body = (
            "<p class=\"hint\">Position sizing needs at least one quoted contract and a "
            "current share price from the last snapshot; neither is available for this "
            "ticker yet.</p>"
        )
        return disclosure(
            "Work out a position" + help_icon("Work out a position", key="option_sizing_tool"),
            body,
        )

    selected_id = _preselected_contract_id(contracts, sizing_request)
    prefill_budget = _prefill_budget(sizing_request)
    options_html = "".join(
        f"<option value=\"{escape(str(row['id']), quote=True)}\""
        f"{' selected' if row['id'] == selected_id else ''}>"
        f"{escape(str(row['label']))}</option>"
        for row in contracts
    )
    contract_help = help_icon(
        "Contract", key="option_sizing_contract", app_config=app_config
    )
    budget_help = help_icon("Budget", key="option_sizing_budget", app_config=app_config)
    price_help = help_icon(
        "Share price at expiry", key="option_sizing_price", app_config=app_config
    )
    ladder_help = help_icon(
        "Profit and loss at expiry", key="option_sizing_ladder", app_config=app_config
    )
    body = (
        f"<div id=\"{SIZING_ROOT_ID}\" class=\"option-sizing\">"
        "<p class=\"hint\">Pick a contract, set a budget, then drag the share price. "
        "The share price is the input — nothing here is derived from a gold move.</p>"
        "<div class=\"option-sizing-controls\">"
        "<p class=\"field\"><label for=\"option-sizing-contract\">Contract</label>"
        f"{contract_help}"
        "<select id=\"option-sizing-contract\" data-role=\"contract\">"
        f"{options_html}</select></p>"
        "<p class=\"field\"><label for=\"option-sizing-budget\">Budget</label>"
        f"{budget_help}"
        "<input id=\"option-sizing-budget\" data-role=\"budget\" type=\"number\" "
        "min=\"0\" step=\"1\" inputmode=\"decimal\" "
        f"value=\"{escape(prefill_budget, quote=True)}\"></p>"
        "<p class=\"field\"><label for=\"option-sizing-price\">Share price at expiry</label>"
        f"{price_help}"
        "<input id=\"option-sizing-price\" data-role=\"price\" type=\"range\">"
        "<output data-role=\"price-out\" for=\"option-sizing-price\"></output></p>"
        "<p class=\"field\"><button type=\"button\" data-role=\"reset\">Reset</button></p>"
        "</div>"
        "<div data-role=\"result\" class=\"option-sizing-result\">"
        "<p data-role=\"contracts-line\"></p>"
        # The heading lives INSIDE the ladder table (option-sizing.js toggles the
        # table's own [hidden]), so a label can never hang over a hidden ladder.
        # The JS only createTHead()s and swaps <tbody>, so the caption survives.
        "<table data-role=\"ladder\">"
        f"<caption class=\"hint sizing-ladder-head\">Profit and loss at expiry"
        f"{ladder_help}</caption>"
        "</table>"
        f"<p class=\"hint\" data-role=\"footnote\">{escape(_INTRINSIC_ONLY_NOTE)}</p>"
        "</div>"
        "<p class=\"visually-hidden\" data-role=\"live\" role=\"status\" "
        "aria-live=\"polite\"></p>"
        "</div>"
        + embed_json_payload(SIZING_PAYLOAD_ID, payload)
        + f"<script src=\"{SIZING_SCRIPT_SRC}\" defer></script>"
    )
    return disclosure(
        "Work out a position" + help_icon("Work out a position", key="option_sizing_tool"),
        body,
    )


def _preselected_contract_id(
    contracts: Sequence[Mapping[str, Any]],
    sizing_request: object | None,
) -> str | None:
    """Map the legacy ``side``/``horizon``/``bucket`` params onto the new select.

    Old links into the sizing calculator must still land on the contract they
    named, even though the server no longer computes anything for them.
    """

    if not contracts:
        return None
    if sizing_request is None:
        return str(contracts[0]["id"])
    side = str(getattr(sizing_request, "side", "") or "").strip().lower()
    horizon = getattr(sizing_request, "horizon_days", None)
    bucket = str(getattr(sizing_request, "bucket", "") or "").strip().lower()
    ids = [str(row["id"]) for row in contracts]
    if side and horizon is not None and bucket:
        exact = f"{side}-{int(horizon)}-{bucket}"
        if exact in ids:
            return exact
    if side and horizon is not None:
        prefix = f"{side}-{int(horizon)}-"
        for row_id in ids:
            if row_id.startswith(prefix):
                return row_id
    if side:
        for row_id in ids:
            if row_id.startswith(f"{side}-"):
                return row_id
    return ids[0]


def _prefill_budget(sizing_request: object | None) -> str:
    budget = getattr(sizing_request, "budget", None) if sizing_request is not None else None
    numeric = _optional_float(budget)
    if numeric is None or numeric <= 0:
        return ""
    return _fmt_number(numeric, decimals=2)


# ---------------------------------------------------------------------------
# 7. closed: greeks and full chain
# ---------------------------------------------------------------------------

_GREEK_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("candidate_gamma", "Gamma", "per $1 of share price"),
    ("candidate_vega", "Vega", "per volatility point"),
    ("candidate_theta", "Theta", "per calendar day"),
)


def _render_greeks_and_chain(
    *,
    detail: OptionTradingDetailData | None,
    candidate_slots_frame: pd.DataFrame | None,
    ticker: str,
    app_config: AppConfig | None,
) -> str:
    body = (
        _render_greeks_table(candidate_slots_frame, ticker=ticker)
        + _render_liquidity_summary(detail, app_config=app_config)
        + _render_context_table(detail, app_config=app_config)
        + _render_method_notes()
    )
    return disclosure(
        "Greeks and full chain" + help_icon("Greeks and full chain", key="option_greeks"),
        body,
    )


def _render_greeks_table(frame: pd.DataFrame | None, *, ticker: str) -> str:
    rows = _greek_rows(frame, ticker=ticker)
    heading = section_heading(
        "Greeks",
        level=4,
        help_html=help_icon("Greeks", key="option_greeks_units"),
    )
    if not rows:
        return (
            "<div class=\"options-greeks\">"
            + heading
            + "<p class=\"hint\">No persisted greeks are available for this ticker's "
            "candidates yet.</p></div>"
        )
    model_versions = sorted(
        {
            str(row.get("candidate_greeks_model_version") or "").strip()
            for row in rows
            if str(row.get("candidate_greeks_model_version") or "").strip()
        }
    )
    model_note = (
        "<p class=\"hint\">Greeks model: "
        + ", ".join(escape(version) for version in model_versions)
        + ". Gamma is per $1 of share price, vega is per volatility point, and theta "
        "is per calendar day.</p>"
        if model_versions
        else ""
    )
    body_rows = "".join(
        "<tr>"
        f"<td>{escape(_greek_row_label(row))}</td>"
        f"<td>{_fmt_text(row.get('candidate_expiration'))}"
        f"{_dte_suffix(row.get('candidate_days_to_expiry'))}</td>"
        f"<td>{_fmt_number(row.get('candidate_strike'), decimals=2)}</td>"
        + "".join(
            f"<td>{_fmt_number(row.get(column), decimals=4)}</td>"
            for column, _, _ in _GREEK_COLUMNS
        )
        + "</tr>"
        for row in rows
    )
    return (
        "<div class=\"options-greeks\">"
        + heading
        + table_region(
            "<table><thead><tr>"
            "<th>Contract</th><th>Expiry (DTE)</th><th>Strike</th>"
            + "".join(
                f"<th>{escape(label)} <span class=\"unit-label\">({escape(unit)})</span></th>"
                for _, label, unit in _GREEK_COLUMNS
            )
            + "</tr></thead>"
            f"<tbody>{body_rows}</tbody></table>",
            region_id="options-greeks-region",
            label="Greeks by candidate contract",
        )
        + model_note
        + "</div>"
    )


def _greek_row_label(row: Mapping[str, Any]) -> str:
    side = "Put" if str(row.get("option_type") or "").strip().upper() == "P" else "Call"
    horizon = row.get("horizon_days")
    horizon_text = f"{int(horizon)}d" if horizon is not None and pd.notna(horizon) else "?"
    return f"{side} {bucket_label(row.get('bucket'))} · {horizon_text} target"


def _greek_rows(frame: pd.DataFrame | None, *, ticker: str) -> list[dict[str, Any]]:
    matches = _rows_for(frame, ticker)
    if not matches:
        return []
    greek_columns = [column for column, _, _ in _GREEK_COLUMNS if column in matches[0]]
    if not greek_columns:
        return []
    rows = [
        row
        for row in matches
        if any(_optional_float(row.get(column)) is not None for column in greek_columns)
    ]
    bucket_order = {"near_atm": 0, "directional": 1}
    return sorted(
        rows,
        key=lambda row: (
            0 if str(row.get("option_type") or "").upper() == "P" else 1,
            _optional_float(row.get("horizon_days")) or 0.0,
            bucket_order.get(str(row.get("bucket") or ""), 9),
        ),
    )


def _render_liquidity_summary(
    detail: OptionTradingDetailData | None, *, app_config: AppConfig | None = None
) -> str:
    if detail is None:
        return ""
    put_counts = slot_tier_counts(detail.put_slots)
    call_counts = slot_tier_counts(detail.call_slots)
    return (
        "<div class=\"options-liquidity-summary\">"
        + section_heading(
            "Liquidity across every window",
            level=4,
            help_html=help_icon(
                "Liquidity across every window",
                key="option_liquidity_windows",
                app_config=app_config,
            ),
        )
        + "<div class=\"metric-grid\">"
        + _metric_card(
            "Put tradable", _fmt_number(put_counts["tradable"], decimals=0),
            help_key="tradable_count",
            app_config=app_config,
        )
        + _metric_card(
            "Put watch", _fmt_number(put_counts["watch"], decimals=0),
            help_key="watch_count",
            app_config=app_config,
        )
        + _metric_card(
            "Put no-trade", _fmt_number(put_counts["no_trade"], decimals=0),
            help_key="no_trade_count",
            app_config=app_config,
        )
        + _metric_card(
            "Call tradable", _fmt_number(call_counts["tradable"], decimals=0),
            help_key="tradable_count",
            app_config=app_config,
        )
        + _metric_card(
            "Call watch", _fmt_number(call_counts["watch"], decimals=0),
            help_key="watch_count",
            app_config=app_config,
        )
        + _metric_card(
            "Call no-trade", _fmt_number(call_counts["no_trade"], decimals=0),
            help_key="no_trade_count",
            app_config=app_config,
        )
        + "</div></div>"
    )


def _render_context_table(
    detail: OptionTradingDetailData | None,
    *,
    app_config: AppConfig | None,
) -> str:
    context = detail.source_context if detail is not None else None
    if context is None:
        return ""
    price, price_basis = _underlying_price_with_basis(detail)
    # A fallback risk-free rate is a data-quality fact about the greeks above,
    # so it stays visible rather than being silently absorbed.
    fallback_note = (
        "<p class=\"hint\">The risk-free rate was missing from the options manifest, "
        "so the greeks above were computed with a 0% rate fallback.</p>"
        if detail is not None and detail.risk_free_rate_is_fallback
        else ""
    )
    rows = (
        "<tr>"
        + help_th("Share price used", key="option_stock_price")
        + f"<td>{_fmt_number(price, decimals=2)}"
        + (
            f" <span class=\"hint\">from the {escape(price_basis)}</span>"
            if price_basis
            else ""
        )
        + "</td></tr>"
        "<tr>"
        + help_th("Snapshot date", key="option_snapshot_date")
        + f"<td>{_fmt_text(getattr(context, 'as_of_date', None))}</td></tr>"
        "<tr>"
        + help_th("Data source", key="option_data_source")
        + f"<td>{_fmt_text(getattr(context, 'source', None))}</td></tr>"
        "<tr>"
        + help_th("Risk-free rate", key="option_risk_free_rate", app_config=app_config)
        + f"<td>{_fmt_percent(getattr(context, 'risk_free_rate', None), decimals=2)}</td></tr>"
        "<tr>"
        + help_th("Refresh run", key="option_refresh_run")
        + f"<td>{_fmt_text(getattr(context, 'refresh_run_id', None))}</td></tr>"
    )
    return (
        "<div class=\"options-context\">"
        + section_heading("Where these numbers came from", level=4)
        + table_region(
            f"<table><tbody>{rows}</tbody></table>",
            region_id="options-context-region",
            label="Option data provenance",
        )
        + fallback_note
        + "</div>"
    )


def _render_method_notes() -> str:
    return (
        "<div class=\"options-method\">"
        + section_heading("Method", level=4)
        + "<p>Contracts are selected during refresh from the captured option chain. "
        "Tradable rows passed the stricter spread and open-interest checks; watch rows "
        "passed the relaxed checks and can be expensive to enter or exit.</p>"
        "<p>Open interest is the number of contracts currently open. Volume is what "
        "traded that day. Spread is ask minus bid over mid — lower is usually better. "
        "Delta is shown as context, not as the bucket rule.</p>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# shared small helpers
# ---------------------------------------------------------------------------


def _display_horizons(app_config: AppConfig | None) -> tuple[int, ...]:
    if app_config is None:
        return ()
    return tuple(int(value) for value in app_config.hedge_readiness.display_horizons_days)


def resolve_target_window(
    requested: int | None,
    app_config: AppConfig | None,
) -> int | None:
    """THE Target-window fallback rule — one copy, used by the route and the chips.

    Anything the config does not list (a typo, a stale bookmark, a horizon that
    was removed) falls back to the signal horizon, else the first configured
    window — never to an empty table.
    """

    horizons = _display_horizons(app_config)
    if not horizons:
        return requested
    if requested is not None and int(requested) in horizons:
        return int(requested)
    signal = _signal_horizon(None, app_config)
    if signal is not None and signal in horizons:
        return signal
    return horizons[0]


def _signal_horizon(
    detail: OptionTradingDetailData | None,
    app_config: AppConfig | None,
) -> int | None:
    if detail is not None:
        stamped = signal_horizon_from_row(detail.signal_row)
        if stamped is not None:
            return int(stamped)
    if app_config is None:
        return None
    return int(app_config.hedge_readiness.option_signal_horizon_days)


def _slots_for_window(
    slots: Sequence[OptionCandidateSlot],
    window: int | None,
) -> list[OptionCandidateSlot]:
    bucket_order = {"near_atm": 0, "directional": 1}
    selected = [
        slot
        for slot in slots
        if window is None or int(slot.horizon_days) == int(window)
    ]
    return sorted(
        selected,
        key=lambda slot: bucket_order.get(str(slot.bucket or ""), 9),
    )


def _underlying_price(detail: OptionTradingDetailData | None) -> float | None:
    return _underlying_price_with_basis(detail)[0]


def _underlying_price_with_basis(
    detail: OptionTradingDetailData | None,
) -> tuple[float | None, str | None]:
    """The persisted underlying price AND which persisted column it came from.

    Two persisted columns can carry it, so the choice is reported rather than
    hidden: an unlabelled price is exactly the kind of silent assumption the
    repo's basis rule exists to stop. The order matches the old panel's, so the
    number itself is unchanged.
    """

    if detail is None:
        return None, None
    price = detail.row.current_stock_price if detail.row is not None else None
    if price:
        return price, "option trading row (current_stock_price)"
    for slot in (*detail.put_slots, *detail.call_slots):
        candidate = slot.display_candidate
        if candidate is not None and candidate.underlying_price > 0:
            return candidate.underlying_price, "candidate contract (underlying_price)"
    return None, None


def _chain_history_for(
    page_artifacts: OptionPageArtifacts | None,
    ticker: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    if page_artifacts is None:
        return None, [], None
    rows = _rows_for(page_artifacts.chain_history, ticker)
    if not rows:
        return None, [], None
    rows = sorted(rows, key=lambda row: str(row.get("as_of_date") or ""))
    # The headline cards and the put/call sentences may only quote a COMPLETE
    # capture. A truncated capture undercounts the chain, so publishing its
    # ratio as "positioning leans bullish" would be a confident headline built
    # on degraded data — excluded, not merely flagged. The chart already draws
    # incomplete days as gaps; this keeps the numbers beside it honest too.
    complete = [row for row in rows if _capture_is_complete(row)]
    if complete:
        skipped = str(rows[-1].get("as_of_date") or "") if rows[-1] is not complete[-1] else None
        return complete[-1], rows, skipped
    return None, rows, str(rows[-1].get("as_of_date") or "")


#: The producer's coverage-flag tokens, in plain English. Anything unmapped
#: falls back to its own token so a new backend flag is visible, not swallowed.
_CAPTURE_FLAG_WORDS: dict[str, str] = {
    "coverage_floor": "fewer contracts than usual were captured",
    "n_contracts": "contract count below the trailing floor",
    "n_expirations": "expiry count below the trailing floor",
    "put_n_contracts": "put side below the trailing floor",
    "call_n_contracts": "call side below the trailing floor",
    "total_open_interest": "total open interest below the trailing floor",
    "expiry_floor": "too few expiries captured",
}


def _capture_reason(row: Mapping[str, Any]) -> str:
    """Turn ``PARTIAL:coverage_floor,n_contracts`` into a sentence.

    The producer packs its coverage flags into the label; rendering the raw
    token would leak an internal enum into user-facing copy.
    """

    label = str(row.get("capture_quality") or "").strip()
    if _capture_is_complete(row):
        return "complete capture"
    _, _, flags = label.partition(":")
    words = [
        _CAPTURE_FLAG_WORDS.get(flag.strip(), flag.strip())
        for flag in flags.split(",")
        if flag.strip()
    ]
    if not words:
        return "incomplete capture"
    return "incomplete capture: " + ", ".join(words)


def _capture_is_complete(row: Mapping[str, Any]) -> bool:
    quality = str(row.get("capture_quality") or "").strip().upper()
    return not quality or quality == _CAPTURE_COMPLETE
