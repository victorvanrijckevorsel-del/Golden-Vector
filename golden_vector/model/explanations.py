"""Plain-English structural Tool A explanations."""

from __future__ import annotations

from golden_vector.common.windows import window_label
from golden_vector.contracts.config_models import ScoringConfig


def build_delta_explanation(
    *,
    anchor_delta: float | None,
    anchor_window_id: str | None,
    structural_delta_core: float | None,
    score_eligible: bool,
    score_eligibility_reason: str,
    scoring_config: ScoringConfig,
) -> str:
    if score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
        return "Structural delta is withheld because trailing FX or return-basis issues block a trustworthy official read."
    if score_eligibility_reason == "LOW_LINKAGE_STRUCTURAL_SIGNAL":
        core_text = (
            f" (core = {structural_delta_core:.2f})"
            if structural_delta_core is not None
            else ""
        )
        return (
            f"Low structural delta{core_text} means the stock has not shown enough weekly gold linkage to earn an official rank."
        )
    if anchor_delta is None:
        return "Structural delta could not be estimated cleanly for the anchor window."
    window_text = (
        f" in the {window_label(anchor_window_id)} window"
        if anchor_window_id
        else ""
    )
    if anchor_delta <= 0:
        return (
            f"Negative structural delta means this stock has tended to move against gold on a weekly basis{window_text}."
        )
    if anchor_delta <= scoring_config.delta_bands.low_max:
        return (
            f"Low structural delta means the stock has moved with gold, but less strongly than higher-torque gold names{window_text}."
        )
    if anchor_delta >= scoring_config.delta_bands.high_min:
        return (
            f"High structural delta means this stock has tended to move more than gold on a weekly basis{window_text}."
        )
    if anchor_delta >= scoring_config.delta_bands.moderate_max:
        return (
            f"Moderately high structural delta means this stock has shown strong gold sensitivity{window_text} without being the most extreme torque name."
        )
    return (
        f"Moderate structural delta means the stock has shown a meaningful weekly link to gold{window_text}, but not exceptional torque."
    )


def build_gamma_explanation(
    *,
    gamma_core: float | None,
    up_beta_anchor: float | None,
    down_beta_anchor: float | None,
    anchor_window_id: str | None,
    score_eligible: bool,
    score_eligibility_reason: str,
    scoring_config: ScoringConfig,
) -> str:
    if score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
        return "Gamma is withheld because the official structural sample is blocked by normalization issues."
    if gamma_core is None or up_beta_anchor is None or down_beta_anchor is None:
        return "Gamma is unavailable because there were not enough clean up-gold and down-gold weeks to compare regime sensitivity."
    window_text = (
        f" in the {window_label(anchor_window_id)} window"
        if anchor_window_id
        else ""
    )
    if gamma_core >= scoring_config.gamma_thresholds.positive_min:
        return (
            f"Positive gamma means sensitivity has been stronger in down-gold weeks than in up-gold weeks{window_text}. That is a fragile regime profile, not clean upside convexity."
        )
    if gamma_core <= scoring_config.gamma_thresholds.negative_max:
        return (
            f"Negative gamma means sensitivity has been stronger in up-gold weeks than in down-gold weeks{window_text}. That points to better upside regime participation."
        )
    return (
        f"Near-flat gamma means the stock has behaved more like a linear gold exposure than a strongly regime-skewed one{window_text}."
    )


def build_asymmetry_explanation(
    *,
    asymmetry_ratio_anchor: float | None,
    up_beta_anchor: float | None,
    down_beta_anchor: float | None,
    score_eligibility_reason: str,
    scoring_config: ScoringConfig,
) -> str:
    if score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
        return "Asymmetry is withheld because the official structural sample is blocked by normalization issues."
    if up_beta_anchor is None or down_beta_anchor is None:
        return "Asymmetry is unavailable because the regime split is too thin."
    if up_beta_anchor > 0 and down_beta_anchor <= 0:
        return "Upside beta is positive while downside beta is flat or negative, which is the cleanest favorable asymmetry case."
    if down_beta_anchor > up_beta_anchor:
        return "Downside beta exceeds upside beta, which points to negative skew and a more fragile gold profile."
    if asymmetry_ratio_anchor is None:
        return "Asymmetry could not be summarized as a clean ratio, but the up-beta and down-beta still show how the stock behaves across gold regimes."
    if asymmetry_ratio_anchor >= scoring_config.asymmetry_thresholds.strong_min:
        return "High asymmetry means the stock has captured more upside gold sensitivity than downside gold sensitivity."
    if asymmetry_ratio_anchor <= scoring_config.asymmetry_thresholds.weak_max:
        return "Weak asymmetry means upside participation has lagged downside sensitivity."
    return "Balanced asymmetry means upside and downside gold participation have been fairly similar."


