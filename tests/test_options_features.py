import math
from datetime import date

import pandas as pd
import pytest

from golden_vector.features.options import (
    _realized_vol,
    compute_options_features,
    rank_options_iv_cross_section,
)


def test_compute_options_features_uses_fixture_chain():
    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")

    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
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
    assert features["put_oi_total"] == 370
    assert features["call_oi_total"] == 585
    assert features["total_volume"] == 92
    assert features["put_volume"] + features["call_volume"] == 92
    assert features["put_iv_25d_30d"] == pytest.approx(0.42)
    assert features["put_25d_delta_gap_30d"] is not None
    assert features["call_iv_25d_60d"] is not None
    assert features["implied_move_30d"] is None
    assert features["implied_move_30d_gates_ok"] is False
    assert features["realized_vol_30d"] is not None
    assert features["iv_rv_ratio_30d"] is not None
    assert features["put_call_oi_ratio_total"] == pytest.approx(370 / 585)
    assert features["optionability_tier"] == "directly_hedgeable"


def test_compute_options_features_handles_empty_chain():
    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
        chain=pd.DataFrame(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["options_available"] is False
    assert features["n_expirations"] == 0
    assert features["n_contracts"] == 0
    # Unknown, not zero: an empty chain has no observed OI to report.
    assert features["put_oi_total"] is None
    assert features["call_oi_total"] is None
    assert features["put_call_oi_ratio_total"] is None
    assert features["put_call_oi_ratio_otm"] is None
    assert features["put_iv_25d_30d"] is None
    assert features["implied_move_30d_gates_ok"] is False
    assert features["optionability_tier"] == "none"


def test_compute_options_features_handles_invalid_underlying_price():
    chain = pd.DataFrame([_contract("P", 50.0, 1.0, 1.2, 0.40, 20, 5)])

    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
        chain=chain,
        underlying_price=0.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["options_available"] is False
    assert features["n_contracts"] == 0
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
        target_horizons_days=(30, 60, 90),
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


def test_compute_options_features_uses_zero_rate_delta_fallback_without_risk_free_rate():
    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")

    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=None,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["put_iv_25d_30d"] == pytest.approx(0.42)
    assert features["put_25d_delta_gap_30d"] is not None
    assert features["call_iv_25d_30d"] is not None
    assert features["call_25d_delta_gap_30d"] is not None
    assert features["atm_iv_30d"] is not None


def test_compute_options_features_does_not_rank_untradable_candidate_quotes():
    chain = pd.DataFrame(
        [
            _contract("P", 45.0, 1.0, 8.0, 0.40, 100, 10),
            _contract("P", 47.5, 1.2, 9.0, 0.38, 100, 10),
            _contract("C", 55.0, 1.0, 8.0, 0.36, 100, 10),
        ]
    )

    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        optionability_open_interest_threshold=100,
    )

    assert features["atm_iv_30d"] is None
    assert features["put_iv_25d_30d"] is None
    assert features["call_iv_25d_30d"] is None
    assert features["optionability_tier"] == "thin"


def test_rank_options_iv_cross_section_returns_percentiles():
    features = pd.DataFrame(
        {
            "ticker": ["AEM", "NEM", "GFI", "NOIV"],
            "atm_iv_60d": [0.4, 0.2, 0.6, None],
        }
    )

    percentiles = rank_options_iv_cross_section(features, iv_column="atm_iv_60d")

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
    # return_basis_usd is a USD price LEVEL (see normalize/prices_usd.py) —
    # a fixture of raw returns here is how the 100x iv_rv bug slipped through.
    prices = [100.0]
    for step in [0.001, -0.002, 0.003, -0.001] * 30:
        prices.append(prices[-1] * (1 + step))
    return pd.DataFrame({"return_basis_usd": prices})


