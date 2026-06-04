"""Listed option candidate selection for hedge-readiness reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, cast

import pandas as pd

from golden_vector.features.black_scholes import strike_for_target_delta
from golden_vector.features.options_chain import (
    add_black_scholes_delta,
    as_float,
    as_int,
    nearest_expiration,
    normalize_options_chain,
    option_quote_is_tradable,
)

CandidateSlotStatus = Literal[
    "accepted",
    "rejected",
    "no_chain",
    "no_price",
    "no_expiration",
    "no_contracts",
    "no_tradable",
    "no_delta",
]


@dataclass(frozen=True)
class OptionCandidate:
    ticker: str
    horizon_days: int
    expiration: str
    days_to_expiry: int
    strike: float
    bid: float | None
    ask: float | None
    mid: float | None
    open_interest: int | None
    volume: int | None
    implied_volatility: float | None
    delta: float | None
    delta_gap: float | None
    premium_pct_spot: float | None
    underlying_price: float
    last_price: float | None = None
    option_type: Literal["P", "C"] = "P"
    bucket: str | None = None
    liquidity_tier: str | None = None
    rel_spread: float | None = None
    half_spread_cost_pct: float | None = None
    liquidity_score: float | None = None
    moneyness_pct: float | None = None
    otm_pct: float | None = None
    quote_flags: tuple[str, ...] = ()


CandidatePut = OptionCandidate


@dataclass(frozen=True)
class OptionCandidateSlot:
    ticker: str
    option_type: Literal["P", "C"]
    horizon_days: int
    target_delta: float
    expiration: str | None
    days_to_expiry: int | None
    status: CandidateSlotStatus
    reason: str
    candidate: OptionCandidate | None = None
    rejected_candidate: OptionCandidate | None = None
    listed_contract_count: int = 0
    tradable_contract_count: int = 0
    bucket: str | None = None
    liquidity_tier: str | None = None

    @property
    def display_candidate(self) -> OptionCandidate | None:
        return self.candidate or self.rejected_candidate


def build_candidate_grid(
    *,
    option_type: Literal["P", "C"],
    ticker: str,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    target_delta: float | None = None,
    max_spread_pct: float = 0.35,
    min_open_interest: int = 1,
    min_volume: int = 0,
    min_implied_volatility: float = 0.01,
    max_implied_volatility: float = 3.0,
    max_delta_gap: float | None = None,
    as_of_date: date | None = None,
) -> list[OptionCandidate]:
    """Return tradable listed options nearest target delta for each horizon."""

    return [
        slot.candidate
        for slot in build_candidate_slots(
            option_type=option_type,
            ticker=ticker,
            chain=chain,
            underlying_price=underlying_price,
            risk_free_rate=risk_free_rate,
            target_horizons_days=target_horizons_days,
            target_delta=target_delta,
            max_spread_pct=max_spread_pct,
            min_open_interest=min_open_interest,
            min_volume=min_volume,
            min_implied_volatility=min_implied_volatility,
            max_implied_volatility=max_implied_volatility,
            max_delta_gap=max_delta_gap,
            as_of_date=as_of_date,
        )
        if slot.candidate is not None
    ]


def build_candidate_slots(
    *,
    option_type: Literal["P", "C"],
    ticker: str,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    target_delta: float | None = None,
    max_spread_pct: float = 0.35,
    min_open_interest: int = 1,
    min_volume: int = 0,
    min_implied_volatility: float = 0.01,
    max_implied_volatility: float = 3.0,
    max_delta_gap: float | None = None,
    as_of_date: date | None = None,
) -> list[OptionCandidateSlot]:
    """Return one candidate slot per horizon, including rejected/missing reasons."""

    normalized_type_raw = str(option_type).strip().upper()
    if normalized_type_raw not in {"P", "C"}:
        raise ValueError(f"Unsupported option type: {option_type}")
    normalized_type = cast(Literal["P", "C"], normalized_type_raw)
    effective_target_delta = (
        target_delta
        if target_delta is not None
        else (-0.25 if normalized_type == "P" else 0.25)
    )

    frame = normalize_options_chain(chain, as_of_date=as_of_date)
    if frame.empty:
        return [
            _empty_slot(
                ticker=ticker,
                option_type=normalized_type,
                horizon_days=horizon,
                target_delta=float(effective_target_delta),
                status="no_chain",
                reason="No listed options chain is available in the cached snapshot.",
            )
            for horizon in target_horizons_days
        ]

    slots: list[OptionCandidateSlot] = []
    for horizon in target_horizons_days:
        expiry = nearest_expiration(frame, horizon)
        if expiry is None:
            slots.append(
                _empty_slot(
                    ticker=ticker,
                    option_type=normalized_type,
                    horizon_days=horizon,
                    target_delta=float(effective_target_delta),
                    status="no_expiration",
                    reason="No listed expiry is available near this horizon.",
                )
            )
            continue
        expiry_slice = frame[
            (frame["expiration"] == expiry) & (frame["option_type"] == normalized_type)
        ].copy()
        expiration = str(expiry)
        days_to_expiry = _slice_days_to_expiry(expiry_slice)
        if expiry_slice.empty:
            slots.append(
                _empty_slot(
                    ticker=ticker,
                    option_type=normalized_type,
                    horizon_days=horizon,
                    target_delta=float(effective_target_delta),
                    status="no_contracts",
                    reason=(
                        f"No listed {_option_label(normalized_type)} contracts "
                        f"are available for {expiration}."
                    ),
                    expiration=expiration,
                    days_to_expiry=days_to_expiry,
                )
            )
            continue
        expiry_slice = add_black_scholes_delta(
            expiry_slice,
            underlying_price=underlying_price,
            risk_free_rate=risk_free_rate,
        )
        tradable_slice = expiry_slice[
            expiry_slice.apply(
                lambda row: option_quote_is_tradable(
                    row,
                    max_spread_pct=max_spread_pct,
                    min_open_interest=min_open_interest,
                    min_volume=min_volume,
                    min_implied_volatility=min_implied_volatility,
                    max_implied_volatility=max_implied_volatility,
                ),
                axis=1,
            )
        ].copy()
        if tradable_slice.empty:
            slots.append(
                _empty_slot(
                    ticker=ticker,
                    option_type=normalized_type,
                    horizon_days=horizon,
                    target_delta=float(effective_target_delta),
                    status="no_tradable",
                    reason=(
                        f"No {_option_label(normalized_type)} contract for {expiration} "
                        "passed the cached bid/ask, liquidity, and IV checks."
                    ),
                    expiration=expiration,
                    days_to_expiry=days_to_expiry,
                    listed_contract_count=len(expiry_slice.index),
                )
            )
            continue
        selected = strike_for_target_delta(
            option_type=normalized_type,
            target_delta=effective_target_delta,
            chain_slice=tradable_slice,
        )
        if selected is None:
            slots.append(
                _empty_slot(
                    ticker=ticker,
                    option_type=normalized_type,
                    horizon_days=horizon,
                    target_delta=float(effective_target_delta),
                    status="no_delta",
                    reason=(
                        f"No tradable {_option_label(normalized_type)} contract for "
                        f"{expiration} had a computable delta."
                    ),
                    expiration=expiration,
                    days_to_expiry=days_to_expiry,
                    listed_contract_count=len(expiry_slice.index),
                    tradable_contract_count=len(tradable_slice.index),
                )
            )
            continue
        candidate = _candidate_from_result(
            option_type=normalized_type,
            ticker=ticker,
            horizon_days=horizon,
            result=selected,
            underlying_price=underlying_price,
        )
        if candidate is None:
            slots.append(
                _empty_slot(
                    ticker=ticker,
                    option_type=normalized_type,
                    horizon_days=horizon,
                    target_delta=float(effective_target_delta),
                    status="no_delta",
                    reason=(
                        f"No tradable {_option_label(normalized_type)} contract for "
                        f"{expiration} had enough data to build a candidate."
                    ),
                    expiration=expiration,
                    days_to_expiry=days_to_expiry,
                    listed_contract_count=len(expiry_slice.index),
                    tradable_contract_count=len(tradable_slice.index),
                )
            )
            continue
        if _delta_gap_exceeds(candidate, max_delta_gap):
            slots.append(
                OptionCandidateSlot(
                    ticker=ticker,
                    option_type=normalized_type,
                    horizon_days=horizon,
                    target_delta=float(effective_target_delta),
                    expiration=candidate.expiration,
                    days_to_expiry=candidate.days_to_expiry,
                    status="rejected",
                    reason=_delta_gap_rejection_reason(
                        candidate,
                        target_delta=float(effective_target_delta),
                    ),
                    rejected_candidate=candidate,
                    listed_contract_count=len(expiry_slice.index),
                    tradable_contract_count=len(tradable_slice.index),
                )
            )
            continue
        slots.append(
            OptionCandidateSlot(
                ticker=ticker,
                option_type=normalized_type,
                horizon_days=horizon,
                target_delta=float(effective_target_delta),
                expiration=candidate.expiration,
                days_to_expiry=candidate.days_to_expiry,
                status="accepted",
                reason=_accepted_reason(candidate, target_delta=float(effective_target_delta)),
                candidate=candidate,
                listed_contract_count=len(expiry_slice.index),
                tradable_contract_count=len(tradable_slice.index),
            )
        )
    return slots


def build_candidate_put_grid(
    *,
    ticker: str,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    target_delta: float = -0.25,
    max_spread_pct: float = 0.35,
    min_open_interest: int = 1,
    min_volume: int = 0,
    min_implied_volatility: float = 0.01,
    max_implied_volatility: float = 3.0,
    max_delta_gap: float | None = None,
    as_of_date: date | None = None,
) -> list[CandidatePut]:
    """Return tradable listed puts nearest target delta for each target horizon."""

    return build_candidate_grid(
        option_type="P",
        ticker=ticker,
        chain=chain,
        underlying_price=underlying_price,
        risk_free_rate=risk_free_rate,
        target_horizons_days=target_horizons_days,
        target_delta=target_delta,
        max_spread_pct=max_spread_pct,
        min_open_interest=min_open_interest,
        min_volume=min_volume,
        min_implied_volatility=min_implied_volatility,
        max_implied_volatility=max_implied_volatility,
        max_delta_gap=max_delta_gap,
        as_of_date=as_of_date,
    )


def _candidate_from_result(
    *,
    option_type: Literal["P", "C"],
    ticker: str,
    horizon_days: int,
    result: dict[str, object],
    underlying_price: float,
) -> OptionCandidate | None:
    strike = as_float(result.get("strike"))
    expiration = result.get("expiration")
    if strike is None or expiration is None:
        return None
    mid = as_float(result.get("mid"))
    days_to_expiry = as_int(result.get("days_to_expiry"))
    if days_to_expiry is None:
        days_to_expiry = 0
    return OptionCandidate(
        ticker=ticker,
        horizon_days=horizon_days,
        expiration=str(expiration),
        days_to_expiry=days_to_expiry,
        strike=strike,
        bid=as_float(result.get("bid")),
        ask=as_float(result.get("ask")),
        mid=mid,
        last_price=as_float(result.get("last_price")),
        open_interest=as_int(result.get("open_interest")),
        volume=as_int(result.get("volume")),
        implied_volatility=as_float(result.get("implied_volatility")),
        delta=as_float(result.get("delta")),
        delta_gap=as_float(result.get("delta_gap")),
        premium_pct_spot=(
            (mid / underlying_price)
            if mid is not None and underlying_price > 0
            else None
        ),
        underlying_price=underlying_price,
        option_type=option_type,
    )


def _empty_slot(
    *,
    ticker: str,
    option_type: Literal["P", "C"],
    horizon_days: int,
    target_delta: float,
    status: CandidateSlotStatus,
    reason: str,
    expiration: str | None = None,
    days_to_expiry: int | None = None,
    listed_contract_count: int = 0,
    tradable_contract_count: int = 0,
) -> OptionCandidateSlot:
    return OptionCandidateSlot(
        ticker=ticker,
        option_type=option_type,
        horizon_days=horizon_days,
        target_delta=target_delta,
        expiration=expiration,
        days_to_expiry=days_to_expiry,
        status=status,
        reason=reason,
        listed_contract_count=listed_contract_count,
        tradable_contract_count=tradable_contract_count,
    )


def _slice_days_to_expiry(frame: pd.DataFrame) -> int | None:
    if frame.empty or "days_to_expiry" not in frame.columns:
        return None
    values = pd.to_numeric(frame["days_to_expiry"], errors="coerce").dropna()
    if values.empty:
        return None
    return int(values.iloc[0])


def _delta_gap_exceeds(candidate: OptionCandidate, max_delta_gap: float | None) -> bool:
    if max_delta_gap is None:
        return False
    if candidate.delta_gap is None:
        return True
    return candidate.delta_gap > float(max_delta_gap)


def _delta_gap_rejection_reason(
    candidate: OptionCandidate,
    *,
    target_delta: float,
) -> str:
    label = _option_label(candidate.option_type)
    delta = _format_signed(candidate.delta)
    target = _format_signed(target_delta)
    strike = f"{candidate.strike:.2f}"
    moneyness = _moneyness_phrase(candidate)
    return (
        f"No acceptable {candidate.horizon_days}d {label} candidate. "
        f"The closest tradable contract was strike {strike}, but {moneyness} "
        f"and delta {delta} is too far from target {target}."
    )


def _accepted_reason(candidate: OptionCandidate, *, target_delta: float) -> str:
    label = _option_label(candidate.option_type)
    delta = _format_signed(candidate.delta)
    target = _format_signed(target_delta)
    return (
        f"Matched as the listed {label} nearest target delta {target} "
        f"after cached liquidity checks; selected delta is {delta}."
    )


def _option_label(option_type: Literal["P", "C"]) -> str:
    return "put" if option_type == "P" else "call"


def _format_signed(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _moneyness_phrase(candidate: OptionCandidate) -> str:
    price = candidate.underlying_price
    if price <= 0:
        return "moneyness could not be computed"
    pct = abs(candidate.strike - price) / price * 100.0
    if candidate.strike < price:
        relation = "below"
    elif candidate.strike > price:
        relation = "above"
    else:
        relation = "at"
    if relation == "at":
        return "it is at the cached stock price"
    return f"it is {pct:.1f}% {relation} the cached stock price"
