"""Pure option-chain liquidity scanning and bucket selection."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, cast

import pandas as pd

from golden_vector.features.options_chain import (
    add_black_scholes_delta,
    as_float,
    as_int,
    normalize_options_chain,
)
from golden_vector.hedge.candidate_puts import (
    CandidateSlotStatus,
    OptionCandidate,
    OptionCandidateSlot,
)

OptionLiquidityTier = Literal["tradable", "watch", "no_trade"]
OptionBucket = Literal["near_atm", "directional"]
OptionSideType = Literal["P", "C"]

BUCKET_LABELS: dict[str, str] = {
    "near_atm": "Near-ATM",
    "directional": "Directional",
}

CANDIDATE_BUCKETS: tuple[Literal["near_atm", "directional"], ...] = (
    "near_atm",
    "directional",
)


@dataclass(frozen=True)
class SlotLiquidityThresholds:
    max_spread_pct: float
    min_open_interest: int
    min_mid: float


class OptionLiquidityConfigLike(Protocol):
    option_liquidity_tradable_spread_pct: float
    option_liquidity_watch_spread_pct: float
    option_liquidity_min_open_interest: int
    option_liquidity_min_premium: float
    option_liquidity_near_spot_pct: float
    option_liquidity_target_depth_count: int
    option_liquidity_oi_cap: int
    option_liquidity_volume_cap: int
    option_sensible_moneyness_max_pct: float
    option_dte_bands: dict[int, list[int]]
    candidate_min_implied_volatility: float
    candidate_max_implied_volatility: float


@dataclass(frozen=True)
class OptionLiquiditySettings:
    tradable_spread_pct: float = 0.20
    watch_spread_pct: float = 0.50
    min_open_interest: int = 1
    min_premium: float = 0.15
    near_spot_pct: float = 0.10
    target_depth_count: int = 10
    oi_cap: int = 1000
    volume_cap: int = 1000
    sensible_moneyness_max_pct: float = 0.35
    min_implied_volatility: float = 0.01
    max_implied_volatility: float = 3.0
    dte_bands: dict[int, tuple[int, int]] | None = None
    near_atm_otm_min: float = 0.0
    near_atm_otm_max: float = 0.05
    directional_preferred_otm_min: float = 0.15
    directional_preferred_otm_max: float = 0.20
    directional_allowed_otm_min: float = 0.12
    directional_allowed_otm_max: float = 0.22
    near_atm_strict_max_spread_pct: float = 0.25
    near_atm_strict_min_open_interest: int = 100
    near_atm_strict_min_mid: float = 0.20
    near_atm_watch_max_spread_pct: float = 0.35
    near_atm_watch_min_open_interest: int = 50
    near_atm_watch_min_mid: float = 0.15
    directional_strict_max_spread_pct: float = 0.35
    directional_strict_min_open_interest: int = 50
    directional_strict_min_mid: float = 0.10
    directional_watch_max_spread_pct: float = 0.45
    directional_watch_min_open_interest: int = 25
    directional_watch_min_mid: float = 0.05
    lottery_iv_threshold: float = 0.75
    lottery_abs_delta_max: float = 0.15
    lottery_dte_max: int = 75

    def band_for_horizon(self, horizon_days: int) -> tuple[int, int]:
        bands = self.dte_bands or {
            60: (40, 74),
            90: (75, 104),
            120: (105, 150),
        }
        return bands.get(horizon_days, (horizon_days, horizon_days))


@dataclass(frozen=True)
class OptionContractMetrics:
    ticker: str
    option_type: OptionSideType
    expiration: str
    days_to_expiry: int
    strike: float
    underlying_price: float
    bid: float | None
    ask: float | None
    mid: float | None
    last_price: float | None
    open_interest: int
    volume: int
    implied_volatility: float | None
    delta: float | None
    rel_spread: float | None
    half_spread_cost_pct: float | None
    moneyness_pct: float | None
    otm_pct: float | None
    premium_pct_spot: float | None
    near_spot_depth_count: int
    liquidity_score: float
    liquidity_tier: OptionLiquidityTier
    quote_flags: tuple[str, ...]
    is_standard_monthly: bool


@dataclass(frozen=True)
class OptionChainScan:
    ticker: str
    underlying_price: float
    metrics: tuple[OptionContractMetrics, ...]

    def by_type(self, option_type: OptionSideType) -> tuple[OptionContractMetrics, ...]:
        return tuple(metric for metric in self.metrics if metric.option_type == option_type)

    def tier_count(self, option_type: OptionSideType, tier: OptionLiquidityTier) -> int:
        return sum(
            1
            for metric in self.metrics
            if metric.option_type == option_type and metric.liquidity_tier == tier
        )


def settings_from_config(config: OptionLiquidityConfigLike) -> OptionLiquiditySettings:
    return OptionLiquiditySettings(
        tradable_spread_pct=float(config.option_liquidity_tradable_spread_pct),
        watch_spread_pct=float(config.option_liquidity_watch_spread_pct),
        min_open_interest=int(config.option_liquidity_min_open_interest),
        min_premium=float(config.option_liquidity_min_premium),
        near_spot_pct=float(config.option_liquidity_near_spot_pct),
        target_depth_count=int(config.option_liquidity_target_depth_count),
        oi_cap=int(config.option_liquidity_oi_cap),
        volume_cap=int(config.option_liquidity_volume_cap),
        sensible_moneyness_max_pct=float(config.option_sensible_moneyness_max_pct),
        min_implied_volatility=float(config.candidate_min_implied_volatility),
        max_implied_volatility=float(config.candidate_max_implied_volatility),
        dte_bands={
            int(horizon): (int(band[0]), int(band[1]))
            for horizon, band in config.option_dte_bands.items()
        },
    )


def scan_option_chain(
    *,
    ticker: str,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    settings: OptionLiquiditySettings | None = None,
    as_of_date: date | None = None,
) -> OptionChainScan:
    settings = settings or OptionLiquiditySettings()
    frame = normalize_options_chain(
        chain,
        as_of_date=as_of_date,
        underlying_price=underlying_price,
    )
    if frame.empty or underlying_price <= 0:
        return OptionChainScan(ticker=ticker, underlying_price=underlying_price, metrics=())
    frame = add_black_scholes_delta(
        frame,
        underlying_price=underlying_price,
        risk_free_rate=risk_free_rate,
    )
    near_spot_depth_by_key = _near_spot_depth_counts(
        frame=frame,
        underlying_price=underlying_price,
        settings=settings,
    )
    metrics = tuple(
        _metric_from_row(
            ticker=ticker,
            row=row,
            underlying_price=underlying_price,
            settings=settings,
            near_spot_depth_by_key=near_spot_depth_by_key,
        )
        for _, row in frame.iterrows()
    )
    return OptionChainScan(
        ticker=ticker,
        underlying_price=underlying_price,
        metrics=metrics,
    )


def build_bucket_slots(
    *,
    option_type: OptionSideType,
    ticker: str,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    target_horizons_days: tuple[int, ...],
    settings: OptionLiquiditySettings | None = None,
    as_of_date: date | None = None,
) -> list[OptionCandidateSlot]:
    normalized_type = _normalize_option_type(option_type)
    settings = settings or OptionLiquiditySettings()
    scan = scan_option_chain(
        ticker=ticker,
        chain=chain,
        underlying_price=underlying_price,
        risk_free_rate=risk_free_rate,
        settings=settings,
        as_of_date=as_of_date,
    )
    return build_bucket_slots_from_scan(
        option_type=normalized_type,
        scan=scan,
        target_horizons_days=target_horizons_days,
        settings=settings,
    )


def build_bucket_slots_from_scan(
    *,
    option_type: OptionSideType,
    scan: OptionChainScan,
    target_horizons_days: tuple[int, ...],
    settings: OptionLiquiditySettings | None = None,
) -> list[OptionCandidateSlot]:
    normalized_type = _normalize_option_type(option_type)
    settings = settings or OptionLiquiditySettings()
    if not scan.metrics:
        return [
            _empty_bucket_slot(
                ticker=scan.ticker,
                option_type=normalized_type,
                horizon_days=horizon,
                bucket=bucket,
                status="no_chain",
                reason="No listed options chain is available in the cached snapshot.",
            )
            for horizon in target_horizons_days
            for bucket in _buckets_for_side()
        ]

    slots: list[OptionCandidateSlot] = []
    side_metrics = scan.by_type(normalized_type)
    for horizon in target_horizons_days:
        lower, upper = settings.band_for_horizon(horizon)
        horizon_metrics = tuple(
            metric
            for metric in side_metrics
            if lower <= metric.days_to_expiry <= upper
        )
        for bucket in _buckets_for_side():
            slots.append(
                _slot_for_bucket(
                    option_type=normalized_type,
                    ticker=scan.ticker,
                    horizon_days=horizon,
                    bucket=bucket,
                    metrics=horizon_metrics,
                    settings=settings,
                    listed_contract_count=len(horizon_metrics),
                )
            )
    return slots


def candidate_bucket_ids() -> tuple[str, ...]:
    return CANDIDATE_BUCKETS


def is_usable_candidate(
    metric: OptionContractMetrics,
    *,
    bucket_fit: bool,
    settings: OptionLiquiditySettings | None = None,
) -> bool:
    settings = settings or OptionLiquiditySettings()
    return (
        bucket_fit
        and metric.liquidity_tier == "tradable"
        and metric.otm_pct is not None
        and metric.moneyness_pct is not None
        and metric.moneyness_pct <= settings.sensible_moneyness_max_pct
        and _iv_is_usable(metric, settings)
    )


def bucket_label(bucket: str | None) -> str:
    return BUCKET_LABELS.get(str(bucket or ""), str(bucket or "").replace("_", " ").title())


def liquidity_summary(scan: OptionChainScan) -> dict[str, dict[str, int]]:
    return {
        side: {
            tier: scan.tier_count(cast(OptionSideType, side), cast(OptionLiquidityTier, tier))
            for tier in ("tradable", "watch", "no_trade")
        }
        for side in ("P", "C")
    }


def slot_tier_counts(slots: Iterable[OptionCandidateSlot]) -> dict[str, int]:
    """Count bucket slots by user-facing availability tier."""

    counts = {"tradable": 0, "watch": 0, "no_trade": 0}
    for slot in slots:
        if slot.candidate is not None:
            tier = slot.candidate.liquidity_tier or slot.liquidity_tier
        elif (
            slot.rejected_candidate is not None
            and slot.rejected_candidate.liquidity_tier == "watch"
        ):
            tier = "watch"
        else:
            tier = "no_trade"
        counts[tier if tier in counts else "no_trade"] += 1
    return counts


def _metric_from_row(
    *,
    ticker: str,
    row: pd.Series,
    underlying_price: float,
    settings: OptionLiquiditySettings,
    near_spot_depth_by_key: dict[tuple[str, OptionSideType], int],
) -> OptionContractMetrics:
    option_type = _normalize_option_type(str(row.get("option_type", "")))
    bid = as_float(row.get("bid"))
    ask = as_float(row.get("ask"))
    mid = as_float(row.get("mid"))
    strike = as_float(row.get("strike")) or 0.0
    expiration_value = row.get("expiration")
    expiration = str(expiration_value) if expiration_value is not None else ""
    days_to_expiry = as_int(row.get("days_to_expiry")) or 0
    open_interest = as_int(row.get("open_interest")) or 0
    volume = as_int(row.get("volume")) or 0
    implied_volatility = as_float(row.get("implied_volatility"))
    delta = as_float(row.get("delta"))
    rel_spread = _relative_spread(bid=bid, ask=ask, mid=mid)
    moneyness_pct = (
        abs(strike - underlying_price) / underlying_price
        if strike > 0 and underlying_price > 0
        else None
    )
    otm_pct = _otm_pct(
        option_type=option_type,
        strike=strike,
        underlying_price=underlying_price,
    )
    half_spread = rel_spread / 2.0 if rel_spread is not None else None
    premium_pct_spot = (
        mid / underlying_price if mid is not None and underlying_price > 0 else None
    )
    near_spot_depth = near_spot_depth_by_key.get(
        (str(expiration_value), option_type),
        0,
    )
    flags = _quote_flags(
        bid=bid,
        ask=ask,
        mid=mid,
        rel_spread=rel_spread,
        open_interest=open_interest,
        implied_volatility=implied_volatility,
        settings=settings,
    )
    tier = _liquidity_tier(
        bid=bid,
        ask=ask,
        mid=mid,
        rel_spread=rel_spread,
        open_interest=open_interest,
        settings=settings,
    )
    score = _liquidity_score(
        rel_spread=rel_spread,
        mid=mid,
        open_interest=open_interest,
        volume=volume,
        near_spot_depth=near_spot_depth,
        settings=settings,
    )
    return OptionContractMetrics(
        ticker=ticker,
        option_type=option_type,
        expiration=expiration,
        days_to_expiry=days_to_expiry,
        strike=strike,
        underlying_price=underlying_price,
        bid=bid,
        ask=ask,
        mid=mid,
        last_price=as_float(row.get("last_price")),
        open_interest=open_interest,
        volume=volume,
        implied_volatility=implied_volatility,
        delta=delta,
        rel_spread=rel_spread,
        half_spread_cost_pct=half_spread,
        moneyness_pct=moneyness_pct,
        otm_pct=otm_pct,
        premium_pct_spot=premium_pct_spot,
        near_spot_depth_count=near_spot_depth,
        liquidity_score=score,
        liquidity_tier=tier,
        quote_flags=tuple(flags),
        is_standard_monthly=_is_standard_monthly(expiration_value),
    )


def _slot_for_bucket(
    *,
    option_type: OptionSideType,
    ticker: str,
    horizon_days: int,
    bucket: OptionBucket,
    metrics: tuple[OptionContractMetrics, ...],
    settings: OptionLiquiditySettings,
    listed_contract_count: int,
) -> OptionCandidateSlot:
    if not metrics:
        return _empty_bucket_slot(
            ticker=ticker,
            option_type=option_type,
            horizon_days=horizon_days,
            bucket=bucket,
            status="no_expiration",
            reason="No listed expiry is available inside this DTE band.",
        )
    strict_candidates = _rank_slot_candidates(
        bucket=bucket,
        metrics=metrics,
        horizon_days=horizon_days,
        settings=settings,
        pass_type="strict",
    )
    if strict_candidates:
        metric = strict_candidates[0]
        candidate = _candidate_from_metric(
            metric,
            horizon_days=horizon_days,
            bucket=bucket,
            settings=settings,
            liquidity_tier="tradable",
        )
        return OptionCandidateSlot(
            ticker=ticker,
            option_type=option_type,
            horizon_days=horizon_days,
            target_delta=_target_delta(option_type, bucket),
            expiration=candidate.expiration,
            days_to_expiry=candidate.days_to_expiry,
            status="accepted",
            reason=_accepted_reason(metric, bucket=bucket),
            candidate=candidate,
            listed_contract_count=listed_contract_count,
            tradable_contract_count=sum(
                1
                for item in metrics
                if _passes_slot_liquidity(
                    item,
                    bucket=bucket,
                    settings=settings,
                    pass_type="strict",
                )
            ),
            bucket=bucket,
            liquidity_tier="tradable",
        )

    watch_candidates = _rank_slot_candidates(
        bucket=bucket,
        metrics=metrics,
        horizon_days=horizon_days,
        settings=settings,
        pass_type="watch",
    )
    if watch_candidates:
        metric = watch_candidates[0]
        candidate = _candidate_from_metric(
            metric,
            horizon_days=horizon_days,
            bucket=bucket,
            settings=settings,
            liquidity_tier="watch",
        )
        return OptionCandidateSlot(
            ticker=ticker,
            option_type=option_type,
            horizon_days=horizon_days,
            target_delta=_target_delta(option_type, bucket),
            expiration=candidate.expiration,
            days_to_expiry=candidate.days_to_expiry,
            status="accepted",
            reason=_watch_reason(metric, bucket=bucket),
            candidate=candidate,
            listed_contract_count=listed_contract_count,
            tradable_contract_count=0,
            bucket=bucket,
            liquidity_tier="watch",
        )

    return _empty_bucket_slot(
        ticker=ticker,
        option_type=option_type,
        horizon_days=horizon_days,
        bucket=bucket,
        status="no_tradable",
        reason=_no_candidate_reason(bucket=bucket),
        listed_contract_count=listed_contract_count,
        expiration=_representative_expiration(metrics, horizon_days=horizon_days),
        days_to_expiry=_representative_days_to_expiry(metrics, horizon_days=horizon_days),
    )


def _rank_slot_candidates(
    *,
    bucket: OptionBucket,
    metrics: tuple[OptionContractMetrics, ...],
    horizon_days: int,
    settings: OptionLiquiditySettings,
    pass_type: Literal["strict", "watch"],
) -> list[OptionContractMetrics]:
    scored: list[tuple[float, OptionContractMetrics]] = []
    for metric in metrics:
        if not _bucket_fit(
            bucket=bucket,
            metric=metric,
            settings=settings,
        ):
            continue
        if not _passes_slot_liquidity(
            metric,
            bucket=bucket,
            settings=settings,
            pass_type=pass_type,
        ):
            continue
        scored.append(
            (
                _slot_fit_score(
                    metric=metric,
                    bucket=bucket,
                    horizon_days=horizon_days,
                    settings=settings,
                    pass_type=pass_type,
                ),
                metric,
            )
        )
    scored.sort(
        key=lambda item: (
            -item[0],
            abs(item[1].days_to_expiry - horizon_days),
            item[1].strike,
        )
    )
    return [metric for _, metric in scored]


def _passes_slot_liquidity(
    metric: OptionContractMetrics,
    *,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
    pass_type: Literal["strict", "watch"],
) -> bool:
    thresholds = _slot_thresholds(bucket=bucket, settings=settings, pass_type=pass_type)
    return (
        metric.bid is not None
        and metric.ask is not None
        and metric.mid is not None
        and metric.bid > 0
        and metric.ask > 0
        and metric.mid >= thresholds.min_mid
        and metric.rel_spread is not None
        and metric.rel_spread <= thresholds.max_spread_pct
        and metric.open_interest >= thresholds.min_open_interest
        and _iv_is_usable(metric, settings)
    )


def _slot_thresholds(
    *,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
    pass_type: Literal["strict", "watch"],
) -> SlotLiquidityThresholds:
    if bucket == "near_atm":
        if pass_type == "strict":
            return SlotLiquidityThresholds(
                max_spread_pct=settings.near_atm_strict_max_spread_pct,
                min_open_interest=settings.near_atm_strict_min_open_interest,
                min_mid=settings.near_atm_strict_min_mid,
            )
        return SlotLiquidityThresholds(
            max_spread_pct=settings.near_atm_watch_max_spread_pct,
            min_open_interest=settings.near_atm_watch_min_open_interest,
            min_mid=settings.near_atm_watch_min_mid,
        )
    if pass_type == "strict":
        return SlotLiquidityThresholds(
            max_spread_pct=settings.directional_strict_max_spread_pct,
            min_open_interest=settings.directional_strict_min_open_interest,
            min_mid=settings.directional_strict_min_mid,
        )
    return SlotLiquidityThresholds(
        max_spread_pct=settings.directional_watch_max_spread_pct,
        min_open_interest=settings.directional_watch_min_open_interest,
        min_mid=settings.directional_watch_min_mid,
    )


def _slot_fit_score(
    *,
    metric: OptionContractMetrics,
    bucket: OptionBucket,
    horizon_days: int,
    settings: OptionLiquiditySettings,
    pass_type: Literal["strict", "watch"],
) -> float:
    thresholds = _slot_thresholds(bucket=bucket, settings=settings, pass_type=pass_type)
    spread_score = (
        _clamp(1.0 - (metric.rel_spread or thresholds.max_spread_pct) / thresholds.max_spread_pct)
        if thresholds.max_spread_pct > 0
        else 0.0
    )
    otm_score = _otm_fit_score(metric=metric, bucket=bucket, settings=settings)
    oi_score = _log_score(metric.open_interest, settings.oi_cap)
    volume_score = _log_score(metric.volume, settings.volume_cap)
    lower, upper = settings.band_for_horizon(horizon_days)
    max_dte_distance = max(abs(horizon_days - lower), abs(upper - horizon_days), 1)
    dte_score = _clamp(1.0 - abs(metric.days_to_expiry - horizon_days) / max_dte_distance)
    monthly_score = 1.0 if metric.is_standard_monthly else 0.0
    return (
        0.35 * spread_score
        + 0.25 * otm_score
        + 0.20 * oi_score
        + 0.10 * dte_score
        + 0.05 * volume_score
        + 0.05 * monthly_score
    )


def _otm_fit_score(
    *,
    metric: OptionContractMetrics,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
) -> float:
    if metric.otm_pct is None:
        return 0.0
    if bucket == "near_atm":
        midpoint = (settings.near_atm_otm_min + settings.near_atm_otm_max) / 2.0
        half_width = max((settings.near_atm_otm_max - settings.near_atm_otm_min) / 2.0, 0.001)
        return _clamp(1.0 - abs(metric.otm_pct - midpoint) / half_width)

    if (
        settings.directional_preferred_otm_min
        <= metric.otm_pct
        <= settings.directional_preferred_otm_max
    ):
        return 1.0
    if metric.otm_pct < settings.directional_preferred_otm_min:
        width = max(
            settings.directional_preferred_otm_min
            - settings.directional_allowed_otm_min,
            0.001,
        )
        return _clamp((metric.otm_pct - settings.directional_allowed_otm_min) / width)
    width = max(
        settings.directional_allowed_otm_max
        - settings.directional_preferred_otm_max,
        0.001,
    )
    return _clamp((settings.directional_allowed_otm_max - metric.otm_pct) / width)


def _bucket_fit(
    *,
    bucket: OptionBucket,
    metric: OptionContractMetrics,
    settings: OptionLiquiditySettings,
) -> bool:
    if metric.otm_pct is None:
        return False
    if bucket == "near_atm":
        return (
            settings.near_atm_otm_min
            <= metric.otm_pct
            <= settings.near_atm_otm_max
        )
    if bucket == "directional":
        return (
            settings.directional_allowed_otm_min
            <= metric.otm_pct
            <= settings.directional_allowed_otm_max
        )
    return False


def _candidate_from_metric(
    metric: OptionContractMetrics,
    *,
    horizon_days: int,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
    liquidity_tier: OptionLiquidityTier | None = None,
) -> OptionCandidate:
    delta_gap = None
    target_delta = _target_delta(metric.option_type, bucket)
    if metric.delta is not None:
        delta_gap = abs(metric.delta - target_delta)
    return OptionCandidate(
        ticker=metric.ticker,
        horizon_days=horizon_days,
        expiration=metric.expiration,
        days_to_expiry=metric.days_to_expiry,
        strike=metric.strike,
        bid=metric.bid,
        ask=metric.ask,
        mid=metric.mid,
        last_price=metric.last_price,
        open_interest=metric.open_interest,
        volume=metric.volume,
        implied_volatility=metric.implied_volatility,
        delta=metric.delta,
        delta_gap=delta_gap,
        premium_pct_spot=metric.premium_pct_spot,
        underlying_price=metric.underlying_price,
        option_type=metric.option_type,
        bucket=bucket,
        liquidity_tier=liquidity_tier or metric.liquidity_tier,
        rel_spread=metric.rel_spread,
        half_spread_cost_pct=metric.half_spread_cost_pct,
        liquidity_score=metric.liquidity_score,
        moneyness_pct=metric.moneyness_pct,
        otm_pct=metric.otm_pct,
        quote_flags=_candidate_quote_flags(metric, bucket=bucket, settings=settings),
    )


def _empty_bucket_slot(
    *,
    ticker: str,
    option_type: OptionSideType,
    horizon_days: int,
    bucket: OptionBucket,
    status: CandidateSlotStatus,
    reason: str,
    listed_contract_count: int = 0,
    expiration: str | None = None,
    days_to_expiry: int | None = None,
) -> OptionCandidateSlot:
    return OptionCandidateSlot(
        ticker=ticker,
        option_type=option_type,
        horizon_days=horizon_days,
        target_delta=_target_delta(option_type, bucket),
        expiration=expiration,
        days_to_expiry=days_to_expiry,
        status=status,
        reason=reason,
        listed_contract_count=listed_contract_count,
        bucket=bucket,
        liquidity_tier=None,
    )


def _representative_expiration(
    metrics: tuple[OptionContractMetrics, ...],
    *,
    horizon_days: int,
) -> str | None:
    metric = _representative_metric(metrics, horizon_days=horizon_days)
    return metric.expiration if metric is not None else None


def _representative_days_to_expiry(
    metrics: tuple[OptionContractMetrics, ...],
    *,
    horizon_days: int,
) -> int | None:
    metric = _representative_metric(metrics, horizon_days=horizon_days)
    return metric.days_to_expiry if metric is not None else None


def _representative_metric(
    metrics: tuple[OptionContractMetrics, ...],
    *,
    horizon_days: int,
) -> OptionContractMetrics | None:
    if not metrics:
        return None
    return min(
        metrics,
        key=lambda metric: (
            abs(metric.days_to_expiry - horizon_days),
            -metric.liquidity_score,
        ),
    )


def _relative_spread(
    *,
    bid: float | None,
    ask: float | None,
    mid: float | None,
) -> float | None:
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0 or mid <= 0:
        return None
    return (ask - bid) / mid


def _liquidity_tier(
    *,
    bid: float | None,
    ask: float | None,
    mid: float | None,
    rel_spread: float | None,
    open_interest: int,
    settings: OptionLiquiditySettings,
) -> OptionLiquidityTier:
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0 or mid <= 0:
        return "no_trade"
    if rel_spread is None or rel_spread > settings.watch_spread_pct:
        return "no_trade"
    if open_interest < settings.min_open_interest:
        return "no_trade"
    if rel_spread <= settings.tradable_spread_pct and mid >= settings.min_premium:
        return "tradable"
    return "watch"


def _liquidity_score(
    *,
    rel_spread: float | None,
    mid: float | None,
    open_interest: int,
    volume: int,
    near_spot_depth: int,
    settings: OptionLiquiditySettings,
) -> float:
    spread_score = 0.0
    if rel_spread is not None:
        spread_score = _clamp(1.0 - rel_spread / settings.watch_spread_pct)
    oi_score = _log_score(open_interest, settings.oi_cap)
    premium_score = 0.0
    if mid is not None and mid > 0:
        premium_score = 1.0 if mid >= settings.min_premium else mid / settings.min_premium
    depth_score = _clamp(near_spot_depth / settings.target_depth_count)
    volume_score = _log_score(volume, settings.volume_cap)
    return (
        0.55 * spread_score
        + 0.25 * oi_score
        + 0.10 * premium_score
        + 0.05 * depth_score
        + 0.05 * volume_score
    )


def _near_spot_depth_counts(
    *,
    frame: pd.DataFrame,
    underlying_price: float,
    settings: OptionLiquiditySettings,
) -> dict[tuple[str, OptionSideType], int]:
    if underlying_price <= 0:
        return {}
    counts: dict[tuple[str, OptionSideType], int] = {}
    for _, row in frame.iterrows():
        strike = as_float(row.get("strike"))
        bid = as_float(row.get("bid"))
        ask = as_float(row.get("ask"))
        mid = as_float(row.get("mid"))
        if (
            strike is None
            or abs(strike - underlying_price) / underlying_price > settings.near_spot_pct
        ):
            continue
        if (
            bid is not None
            and ask is not None
            and mid is not None
            and bid > 0
            and ask > 0
            and mid > 0
        ):
            option_type = _normalize_option_type(str(row.get("option_type", "")))
            key = (str(row.get("expiration")), option_type)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _quote_flags(
    *,
    bid: float | None,
    ask: float | None,
    mid: float | None,
    rel_spread: float | None,
    open_interest: int,
    implied_volatility: float | None,
    settings: OptionLiquiditySettings,
) -> list[str]:
    flags: list[str] = []
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0 or mid <= 0:
        flags.append("invalid_quote")
    if rel_spread is not None and rel_spread > settings.tradable_spread_pct:
        flags.append("wide_spread")
    if rel_spread is not None and rel_spread > settings.watch_spread_pct:
        flags.append("too_wide_to_watch")
    if open_interest < settings.min_open_interest:
        flags.append("low_open_interest")
    if mid is not None and 0 < mid < settings.min_premium:
        flags.append("sub_min_premium")
    if not _iv_value_is_usable(implied_volatility, settings):
        flags.append("unusable_iv")
    return flags


def _iv_is_usable(
    metric: OptionContractMetrics,
    settings: OptionLiquiditySettings,
) -> bool:
    return _iv_value_is_usable(metric.implied_volatility, settings)


def _iv_value_is_usable(
    implied_volatility: float | None,
    settings: OptionLiquiditySettings,
) -> bool:
    return (
        implied_volatility is not None
        and settings.min_implied_volatility <= implied_volatility <= settings.max_implied_volatility
    )


def _otm_pct(
    *,
    option_type: OptionSideType,
    strike: float,
    underlying_price: float,
) -> float | None:
    if strike <= 0 or underlying_price <= 0:
        return None
    if option_type == "P":
        if strike >= underlying_price:
            return None
        return (underlying_price - strike) / underlying_price
    if strike <= underlying_price:
        return None
    return (strike - underlying_price) / underlying_price


def _candidate_quote_flags(
    metric: OptionContractMetrics,
    *,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
) -> tuple[str, ...]:
    flags = list(metric.quote_flags)
    if _is_lottery_like(metric, bucket=bucket, settings=settings):
        flags.append("lottery_like")
    return tuple(dict.fromkeys(flags))


def _is_lottery_like(
    metric: OptionContractMetrics,
    *,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
) -> bool:
    return (
        bucket == "directional"
        and metric.days_to_expiry <= settings.lottery_dte_max
        and metric.implied_volatility is not None
        and metric.implied_volatility >= settings.lottery_iv_threshold
        and metric.delta is not None
        and abs(metric.delta) <= settings.lottery_abs_delta_max
    )


def _accepted_reason(metric: OptionContractMetrics, *, bucket: OptionBucket) -> str:
    spread = _format_percent(metric.rel_spread)
    return (
        f"{bucket_label(bucket)} candidate passed the strict liquidity checks "
        f"with spread {spread}."
    )


def _watch_reason(metric: OptionContractMetrics, *, bucket: OptionBucket) -> str:
    spread = _format_percent(metric.rel_spread)
    return (
        f"{bucket_label(bucket)} candidate passed the relaxed liquidity checks "
        f"with spread {spread}. Watch: wide spreads mean the midpoint may be optimistic."
    )


def _no_candidate_reason(*, bucket: OptionBucket) -> str:
    if bucket == "near_atm":
        return "No liquid candidate in the 0-5% OTM range passed the cached checks."
    return "No liquid candidate in the 12-22% OTM range passed the cached checks."


def _target_delta(option_type: OptionSideType, bucket: OptionBucket) -> float:
    if bucket == "directional":
        return 0.425 if option_type == "C" else -0.425
    return 0.0


def _buckets_for_side() -> tuple[OptionBucket, ...]:
    return CANDIDATE_BUCKETS


def _is_standard_monthly(value: object) -> bool:
    expiration = pd.to_datetime(value, errors="coerce")
    if pd.isna(expiration):
        return False
    expiry_date = expiration.date()
    return expiry_date.weekday() == 4 and 15 <= expiry_date.day <= 21


def _normalize_option_type(option_type: str) -> OptionSideType:
    normalized = option_type.strip().upper()
    if normalized not in {"P", "C"}:
        raise ValueError(f"Unsupported option type: {option_type}")
    return cast(OptionSideType, normalized)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _log_score(value: int, cap: int) -> float:
    if value <= 0 or cap <= 0:
        return 0.0
    return min(math.log1p(value) / math.log1p(cap), 1.0)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"