def build_volatility_explanation(
    *,
    volatility_context: str,
    residual_volatility_52w: float | None,
    downside_volatility_52w: float | None,
) -> str:
    if volatility_context == "LOW_NOISE":
        return "Low residual volatility means a relatively large share of annualized weekly log-return movement has been explained by gold rather than idiosyncratic noise."
    if volatility_context == "HIGH_NOISE":
        return "High residual volatility means a large share of annualized weekly log-return movement is not well explained by gold, so the exposure is noisy."
    if volatility_context == "HIGH_DOWNSIDE_RISK":
        return "High downside volatility means weekly drawdowns have been especially violent, which makes the exposure more fragile even when gold linkage is strong."
    residual_text = (
        "Residual volatility is moderate"
        if residual_volatility_52w is not None
        else "Residual volatility is unavailable"
    )
    downside_text = (
        "and downside risk is moderate."
        if downside_volatility_52w is not None
        else "and downside risk could not be estimated cleanly."
    )
    return f"{residual_text}, {downside_text}"


def build_confidence_explanation(
    *,
    confidence_label: str,
    confidence_score: float | None,
    score_eligibility_reason: str,
) -> str:
    if score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
        return "Confidence is withheld because trailing FX or return-basis issues block a trustworthy official structural read."
    if confidence_label == "HIGH":
        return "High confidence means the structural signal is supported by decent fit, enough weekly observations, and consistent window behaviour."
    if confidence_label == "MEDIUM":
        return "Medium confidence means the gold-linkage signal is usable, but it still shows fit, stability, or regime-split weakness."
    if confidence_score is None:
        return "Confidence is low because the structural signal could not be estimated with enough clean weekly evidence."
    return "Low confidence means the structural signal is noisy, thin, or inconsistent enough that the rank should be treated cautiously."


def build_interaction_explanation(
    *,
    score_eligible: bool,
    score_eligibility_reason: str,
    profile_label: str,
    structural_delta_core: float | None,
    structural_gamma_core: float | None,
    asymmetry_ratio_core: float | None,
    volatility_context: str,
    confidence_label: str,
    scoring_config: ScoringConfig,
) -> str:
    if score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
        return "Official Tool A score is withheld because trailing FX or return-basis issues make the structural signal untrustworthy."
    if score_eligibility_reason == "LOW_LINKAGE_STRUCTURAL_SIGNAL":
        return "This stock does not show enough structural gold linkage to earn an official Tool A rank."
    if confidence_label == "LOW":
        return "The stock may have interesting traits, but the structural signal is not reliable enough yet."
    if profile_label == "FRAGILE":
        return "This is a fragile gold exposure: meaningful delta, but down-gold sensitivity has been stronger than upside participation."
    if profile_label == "CONVEX":
        if volatility_context in {"HIGH_NOISE", "HIGH_DOWNSIDE_RISK"}:
            return "This is an upside-skewed gold exposure, but the volatility profile is noisy enough that the torque should be treated cautiously."
        return "This is an upside-skewed gold exposure: strong linkage, better up-gold participation than down-gold sensitivity, and manageable noise."
    if profile_label == "HIGH_DELTA":
        return "This is a high-delta gold exposure: strong weekly linkage, but less favorable regime skew than the best upside names."
    if profile_label == "LINEAR":
        return "This is a clean linear gold exposure: strong delta, fairly balanced regime behaviour, and low residual noise."
    if profile_label == "LOW_LINKAGE":
        return "This stock may still move with gold at times, but the structural linkage is too weak to treat it as a core Tool A name."
    if profile_label == "DEFENSIVE":
        return "This is a more defensive gold exposure: some linkage to gold, but less torque or less favorable regime behaviour than the stronger names."
    if profile_label == "SCORE_WITHHELD":
        return "Official Tool A score is withheld until the normalization issues in the trailing sample are resolved."
    if not score_eligible:
        return "This stock does not yet have enough clean structural evidence for an official Tool A rank."
    return "This stock has some gold linkage, but the delta, regime behaviour, and volatility mix is more balanced than specialized."


def build_summary_explanation(
    *,
    profile_label: str,
    confidence_label: str,
    score_eligibility_reason: str,
    interaction_explanation: str,
) -> str:
    if score_eligibility_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
        return f"Score withheld. {interaction_explanation}"
    profile_text = profile_label.replace("_", " ").title()
    return f"{profile_text}. Confidence is {confidence_label.lower()}. {interaction_explanation}"
