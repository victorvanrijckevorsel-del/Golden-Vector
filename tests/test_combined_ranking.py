from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.combined.ranking import (
    compute_combined_score,
    determine_combined_verdict,
    determine_join_status,
    rank_combined_outputs,
)


def test_determine_join_status_and_combined_score_distinguish_complete_and_partial_rows():
    complete_row = pd.Series(
        {
            "tool_a_run_id": "tool-a-run",
            "tool_b_run_id": "tool-b-run",
            "tool_a_score": 80.0,
            "tool_b_score": 70.0,
        }
    )
    partial_row = pd.Series(
        {
            "tool_a_run_id": "tool-a-run",
            "tool_b_run_id": None,
            "tool_a_score": 80.0,
            "tool_b_score": None,
        }
    )

    assert determine_join_status(complete_row) == "COMPLETE"
    assert compute_combined_score(complete_row) == 75.0
    assert determine_join_status(partial_row) == "PARTIAL"
    assert compute_combined_score(partial_row) is None


def test_determine_combined_verdict_covers_partial_and_complete_outcomes():
    thresholds = load_app_config(ProjectPaths.discover()).app.scoring.combined_verdict_thresholds

    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": None, "tool_a_score": 80.0}),
        thresholds=thresholds,
    ) == "TOOL_A_ONLY"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": None, "tool_b_run_id": "b", "tool_b_score": 80.0}),
        thresholds=thresholds,
    ) == "TOOL_B_ONLY"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": "b", "tool_a_score": None, "tool_b_score": 80.0}),
        thresholds=thresholds,
    ) == "INCOMPLETE"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": "b", "tool_a_score": 80.0, "tool_b_score": 90.0, "screening_verdict": "STRONG_CANDIDATE"}),
        thresholds=thresholds,
    ) == "HIGH_CONVICTION"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": "b", "tool_a_score": 65.0, "tool_b_score": 70.0, "screening_verdict": "WATCHLIST"}),
        thresholds=thresholds,
    ) == "DUAL_PASS"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": "b", "tool_a_score": 65.0, "tool_b_score": 30.0, "screening_verdict": "SCREEN_OUT"}),
        thresholds=thresholds,
    ) == "GOLD_BETA_ONLY"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": "b", "tool_a_score": 40.0, "tool_b_score": 90.0, "screening_verdict": "STRONG_CANDIDATE"}),
        thresholds=thresholds,
    ) == "VALUATION_ONLY"
    assert determine_combined_verdict(
        pd.Series({"tool_a_run_id": "a", "tool_b_run_id": "b", "tool_a_score": 40.0, "tool_b_score": 70.0, "screening_verdict": "WATCHLIST"}),
        thresholds=thresholds,
    ) == "REVIEW"


def test_rank_combined_outputs_uses_dense_ranking_per_date_and_scenario():
    frame = pd.DataFrame(
        [
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "combined_score": 90.0},
            {"ticker": "AEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "combined_score": 90.0},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "combined_score": 80.0},
            {"ticker": "NEM", "as_of_date": date(2026, 2, 2), "gold_price_assumption": 4000.0, "combined_score": 85.0},
        ]
    )

    ranked = rank_combined_outputs(frame).set_index(["ticker", "as_of_date"])

    assert int(ranked.loc[("NEM", date(2026, 2, 1)), "combined_rank"]) == 1
    assert int(ranked.loc[("AEM", date(2026, 2, 1)), "combined_rank"]) == 1
    assert int(ranked.loc[("GOLD", date(2026, 2, 1)), "combined_rank"]) == 2
    assert int(ranked.loc[("NEM", date(2026, 2, 2)), "combined_rank"]) == 1
