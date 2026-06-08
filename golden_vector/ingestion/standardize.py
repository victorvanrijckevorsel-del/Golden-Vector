"""Standardize Yahoo Finance payloads into canonical raw tables."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from golden_vector.common.numeric import optional_float as _as_float
from golden_vector.contracts.data_models import MarketSnapshot
from golden_vector.normalize.price_units import price_unit_adjustment


def fetched_at_utc() -> datetime:
    return datetime.now(timezone.utc)


def standardize_equity_history(
    ticker: str,
    exchange: str | None,
    currency: str,
    source_symbol: str,
    frame: pd.DataFrame,
    fetched_at: datetime,
    feed_currency: object | None = None,
) -> pd.DataFrame:
    price_adjustment = price_unit_adjustment(feed_currency)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "date",
                "open_local",
                "high_local",
                "low_local",
                "close_local",
                "adj_close_local",
                "volume",
                "currency",
                "exchange",
                "source",
                "source_symbol",
                "feed_currency",
                "price_scale_factor",
                "minor_unit_adjusted",
                "fetched_at_utc",
            ]
        )

    standardized = pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.to_datetime(frame["Date"]).dt.date,
            "open_local": _adjust_history_price(frame, "Open", price_adjustment.scale_factor),
            "high_local": _adjust_history_price(frame, "High", price_adjustment.scale_factor),
            "low_local": _adjust_history_price(frame, "Low", price_adjustment.scale_factor),
            "close_local": _adjust_history_price(frame, "Close", price_adjustment.scale_factor),
            "adj_close_local": _adjust_history_price(frame, "Adj Close", price_adjustment.scale_factor),
            "volume": frame.get("Volume"),
            "currency": currency,
            "exchange": exchange,
            "source": "yfinance",
            "source_symbol": source_symbol,
            "feed_currency": price_adjustment.feed_currency,
            "price_scale_factor": price_adjustment.scale_factor,
            "minor_unit_adjusted": price_adjustment.minor_unit_adjusted,
            "fetched_at_utc": fetched_at,
        }
    )
    return standardized


def standardize_fx_history(
    base_currency: str,
    source_symbol: str,
    frame: pd.DataFrame,
    fetched_at: datetime,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "base_currency",
                "quote_currency",
                "date",
                "fx_pair",
                "fx_rate_to_usd",
                "source",
                "source_symbol",
                "fetched_at_utc",
            ]
        )

    standardized = pd.DataFrame(
        {
            "base_currency": base_currency,
            "quote_currency": "USD",
            "date": pd.to_datetime(frame["Date"]).dt.date,
            "fx_pair": f"{base_currency}USD",
            "fx_rate_to_usd": frame.get("Close"),
            "source": "yfinance",
            "source_symbol": source_symbol,
            "fetched_at_utc": fetched_at,
        }
    )
    return standardized


def standardize_gold_history(
    gold_symbol: str,
    source_symbol: str,
    frame: pd.DataFrame,
    fetched_at: datetime,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "gold_symbol",
                "close_usd",
                "adj_close_usd",
                "source",
                "source_symbol",
                "fetched_at_utc",
            ]
        )

    standardized = pd.DataFrame(
        {
            "date": pd.to_datetime(frame["Date"]).dt.date,
            "gold_symbol": gold_symbol,
            "close_usd": frame.get("Close"),
            "adj_close_usd": frame.get("Adj Close"),
            "source": "yfinance",
            "source_symbol": source_symbol,
            "fetched_at_utc": fetched_at,
        }
    )
    return standardized


def standardize_market_snapshot(
    ticker: str,
    currency: str,
    frame: pd.DataFrame,
    fast_info: dict[str, object],
    source_run_id: str,
) -> dict[str, object]:
    if frame.empty:
        raise ValueError(f"No recent history returned for market snapshot: {ticker}")

    last_row = frame.iloc[-1]
    snapshot_date = _extract_snapshot_date(ticker, last_row)
    raw_share_price_local = _extract_share_price_local(ticker, last_row, fast_info)
    # LSE (and a few other) feeds quote in a currency's minor unit (pence);
    # convert to the major unit so the downstream local->USD step isn't ~100x
    # too large (this silently inflated market_cap_usd for LSE names).
    price_adjustment = price_unit_adjustment(fast_info.get("currency"))
    share_price_local = price_adjustment.apply(raw_share_price_local)
    market_cap = _as_float(fast_info.get("marketCap") or fast_info.get("market_cap"))
    shares = _as_float(
        fast_info.get("shares")
        or fast_info.get("sharesOutstanding")
        or fast_info.get("shares_outstanding")
    )

    snapshot = MarketSnapshot(
        ticker=ticker,
        snapshot_date=snapshot_date,
        share_price_local=share_price_local,
        currency=currency,
        fx_rate_to_usd=1.0 if currency == "USD" else None,
        share_price_usd=share_price_local if currency == "USD" else None,
        market_cap_usd=market_cap if currency == "USD" else None,
        shares_outstanding=shares,
        source="yfinance",
        source_run_id=source_run_id,
        feed_currency=price_adjustment.feed_currency,
        price_scale_factor=price_adjustment.scale_factor,
        minor_unit_adjusted=price_adjustment.minor_unit_adjusted,
    )
    return snapshot.model_dump()


def empty_market_snapshot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "snapshot_date",
            "share_price_local",
            "currency",
            "fx_rate_to_usd",
            "share_price_usd",
            "market_cap_usd",
            "shares_outstanding",
            "source",
            "source_run_id",
            "feed_currency",
            "price_scale_factor",
            "minor_unit_adjusted",
        ]
    )


def _extract_snapshot_date(ticker: str, row: pd.Series) -> object:
    if "Date" not in row.index:
        raise ValueError(f"Market snapshot history is missing Date for {ticker}")
    snapshot_date = pd.to_datetime(row.get("Date"), errors="coerce")
    if pd.isna(snapshot_date):
        raise ValueError(f"Market snapshot history has an invalid Date for {ticker}")
    return snapshot_date.date()


def _extract_share_price_local(
    ticker: str,
    row: pd.Series,
    fast_info: dict[str, object],
) -> float:
    candidates = [
        row.get("Close"),
        row.get("Adj Close"),
        fast_info.get("lastPrice"),
        fast_info.get("last_price"),
        fast_info.get("currentPrice"),
        fast_info.get("current_price"),
        fast_info.get("regularMarketPrice"),
    ]
    for candidate in candidates:
        numeric = _as_float(candidate)
        if numeric is not None and numeric > 0:
            return numeric
    raise ValueError(f"Market snapshot has no valid positive share price for {ticker}")


def _adjust_history_price(
    frame: pd.DataFrame,
    column: str,
    scale_factor: float,
) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce") * float(scale_factor)
