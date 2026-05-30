"""Implied-move helpers for hedge-readiness reports."""

from __future__ import annotations

from datetime import date

import pandas as pd


def compute_implied_move_from_straddle(
    *,
    chain: pd.DataFrame,
    underlying_price: float,
    expiration: date | str,
    max_spread_pct: float = 0.35,
    min_open_interest: int = 1,
    min_volume: int = 0,
) -> float | None:
    """Return ATM straddle implied move when quote liquidity gates pass."""

    if chain.empty or underlying_price <= 0:
        return None
    frame = _normalize_chain(chain)
    expiration_date = pd.to_datetime(expiration, errors="coerce")
    if pd.isna(expiration_date):
        return None
    frame = frame[frame["expiration"] == expiration_date.date()].copy()
    if frame.empty:
        return None

    common_strikes = set(frame.loc[frame["option_type"] == "P", "strike"]).intersection(
        set(frame.loc[frame["option_type"] == "C", "strike"])
    )
    if not common_strikes:
        return None

    strike = min(common_strikes, key=lambda value: abs(float(value) - float(underlying_price)))
    put = frame[(frame["option_type"] == "P") & (frame["strike"] == strike)].iloc[0]
    call = frame[(frame["option_type"] == "C") & (frame["strike"] == strike)].iloc[0]
    if not (_passes_quote_gates(put, max_spread_pct) and _passes_quote_gates(call, max_spread_pct)):
        return None
    if min(_safe_int(put.get("open_interest")), _safe_int(call.get("open_interest"))) < min_open_interest:
        return None
    if min(_safe_int(put.get("volume")), _safe_int(call.get("volume"))) < min_volume:
        return None

    return (_as_float(put["mid"]) + _as_float(call["mid"])) / float(underlying_price)


def _normalize_chain(chain: pd.DataFrame) -> pd.DataFrame:
    frame = chain.rename(
        columns={
            "lastPrice": "last_price",
            "openInterest": "open_interest",
            "impliedVolatility": "implied_volatility",
        }
    ).copy()
    required = {"expiration", "option_type", "strike", "bid", "ask"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    if "mid" not in frame.columns:
        frame["mid"] = [
            _midpoint(bid, ask)
            for bid, ask in zip(frame["bid"], frame["ask"], strict=False)
        ]
    for column in ("strike", "bid", "ask", "mid", "volume", "open_interest"):
        if column not in frame.columns:
            frame[column] = None
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["expiration"] = pd.to_datetime(frame["expiration"], errors="coerce").dt.date
    frame["option_type"] = frame["option_type"].astype(str).str.upper()
    return frame.dropna(subset=["expiration", "strike", "bid", "ask", "mid"])


def _passes_quote_gates(row: pd.Series, max_spread_pct: float) -> bool:
    bid = _as_float(row.get("bid"))
    ask = _as_float(row.get("ask"))
    mid = _as_float(row.get("mid"))
    if bid is None or ask is None or mid is None or bid <= 0 or ask <= 0 or mid <= 0:
        return False
    return ((ask - bid) / mid) <= max_spread_pct


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
