"""Deterministic structural Tool A labels and eligibility rules."""

from __future__ import annotations

from golden_vector.contracts.config_models import ScoringConfig


WITHHELD_SCORE_REASONS = {"UNACCEPTABLE_NORMALIZATION_STATUS"}


def determine_confidence_label(
    *,
    confidence_score: float | None,
    scoring_config: ScoringConfig,
    score_eligible: bool | None = None,
    score_eligibility_reason: str | None = None,
) -> str:
    if score_eligibility_reason in WITHHELD_SCORE_REASONS:
        return "WITHHELD"
    if confidence_score is None:
        return "LOW"
    if confidence_score >= scoring_config.confidence_thresholds.high_min:
        return "HIGH"
    if confidence_score > scoring_config.confidence_thresholds.low_max:
        return "MEDIUM"
    return "LOW"


def determine_volatility_context(
    *,
    total_volatility_52w: float | None,
    residual_volatility_52w: float | None,
    downside_volatility_52w: float | None,
    scoring_config: ScoringConfig,
) -> str:
    bands = scoring_config.volatility_bands
    if (
        downside_volatility_52w is not None
        and downside_volatility_52w >= bands.high_downside_volatility_min
    ):
        return "HIGH_DOWNSIDE_RISK"
    if (
        residual_volatility_52w is not None
        and residual_volatility_52w >= bands.high_residual_volatility_min
    ):
        return "HIGH_NOISE"
    if (
        total_volatility_52w is not None
        and total_volatility_52w >= bands.high_total_volatility_min
    ):
        return "HIGH_NOISE"
    if (
        residual_volatility_52w is not None
        and residual_volatility_52w <= bands.low_residual_volatility_max
    ):
        return "LOW_NOISE"
    return "MODERATE_NOISE"


def determine_score_eligibility(
    *,
    structural_delta_core: float | None,
    eligible_structural_window_count: int,
    confidence_score: float | None,
    normalization_issue_summary: str | None,
    scoring_config: ScoringConfig,
) -> tuple[bool, str]:
    blocked_statuses = {
        status.strip().upper()
        for status in str(normalization_issue_summary or "").split(",")
        if status.strip()
    }
    if blocked_statuses.intersection(scoring_config.blocked_normalization_status_set()):
        return False, "UNACCEPTABLE_NORMALIZATION_STATUS"
    if eligible_structural_window_count < 2:
        return False, "INSUFFICIENT_ELIGIBLE_STRUCTURAL_WINDOWS"
    if structural_delta_core is None:
        return False, "MISSING_STRUCTURAL_DELTA"
    if structural_delta_core <= 0:
        return False, "NON_POSITIVE_STRUCTURAL_DELTA"
    if structural_delta_core < scoring_config.minimum_rankable_structural_delta:
        return False, "LOW_LINKAGE_STRUCTURAL_SIGNAL"
    if confidence_score is None:
        return False, "MISSING_CONFIDENCE"
    if confidence_score < scoring_config.confidence_thresholds.minimum_rankable:
        return False, "LOW_CONFIDENCE_STRUCTURAL_SIGNAL"
    return True, "OK"


def determine_profile_label(
    *,
    score_eligible: bool,
    score_eligibility_reason: str,
    structural_delta_core: float | None,
    structural_gamma_core: float | None,
    asymmetry_ratio_core: float | None,
    up_beta_core: float | None,
    down_beta_core: float | None,
    confidence_label: str,
    residual_volatility_52w: float | None,
    volatility_context: str,
    scoring_config: ScoringConfig,
) -> str:
    if score_eligibility_reason in WITHHELD_SCORE_REASONS:
        return "SCORE_WITHHELD"
    if structural_delta_core is None:
        return "UNRELIABLE_SIGNAL"
    if (
        confidence_label == "LOW"
        and not score_eligible
        and score_eligibility_reason != "LOW_LINKAGE_STRUCTURAL_SIGNAL"
    ):
        return "UNRELIABLE_SIGNAL"
    if structural_delta_core < scoring_config.minimum_rankable_structural_delta:
        return "LOW_LINKAGE"
    if (
        up_beta_core is not None
        and down_beta_core is not None
        and down_beta_core > up_beta_core
        and structural_delta_core > scoring_config.delta_bands.low_max
    ):
        return "FRAGILE"
    if (
        structural_gamma_core is not None
        and structural_gamma_core <= scoring_config.gamma_thresholds.negative_max
        and asymmetry_ratio_core is not None
        and asymmetry_ratio_core >= scoring_config.asymmetry_thresholds.strong_min
        and structural_delta_core >= scoring_config.delta_bands.moderate_max
    ):
        return "CONVEX"
    if structural_delta_core >= scoring_config.delta_bands.high_min:
        return "HIGH_DELTA"
    if volatility_context == "LOW_NOISE" and (
        residual_volatility_52w is None
        or residual_volatility_52w < scoring_config.volatility_bands.high_residual_volatility_min
    ):
        return "LINEAR"
    return "DEFENSIVE"
