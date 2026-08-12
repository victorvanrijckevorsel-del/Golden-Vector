"""Render tests for the redesigned ticker-page Options section (M3d).

Fixture-driven throughout: no test here reads ``data/``. The five availability
states each get a control fixture, because the load-bearing promise of this
section is that exactly ONE of them may hide it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_availability import (
    AVAILABILITY_FETCH_FAILED,
    AVAILABILITY_FILTERED_WINDOW_EMPTY,
    AVAILABILITY_LISTED,
    AVAILABILITY_NONE_LISTED,
)
from golden_vector.hedge.option_trading import (
    OptionSizingRequest,
    OptionTradingDetailData,
    OptionTradingRow,
    OptionTradingSourceContext,
)
from golden_vector.serve.detail_page import render_detail_page
from golden_vector.serve.option_trading_data import (
    OPTION_PAGE_MISSING,
    OPTION_PAGE_OK,
    OPTION_PAGE_UNAVAILABLE_PRE_V4,
    OPTION_PAGE_UNREADABLE,
    OptionPageArtifacts,
)
from golden_vector.serve.ticker_page import SIZING_PAYLOAD_ID, render_options_section
from golden_vector.serve.workspace_state import WorkspaceState


TICKER = "AEM"


@pytest.fixture(scope="module")
def app_config():
    return load_app_config(ProjectPaths.discover()).app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def availability_frame(status: str = AVAILABILITY_LISTED, *, ticker: str = TICKER):
    """One universe-complete availability artifact plus a healthy control row.

    The control (a second ticker that is always LISTED) is what proves an
    exclusion test excluded the SUBJECT rather than everything.
    """

    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "availability_status": status,
                "expirations_enumerated": 0 if status == AVAILABILITY_NONE_LISTED else 12,
                "fetch_status": "EMPTY" if status == AVAILABILITY_NONE_LISTED else "SUCCESS",
                "fetch_message": None,
                "provider": "yahoo",
                "capture_date": "2026-08-11",
                "schema_version": 1,
            },
            {
                "ticker": "CONTROL",
                "availability_status": AVAILABILITY_LISTED,
                "expirations_enumerated": 9,
                "fetch_status": "SUCCESS",
                "fetch_message": None,
                "provider": "yahoo",
                "capture_date": "2026-08-11",
                "schema_version": 1,
            },
        ]
    )


def chain_history_frame(rows=None, *, ticker: str = TICKER):
    defaults = [
        _history_row(ticker, "2026-08-07", put_oi=200_000, call_oi=300_000),
        _history_row(ticker, "2026-08-10", put_oi=205_000, call_oi=310_000),
        _history_row(ticker, "2026-08-11", put_oi=211_900, call_oi=322_506),
    ]
    return pd.DataFrame(rows if rows is not None else defaults)


def _history_row(
    ticker: str,
    as_of_date: str,
    *,
    put_oi: int,
    call_oi: int,
    ratio_total: float = 0.66,
    ratio_otm: float = 1.42,
    capture_quality: str = "COMPLETE",
) -> dict:
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "total_open_interest": put_oi + call_oi,
        "put_oi_total": put_oi,
        "call_oi_total": call_oi,
        "put_oi_otm": 90_000,
        "call_oi_otm": 63_000,
        "put_call_oi_ratio_total": ratio_total,
        "put_call_oi_ratio_otm": ratio_otm,
        "total_volume": 12_400,
        "put_volume": 5_100,
        "call_volume": 7_300,
        "n_contracts": 830,
        "n_expirations": 14,
        "put_n_contracts": 420,
        "call_n_contracts": 410,
        "capture_quality": capture_quality,
        "row_status": "observed",
        "oi_split_backfilled": False,
        "capture_run_id": "options-run",
        "published_run_id": "options-run",
        "schema_version": 1,
    }


def page_artifacts(
    *,
    state: str = OPTION_PAGE_OK,
    status: str = AVAILABILITY_LISTED,
    reason: str | None = None,
    freshness_status: str | None = "OK",
    as_of_date: str | None = "2026-08-11",
    history=None,
) -> OptionPageArtifacts:
    return OptionPageArtifacts(
        state=state,
        reason=reason,
        generation_schema_version=4,
        availability=availability_frame(status),
        chain_history=chain_history_frame(history),
        freshness_status=freshness_status,
        freshness_as_of_date=as_of_date,
        freshness_message="Option prices are from the latest stored snapshot: 2026-08-11.",
    )


def candidate(
    *,
    option_type: str = "P",
    horizon_days: int = 90,
    strike: float = 12.0,
    bid: float | None = 0.80,
    ask: float | None = 0.85,
    expiration: str = "2026-11-20",
    days_to_expiry: int = 100,
    liquidity_tier: str = "tradable",
    bucket: str = "near_atm",
    quote_flags: tuple[str, ...] = (),
) -> OptionCandidate:
    return OptionCandidate(
        ticker=TICKER,
        horizon_days=horizon_days,
        expiration=expiration,
        days_to_expiry=days_to_expiry,
        strike=strike,
        bid=bid,
        ask=ask,
        mid=0.82,
        open_interest=1_450,
        volume=63,
        implied_volatility=0.42,
        delta=-0.28,
        delta_gap=0.03,
        premium_pct_spot=0.066,
        underlying_price=12.34,
        last_price=0.83,
        option_type=option_type,
        bucket=bucket,
        liquidity_tier=liquidity_tier,
        rel_spread=0.06,
        half_spread_cost_pct=0.03,
        liquidity_score=0.8,
        moneyness_pct=0.02,
        otm_pct=0.02,
        quote_flags=quote_flags,
    )


def slot(
    *,
    option_type: str = "P",
    horizon_days: int = 90,
    bucket: str = "near_atm",
    status: str = "accepted",
    reason: str = "Near-ATM candidate passed the strict liquidity checks.",
    contract: OptionCandidate | None = None,
    rejected: OptionCandidate | None = None,
    liquidity_tier: str = "tradable",
) -> OptionCandidateSlot:
    resolved = contract if contract is not None else candidate(
        option_type=option_type, horizon_days=horizon_days, bucket=bucket
    )
    return OptionCandidateSlot(
        ticker=TICKER,
        option_type=option_type,
        horizon_days=horizon_days,
        target_delta=-0.25,
        expiration=(resolved or rejected).expiration if (resolved or rejected) else None,
        days_to_expiry=(resolved or rejected).days_to_expiry
        if (resolved or rejected)
        else None,
        status=status,
        reason=reason,
        candidate=resolved if status == "accepted" else None,
        rejected_candidate=rejected if status != "accepted" else None,
        listed_contract_count=52,
        tradable_contract_count=7,
        bucket=bucket,
        liquidity_tier=liquidity_tier,
    )


def detail(*, put_slots=None, call_slots=None, reason: str | None = None):
    return OptionTradingDetailData(
        ticker=TICKER,
        row=OptionTradingRow(
            ticker=TICKER,
            structural_delta_core=1.33,
            down_beta_core=1.33,
            up_beta_core=1.16,
            confidence_label="HIGH",
            confidence_score=0.9,
            iv_percentile_cross_sectional=29.5,
            iv_skew_signal=None,
            iv_rv_ratio_signal=None,
            optionability_tier="directly_hedgeable",
            put_status="tradable",
            call_status="tradable",
            pnl_put_at_context=None,
            pnl_call_at_context=None,
            notes=(),
            current_stock_price=12.34,
        ),
        put_candidates=(),
        put_bundles=(),
        put_slots=tuple(put_slots if put_slots is not None else (slot(),)),
        call_slots=tuple(
            call_slots
            if call_slots is not None
            else (slot(option_type="C", contract=candidate(option_type="C")),)
        ),
        reason=reason,
        source_context=OptionTradingSourceContext(
            as_of_date="2026-08-11",
            refresh_run_id="options-run",
            tool_a_refresh_run_ids=("tool-run",),
            tool_b_refresh_run_ids=("tool-run",),
            context_warnings=(),
            risk_free_rate=0.041,
        ),
    )


def slots_frame(rows=None) -> pd.DataFrame:
    defaults = [
        {
            "ticker": TICKER,
            "option_type": "P",
            "horizon_days": 90,
            "bucket": "near_atm",
            "status": "accepted",
            "candidate_strike": 12.0,
            "candidate_expiration": "2026-11-20",
            "candidate_days_to_expiry": 100,
            "candidate_gamma": 0.0812,
            "candidate_vega": 0.0231,
            "candidate_theta": -0.0044,
            "candidate_greeks_model_version": "black_scholes_q0_v1",
        },
        {
            "ticker": "CONTROL",
            "option_type": "C",
            "horizon_days": 90,
            "bucket": "near_atm",
            "status": "accepted",
            "candidate_strike": 44.0,
            "candidate_expiration": "2026-11-20",
            "candidate_days_to_expiry": 100,
            "candidate_gamma": 0.9999,
            "candidate_vega": 0.8888,
            "candidate_theta": -0.7777,
            "candidate_greeks_model_version": "black_scholes_q0_v1",
        },
    ]
    return pd.DataFrame(rows if rows is not None else defaults)


def render(app_config, **overrides) -> str:
    kwargs = {
        "ticker": TICKER,
        "detail": detail(),
        "page_artifacts": page_artifacts(),
        "candidate_slots_frame": slots_frame(),
        "app_config": app_config,
    }
    kwargs.update(overrides)
    return render_options_section(**kwargs)


# ---------------------------------------------------------------------------
# 1. the five availability states
# ---------------------------------------------------------------------------


def test_none_listed_removes_the_section_entirely(app_config):
    html = render(app_config, page_artifacts=page_artifacts(status=AVAILABILITY_NONE_LISTED))

    assert html == ""


def test_none_listed_for_one_ticker_does_not_hide_the_control(app_config):
    """The exclusion must be about THIS ticker, not the whole artifact."""

    artifacts = page_artifacts(status=AVAILABILITY_NONE_LISTED)
    assert render(app_config, page_artifacts=artifacts) == ""

    control = render_options_section(
        ticker="CONTROL",
        detail=detail(),
        page_artifacts=artifacts,
        candidate_slots_frame=slots_frame(),
        app_config=app_config,
    )
    assert control != ""
    assert 'id="options"' in control


def test_current_coherent_data_renders_full_section_with_as_of_date(app_config):
    html = render(app_config)

    assert 'id="options"' in html
    assert "Option data as of 2026-08-11" in html
    assert "Market context" in html
    assert "Most liquid contracts" in html
    assert "carried forward" not in html.lower()


def test_carried_forward_generation_labels_itself(app_config):
    html = render(
        app_config,
        page_artifacts=page_artifacts(freshness_status="CARRIED_FORWARD"),
    )

    assert "Carried forward from 2026-08-11" in html
    assert "Market context" in html
    assert 'id="options"' in html


@pytest.mark.parametrize(
    ("state", "status", "reason"),
    [
        (OPTION_PAGE_MISSING, AVAILABILITY_LISTED, "the option_availability artifact is missing"),
        (OPTION_PAGE_UNREADABLE, AVAILABILITY_LISTED, "the artifact could not be read (bad magic)"),
    ],
)
def test_missing_or_corrupt_artifact_degrades_with_a_reason(app_config, state, status, reason):
    html = render(
        app_config,
        page_artifacts=page_artifacts(state=state, status=status, reason=reason),
    )

    assert html != ""
    assert 'id="options"' in html
    assert reason in html
    assert "no options" not in html.lower()


def test_misaligned_generation_degrades_rather_than_claiming_no_options(app_config):
    html = render(app_config, page_artifacts=page_artifacts(freshness_status="MISALIGNED"))

    assert html != ""
    assert "unavailable right now" in html
    assert "no options" not in html.lower()


def test_fetch_failed_is_a_data_gap_not_an_absence(app_config):
    html = render(app_config, page_artifacts=page_artifacts(status=AVAILABILITY_FETCH_FAILED))

    assert html != ""
    assert "the last option capture for this ticker failed" in html
    assert "no options" not in html.lower()


def test_pre_v4_generation_says_awaiting_first_v4_refresh(app_config):
    html = render(
        app_config,
        page_artifacts=page_artifacts(state=OPTION_PAGE_UNAVAILABLE_PRE_V4),
    )

    assert html != ""
    assert "awaiting first v4 refresh" in html
    assert "no options" not in html.lower()


def test_listed_with_no_eligible_candidates_keeps_market_context(app_config):
    html = render(
        app_config,
        page_artifacts=page_artifacts(status=AVAILABILITY_FILTERED_WINDOW_EMPTY),
        detail=detail(put_slots=(), call_slots=(), reason=None),
    )

    assert "Market context" in html
    assert "Put/call open interest" in html
    assert "no listed expiry fell inside the configured capture window" in html
    assert "no options" not in html.lower()


@pytest.mark.parametrize(
    ("artifacts", "expected"),
    [
        (page_artifacts(status=AVAILABILITY_NONE_LISTED), False),
        (page_artifacts(), True),
        (page_artifacts(freshness_status="CARRIED_FORWARD"), True),
        (page_artifacts(state=OPTION_PAGE_MISSING, reason="gone"), True),
        (page_artifacts(state=OPTION_PAGE_UNAVAILABLE_PRE_V4), True),
        (page_artifacts(status=AVAILABILITY_FILTERED_WINDOW_EMPTY), True),
    ],
)
def test_nav_anchor_follows_the_availability_outcome(app_config, artifacts, expected):
    """The nav entry exists exactly when the section does — both directions."""

    page = render_detail_page(
        _empty_workspace_state(),
        ticker=TICKER,
        tool_a_detail=None,
        flash=None,
        app_config=app_config,
        option_trading_detail=detail(),
        option_page_artifacts=artifacts,
        option_candidate_slots_frame=slots_frame(),
        show_workspace_panels=False,
        show_manual_sections=False,
    )

    has_nav = '<a class="section-nav-link" href="#options">Options</a>' in page
    assert has_nav is expected
    assert ('id="options"' in page) is expected


def _empty_workspace_state() -> WorkspaceState:
    empty = pd.DataFrame()
    return WorkspaceState(
        tool_b_tickers=[TICKER],
        foundation_manifest=None,
        company_inputs=empty,
        source_verification=empty,
        reporting_calendar=empty,
        stock_notes=empty,
        latest_tool_a=empty,
        latest_tool_b=empty,
        latest_tool_c=empty,
        latest_tool_d=empty,
        tool_a_alias_present=False,
        tool_b_alias_present=False,
        tool_c_alias_present=False,
        tool_d_alias_present=False,
        model_state_manifest=None,
    )


def test_misaligned_generation_never_hides_the_section_even_when_none_listed(app_config):
    """A misaligned generation is not current, so its NONE_LISTED cannot hide it.

    Self-review P1: a company that has since listed options would otherwise
    lose its whole section off an artifact the code itself calls untrustworthy.
    """

    html = render(
        app_config,
        page_artifacts=page_artifacts(
            status=AVAILABILITY_NONE_LISTED, freshness_status="MISALIGNED"
        ),
    )

    assert html != ""
    assert 'id="options"' in html
    assert "unavailable right now" in html


def test_carried_forward_without_a_date_still_warns_and_locks_sizing(app_config):
    """The manifest may omit as_of_date; staleness must key on the STATUS.

    Self-review P1: keying on the date let a dateless carried-forward
    generation render as fully fresh AND re-enable position sizing on stale asks.
    """

    html = render(
        app_config,
        page_artifacts=page_artifacts(freshness_status="CARRIED_FORWARD", as_of_date=None),
    )

    assert "Carried forward from an earlier snapshot" in html
    payload = _payload(html)
    assert payload["contracts"][0]["quote_ok"] is False
    assert payload["contracts"][0]["quote_reason"] == (
        "quote stale (carried forward from an earlier snapshot)"
    )


def test_a_non_finite_persisted_number_does_not_take_the_page_down(app_config):
    """embed_json_payload uses allow_nan=False, so inf must reach it as null."""

    broken = slot(contract=candidate(strike=float("inf")))
    html = render(app_config, detail=detail(put_slots=(broken,), call_slots=()))

    assert _payload(html)["contracts"][0]["strike"] is None


def test_a_backend_flagged_quote_cannot_be_sized(app_config):
    """The persisted `invalid_quote` flag is the backend's own verdict."""

    flagged = slot(contract=candidate(quote_flags=("invalid_quote",)))
    payload = _payload(render(app_config, detail=detail(put_slots=(flagged,), call_slots=())))

    assert payload["contracts"][0]["quote_ok"] is False
    assert payload["contracts"][0]["quote_reason"] == "the captured quote was flagged unusable"


