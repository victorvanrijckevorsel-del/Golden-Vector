"""Candidate put selection for hedge-readiness reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

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
    option_type: Literal["P", "C"] = "P"


CandidatePut = OptionCandidate


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
    as_of_date: date | None = None,
) -> list[OptionCandidate]:
    """Return tradable listed options nearest target delta for each horizon."""

    normalized_type = option_type.upper()
    if normalized_type not in {"P", "C"}:
        raise ValueError(f"Unsupported option type: {option_type}")
    effective_target_delta = (
        target_delta
        if target_delta is not None
        else (-0.25 if normalized_type == "P" else 0.25)
    )

    frame = normalize_options_chain(chain, as_of_date=as_of_date)
    if frame.empty:
        return []

    candidates: list[OptionCandidate] = []
    for horizon in target_horizons_days:
        expiry = nearest_expiration(frame, horizon)
        if expiry is None:
            continue
        expiry_slice = frame[
            (frame["expiration"] == expiry) & (frame["option_type"] == normalized_type)
        ].copy()
        if expiry_slice.empty:
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
            continue
        selected = strike_for_target_delta(
            option_type=normalized_type,
            target_delta=effective_target_delta,
            chain_slice=tradable_slice,
        )
        if selected is None:
            continue
        candidate = _candidate_from_result(
            option_type=normalized_type,
            ticker=ticker,
            horizon_days=horizon,
            result=selected,
            underlying_price=underlying_price,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


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
        open_interest=as_int(result.get("open_interest")),
        volume=as_int(result.get("volume")),
        implied_volatility=as_float(result.get("implied_volatility")),
        delta=as_float(result.get("delta")),
        delta_gap=as_float(result.get("delta_gap")),
        premium_pct_spot=(mid / underlying_price) if mid is not None and underlying_price > 0 else None,
        underlying_price=underlying_price,
        option_type=option_type,
    )
