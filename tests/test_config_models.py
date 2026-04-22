import pytest
from pydantic import ValidationError

from golden_vector.contracts.config_models import (
    CombinedVerdictThresholds,
    GammaThresholds,
    HorizonsConfig,
    ScoreWeights,
    ScreeningParamsConfig,
    StabilityThresholds,
    UniverseConfig,
)


def test_universe_config_requires_at_least_one_ticker():
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate({"version": 1, "tickers": []})


def test_horizons_config_rejects_empty_core_horizons():
    with pytest.raises(ValidationError):
        HorizonsConfig.model_validate(
            {
                "version": 1,
                "core_horizons": [],
                "custom_validation": {
                    "allowed_units": ["D", "M", "Y"],
                    "min_value": 1,
                    "max_value": 120,
                },
            }
        )


def test_horizons_config_rejects_invalid_horizon_format():
    with pytest.raises(ValidationError):
        HorizonsConfig.model_validate(
            {
                "version": 1,
                "core_horizons": ["5D", "banana"],
                "custom_validation": {
                    "allowed_units": ["D", "M", "Y"],
                    "min_value": 1,
                    "max_value": 120,
                },
            }
        )


def test_screening_params_require_all_peer_benchmark_buckets():
    with pytest.raises(ValidationError):
        ScreeningParamsConfig.model_validate(
            {
                "version": 1,
                "gold_price_scenarios": [3000, 4000],
                "layer1_thresholds": {
                    "aisc_max": 1850,
                    "margin_min": 0.5,
                    "fcf_yield_min": 0.15,
                    "reserve_life_min": 6,
                    "leverage_max": 2.5,
                },
                "verdict_thresholds": {
                    "strong_candidate_forward_pe_max": 8,
                    "watchlist_forward_pe_max": 10,
                },
                "jurisdiction_discounts": {
                    "tier_1": 0.0,
                    "tier_2": 0.15,
                    "tier_3": 0.3,
                },
                "peer_benchmarks": {
                    "large": {
                        "pe_2026": 16,
                        "pe_2011_peak": 28.5,
                        "evebitda_2026": 8,
                        "evebitda_2011": 14,
                        "fcf_yield_2026": 0.05,
                        "fcf_yield_2011": 0.02,
                    }
                },
            }
        )


def test_universe_config_rejects_duplicate_tickers():
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate(
            {
                "version": 1,
                "tickers": [
                    {
                        "ticker": "NEM",
                        "currency": "USD",
                    },
                    {
                        "ticker": "NEM",
                        "currency": "USD",
                    },
                ],
            }
        )


def test_universe_config_rejects_invalid_jurisdiction_tier():
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate(
            {
                "version": 1,
                "tickers": [
                    {
                        "ticker": "NEM",
                        "currency": "USD",
                        "jurisdiction_tier": 5,
                    }
                ],
            }
        )


def test_universe_config_requires_currency():
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate(
            {
                "version": 1,
                "tickers": [
                    {
                        "ticker": "NEM",
                    }
                ],
            }
        )


def test_universe_config_rejects_unknown_currency():
    with pytest.raises(ValidationError):
        UniverseConfig.model_validate(
            {
                "version": 1,
                "tickers": [
                    {
                        "ticker": "NEM",
                        "currency": "UDS",
                    }
                ],
            }
        )


