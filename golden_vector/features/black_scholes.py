"""Small Black-Scholes helpers for option-delta based strike selection."""

from __future__ import annotations

import math
from typing import Literal

import pandas as pd

from golden_vector.common.numeric import optional_float


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution via math.erf."""

    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    """Standard normal probability density."""

    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _inputs_are_usable(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    implied_volatility: float | None,
) -> bool:
    """Shared degenerate-input gate for the greek surface (NaN-safe)."""

    # optional_float is the shared NaN/NA-safe scalar coercion (common/numeric).
    values = [
        optional_float(value)
        for value in (spot, strike, time_to_expiry_years, implied_volatility)
    ]
    return all(value is not None and value > 0 for value in values)


def _d1_d2(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float,
) -> tuple[float, float]:
    """Return the Black-Scholes (d1, d2) pair. Callers gate inputs first."""

    sqrt_time = math.sqrt(time_to_expiry_years)
    sigma_sqrt_time = implied_volatility * sqrt_time
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * implied_volatility * implied_volatility)
        * time_to_expiry_years
    ) / sigma_sqrt_time
    return d1, d1 - sigma_sqrt_time


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

    d1, _ = _d1_d2(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        implied_volatility=implied_volatility,
    )
    call_delta = normal_cdf(d1)
    if option_type == "C":
        return call_delta
    return call_delta - 1.0


def black_scholes_gamma(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
) -> float | None:
    """Return gamma per $1 move in the underlying (same for puts and calls).

    Continuous dividend yield q = 0 (miners in this universe pay small,
    discrete dividends; a zero-q assumption is the stated convention).
    Time is in YEARS — call sites convert calendar DTE with
    ``options_chain.CALENDAR_DAYS_PER_YEAR`` exactly as ``add_black_scholes_delta``
    does, so every greek shares delta's day-count.
    Degenerate / NaN inputs return None.
    """

    if not _inputs_are_usable(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        implied_volatility=implied_volatility,
    ):
        return None
    sigma = float(implied_volatility)  # type: ignore[arg-type]
    d1, _ = _d1_d2(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        implied_volatility=sigma,
    )
    return normal_pdf(d1) / (spot * sigma * math.sqrt(time_to_expiry_years))


def black_scholes_vega(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
) -> float | None:
    """Return vega per 1.00 of volatility (i.e. per 100 vol points), q = 0.

    Displays divide by 100 for "per vol point". Same for puts and calls.
    Time in years (see ``black_scholes_gamma``). NaN/degenerate -> None.
    """

    if not _inputs_are_usable(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        implied_volatility=implied_volatility,
    ):
        return None
    d1, _ = _d1_d2(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        implied_volatility=float(implied_volatility),  # type: ignore[arg-type]
    )
    return spot * normal_pdf(d1) * math.sqrt(time_to_expiry_years)


def black_scholes_theta(
    *,
    option_type: Literal["P", "C"],
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
    days_per_year: float = 365.25,
) -> float | None:
    """Return theta per CALENDAR day (negative for long premium), q = 0.

    The annual closed form is divided by ``days_per_year`` (365.25 — the same
    calendar convention as ``CALENDAR_DAYS_PER_YEAR``, kept as a parameter so
    this module stays import-free of ``options_chain``, which imports from here).
    Time in years (see ``black_scholes_gamma``). NaN/degenerate -> None.
    """

    if option_type not in {"P", "C"}:
        raise ValueError("option_type must be 'P' or 'C'")
    if not _inputs_are_usable(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        implied_volatility=implied_volatility,
    ):
        return None
    sigma = float(implied_volatility)  # type: ignore[arg-type]
    d1, d2 = _d1_d2(
        spot=spot,
        strike=strike,
        time_to_expiry_years=time_to_expiry_years,
        risk_free_rate=risk_free_rate,
        implied_volatility=sigma,
    )
    decay = -(spot * normal_pdf(d1) * sigma) / (2.0 * math.sqrt(time_to_expiry_years))
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    if option_type == "C":
        annual = decay - risk_free_rate * discounted_strike * normal_cdf(d2)
    else:
        annual = decay + risk_free_rate * discounted_strike * normal_cdf(-d2)
    return annual / float(days_per_year)


def black_scholes_greeks(
    *,
    option_type: Literal["P", "C"],
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
) -> dict[str, float | None]:
    """Return {'gamma', 'vega', 'theta'} in the units documented above (q = 0)."""

    shared = {
        "spot": spot,
        "strike": strike,
        "time_to_expiry_years": time_to_expiry_years,
        "risk_free_rate": risk_free_rate,
        "implied_volatility": implied_volatility,
    }
    return {
        "gamma": black_scholes_gamma(**shared),
        "vega": black_scholes_vega(**shared),
        "theta": black_scholes_theta(option_type=option_type, **shared),
    }


def black_scholes_put_price(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
) -> float | None:
    """Return the European Black-Scholes put price."""

    if strike <= 0 or time_to_expiry_years <= 0 or spot < 0:
        return None
    if spot == 0:
        return strike * math.exp(-risk_free_rate * time_to_expiry_years)
    if implied_volatility is None or implied_volatility <= 0:
        return None

    sqrt_time = math.sqrt(time_to_expiry_years)
    sigma_sqrt_time = implied_volatility * sqrt_time
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * implied_volatility * implied_volatility)
        * time_to_expiry_years
    ) / sigma_sqrt_time
    d2 = d1 - sigma_sqrt_time
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    return discounted_strike * normal_cdf(-d2) - spot * normal_cdf(-d1)


def black_scholes_call_price(
    *,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    implied_volatility: float | None,
) -> float | None:
    """Return the European Black-Scholes call price."""

    if strike <= 0 or time_to_expiry_years <= 0 or spot < 0:
        return None
    if spot == 0:
        return 0.0
    if implied_volatility is None or implied_volatility <= 0:
        return None

    sqrt_time = math.sqrt(time_to_expiry_years)
    sigma_sqrt_time = implied_volatility * sqrt_time
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate + 0.5 * implied_volatility * implied_volatility)
        * time_to_expiry_years
    ) / sigma_sqrt_time
    d2 = d1 - sigma_sqrt_time
    discounted_strike = strike * math.exp(-risk_free_rate * time_to_expiry_years)
    return spot * normal_cdf(d1) - discounted_strike * normal_cdf(d2)


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
        "last_price": _value(row, "last_price"),
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