def test_the_share_price_states_which_persisted_column_it_came_from(app_config):
    html = render(app_config)
    payload = _payload(html)

    assert payload["current_price_basis"] == "option trading row (current_stock_price)"
    assert "from the option trading row (current_stock_price)" in html


# ---------------------------------------------------------------------------
# 2. the ratio pair — the disagreement IS the insight
# ---------------------------------------------------------------------------


def test_both_ratios_render_with_their_readings_and_the_disagreement(app_config):
    html = render(app_config)

    assert "Whole chain" in html and "0.66" in html
    assert "Out-of-the-money only" in html and "1.42" in html
    assert "211,900" in html and "322,506" in html
    assert "More calls than puts overall, so positioning leans bullish." in html
    assert "Puts outnumber calls where speculation and hedging live" in html
    assert "These two disagree, and the disagreement is the point" in html


def test_agreeing_ratios_render_no_disagreement_sentence(app_config):
    rows = [
        _history_row(
            TICKER, "2026-08-11", put_oi=400_000, call_oi=200_000,
            ratio_total=2.0, ratio_otm=1.8,
        )
    ]
    html = render(app_config, page_artifacts=page_artifacts(history=rows))

    assert "2.00" in html and "1.80" in html
    assert "More puts than calls overall" in html
    assert "These two disagree" not in html