def test_screening_params_reject_unknown_keys():
    with pytest.raises(ValidationError):
        ScreeningParamsConfig.model_validate(
            {
                "version": 1,
                "gold_price_scenarios": [3000, 4000],
                "unknown_field": True,
                "layer1_thresholds": {
                    "aisc_max": 1850,
                    "margin_min": 0.5,
                    "fcf_yield_min": 0.15,
                    "reserve_life_min": 6,
                    "leverage_max": 2.5,
                },
                "verdict_thresholds": {
                    "strong_candidate_forward_pe_max": 8,
                    "watchlist_forward_pe_max": 10,
                },
                "jurisdiction_discounts": {
                    "tier_1": 0.0,
                    "tier_2": 0.15,
                    "tier_3": 0.3,
                },
                "peer_benchmarks": {
                    "large": {
                        "pe_2026": 16,
                        "pe_2011_peak": 28.5,
                        "evebitda_2026": 8,
                        "evebitda_2011": 14,
                        "fcf_yield_2026": 0.05,
                        "fcf_yield_2011": 0.02,
                    },
                    "mid": {
                        "pe_2026": 13,
                        "pe_2011_peak": 23,
                        "evebitda_2026": 6.5,
                        "evebitda_2011": 12,
                        "fcf_yield_2026": 0.075,
                        "fcf_yield_2011": 0.035,
                    },
                    "small": {
                        "pe_2026": 11.5,
                        "pe_2011_peak": 20,
                        "evebitda_2026": 5.5,
                        "evebitda_2011": 10,
                        "fcf_yield_2026": 0.1,
                        "fcf_yield_2011": 0.045,
                    },
                    "micro": {
                        "pe_2026": 10,
                        "pe_2011_peak": 18,
                        "evebitda_2026": 4.5,
                        "evebitda_2011": 9,
                        "fcf_yield_2026": 0.12,
                        "fcf_yield_2011": 0.05,
                    },
                },
            }
        )


@pytest.mark.parametrize("gold_price_scenarios", [[-100], [0], [3000, 3000]])
def test_screening_params_reject_invalid_gold_price_scenarios(gold_price_scenarios):
    with pytest.raises(ValidationError):
        ScreeningParamsConfig.model_validate(
            {
                "version": 1,
                "gold_price_scenarios": gold_price_scenarios,
                "layer1_thresholds": {
                    "aisc_max": 1850,
                    "margin_min": 0.5,
                    "fcf_yield_min": 0.15,
                    "reserve_life_min": 6,
                    "leverage_max": 2.5,
                },
                "verdict_thresholds": {
                    "strong_candidate_forward_pe_max": 8,
                    "watchlist_forward_pe_max": 10,
                },
                "jurisdiction_discounts": {
                    "tier_1": 0.0,
                    "tier_2": 0.15,
                    "tier_3": 0.3,
                },
                "peer_benchmarks": {
                    "large": {
                        "pe_2026": 16,
                        "pe_2011_peak": 28.5,
                        "evebitda_2026": 8,
                        "evebitda_2011": 14,
                        "fcf_yield_2026": 0.05,
                        "fcf_yield_2011": 0.02,
                    },
                    "mid": {
                        "pe_2026": 13,
                        "pe_2011_peak": 23,
                        "evebitda_2026": 6.5,
                        "evebitda_2011": 12,
                        "fcf_yield_2026": 0.075,
                        "fcf_yield_2011": 0.035,
                    },
                    "small": {
                        "pe_2026": 11.5,
                        "pe_2011_peak": 20,
                        "evebitda_2026": 5.5,
                        "evebitda_2011": 10,
                        "fcf_yield_2026": 0.1,
                        "fcf_yield_2011": 0.045,
                    },
                    "micro": {
                        "pe_2026": 10,
                        "pe_2011_peak": 18,
                        "evebitda_2026": 4.5,
                        "evebitda_2011": 9,
                        "fcf_yield_2026": 0.12,
                        "fcf_yield_2011": 0.05,
                    },
                },
            }
        )


def test_score_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        ScoreWeights.model_validate(
            {
                "core_delta": 0.6,
                "stability": 0.3,
                "gamma_proxy": 0.3,
            }
        )


def test_stability_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        StabilityThresholds.model_validate(
            {
                "weak_max": 0.7,
                "strong_min": 0.6,
            }
        )


def test_gamma_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        GammaThresholds.model_validate(
            {
                "negative_max": 0.2,
                "positive_min": 0.1,
            }
        )


def test_combined_verdict_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        CombinedVerdictThresholds.model_validate(
            {
                "high_conviction_min_tool_a_score": 55.0,
                "dual_pass_min_tool_a_score": 60.0,
            }
        )
