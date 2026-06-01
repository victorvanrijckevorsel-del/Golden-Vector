"""Shared option-chain normalization and quote helpers."""

from __future__ import annotations

from datetime import date
from typing import Literal, cast

import pandas as pd

from golden_vector.features.black_scholes import black_scholes_delta

CALENDAR_DAYS_PER_YEAR = 365.25


def normalize_options_chain(
    chain: pd.DataFrame,
    *,
    as_of_date: date | None = None,
    underlying_price: float | None = None,
    require_implied_volatility: bool = True,
    require_days_to_expiry: bool = True,
) -> pd.DataFrame:
    """Return a canonical options chain or an empty frame when unusable."""

    if chain.empty:
        return _empty_chain()
    if "options_available" in chain.columns and not chain["options_available"].fillna(False).any():
        return _empty_chain()

    frame = chain.rename(
        columns={
            "lastPrice": "last_price",
            "openInterest": "open_interest",
            "impliedVolatility": "implied_volatility",
        }
    ).copy()
    required = {"expiration", "option_type", "strike", "bid", "ask"}
    if require_implied_volatility:
        required.add("implied_volatility")
    if not required.issubset(frame.columns):
        return _empty_chain()

    if "open_interest" not in frame.columns:
        frame["open_interest"] = None
    if "volume" not in frame.columns:
        frame["volume"] = None
    if "mid" not in frame.columns:
        frame["mid"] = [
            midpoint(bid, ask)
            for bid, ask in zip(frame["bid"], frame["ask"], strict=False)
        ]
    if "days_to_expiry" not in frame.columns:
        if as_of_date is None and require_days_to_expiry:
            return _empty_chain()
        if as_of_date is None:
            frame["days_to_expiry"] = None
        else:
            expiration_dates = pd.to_datetime(frame["expiration"], errors="coerce")
            frame["days_to_expiry"] = [
                (value.date() - as_of_date).days if pd.notna(value) else None
                for value in expiration_dates
            ]
    if "underlying_price" not in frame.columns and underlying_price is not None:
        frame["underlying_price"] = float(underlying_price)

    for column in (
        "strike",
        "bid",
        "ask",
        "mid",
        "volume",
        "open_interest",
        "implied_volatility",
        "underlying_price",
        "days_to_expiry",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["expiration"] = pd.to_datetime(frame["expiration"], errors="coerce").dt.date
    frame["option_type"] = frame["option_type"].astype(str).str.upper()
    frame = frame[
        frame["expiration"].notna()
        & frame["option_type"].isin(["P", "C"])
        & frame["strike"].notna()
    ].copy()
    if require_days_to_expiry:
        frame = frame[frame["days_to_expiry"] > 0].copy()
    return frame.reset_index(drop=True)


def add_black_scholes_delta(
    frame: pd.DataFrame,
    *,
    underlying_price: float,
    risk_free_rate: float | None,
) -> pd.DataFrame:
    """Add signed Black-Scholes deltas to a normalized option chain."""

    result = frame.copy()
    if risk_free_rate is None:
        result["delta"] = None
        return result

    deltas: list[float | None] = []
    for row in result.itertuples(index=False):
        days = as_float(getattr(row, "days_to_expiry", None))
        iv = as_float(getattr(row, "implied_volatility", None))
        strike = as_float(getattr(row, "strike", None))
        option_type = str(getattr(row, "option_type", "")).upper()
        if days is None or strike is None or option_type not in {"P", "C"}:
            deltas.append(None)
            continue
        option_kind = cast(Literal["P", "C"], option_type)
        deltas.append(
            black_scholes_delta(
                option_type=option_kind,
                spot=float(underlying_price),
                strike=strike,
                time_to_expiry_years=days / CALENDAR_DAYS_PER_YEAR,
                risk_free_rate=float(risk_free_rate),
                implied_volatility=iv,
            )
        )
    result["delta"] = deltas
    return result


def nearest_expiration(frame: pd.DataFrame, horizon_days: int) -> date | None:
    """Return the listed expiration nearest a target horizon."""

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


def compute_straddle_implied_move(
    frame: pd.DataFrame,
    *,
    underlying_price: float,
    expiration: date | str | None = None,
    max_spread_pct: float,
    min_open_interest: int,
    min_volume: int,
) -> tuple[float | None, bool]:
    """Return ATM straddle implied move plus a gate-pass flag."""

    if frame.empty or underlying_price <= 0:
        return None, False
    candidates = frame.dropna(subset=["strike", "bid", "ask", "mid"]).copy()
    if expiration is not None:
        expiration_date = pd.to_datetime(expiration, errors="coerce")
        if pd.isna(expiration_date):
            return None, False
        candidates = candidates[candidates["expiration"] == expiration_date.date()]
    if candidates.empty:
        return None, False

    put_strikes = set(candidates.loc[candidates["option_type"] == "P", "strike"])
    call_strikes = set(candidates.loc[candidates["option_type"] == "C", "strike"])
    common_strikes = put_strikes.intersection(call_strikes)
    if not common_strikes:
        return None, False

    strike = min(common_strikes, key=lambda value: abs(float(value) - float(underlying_price)))
    put = candidates[(candidates["option_type"] == "P") & (candidates["strike"] == strike)].iloc[0]
    call = candidates[(candidates["option_type"] == "C") & (candidates["strike"] == strike)].iloc[0]
    if not (
        quote_passes_liquidity_gates(put, max_spread_pct)
        and quote_passes_liquidity_gates(call, max_spread_pct)
    ):
        return None, False
    min_open_interest_seen = min(
        as_int(put.get("open_interest")) or 0,
        as_int(call.get("open_interest")) or 0,
    )
    if min_open_interest_seen < min_open_interest:
        return None, False
    min_volume_seen = min(
        as_int(put.get("volume")) or 0,
        as_int(call.get("volume")) or 0,
    )
    if min_volume_seen < min_volume:
        return None, False

    put_mid = as_float(put["mid"])
    call_mid = as_float(call["mid"])
    if put_mid is None or call_mid is None:
        return None, False
    implied_move = (put_mid + call_mid) / float(underlying_price)
    return implied_move, True


def quote_passes_liquidity_gates(row: pd.Series, max_spread_pct: float) -> bool:
    bid = as_float(row.get("bid"))
    ask = as_float(row.get("ask"))
    mid = as_float(row.get("mid"))
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0 or mid <= 0:
        return False
    return ((ask - bid) / mid) <= max_spread_pct


def midpoint(bid: object, ask: object) -> float | None:
    bid_value = as_float(bid)
    ask_value = as_float(ask)
    if bid_value is None or ask_value is None or bid_value <= 0 or ask_value <= 0:
        return None
    return (bid_value + ask_value) / 2.0


def as_float(value: object) -> float | None:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        return None
    return float(numeric)


def as_int(value: object) -> int | None:
    numeric = as_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _empty_chain() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "expiration",
            "option_type",
            "strike",
            "bid",
            "ask",
            "mid",
            "volume",
            "open_interest",
            "implied_volatility",
            "underlying_price",
            "days_to_expiry",
        ]
    )
