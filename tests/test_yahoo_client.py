from __future__ import annotations

import pandas as pd

from golden_vector.ingestion.collection_resilience import RetryPolicy
from golden_vector.ingestion.yahoo_client import YahooClient, YahooRateLimiter


def test_yahoo_rate_limiter_spaces_concurrent_attempts_without_burst():
    sleeps: list[float] = []
    now = {"value": 0.0}
    limiter = YahooRateLimiter(
        0.25,
        sleep_func=sleeps.append,
        monotonic_func=lambda: now["value"],
    )

    limiter.wait()
    limiter.wait()
    limiter.wait()

    assert sleeps == [0.25, 0.50]


def test_yahoo_client_rate_limits_before_retry_attempts():
    sleeps: list[float] = []
    fake_yf = _FakeYFinance(fail_first_history=True)
    client = YahooClient(
        retry_policy=RetryPolicy(
            max_attempts=2,
            initial_backoff_seconds=0.0,
            throttle_seconds=0.5,
        ),
        yf_module=fake_yf,
        sleep_func=sleeps.append,
        monotonic_func=lambda: 0.0,
    )

    frame = client.fetch_history("NEM")

    assert not frame.empty
    assert fake_yf.tickers["NEM"].history_calls == 2
    assert sleeps == [0.5]


class _FakeYFinance:
    def __init__(self, *, fail_first_history: bool = False) -> None:
        self.fail_first_history = fail_first_history
        self.tickers: dict[str, _FakeTicker] = {}

    def Ticker(self, symbol: str) -> "_FakeTicker":
        ticker = self.tickers.get(symbol)
        if ticker is None:
            ticker = _FakeTicker(fail_first_history=self.fail_first_history)
            self.tickers[symbol] = ticker
        return ticker


class _FakeTicker:
    def __init__(self, *, fail_first_history: bool) -> None:
        self.fail_first_history = fail_first_history
        self.history_calls = 0
        self.fast_info = {"last_price": 50.0}
        self.options = []

    def history(self, **_: object) -> pd.DataFrame:
        self.history_calls += 1
        if self.fail_first_history and self.history_calls == 1:
            raise RuntimeError("temporary")
        return pd.DataFrame(
            {
                "Date": ["2026-01-30"],
                "Open": [10.0],
                "High": [11.0],
                "Low": [9.0],
                "Close": [10.5],
                "Adj Close": [10.4],
                "Volume": [1000],
            }
        )
