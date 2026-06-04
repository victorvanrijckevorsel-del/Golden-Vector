from __future__ import annotations

from datetime import datetime, timezone

from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_trading import (
    OptionTradingDetailData,
    OptionTradingRow,
    OptionTradingSourceContext,
)
from golden_vector.serve.detail_panels import _render_option_trading_panel


def test_option_trading_detail_renders_watch_candidate_without_half_spread_column():
    watch_candidate = OptionCandidate(
        ticker="AEM",
        horizon_days=60,
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
        horizon_days=60,
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
            context_warnings=(
                "Refresh context is mixed: options snapshot uses options-run; "
                "Tool A uses tool-run; Tool B uses tool-run. Scenario betas and "
                "fundamentals may lag the option chains. Run python main.py "
                "refresh to realign the full model outputs.",
            ),
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
    assert "Refresh context is mixed" in html
    assert "Last" in html
    assert "Mid" in html
    assert "1.88" in html
    assert "8.6% OTM" in html
    assert "Watch" in html
    assert "midpoint may be optimistic" in html
    assert "Put Directional" in html
    assert "button-link" not in html
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
        iv_skew_60d=None,
        iv_rv_ratio_60d=None,
        optionability_tier="directly_hedgeable",
        put_status="watch",
        call_status="none",
        pnl_put_at_minus10_60d=None,
        pnl_call_at_plus10_60d=None,
        notes=(),
        current_stock_price=175.0,
    )
