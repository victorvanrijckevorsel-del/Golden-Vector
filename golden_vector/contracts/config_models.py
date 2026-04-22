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


class ScoreWeights(StrictConfigModel):
    core_delta: float = 0.5
    stability: float = 0.3
    gamma_proxy: float = 0.2

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ScoreWeights":
        total = self.core_delta + self.stability + self.gamma_proxy
        if abs(total - 1.0) > 1e-9:
            raise ValueError("score weights must sum to 1.0")
        return self


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
    version: int = 1
    minimum_core_horizons_for_scoring: int = 5
    allow_warn_coverage_for_scoring: bool = False
    delta_buckets: DeltaBucketThresholds = Field(default_factory=DeltaBucketThresholds)
    stability_thresholds: StabilityThresholds = Field(default_factory=StabilityThresholds)
    gamma_thresholds: GammaThresholds = Field(default_factory=GammaThresholds)
    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    combined_verdict_thresholds: CombinedVerdictThresholds = Field(
        default_factory=CombinedVerdictThresholds
    )


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
    horizons: HorizonsConfig
    qa: QaConfig
    scoring: ScoringConfig
    screening_params: ScreeningParamsConfig
