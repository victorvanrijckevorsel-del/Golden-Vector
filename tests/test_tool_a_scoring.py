from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.scoring import compute_tool_a_score, rank_tool_a_outputs


def test_compute_tool_a_score_applies_weights_and_rounding():
    weights = load_app_config(ProjectPaths.discover()).app.scoring.weights

    score = compute_tool_a_score(
        delta_component_score=0.8,
        stability_score=0.7,
        gamma_component_score=0.5,
        score_eligible=True,
        weights=weights,
    )

    assert score == 71.0


def test_compute_tool_a_score_returns_none_when_row_is_ineligible():
    weights = load_app_config(ProjectPaths.discover()).app.scoring.weights

    score = compute_tool_a_score(
        delta_component_score=1.0,
        stability_score=1.0,
        gamma_component_score=1.0,
        score_eligible=False,
        weights=weights,
    )

    assert score is None


def test_rank_tool_a_outputs_uses_dense_ranking_and_leaves_ineligible_rows_unranked():
    frame = pd.DataFrame(
        [
            {"ticker": "NEM", "as_of_date": date(2026, 2, 1), "score_eligible": True, "tool_a_score": 90.0},
            {"ticker": "AEM", "as_of_date": date(2026, 2, 1), "score_eligible": True, "tool_a_score": 90.0},
            {"ticker": "GOLD", "as_of_date": date(2026, 2, 1), "score_eligible": True, "tool_a_score": 70.0},
            {"ticker": "KGC", "as_of_date": date(2026, 2, 1), "score_eligible": False, "tool_a_score": None},
        ]
    )

    ranked = rank_tool_a_outputs(frame).set_index("ticker")

    assert int(ranked.loc["NEM", "tool_a_rank"]) == 1
    assert int(ranked.loc["AEM", "tool_a_rank"]) == 1
    assert int(ranked.loc["GOLD", "tool_a_rank"]) == 2
    assert pd.isna(ranked.loc["KGC", "tool_a_rank"])
