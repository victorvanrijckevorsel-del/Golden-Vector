import pandas as pd
import pytest

from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.sensitivity_ranking import build_sensitivity_ranking


def test_build_sensitivity_ranking_sorts_rankable_rows_by_core_down_beta():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a(
            [
                ("AEM", 1.40, 1.10, "HIGH", 0.80, True),
                ("KGC", 1.80, 1.20, "HIGH", 0.85, True),
            ]
        ),
        options_features=_features(
            [
                ("AEM", "directly_hedgeable", 35.0),
                ("KGC", "directly_hedgeable", 45.0),
            ]
        ),
        candidate_grids={
            "AEM": [_candidate("AEM", horizon_days=60)],
            "KGC": [_candidate("KGC", horizon_days=60)],
        },
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
    )

    assert [row.ticker for row in ranking.rows] == ["KGC", "AEM"]
    assert [row.rank for row in ranking.rows] == [1, 2]
    assert ranking.rows[0].pnl_at_minus10_60d == pytest.approx(2.80)
    assert ranking.rows[1].pnl_at_minus10_60d == pytest.approx(0.80)
    assert ranking.total_count == 2
    assert ranking.score_eligible_count == 2


def test_build_sensitivity_ranking_ranks_ineligible_beta_rows_with_note():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a(
            [
                ("AEM", 1.40, 1.10, "HIGH", 0.80, True),
                ("BAD", 2.00, 1.00, "WITHHELD", None, False),
                ("NULL", None, 1.00, "WITHHELD", None, True),
            ]
        ),
        options_features=_features([("AEM", "directly_hedgeable", 35.0)]),
        candidate_grids={"AEM": [_candidate("AEM", horizon_days=60)]},
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
    )

    assert [row.ticker for row in ranking.rows] == ["BAD", "AEM", "NULL"]
    assert ranking.rows[0].rank == 1
    assert "score withheld; downside beta shown for context" in ranking.rows[0].notes
    assert ranking.rows[1].rank == 2
    assert ranking.rows[2].rank is None
    assert "down-beta unavailable" in ranking.rows[2].notes
    assert ranking.score_eligible_count == 1


def test_build_sensitivity_ranking_notes_missing_60d_candidate():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
        options_features=_features([("AEM", "directly_hedgeable", 35.0)]),
        candidate_grids={"AEM": [_candidate("AEM", horizon_days=30)]},
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
    )

    row = ranking.rows[0]
    assert row.pnl_at_minus10_60d is None
    assert "no 60d candidate" in row.notes


def test_build_sensitivity_ranking_notes_missing_options_features():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
        options_features=pd.DataFrame(),
        candidate_grids={},
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
    )

    row = ranking.rows[0]
    assert row.optionability_tier == "none"
    assert "no options features" in row.notes
    assert "no listed options" in row.notes


def test_build_sensitivity_ranking_treats_missing_optionability_as_none():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
        options_features=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "optionability_tier": pd.NA,
                    "iv_percentile_cross_sectional": 35.0,
                }
            ]
        ),
        candidate_grids={},
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
    )

    row = ranking.rows[0]
    assert row.optionability_tier == "none"
    assert "no listed options" in row.notes


def test_build_sensitivity_ranking_honors_max_tickers_cap():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a(
            [
                ("AEM", 1.40, 1.10, "HIGH", 0.80, True),
                ("KGC", 1.80, 1.20, "HIGH", 0.85, True),
            ]
        ),
        options_features=_features(
            [
                ("AEM", "directly_hedgeable", 35.0),
                ("KGC", "directly_hedgeable", 45.0),
            ]
        ),
        candidate_grids={
            "AEM": [_candidate("AEM", horizon_days=60)],
            "KGC": [_candidate("KGC", horizon_days=60)],
        },
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
        max_tickers=1,
    )

    assert [row.ticker for row in ranking.rows] == ["KGC"]


def test_build_sensitivity_ranking_does_not_note_rate_fallback_for_expiry_pnl():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
        options_features=_features([("AEM", "directly_hedgeable", 35.0)]),
        candidate_grids={"AEM": [_candidate("AEM", horizon_days=60)]},
        risk_free_rate=None,
        down_beta_min_for_scenario=0.10,
    )

    assert ranking.rows[0].pnl_at_minus10_60d == pytest.approx(0.80)
    assert "risk-free rate unavailable; used 0%" not in ranking.rows[0].notes


def test_build_sensitivity_ranking_skips_risk_free_note_when_pricing_is_not_run():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
        options_features=_features([("AEM", "directly_hedgeable", 35.0)]),
        candidate_grids={},
        risk_free_rate=None,
        down_beta_min_for_scenario=0.10,
    )

    assert "no 60d candidate" in ranking.rows[0].notes
    assert "risk-free rate unavailable; used 0%" not in ranking.rows[0].notes


def test_build_sensitivity_ranking_rejects_unknown_sort_column():
    with pytest.raises(ValueError, match="down_beta_core"):
        build_sensitivity_ranking(
            tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
            options_features=pd.DataFrame(),
            candidate_grids={},
            risk_free_rate=0.04,
            down_beta_min_for_scenario=0.10,
            sort_by="down_beta_12m",
        )


def test_build_sensitivity_ranking_uses_latest_feature_row_by_date():
    ranking = build_sensitivity_ranking(
        tool_a_frame=_tool_a([("AEM", 1.40, 1.10, "HIGH", 0.80, True)]),
        options_features=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "as_of_date": "2026-06-01",
                    "optionability_tier": "directly_hedgeable",
                    "iv_percentile_cross_sectional": 70.0,
                },
                {
                    "ticker": "AEM",
                    "as_of_date": "2026-05-01",
                    "optionability_tier": "none",
                    "iv_percentile_cross_sectional": 20.0,
                },
            ]
        ),
        candidate_grids={},
        risk_free_rate=0.04,
        down_beta_min_for_scenario=0.10,
    )

    assert ranking.rows[0].optionability_tier == "directly_hedgeable"
    assert ranking.rows[0].iv_percentile_cross_sectional == pytest.approx(70.0)


def _tool_a(rows):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "down_beta_core": down_beta,
                "up_beta_core": up_beta,
                "confidence_label": confidence_label,
                "confidence_score": confidence_score,
                "score_eligible": score_eligible,
            }
            for ticker, down_beta, up_beta, confidence_label, confidence_score, score_eligible in rows
        ]
    )


def _features(rows):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "optionability_tier": tier,
                "iv_percentile_cross_sectional": iv_percentile,
            }
            for ticker, tier, iv_percentile in rows
        ]
    )


def _candidate(ticker: str, *, horizon_days: int) -> CandidatePut:
    return CandidatePut(
        ticker=ticker,
        horizon_days=horizon_days,
        expiration="2026-07-31",
        days_to_expiry=horizon_days,
        strike=45.0,
        bid=1.15,
        ask=1.25,
        mid=1.20,
        open_interest=500,
        volume=50,
        implied_volatility=0.40,
        delta=-0.25,
        delta_gap=0.01,
        premium_pct_spot=1.20 / 50.0,
        underlying_price=50.0,
    )