def test_ratio_disagreement_the_other_way_round(app_config):
    rows = [
        _history_row(
            TICKER, "2026-08-11", put_oi=400_000, call_oi=200_000,
            ratio_total=2.0, ratio_otm=0.7,
        )
    ]
    html = render(app_config, page_artifacts=page_artifacts(history=rows))

    assert "These two disagree, and the disagreement is the point: more puts overall" in html


# ---------------------------------------------------------------------------
# 3. the trend chart — incomplete captures are gaps, never smoothed
# ---------------------------------------------------------------------------


def test_partial_capture_day_is_a_gap_with_a_reason(app_config):
    rows = [
        _history_row(TICKER, "2026-08-07", put_oi=200_000, call_oi=300_000),
        # The producer packs its coverage flags into the label
        # (hedge/chain_history.py::_quality_label) — a bare "PARTIAL" is
        # unreachable in production, so the fixture uses the real shape.
        _history_row(
            TICKER, "2026-08-10", put_oi=11_111, call_oi=22_222,
            capture_quality="PARTIAL:coverage_floor,n_contracts",
        ),
        _history_row(TICKER, "2026-08-11", put_oi=211_900, call_oi=322_506),
    ]
    html = render(app_config, page_artifacts=page_artifacts(history=rows))

    # The partial day's OI values appear nowhere — not in the line, not in the twin.
    assert "11,111" not in html
    assert "22,222" not in html
    assert "11111" not in html
    # ...but the day and a PLAIN-ENGLISH reason do. The internal flag tokens
    # must never leak into user copy.
    assert "2026-08-10 (incomplete capture:" in html
    assert "fewer contracts than usual were captured" in html
    assert "contract count below the trailing floor" in html
    assert "coverage_floor," not in html
    assert "smoothing over it would invent a dip" in html
    # The complete days still render.
    assert "211,900" in html


