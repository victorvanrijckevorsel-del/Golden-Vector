from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from golden_vector.hedge.options_liquidity import (
    OptionLiquiditySettings,
    build_bucket_slots,
    build_bucket_slots_from_scan,
    is_usable_candidate,
    scan_option_chain,
    slot_tier_counts,
)


def test_scan_option_chain_classifies_quote_quality_and_scores_spread_first():
    scan = scan_option_chain(
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-17", "P", 95.0, 4.00, 4.40, 100, 20),
                _option("2026-07-17", "P", 90.0, 1.00, 3.00, 5000, 5000),
                _option("2026-07-17", "P", 100.0, 0.00, 1.00, 100, 20),
                _option("2026-07-17", "P", 99.0, 0.05, 0.07, 100, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        as_of_date=date(2026, 5, 29),
    )

    by_strike = {metric.strike: metric for metric in scan.metrics}

    assert by_strike[95.0].liquidity_tier == "tradable"
    assert by_strike[95.0].rel_spread == pytest.approx(0.40 / 4.20)
    assert by_strike[95.0].half_spread_cost_pct == pytest.approx(0.40 / 4.20 / 2)
    assert by_strike[90.0].liquidity_tier == "no_trade"
    assert "too_wide_to_watch" in by_strike[90.0].quote_flags
    assert by_strike[100.0].liquidity_tier == "no_trade"
    assert "invalid_quote" in by_strike[100.0].quote_flags
    assert by_strike[99.0].liquidity_tier == "watch"
    assert "sub_min_premium" in by_strike[99.0].quote_flags
    assert by_strike[90.0].liquidity_score < by_strike[95.0].liquidity_score


def test_is_usable_candidate_requires_tradable_tier_and_bucket_fit():
    scan = scan_option_chain(
        ticker="NEM",
        chain=pd.DataFrame([_option("2026-07-17", "P", 95.0, 4.00, 4.40, 100, 20)]),
        underlying_price=100.0,
        risk_free_rate=0.04,
        as_of_date=date(2026, 5, 29),
    )
    metric = scan.metrics[0]

    assert is_usable_candidate(metric, bucket_fit=True)
    assert not is_usable_candidate(metric, bucket_fit=False)


def test_scan_option_chain_counts_near_spot_depth_once_per_expiry_side():
    scan = scan_option_chain(
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-17", "P", 95.0, 4.00, 4.40, 100, 20),
                _option("2026-07-17", "P", 105.0, 5.00, 5.40, 100, 20),
                _option("2026-07-17", "P", 80.0, 1.00, 1.20, 100, 20),
                _option("2026-07-17", "P", 100.0, 0.00, 1.00, 100, 20),
                _option("2026-07-17", "C", 105.0, 4.00, 4.40, 100, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        as_of_date=date(2026, 5, 29),
    )

    puts_by_strike = {
        metric.strike: metric
        for metric in scan.metrics
        if metric.option_type == "P"
    }
    calls_by_strike = {
        metric.strike: metric
        for metric in scan.metrics
        if metric.option_type == "C"
    }

    assert puts_by_strike[95.0].near_spot_depth_count == 2
    assert puts_by_strike[105.0].near_spot_depth_count == 2
    assert calls_by_strike[105.0].near_spot_depth_count == 1


def test_build_bucket_slots_never_accepts_absurdly_far_otm_contract():
    slots = build_bucket_slots(
        option_type="P",
        ticker="AEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-17", "P", 50.0, 1.70, 2.05, 500, 20),
            ]
        ),
        underlying_price=175.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(
            dte_bands={60: (45, 75)},
            sensible_moneyness_max_pct=0.35,
        ),
        as_of_date=date(2026, 5, 29),
    )

    assert slots
    assert all(slot.candidate is None for slot in slots)
    assert all(slot.rejected_candidate is None for slot in slots)
    assert {slot.expiration for slot in slots} == {"2026-07-17"}
    assert {slot.days_to_expiry for slot in slots} == {49}
    assert "No liquid candidate" in " ".join(slot.reason for slot in slots)
    assert slot_tier_counts(slots) == {"tradable": 0, "watch": 0, "no_trade": len(slots)}


