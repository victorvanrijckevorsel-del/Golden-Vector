import pytest
from pydantic import ValidationError

from golden_vector.common.windows import (
    ALL_WINDOWS,
    DISPLAY_WINDOWS,
    SCORING_WINDOWS,
    window_suffix,
)
from golden_vector.contracts.config_models import (
    GOLD_BUCKET_NAMES,
    AsymmetryThresholds,
    BenchmarksConfig,
    CandidateFinderConfig,
    ConfidenceThresholds,
    FundamentalsConfig,
    GammaThresholds,
    GoldProfileConfig,
    HedgeReadinessConfig,
    HorizonsConfig,
    MarketDataConfig,
    QaConfig,
    ScoreWeights,
    ScreeningParamsConfig,
    ScoringConfig,
    StructuralDeltaBands,
    StructuralWindowWeights,
    ToolCConfig,
    ToolDConfig,
    UniverseConfig,
    VolatilityDiagnosticBands,
)
from golden_vector.model.gold_shock import DEFAULT_GOLD_DOWN_MIN_BETA


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


def test_screening_params_reject_duplicate_gold_price_scenarios():
    with pytest.raises(ValidationError):
        ScreeningParamsConfig.model_validate(
            {
                "version": 1,
                "gold_price_scenarios": [4000, 4000],
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
            "version": 2,
            "target_delta": -0.25,
            "target_horizons_days": [30, 60, 90, 120],
            "display_horizons_days": [30, 60, 90, 120],
            "option_signal_horizon_days": 90,
            "optionability_core_horizons": [60, 90],
            "optionability_open_interest_threshold": 1000,
            "implied_move_max_spread_pct": 0.35,
            "implied_move_min_open_interest": 1,
            "implied_move_min_volume": 0,
            "candidate_max_spread_pct": 0.35,
            "candidate_min_open_interest": 1,
            "candidate_min_volume": 0,
            "candidate_min_implied_volatility": 0.01,
            "candidate_max_implied_volatility": 10.0,
            "option_liquidity_tradable_spread_pct": 0.20,
            "option_liquidity_watch_spread_pct": 0.50,
            "option_liquidity_min_open_interest": 1,
            "option_liquidity_min_premium": 0.15,
            "option_liquidity_near_spot_pct": 0.10,
            "option_liquidity_target_depth_count": 10,
            "option_liquidity_oi_cap": 1000,
            "option_liquidity_volume_cap": 1000,
            "option_sensible_moneyness_max_pct": 0.35,
            "option_near_atm_otm_min": 0.0,
            "option_near_atm_otm_max": 0.05,
            "option_directional_preferred_otm_min": 0.15,
            "option_directional_preferred_otm_max": 0.20,
            "option_directional_allowed_otm_min": 0.12,
            "option_directional_allowed_otm_max": 0.22,
            "option_near_atm_strict_max_spread_pct": 0.25,
            "option_near_atm_strict_min_open_interest": 100,
            "option_near_atm_strict_min_mid": 0.20,
            "option_near_atm_watch_max_spread_pct": 0.35,
            "option_near_atm_watch_min_open_interest": 50,
            "option_near_atm_watch_min_mid": 0.15,
            "option_directional_strict_max_spread_pct": 0.35,
            "option_directional_strict_min_open_interest": 50,
            "option_directional_strict_min_mid": 0.10,
            "option_directional_watch_max_spread_pct": 0.45,
            "option_directional_watch_min_open_interest": 25,
            "option_directional_watch_min_mid": 0.05,
            "option_extreme_implied_volatility_threshold": 3.0,
            "option_lottery_implied_volatility_threshold": 0.75,
            "option_lottery_abs_delta_max": 0.15,
            "option_lottery_dte_max": 75,
            "option_verdict_model_over_market_ratio": 1.5,
            "option_verdict_market_over_model_ratio": 0.67,
            "option_dte_bands": {
                30: [21, 45],
                60: [46, 75],
                90: [76, 105],
                120: [106, 150],
            },
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
        }
    )

    assert config.version == 2
    assert config.target_delta == -0.25
    assert config.target_horizons_days == [30, 60, 90, 120]
    assert config.display_horizons_days == [30, 60, 90, 120]
    assert config.benchmark_tickers == ["GDX", "GDXJ"]
    assert config.candidate_max_spread_pct == 0.35
    assert config.candidate_min_open_interest == 1
    assert config.candidate_min_volume == 0
    assert config.candidate_min_implied_volatility == 0.01
    assert config.candidate_max_implied_volatility == 10.0
    assert config.option_liquidity_tradable_spread_pct == 0.20
    assert config.option_liquidity_watch_spread_pct == 0.50
    assert config.option_liquidity_min_open_interest == 1
    assert config.option_liquidity_min_premium == 0.15
    assert config.option_liquidity_near_spot_pct == 0.10
    assert config.option_liquidity_target_depth_count == 10
    assert config.option_liquidity_oi_cap == 1000
    assert config.option_liquidity_volume_cap == 1000
    assert config.option_sensible_moneyness_max_pct == 0.35
    assert config.option_near_atm_otm_min == 0.0
    assert config.option_near_atm_otm_max == 0.05
    assert config.option_directional_preferred_otm_min == 0.15
    assert config.option_directional_preferred_otm_max == 0.20
    assert config.option_directional_allowed_otm_min == 0.12
    assert config.option_directional_allowed_otm_max == 0.22
    assert config.option_near_atm_strict_min_open_interest == 100
    assert config.option_near_atm_watch_min_open_interest == 50
    assert config.option_directional_strict_min_open_interest == 50
    assert config.option_directional_watch_min_open_interest == 25
    assert config.option_extreme_implied_volatility_threshold == 3.0
    assert config.option_lottery_implied_volatility_threshold == 0.75
    assert config.option_lottery_abs_delta_max == 0.15
    assert config.option_lottery_dte_max == 75
    assert config.option_verdict_model_over_market_ratio == 1.5
    assert config.option_verdict_market_over_model_ratio == 0.67
    assert config.option_dte_bands == {
        30: [21, 45],
        60: [46, 75],
        90: [76, 105],
        120: [106, 150],
    }
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
    assert config.down_beta_min_for_scenario == DEFAULT_GOLD_DOWN_MIN_BETA


