"""Deterministic Tool A labels and eligibility rules."""

from __future__ import annotations

from golden_vector.contracts.config_models import ScoringConfig


def determine_coverage_summary(
    *,
    total_core_count: int,
    eligible_core_count: int,
    fail_core_count: int,
    minimum_core_horizons_for_scoring: int,
) -> str:
    if total_core_count == 0 or eligible_core_count < minimum_core_horizons_for_scoring:
        return "FAIL"
    if fail_core_count > 0 or eligible_core_count < total_core_count:
        return "WARN"
    return "PASS"


def determine_score_eligibility(
    *,
    core_delta: float | None,
    eligible_core_count: int,
    coverage_summary: str,
    scoring_config: ScoringConfig,
) -> tuple[bool, str]:
    if eligible_core_count < scoring_config.minimum_core_horizons_for_scoring:
        return False, "INSUFFICIENT_ELIGIBLE_HORIZONS"
    if core_delta is None:
        return False, "MISSING_CORE_DELTA"
    if core_delta <= 0:
        return False, "NON_POSITIVE_CORE_DELTA"
    if (
        coverage_summary != "PASS"
        and not scoring_config.allow_warn_coverage_for_scoring
    ):
        return False, "INCOMPLETE_CORE_COVERAGE"
    return True, "OK"


def determine_regime_tag(
    *,
    core_delta: float | None,
    delta_bucket: str | None,
    stability_score: float | None,
    gamma_proxy: float | None,
    scoring_config: ScoringConfig,
) -> str:
    if core_delta is None:
        return "INSUFFICIENT_DATA"
    if core_delta <= 0:
        return "INVERSE"
    if delta_bucket == "LOW":
        return "LOW_LINK"

    weak_max = scoring_config.stability_thresholds.weak_max
    strong_min = scoring_config.stability_thresholds.strong_min
    negative_max = scoring_config.gamma_thresholds.negative_max
    positive_min = scoring_config.gamma_thresholds.positive_min

    if stability_score is not None and stability_score <= weak_max:
        return "UNSTABLE"
    if (
        gamma_proxy is not None
        and gamma_proxy >= positive_min
        and stability_score is not None
        and stability_score >= strong_min
    ):
        return "CONVEX_STABLE"
    if gamma_proxy is not None and gamma_proxy >= positive_min:
        return "CONVEX"
    if gamma_proxy is not None and gamma_proxy <= negative_max:
        return "DECAYING"
    if stability_score is not None and stability_score >= strong_min:
        return "STABLE_BETA"
    return "BALANCED"