def test_build_bucket_slots_prefers_expiry_closest_to_named_horizon_when_quotes_tie():
    slots = build_bucket_slots(
        option_type="P",
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-14", "P", 95.0, 4.00, 4.40, 100, 20),
                _option("2026-07-23", "P", 95.0, 4.00, 4.40, 100, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(dte_bands={60: (46, 75)}),
        as_of_date=date(2026, 5, 29),
    )

    near_atm = next(slot for slot in slots if slot.bucket == "near_atm")

    assert near_atm.candidate is not None
    assert near_atm.candidate.days_to_expiry == 55
    assert near_atm.candidate.expiration == "2026-07-23"


def test_build_bucket_slots_from_scan_matches_chain_wrapper():
    chain = pd.DataFrame(
        [
            _option("2026-07-23", "P", 96.0, 4.00, 4.40, 500, 20),
            _option("2026-07-23", "P", 82.0, 2.00, 2.20, 500, 20),
            _option("2026-07-23", "C", 104.0, 4.00, 4.40, 500, 20),
        ]
    )
    settings = OptionLiquiditySettings(dte_bands={60: (46, 75)})
    scan = scan_option_chain(
        ticker="NEM",
        chain=chain,
        underlying_price=100.0,
        risk_free_rate=0.04,
        settings=settings,
        as_of_date=date(2026, 5, 29),
    )

    assert build_bucket_slots_from_scan(
        option_type="P",
        scan=scan,
        target_horizons_days=(60,),
        settings=settings,
    ) == build_bucket_slots(
        option_type="P",
        ticker="NEM",
        chain=chain,
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=settings,
        as_of_date=date(2026, 5, 29),
    )


def test_build_bucket_slots_requires_side_aware_otm_contracts():
    put_slots = build_bucket_slots(
        option_type="P",
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-23", "P", 102.0, 4.00, 4.40, 500, 20),
                _option("2026-07-23", "P", 96.0, 4.00, 4.40, 500, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(dte_bands={60: (46, 75)}),
        as_of_date=date(2026, 5, 29),
    )
    call_slots = build_bucket_slots(
        option_type="C",
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-23", "C", 98.0, 4.00, 4.40, 500, 20),
                _option("2026-07-23", "C", 104.0, 4.00, 4.40, 500, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(dte_bands={60: (46, 75)}),
        as_of_date=date(2026, 5, 29),
    )

    put_near = next(slot for slot in put_slots if slot.bucket == "near_atm")
    call_near = next(slot for slot in call_slots if slot.bucket == "near_atm")

    assert put_near.candidate is not None
    assert put_near.candidate.strike == 96.0
    assert put_near.candidate.otm_pct == pytest.approx(0.04)
    assert call_near.candidate is not None
    assert call_near.candidate.strike == 104.0
    assert call_near.candidate.otm_pct == pytest.approx(0.04)


def test_directional_bucket_prefers_15_to_20_percent_otm_when_liquidity_is_similar():
    slots = build_bucket_slots(
        option_type="P",
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-23", "P", 87.0, 3.00, 3.20, 500, 20),
                _option("2026-07-23", "P", 83.0, 3.00, 3.20, 500, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(dte_bands={60: (46, 75)}),
        as_of_date=date(2026, 5, 29),
    )

    directional = next(slot for slot in slots if slot.bucket == "directional")

    assert directional.candidate is not None
    assert directional.candidate.strike == 83.0
    assert directional.candidate.otm_pct == pytest.approx(0.17)
    assert directional.candidate.liquidity_tier == "tradable"


def test_directional_bucket_allows_12_to_22_percent_otm_when_liquid():
    slots = build_bucket_slots(
        option_type="C",
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-23", "C", 113.0, 3.00, 3.20, 500, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(dte_bands={60: (46, 75)}),
        as_of_date=date(2026, 5, 29),
    )

    directional = next(slot for slot in slots if slot.bucket == "directional")

    assert directional.candidate is not None
    assert directional.candidate.strike == 113.0
    assert directional.candidate.otm_pct == pytest.approx(0.13)
    assert directional.candidate.liquidity_tier == "tradable"


def test_build_bucket_slots_accepts_single_relaxed_watch_candidate():
    slots = build_bucket_slots(
        option_type="P",
        ticker="NEM",
        chain=pd.DataFrame(
            [
                _option("2026-07-23", "P", 96.0, 3.00, 4.00, 60, 20),
            ]
        ),
        underlying_price=100.0,
        risk_free_rate=0.04,
        target_horizons_days=(60,),
        settings=OptionLiquiditySettings(dte_bands={60: (46, 75)}),
        as_of_date=date(2026, 5, 29),
    )

    near_atm = next(slot for slot in slots if slot.bucket == "near_atm")

    assert near_atm.candidate is not None
    assert near_atm.candidate.liquidity_tier == "watch"
    assert "Watch" in near_atm.reason
    assert slot_tier_counts(slots)["watch"] == 1


def _option(
    expiration: str,
    option_type: str,
    strike: float,
    bid: float,
    ask: float,
    open_interest: int,
    volume: int,
    implied_volatility: float = 0.40,
) -> dict[str, object]:
    return {
        "expiration": expiration,
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": (bid + ask) / 2,
        "volume": volume,
        "openInterest": open_interest,
        "impliedVolatility": implied_volatility,
    }
