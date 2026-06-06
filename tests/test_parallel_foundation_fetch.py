from __future__ import annotations

from threading import Lock
from time import sleep

import pandas as pd

from golden_vector.ingestion import fetch_equities as fetch_equities_module
from golden_vector.ingestion.fetch_equities import fetch_equity_histories
from golden_vector.ingestion.fetch_market_snapshot import fetch_market_snapshots
from golden_vector.ingestion.registry import EquityFetchTarget, MarketSnapshotTarget


def test_fetch_equity_histories_uses_bounded_workers_and_preserves_order():
    client = _TrackingHistoryClient(failing_symbols={"BBB"})
    targets = [
        EquityFetchTarget(ticker=symbol, exchange=None, currency="USD", yahoo_symbol=symbol)
        for symbol in ("AAA", "BBB", "CCC", "DDD")
    ]

    histories, statuses = fetch_equity_histories(
        client,
        targets,
        max_workers=2,
    )

    assert client.max_in_flight <= 2
    assert client.max_in_flight > 1
    assert [status.entity for status in statuses] == ["AAA", "BBB", "CCC", "DDD"]
    assert [status.status for status in statuses] == ["PASS", "FAIL", "PASS", "PASS"]
    assert list(histories) == ["AAA", "BBB", "CCC", "DDD"]
    assert histories["BBB"].empty
    assert not histories["AAA"].empty


def test_fetch_equity_histories_does_not_abort_when_empty_fallback_fails(monkeypatch):
    client = _TrackingHistoryClient(failing_symbols={"BBB"})
    target = EquityFetchTarget(
        ticker="BBB",
        exchange=None,
        currency="USD",
        yahoo_symbol="BBB",
    )
    original_standardize = fetch_equities_module.standardize_equity_history

    def fail_empty_standardize(**kwargs):
        if kwargs["frame"].empty:
            raise RuntimeError("synthetic empty fallback failure")
        return original_standardize(**kwargs)

    monkeypatch.setattr(
        fetch_equities_module,
        "standardize_equity_history",
        fail_empty_standardize,
    )

    histories, statuses = fetch_equity_histories(client, [target], max_workers=1)

    assert histories["BBB"].empty
    assert statuses[0].status == "FAIL"
    assert "empty-frame fallback failed" in str(statuses[0].message)


def test_fetch_market_snapshots_preserves_order_and_isolates_failures():
    client = _TrackingHistoryClient(failing_symbols={"BBB"})
    targets = [
        MarketSnapshotTarget(ticker=symbol, currency="USD", yahoo_symbol=symbol)
        for symbol in ("AAA", "BBB", "CCC")
    ]

    snapshots, statuses = fetch_market_snapshots(
        client,
        targets,
        source_run_id="run-1",
        max_workers=2,
    )

    assert client.max_in_flight <= 2
    assert [status.entity for status in statuses] == ["AAA", "BBB", "CCC"]
    assert [status.status for status in statuses] == ["PASS", "FAIL", "PASS"]
    assert snapshots["ticker"].tolist() == ["AAA", "CCC"]


class _TrackingHistoryClient:
    def __init__(self, *, failing_symbols: set[str] | None = None) -> None:
        self.failing_symbols = failing_symbols or set()
        self._lock = Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def fetch_history(self, symbol: str, **_: object) -> pd.DataFrame:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            sleep(0.02)
            if symbol in self.failing_symbols:
                raise RuntimeError(f"synthetic failure for {symbol}")
            return _history_frame()
        finally:
            with self._lock:
                self._in_flight -= 1

    def fetch_fast_info(self, symbol: str) -> dict[str, object]:
        if symbol in self.failing_symbols:
            raise RuntimeError(f"synthetic fast_info failure for {symbol}")
        return {"last_price": 10.5, "marketCap": 1000.0, "shares": 100.0}


def _history_frame() -> pd.DataFrame:
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