def test_realized_vol_treats_return_basis_as_price_level():
    """Prices 100 -> 101 -> 104.03 are +1% then +3% returns; realized vol is
    the annualized stdev of THOSE, never the stdev of the dollar levels."""

    features = compute_options_features(
        target_horizons_days=(3,),
        chain=pd.DataFrame(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame({"return_basis_usd": [100.0, 101.0, 104.03]}),
        as_of_date=date(2026, 5, 29),
    )

    expected = math.sqrt(0.0002) * math.sqrt(252)  # std(ddof=1) of [0.01, 0.03]
    assert features["realized_vol_3d"] == pytest.approx(expected, rel=1e-6)


def test_put_call_oi_and_volume_splits():
    chain = pd.DataFrame(
        [
            _contract("P", 50.0, 1.0, 1.2, 0.40, 20, 5),
            _contract("C", 50.0, 1.4, 1.6, 0.38, 22, 6),
            _contract("P", 45.0, 0.45, 0.55, 0.42, 12, 4),
            _contract("C", 55.0, 0.35, 0.45, 0.36, 10, 3),
        ]
    )

    features = compute_options_features(
        target_horizons_days=(30,),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["put_oi_total"] == 32
    assert features["call_oi_total"] == 32
    assert features["put_call_oi_ratio_total"] == pytest.approx(1.0)
    # OTM keeps only P45 (strike < spot) and C55 (strike > spot); the
    # at-the-money 50s belong to neither side.
    assert features["put_oi_otm"] == 12
    assert features["call_oi_otm"] == 10
    assert features["put_call_oi_ratio_otm"] == pytest.approx(12 / 10)
    assert features["put_volume"] == 9
    assert features["call_volume"] == 9


def test_horizon_features_respect_dte_bands():
    """A 550d-labeled feature computed from a 162d expiry (the nearest
    listed) is a mislabeled basis. With bands supplied, horizons whose band
    holds no expiry stay None instead of borrowing a wrong-dated chain."""

    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    # The fixture's expiries sit near 30/60 DTE; ask for 60 and 550 with
    # bands so only 60 has an in-band expiry.
    features = compute_options_features(
        target_horizons_days=(60, 550),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        optionability_open_interest_threshold=100,
        option_dte_bands={60: (45, 75), 550: (450, 650)},
    )
    assert features["call_iv_25d_60d"] is not None  # in-band control row
    assert features["atm_iv_550d"] is None
    assert features["iv_skew_550d"] is None
    assert features["implied_move_550d"] is None

    # Without bands the legacy nearest-expiry behavior is preserved.
    legacy = compute_options_features(
        target_horizons_days=(550,),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        optionability_open_interest_threshold=100,
    )
    assert legacy["atm_iv_550d"] is not None


def _dated_history(dates: list[str], prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, "return_basis_usd": prices})


def test_realized_vol_is_order_independent():
    """Identical data arriving newest-first must give the identical number."""

    dates = ["2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-29"]
    prices = [100.0, 101.0, 100.5, 102.0, 103.0]
    ascending = _realized_vol(_dated_history(dates, prices), window_days=3)
    reversed_frame = _dated_history(dates[::-1], prices[::-1])

    assert ascending is not None
    assert _realized_vol(reversed_frame, window_days=3) == ascending


def test_realized_vol_keeps_last_row_per_duplicate_date():
    """A corrected re-print of the same date wins; keep-first would use the
    stale 150.0 and produce a wildly different vol."""

    dates = ["2026-05-26", "2026-05-27", "2026-05-28", "2026-05-28"]
    duplicated = _realized_vol(
        _dated_history(dates, [100.0, 101.0, 150.0, 102.0]), window_days=3
    )
    deduped = _realized_vol(
        _dated_history(dates[:3], [100.0, 101.0, 102.0]), window_days=3
    )
    keep_first = _realized_vol(
        _dated_history(dates[:3], [100.0, 101.0, 150.0]), window_days=3
    )

    assert duplicated == deduped
    assert duplicated != keep_first


def test_realized_vol_drops_missing_prices_instead_of_forward_filling():
    """pandas' default pct_change pads the gap forward, inventing a 0% day and
    shifting the window. With fill_method=None the gap simply drops out."""

    history = pd.DataFrame(
        {"return_basis_usd": [100.0, 101.0, float("nan"), 103.0, 106.0]}
    )

    returns = [0.01, 106.0 / 103.0 - 1.0]
    mean = sum(returns) / 2
    stdev = math.sqrt(sum((r - mean) ** 2 for r in returns))  # ddof=1, n=2

    assert _realized_vol(history, window_days=3) == pytest.approx(
        stdev * math.sqrt(252)
    )


def test_unknown_open_interest_stays_unknown_while_volume_is_counted():
    """An all-null OI column is not zero activity: the OI splits and both OI
    ratios must be None while the observed volume still reports ints."""

    chain = pd.DataFrame(
        [
            _contract("P", 45.0, 0.45, 0.55, 0.42, None, 4),
            _contract("C", 55.0, 0.35, 0.45, 0.36, None, 3),
        ]
    )

    features = compute_options_features(
        target_horizons_days=(30,),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
    )

    assert features["put_oi_total"] is None
    assert features["call_oi_total"] is None
    assert features["put_oi_otm"] is None
    assert features["call_oi_otm"] is None
    assert features["put_call_oi_ratio_total"] is None
    assert features["put_call_oi_ratio_otm"] is None
    assert features["put_volume"] == 4
    assert features["call_volume"] == 3


def test_per_horizon_source_expiry_and_side_counts_are_emitted():
    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")

    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
        chain=chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        optionability_open_interest_threshold=100,
    )

    normalized_expirations = set(
        pd.to_datetime(chain["expiration"]).dt.strftime("%Y-%m-%d")
    )
    for horizon in (30, 60, 90):
        expiration = features[f"source_expiration_{horizon}d"]
        dte = features[f"source_dte_{horizon}d"]
        assert str(expiration)[:10] in normalized_expirations
        assert isinstance(dte, int) and dte > 0

    # 0 is a genuine count for a side; the chain here has both sides.
    assert features["put_n_contracts"] + features["call_n_contracts"] == 8
    assert features["put_n_contracts"] > 0
    assert features["call_n_contracts"] > 0


def test_one_sided_chain_counts_zero_but_an_empty_chain_is_unknown():
    puts_only = pd.DataFrame(
        [
            _contract("P", 48.0, 1.0, 1.2, 0.40, 20, 5),
            _contract("P", 50.0, 1.5, 1.7, 0.42, 30, 6),
        ]
    )
    features = compute_options_features(
        target_horizons_days=(30,),
        chain=puts_only,
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
    )
    assert features["put_n_contracts"] == 2
    assert features["call_n_contracts"] == 0

    empty = compute_options_features(
        target_horizons_days=(30,),
        chain=pd.DataFrame(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
    )
    assert empty["put_n_contracts"] is None
    assert empty["call_n_contracts"] is None
    # Unresolved horizons still expose the provenance keys as explicit unknowns.
    assert empty["source_expiration_30d"] is None
    assert empty["source_dte_30d"] is None
