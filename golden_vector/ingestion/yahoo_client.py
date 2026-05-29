"""Thin wrapper around yfinance."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd


class YahooClient:
    """Fetches market data from Yahoo Finance."""

    def __init__(self) -> None:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "yfinance is required to run the foundation pipeline. Install dependencies from requirements.txt."
            ) from exc
        self._yf = yf

    def fetch_history(
        self,
        symbol: str,
        period: str = "max",
        interval: str = "1d",
    ) -> pd.DataFrame:
        ticker = self._yf.Ticker(symbol)
        frame = ticker.history(
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False,
        )
        if frame.empty:
            return frame
        if "Date" not in frame.columns:
            frame = frame.reset_index()
        return frame

    def fetch_fast_info(self, symbol: str) -> Mapping[str, object]:
        ticker = self._yf.Ticker(symbol)
        try:
            return dict(ticker.fast_info)
        except Exception:
            return {}

    def fetch_options_expirations(self, symbol: str) -> list[str]:
        ticker = self._yf.Ticker(symbol)
        return list(ticker.options or [])

    def fetch_option_chain(self, symbol: str, expiration: str) -> object:
        ticker = self._yf.Ticker(symbol)
        return ticker.option_chain(expiration)
