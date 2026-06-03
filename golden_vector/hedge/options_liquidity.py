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
OptionBucket = Literal["most_liquid", "near_atm", "directional", "tail", "model_fit"]
OptionSideType = Literal["P", "C"]

BUCKET_LABELS: dict[str, str] = {
    "most_liquid": "Most liquid",
    "near_atm": "Near-ATM",
    "directional": "Directional",
    "tail": "Tail",
    "model_fit": "Model fit",
}

DIRECTIONAL_CALL_DELTA = (0.35, 0.50)
DIRECTIONAL_PUT_DELTA = (-0.50, -0.35)
TAIL_PUT_DELTA = (-0.30, -0.15)
MODEL_FIT_GOLD_MOVE = {"P": -0.10, "C": 0.10}


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

    def band_for_horizon(self, horizon_days: int) -> tuple[int, int]:
        bands = self.dte_bands or {
            30: (21, 45),
            60: (46, 75),
            90: (76, 105),
            120: (106, 150),
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
    metrics = tuple(
        _metric_from_row(
            ticker=ticker,
            row=row,
            frame=frame,
            underlying_price=underlying_price,
            settings=settings,
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
    gold_beta: float | None = None,
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
    if not scan.metrics:
        return [
            _empty_bucket_slot(
                ticker=ticker,
                option_type=normalized_type,
                horizon_days=horizon,
                bucket=bucket,
                status="no_chain",
                reason="No listed options chain is available in the cached snapshot.",
            )
            for horizon in target_horizons_days
            for bucket in _buckets_for_side(normalized_type)
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
        for bucket in _buckets_for_side(normalized_type):
            slots.append(
                _slot_for_bucket(
                    option_type=normalized_type,
                    ticker=ticker,
                    horizon_days=horizon,
                    bucket=bucket,
                    metrics=horizon_metrics,
                    underlying_price=underlying_price,
                    settings=settings,
                    gold_beta=gold_beta,
                    listed_contract_count=len(horizon_metrics),
                )
            )
    return slots


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
    frame: pd.DataFrame,
    underlying_price: float,
    settings: OptionLiquiditySettings,
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
    half_spread = rel_spread / 2.0 if rel_spread is not None else None
    premium_pct_spot = (
        mid / underlying_price if mid is not None and underlying_price > 0 else None
    )
    near_spot_depth = _near_spot_depth_count(
        frame=frame,
        expiration=expiration_value,
        option_type=option_type,
        underlying_price=underlying_price,
        settings=settings,
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
    underlying_price: float,
    settings: OptionLiquiditySettings,
    gold_beta: float | None,
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
    ranked = _rank_bucket_metrics(
        option_type=option_type,
        bucket=bucket,
        metrics=metrics,
        horizon_days=horizon_days,
        underlying_price=underlying_price,
        settings=settings,
        gold_beta=gold_beta,
    )
    if not ranked:
        return _empty_bucket_slot(
            ticker=ticker,
            option_type=option_type,
            horizon_days=horizon_days,
            bucket=bucket,
            status="no_tradable",
            reason=(
                f"No sensible liquid contract for the {bucket_label(bucket)} bucket."
            ),
            listed_contract_count=listed_contract_count,
        )
    tradable = [
        metric
        for metric, bucket_fit in ranked
        if is_usable_candidate(metric, bucket_fit=bucket_fit, settings=settings)
    ]
    if tradable:
        metric = tradable[0]
        candidate = _candidate_from_metric(
            metric,
            horizon_days=horizon_days,
            bucket=bucket,
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
            tradable_contract_count=sum(1 for metric in metrics if metric.liquidity_tier == "tradable"),
            bucket=bucket,
            liquidity_tier=metric.liquidity_tier,
        )

    metric, _ = ranked[0]
    rejected = _candidate_from_metric(
        metric,
        horizon_days=horizon_days,
        bucket=bucket,
    )
    return OptionCandidateSlot(
        ticker=ticker,
        option_type=option_type,
        horizon_days=horizon_days,
        target_delta=_target_delta(option_type, bucket),
        expiration=rejected.expiration,
        days_to_expiry=rejected.days_to_expiry,
        status="rejected",
        reason=_near_miss_reason(metric, bucket=bucket, settings=settings),
        rejected_candidate=rejected,
        listed_contract_count=listed_contract_count,
        tradable_contract_count=sum(1 for metric in metrics if metric.liquidity_tier == "tradable"),
        bucket=bucket,
        liquidity_tier=metric.liquidity_tier,
    )


def _rank_bucket_metrics(
    *,
    option_type: OptionSideType,
    bucket: OptionBucket,
    metrics: tuple[OptionContractMetrics, ...],
    horizon_days: int,
    underlying_price: float,
    settings: OptionLiquiditySettings,
    gold_beta: float | None,
) -> list[tuple[OptionContractMetrics, bool]]:
    scored: list[tuple[OptionContractMetrics, bool, tuple[float, ...]]] = []
    target_price = _model_fit_target_price(
        option_type=option_type,
        underlying_price=underlying_price,
        gold_beta=gold_beta,
    )
    for metric in metrics:
        bucket_fit = _bucket_fit(
            option_type=option_type,
            bucket=bucket,
            metric=metric,
            settings=settings,
            target_price=target_price,
        )
        if bucket == "model_fit" and target_price is None:
            continue
        if not _sensible_moneyness(metric, settings) and bucket != "model_fit":
            bucket_fit = False
        if bucket_fit or metric.liquidity_tier != "no_trade":
            scored.append(
                (
                    metric,
                    bucket_fit,
                    _bucket_sort_key(
                        bucket=bucket,
                        metric=metric,
                        bucket_fit=bucket_fit,
                        horizon_days=horizon_days,
                        target_price=target_price,
                    ),
                )
            )
    scored.sort(key=lambda item: item[2])
    return [(metric, bucket_fit) for metric, bucket_fit, _ in scored]


def _bucket_sort_key(
    *,
    bucket: OptionBucket,
    metric: OptionContractMetrics,
    bucket_fit: bool,
    horizon_days: int,
    target_price: float | None,
) -> tuple[float, ...]:
    tier_rank = {"tradable": 0.0, "watch": 1.0, "no_trade": 2.0}[metric.liquidity_tier]
    monthly_rank = 0.0 if metric.is_standard_monthly else 1.0
    dte_distance = abs(metric.days_to_expiry - horizon_days)
    if bucket == "near_atm":
        primary = metric.moneyness_pct if metric.moneyness_pct is not None else 99.0
    elif bucket == "directional":
        target = 0.425 if metric.option_type == "C" else -0.425
        primary = abs((metric.delta if metric.delta is not None else 99.0) - target)
    elif bucket == "tail":
        primary = abs((metric.delta if metric.delta is not None else 99.0) - -0.225)
    elif bucket == "model_fit" and target_price is not None:
        primary = abs(metric.strike - target_price)
    else:
        primary = -metric.liquidity_score
    return (
        0.0 if bucket_fit else 1.0,
        tier_rank,
        primary,
        monthly_rank,
        -metric.liquidity_score,
        float(dte_distance),
        metric.strike,
    )


def _bucket_fit(
    *,
    option_type: OptionSideType,
    bucket: OptionBucket,
    metric: OptionContractMetrics,
    settings: OptionLiquiditySettings,
    target_price: float | None,
) -> bool:
    if not _sensible_moneyness(metric, settings):
        return False
    if bucket in {"most_liquid", "near_atm"}:
        return True
    if bucket == "directional":
        return _delta_in_range(
            metric.delta,
            DIRECTIONAL_CALL_DELTA if option_type == "C" else DIRECTIONAL_PUT_DELTA,
        )
    if bucket == "tail":
        return option_type == "P" and _delta_in_range(metric.delta, TAIL_PUT_DELTA)
    if bucket == "model_fit":
        return target_price is not None
    return False


def _candidate_from_metric(
    metric: OptionContractMetrics,
    *,
    horizon_days: int,
    bucket: OptionBucket,
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
        liquidity_tier=metric.liquidity_tier,
        rel_spread=metric.rel_spread,
        half_spread_cost_pct=metric.half_spread_cost_pct,
        liquidity_score=metric.liquidity_score,
        moneyness_pct=metric.moneyness_pct,
        quote_flags=metric.quote_flags,
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
) -> OptionCandidateSlot:
    return OptionCandidateSlot(
        ticker=ticker,
        option_type=option_type,
        horizon_days=horizon_days,
        target_delta=_target_delta(option_type, bucket),
        expiration=None,
        days_to_expiry=None,
        status=status,
        reason=reason,
        listed_contract_count=listed_contract_count,
        bucket=bucket,
        liquidity_tier=None,
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


def _near_spot_depth_count(
    *,
    frame: pd.DataFrame,
    expiration: object,
    option_type: OptionSideType,
    underlying_price: float,
    settings: OptionLiquiditySettings,
) -> int:
    if underlying_price <= 0:
        return 0
    subset = frame[
        (frame["expiration"] == expiration)
        & (frame["option_type"].astype(str).str.upper() == option_type)
    ]
    count = 0
    for _, row in subset.iterrows():
        strike = as_float(row.get("strike"))
        bid = as_float(row.get("bid"))
        ask = as_float(row.get("ask"))
        mid = as_float(row.get("mid"))
        if strike is None or abs(strike - underlying_price) / underlying_price > settings.near_spot_pct:
            continue
        if bid is not None and ask is not None and mid is not None and bid > 0 and ask > 0 and mid > 0:
            count += 1
    return count


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


def _sensible_moneyness(
    metric: OptionContractMetrics,
    settings: OptionLiquiditySettings,
) -> bool:
    return (
        metric.moneyness_pct is not None
        and metric.moneyness_pct <= settings.sensible_moneyness_max_pct
    )


def _accepted_reason(metric: OptionContractMetrics, *, bucket: OptionBucket) -> str:
    spread = _format_percent(metric.rel_spread)
    half_spread = _format_percent(metric.half_spread_cost_pct)
    return (
        f"{bucket_label(bucket)} bucket has a sensible liquid contract: "
        f"{metric.liquidity_tier.replace('_', '-')} tier, spread {spread}, "
        f"half-spread cost {half_spread}."
    )


def _near_miss_reason(
    metric: OptionContractMetrics,
    *,
    bucket: OptionBucket,
    settings: OptionLiquiditySettings,
) -> str:
    problems: list[str] = []
    if metric.liquidity_tier != "tradable":
        problems.append(f"tier is {metric.liquidity_tier.replace('_', '-')}")
    if not _sensible_moneyness(metric, settings):
        problems.append("strike is too far from the cached stock price")
    if not _iv_is_usable(metric, settings):
        problems.append("IV is missing or outside configured bounds")
    if metric.quote_flags:
        problems.append(", ".join(flag.replace("_", " ") for flag in metric.quote_flags))
    detail = "; ".join(dict.fromkeys(problems)) or "it did not pass all gates"
    return (
        f"No sensible liquid contract for the {bucket_label(bucket)} bucket. "
        f"Nearest visible contract is shown for context, but {detail}."
    )


def _target_delta(option_type: OptionSideType, bucket: OptionBucket) -> float:
    if bucket == "directional":
        return 0.425 if option_type == "C" else -0.425
    if bucket == "tail":
        return -0.225
    return 0.0


def _model_fit_target_price(
    *,
    option_type: OptionSideType,
    underlying_price: float,
    gold_beta: float | None,
) -> float | None:
    if gold_beta is None or underlying_price <= 0:
        return None
    gold_move = MODEL_FIT_GOLD_MOVE[option_type]
    return max(0.01, underlying_price * (1.0 + gold_beta * gold_move))


def _buckets_for_side(option_type: OptionSideType) -> tuple[OptionBucket, ...]:
    if option_type == "P":
        return ("most_liquid", "near_atm", "directional", "tail", "model_fit")
    return ("most_liquid", "near_atm", "directional", "model_fit")


def _delta_in_range(value: float | None, bounds: tuple[float, float]) -> bool:
    if value is None:
        return False
    lower, upper = bounds
    return lower <= value <= upper


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
