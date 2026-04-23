from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.scoring import (
    compute_asymmetry_component_score,
    compute_delta_component_score,
    compute_gamma_component_score,
    compute_tool_a_score,
    rank_tool_a_outputs,
)


def test_compute_tool_a_score_applies_structural_weights_and_rounding():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    delta_component = compute_delta_component_score(
        1.8,
        bands=scoring.delta_bands,
    )
    gamma_component = compute_gamma_component_score(
        -0.25,
        thresholds=scoring.gamma_thresholds,
    )
    asymmetry_component = compute_asymmetry_component_score(
        asymmetry_ratio=1.25,
        up_beta=2.0,
        down_beta=1.6,
        thresholds=scoring.asymmetry_thresholds,
    )
    score = compute_tool_a_score(
        delta_component_score=delta_component,
        gamma_component_score=gamma_component,
        asymmetry_component_score=asymmetry_component,
        confidence_score=0.8,
        score_eligible=True,
        weights=scoring.weights,
    )

    assert score == 88.8


def test_compute_gamma_component_score_rewards_negative_gamma_and_penalizes_fragility():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    strong_upside = compute_gamma_component_score(
        -0.30,
        thresholds=scoring.gamma_thresholds,
    )
    fragile = compute_gamma_component_score(
        0.30,
        thresholds=scoring.gamma_thresholds,
    )

    assert strong_upside == 1.0
    assert fragile == 0.0


def test_compute_tool_a_score_returns_none_when_row_is_ineligible():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    score = compute_tool_a_score(
        delta_component_score=1.0,
        gamma_component_score=1.0,
        asymmetry_component_score=1.0,
        confidence_score=1.0,
        score_eligible=False,
        weights=scoring.weights,
    )

    assert score is None


def test_compute_asymmetry_component_score_returns_zero_when_down_beta_is_missing():
    """Regression: previously awarded 0.5 free credit when down-gold weeks were too thin."""
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    score = compute_asymmetry_component_score(
        asymmetry_ratio=None,
        up_beta=1.5,
        down_beta=None,
        thresholds=scoring.asymmetry_thresholds,
    )
    assert score == 0.0


def test_compute_asymmetry_component_score_still_rewards_clean_negative_down_beta():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring
    score = compute_asymmetry_component_score(
        asymmetry_ratio=None,
        up_beta=1.5,
        down_beta=-0.2,
        thresholds=scoring.asymmetry_thresholds,
    )
    assert score == 1.0


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