@pytest.mark.parametrize(
    "override",
    [
        {"target_delta": 0.25},
        {"target_horizons_days": [30, 30]},
        {"display_horizons_days": [30, 30]},
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
        {
            "candidate_max_implied_volatility": 2.0,
            "option_extreme_implied_volatility_threshold": 3.0,
        },
        {
            "option_lottery_implied_volatility_threshold": 3.5,
            "option_extreme_implied_volatility_threshold": 3.0,
        },
        {"option_liquidity_tradable_spread_pct": 0},
        {"option_liquidity_watch_spread_pct": 0},
        {"option_liquidity_tradable_spread_pct": 0.50, "option_liquidity_watch_spread_pct": 0.20},
        {"option_liquidity_min_open_interest": -1},
        {"option_liquidity_min_premium": 0},
        {"option_liquidity_near_spot_pct": 0},
        {"option_liquidity_target_depth_count": 0},
        {"option_liquidity_oi_cap": 0},
        {"option_liquidity_volume_cap": 0},
        {"option_sensible_moneyness_max_pct": 0},
        {"option_near_atm_otm_min": -0.01},
        {"option_near_atm_otm_min": 0.05, "option_near_atm_otm_max": 0.05},
        {
            "option_directional_allowed_otm_min": 0.20,
            "option_directional_preferred_otm_min": 0.15,
        },
        {
            "option_near_atm_strict_max_spread_pct": 0.40,
            "option_near_atm_watch_max_spread_pct": 0.35,
        },
        {
            "option_directional_strict_max_spread_pct": 0.50,
            "option_directional_watch_max_spread_pct": 0.45,
        },
        {"option_lottery_abs_delta_max": 1.2},
        {"option_lottery_dte_max": 0},
        {"option_verdict_model_over_market_ratio": 1.0},
        {"option_verdict_market_over_model_ratio": 1.0},
        {
            "option_verdict_model_over_market_ratio": 0.9,
            "option_verdict_market_over_model_ratio": 0.8,
        },
        {"option_dte_bands": {30: [45, 21]}},
        {"option_dte_bands": {30: [21]}},
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
    ],
)
def test_hedge_readiness_config_rejects_invalid_thresholds(override):
    payload = {
        "version": 2,
        "target_delta": -0.25,
        "target_horizons_days": [30, 60, 90],
        "display_horizons_days": [30, 60, 90, 120],
        "optionability_open_interest_threshold": 1000,
        "implied_move_max_spread_pct": 0.35,
        "implied_move_min_open_interest": 1,
        "implied_move_min_volume": 0,
        "candidate_max_spread_pct": 0.35,
        "candidate_min_open_interest": 1,
        "candidate_min_volume": 0,
        "candidate_min_implied_volatility": 0.01,
        "candidate_max_implied_volatility": 10.0,
        "option_liquidity_tradable_spread_pct": 0.20,
        "option_liquidity_watch_spread_pct": 0.50,
        "option_liquidity_min_open_interest": 1,
        "option_liquidity_min_premium": 0.15,
        "option_liquidity_near_spot_pct": 0.10,
        "option_liquidity_target_depth_count": 10,
        "option_liquidity_oi_cap": 1000,
        "option_liquidity_volume_cap": 1000,
        "option_sensible_moneyness_max_pct": 0.35,
        "option_dte_bands": {
            30: [21, 45],
            60: [46, 75],
            90: [76, 105],
            120: [106, 150],
        },
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
    }
    payload.update(override)

    with pytest.raises(ValidationError):
        HedgeReadinessConfig.model_validate(payload)


