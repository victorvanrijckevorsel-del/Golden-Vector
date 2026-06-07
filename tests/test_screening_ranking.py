from datetime import date

import pandas as pd

from golden_vector.screening.ranking import rank_tool_b_outputs


def test_rank_tool_b_outputs_uses_dense_ranking_per_date_and_gold_scenario():
    frame = pd.DataFrame(
        [
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "fundamental_check_score": 80.0},
            {"ticker": "AEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "fundamental_check_score": 80.0},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "fundamental_check_score": 70.0},
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4500.0, "fundamental_check_score": 60.0},
        ]
    )

    ranked = rank_tool_b_outputs(frame).set_index(["ticker", "gold_price_assumption"])

    assert int(ranked.loc[("NEM", 4000.0), "fundamental_check_rank"]) == 1
    assert int(ranked.loc[("AEM", 4000.0), "fundamental_check_rank"]) == 1
    assert int(ranked.loc[("GOLD", 4000.0), "fundamental_check_rank"]) == 2
    assert int(ranked.loc[("NEM", 4500.0), "fundamental_check_rank"]) == 1


def test_rank_tool_b_outputs_leaves_incomplete_rows_unranked():
    frame = pd.DataFrame(
        [
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "fundamental_check_score": 80.0},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "gold_price_assumption": 4000.0, "fundamental_check_score": None},
        ]
    )

    ranked = rank_tool_b_outputs(frame).set_index("ticker")

    assert int(ranked.loc["NEM", "fundamental_check_rank"]) == 1
    assert pd.isna(ranked.loc["GOLD", "fundamental_check_rank"])


def test_rank_tool_b_outputs_handles_missing_as_of_date_group():
    frame = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": None,
                "gold_price_assumption": 4000.0,
                "fundamental_check_score": 80.0,
            },
            {
                "ticker": "AEM",
                "as_of_date": None,
                "gold_price_assumption": 4000.0,
                "fundamental_check_score": 70.0,
            },
        ]
    )

    ranked = rank_tool_b_outputs(frame).set_index("ticker")

    assert int(ranked.loc["NEM", "fundamental_check_rank"]) == 1
    assert int(ranked.loc["AEM", "fundamental_check_rank"]) == 2