def test_a_partial_latest_capture_never_becomes_the_headline_ratio(app_config):
    """Degraded data is EXCLUDED from confident headlines, not merely flagged.

    Self-review P1: the ratio cards read `rows[-1]`, so one truncated capture
    would have the page announce that positioning had flipped when the only
    thing that changed was that half the chain was not fetched.
    """

    rows = [
        _history_row(
            TICKER, "2026-08-10", put_oi=211_900, call_oi=322_506,
            ratio_total=0.66, ratio_otm=1.42,
        ),
        _history_row(
            TICKER, "2026-08-11", put_oi=9_999, call_oi=1_111,
            ratio_total=9.01, ratio_otm=8.02,
            capture_quality="PARTIAL:coverage_floor",
        ),
    ]
    html = render(app_config, page_artifacts=page_artifacts(history=rows))

    # The headline quotes the last COMPLETE day...
    assert "0.66" in html and "1.42" in html
    assert "211,900" in html
    # ...never the truncated one.
    assert "9.01" not in html
    assert "8.02" not in html
    assert "9,999" not in html
    assert "As of 2026-08-11" not in html
    assert "As of 2026-08-10" in html
    assert "2026-08-11" in html  # still listed as a gap in the chart note


def test_when_every_capture_is_partial_the_ratios_are_withheld(app_config):
    rows = [
        _history_row(
            TICKER, "2026-08-11", put_oi=9_999, call_oi=1_111,
            ratio_total=9.01, ratio_otm=8.02,
            capture_quality="PARTIAL:coverage_floor",
        ),
    ]
    html = render(app_config, page_artifacts=page_artifacts(history=rows))

    assert "9.01" not in html
    assert "No daily option-chain history" in html or "not available" in html
    assert 'id="options"' in html