def test_tool_c_config_accepts_defaults():
    config = ToolCConfig()

    assert config.min_events == 8
    assert config.regime_rolling_weeks == 156
    assert config.regime_min_weeks == 52
    assert config.downside_hit_rate_threshold_pct == -10.0
    assert config.downside_hit_rate_threshold == -0.10
    assert config.upside_hit_rate_threshold_pct == 10.0
    assert config.upside_hit_rate_threshold == 0.10


@pytest.mark.parametrize(
    "override",
    [
        {"min_events": 0},
        {"regime_rolling_weeks": 0},
        {"regime_min_weeks": 0},
        {"regime_rolling_weeks": 51, "regime_min_weeks": 52},
        {"downside_hit_rate_threshold_pct": 0},
        {"upside_hit_rate_threshold_pct": 0},
    ],
)
def test_tool_c_config_rejects_invalid_settings(override):
    with pytest.raises(ValidationError):
        ToolCConfig.model_validate({"version": 1, **override})


def test_gold_profile_config_accepts_defaults():
    config = GoldProfileConfig()

    assert config.tilt_threshold == 0.10
    assert config.min_usable_down_buckets == 1
    assert config.min_usable_up_buckets == 1
    assert config.down_buckets == ["gold_down_big", "gold_down"]
    assert config.up_buckets == ["gold_up", "gold_up_big"]
    assert config.default_profile_horizon == 13


@pytest.mark.parametrize(
    "override",
    [
        {"tilt_threshold": 0.0},
        {"tilt_threshold": -0.1},
        {"tilt_threshold": 1.5},
        {"min_usable_down_buckets": 0},
        {"min_usable_up_buckets": 0},
        {"default_profile_horizon": 0},
        {"default_profile_horizon": -1},
        {"down_buckets": []},
        {"up_buckets": ["gold_up", "gold_up"]},  # repeated
        {"down_buckets": ["gold_down"], "up_buckets": ["gold_down"]},  # not disjoint
        {"down_buckets": ["gold_dwon_big", "gold_down"]},  # typo'd bucket name
        {"up_buckets": ["not_a_bucket"]},  # unknown bucket name
    ],
)
def test_gold_profile_config_rejects_invalid_settings(override):
    with pytest.raises(ValidationError):
        GoldProfileConfig.model_validate(override)


