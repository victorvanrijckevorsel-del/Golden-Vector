from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.model.labels import (
    determine_coverage_summary,
    determine_regime_tag,
    determine_score_eligibility,
)


def test_determine_coverage_summary_distinguishes_fail_warn_and_pass():
    assert determine_coverage_summary(
        total_core_count=0,
        eligible_core_count=0,
        fail_core_count=0,
        minimum_core_horizons_for_scoring=5,
    ) == "FAIL"
    assert determine_coverage_summary(
        total_core_count=5,
        eligible_core_count=4,
        fail_core_count=0,
        minimum_core_horizons_for_scoring=5,
    ) == "FAIL"
    assert determine_coverage_summary(
        total_core_count=5,
        eligible_core_count=5,
        fail_core_count=1,
        minimum_core_horizons_for_scoring=5,
    ) == "WARN"
    assert determine_coverage_summary(
        total_core_count=5,
        eligible_core_count=4,
        fail_core_count=0,
        minimum_core_horizons_for_scoring=4,
    ) == "PASS"
    assert determine_coverage_summary(
        total_core_count=5,
        eligible_core_count=5,
        fail_core_count=0,
        minimum_core_horizons_for_scoring=5,
    ) == "PASS"


def test_determine_score_eligibility_returns_specific_blocking_reasons():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    assert determine_score_eligibility(
        core_delta=1.0,
        eligible_core_count=4,
        coverage_summary="PASS",
        scoring_config=scoring,
    ) == (False, "INSUFFICIENT_ELIGIBLE_HORIZONS")
    assert determine_score_eligibility(
        core_delta=None,
        eligible_core_count=5,
        coverage_summary="PASS",
        scoring_config=scoring,
    ) == (False, "MISSING_CORE_DELTA")
    assert determine_score_eligibility(
        core_delta=0.0,
        eligible_core_count=5,
        coverage_summary="PASS",
        scoring_config=scoring,
    ) == (False, "NON_POSITIVE_CORE_DELTA")
    assert determine_score_eligibility(
        core_delta=1.0,
        eligible_core_count=5,
        coverage_summary="WARN",
        scoring_config=scoring,
    ) == (False, "INCOMPLETE_CORE_COVERAGE")


def test_determine_score_eligibility_can_allow_warn_coverage_when_enabled():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring.model_copy(
        update={"allow_warn_coverage_for_scoring": True}
    )

    eligible, reason = determine_score_eligibility(
        core_delta=1.0,
        eligible_core_count=5,
        coverage_summary="WARN",
        scoring_config=scoring,
    )

    assert eligible is True
    assert reason == "OK"


def test_determine_regime_tag_covers_key_regime_branches():
    scoring = load_app_config(ProjectPaths.discover()).app.scoring

    assert determine_regime_tag(
        core_delta=None,
        delta_bucket=None,
        stability_score=None,
        gamma_proxy=None,
        scoring_config=scoring,
    ) == "INSUFFICIENT_DATA"
    assert determine_regime_tag(
        core_delta=-0.2,
        delta_bucket="LOW",
        stability_score=0.8,
        gamma_proxy=0.3,
        scoring_config=scoring,
    ) == "INVERSE"
    assert determine_regime_tag(
        core_delta=0.5,
        delta_bucket="LOW",
        stability_score=0.8,
        gamma_proxy=0.3,
        scoring_config=scoring,
    ) == "LOW_LINK"
    assert determine_regime_tag(
        core_delta=1.2,
        delta_bucket="MODERATE",
        stability_score=0.2,
        gamma_proxy=0.0,
        scoring_config=scoring,
    ) == "UNSTABLE"
    assert determine_regime_tag(
        core_delta=1.2,
        delta_bucket="MODERATE",
        stability_score=0.8,
        gamma_proxy=0.4,
        scoring_config=scoring,
    ) == "CONVEX_STABLE"
    assert determine_regime_tag(
        core_delta=1.2,
        delta_bucket="MODERATE",
        stability_score=0.5,
        gamma_proxy=0.4,
        scoring_config=scoring,
    ) == "CONVEX"
    assert determine_regime_tag(
        core_delta=1.2,
        delta_bucket="MODERATE",
        stability_score=0.5,
        gamma_proxy=-0.3,
        scoring_config=scoring,
    ) == "DECAYING"
    assert determine_regime_tag(
        core_delta=1.2,
        delta_bucket="MODERATE",
        stability_score=0.8,
        gamma_proxy=0.0,
        scoring_config=scoring,
    ) == "STABLE_BETA"
    assert determine_regime_tag(
        core_delta=1.2,
        delta_bucket="MODERATE",
        stability_score=0.5,
        gamma_proxy=0.0,
        scoring_config=scoring,
    ) == "BALANCED"
