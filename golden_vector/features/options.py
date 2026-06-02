"""Derived options features for hedge-readiness reporting."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd

from golden_vector.features.black_scholes import strike_for_target_delta
from golden_vector.features.options_chain import (
    add_black_scholes_delta,
    as_float,
    compute_straddle_implied_move,
    nearest_expiration,
    normalize_options_chain,
    option_quote_is_tradable,
)

DEFAULT_TARGET_HORIZONS_DAYS = (30, 60, 90)
TRADING_DAYS_PER_YEAR = 252


def compute_options_features(
    *,
    chain: pd.DataFrame,
    underlying_price: float,
    risk_free_rate: float | None,
    price_history: pd.DataFrame,
    as_of_date: date,
    target_horizons_days: tuple[int, ...] = DEFAULT_TARGET_HORIZONS_DAYS,
    target_delta: float = -0.25,
    optionability_open_interest_threshold: int = 1000,
    implied_move_max_spread_pct: float = 0.35,
    implied_move_min_open_interest: int = 1,
    implied_move_min_volume: int = 0,
    candidate_max_spread_pct: float = 0.35,
    candidate_min_open_interest: int = 1,
    candidate_min_volume: int = 0,
    candidate_min_implied_volatility: float = 0.01,
    candidate_max_implied_volatility: float = 3.0,
) -> dict[str, Any]:
    """Compute one long-format options feature row for a ticker/as-of date."""

    frame = (
        normalize_options_chain(
            chain,
            underlying_price=underlying_price,
            as_of_date=as_of_date,
        )
        if underlying_price > 0
        else pd.DataFrame()
    )
    ticker = _first_value(chain, "ticker")
    run_id = _first_value(chain, "run_id")

    row: dict[str, Any] = {
        "ticker": ticker,
        "as_of_date": as_of_date.isoformat(),
        "run_id": run_id,
        "options_available": not frame.empty,
        "n_expirations": int(frame["expiration"].nunique()) if not frame.empty else 0,
        "n_contracts": int(len(frame.index)),
        "total_open_interest": _numeric_sum(frame, "open_interest"),
        "total_volume": _numeric_sum(frame, "volume"),
        "iv_percentile_cross_sectional": None,
        "put_call_oi_ratio_total": _put_call_oi_ratio(frame),
        "put_call_oi_ratio_otm": _put_call_oi_ratio(frame, otm_only=True, spot=underlying_price),
    }

    for horizon in target_horizons_days:
        suffix = f"{horizon}d"
        row[f"atm_iv_{suffix}"] = None
        row[f"put_iv_25d_{suffix}"] = None
        row[f"put_25d_delta_gap_{suffix}"] = None
        row[f"call_iv_25d_{suffix}"] = None
        row[f"call_25d_delta_gap_{suffix}"] = None
        row[f"iv_skew_{suffix}"] = None
        row[f"implied_move_{suffix}"] = None
        row[f"implied_move_{suffix}_gates_ok"] = False
        row[f"realized_vol_{suffix}"] = _realized_vol(price_history, window_days=horizon)
        row[f"iv_rv_ratio_{suffix}"] = None

    if frame.empty:
        row["term_slope_30_90"] = None
        row["optionability_tier"] = "none"
        return row

    for horizon in target_horizons_days:
        suffix = f"{horizon}d"
        expiry = nearest_expiration(frame, horizon)
        if expiry is None:
            continue

        expiry_slice = frame[frame["expiration"] == expiry].copy()
        with_delta = add_black_scholes_delta(
            expiry_slice,
            underlying_price=underlying_price,
            risk_free_rate=risk_free_rate,
        )
        tradable_slice = _tradable_option_slice(
            with_delta,
            max_spread_pct=candidate_max_spread_pct,
            min_open_interest=candidate_min_open_interest,
            min_volume=candidate_min_volume,
            min_implied_volatility=candidate_min_implied_volatility,
            max_implied_volatility=candidate_max_implied_volatility,
        )
        atm_iv = _atm_iv(tradable_slice, underlying_price)
        put_result = strike_for_target_delta(
            option_type="P",
            target_delta=float(target_delta),
            chain_slice=tradable_slice,
        )
        call_result = strike_for_target_delta(
            option_type="C",
            target_delta=abs(float(target_delta)),
            chain_slice=tradable_slice,
        )
        implied_move, gates_ok = compute_straddle_implied_move(
            expiry_slice,
            underlying_price=underlying_price,
            max_spread_pct=implied_move_max_spread_pct,
            min_open_interest=implied_move_min_open_interest,
            min_volume=implied_move_min_volume,
        )

        put_iv = _result_float(put_result, "implied_volatility")
        call_iv = _result_float(call_result, "implied_volatility")
        realized_vol = row[f"realized_vol_{suffix}"]
        row[f"atm_iv_{suffix}"] = atm_iv
        row[f"put_iv_25d_{suffix}"] = put_iv
        row[f"put_25d_delta_gap_{suffix}"] = _result_float(put_result, "delta_gap")
        row[f"call_iv_25d_{suffix}"] = call_iv
        row[f"call_25d_delta_gap_{suffix}"] = _result_float(call_result, "delta_gap")
        row[f"iv_skew_{suffix}"] = _difference(put_iv, call_iv)
        row[f"implied_move_{suffix}"] = implied_move
        row[f"implied_move_{suffix}_gates_ok"] = gates_ok
        row[f"iv_rv_ratio_{suffix}"] = _ratio(atm_iv, realized_vol)

    row["term_slope_30_90"] = _difference(row.get("atm_iv_90d"), row.get("atm_iv_30d"))
    row["optionability_tier"] = _optionability_tier(
        row=row,
        target_horizons_days=target_horizons_days,
        open_interest_threshold=optionability_open_interest_threshold,
    )
    return row


def rank_options_iv_cross_section(
    features: pd.DataFrame,
    *,
    iv_column: str = "atm_iv_60d",
) -> pd.Series:
    """Return a 0-100 cross-sectional IV percentile for one feature date."""

    if iv_column not in features.columns:
        return pd.Series([math.nan] * len(features.index), index=features.index)
    values = pd.to_numeric(features[iv_column], errors="coerce")
    return values.rank(pct=True, method="average") * 100.0


def _tradable_option_slice(
    frame: pd.DataFrame,
    *,
    max_spread_pct: float,
    min_open_interest: int,
    min_volume: int,
    min_implied_volatility: float,
    max_implied_volatility: float,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    return frame[
        frame.apply(
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


def _atm_iv(frame: pd.DataFrame, underlying_price: float) -> float | None:
    candidates = frame.dropna(subset=["strike", "implied_volatility"]).copy()
    if candidates.empty:
        return None
    candidates["distance"] = (candidates["strike"] - float(underlying_price)).abs()
    selected = candidates.sort_values(["distance", "option_type"]).iloc[0]
    return as_float(selected["implied_volatility"])


def _realized_vol(price_history: pd.DataFrame, *, window_days: int) -> float | None:
    if price_history.empty:
        return None
    if "return_basis_usd" in price_history.columns:
        returns = pd.to_numeric(price_history["return_basis_usd"], errors="coerce").dropna()
    elif "adj_close_usd" in price_history.columns:
        returns = pd.to_numeric(price_history["adj_close_usd"], errors="coerce").pct_change().dropna()
    else:
        return None
    returns = returns.tail(window_days)
    if len(returns.index) < 2:
        return None
    return float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))


def _optionability_tier(
    *,
    row: dict[str, Any],
    target_horizons_days: tuple[int, ...],
    open_interest_threshold: int,
) -> str:
    if not row["options_available"]:
        return "none"
    has_all_horizons = all(
        row.get(f"put_iv_25d_{horizon}d") is not None
        for horizon in target_horizons_days
    )
    if row["total_open_interest"] >= open_interest_threshold and has_all_horizons:
        return "directly_hedgeable"
    return "thin"


def _put_call_oi_ratio(
    frame: pd.DataFrame,
    *,
    otm_only: bool = False,
    spot: float | None = None,
) -> float | None:
    if frame.empty or "open_interest" not in frame.columns:
        return None
    scoped = frame
    if otm_only and spot is not None:
        scoped = frame[
            ((frame["option_type"] == "P") & (frame["strike"] < float(spot)))
            | ((frame["option_type"] == "C") & (frame["strike"] > float(spot)))
        ]
    puts = scoped.loc[scoped["option_type"] == "P", "open_interest"].sum()
    calls = scoped.loc[scoped["option_type"] == "C", "open_interest"].sum()
    return _ratio(float(puts), float(calls))


def _numeric_sum(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(pd.to_numeric(frame[column], errors="coerce").fillna(0).sum())


def _ratio(numerator: object, denominator: object) -> float | None:
    top = as_float(numerator)
    bottom = as_float(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


def _difference(left: object, right: object) -> float | None:
    left_value = as_float(left)
    right_value = as_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _result_float(result: dict[str, object] | None, key: str) -> float | None:
    if result is None:
        return None
    return as_float(result.get(key))


def _first_value(frame: pd.DataFrame, column: str) -> object | None:
    if frame.empty or column not in frame.columns:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    value = values.iloc[0]
    if hasattr(value, "item"):
        return value.item()
    return value
