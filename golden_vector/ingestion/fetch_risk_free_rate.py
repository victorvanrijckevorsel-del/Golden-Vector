"""Fetch the short risk-free rate used for option deltas."""

from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.ingestion.yahoo_client import YahooClient

DEFAULT_RISK_FREE_SYMBOL = "^IRX"


def fetch_risk_free_rate(
    *,
    as_of_date: date,
    yahoo_client: YahooClient,
    symbol: str = DEFAULT_RISK_FREE_SYMBOL,
) -> float:
    """Fetch the latest 13-week T-bill yield from Yahoo and return a decimal rate."""

    history = yahoo_client.fetch_history(symbol, period="5d")
    if history.empty:
        raise ValueError(f"No risk-free-rate history returned for {symbol}.")
    if "Date" in history.columns:
        dated = history[pd.to_datetime(history["Date"]).dt.date <= as_of_date].copy()
        if dated.empty:
            dated = history.copy()
    else:
        dated = history.copy()
    close = pd.to_numeric(dated.iloc[-1].get("Close"), errors="coerce")
    if pd.isna(close):
        raise ValueError(f"No close value returned for {symbol}.")
    rate = float(close)
    # ^IRX (the 13-week T-bill yield index) is ALWAYS quoted as a percent — 5.25 means
    # 5.25%, and 0.50 means 0.50% (decimal 0.005), NOT 50%. Convert to a decimal
    # unconditionally. The old magnitude heuristic ("/100 only when > 1.0") silently
    # 100x'd the rate in any low-rate regime where the yield printed below 1% (common
    # 2010-15, 2020-21), corrupting every Black-Scholes delta/discount downstream.
    # The unit is known from the feed; never infer it from the value's magnitude.
    return rate / 100.0
