import pytest

from golden_vector.model.gold_shock import compute_gold_shock_exposure


def test_gold_shock_floors_negative_beta_and_allows_explicit_zero_when_requested():
    shock = compute_gold_shock_exposure(
        value_usd=10_000,
        beta=-1.5,
        shock_fraction=-0.10,
        min_effective_beta=None,
    )

    assert shock.modelable is True
    assert shock.effective_beta == 0.0
    assert shock.pnl_usd == pytest.approx(0.0)
    assert shock.loss_usd == pytest.approx(0.0)
    assert shock.effective_exposure_usd == pytest.approx(0.0)


def test_gold_shock_gates_low_beta_and_clamps_loss_at_position_value():
    low = compute_gold_shock_exposure(value_usd=10_000, beta=0.05, shock_fraction=-0.10)
    crash = compute_gold_shock_exposure(
        value_usd=10_000,
        beta=15.0,
        shock_fraction=-0.20,
    )

    assert low.modelable is False
    assert low.loss_usd is None
    assert crash.modelable is True
    assert crash.pnl_usd == pytest.approx(-10_000.0)
    assert crash.loss_usd == pytest.approx(10_000.0)
    assert crash.effective_exposure_usd == pytest.approx(150_000.0)
    assert crash.stock_clamped_at_zero is True