def test_three_open_interest_series_are_drawn_separately(app_config):
    html = render(app_config)

    assert "Put open interest" in html
    assert "Call open interest" in html
    assert "Total open interest" in html
    assert "Open interest over time" in html


def test_daily_volume_is_labelled_with_its_as_of_date(app_config):
    html = render(app_config)

    assert "Daily volume" in html
    assert "Contracts traded on 2026-08-11" in html
    assert "5,100" in html and "7,300" in html and "12,400" in html


# ---------------------------------------------------------------------------
# 4. contracts — the Target window, real expiries, per-row DTE
# ---------------------------------------------------------------------------


def test_target_window_selector_lists_the_configured_horizons(app_config):
    html = render(app_config)

    assert "Target window" in html
    for horizon in app_config.hedge_readiness.display_horizons_days:
        assert f">{horizon}d</a>" in html


def test_invalid_target_window_falls_back_to_a_configured_one(app_config):
    html = render(app_config, target_window=7)

    assert 'aria-current="true"' in html
    assert ">7d</a>" not in html


def test_every_contract_row_shows_its_own_expiry_and_dte(app_config):
    html = render(app_config)

    assert "2026-11-20" in html
    assert "(100 DTE)" in html


def test_put_and_call_rows_may_show_different_expiries(app_config):
    put = slot(contract=candidate(expiration="2026-11-20", days_to_expiry=100))
    call = slot(
        option_type="C",
        contract=candidate(
            option_type="C", expiration="2026-12-18", days_to_expiry=128, strike=13.0
        ),
    )
    html = render(app_config, detail=detail(put_slots=(put,), call_slots=(call,)))

    assert "2026-11-20" in html and "(100 DTE)" in html
    assert "2026-12-18" in html and "(128 DTE)" in html
    assert "different expiry dates inside the same target window" in html


