"""Contract-row rendering on the ticker page's Options section (M3d).

This file used to test ``detail_panels._render_option_trading_panel`` and its
gold-scenario sizing form. Both are deleted: the section moved to
``serve/ticker_page/options.py`` and the sizing form was replaced by the
share-price slider (Q40 — Victor rejected deriving the share price from a gold
beta). What survives is the behaviour that was always about the CONTRACTS: the
watch-tier note, the depth hover, the Yahoo chain link, and the provenance
table. Those assertions are kept, retargeted at the new renderer.
"""

from __future__ import annotations

from datetime import datetime, timezone

from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_trading import (
    OptionTradingDetailData,
    OptionTradingRow,
    OptionTradingSourceContext,
)
from golden_vector.serve.ticker_page import render_options_section
from tests.test_ticker_page_options import app_config  # noqa: F401  (pytest fixture)
from tests.test_ticker_page_options import page_artifacts, slots_frame


def test_watch_candidate_renders_its_note_hover_and_chain_link(app_config):  # noqa: F811
    watch_candidate = OptionCandidate(
        ticker="AEM",
        horizon_days=90,
        expiration="2026-07-17",
        days_to_expiry=46,
        strike=160.0,
        bid=1.70,
        ask=2.05,
        mid=1.88,
        open_interest=40,
        volume=2,
        implied_volatility=0.75,
        delta=-0.18,
        delta_gap=0.07,
        premium_pct_spot=1.88 / 175.0,
        underlying_price=175.0,
        last_price=0.23,
        option_type="P",
        bucket="directional",
        liquidity_tier="watch",
        rel_spread=(2.05 - 1.70) / 1.88,
        half_spread_cost_pct=((2.05 - 1.70) / 1.88) / 2,
        liquidity_score=0.25,
        moneyness_pct=15.0 / 175.0,
        otm_pct=15.0 / 175.0,
        quote_flags=("wide_spread",),
    )
    slot = OptionCandidateSlot(
        ticker="AEM",
        option_type="P",
        horizon_days=90,
        target_delta=-0.25,
        expiration="2026-07-17",
        days_to_expiry=46,
        status="accepted",
        reason=(
            "Directional candidate passed the relaxed liquidity checks with "
            "spread 18.6%. Watch: wide spreads mean the midpoint may be optimistic."
        ),
        candidate=watch_candidate,
        listed_contract_count=43,
        tradable_contract_count=3,
        bucket="directional",
        liquidity_tier="watch",
    )
    detail = OptionTradingDetailData(
        ticker="AEM",
        row=_row(),
        put_candidates=(),
        put_bundles=(),
        put_slots=(slot,),
        source_context=OptionTradingSourceContext(
            as_of_date="2026-06-01",
            refresh_run_id="options-run",
            tool_a_refresh_run_ids=("tool-run",),
            tool_b_refresh_run_ids=("tool-run",),
            context_warnings=(),
            risk_free_rate=0.036,
        ),
    )

    html = render_options_section(
        ticker="AEM",
        detail=detail,
        page_artifacts=page_artifacts(),
        candidate_slots_frame=slots_frame(),
        app_config=app_config,
    )
    expiry_epoch = int(datetime(2026, 7, 17, tzinfo=timezone.utc).timestamp())

    assert "Share price used" in html
    assert "175.00" in html
    assert "Snapshot date" in html
    assert "2026-06-01" in html
    assert "Method" in html
    assert "Mid" in html
    assert "1.88" in html
    # OTM% was dropped in the candidates redesign (redundant next to
    # strike/delta); the watch note lives in the candidate-name hover.
    assert "OTM" not in html
    assert "Watch" in html
    assert "midpoint may be optimistic" in html
    assert "Put Directional" in html
    assert "Half-spread Cost" not in html
    assert f"https://finance.yahoo.com/quote/AEM/options?date={expiry_epoch}" in html


def _row() -> OptionTradingRow:
    return OptionTradingRow(
        ticker="AEM",
        structural_delta_core=1.33,
        down_beta_core=1.33,
        up_beta_core=1.16,
        confidence_label="HIGH",
        confidence_score=0.9,
        iv_percentile_cross_sectional=29.5,
        iv_skew_signal=None,
        iv_rv_ratio_signal=None,
        optionability_tier="directly_hedgeable",
        put_status="watch",
        call_status="none",
        pnl_put_at_context=None,
        pnl_call_at_context=None,
        notes=(),
        current_stock_price=175.0,
    )
