from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from threading import Lock
from time import sleep

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.ingestion.fetch_options import (
    OPTIONS_STATUS_ERROR,
    OPTIONS_STATUS_SUCCESS,
)
from golden_vector.ingestion.options_phase import (
    _OptionFetchTarget,
    _fetch_option_targets,
)
from tests.helpers import build_test_paths


@dataclass
class _OptionChain:
    puts: pd.DataFrame
    calls: pd.DataFrame


def test_fetch_option_targets_uses_bounded_workers_and_preserves_order(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    client = _TrackingOptionsClient(
        fixture=fixture,
        failing_symbols={"BBB"},
    )
    targets = [
        _OptionFetchTarget(
            ticker=symbol,
            yahoo_symbol=symbol,
            vehicle_type="single_stock",
        )
        for symbol in ("AAA", "BBB", "CCC", "DDD")
    ]

    results = _fetch_option_targets(
        targets=targets,
        client=client,
        app_config=app_config,
        as_of_date=date(2026, 5, 29),
        max_workers=2,
    )

    assert client.max_in_flight <= 2
    assert client.max_in_flight > 1
    assert [item.target.ticker for item in results] == ["AAA", "BBB", "CCC", "DDD"]
    assert [item.result.status for item in results] == [
        OPTIONS_STATUS_SUCCESS,
        OPTIONS_STATUS_ERROR,
        OPTIONS_STATUS_SUCCESS,
        OPTIONS_STATUS_SUCCESS,
    ]
    assert [item.collection_event["ticker"] for item in results] == [
        "AAA",
        "BBB",
        "CCC",
        "DDD",
    ]


class _TrackingOptionsClient:
    def __init__(
        self,
        *,
        fixture: pd.DataFrame,
        failing_symbols: set[str] | None = None,
    ) -> None:
        self.fixture = fixture
        self.failing_symbols = failing_symbols or set()
        self._lock = Lock()
        self._in_flight = 0
        self.max_in_flight = 0

    def fetch_options_expirations(self, symbol: str) -> list[str]:
        with self._lock:
            self._in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            sleep(0.02)
            if symbol in self.failing_symbols:
                raise RuntimeError(f"synthetic options failure for {symbol}")
            return sorted(self.fixture["expiration"].astype(str).unique().tolist())
        finally:
            with self._lock:
                self._in_flight -= 1

    def fetch_fast_info(self, symbol: str) -> dict[str, object]:
        return {"last_price": 50.0}

    def fetch_option_chain(self, symbol: str, expiration: str) -> _OptionChain:
        rows = self.fixture[self.fixture["expiration"].astype(str) == expiration]
        puts = rows[rows["option_type"] == "P"].drop(columns=["option_type"])
        calls = rows[rows["option_type"] == "C"].drop(columns=["option_type"])
        return _OptionChain(
            puts=puts.reset_index(drop=True),
            calls=calls.reset_index(drop=True),
        )
