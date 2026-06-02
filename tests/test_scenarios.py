import math

import pytest

from golden_vector.features.options_chain import CALENDAR_DAYS_PER_YEAR
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.scenarios import (
    DOWN_BETA_MIN_FOR_SCENARIO,
    compute_scenario_bundle,
)


def test_compute_scenario_bundle_calculates_put_pnl_rows_and_breakeven():
    bundle = compute_scenario_bundle(
        candidate=_candidate(strike=45.0, mid=1.20, implied_volatility=0.40),
        current_stock_price=50.0,
        down_beta_core=1.40,
        confidence_label="high",
        risk_free_rate=0.04,
        gold_scenarios=(0.0, -0.10),
        quantity=5,
    )

    assert bundle.skipped_reason is None
    assert bundle.horizon == "60d"
    assert bundle.breakeven_gold_pct == pytest.approx(-0.0885714286)
    downside = bundle.rows[1]
    assert downside.gold_pct_change == -0.10
    assert downside.implied_stock_price == pytest.approx(43.0)
    assert downside.expiry_value_per_contract == pytest.approx(2.0)
    assert downside.pnl_per_contract_at_expiry == pytest.approx(0.80)
    assert downside.net_pnl_at_expiry == pytest.approx(400.0)
    assert downside.current_value_per_contract > 0
    assert downside.net_pnl_if_closed_today is not None


def test_compute_scenario_bundle_skips_low_down_beta_without_fake_breakeven():
    bundle = compute_scenario_bundle(
        candidate=_candidate(),
        current_stock_price=50.0,
        down_beta_core=DOWN_BETA_MIN_FOR_SCENARIO,
        confidence_label="low",
        risk_free_rate=0.04,
    )

    assert bundle.rows == []
    assert bundle.breakeven_gold_pct is None
    assert bundle.skipped_reason is not None
    assert "Down-beta is too small" in bundle.skipped_reason


def test_compute_scenario_bundle_populates_spot_zero_limit_when_stock_clamps():
    bundle = compute_scenario_bundle(
        candidate=_candidate(strike=5.0, mid=0.50, implied_volatility=None),
        current_stock_price=10.0,
        down_beta_core=8.0,
        confidence_label="medium",
        risk_free_rate=0.04,
        gold_scenarios=(-0.20,),
        quantity=2,
    )

    row = bundle.rows[0]
    assert row.stock_clamped_at_zero is True
    assert row.implied_stock_price == 0.0
    assert row.current_value_per_contract == pytest.approx(
        5.0 * math.exp(-0.04 * (60 / CALENDAR_DAYS_PER_YEAR))
    )
    assert row.net_pnl_at_expiry == pytest.approx((5.0 - 0.50) * 2 * 100)


def test_compute_scenario_bundle_marks_positive_breakeven_as_invalid():
    bundle = compute_scenario_bundle(
        candidate=_candidate(strike=60.0, mid=1.00, implied_volatility=0.40),
        current_stock_price=50.0,
        down_beta_core=1.40,
        confidence_label="high",
        risk_free_rate=0.04,
    )

    assert bundle.breakeven_gold_pct is None
    assert bundle.breakeven_annotation is not None
    assert "breakeven requires gold to rise" in bundle.breakeven_annotation


@pytest.mark.parametrize(
    "price,down_beta,mid,quantity,expected",
    [
        (0.0, 1.0, 1.0, 1, "Current stock price"),
        (50.0, None, 1.0, 1, "Down-beta"),
        (50.0, 1.0, None, 1, "mid premium"),
        (50.0, 1.0, 1.0, 0, "quantity"),
    ],
)
def test_compute_scenario_bundle_skips_unusable_inputs(
    price,
    down_beta,
    mid,
    quantity,
    expected,
):
    bundle = compute_scenario_bundle(
        candidate=_candidate(mid=mid),
        current_stock_price=price,
        down_beta_core=down_beta,
        confidence_label="n/a",
        risk_free_rate=0.04,
        quantity=quantity,
    )

    assert bundle.rows == []
    assert bundle.skipped_reason is not None
    assert expected in bundle.skipped_reason


def _candidate(
    *,
    strike: float = 45.0,
    mid: float | None = 1.20,
    implied_volatility: float | None = 0.40,
) -> CandidatePut:
    return CandidatePut(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-31",
        days_to_expiry=60,
        strike=strike,
        bid=None if mid is None else mid - 0.05,
        ask=None if mid is None else mid + 0.05,
        mid=mid,
        open_interest=500,
        volume=50,
        implied_volatility=implied_volatility,
        delta=-0.25,
        delta_gap=0.01,
        premium_pct_spot=None,
        underlying_price=50.0,
    )
