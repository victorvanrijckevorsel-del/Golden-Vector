import pytest
from pydantic import ValidationError

from golden_vector.contracts.config_models import (
    AsymmetryThresholds,
    BenchmarksConfig,
    CombinedVerdictThresholds,
    ConfidenceThresholds,
    GammaThresholds,
    HedgeReadinessConfig,
    HorizonsConfig,
    QaConfig,
    ScoreWeights,
    ScreeningParamsConfig,
    ScoringConfig,
    StructuralDeltaBands,
    StructuralWindowWeights,
    UniverseConfig,
    VolatilityDiagnosticBands,
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


def test_benchmarks_config_accepts_gdx_and_gdxj():
    config = BenchmarksConfig.model_validate(
        {
            "version": 1,
            "benchmarks": [
                {"ticker": "gdx", "yahoo_symbol": "gdx", "label": "GDX"},
                {"ticker": "gdxj", "yahoo_symbol": "gdxj", "label": "GDXJ"},
            ],
        }
    )

    assert [benchmark.ticker for benchmark in config.benchmarks] == ["GDX", "GDXJ"]
    assert [benchmark.yahoo_symbol for benchmark in config.benchmarks] == ["GDX", "GDXJ"]


def test_benchmarks_config_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        BenchmarksConfig.model_validate(
            {
                "version": 1,
                "benchmarks": [
                    {
                        "ticker": "GDX",
                        "yahoo_symbol": "GDX",
                        "is_benchmark": True,
                    }
                ],
            }
        )


def test_benchmarks_config_rejects_duplicate_tickers():
    with pytest.raises(ValidationError):
        BenchmarksConfig.model_validate(
            {
                "version": 1,
                "benchmarks": [
                    {"ticker": "GDX", "yahoo_symbol": "GDX"},
                    {"ticker": "gdx", "yahoo_symbol": "GDX"},
                ],
            }
        )


def test_hedge_readiness_config_accepts_defaults():
    config = HedgeReadinessConfig.model_validate(
        {
            "version": 1,
            "target_delta": -0.25,
            "target_horizons_days": [30, 60, 90],
            "optionability_open_interest_threshold": 1000,
            "implied_move_max_spread_pct": 0.35,
            "implied_move_min_open_interest": 1,
            "implied_move_min_volume": 0,
            "candidate_max_spread_pct": 0.35,
            "candidate_min_open_interest": 1,
            "candidate_min_volume": 0,
            "candidate_min_implied_volatility": 0.01,
            "candidate_max_implied_volatility": 3.0,
            "delta_gap_warning_threshold": 0.10,
            "hedge_ratio_cheap_max": 0.40,
            "hedge_ratio_expensive_min": 0.80,
            "proxy_max_beta_diff": 0.35,
            "proxy_low_basis_max_beta_diff": 0.10,
            "proxy_medium_basis_max_beta_diff": 0.30,
            "proxy_low_basis_min_confidence": 0.70,
            "proxy_top_n": 3,
            "benchmark_tickers": ["gdx", "gdxj"],
            "gold_down_scenarios": [0.05, 0.10, 0.20],
            "default_scenario_quantity": 5,
            "default_scenarios": [0.0, -0.05, -0.10, -0.15, -0.20],
            "protection_levels": [0.5, 1.0],
            "optionability_tier_min": "directly_hedgeable",
            "speculation_max_tickers_default": 15,
            "ranking_max_tickers_default": 60,
            "down_beta_min_for_scenario": 0.10,
            "max_tickers_speculation_section": 15,
        }
    )

    assert config.target_delta == -0.25
    assert config.target_horizons_days == [30, 60, 90]
    assert config.benchmark_tickers == ["GDX", "GDXJ"]
    assert config.candidate_max_spread_pct == 0.35
    assert config.candidate_min_open_interest == 1
    assert config.candidate_min_volume == 0
    assert config.candidate_min_implied_volatility == 0.01
    assert config.candidate_max_implied_volatility == 3.0
    assert config.proxy_low_basis_max_beta_diff == 0.10
    assert config.proxy_medium_basis_max_beta_diff == 0.30
    assert config.proxy_low_basis_min_confidence == 0.70
    assert config.default_scenario_quantity == 5
    assert config.default_scenarios == [0.0, -0.05, -0.10, -0.15, -0.20]
    assert config.protection_levels == [0.5, 1.0]
    assert config.optionability_tier_min == "directly_hedgeable"
    assert config.speculation_max_tickers_default == 15
    assert config.ranking_max_tickers_default == 60
    assert config.down_beta_min_for_scenario == 0.10
    assert config.max_tickers_speculation_section == 15


@pytest.mark.parametrize(
    "override",
    [
        {"target_delta": 0.25},
        {"target_horizons_days": [30, 30]},
        {"hedge_ratio_cheap_max": 1.0, "hedge_ratio_expensive_min": 0.8},
        {"gold_down_scenarios": [0.10, 1.20]},
        {"benchmark_tickers": ["GDX", "gdx"]},
        {"proxy_top_n": 0},
        {"proxy_low_basis_max_beta_diff": 0},
        {"proxy_medium_basis_max_beta_diff": 0},
        {"proxy_low_basis_min_confidence": -0.01},
        {"proxy_low_basis_min_confidence": 1.01},
        {"proxy_low_basis_max_beta_diff": 0.30, "proxy_medium_basis_max_beta_diff": 0.10},
        {"proxy_medium_basis_max_beta_diff": 0.40},
        {"candidate_max_spread_pct": 0},
        {"candidate_min_open_interest": -1},
        {"candidate_min_volume": -1},
        {"candidate_min_implied_volatility": 0.0},
        {"candidate_max_implied_volatility": 0.0},
        {"candidate_min_implied_volatility": 0.5, "candidate_max_implied_volatility": 0.5},
        {"default_scenario_quantity": 0},
        {"default_scenarios": [0.0, -0.05, -0.05]},
        {"default_scenarios": [0.05, -0.05]},
        {"default_scenarios": [-1.0, -0.05]},
        {"protection_levels": [0.5, 0.5]},
        {"protection_levels": [0.0, 0.5]},
        {"protection_levels": [1.20]},
        {"optionability_tier_min": "none"},
        {"speculation_max_tickers_default": 0},
        {"ranking_max_tickers_default": 0},
        {"down_beta_min_for_scenario": 0},
        {"max_tickers_speculation_section": 0},
    ],
)
def test_hedge_readiness_config_rejects_invalid_thresholds(override):
    payload = {
        "version": 1,
        "target_delta": -0.25,
        "target_horizons_days": [30, 60, 90],
        "optionability_open_interest_threshold": 1000,
        "implied_move_max_spread_pct": 0.35,
        "implied_move_min_open_interest": 1,
        "implied_move_min_volume": 0,
        "candidate_max_spread_pct": 0.35,
        "candidate_min_open_interest": 1,
        "candidate_min_volume": 0,
        "candidate_min_implied_volatility": 0.01,
        "candidate_max_implied_volatility": 3.0,
        "delta_gap_warning_threshold": 0.10,
        "hedge_ratio_cheap_max": 0.40,
        "hedge_ratio_expensive_min": 0.80,
        "proxy_max_beta_diff": 0.35,
        "proxy_low_basis_max_beta_diff": 0.10,
        "proxy_medium_basis_max_beta_diff": 0.30,
        "proxy_low_basis_min_confidence": 0.70,
        "proxy_top_n": 3,
        "benchmark_tickers": ["GDX", "GDXJ"],
        "gold_down_scenarios": [0.05, 0.10, 0.20],
        "default_scenario_quantity": 5,
        "default_scenarios": [0.0, -0.05, -0.10, -0.15, -0.20],
        "protection_levels": [0.5, 1.0],
        "optionability_tier_min": "directly_hedgeable",
        "speculation_max_tickers_default": 15,
        "ranking_max_tickers_default": 60,
        "down_beta_min_for_scenario": 0.10,
        "max_tickers_speculation_section": 15,
    }
    payload.update(override)

    with pytest.raises(ValidationError):
        HedgeReadinessConfig.model_validate(payload)


def test_score_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        ScoreWeights.model_validate(
            {
                "structural_delta": 0.6,
                "structural_gamma": 0.3,
                "asymmetry": 0.3,
                "confidence": 0.1,
            }
        )


def test_structural_delta_bands_must_be_ordered():
    with pytest.raises(ValidationError):
        StructuralDeltaBands.model_validate(
            {
                "low_max": 1.0,
                "moderate_max": 0.9,
                "high_min": 2.0,
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


def test_asymmetry_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        AsymmetryThresholds.model_validate(
            {
                "weak_max": 1.2,
                "strong_min": 1.1,
            }
        )


def test_confidence_thresholds_must_be_ordered():
    with pytest.raises(ValidationError):
        ConfidenceThresholds.model_validate(
            {
                "low_max": 0.8,
                "high_min": 0.7,
            }
        )


def test_volatility_bands_must_be_ordered():
    with pytest.raises(ValidationError):
        VolatilityDiagnosticBands.model_validate(
            {
                "low_residual_volatility_max": 0.7,
                "high_residual_volatility_min": 0.6,
                "high_downside_volatility_min": 0.5,
                "high_total_volatility_min": 0.75,
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


def test_qa_config_rejects_negative_fx_staleness_threshold():
    with pytest.raises(ValidationError):
        QaConfig.model_validate({"max_fx_staleness_days": -1})


def test_structural_window_weights_require_exact_window_set():
    with pytest.raises(ValidationError):
        StructuralWindowWeights.model_validate({"windows": {"6M": 1.0, "12M": 1.0}})


def test_scoring_config_rejects_unsupported_blocked_normalization_status():
    with pytest.raises(ValidationError):
        ScoringConfig.model_validate(
            {
                "blocked_normalization_statuses": ["UNKNOWN_STATUS"],
            }
        )
