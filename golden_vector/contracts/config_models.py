"""Pydantic models for repository configuration."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_CURRENCIES = {"USD", "CAD", "GBP", "AUD", "ZAR", "EUR", "SEK"}
HORIZON_PATTERN = re.compile(r"^\d+[DMY]$")


class StrictConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UniverseTicker(StrictConfigModel):
    ticker: str
    company: str | None = None
    exchange: str | None = None
    currency: str
    jurisdiction_tier: int | None = None
    active: bool = True
    tool_a_enabled: bool = True
    tool_b_enabled: bool = True

    @field_validator("ticker", "currency")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.upper()

    @field_validator("jurisdiction_tier")
    @classmethod
    def valid_tier(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in {1, 2, 3}:
            raise ValueError("jurisdiction_tier must be 1, 2, or 3")
        return value

    @field_validator("currency")
    @classmethod
    def supported_currency(cls, value: str) -> str:
        if value not in SUPPORTED_CURRENCIES:
            supported = ", ".join(sorted(SUPPORTED_CURRENCIES))
            raise ValueError(f"currency must be one of: {supported}")
        return value


class UniverseConfig(StrictConfigModel):
    version: int = 1
    tickers: list[UniverseTicker] = Field(default_factory=list, min_length=1)

    @model_validator(mode="after")
    def unique_tickers(self) -> "UniverseConfig":
        seen: set[str] = set()
        for ticker in self.tickers:
            if ticker.ticker in seen:
                raise ValueError(f"Duplicate ticker in universe config: {ticker.ticker}")
            seen.add(ticker.ticker)
        return self


class BenchmarkTicker(StrictConfigModel):
    ticker: str
    yahoo_symbol: str
    label: str | None = None
    active: bool = True

    @field_validator("ticker", "yahoo_symbol")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.upper()


class BenchmarksConfig(StrictConfigModel):
    version: int = 1
    benchmarks: list[BenchmarkTicker] = Field(default_factory=list, min_length=1)

    @model_validator(mode="after")
    def unique_tickers(self) -> "BenchmarksConfig":
        seen: set[str] = set()
        for benchmark in self.benchmarks:
            if benchmark.ticker in seen:
                raise ValueError(f"Duplicate benchmark ticker: {benchmark.ticker}")
            seen.add(benchmark.ticker)
        return self


class HedgeReadinessConfig(StrictConfigModel):
    version: int = 1
    target_delta: float = -0.25
    target_horizons_days: list[int] = Field(default_factory=lambda: [30, 60, 90], min_length=1)
    optionability_open_interest_threshold: int = 1000
    implied_move_max_spread_pct: float = 0.35
    implied_move_min_open_interest: int = 1
    implied_move_min_volume: int = 0
    candidate_max_spread_pct: float = 0.35
    candidate_min_open_interest: int = 1
    candidate_min_volume: int = 0
    candidate_min_implied_volatility: float = 0.01
    candidate_max_implied_volatility: float = 3.0
    delta_gap_warning_threshold: float = 0.10
    hedge_ratio_cheap_max: float = 0.40
    hedge_ratio_expensive_min: float = 0.80
    proxy_max_beta_diff: float = 0.35
    proxy_top_n: int = 3
    benchmark_tickers: list[str] = Field(default_factory=lambda: ["GDX", "GDXJ"], min_length=1)
    gold_down_scenarios: list[float] = Field(default_factory=lambda: [0.05, 0.10, 0.20], min_length=1)
    default_scenario_quantity: int = 5
    default_scenarios: list[float] = Field(
        default_factory=lambda: [0.0, -0.05, -0.10, -0.15, -0.20],
        min_length=1,
    )
    optionability_tier_min: Literal["directly_hedgeable", "thin"] = "directly_hedgeable"
    max_tickers_speculation_section: int = 15

    @field_validator("target_delta")
    @classmethod
    def valid_put_target_delta(cls, value: float) -> float:
        if not -1.0 < value < 0.0:
            raise ValueError("target_delta must be a negative put delta between -1 and 0")
        return float(value)

    @field_validator(
        "optionability_open_interest_threshold",
        "implied_move_min_open_interest",
        "implied_move_min_volume",
        "candidate_min_open_interest",
        "candidate_min_volume",
    )
    @classmethod
    def non_negative_ints(cls, value: int) -> int:
        if value < 0:
            raise ValueError("integer thresholds must be non-negative")
        return value

    @field_validator("proxy_top_n")
    @classmethod
    def positive_proxy_top_n(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("proxy_top_n must be positive")
        return value

    @field_validator("default_scenario_quantity", "max_tickers_speculation_section")
    @classmethod
    def positive_scenario_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("scenario integer settings must be positive")
        return value

    @field_validator("target_horizons_days")
    @classmethod
    def valid_target_horizons(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("target_horizons_days must be positive")
        if len(set(values)) != len(values):
            raise ValueError("target_horizons_days must be unique")
        return values

    @field_validator(
        "implied_move_max_spread_pct",
        "candidate_max_spread_pct",
        "candidate_min_implied_volatility",
        "candidate_max_implied_volatility",
        "delta_gap_warning_threshold",
        "proxy_max_beta_diff",
    )
    @classmethod
    def positive_float_thresholds(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("float thresholds must be positive")
        return float(value)

    @model_validator(mode="after")
    def valid_candidate_iv_range(self) -> "HedgeReadinessConfig":
        if self.candidate_min_implied_volatility >= self.candidate_max_implied_volatility:
            raise ValueError(
                "candidate_min_implied_volatility must be less than "
                "candidate_max_implied_volatility"
            )
        return self

    @field_validator("benchmark_tickers")
    @classmethod
    def uppercase_benchmark_tickers(cls, values: list[str]) -> list[str]:
        normalized = [value.upper() for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("benchmark_tickers must be unique")
        return normalized

    @field_validator("gold_down_scenarios")
    @classmethod
    def valid_gold_down_scenarios(cls, values: list[float]) -> list[float]:
        if any(value <= 0 or value >= 1 for value in values):
            raise ValueError("gold_down_scenarios must be fractions between 0 and 1")
        if len(set(values)) != len(values):
            raise ValueError("gold_down_scenarios must be unique")
        return values

    @field_validator("default_scenarios")
    @classmethod
    def valid_default_scenarios(cls, values: list[float]) -> list[float]:
        normalized = [float(value) for value in values]
        if any(value <= -1 or value > 0 for value in normalized):
            raise ValueError("default_scenarios must be fractions greater than -1 and at most 0")
        if len(set(normalized)) != len(normalized):
            raise ValueError("default_scenarios must be unique")
        return normalized

    @model_validator(mode="after")
    def ordered_hedge_ratio_bands(self) -> "HedgeReadinessConfig":
        if self.hedge_ratio_cheap_max <= 0:
            raise ValueError("hedge_ratio_cheap_max must be positive")
        if self.hedge_ratio_expensive_min <= self.hedge_ratio_cheap_max:
            raise ValueError("hedge_ratio_expensive_min must exceed hedge_ratio_cheap_max")
        return self


class CustomHorizonValidation(StrictConfigModel):
    allowed_units: list[Literal["D", "M", "Y"]] = Field(default_factory=lambda: ["D", "M", "Y"])
    min_value: int = 1
    max_value: int = 120


class HorizonsConfig(StrictConfigModel):
    version: int = 1
    core_horizons: list[str] = Field(min_length=1)
    custom_validation: CustomHorizonValidation

    @model_validator(mode="after")
    def unique_core_horizons(self) -> "HorizonsConfig":
        if len(set(self.core_horizons)) != len(self.core_horizons):
            raise ValueError("core_horizons must be unique")
        return self

    @field_validator("core_horizons")
    @classmethod
    def valid_core_horizon_format(cls, values: list[str]) -> list[str]:
        invalid = [value for value in values if not HORIZON_PATTERN.match(value)]
        if invalid:
            raise ValueError(
                "core_horizons must match positive integer plus D, M, or Y: "
                + ", ".join(invalid)
            )
        return values


class QaConfig(StrictConfigModel):
    version: int = 1
    near_zero_gold_return_threshold: float = 0.005
    minimum_equity_history_days: int = 252
    minimum_gold_history_days: int = 252
    minimum_fx_history_days: int = 252
    max_fx_staleness_days: int = 5
    block_on_missing_currency_map: bool = True
    block_on_missing_fx_history: bool = True
    block_on_missing_gold_history: bool = True
    block_on_stale_fx: bool = False
    warn_on_duplicate_rows: bool = True

    @field_validator(
        "minimum_equity_history_days",
        "minimum_gold_history_days",
        "minimum_fx_history_days",
        "max_fx_staleness_days",
    )
    @classmethod
    def positive_day_thresholds(cls, value: int) -> int:
        if value < 0:
            raise ValueError("QA day thresholds must be non-negative")
        return value


class DeltaBucketThresholds(StrictConfigModel):
    low_max: float = 0.75
    moderate_max: float = 1.5


class StructuralDeltaBands(StrictConfigModel):
    low_max: float = 0.75
    moderate_max: float = 1.5
    high_min: float = 2.0

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "StructuralDeltaBands":
        if not (self.low_max < self.moderate_max < self.high_min):
            raise ValueError(
                "structural delta bands must satisfy low_max < moderate_max < high_min"
            )
        return self


class StabilityThresholds(StrictConfigModel):
    weak_max: float = 0.4
    strong_min: float = 0.7

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "StabilityThresholds":
        if self.strong_min <= self.weak_max:
            raise ValueError("stability thresholds must satisfy weak_max < strong_min")
        return self


class GammaThresholds(StrictConfigModel):
    negative_max: float = -0.25
    positive_min: float = 0.25

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "GammaThresholds":
        if self.positive_min <= self.negative_max:
            raise ValueError("gamma thresholds must satisfy negative_max < positive_min")
        return self


class AsymmetryThresholds(StrictConfigModel):
    weak_max: float = 0.9
    strong_min: float = 1.1

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "AsymmetryThresholds":
        if self.strong_min <= self.weak_max:
            raise ValueError(
                "asymmetry thresholds must satisfy weak_max < strong_min"
            )
        return self


class ConfidenceThresholds(StrictConfigModel):
    low_max: float = 0.5
    high_min: float = 0.8
    minimum_rankable: float = 0.45
    fit_warn_r_squared: float = 0.15
    fit_good_r_squared: float = 0.3
    minimum_observations_6m: int = 20
    minimum_observations_12m: int = 40
    minimum_observations_3y: int = 120
    stability_floor: float = 0.25

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "ConfidenceThresholds":
        if not (0.0 <= self.low_max < self.high_min <= 1.0):
            raise ValueError(
                "confidence thresholds must satisfy 0 <= low_max < high_min <= 1"
            )
        if not (0.0 <= self.minimum_rankable <= 1.0):
            raise ValueError("minimum_rankable must be between 0 and 1")
        if not (0.0 <= self.fit_warn_r_squared < self.fit_good_r_squared <= 1.0):
            raise ValueError(
                "fit R-squared thresholds must satisfy "
                "0 <= fit_warn_r_squared < fit_good_r_squared <= 1"
            )
        if min(
            self.minimum_observations_6m,
            self.minimum_observations_12m,
            self.minimum_observations_3y,
        ) <= 0:
            raise ValueError("minimum observations must all be positive")
        if self.stability_floor <= 0:
            raise ValueError("stability_floor must be positive")
        return self

    def minimum_observations_for_window(self, window_id: str) -> int:
        normalized = str(window_id).strip().upper()
        mapping = {
            "6M": self.minimum_observations_6m,
            "12M": self.minimum_observations_12m,
            "3Y": self.minimum_observations_3y,
        }
        if normalized not in mapping:
            raise ValueError(f"Unsupported structural window: {window_id}")
        return mapping[normalized]

    def minimum_regime_observations_for_window(self, window_id: str) -> int:
        minimum_observations = self.minimum_observations_for_window(window_id)
        return max(8, minimum_observations // 3)


class VolatilityDiagnosticBands(StrictConfigModel):
    low_residual_volatility_max: float = 0.35
    high_residual_volatility_min: float = 0.6
    high_downside_volatility_min: float = 0.5
    high_total_volatility_min: float = 0.75

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "VolatilityDiagnosticBands":
        if self.high_residual_volatility_min <= self.low_residual_volatility_max:
            raise ValueError(
                "volatility bands must satisfy "
                "low_residual_volatility_max < high_residual_volatility_min"
            )
        if min(
            self.high_downside_volatility_min,
            self.high_total_volatility_min,
        ) <= 0:
            raise ValueError("volatility thresholds must be positive")
        return self


class ScoreWeights(StrictConfigModel):
    structural_delta: float = 0.4
    structural_gamma: float = 0.25
    asymmetry: float = 0.15
    confidence: float = 0.2

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ScoreWeights":
        total = (
            self.structural_delta
            + self.structural_gamma
            + self.asymmetry
            + self.confidence
        )
        if abs(total - 1.0) > 1e-9:
            raise ValueError("score weights must sum to 1.0")
        return self


class StructuralWindowWeights(StrictConfigModel):
    windows: dict[str, float] = Field(
        default_factory=lambda: {"6M": 1.0, "12M": 1.0, "3Y": 1.0}
    )

    @field_validator("windows")
    @classmethod
    def valid_window_weights(cls, value: dict[str, float]) -> dict[str, float]:
        normalized = {str(key).strip().upper(): float(weight) for key, weight in value.items()}
        if set(normalized) != {"6M", "12M", "3Y"}:
            raise ValueError("structural window weights must contain exactly: 6M, 12M, 3Y")
        if any(weight <= 0 for weight in normalized.values()):
            raise ValueError("structural window weights must all be positive")
        return normalized


class CombinedVerdictThresholds(StrictConfigModel):
    high_conviction_min_tool_a_score: float = 75.0
    dual_pass_min_tool_a_score: float = 60.0

    @model_validator(mode="after")
    def ordered_thresholds(self) -> "CombinedVerdictThresholds":
        if self.high_conviction_min_tool_a_score < self.dual_pass_min_tool_a_score:
            raise ValueError(
                "combined verdict thresholds must satisfy "
                "high_conviction_min_tool_a_score >= dual_pass_min_tool_a_score"
            )
        return self


class ScoringConfig(StrictConfigModel):
    version: int = 2
    structural_windows: list[str] = Field(
        default_factory=lambda: ["6M", "12M", "3Y"],
        min_length=3,
        max_length=3,
    )
    delta_bands: StructuralDeltaBands = Field(default_factory=StructuralDeltaBands)
    gamma_thresholds: GammaThresholds = Field(default_factory=GammaThresholds)
    asymmetry_thresholds: AsymmetryThresholds = Field(
        default_factory=AsymmetryThresholds
    )
    confidence_thresholds: ConfidenceThresholds = Field(
        default_factory=ConfidenceThresholds
    )
    volatility_bands: VolatilityDiagnosticBands = Field(
        default_factory=VolatilityDiagnosticBands
    )
    structural_window_weights: StructuralWindowWeights = Field(
        default_factory=StructuralWindowWeights
    )
    structural_anchor_window: str = "12M"
    minimum_rankable_structural_delta: float = 1.0
    blocked_normalization_statuses: list[str] = Field(
        default_factory=lambda: ["MISSING_RETURN_BASIS", "MISSING_FX", "STALE_FX"]
    )
    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    combined_verdict_thresholds: CombinedVerdictThresholds = Field(
        default_factory=CombinedVerdictThresholds
    )

    @field_validator("structural_windows")
    @classmethod
    def valid_structural_windows(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if normalized != ["6M", "12M", "3Y"]:
            raise ValueError(
                "structural_windows must be exactly: 6M, 12M, 3Y"
            )
        return normalized

    @field_validator("structural_anchor_window")
    @classmethod
    def valid_anchor_window(cls, value: str) -> str:
        normalized = str(value).strip().upper()
        if normalized not in {"6M", "12M", "3Y"}:
            raise ValueError("structural_anchor_window must be one of: 6M, 12M, 3Y")
        return normalized

    @field_validator("blocked_normalization_statuses")
    @classmethod
    def valid_blocked_statuses(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip().upper() for value in values if str(value).strip()]
        allowed = {"MISSING_RETURN_BASIS", "MISSING_FX", "STALE_FX"}
        invalid = sorted(set(normalized).difference(allowed))
        if invalid:
            raise ValueError(
                "blocked_normalization_statuses contains unsupported values: "
                + ", ".join(invalid)
            )
        return normalized

    @field_validator("minimum_rankable_structural_delta")
    @classmethod
    def positive_rankable_delta(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("minimum_rankable_structural_delta must be positive")
        return float(value)

    def structural_weight_map(self) -> dict[str, float]:
        return dict(self.structural_window_weights.windows)

    def anchor_window_preference(self) -> list[str]:
        canonical_order = ["12M", "3Y", "6M"]
        anchor = self.structural_anchor_window
        return [anchor] + [window for window in canonical_order if window != anchor]

    def blocked_normalization_status_set(self) -> set[str]:
        return {status.upper() for status in self.blocked_normalization_statuses}


class Layer1Thresholds(StrictConfigModel):
    aisc_max: float = 1850.0
    margin_min: float = 0.5
    fcf_yield_min: float = 0.15
    reserve_life_min: float = 6.0
    leverage_max: float = 2.5


class VerdictThresholds(StrictConfigModel):
    strong_candidate_forward_pe_max: float = 8.0
    watchlist_forward_pe_max: float = 10.0


class PeerBenchmark(StrictConfigModel):
    pe_2026: float
    pe_2011_peak: float
    evebitda_2026: float
    evebitda_2011: float
    fcf_yield_2026: float
    fcf_yield_2011: float


class JurisdictionDiscounts(StrictConfigModel):
    tier_1: float = 0.0
    tier_2: float = 0.15
    tier_3: float = 0.3


class ScreeningParamsConfig(StrictConfigModel):
    version: int = 1
    default_gold_price_assumption: float | None = None
    gold_price_scenarios: list[float] = Field(min_length=1)
    layer1_thresholds: Layer1Thresholds = Field(default_factory=Layer1Thresholds)
    verdict_thresholds: VerdictThresholds = Field(default_factory=VerdictThresholds)
    jurisdiction_discounts: JurisdictionDiscounts = Field(default_factory=JurisdictionDiscounts)
    peer_benchmarks: dict[str, PeerBenchmark]

    @field_validator("gold_price_scenarios")
    @classmethod
    def valid_gold_price_scenarios(cls, values: list[float]) -> list[float]:
        if any(value <= 0 for value in values):
            raise ValueError("gold_price_scenarios must be positive")
        if len(set(values)) != len(values):
            raise ValueError("gold_price_scenarios must be unique")
        return values

    @field_validator("default_gold_price_assumption")
    @classmethod
    def valid_default_gold_price(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("default_gold_price_assumption must be positive")
        return float(value)

    def resolve_gold_price(self, override: float | None = None) -> float:
        """Pick the gold price for a Tool B run.

        Order of preference: explicit CLI override → config default → first
        configured scenario. The last fallback ensures Tool B can always run
        even if the operator hasn't set a default.
        """
        if override is not None:
            return float(override)
        if self.default_gold_price_assumption is not None:
            return float(self.default_gold_price_assumption)
        return float(self.gold_price_scenarios[0])

    @field_validator("peer_benchmarks")
    @classmethod
    def required_peer_benchmarks(cls, values: dict[str, PeerBenchmark]) -> dict[str, PeerBenchmark]:
        required = {"large", "mid", "small", "micro"}
        missing = sorted(required.difference(values))
        if missing:
            raise ValueError(f"peer_benchmarks is missing required buckets: {', '.join(missing)}")
        return values


class AppConfig(StrictConfigModel):
    universe: UniverseConfig
    benchmarks: BenchmarksConfig
    hedge_readiness: HedgeReadinessConfig = Field(default_factory=HedgeReadinessConfig)
    horizons: HorizonsConfig
    qa: QaConfig
    scoring: ScoringConfig
    screening_params: ScreeningParamsConfig