def test_non_ok_candidate_row_renders_its_persisted_reason(app_config):
    rejected = slot(
        status="rejected",
        reason="Spread 41.2% is wider than the relaxed 35% gate.",
        rejected=candidate(liquidity_tier="no_trade"),
        liquidity_tier="no_trade",
    )
    html = render(app_config, detail=detail(put_slots=(rejected,), call_slots=()))

    assert "Spread 41.2% is wider than the relaxed 35% gate." in html
    assert "No-trade" in html


def test_slot_without_a_contract_renders_its_reason_not_a_blank_row(app_config):
    empty = OptionCandidateSlot(
        ticker=TICKER,
        option_type="P",
        horizon_days=90,
        target_delta=-0.25,
        expiration=None,
        days_to_expiry=None,
        status="no_chain",
        reason="No listed contract fell inside the 75-104 day band.",
        bucket="directional",
    )
    html = render(app_config, detail=detail(put_slots=(empty,), call_slots=()))

    assert "No listed contract fell inside the 75-104 day band." in html
    assert "No candidate" in html


# ---------------------------------------------------------------------------
# 5. the sizing payload — the frozen option-sizing.js contract
# ---------------------------------------------------------------------------


def _payload(html: str) -> dict:
    match = re.search(
        rf'<script type="application/json" id="{SIZING_PAYLOAD_ID}">(.*?)</script>',
        html,
        flags=re.S,
    )
    assert match, "sizing payload script block is missing"
    return json.loads(match.group(1))


