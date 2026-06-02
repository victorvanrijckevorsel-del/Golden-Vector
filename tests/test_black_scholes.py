import math

import pandas as pd
import pytest

from golden_vector.features.black_scholes import (
    black_scholes_call_price,
    black_scholes_delta,
    black_scholes_put_price,
    normal_cdf,
    strike_for_target_delta,
)


def test_normal_cdf_known_values():
    assert normal_cdf(0.0) == 0.5
    assert normal_cdf(1.96) == pytest.approx(0.975002, abs=1e-6)
    assert normal_cdf(-1.96) == pytest.approx(0.024998, abs=1e-6)


def test_black_scholes_call_delta_matches_reference_value():
    delta = black_scholes_delta(
        option_type="C",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        implied_volatility=0.20,
    )

    assert delta == pytest.approx(0.636831, abs=1e-6)


def test_black_scholes_put_delta_matches_reference_value():
    delta = black_scholes_delta(
        option_type="P",
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        implied_volatility=0.20,
    )

    assert delta == pytest.approx(-0.363169, abs=1e-6)


def test_black_scholes_put_price_matches_reference_value():
    price = black_scholes_put_price(
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        implied_volatility=0.20,
    )

    assert price == pytest.approx(5.573526, abs=1e-6)


def test_black_scholes_call_price_matches_reference_value():
    price = black_scholes_call_price(
        spot=100.0,
        strike=100.0,
        time_to_expiry_years=1.0,
        risk_free_rate=0.05,
        implied_volatility=0.20,
    )

    assert price == pytest.approx(10.450584, abs=1e-6)


@pytest.mark.parametrize(
    "spot,strike,time_to_expiry_years,risk_free_rate,implied_volatility",
    [
        (100.0, 100.0, 1.0, 0.05, 0.20),
        (75.0, 80.0, 0.5, 0.03, 0.35),
        (120.0, 100.0, 0.25, 0.01, 0.10),
        (50.0, 75.0, 2.0, 0.04, 0.60),
        (0.0, 40.0, 0.5, 0.04, None),
    ],
)
def test_black_scholes_prices_satisfy_put_call_parity(
    spot,
    strike,
    time_to_expiry_years,
    risk_free_rate,
    implied_volatility,
):
    put_price = black_scholes_put_price(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        implied_volatility=implied_volatility,
    )
    call_price = black_scholes_call_price(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        implied_volatility=implied_volatility,
    )

    assert put_price is not None
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    assert call_price + discounted_strike == pytest.approx(put_price + spot, abs=1e-6)


def test_black_scholes_put_price_uses_spot_zero_limit_value():
    price = black_scholes_put_price(
        spot=0.0,
        strike=40.0,
        time_to_expiry_years=0.5,
        risk_free_rate=0.04,
        implied_volatility=None,
    )

    assert price == pytest.approx(40.0 * math.exp(-0.04 * 0.5))


def test_black_scholes_call_price_uses_spot_zero_limit_value():
    price = black_scholes_call_price(
        spot=0.0,
        strike=40.0,
        time_to_expiry_years=0.5,
        risk_free_rate=0.04,
        implied_volatility=None,
    )

    assert price == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spot": -1.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 0.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 0.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.0},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": None},
    ],
)
def test_black_scholes_put_price_returns_none_for_degenerate_inputs(kwargs):
    price = black_scholes_put_price(
        risk_free_rate=0.04,
        **kwargs,
    )

    assert price is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spot": -1.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 0.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 0.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.0},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": None},
    ],
)
def test_black_scholes_call_price_returns_none_for_degenerate_inputs(kwargs):
    price = black_scholes_call_price(
        risk_free_rate=0.04,
        **kwargs,
    )

    assert price is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spot": 0.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 0.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 0.0, "implied_volatility": 0.2},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": 0.0},
        {"spot": 100.0, "strike": 100.0, "time_to_expiry_years": 1.0, "implied_volatility": None},
    ],
)
def test_black_scholes_delta_returns_none_for_degenerate_inputs(kwargs):
    delta = black_scholes_delta(
        option_type="P",
        risk_free_rate=0.04,
        **kwargs,
    )

    assert delta is None


def test_black_scholes_delta_rejects_unknown_option_type():
    with pytest.raises(ValueError, match="option_type"):
        black_scholes_delta(
            option_type="X",
            spot=100.0,
            strike=100.0,
            time_to_expiry_years=1.0,
            risk_free_rate=0.04,
            implied_volatility=0.2,
        )


def test_strike_for_target_delta_returns_listed_strike_with_delta_gap():
    chain = pd.DataFrame(
        [
            {"option_type": "P", "expiration": "2026-06-19", "strike": 45.0, "delta": -0.18, "bid": 1.0},
            {"option_type": "P", "expiration": "2026-06-19", "strike": 47.5, "delta": -0.27, "bid": 1.4},
            {"option_type": "P", "expiration": "2026-06-19", "strike": 50.0, "delta": -0.39, "bid": 2.2},
        ]
    )

    selected = strike_for_target_delta(
        option_type="P",
        target_delta=-0.25,
        chain_slice=chain,
    )

    assert selected is not None
    assert selected["strike"] == 47.5
    assert selected["bid"] == 1.4
    assert selected["delta"] == -0.27
    assert selected["delta_gap"] == pytest.approx(0.02)


def test_strike_for_target_delta_filters_option_type():
    chain = pd.DataFrame(
        [
            {"option_type": "C", "strike": 45.0, "delta": 0.25},
            {"option_type": "P", "strike": 47.5, "delta": -0.26},
        ]
    )

    selected = strike_for_target_delta(
        option_type="P",
        target_delta=-0.25,
        chain_slice=chain,
    )

    assert selected is not None
    assert selected["strike"] == 47.5


def test_strike_for_target_delta_returns_none_without_computable_delta():
    chain = pd.DataFrame(
        [
            {"option_type": "P", "strike": 45.0, "delta": math.nan},
            {"option_type": "P", "strike": 47.5, "delta": None},
        ]
    )

    selected = strike_for_target_delta(
        option_type="P",
        target_delta=-0.25,
        chain_slice=chain,
    )

    assert selected is None


def test_strike_for_target_delta_returns_none_for_missing_delta_column():
    selected = strike_for_target_delta(
        option_type="P",
        target_delta=-0.25,
        chain_slice=pd.DataFrame([{"strike": 45.0}]),
    )

    assert selected is None


def test_strike_for_target_delta_rejects_unknown_option_type():
    with pytest.raises(ValueError, match="option_type"):
        strike_for_target_delta(
            option_type="X",
            target_delta=-0.25,
            chain_slice=pd.DataFrame([{"delta": -0.25}]),
        )
