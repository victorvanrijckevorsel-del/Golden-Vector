import pandas as pd
import pytest

from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.holdings import Holding
from golden_vector.hedge.portfolio_totals import compute_portfolio_totals


def test_compute_portfolio_totals_returns_none_for_empty_holdings():
    assert compute_portfolio_totals(
        holdings=[],
        tool_a_frame=pd.DataFrame(),
        tool_b_frame=pd.DataFrame(),
        candidate_grids={},
        config=_config(),
    ) is None


def test_compute_portfolio_totals_handles_share_mode_holding():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", shares=200.0)],
        tool_a_frame=_tool_a([("AEM", 1.40)]),
        tool_b_frame=_tool_b([("AEM", 50.0)]),
        candidate_grids={"AEM": [_candidate("AEM", mid=1.20, underlying_price=50.0)]},
        config=_config(),
    )

    assert totals is not None
    assert totals.holdings_count == 1
    assert totals.holdings_resolved_count == 1
    assert totals.current_total_value == pytest.approx(10_000.0)
    downside = totals.scenario_rows[1]
    assert downside.gold_pct_change == -0.10
    assert downside.portfolio_value_at_scenario == pytest.approx(8_600.0)
    assert downside.portfolio_loss_dollars == pytest.approx(1_400.0)
    assert downside.portfolio_loss_pct == pytest.approx(0.14)
    assert totals.hedge_cost_by_protection[0.5] == pytest.approx(120.0)
    assert totals.hedge_cost_by_protection[1.0] == pytest.approx(240.0)


def test_compute_portfolio_totals_prefers_options_feature_price_over_tool_b_price():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", shares=200.0)],
        tool_a_frame=_tool_a([("AEM", 1.00)]),
        tool_b_frame=_tool_b([("AEM", 50.0)]),
        options_features=pd.DataFrame(
            [{"ticker": "AEM", "underlying_price": 55.0}]
        ),
        candidate_grids={"AEM": [_candidate("AEM", mid=1.20, underlying_price=55.0)]},
        config=_config(protection_levels=[1.0]),
    )

    assert totals is not None
    assert totals.current_total_value == pytest.approx(11_000.0)
    assert totals.scenario_rows[1].portfolio_loss_dollars == pytest.approx(1_100.0)
    assert totals.hedge_cost_by_protection[1.0] == pytest.approx(240.0)


def test_compute_portfolio_totals_handles_dollar_exposure_mode_holding():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="NEM", dollar_exposure=50_000.0)],
        tool_a_frame=_tool_a([("NEM", 1.00)]),
        tool_b_frame=_tool_b([("NEM", 50.0)]),
        candidate_grids={"NEM": [_candidate("NEM", mid=2.00, underlying_price=50.0)]},
        config=_config(),
    )

    assert totals is not None
    downside = totals.scenario_rows[1]
    assert totals.current_total_value == pytest.approx(50_000.0)
    assert downside.portfolio_value_at_scenario == pytest.approx(45_000.0)
    assert downside.portfolio_loss_dollars == pytest.approx(5_000.0)
    assert totals.hedge_cost_by_protection[0.5] == pytest.approx(1_000.0)
    assert totals.holdings_excluded_from_totals == []
    assert totals.downside_model_skipped == []
    assert totals.hedge_cost_skipped == []


def test_compute_portfolio_totals_handles_mixed_holdings():
    totals = compute_portfolio_totals(
        holdings=[
            Holding(ticker="AEM", shares=100.0),
            Holding(ticker="NEM", dollar_exposure=20_000.0),
        ],
        tool_a_frame=_tool_a([("AEM", 1.00), ("NEM", 1.50)]),
        tool_b_frame=_tool_b([("AEM", 50.0), ("NEM", 100.0)]),
        candidate_grids={
            "AEM": [_candidate("AEM", mid=1.00, underlying_price=50.0)],
            "NEM": [_candidate("NEM", mid=2.00, underlying_price=100.0)],
        },
        config=_config(),
    )

    assert totals is not None
    assert totals.current_total_value == pytest.approx(25_000.0)
    assert totals.scenario_rows[1].portfolio_loss_dollars == pytest.approx(3_500.0)
    assert totals.hedge_cost_by_protection[1.0] == pytest.approx(500.0)


def test_compute_portfolio_totals_counts_dollar_notional_without_price_but_skips_hedge_cost():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", dollar_exposure=50_000.0)],
        tool_a_frame=_tool_a([("AEM", 1.00)]),
        tool_b_frame=pd.DataFrame(),
        candidate_grids={"AEM": [_candidate("AEM", mid=2.00, underlying_price=0.0)]},
        config=_config(),
    )

    assert totals is not None
    assert totals.current_total_value == pytest.approx(50_000.0)
    downside = totals.scenario_rows[1]
    assert downside.portfolio_loss_dollars == pytest.approx(5_000.0)
    assert totals.hedge_cost_by_protection[1.0] == 0.0
    assert totals.holdings_excluded_from_totals == []
    assert totals.downside_model_skipped == []
    assert totals.hedge_cost_skipped == [("AEM", "no hedge-cost inputs")]


