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
        self._fast_info_cache: dict[str, dict[str, object]] = {}
        self._fast_info_cache_lock = Lock()

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
        cache_key = str(symbol).upper()
        with self._fast_info_cache_lock:
            cached = self._fast_info_cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        try:
            result = dict(
                call_with_retries(
                    f"Yahoo fast_info {symbol}",
                    lambda: self._yf.Ticker(symbol).fast_info,
                    policy=self._retry_policy,
                    logger=LOGGER,
                    sleep_func=self._sleep_func,
                    before_attempt=self._rate_limiter.wait,
                )
            )
            if result:
                with self._fast_info_cache_lock:
                    self._fast_info_cache[cache_key] = dict(result)
            return result
        except Exception:
            return {}

    def fetch_financial_statements(self, symbol: str) -> dict[str, object]:
        """Fetch raw Yahoo financial statements for one symbol.

        This intentionally returns Yahoo-shaped frames. Canonical field mapping,
        currency conversion, and data-quality decisions happen downstream after
        the raw frames have been persisted.
        """

        try:
            ticker = self._yf.Ticker(symbol)
            income_stmt = call_with_retries(
                f"Yahoo statements {symbol} income_stmt",
                lambda: ticker.income_stmt,
                policy=self._retry_policy,
                logger=LOGGER,
                sleep_func=self._sleep_func,
                before_attempt=self._rate_limiter.wait,
            )
            balance_sheet = call_with_retries(
                f"Yahoo statements {symbol} balance_sheet",
                lambda: ticker.balance_sheet,
                policy=self._retry_policy,
                logger=LOGGER,
                sleep_func=self._sleep_func,
                before_attempt=self._rate_limiter.wait,
            )
            cashflow = call_with_retries(
                f"Yahoo statements {symbol} cashflow",
                lambda: ticker.cashflow,
                policy=self._retry_policy,
                logger=LOGGER,
                sleep_func=self._sleep_func,
                before_attempt=self._rate_limiter.wait,
            )
            return {
                "income_stmt": income_stmt,
                "balance_sheet": balance_sheet,
                "cashflow": cashflow,
                "financialCurrency": self._financial_currency(ticker),
            }
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

    def _financial_currency(self, ticker: object) -> str | None:
        try:
            value = call_with_retries(
                "Yahoo statements financial currency",
                lambda: getattr(ticker, "financial_currency", None),
                policy=self._retry_policy,
                logger=LOGGER,
                sleep_func=self._sleep_func,
                before_attempt=self._rate_limiter.wait,
            )
        except Exception:
            value = None
        if value:
            return str(value).upper()
        try:
            info = call_with_retries(
                "Yahoo statements info currency",
                lambda: getattr(ticker, "info", None) or {},
                policy=self._retry_policy,
                logger=LOGGER,
                sleep_func=self._sleep_func,
                before_attempt=self._rate_limiter.wait,
            )
        except Exception:
            info = {}
        if isinstance(info, Mapping):
            value = info.get("financialCurrency") or info.get("currency")
            if value:
                return str(value).upper()
        try:
            fast_info = dict(
                call_with_retries(
                    "Yahoo statements fast_info currency",
                    lambda: getattr(ticker, "fast_info", {}) or {},
                    policy=self._retry_policy,
                    logger=LOGGER,
                    sleep_func=self._sleep_func,
                    before_attempt=self._rate_limiter.wait,
                )
            )
        except Exception:
            fast_info = {}
        value = fast_info.get("currency")
        return str(value).upper() if value else None
