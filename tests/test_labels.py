from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.labels import (
    determine_confidence_label,
    determine_profile_label,
    determine_score_eligibility,
    determine_volatility_context,
)


def test_determine_confidence_label_uses_structural_thresholds():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    assert determine_confidence_label(confidence_score=0.82, scoring_config=scoring) == "HIGH"
    assert determine_confidence_label(confidence_score=0.62, scoring_config=scoring) == "MEDIUM"
    assert determine_confidence_label(confidence_score=0.2, scoring_config=scoring) == "LOW"
    assert determine_confidence_label(
        confidence_score=0.95,
        scoring_config=scoring,
        score_eligible=False,
        score_eligibility_reason="UNACCEPTABLE_NORMALIZATION_STATUS",
    ) == "WITHHELD"


def test_determine_score_eligibility_returns_specific_blocking_reasons():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    assert determine_score_eligibility(
        structural_delta_core=1.0,
        eligible_structural_window_count=1,
        confidence_score=0.8,
        normalization_issue_summary=None,
        scoring_config=scoring,
    ) == (False, "INSUFFICIENT_ELIGIBLE_STRUCTURAL_WINDOWS")
    assert determine_score_eligibility(
        structural_delta_core=None,
        eligible_structural_window_count=3,
        confidence_score=0.8,
        normalization_issue_summary=None,
        scoring_config=scoring,
    ) == (False, "MISSING_STRUCTURAL_DELTA")
    assert determine_score_eligibility(
        structural_delta_core=0.0,
        eligible_structural_window_count=3,
        confidence_score=0.8,
        normalization_issue_summary=None,
        scoring_config=scoring,
    ) == (False, "NON_POSITIVE_STRUCTURAL_DELTA")
    assert determine_score_eligibility(
        structural_delta_core=1.0,
        eligible_structural_window_count=3,
        confidence_score=0.2,
        normalization_issue_summary=None,
        scoring_config=scoring,
    ) == (False, "LOW_CONFIDENCE_STRUCTURAL_SIGNAL")
    assert determine_score_eligibility(
        structural_delta_core=1.0,
        eligible_structural_window_count=3,
        confidence_score=0.8,
        normalization_issue_summary="MISSING_RETURN_BASIS",
        scoring_config=scoring,
    ) == (False, "UNACCEPTABLE_NORMALIZATION_STATUS")
    assert determine_score_eligibility(
        structural_delta_core=1.0,
        eligible_structural_window_count=3,
        confidence_score=0.8,
        normalization_issue_summary="STALE_FX",
        scoring_config=scoring,
    ) == (False, "UNACCEPTABLE_NORMALIZATION_STATUS")
    assert determine_score_eligibility(
        structural_delta_core=0.8,
        eligible_structural_window_count=3,
        confidence_score=0.8,
        normalization_issue_summary=None,
        scoring_config=scoring,
    ) == (False, "LOW_LINKAGE_STRUCTURAL_SIGNAL")


def test_determine_volatility_context_distinguishes_noise_and_downside_risk():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    assert determine_volatility_context(
        total_volatility_52w=0.3,
        residual_volatility_52w=0.2,
        downside_volatility_52w=0.2,
        scoring_config=scoring,
    ) == "LOW_NOISE"
    assert determine_volatility_context(
        total_volatility_52w=0.8,
        residual_volatility_52w=0.65,
        downside_volatility_52w=0.2,
        scoring_config=scoring,
    ) == "HIGH_NOISE"
    assert determine_volatility_context(
        total_volatility_52w=0.4,
        residual_volatility_52w=0.4,
        downside_volatility_52w=0.6,
        scoring_config=scoring,
    ) == "HIGH_DOWNSIDE_RISK"


def test_determine_profile_label_covers_structural_branches():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    assert determine_profile_label(
        score_eligible=False,
        score_eligibility_reason="INSUFFICIENT_ELIGIBLE_STRUCTURAL_WINDOWS",
        structural_delta_core=None,
        structural_gamma_core=None,
        asymmetry_ratio_core=None,
        up_beta_core=None,
        down_beta_core=None,
        confidence_label="LOW",
        residual_volatility_52w=None,
        volatility_context="MODERATE_NOISE",
        scoring_config=scoring,
    ) == "UNRELIABLE_SIGNAL"
    assert determine_profile_label(
        score_eligible=False,
        score_eligibility_reason="LOW_LINKAGE_STRUCTURAL_SIGNAL",
        structural_delta_core=0.5,
        structural_gamma_core=-0.2,
        asymmetry_ratio_core=1.2,
        up_beta_core=1.2,
        down_beta_core=1.0,
        confidence_label="HIGH",
        residual_volatility_52w=0.2,
        volatility_context="LOW_NOISE",
        scoring_config=scoring,
    ) == "LOW_LINKAGE"
    assert determine_profile_label(
        score_eligible=True,
        score_eligibility_reason="OK",
        structural_delta_core=1.8,
        structural_gamma_core=-0.2,
        asymmetry_ratio_core=1.3,
        up_beta_core=2.1,
        down_beta_core=1.4,
        confidence_label="HIGH",
        residual_volatility_52w=0.2,
        volatility_context="LOW_NOISE",
        scoring_config=scoring,
    ) == "CONVEX"
    assert determine_profile_label(
        score_eligible=True,
        score_eligibility_reason="OK",
        structural_delta_core=2.2,
        structural_gamma_core=0.05,
        asymmetry_ratio_core=1.0,
        up_beta_core=1.8,
        down_beta_core=1.8,
        confidence_label="HIGH",
        residual_volatility_52w=0.3,
        volatility_context="MODERATE_NOISE",
        scoring_config=scoring,
    ) == "HIGH_DELTA"
    assert determine_profile_label(
        score_eligible=True,
        score_eligibility_reason="OK",
        structural_delta_core=1.4,
        structural_gamma_core=0.0,
        asymmetry_ratio_core=1.0,
        up_beta_core=1.3,
        down_beta_core=1.3,
        confidence_label="HIGH",
        residual_volatility_52w=0.2,
        volatility_context="LOW_NOISE",
        scoring_config=scoring,
    ) == "LINEAR"
    assert determine_profile_label(
        score_eligible=True,
        score_eligibility_reason="OK",
        structural_delta_core=1.4,
        structural_gamma_core=0.0,
        asymmetry_ratio_core=1.0,
        up_beta_core=1.2,
        down_beta_core=1.2,
        confidence_label="MEDIUM",
        residual_volatility_52w=0.45,
        volatility_context="MODERATE_NOISE",
        scoring_config=scoring,
    ) == "DEFENSIVE"
    assert determine_profile_label(
        score_eligible=True,
        score_eligibility_reason="OK",
        structural_delta_core=1.5,
        structural_gamma_core=0.25,
        asymmetry_ratio_core=0.75,
        up_beta_core=1.1,
        down_beta_core=1.5,
        confidence_label="HIGH",
        residual_volatility_52w=0.25,
        volatility_context="LOW_NOISE",
        scoring_config=scoring,
    ) == "FRAGILE"
    assert determine_profile_label(
        score_eligible=False,
        score_eligibility_reason="UNACCEPTABLE_NORMALIZATION_STATUS",
        structural_delta_core=1.5,
        structural_gamma_core=-0.3,
        asymmetry_ratio_core=1.2,
        up_beta_core=1.6,
        down_beta_core=1.2,
        confidence_label="WITHHELD",
        residual_volatility_52w=0.3,
        volatility_context="LOW_NOISE",
        scoring_config=scoring,
    ) == "SCORE_WITHHELD"
