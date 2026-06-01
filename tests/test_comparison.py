import pytest

from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.comparison import (
    COMPARISON_SORT_COLUMNS,
    build_comparison_table,
)
from golden_vector.hedge.scenarios import compute_scenario_bundle


def test_build_comparison_table_returns_empty_for_empty_input():
    assert build_comparison_table(bundles=[]) == []


def test_build_comparison_table_sorts_by_minus10_pnl_descending():
    rows = build_comparison_table(
        bundles=[
            _bundle("AEM", strike=45.0, mid=1.20),
            _bundle("NEM", strike=50.0, mid=1.00),
        ],
    )

    assert [row.ticker for row in rows] == ["NEM", "AEM"]
    assert rows[0].pnl_per_contract_minus10 == pytest.approx(6.0)
    assert rows[1].pnl_per_contract_minus10 == pytest.approx(0.80)


def test_build_comparison_table_sorts_by_return_on_premium():
    rows = build_comparison_table(
        bundles=[
            _bundle("AEM", strike=45.0, mid=1.20),
            _bundle("NEM", strike=50.0, mid=6.00),
        ],
        sort_by="pnl_per_dollar_premium_minus10",
    )

    assert [row.ticker for row in rows] == ["AEM", "NEM"]
    assert rows[0].pnl_per_dollar_premium_minus10 == pytest.approx(0.80 / 1.20)


def test_build_comparison_table_skips_unusable_bundles():
    skipped = compute_scenario_bundle(
        candidate=_candidate("AEM", strike=45.0, mid=1.20),
        current_stock_price=50.0,
        down_beta_core=None,
        confidence_label="low",
        risk_free_rate=0.04,
    )

    assert build_comparison_table(bundles=[skipped]) == []


def test_build_comparison_table_places_missing_sort_values_last():
    rows = build_comparison_table(
        bundles=[
            _bundle("AEM", strike=45.0, mid=1.20, scenarios=(-0.10,)),
            _bundle("NEM", strike=50.0, mid=1.00),
        ],
        sort_by="pnl_per_contract_minus20",
    )

    assert [row.ticker for row in rows] == ["NEM", "AEM"]
    assert rows[1].pnl_per_contract_minus20 is None


def test_build_comparison_table_rejects_unknown_sort_column():
    with pytest.raises(ValueError, match="Unsupported comparison sort column"):
        build_comparison_table(bundles=[], sort_by="banana")


def test_comparison_sort_columns_cover_cli_choices():
    assert set(COMPARISON_SORT_COLUMNS) == {
        "pnl_per_contract_minus5",
        "pnl_per_contract_minus10",
        "pnl_per_contract_minus20",
        "pnl_per_dollar_premium_minus10",
        "breakeven_gold_pct",
    }


def _bundle(
    ticker: str,
    *,
    strike: float,
    mid: float,
    scenarios: tuple[float, ...] = (-0.05, -0.10, -0.20),
):
    return compute_scenario_bundle(
        candidate=_candidate(ticker, strike=strike, mid=mid),
        current_stock_price=50.0,
        down_beta_core=1.40,
        confidence_label="high",
        risk_free_rate=0.04,
        gold_scenarios=scenarios,
        quantity=5,
    )


def _candidate(ticker: str, *, strike: float, mid: float) -> CandidatePut:
    return CandidatePut(
        ticker=ticker,
        horizon_days=60,
        expiration="2026-07-31",
        days_to_expiry=60,
        strike=strike,
        bid=mid - 0.05,
        ask=mid + 0.05,
        mid=mid,
        open_interest=500,
        volume=50,
        implied_volatility=0.40,
        delta=-0.25,
        delta_gap=0.01,
        premium_pct_spot=mid / 50.0,
        underlying_price=50.0,
    )
