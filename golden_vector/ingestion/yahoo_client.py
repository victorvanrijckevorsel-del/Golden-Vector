"""Thin wrapper around yfinance."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from threading import Lock
from time import monotonic as default_monotonic
from time import sleep as default_sleep
from typing import Any

import pandas as pd

from golden_vector.ingestion.collection_resilience import RetryPolicy, call_with_retries

LOGGER = logging.getLogger(__name__)


class YahooRateLimiter:
    """Thread-safe no-burst limiter for unofficial Yahoo calls."""

    def __init__(
        self,
        min_interval_seconds: float,
        *,
        sleep_func: Callable[[float], None] = default_sleep,
        monotonic_func: Callable[[], float] = default_monotonic,
    ) -> None:
        self._min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._sleep_func = sleep_func
        self._monotonic_func = monotonic_func
        self._lock = Lock()
        self._next_allowed_at = 0.0

    def wait(self) -> None:
        if self._min_interval_seconds <= 0:
            return
        with self._lock:
            now = self._monotonic_func()
            sleep_seconds = max(0.0, self._next_allowed_at - now)
            self._next_allowed_at = max(now, self._next_allowed_at) + (
                self._min_interval_seconds
            )
        if sleep_seconds > 0:
            self._sleep_func(sleep_seconds)


class YahooClient:
    """Fetches market data from Yahoo Finance."""

    def __init__(
        self,
        *,
        retry_policy: RetryPolicy | None = None,
        yf_module: Any | None = None,
        sleep_func: Callable[[float], None] = default_sleep,
        monotonic_func: Callable[[], float] = default_monotonic,
    ) -> None:
        if yf_module is None:
            try:
                import yfinance as yf
            except ImportError as exc:  # pragma: no cover - depends on environment
                raise RuntimeError(
                    "yfinance is required to run the foundation pipeline. "
                    "Install dependencies from requirements.txt."
                ) from exc
            yf_module = yf
        policy = retry_policy or RetryPolicy()
        self._yf = yf_module
        self._rate_limiter = YahooRateLimiter(
            policy.throttle_seconds,
            sleep_func=sleep_func,
            monotonic_func=monotonic_func,
        )
        self._retry_policy = replace(policy, throttle_seconds=0.0)
        self._sleep_func = sleep_func

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
            sleep_func=self._sleep_func,
            before_attempt=self._rate_limiter.wait,
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
                    sleep_func=self._sleep_func,
                    before_attempt=self._rate_limiter.wait,
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
                sleep_func=self._sleep_func,
                before_attempt=self._rate_limiter.wait,
            )
        )

    def fetch_option_chain(self, symbol: str, expiration: str) -> object:
        return call_with_retries(
            f"Yahoo option chain {symbol} {expiration}",
            lambda: self._yf.Ticker(symbol).option_chain(expiration),
            policy=self._retry_policy,
            logger=LOGGER,
            sleep_func=self._sleep_func,
            before_attempt=self._rate_limiter.wait,
        )
