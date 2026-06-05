"""Thin wrapper around yfinance."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pandas as pd

from golden_vector.ingestion.collection_resilience import RetryPolicy, call_with_retries

LOGGER = logging.getLogger(__name__)


class YahooClient:
    """Fetches market data from Yahoo Finance."""

    def __init__(self, *, retry_policy: RetryPolicy | None = None) -> None:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise RuntimeError(
                "yfinance is required to run the foundation pipeline. Install dependencies from requirements.txt."
            ) from exc
        self._yf = yf
        self._retry_policy = retry_policy or RetryPolicy()

    def fetch_history(
        self,
        symbol: str,
        period: str = "max",
        interval: str = "1d",
    ) -> pd.DataFrame:
        frame = call_with_retries(
            f"Yahoo history {symbol}",
            lambda: self._yf.Ticker(symbol).history(
                period=period,
                interval=interval,
                auto_adjust=False,
                actions=False,
            ),
            policy=self._retry_policy,
            logger=LOGGER,
        )
        if frame.empty:
            return frame
        if "Date" not in frame.columns:
            frame = frame.reset_index()
        return frame

    def fetch_fast_info(self, symbol: str) -> Mapping[str, object]:
        try:
            return dict(
                call_with_retries(
                    f"Yahoo fast_info {symbol}",
                    lambda: self._yf.Ticker(symbol).fast_info,
                    policy=self._retry_policy,
                    logger=LOGGER,
                )
            )
        except Exception:
            return {}

    def fetch_options_expirations(self, symbol: str) -> list[str]:
        return list(
            call_with_retries(
                f"Yahoo options expirations {symbol}",
                lambda: self._yf.Ticker(symbol).options or [],
                policy=self._retry_policy,
                logger=LOGGER,
            )
        )

    def fetch_option_chain(self, symbol: str, expiration: str) -> object:
        return call_with_retries(
            f"Yahoo option chain {symbol} {expiration}",
            lambda: self._yf.Ticker(symbol).option_chain(expiration),
            policy=self._retry_policy,
            logger=LOGGER,
        )
