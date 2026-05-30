from datetime import date

import pandas as pd
import pytest

from golden_vector.features.options import (
    compute_options_features,
    rank_options_iv_cross_section,
)


def test_compute_options_features_uses_fixture_chain():
    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")

    features = compute_options_features(
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        optionability_open_interest_threshold=100,
    )

    assert features["options_available"] is True
    assert features["n_expirations"] == 2
    assert features["n_contracts"] == 8
    assert features["total_open_interest"] == 955
    assert features["total_volume"] == 92
    assert features["put_iv_25d_30d"] == pytest.approx(0.39)
    assert features["put_25d_delta_gap_30d"] is not None
    assert features["call_iv_25d_60d"] is not None
    assert features["term_slope_30_90"] is not None
    assert features["implied_move_30d"] is None
    assert features["implied_move_30d_gates_ok"] is False
    assert features["realized_vol_30d"] is not None
    assert features["iv_rv_ratio_30d"] is not None
    assert features["put_call_oi_ratio_total"] == pytest.approx(370 / 585)
    assert features["optionability_tier"] == "directly_hedgeable"


def test_compute_options_features_handles_empty_chain():
    features = compute_options_features(
        chain=pd.DataFrame(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["options_available"] is False
    assert features["n_expirations"] == 0
    assert features["n_contracts"] == 0
    assert features["put_iv_25d_30d"] is None
    assert features["implied_move_30d_gates_ok"] is False
    assert features["optionability_tier"] == "none"


def test_compute_options_features_liquidity_gates_implied_move():
    chain = pd.DataFrame(
        [
            _contract("P", 50.0, 1.0, 1.2, 0.40, 20, 5),
            _contract("C", 50.0, 1.4, 1.6, 0.38, 22, 6),
            _contract("P", 45.0, 0.45, 0.55, 0.42, 12, 4),
            _contract("C", 55.0, 0.35, 0.45, 0.36, 10, 3),
        ]
    )

    features = compute_options_features(
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        implied_move_max_spread_pct=0.40,
        implied_move_min_open_interest=10,
        implied_move_min_volume=3,
    )

    assert features["implied_move_30d_gates_ok"] is True
    assert features["implied_move_30d"] == pytest.approx((1.1 + 1.5) / 50.0)


def test_compute_options_features_skips_delta_fields_without_risk_free_rate():
    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")

    features = compute_options_features(
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=None,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["put_iv_25d_30d"] is None
    assert features["call_iv_25d_30d"] is None
    assert features["atm_iv_30d"] is not None


def test_rank_options_iv_cross_section_returns_percentiles():
    features = pd.DataFrame(
        {
            "ticker": ["AEM", "NEM", "GFI", "NOIV"],
            "atm_iv_60d": [0.4, 0.2, 0.6, None],
        }
    )

    percentiles = rank_options_iv_cross_section(features)

    assert percentiles.iloc[0] == pytest.approx(2 / 3 * 100)
    assert percentiles.iloc[1] == pytest.approx(1 / 3 * 100)
    assert percentiles.iloc[2] == pytest.approx(100)
    assert pd.isna(percentiles.iloc[3])


def _contract(
    option_type: str,
    strike: float,
    bid: float,
    ask: float,
    implied_volatility: float,
    open_interest: int,
    volume: int,
) -> dict[str, object]:
    return {
        "expiration": "2026-06-26",
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": (bid + ask) / 2,
        "volume": volume,
        "openInterest": open_interest,
        "impliedVolatility": implied_volatility,
    }


def _price_history() -> pd.DataFrame:
    return pd.DataFrame({"return_basis_usd": [0.001, -0.002, 0.003, -0.001] * 30})
