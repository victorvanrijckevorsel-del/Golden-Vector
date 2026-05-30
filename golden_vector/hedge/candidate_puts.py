"""Candidate put selection for hedge-readiness reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.features.black_scholes import (
    black_scholes_delta,
    strike_for_target_delta,
)

CALENDAR_DAYS_PER_YEAR = 365.25


@dataclass(frozen=True)
class CandidatePut:
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


def build_candidate_put_grid(
    *,
    ticker: str,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    target_horizons_days: tuple[int, ...] = (30, 60, 90),
    target_delta: float = -0.25,
    as_of_date: date | None = None,
) -> list[CandidatePut]:
    """Return the listed put nearest target delta for each target horizon."""

    frame = _normalize_chain(chain, as_of_date=as_of_date)
    if frame.empty:
        return []

    candidates: list[CandidatePut] = []
    for horizon in target_horizons_days:
        expiry = _nearest_expiration(frame, horizon)
        if expiry is None:
            continue
        expiry_slice = frame[
            (frame["expiration"] == expiry) & (frame["option_type"] == "P")
        ].copy()
        if expiry_slice.empty:
            continue
        expiry_slice = _with_delta(
            expiry_slice,
            underlying_price=underlying_price,
            risk_free_rate=risk_free_rate,
        )
        selected = strike_for_target_delta(
            option_type="P",
            target_delta=target_delta,
            chain_slice=expiry_slice,
        )
        if selected is None:
            continue
        candidate = _candidate_from_result(
            ticker=ticker,
            horizon_days=horizon,
            result=selected,
            underlying_price=underlying_price,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _candidate_from_result(
    *,
    ticker: str,
    horizon_days: int,
    result: dict[str, object],
    underlying_price: float,
) -> CandidatePut | None:
    strike = _as_float(result.get("strike"))
    expiration = result.get("expiration")
    if strike is None or expiration is None:
        return None
    mid = _as_float(result.get("mid"))
    days_to_expiry = _as_int(result.get("days_to_expiry"))
    if days_to_expiry is None:
        days_to_expiry = 0
    return CandidatePut(
        ticker=ticker,
        horizon_days=horizon_days,
        expiration=str(expiration),
        days_to_expiry=days_to_expiry,
        strike=strike,
        bid=_as_float(result.get("bid")),
        ask=_as_float(result.get("ask")),
        mid=mid,
        open_interest=_as_int(result.get("open_interest")),
        volume=_as_int(result.get("volume")),
        implied_volatility=_as_float(result.get("implied_volatility")),
        delta=_as_float(result.get("delta")),
        delta_gap=_as_float(result.get("delta_gap")),
        premium_pct_spot=(mid / underlying_price) if mid is not None and underlying_price > 0 else None,
        underlying_price=underlying_price,
    )


def _normalize_chain(chain: pd.DataFrame, *, as_of_date: date | None) -> pd.DataFrame:
    if chain.empty:
        return pd.DataFrame()
    frame = chain.rename(
        columns={
            "lastPrice": "last_price",
            "openInterest": "open_interest",
            "impliedVolatility": "implied_volatility",
        }
    ).copy()
    required = {"expiration", "option_type", "strike", "bid", "ask", "implied_volatility"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    if "open_interest" not in frame.columns:
        frame["open_interest"] = None
    if "volume" not in frame.columns:
        frame["volume"] = None
    if "mid" not in frame.columns:
        frame["mid"] = [
            _midpoint(bid, ask)
            for bid, ask in zip(frame["bid"], frame["ask"], strict=False)
        ]
    if "days_to_expiry" not in frame.columns:
        if as_of_date is None:
            return pd.DataFrame()
        frame["days_to_expiry"] = [
            (value.date() - as_of_date).days
            if pd.notna(value := pd.to_datetime(expiration, errors="coerce"))
            else None
            for expiration in frame["expiration"]
        ]

    for column in (
        "strike",
        "bid",
        "ask",
        "mid",
        "volume",
        "open_interest",
        "implied_volatility",
        "days_to_expiry",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["expiration"] = pd.to_datetime(frame["expiration"], errors="coerce").dt.date
    frame["option_type"] = frame["option_type"].astype(str).str.upper()
    frame = frame[
        frame["expiration"].notna()
        & (frame["days_to_expiry"] > 0)
        & frame["option_type"].isin(["P", "C"])
    ].copy()
    return frame.reset_index(drop=True)


def _with_delta(
    frame: pd.DataFrame,
    *,
    underlying_price: float,
    risk_free_rate: float | None,
) -> pd.DataFrame:
    result = frame.copy()
    if risk_free_rate is None:
        result["delta"] = None
        return result
    result["delta"] = [
        black_scholes_delta(
            option_type=str(row.option_type),
            spot=underlying_price,
            strike=float(row.strike),
            time_to_expiry_years=float(row.days_to_expiry) / CALENDAR_DAYS_PER_YEAR,
            risk_free_rate=risk_free_rate,
            implied_volatility=_as_float(row.implied_volatility),
        )
        for row in result.itertuples(index=False)
    ]
    return result


def _nearest_expiration(frame: pd.DataFrame, horizon_days: int) -> date | None:
    expirations = (
        frame[["expiration", "days_to_expiry"]]
        .dropna()
        .drop_duplicates()
        .assign(distance=lambda item: (item["days_to_expiry"] - horizon_days).abs())
        .sort_values(["distance", "days_to_expiry"])
    )
    if expirations.empty:
        return None
    return expirations.iloc[0]["expiration"]


def _midpoint(bid: object, ask: object) -> float | None:
    bid_value = _as_float(bid)
    ask_value = _as_float(ask)
    if bid_value is None or ask_value is None or bid_value <= 0 or ask_value <= 0:
        return None
    return (bid_value + ask_value) / 2.0


def _as_float(value: object) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def _as_int(value: object) -> int | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return int(numeric)
