"""Milestone C3: most-liquid expiry selector contract.

Pins the plan-v3 selector rules: configured windows only, tradable-only
robust medians (never raw sums), side-aware defaults, deterministic
tie-breaks, and benchmark ETFs excluded from the group vote.
"""

from __future__ import annotations

from typing import Literal, cast

from golden_vector.hedge.option_horizon_selection import (
    select_group_default_window,
    select_most_liquid_expiry,
    select_ticker_default_window,
)
from golden_vector.hedge.options_liquidity import OptionContractMetrics

BANDS = {90: (75, 104), 230: (210, 320)}


def _metric(
    *,
    ticker: str = "NEM",
    side: str = "P",
    expiration: str = "2026-09-18",
    days_to_expiry: int = 90,
    tier: str = "tradable",
    rel_spread: float = 0.10,
    open_interest: int = 100,
    volume: int = 10,
    near_spot_depth_count: int = 8,
    is_standard_monthly: bool = True,
) -> OptionContractMetrics:
    return OptionContractMetrics(
        ticker=ticker,
        option_type=cast(Literal["P", "C"], side),
        expiration=expiration,
        days_to_expiry=days_to_expiry,
        strike=95.0,
        underlying_price=100.0,
        bid=1.9,
        ask=2.1,
        mid=2.0,
        last_price=2.0,
        open_interest=open_interest,
        volume=volume,
        implied_volatility=0.35,
        delta=-0.25 if side == "P" else 0.25,
        rel_spread=rel_spread,
        half_spread_cost_pct=0.05,
        moneyness_pct=0.05,
        otm_pct=0.05,
        premium_pct_spot=0.02,
        near_spot_depth_count=near_spot_depth_count,
        liquidity_score=0.8,
        liquidity_tier=cast(Literal["tradable", "watch", "no_trade"], tier),
        quote_flags=(),
        is_standard_monthly=is_standard_monthly,
    )


def test_selects_most_liquid_expiry_within_the_window_only():
    metrics = [
        # Inside the 90d window: a thin expiry and a liquid one.
        _metric(expiration="2026-09-04", days_to_expiry=84, rel_spread=0.30, open_interest=10),
        _metric(expiration="2026-09-18", days_to_expiry=98, rel_spread=0.08, open_interest=400),
        _metric(expiration="2026-09-18", days_to_expiry=98, rel_spread=0.12, open_interest=300),
        # Outside every window: must be invisible to selection.
        _metric(expiration="2027-06-18", days_to_expiry=370, rel_spread=0.01, open_interest=9999),
    ]

    selection = select_most_liquid_expiry(
        metrics=metrics, ticker="NEM", side="P", horizon_days=90, band=BANDS[90]
    )

    assert selection is not None
    assert selection.expiration == "2026-09-18"
    assert selection.tradable_count == 2
    assert selection.median_open_interest == 350.0


def test_watch_and_no_trade_contracts_never_drive_selection():
    metrics = [
        _metric(expiration="2026-09-04", days_to_expiry=84, rel_spread=0.10, open_interest=50),
        # Huge but untradable interest at another expiry must not win.
        _metric(expiration="2026-09-18", days_to_expiry=98, tier="watch", open_interest=100000),
        _metric(expiration="2026-09-18", days_to_expiry=98, tier="no_trade", open_interest=100000),
    ]

    selection = select_most_liquid_expiry(
        metrics=metrics, ticker="NEM", side="P", horizon_days=90, band=BANDS[90]
    )

    assert selection is not None
    assert selection.expiration == "2026-09-04"


def test_many_thin_contracts_do_not_beat_fewer_tight_ones_on_medians():
    metrics = [
        # Expiry A: three tradable contracts, wide spreads (median 0.30).
        *[
            _metric(expiration="2026-09-04", days_to_expiry=84, rel_spread=0.30, open_interest=50)
            for _ in range(3)
        ],
        # Expiry B: three tradable contracts, tight spreads (median 0.06).
        *[
            _metric(expiration="2026-09-18", days_to_expiry=98, rel_spread=0.06, open_interest=50)
            for _ in range(3)
        ],
    ]

    selection = select_most_liquid_expiry(
        metrics=metrics, ticker="NEM", side="P", horizon_days=90, band=BANDS[90]
    )

    assert selection is not None
    # Equal counts -> the tighter median spread wins (robust aggregate, not sum).
    assert selection.expiration == "2026-09-18"


def test_deterministic_tie_break_prefers_earlier_expiration():
    metrics = [
        _metric(expiration="2026-09-18", days_to_expiry=98),
        _metric(expiration="2026-09-25", days_to_expiry=98),
    ]

    selection = select_most_liquid_expiry(
        metrics=metrics, ticker="NEM", side="P", horizon_days=90, band=BANDS[90]
    )

    assert selection is not None
    assert selection.expiration == "2026-09-18"


def test_ticker_default_window_is_side_aware():
    metrics = [
        # Puts are deep in the 90d window...
        _metric(side="P", expiration="2026-09-18", days_to_expiry=98, open_interest=500),
        _metric(side="P", expiration="2027-02-19", days_to_expiry=255, open_interest=20),
        # ...calls are deep in the ~230d window.
        _metric(side="C", expiration="2026-09-18", days_to_expiry=98, open_interest=20),
        _metric(side="C", expiration="2027-02-19", days_to_expiry=255, open_interest=500),
        _metric(side="C", expiration="2027-02-19", days_to_expiry=255, open_interest=400),
    ]

    put_default = select_ticker_default_window(
        metrics=metrics, ticker="NEM", side="P", dte_bands=BANDS
    )
    call_default = select_ticker_default_window(
        metrics=metrics, ticker="NEM", side="C", dte_bands=BANDS
    )

    assert put_default is not None and put_default.horizon_days == 90
    assert call_default is not None and call_default.horizon_days == 230
    assert call_default.expiration == "2027-02-19"


def test_group_default_votes_per_ticker_and_excludes_benchmarks():
    metrics = [
        # Two miners each vote 90d with modest books.
        _metric(ticker="NEM", expiration="2026-09-18", days_to_expiry=98, open_interest=80),
        _metric(ticker="AEM", expiration="2026-09-18", days_to_expiry=98, open_interest=60),
        # GDX has a giant long-dated book; it must not drag the default.
        *[
            _metric(
                ticker="GDX",
                expiration="2027-02-19",
                days_to_expiry=255,
                open_interest=50000,
            )
            for _ in range(10)
        ],
    ]

    default = select_group_default_window(
        metrics=metrics,
        tickers=["NEM", "AEM", "GDX"],
        side="P",
        dte_bands=BANDS,
        exclude_tickers=["GDX", "GDXJ"],
    )

    assert default == 90


def test_no_tradable_contracts_yields_no_selection():
    metrics = [
        _metric(tier="watch"),
        _metric(tier="no_trade"),
    ]

    assert (
        select_most_liquid_expiry(
            metrics=metrics, ticker="NEM", side="P", horizon_days=90, band=BANDS[90]
        )
        is None
    )
    assert (
        select_group_default_window(
            metrics=metrics, tickers=["NEM"], side="P", dte_bands=BANDS
        )
        is None
    )