def test_gold_profile_bucket_names_match_the_lab_canonical_set():
    """Pin the contracts-layer GOLD_BUCKET_NAMES equal to the lab's canonical
    bucket labels so the membership validator can never silently drift from the
    real buckets."""
    from golden_vector.lab.conditional_dial import BUCKET_LABELS

    assert GOLD_BUCKET_NAMES == frozenset(BUCKET_LABELS)


def test_tool_d_config_accepts_defaults():
    config = ToolDConfig()

    assert config.max_reasonable_ev_ebitda == 100.0
    assert config.debt_stress_leverage_danger_threshold == 3.0
    assert config.quality_components == {
        "survival_distance_to_interest_cover_pct": "high_good",
        "cost_curve_aisc_percentile": "low_good",
        "fragility_ebitda_pct_per_10pct_gold": "low_good",
        "leverage_stressed_at_g": "low_good",
    }


@pytest.mark.parametrize(
    "override",
    [
        {"max_reasonable_ev_ebitda": 0},
        {"debt_stress_leverage_danger_threshold": 0},
        {
            "quality_components": {
                "survival_distance_to_interest_cover_pct": "high_good",
                "leverage_stressed_at_g": "low_good",
            }
        },
    ],
)
def test_tool_d_config_rejects_invalid_settings(override):
    with pytest.raises(ValidationError):
        ToolDConfig.model_validate({"version": 1, **override})


def test_market_data_config_accepts_yahoo_retry_and_throttle_defaults():
    config = MarketDataConfig()

    assert config.yahoo_max_attempts == 3
    assert config.yahoo_initial_backoff_seconds == 0.5
    assert config.yahoo_backoff_multiplier == 2.0
    assert config.yahoo_throttle_seconds == 0.15
    assert config.yahoo_backoff_jitter_seconds == 0.1
    assert config.yahoo_max_workers == 4


@pytest.mark.parametrize(
    "override",
    [
        {"yahoo_max_attempts": 0},
        {"yahoo_initial_backoff_seconds": -0.1},
        {"yahoo_backoff_multiplier": 0.9},
        {"yahoo_throttle_seconds": -0.1},
        {"yahoo_backoff_jitter_seconds": -0.1},
        {"yahoo_max_workers": 0},
    ],
)
def test_market_data_config_rejects_invalid_yahoo_retry_settings(override):
    with pytest.raises(ValidationError):
        MarketDataConfig.model_validate({"version": 1, **override})


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


def test_scoring_config_default_display_windows_are_disjoint_from_scoring():
    # The shipped default (2Y/5Y display, 6M/12M/3Y scoring) must validate.
    config = ScoringConfig()
    assert config.structural_display_windows == ["2Y", "5Y"]
    assert not (
        set(config.structural_windows) & set(config.structural_display_windows)
    )


def test_scoring_config_rejects_display_window_overlapping_a_scoring_window():
    # A scoring window listed as display would emit a duplicate structural row and
    # inflate eligible_structural_window_count / positive_delta_window_count — a
    # silent rank corruption. Must fail loud at config validation.
    with pytest.raises(ValidationError, match="disjoint"):
        ScoringConfig.model_validate(
            {
                "structural_display_windows": ["6M", "2Y"],
            }
        )


def test_scoring_config_rejects_unknown_display_window():
    with pytest.raises(ValidationError, match="within"):
        ScoringConfig.model_validate({"structural_display_windows": ["7Y"]})


def test_scoring_config_window_defaults_follow_registry():
    config = ScoringConfig()
    assert tuple(config.structural_windows) == SCORING_WINDOWS
    assert tuple(config.structural_display_windows) == DISPLAY_WINDOWS
    assert set(config.structural_windows) | set(config.structural_display_windows) == set(ALL_WINDOWS)
    assert StructuralWindowWeights().windows == {window: 1.0 for window in SCORING_WINDOWS}


