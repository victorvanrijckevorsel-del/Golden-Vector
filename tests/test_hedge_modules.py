from datetime import date

import pandas as pd
import pytest

from golden_vector.hedge.candidate_puts import CandidatePut, build_candidate_put_grid
from golden_vector.hedge.expected_downside import compute_premium_vs_downside
from golden_vector.hedge.holdings import Holding
from golden_vector.hedge.implied_move import compute_implied_move_from_straddle


def test_build_candidate_put_grid_returns_listed_puts_by_horizon():
    candidates = build_candidate_put_grid(
        ticker="AEM",
        chain=_candidate_chain(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        target_horizons_days=(30, 60, 90),
        as_of_date=date(2026, 5, 29),
    )

    assert [candidate.horizon_days for candidate in candidates] == [30, 60, 90]
    assert all(candidate.ticker == "AEM" for candidate in candidates)
    assert all(candidate.delta is not None for candidate in candidates)
    assert all(candidate.delta_gap is not None for candidate in candidates)
    assert candidates[0].expiration == "2026-06-27"
    assert candidates[0].premium_pct_spot == pytest.approx(candidates[0].mid / 50.0)


def test_build_candidate_put_grid_returns_empty_without_delta_inputs():
    candidates = build_candidate_put_grid(
        ticker="AEM",
        chain=_candidate_chain(),
        underlying_price=50.0,
        risk_free_rate=None,
        target_horizons_days=(30,),
        as_of_date=date(2026, 5, 29),
    )

    assert candidates == []


def test_build_candidate_put_grid_filters_untradable_quotes():
    bad_chain = _candidate_chain().copy()
    bad_chain.loc[bad_chain["option_type"] == "P", "ask"] = (
        bad_chain.loc[bad_chain["option_type"] == "P", "bid"] + 10.0
    )

    candidates = build_candidate_put_grid(
        ticker="AEM",
        chain=bad_chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        target_horizons_days=(30, 60, 90),
        as_of_date=date(2026, 5, 29),
    )

    assert candidates == []


def test_build_candidate_put_grid_filters_placeholder_iv():
    bad_chain = _candidate_chain().copy()
    bad_chain.loc[bad_chain["option_type"] == "P", "impliedVolatility"] = 0.00001

    candidates = build_candidate_put_grid(
        ticker="AEM",
        chain=bad_chain,
        underlying_price=50.0,
        risk_free_rate=0.04,
        target_horizons_days=(30, 60, 90),
        as_of_date=date(2026, 5, 29),
    )

    assert candidates == []


def test_compute_implied_move_from_straddle_requires_liquid_quotes():
    chain = pd.DataFrame(
        [
            _option("2026-06-27", "P", 50.0, 1.0, 1.2, 20, 5),
            _option("2026-06-27", "C", 50.0, 1.4, 1.6, 24, 7),
        ]
    )

    implied_move = compute_implied_move_from_straddle(
        chain=chain,
        underlying_price=50.0,
        expiration="2026-06-27",
        max_spread_pct=0.40,
        min_open_interest=10,
        min_volume=5,
    )

    assert implied_move == pytest.approx((1.1 + 1.5) / 50.0)
    assert (
        compute_implied_move_from_straddle(
            chain=chain.assign(ask=[5.0, 1.6]),
            underlying_price=50.0,
            expiration="2026-06-27",
            max_spread_pct=0.40,
        )
        is None
    )


def test_compute_premium_vs_downside_tags_scenarios():
    candidate = CandidatePut(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-31",
        days_to_expiry=63,
        strike=45.0,
        bid=1.9,
        ask=2.1,
        mid=2.0,
        open_interest=100,
        volume=12,
        implied_volatility=0.4,
        delta=-0.26,
        delta_gap=0.01,
        premium_pct_spot=0.04,
        underlying_price=50.0,
    )

    card = compute_premium_vs_downside(
        ticker="AEM",
        down_beta=1.5,
        confidence_score=0.8,
        holding=Holding(ticker="AEM", dollar_exposure=10000.0),
        candidate_put=candidate,
        gold_scenarios=(0.10, 0.20),
    )

    assert card.full_hedge_premium_usd == pytest.approx(400.0)
    assert card.scenarios[0].modeled_downside_usd == pytest.approx(1500.0)
    assert card.scenarios[0].hedge_ratio == pytest.approx(400 / 1500)
    assert card.scenarios[0].tag == "protection_cheap"
    assert card.scenarios[1].tag == "protection_cheap"


def test_compute_premium_vs_downside_does_not_abs_negative_down_beta():
    candidate = CandidatePut(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-31",
        days_to_expiry=63,
        strike=45.0,
        bid=1.9,
        ask=2.1,
        mid=2.0,
        open_interest=100,
        volume=12,
        implied_volatility=0.4,
        delta=-0.26,
        delta_gap=0.01,
        premium_pct_spot=0.04,
        underlying_price=50.0,
    )

    card = compute_premium_vs_downside(
        ticker="AEM",
        down_beta=-1.5,
        confidence_score=0.8,
        holding=Holding(ticker="AEM", dollar_exposure=10000.0),
        candidate_put=candidate,
        gold_scenarios=(0.10,),
    )

    assert card.scenarios[0].modeled_stock_down_pct == 0.0
    assert card.scenarios[0].modeled_downside_usd == 0.0
    assert card.scenarios[0].hedge_ratio is None
    assert card.scenarios[0].tag == "premium_unavailable"


def _candidate_chain() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for expiration, put_prices in (
        ("2026-06-27", [(45.0, 0.9, 1.1, 0.40), (47.5, 1.3, 1.5, 0.38)]),
        ("2026-07-31", [(45.0, 1.8, 2.0, 0.42), (47.5, 2.5, 2.7, 0.41)]),
        ("2026-08-28", [(45.0, 2.8, 3.0, 0.44), (47.5, 3.5, 3.8, 0.43)]),
    ):
        for strike, bid, ask, iv in put_prices:
            rows.append(_option(expiration, "P", strike, bid, ask, 100, 20, iv))
        rows.append(_option(expiration, "C", 55.0, 0.8, 1.0, 100, 20, 0.36))
    return pd.DataFrame(rows)


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
