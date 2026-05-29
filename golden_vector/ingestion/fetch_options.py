"""Fetch and standardize Yahoo options chains."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd

from golden_vector.ingestion.yahoo_client import YahooClient

OPTIONS_STATUS_SUCCESS = "SUCCESS"
OPTIONS_STATUS_EMPTY = "EMPTY"
OPTIONS_STATUS_ERROR = "ERROR"
RAW_OPTIONS_COLUMNS = [
    "ticker",
    "as_of_date",
    "expiration",
    "option_type",
    "strike",
    "bid",
    "ask",
    "mid",
    "last_price",
    "volume",
    "open_interest",
    "implied_volatility",
    "underlying_price",
    "moneyness",
    "days_to_expiry",
]


@dataclass(frozen=True)
class OptionsChainResult:
    ticker: str
    as_of_date: date
    status: str
    frame: pd.DataFrame
    message: str | None = None

    @property
    def options_available(self) -> bool:
        return self.status == OPTIONS_STATUS_SUCCESS and not self.frame.empty


def fetch_options_chain(
    *,
    ticker: str,
    as_of_date: date,
    yahoo_client: YahooClient,
) -> OptionsChainResult:
    """Fetch all available Yahoo option expirations for one ticker."""

    try:
        expirations = yahoo_client.fetch_options_expirations(ticker)
        if not expirations:
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_EMPTY,
                frame=_empty_options_frame(),
                message="No listed options returned by Yahoo.",
            )

        underlying_price = _extract_underlying_price(yahoo_client.fetch_fast_info(ticker))
        if underlying_price is None:
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_ERROR,
                frame=_empty_options_frame(),
                message="Could not determine underlying price.",
            )

        frames: list[pd.DataFrame] = []
        for expiration in expirations:
            chain = yahoo_client.fetch_option_chain(ticker, expiration)
            frames.append(
                _standardize_option_side(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    expiration=expiration,
                    option_type="P",
                    frame=pd.DataFrame(chain.puts),
                    underlying_price=underlying_price,
                )
            )
            frames.append(
                _standardize_option_side(
                    ticker=ticker,
                    as_of_date=as_of_date,
                    expiration=expiration,
                    option_type="C",
                    frame=pd.DataFrame(chain.calls),
                    underlying_price=underlying_price,
                )
            )

        frame = pd.concat(frames, ignore_index=True) if frames else _empty_options_frame()
        if frame.empty:
            return OptionsChainResult(
                ticker=ticker,
                as_of_date=as_of_date,
                status=OPTIONS_STATUS_EMPTY,
                frame=_empty_options_frame(),
                message="Yahoo returned expirations but no option rows.",
            )
        return OptionsChainResult(
            ticker=ticker,
            as_of_date=as_of_date,
            status=OPTIONS_STATUS_SUCCESS,
            frame=frame[RAW_OPTIONS_COLUMNS].reset_index(drop=True),
        )
    except Exception as exc:  # noqa: BLE001 - per-ticker options fetch is best-effort.
        return OptionsChainResult(
            ticker=ticker,
            as_of_date=as_of_date,
            status=OPTIONS_STATUS_ERROR,
            frame=_empty_options_frame(),
            message=str(exc),
        )


def _standardize_option_side(
    *,
    ticker: str,
    as_of_date: date,
    expiration: str,
    option_type: Literal["P", "C"],
    frame: pd.DataFrame,
    underlying_price: float,
) -> pd.DataFrame:
    if frame.empty:
        return _empty_options_frame()

    expiration_date = pd.to_datetime(expiration).date()
    standardized = pd.DataFrame(
        {
            "ticker": ticker,
            "as_of_date": as_of_date.isoformat(),
            "expiration": expiration_date.isoformat(),
            "option_type": option_type,
            "strike": pd.to_numeric(frame.get("strike"), errors="coerce"),
            "bid": pd.to_numeric(frame.get("bid"), errors="coerce"),
            "ask": pd.to_numeric(frame.get("ask"), errors="coerce"),
            "last_price": pd.to_numeric(frame.get("lastPrice"), errors="coerce"),
            "volume": pd.to_numeric(frame.get("volume"), errors="coerce"),
            "open_interest": pd.to_numeric(frame.get("openInterest"), errors="coerce"),
            "implied_volatility": pd.to_numeric(frame.get("impliedVolatility"), errors="coerce"),
            "underlying_price": float(underlying_price),
        }
    )
    standardized["mid"] = [
        _midpoint(bid, ask)
        for bid, ask in zip(standardized["bid"], standardized["ask"], strict=False)
    ]
    standardized["moneyness"] = standardized["strike"] / float(underlying_price)
    standardized["days_to_expiry"] = (expiration_date - as_of_date).days
    return standardized[RAW_OPTIONS_COLUMNS]


def _extract_underlying_price(fast_info: object) -> float | None:
    if not isinstance(fast_info, dict):
        return None
    for key in ("last_price", "lastPrice", "regularMarketPrice", "previousClose"):
        value = _as_float(fast_info.get(key))
        if value is not None and value > 0:
            return value
    return None


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


def _empty_options_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=RAW_OPTIONS_COLUMNS)
