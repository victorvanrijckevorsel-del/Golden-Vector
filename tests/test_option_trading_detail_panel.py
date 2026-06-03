from __future__ import annotations

from datetime import datetime, timezone

from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_trading import (
    OptionTradingDetailData,
    OptionTradingRow,
    OptionTradingSourceContext,
)
from golden_vector.serve.detail_panels import _render_option_trading_panel


def test_option_trading_detail_renders_rejected_candidate_with_quote_context():
    rejected = OptionCandidate(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-17",
        days_to_expiry=46,
        strike=50.0,
        bid=1.70,
        ask=2.05,
        mid=1.88,
        open_interest=7,
        volume=2,
        implied_volatility=2.256,
        delta=-0.02,
        delta_gap=0.23,
        premium_pct_spot=1.88 / 175.0,
        underlying_price=175.0,
        last_price=0.23,
        option_type="P",
        bucket="directional",
        liquidity_tier="watch",
        rel_spread=(2.05 - 1.70) / 1.88,
        half_spread_cost_pct=((2.05 - 1.70) / 1.88) / 2,
        liquidity_score=0.25,
        moneyness_pct=125.0 / 175.0,
        quote_flags=("wide_spread",),
    )
    slot = OptionCandidateSlot(
        ticker="AEM",
        option_type="P",
        horizon_days=60,
        target_delta=-0.25,
        expiration="2026-07-17",
        days_to_expiry=46,
        status="rejected",
        reason=(
            "No acceptable 60d put candidate. The closest tradable contract "
            "was strike 50.00, but it is 71.4% below the cached stock price "
            "and delta -0.02 is too far from target -0.25."
        ),
        rejected_candidate=rejected,
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
            risk_free_rate=0.036,
        ),
    )

    html = _render_option_trading_panel(detail)
    expiry_epoch = int(datetime(2026, 7, 17, tzinfo=timezone.utc).timestamp())

    assert "Stock Price" in html
    assert "175.00" in html
    assert "Snapshot Date" in html
    assert "2026-06-01" in html
    assert "Cached Yahoo Finance data via yfinance" in html
    assert "Method" in html
    assert "Last" in html
    assert "0.23" in html
    assert "Mid" in html
    assert "1.88" in html
    assert "71.4% OTM" in html
    assert "Watch" in html
    assert "No acceptable 60d put candidate" in html
    assert "Directional" in html
    assert "Select" in html
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
        iv_skew_60d=None,
        iv_rv_ratio_60d=None,
        optionability_tier="directly_hedgeable",
        put_status="thin",
        call_status="thin",
        pnl_put_at_minus10_60d=None,
        pnl_call_at_plus10_60d=None,
        notes=(),
        current_stock_price=175.0,
    )