def test_compute_portfolio_totals_skips_share_holding_without_price():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", shares=100.0)],
        tool_a_frame=_tool_a([("AEM", 1.00)]),
        tool_b_frame=pd.DataFrame(),
        candidate_grids={},
        config=_config(),
    )

    assert totals is not None
    assert totals.current_total_value == 0.0
    assert totals.holdings_resolved_count == 0
    assert totals.holdings_excluded_from_totals == [("AEM", "missing share price")]
    assert totals.downside_model_skipped == []
    assert totals.hedge_cost_skipped == []


def test_compute_portfolio_totals_notes_missing_candidate_and_skips_hedge_cost():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", dollar_exposure=10_000.0)],
        tool_a_frame=_tool_a([("AEM", 1.00)]),
        tool_b_frame=_tool_b([("AEM", 50.0)]),
        candidate_grids={},
        config=_config(),
    )

    assert totals is not None
    assert totals.scenario_rows[1].portfolio_loss_dollars == pytest.approx(1_000.0)
    assert totals.hedge_cost_by_protection[1.0] == 0.0
    assert totals.holdings_excluded_from_totals == []
    assert totals.downside_model_skipped == []
    assert totals.hedge_cost_skipped == [("AEM", "no 60d candidate")]


def test_compute_portfolio_totals_uses_non_60d_candidate_price_for_notional_only():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", shares=200.0)],
        tool_a_frame=_tool_a([("AEM", 1.00)]),
        tool_b_frame=pd.DataFrame(),
        candidate_grids={
            "AEM": [
                _candidate(
                    "AEM",
                    mid=1.00,
                    underlying_price=50.0,
                    horizon_days=30,
                )
            ]
        },
        config=_config(protection_levels=[1.0]),
    )

    assert totals is not None
    assert totals.current_total_value == pytest.approx(10_000.0)
    assert totals.holdings_resolved_count == 1
    assert totals.hedge_cost_skipped == [("AEM", "no 60d candidate")]
    assert totals.hedge_cost_by_protection[1.0] == 0.0


def test_compute_portfolio_totals_low_beta_holding_counts_notional_but_not_scenario_loss():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", dollar_exposure=10_000.0)],
        tool_a_frame=_tool_a([("AEM", 0.05)]),
        tool_b_frame=_tool_b([("AEM", 50.0)]),
        candidate_grids={"AEM": [_candidate("AEM", mid=1.00, underlying_price=50.0)]},
        config=_config(down_beta_min_for_scenario=0.10),
    )

    assert totals is not None
    assert totals.current_total_value == pytest.approx(10_000.0)
    assert totals.scenario_rows[1].portfolio_loss_dollars == 0.0
    assert totals.holdings_excluded_from_totals == []
    assert totals.downside_model_skipped == [
        ("AEM", "down-beta unavailable or too small")
    ]
    assert totals.hedge_cost_skipped == []


def test_compute_portfolio_totals_ceil_rounds_contracts_needed():
    totals = compute_portfolio_totals(
        holdings=[Holding(ticker="AEM", shares=101.0)],
        tool_a_frame=_tool_a([("AEM", 1.00)]),
        tool_b_frame=_tool_b([("AEM", 50.0)]),
        candidate_grids={"AEM": [_candidate("AEM", mid=1.00, underlying_price=50.0)]},
        config=_config(protection_levels=[1.0]),
    )

    assert totals is not None
    assert totals.hedge_cost_by_protection[1.0] == pytest.approx(200.0)


def _config(
    *,
    protection_levels: list[float] | None = None,
    down_beta_min_for_scenario: float = 0.10,
) -> HedgeReadinessConfig:
    return HedgeReadinessConfig(
        default_scenarios=[0.0, -0.10],
        protection_levels=protection_levels or [0.5, 1.0],
        down_beta_min_for_scenario=down_beta_min_for_scenario,
    )


def _tool_a(rows):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "down_beta_core": down_beta,
            }
            for ticker, down_beta in rows
        ]
    )


def _tool_b(rows):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "share_price_usd": price,
            }
            for ticker, price in rows
        ]
    )


def _candidate(
    ticker: str,
    *,
    mid: float,
    underlying_price: float,
    horizon_days: int = 60,
) -> CandidatePut:
    return CandidatePut(
        ticker=ticker,
        horizon_days=horizon_days,
        expiration="2026-07-31",
        days_to_expiry=60,
        strike=45.0,
        bid=mid - 0.05,
        ask=mid + 0.05,
        mid=mid,
        open_interest=500,
        volume=50,
        implied_volatility=0.40,
        delta=-0.25,
        delta_gap=0.01,
        premium_pct_spot=mid / underlying_price if underlying_price > 0 else None,
        underlying_price=underlying_price,
    )