def test_scoring_config_rejects_duplicate_display_window():
    with pytest.raises(ValidationError, match="duplicate"):
        ScoringConfig.model_validate({"structural_display_windows": ["2Y", "2Y"]})


def test_confidence_thresholds_minimum_observations_for_window_covers_all_windows():
    ct = ConfidenceThresholds()
    assert ct.minimum_observations_for_window("6M") == 20
    assert ct.minimum_observations_for_window("12M") == 40
    assert ct.minimum_observations_for_window("2Y") == 80
    assert ct.minimum_observations_for_window("3Y") == 120
    assert ct.minimum_observations_for_window("5Y") == 200
    for window in ALL_WINDOWS:
        assert ct.minimum_observations_for_window(window) == getattr(
            ct, f"minimum_observations_{window_suffix(window)}"
        )
    with pytest.raises(ValueError, match="Unsupported structural window"):
        ct.minimum_observations_for_window("7Y")


@pytest.mark.parametrize("field", ["minimum_observations_2y", "minimum_observations_5y"])
def test_confidence_thresholds_reject_non_positive_display_floor(field):
    # A non-positive observation floor would defeat the LOW_OBSERVATION gate, letting a
    # thin long-lookback window show as ELIGIBLE/reliable. Must be rejected like the
    # scoring-window floors (the positivity guard covers all five windows).
    for bad in (0, -5):
        with pytest.raises(
            ValidationError, match="minimum observations must all be positive"
        ):
            ConfidenceThresholds.model_validate({field: bad})


def test_confidence_thresholds_observation_floors_share_one_scaling():
    # Every window's floor tracks the same ~0.77 obs/week scaling. Pins the floors so a
    # future edit cannot silently desync one window from the rest.
    ct = ConfidenceThresholds()
    ratios = {
        "6M": ct.minimum_observations_6m / 26,
        "12M": ct.minimum_observations_12m / 52,
        "2Y": ct.minimum_observations_2y / 104,
        "3Y": ct.minimum_observations_3y / 156,
        "5Y": ct.minimum_observations_5y / 260,
    }
    for window, ratio in ratios.items():
        assert ratio == pytest.approx(20 / 26, abs=0.05), window


def test_fundamentals_config_refresh_fetch_max_age_days_defaults_and_validates():
    assert FundamentalsConfig().refresh_fetch_max_age_days == 7
    assert FundamentalsConfig(refresh_fetch_max_age_days=30).refresh_fetch_max_age_days == 30
    for bad in (0, -3):
        with pytest.raises(ValidationError, match="refresh_fetch_max_age_days must be positive"):
            FundamentalsConfig(refresh_fetch_max_age_days=bad)


def test_candidate_finder_preset_accepts_no_option_filter():
    config = CandidateFinderConfig.model_validate(
        {
            "criteria": [
                {
                    "id": "fundamental_check_score",
                    "label": "Fundamental checks",
                    "description": "Pass/fail count across core finance checks.",
                    "source_field": "fundamental_check_score",
                    "group": "Corporate Finance",
                    "default_direction": "high_good",
                    "unit": "score",
                }
            ],
            "presets": [
                {
                    "id": "bull",
                    "label": "Bull",
                    "options_side": "none",
                    "criteria": [{"id": "fundamental_check_score"}],
                }
            ],
        }
    )

    assert config.presets[0].options_side == "none"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    "field", ["tag_steep_beta_at_least", "tag_low_confidence_below"]
)
def test_tool_c_config_rejects_non_finite_tag_thresholds(field, bad):
    """NaN/+inf slip past bare `<= 0` comparisons; a non-finite tag threshold
    would tag every miner (or none) with no error."""

    with pytest.raises(ValidationError):
        ToolCConfig.model_validate({"version": 1, field: bad})


def test_real_tool_c_yaml_validates():
    import yaml

    from golden_vector.app.paths import ProjectPaths

    raw = yaml.safe_load(
        ProjectPaths.discover().config_path("tool_c.yaml").read_text(encoding="utf-8")
    )
    config = ToolCConfig.model_validate(raw)

    assert config.tag_steep_beta_at_least > 0
