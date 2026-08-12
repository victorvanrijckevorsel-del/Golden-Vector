"""Greeks (plan §6.4 / B9): closed-form values vs hand-computed references."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from golden_vector.features.black_scholes import (
    black_scholes_delta,
    black_scholes_gamma,
    black_scholes_greeks,
    black_scholes_theta,
    black_scholes_vega,
    normal_cdf,
    normal_pdf,
)


def _reference(spot, strike, years, rate, sigma, option_type):
    """Independent textbook Black-Scholes greeks (q = 0)."""

    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma**2) * years) / (
        sigma * math.sqrt(years)
    )
    d2 = d1 - sigma * math.sqrt(years)
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    gamma = pdf / (spot * sigma * math.sqrt(years))
    vega = spot * pdf * math.sqrt(years)
    decay = -(spot * pdf * sigma) / (2 * math.sqrt(years))
    disc = strike * math.exp(-rate * years)
    if option_type == "C":
        theta = decay - rate * disc * normal_cdf(d2)
    else:
        theta = decay + rate * disc * normal_cdf(-d2)
    return gamma, vega, theta / 365.25


CASES = [
    # (spot, strike, years, rate, sigma, option_type) — ATM, deep ITM, deep OTM
    (100.0, 100.0, 0.25, 0.04, 0.35, "P"),
    (100.0, 40.0, 1.0, 0.04, 0.55, "C"),  # deep ITM call / deep OTM put strike
    (20.0, 60.0, 0.5, 0.03, 0.80, "P"),  # deep ITM put
]


@pytest.mark.parametrize("spot,strike,years,rate,sigma,option_type", CASES)
def test_greeks_match_hand_computed_black_scholes(
    spot, strike, years, rate, sigma, option_type
):
    gamma_ref, vega_ref, theta_ref = _reference(spot, strike, years, rate, sigma, option_type)
    shared = dict(
        spot=spot,
        strike=strike,
        time_to_expiry_years=years,
        risk_free_rate=rate,
        implied_volatility=sigma,
    )
    assert black_scholes_gamma(**shared) == pytest.approx(gamma_ref, rel=1e-12)
    assert black_scholes_vega(**shared) == pytest.approx(vega_ref, rel=1e-12)
    assert black_scholes_theta(option_type=option_type, **shared) == pytest.approx(
        theta_ref, rel=1e-12
    )
    bundle = black_scholes_greeks(option_type=option_type, **shared)
    assert bundle == {
        "gamma": pytest.approx(gamma_ref, rel=1e-12),
        "vega": pytest.approx(vega_ref, rel=1e-12),
        "theta": pytest.approx(theta_ref, rel=1e-12),
    }


def test_units_are_the_documented_ones():
    """gamma per $1 underlying, vega per 1.00 vol, theta per CALENDAR day."""

    shared = dict(
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.0,
        implied_volatility=0.20,
    )
    # gamma ~= delta change for a $1 move
    delta_up = black_scholes_delta(option_type="C", **{**shared, "spot": 100.5})
    delta_down = black_scholes_delta(option_type="C", **{**shared, "spot": 99.5})
    assert black_scholes_gamma(**shared) == pytest.approx(delta_up - delta_down, rel=1e-3)
    # vega per 1.00 vol == 100 x the per-vol-point sensitivity
    assert black_scholes_vega(**shared) == pytest.approx(
        100.0 * normal_pdf(0.1) * 1.0, rel=1e-12
    )
    # theta per calendar day == annual/365.25 and negative for long premium
    theta = black_scholes_theta(option_type="C", **shared)
    assert theta is not None and theta < 0


@pytest.mark.parametrize(
    "override",
    [
        {"spot": 0.0},
        {"strike": 0.0},
        {"time_to_expiry_years": 0.0},
        {"time_to_expiry_years": -1.0},
        {"implied_volatility": None},
        {"implied_volatility": 0.0},
        {"implied_volatility": float("nan")},
        {"spot": float("nan")},
        {"spot": pd.NA},
    ],
)
def test_degenerate_and_nan_inputs_return_none(override):
    shared = dict(
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=0.5,
        risk_free_rate=0.03,
        implied_volatility=0.4,
    )
    shared.update(override)
    assert black_scholes_gamma(**shared) is None
    assert black_scholes_vega(**shared) is None
    assert black_scholes_theta(option_type="P", **shared) is None


def test_delta_public_behaviour_unchanged_by_the_d1_refactor():
    """Control: the refactor that extracted _d1_d2 must not move delta."""

    value = black_scholes_delta(
        option_type="P",
        spot=100.0,
        strike=95.0,
        time_to_expiry_years=0.5,
        risk_free_rate=0.03,
        implied_volatility=0.4,
    )
    d1 = (math.log(100.0 / 95.0) + (0.03 + 0.5 * 0.4**2) * 0.5) / (0.4 * math.sqrt(0.5))
    assert value == pytest.approx(normal_cdf(d1) - 1.0, rel=1e-15)
    assert black_scholes_delta(
        option_type="C",
        spot=100.0,
        strike=95.0,
        time_to_expiry_years=0.5,
        risk_free_rate=0.03,
        implied_volatility=None,
    ) is None
    with pytest.raises(ValueError):
        black_scholes_delta(
            option_type="X",  # type: ignore[arg-type]
            spot=1.0,
            strike=1.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.0,
            implied_volatility=0.2,
        )


def test_theta_option_type_is_validated():
    with pytest.raises(ValueError):
        black_scholes_theta(
            option_type="X",  # type: ignore[arg-type]
            spot=1.0,
            strike=1.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.0,
            implied_volatility=0.2,
        )
