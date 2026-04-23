from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.explanations import build_delta_explanation


def _scoring():
    return load_app_config(ProjectPaths.discover()).app.scoring


def test_build_delta_explanation_does_not_claim_no_rank_when_score_is_eligible():
    """Regression for the FNV case: anchor delta < minimum_rankable but core >= minimum_rankable."""
    scoring = _scoring()

    explanation = build_delta_explanation(
        anchor_delta=0.9997,  # below minimum_rankable_structural_delta (1.0)
        anchor_window_id="12M",
        structural_delta_core=1.108,  # above threshold; row is rankable
        score_eligible=True,
        score_eligibility_reason="OK",
        scoring_config=scoring,
    )

    assert "earn an official rank" not in explanation.lower()
    assert "structural delta" in explanation.lower()


def test_build_delta_explanation_calls_out_low_linkage_when_score_is_withheld():
    scoring = _scoring()

    explanation = build_delta_explanation(
        anchor_delta=0.5,
        anchor_window_id="12M",
        structural_delta_core=0.6,
        score_eligible=False,
        score_eligibility_reason="LOW_LINKAGE_STRUCTURAL_SIGNAL",
        scoring_config=scoring,
    )

    assert "earn an official rank" in explanation
    assert "0.60" in explanation


def test_build_delta_explanation_withholds_when_normalization_blocked():
    scoring = _scoring()

    explanation = build_delta_explanation(
        anchor_delta=1.5,
        anchor_window_id="12M",
        structural_delta_core=1.5,
        score_eligible=False,
        score_eligibility_reason="UNACCEPTABLE_NORMALIZATION_STATUS",
        scoring_config=scoring,
    )

    assert "withheld" in explanation.lower()


def test_build_delta_explanation_describes_high_delta_for_eligible_row():
    scoring = _scoring()

    explanation = build_delta_explanation(
        anchor_delta=2.1,
        anchor_window_id="12M",
        structural_delta_core=2.1,
        score_eligible=True,
        score_eligibility_reason="OK",
        scoring_config=scoring,
    )

    assert "High structural delta" in explanation
    assert "12M anchor window" in explanation
