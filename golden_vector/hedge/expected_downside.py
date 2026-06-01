"""Premium-versus-modeled-downside helpers."""

from __future__ import annotations

from dataclasses import dataclass

from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.holdings import Holding


@dataclass(frozen=True)
class DownsideScenario:
    gold_down_pct: float
    modeled_stock_down_pct: float | None
    modeled_downside_usd: float | None
    hedge_premium_usd: float | None
    hedge_ratio: float | None
    tag: str


@dataclass(frozen=True)
class PremiumVsDownsideCard:
    ticker: str
    horizon_days: int
    confidence_score: float | None
    exposure_usd: float | None
    premium_pct_of_notional: float | None
    full_hedge_premium_usd: float | None
    scenarios: list[DownsideScenario]


def compute_premium_vs_downside(
    *,
    ticker: str,
    down_beta: float | None,
    confidence_score: float | None,
    holding: Holding,
    candidate_put: CandidatePut,
    gold_scenarios: tuple[float, ...] = (0.05, 0.10, 0.20),
    cheap_ratio_max: float = 0.40,
    expensive_ratio_min: float = 0.80,
) -> PremiumVsDownsideCard:
    """Compare full-notional put premium against modeled gold-down downside."""

    exposure = holding.exposure_usd(share_price=candidate_put.underlying_price)
    premium_pct = candidate_put.premium_pct_spot
    full_premium = (
        exposure * premium_pct
        if exposure is not None and premium_pct is not None
        else None
    )
    scenarios = [
        _scenario(
            gold_down_pct=gold_down_pct,
            down_beta=down_beta,
            exposure=exposure,
            full_premium=full_premium,
            cheap_ratio_max=cheap_ratio_max,
            expensive_ratio_min=expensive_ratio_min,
        )
        for gold_down_pct in gold_scenarios
    ]
    return PremiumVsDownsideCard(
        ticker=ticker,
        horizon_days=candidate_put.horizon_days,
        confidence_score=confidence_score,
        exposure_usd=exposure,
        premium_pct_of_notional=premium_pct,
        full_hedge_premium_usd=full_premium,
        scenarios=scenarios,
    )


def _scenario(
    *,
    gold_down_pct: float,
    down_beta: float | None,
    exposure: float | None,
    full_premium: float | None,
    cheap_ratio_max: float,
    expensive_ratio_min: float,
) -> DownsideScenario:
    if down_beta is None or exposure is None:
        return DownsideScenario(
            gold_down_pct=gold_down_pct,
            modeled_stock_down_pct=None,
            modeled_downside_usd=None,
            hedge_premium_usd=full_premium,
            hedge_ratio=None,
            tag="downside_unavailable",
        )

    modeled_stock_down_pct = max(float(down_beta), 0.0) * gold_down_pct
    modeled_downside = exposure * modeled_stock_down_pct
    hedge_ratio = (
        full_premium / modeled_downside
        if full_premium is not None and modeled_downside > 0
        else None
    )
    return DownsideScenario(
        gold_down_pct=gold_down_pct,
        modeled_stock_down_pct=modeled_stock_down_pct,
        modeled_downside_usd=modeled_downside,
        hedge_premium_usd=full_premium,
        hedge_ratio=hedge_ratio,
        tag=_tag_for_ratio(
            hedge_ratio,
            cheap_ratio_max=cheap_ratio_max,
            expensive_ratio_min=expensive_ratio_min,
        ),
    )


def _tag_for_ratio(
    hedge_ratio: float | None,
    *,
    cheap_ratio_max: float,
    expensive_ratio_min: float,
) -> str:
    if hedge_ratio is None:
        return "premium_unavailable"
    if hedge_ratio <= cheap_ratio_max:
        return "protection_cheap"
    if hedge_ratio >= expensive_ratio_min:
        return "protection_expensive"
    return "protection_normal"
