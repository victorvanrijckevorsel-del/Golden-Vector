"""Milestone B: Cached Liquidity Check medians cover tradable contracts only.

The Tradable/Watch/No-trade counts keep describing every measured contract,
but the spread/OI/volume/near-spot-depth medians describe only the tradable
tier — the contracts a user could actually trade. The aggregation lives in one
backend primitive (`aggregate_tradable_liquidity`) that Milestone C3's
most-liquid selector will reuse.
"""

from __future__ import annotations

from typing import Literal, cast

import pytest

from golden_vector.hedge.option_trading import OptionLiquidityMeasurement
from golden_vector.hedge.options_liquidity import (
    OptionContractMetrics,
    aggregate_tradable_liquidity,
)
from golden_vector.serve.overview_option_trading import _render_liquidity_measurements


def _metric(
    *,
    tier: str,
    rel_spread: float | None = 0.10,
    mid: float | None = 2.0,
    open_interest: int = 100,
    volume: int = 10,
    near_spot_depth_count: int = 8,
) -> OptionContractMetrics:
    return OptionContractMetrics(
        ticker="NEM",
        option_type=cast(Literal["P", "C"], "P"),
        expiration="2026-09-18",
        days_to_expiry=74,
        strike=95.0,
        underlying_price=100.0,
        bid=1.9,
        ask=2.1,
        mid=mid,
        last_price=mid,
        open_interest=open_interest,
        volume=volume,
        implied_volatility=0.35,
        delta=-0.25,
        rel_spread=rel_spread,
        half_spread_cost_pct=0.05,
        moneyness_pct=0.05,
        otm_pct=0.05,
        premium_pct_spot=0.02,
        near_spot_depth_count=near_spot_depth_count,
        liquidity_score=0.8,
        liquidity_tier=cast(Literal["tradable", "watch", "no_trade"], tier),
        quote_flags=(),
        is_standard_monthly=True,
    )


def test_medians_use_tradable_contracts_only_while_counts_cover_all_tiers():
    metrics = [
        _metric(tier="tradable", rel_spread=0.10, open_interest=100, volume=10, near_spot_depth_count=8),
        _metric(tier="tradable", rel_spread=0.20, open_interest=200, volume=20, near_spot_depth_count=10),
        # Watch/no-trade rows have wildly different stats; they must move the
        # counts but never the medians.
        _metric(tier="watch", rel_spread=0.90, open_interest=1, volume=0, near_spot_depth_count=1),
        _metric(tier="no_trade", rel_spread=2.50, open_interest=0, volume=0, near_spot_depth_count=0),
    ]

    aggregate = aggregate_tradable_liquidity(metrics)

    assert aggregate.measured_count == 4
    assert aggregate.tradable_count == 2
    assert aggregate.watch_count == 1
    assert aggregate.no_trade_count == 1
    assert aggregate.median_tradable_rel_spread == pytest.approx(0.15)
    assert aggregate.median_tradable_open_interest == 150.0
    assert aggregate.median_tradable_volume == 15.0
    assert aggregate.median_tradable_near_spot_depth == 9.0


def test_zero_tradable_contracts_yield_none_medians_but_full_counts():
    metrics = [
        _metric(tier="watch", rel_spread=0.40),
        _metric(tier="no_trade", rel_spread=1.20),
    ]

    aggregate = aggregate_tradable_liquidity(metrics)

    assert aggregate.measured_count == 2
    assert aggregate.tradable_count == 0
    assert aggregate.watch_count == 1
    assert aggregate.no_trade_count == 1
    assert aggregate.median_tradable_rel_spread is None
    assert aggregate.median_tradable_open_interest is None
    assert aggregate.median_tradable_volume is None
    assert aggregate.median_tradable_near_spot_depth is None


def test_unusable_quotes_are_excluded_from_measurement_entirely():
    metrics = [
        _metric(tier="tradable", rel_spread=0.10),
        _metric(tier="no_trade", rel_spread=None),
        _metric(tier="no_trade", mid=None),
        _metric(tier="no_trade", mid=0.0),
    ]

    aggregate = aggregate_tradable_liquidity(metrics)

    assert aggregate.measured_count == 1
    assert aggregate.tradable_count == 1
    assert aggregate.no_trade_count == 0


def test_liquidity_table_renders_tradable_headers_and_dash_for_empty_medians():
    measurements = (
        OptionLiquidityMeasurement(
            group_label="Benchmark ETFs",
            ticker_count=2,
            contract_count=5,
            median_rel_spread=None,
            median_open_interest=None,
            median_volume=None,
            median_near_spot_depth=None,
            tradable_count=0,
            watch_count=3,
            no_trade_count=2,
        ),
    )

    html = _render_liquidity_measurements(measurements)

    assert "Median Tradable Spread" in html
    assert "Median Tradable OI" in html
    assert "Median Tradable Volume" in html
    assert "Median Tradable Near-Spot Depth" in html
    assert "medians cover tradable contracts only" in html
    # Zero tradable contracts: counts render, medians render as dashes.
    assert "<td>3</td>" in html
    assert "<td>-</td>" in html
