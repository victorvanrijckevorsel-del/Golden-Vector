"""Small Black-Scholes helpers for option-delta based strike selection."""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution via math.erf."""

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_delta(
    *,
    option_type: Literal["P", "C"],
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
) -> float | None:
    """Return signed Black-Scholes delta, with puts negative and calls positive."""

    if option_type not in {"P", "C"}:
        raise ValueError("option_type must be 'P' or 'C'")
    if (
        spot <= 0
        or strike <= 0
        or time_to_expiry_years <= 0
        or implied_volatility is None
        or implied_volatility <= 0
    ):
        return None

    sqrt_time = math.sqrt(time_to_expiry_years)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * implied_volatility * implied_volatility)
        * time_to_expiry_years
    ) / (implied_volatility * sqrt_time)
    call_delta = normal_cdf(d1)
    if option_type == "C":
        return call_delta
    return call_delta - 1.0


def strike_for_target_delta(
    *,
    option_type: Literal["P", "C"],
    target_delta: float,
    chain_slice: pd.DataFrame,
) -> dict[str, object] | None:
    """Return the listed contract whose computed delta is closest to target_delta."""

    if option_type not in {"P", "C"}:
        raise ValueError("option_type must be 'P' or 'C'")
    if chain_slice.empty or "delta" not in chain_slice.columns:
        return None

    candidates = chain_slice.copy()
    if "option_type" in candidates.columns:
        candidates = candidates[candidates["option_type"].astype(str) == option_type]
    candidates["delta"] = pd.to_numeric(candidates["delta"], errors="coerce")
    candidates = candidates[candidates["delta"].notna()].copy()
    if candidates.empty:
        return None

    candidates["delta_gap"] = (candidates["delta"] - float(target_delta)).abs()
    sort_columns = ["delta_gap"]
    if "strike" in candidates.columns:
        candidates["strike"] = pd.to_numeric(candidates["strike"], errors="coerce")
        sort_columns.append("strike")
    selected = candidates.sort_values(sort_columns, na_position="last").iloc[0]
    return _contract_result(selected)


def _contract_result(row: pd.Series) -> dict[str, object]:
    return {
        "strike": _value(row, "strike"),
        "expiration": _value(row, "expiration"),
        "bid": _value(row, "bid"),
        "ask": _value(row, "ask"),
        "mid": _value(row, "mid"),
        "open_interest": _value(row, "open_interest"),
        "volume": _value(row, "volume"),
        "implied_volatility": _value(row, "implied_volatility"),
        "delta": _value(row, "delta"),
        "delta_gap": _value(row, "delta_gap"),
        "days_to_expiry": _value(row, "days_to_expiry"),
    }


def _value(row: pd.Series, column: str) -> object:
    if column not in row.index:
        return None
    value = row[column]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