def test_sizing_payload_parses_and_mirrors_the_persisted_fields(app_config):
    payload = _payload(render(app_config))

    assert payload["current_price"] == 12.34
    assert payload["max_contracts"] == app_config.ticker_page.sizing.max_contracts
    assert payload["currency"] == "USD"
    put = next(row for row in payload["contracts"] if row["option_type"] == "P")
    assert put["id"] == "put-90-near_atm"
    assert put["strike"] == 12.0
    assert put["ask"] == 0.85
    assert put["bid"] == 0.80
    assert put["multiplier"] == 100
    assert put["expiration"] == "2026-11-20"
    assert put["dte"] == 100
    assert put["quote_ok"] is True
    assert put["quote_reason"] is None
    assert "2026-11-20" in put["label"]


def test_sizing_payload_flags_a_missing_ask(app_config):
    broken = slot(contract=candidate(ask=None))
    payload = _payload(render(app_config, detail=detail(put_slots=(broken,), call_slots=())))

    row = payload["contracts"][0]
    assert row["quote_ok"] is False
    assert row["quote_reason"] == "ask missing"


def test_sizing_payload_flags_a_zero_ask(app_config):
    broken = slot(contract=candidate(ask=0.0))
    payload = _payload(render(app_config, detail=detail(put_slots=(broken,), call_slots=())))

    assert payload["contracts"][0]["quote_reason"] == "ask missing"


def test_sizing_payload_flags_a_crossed_quote(app_config):
    crossed = slot(contract=candidate(bid=0.55, ask=0.40))
    payload = _payload(render(app_config, detail=detail(put_slots=(crossed,), call_slots=())))

    row = payload["contracts"][0]
    assert row["quote_ok"] is False
    assert row["quote_reason"] == "crossed quote (bid above ask)"


def test_sizing_payload_flags_a_carried_forward_generation_as_stale(app_config):
    payload = _payload(
        render(app_config, page_artifacts=page_artifacts(freshness_status="CARRIED_FORWARD"))
    )

    row = payload["contracts"][0]
    assert row["quote_ok"] is False
    assert row["quote_reason"] == "quote stale (carried forward from 2026-08-11)"


def test_sizing_payload_uses_the_persisted_reason_for_a_non_ok_status(app_config):
    rejected = slot(
        status="rejected",
        reason="Open interest 3 is below the 50-contract gate.",
        rejected=candidate(liquidity_tier="no_trade"),
    )
    payload = _payload(render(app_config, detail=detail(put_slots=(rejected,), call_slots=())))

    row = payload["contracts"][0]
    assert row["quote_ok"] is False
    assert row["quote_reason"] == "Open interest 3 is below the 50-contract gate."


def test_sizing_script_tag_appears_exactly_once(app_config):
    html = render(app_config)

    assert html.count('src="/static/option-sizing.js"') == 1
    assert html.count(f'id="{SIZING_PAYLOAD_ID}"') == 1
    assert 'id="option-sizing"' in html
    assert 'data-role="contract"' in html
    assert 'data-role="budget"' in html
    assert 'data-role="price"' in html
    assert 'data-role="result"' in html
    assert 'data-role="ladder"' in html
    assert 'data-role="reset"' in html
    assert 'data-role="live"' in html


def test_legacy_params_preselect_the_contract_and_prefill_the_budget(app_config):
    put = slot(horizon_days=90)
    call = slot(
        option_type="C",
        horizon_days=180,
        bucket="directional",
        contract=candidate(option_type="C", horizon_days=180, bucket="directional"),
    )
    html = render(
        app_config,
        detail=detail(put_slots=(put,), call_slots=(call,)),
        sizing_request=OptionSizingRequest(
            side="call",
            horizon_days=180,
            bucket="directional",
            size_mode="budget",
            budget=2500.0,
        ),
    )

    assert '<option value="call-180-directional" selected>' in html
    assert 'data-role="budget"' in html
    assert 'value="2,500.00"' in html


