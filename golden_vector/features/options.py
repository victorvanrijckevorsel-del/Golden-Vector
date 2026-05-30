"""Derived options features for hedge-readiness reporting."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd

from golden_vector.features.black_scholes import (
    black_scholes_delta,
    strike_for_target_delta,
)

DEFAULT_TARGET_HORIZONS_DAYS = (30, 60, 90)
TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365.25


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
) -> dict[str, Any]:
    """Compute one long-format options feature row for a ticker/as-of date."""

    frame = _normalize_chain(chain, underlying_price=underlying_price, as_of_date=as_of_date)
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
        expiry = _nearest_expiration(frame, horizon)
        if expiry is None:
            continue

        expiry_slice = frame[frame["expiration"] == expiry].copy()
        with_delta = _with_delta(
            expiry_slice,
            underlying_price=underlying_price,
            risk_free_rate=risk_free_rate,
        )
        atm_iv = _atm_iv(expiry_slice, underlying_price)
        put_result = strike_for_target_delta(
            option_type="P",
            target_delta=float(target_delta),
            chain_slice=with_delta,
        )
        call_result = strike_for_target_delta(
            option_type="C",
            target_delta=abs(float(target_delta)),
            chain_slice=with_delta,
        )
        implied_move, gates_ok = _implied_move_from_straddle(
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


def _normalize_chain(
    chain: pd.DataFrame,
    *,
    underlying_price: float,
    as_of_date: date,
) -> pd.DataFrame:
    if chain.empty:
        return _empty_chain()
    if "options_available" in chain.columns and not chain["options_available"].fillna(False).any():
        return _empty_chain()
    required = {"expiration", "option_type", "strike", "bid", "ask", "implied_volatility"}
    renamed = chain.rename(
        columns={
            "lastPrice": "last_price",
            "openInterest": "open_interest",
            "impliedVolatility": "implied_volatility",
        }
    ).copy()
    if not required.issubset(renamed.columns):
        return _empty_chain()

    if "open_interest" not in renamed.columns:
        renamed["open_interest"] = None
    if "volume" not in renamed.columns:
        renamed["volume"] = None
    if "mid" not in renamed.columns:
        renamed["mid"] = [
            _midpoint(bid, ask)
            for bid, ask in zip(renamed["bid"], renamed["ask"], strict=False)
        ]
    if "days_to_expiry" not in renamed.columns:
        expiration_dates = pd.to_datetime(renamed["expiration"], errors="coerce")
        renamed["days_to_expiry"] = [
            (value.date() - as_of_date).days if pd.notna(value) else math.nan
            for value in expiration_dates
        ]
    if "underlying_price" not in renamed.columns:
        renamed["underlying_price"] = float(underlying_price)

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
        renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
    renamed["expiration"] = pd.to_datetime(renamed["expiration"], errors="coerce").dt.date
    renamed["option_type"] = renamed["option_type"].astype(str).str.upper()
    renamed = renamed[
        renamed["expiration"].notna()
        & renamed["option_type"].isin(["P", "C"])
        & (renamed["days_to_expiry"] > 0)
    ].copy()
    return renamed.reset_index(drop=True)


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

    deltas: list[float | None] = []
    for row in result.itertuples(index=False):
        days = _as_float(getattr(row, "days_to_expiry", None))
        iv = _as_float(getattr(row, "implied_volatility", None))
        strike = _as_float(getattr(row, "strike", None))
        option_type = str(getattr(row, "option_type", "")).upper()
        if days is None or strike is None or option_type not in {"P", "C"}:
            deltas.append(None)
            continue
        deltas.append(
            black_scholes_delta(
                option_type=option_type,  # type: ignore[arg-type]
                spot=float(underlying_price),
                strike=strike,
                time_to_expiry_years=days / CALENDAR_DAYS_PER_YEAR,
                risk_free_rate=float(risk_free_rate),
                implied_volatility=iv,
            )
        )
    result["delta"] = deltas
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


def _atm_iv(frame: pd.DataFrame, underlying_price: float) -> float | None:
    candidates = frame.dropna(subset=["strike", "implied_volatility"]).copy()
    if candidates.empty:
        return None
    candidates["distance"] = (candidates["strike"] - float(underlying_price)).abs()
    selected = candidates.sort_values(["distance", "option_type"]).iloc[0]
    return _as_float(selected["implied_volatility"])


def _implied_move_from_straddle(
    frame: pd.DataFrame,
    *,
    underlying_price: float,
    max_spread_pct: float,
    min_open_interest: int,
    min_volume: int,
) -> tuple[float | None, bool]:
    candidates = frame.dropna(subset=["strike", "bid", "ask", "mid"]).copy()
    if candidates.empty:
        return None, False
    common_strikes = set(candidates.loc[candidates["option_type"] == "P", "strike"]).intersection(
        set(candidates.loc[candidates["option_type"] == "C", "strike"])
    )
    if not common_strikes:
        return None, False

    strike = min(common_strikes, key=lambda value: abs(float(value) - float(underlying_price)))
    put = candidates[(candidates["option_type"] == "P") & (candidates["strike"] == strike)].iloc[0]
    call = candidates[(candidates["option_type"] == "C") & (candidates["strike"] == strike)].iloc[0]
    if not (_passes_quote_gates(put, max_spread_pct) and _passes_quote_gates(call, max_spread_pct)):
        return None, False
    if min(_safe_int(put.get("open_interest")), _safe_int(call.get("open_interest"))) < min_open_interest:
        return None, False
    if min(_safe_int(put.get("volume")), _safe_int(call.get("volume"))) < min_volume:
        return None, False

    implied_move = (_as_float(put["mid"]) + _as_float(call["mid"])) / float(underlying_price)
    return implied_move, True


def _passes_quote_gates(row: pd.Series, max_spread_pct: float) -> bool:
    bid = _as_float(row.get("bid"))
    ask = _as_float(row.get("ask"))
    mid = _as_float(row.get("mid"))
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0 or mid <= 0:
        return False
    return ((ask - bid) / mid) <= max_spread_pct


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
    top = _as_float(numerator)
    bottom = _as_float(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


def _difference(left: object, right: object) -> float | None:
    left_value = _as_float(left)
    right_value = _as_float(right)
    if left_value is None or right_value is None:
        return None
    return left_value - right_value


def _result_float(result: dict[str, object] | None, key: str) -> float | None:
    if result is None:
        return None
    return _as_float(result.get(key))


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


def _safe_int(value: object) -> int:
    numeric = _as_float(value)
    if numeric is None:
        return 0
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
