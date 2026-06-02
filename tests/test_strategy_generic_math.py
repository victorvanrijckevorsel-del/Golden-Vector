import pytest

from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.scenarios import (
    OptionStrategy,
    compute_scenario_bundle,
    compute_strategy_pnl,
)


@pytest.mark.parametrize(
    "strategy,underlying,strike,premium,expected",
    [
        (OptionStrategy.LONG_PUT, 40.0, 50.0, 2.0, 8.0),
        (OptionStrategy.SHORT_PUT, 40.0, 50.0, 2.0, -8.0),
        (OptionStrategy.LONG_CALL, 60.0, 50.0, 3.0, 7.0),
        (OptionStrategy.SHORT_CALL, 60.0, 50.0, 3.0, -7.0),
        (OptionStrategy.LONG_CALL, 40.0, 50.0, 3.0, -3.0),
        (OptionStrategy.SHORT_PUT, 60.0, 50.0, 2.0, 2.0),
    ],
)
def test_compute_strategy_pnl_handles_all_single_leg_sign_rules(
    strategy,
    underlying,
    strike,
    premium,
    expected,
):
    assert compute_strategy_pnl(
        strategy=strategy,
        underlying=underlying,
        strike=strike,
        premium=premium,
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    "strategy,expected_pnl",
    [
        (OptionStrategy.LONG_PUT, 0.80),
        (OptionStrategy.SHORT_PUT, -0.80),
        (OptionStrategy.LONG_CALL, -1.20),
        (OptionStrategy.SHORT_CALL, 1.20),
    ],
)
def test_compute_scenario_bundle_applies_strategy_pnl_signs(
    strategy,
    expected_pnl,
):
    bundle = compute_scenario_bundle(
        candidate=_candidate(strike=45.0, mid=1.20),
        current_stock_price=50.0,
        gold_beta=1.40,
        confidence_label="high",
        risk_free_rate=0.04,
        strategy=strategy,
        gold_scenarios=(-0.10,),
        quantity=2,
    )

    assert bundle.skipped_reason is None
    row = bundle.rows[0]
    assert row.implied_stock_price == pytest.approx(43.0)
    assert row.pnl_per_contract_at_expiry == pytest.approx(expected_pnl)
    assert row.net_pnl_at_expiry == pytest.approx(expected_pnl * 2 * 100)
    if strategy == OptionStrategy.LONG_PUT:
        assert bundle.breakeven_gold_pct is not None
    else:
        assert bundle.breakeven_gold_pct is None


def test_compute_scenario_bundle_uses_configured_down_beta_threshold():
    skipped = compute_scenario_bundle(
        candidate=_candidate(),
        current_stock_price=50.0,
        gold_beta=0.20,
        confidence_label="low",
        risk_free_rate=0.04,
        gold_beta_min_for_scenario=0.30,
    )
    included = compute_scenario_bundle(
        candidate=_candidate(),
        current_stock_price=50.0,
        gold_beta=0.20,
        confidence_label="low",
        risk_free_rate=0.04,
        gold_beta_min_for_scenario=0.10,
    )

    assert skipped.rows == []
    assert skipped.skipped_reason is not None
    assert "Down-beta is too small" in skipped.skipped_reason
    assert included.rows
    assert included.skipped_reason is None


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