def test_sizing_tool_degrades_when_no_contract_is_quoted(app_config):
    html = render(app_config, detail=detail(put_slots=(), call_slots=()))

    assert "Position sizing needs at least one quoted contract" in html
    assert 'src="/static/option-sizing.js"' not in html


# ---------------------------------------------------------------------------
# 6. greeks — values, units, model version
# ---------------------------------------------------------------------------


def test_greeks_render_with_their_units_and_model_version(app_config):
    html = render(app_config)

    assert "0.0812" in html
    assert "0.0231" in html
    assert "-0.0044" in html
    assert "per $1 of share price" in html
    assert "per volatility point" in html
    assert "per calendar day" in html
    assert "black_scholes_q0_v1" in html


def test_greeks_do_not_leak_another_tickers_rows(app_config):
    html = render(app_config)

    assert "0.9999" not in html
    assert "0.8888" not in html


def test_greeks_degrade_when_the_columns_are_absent(app_config):
    frame = pd.DataFrame([{"ticker": TICKER, "option_type": "P", "horizon_days": 90}])
    html = render(app_config, candidate_slots_frame=frame)

    assert "No persisted greeks are available" in html


# ---------------------------------------------------------------------------
# 7. what had to be REMOVED
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        "implied stock",
        "Implied Stock",
        "Modeled Stock",
        "Gold Move",
        "Modeled Stock Price",
        "Scenario Table and Sizing Calculator",
        "Net P&L",
        "P&L at Expiry",
    ],
)
def test_gold_scenario_sizing_strings_are_gone_from_the_page(app_config, forbidden):
    html = render(app_config)

    assert forbidden not in html


def test_old_option_panel_functions_no_longer_exist():
    import golden_vector.serve.detail_panels as panels

    for name in (
        "_render_option_trading_panel",
        "_render_option_trading_link_panel",
        "_render_option_sizing_calculator",
        "_render_option_sizing_result",
        "_render_option_candidate_matrix",
        "_render_option_signal_card",
    ):
        assert not hasattr(panels, name), name

    source = Path("golden_vector/serve/detail_panels.py").read_text(encoding="utf-8")
    assert "option" not in source.lower()


# ---------------------------------------------------------------------------
# 8. serve-layer guardrail (clone of the Tool-D / Tool-B scans)
# ---------------------------------------------------------------------------


def test_options_serve_layer_has_no_option_arithmetic():
    """The Options section renders backend-resolved columns only.

    It must never recompute a ratio, a premium, a greek or a P&L — a serve-side
    copy of any of those would let this page disagree with the artifact every
    other surface reads. The gold-scenario sizing device is explicitly banned:
    it derived the share price from a gold beta, which Victor rejected (Q40).
    """

    source = Path("golden_vector/serve/ticker_page/options.py").read_text(encoding="utf-8")

    # It reads the persisted ratio columns by name (display only).
    assert "put_call_oi_ratio_total" in source
    assert "put_call_oi_ratio_otm" in source
    for forbidden in (
        # Ratio recompute.
        "put_oi_total /",
        "/ call_oi_total",
        "put_oi_otm /",
        "/ call_oi_otm",
        "put_volume /",
        "/ total_volume",
        # Premium / position math belongs to option-sizing.js and the backend.
        "* OPTION_CONTRACT_MULTIPLIER",
        "OPTION_CONTRACT_MULTIPLIER *",
        "candidate.ask *",
        "* candidate.ask",
        "candidate.strike -",
        "candidate.strike +",
        "break_even =",
        "intrinsic_at",
        # Greeks are computed during the refresh, never here.
        "black_scholes",
        "_row_greeks",
        # The rejected gold-scenario sizing device.
        "compute_scenario_bundle",
        "scenario_model_note",
        "gold_pct_change",
        "down_beta",
        # Coalesce / fallback resolution belongs upstream.
        ".fillna(",
        ".combine_first(",
        "np.polyfit",
    ):
        assert forbidden not in source, forbidden
