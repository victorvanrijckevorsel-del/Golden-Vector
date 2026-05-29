"""Fetch hedge-layer benchmark histories outside the Tool A/B universe."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from golden_vector.contracts.config_models import BenchmarkTicker
from golden_vector.ingestion.standardize import standardize_equity_history
from golden_vector.ingestion.yahoo_client import YahooClient


@dataclass(frozen=True)
class BenchmarkFetchStatus:
    ticker: str
    source_symbol: str
    status: str
    row_count: int
    message: str | None = None


def fetch_benchmark_histories(
    client: YahooClient,
    benchmarks: list[BenchmarkTicker],
) -> tuple[dict[str, pd.DataFrame], list[BenchmarkFetchStatus]]:
    """Fetch benchmark ETF histories for hedge-layer proxy comparisons."""

    histories: dict[str, pd.DataFrame] = {}
    statuses: list[BenchmarkFetchStatus] = []
    for benchmark in benchmarks:
        if not benchmark.active:
            continue
        try:
            raw_history = client.fetch_history(benchmark.yahoo_symbol, period="max")
            fetched_at = datetime.now(timezone.utc)
            standardized = standardize_equity_history(
                ticker=benchmark.ticker,
                exchange="BENCHMARK",
                currency="USD",
                source_symbol=benchmark.yahoo_symbol,
                frame=raw_history,
                fetched_at=fetched_at,
            )
            histories[benchmark.ticker] = standardized
            status = "PASS" if not standardized.empty else "FAIL"
            message = None if status == "PASS" else "No benchmark history returned."
            statuses.append(
                BenchmarkFetchStatus(
                    ticker=benchmark.ticker,
                    source_symbol=benchmark.yahoo_symbol,
                    status=status,
                    row_count=len(standardized.index),
                    message=message,
                )
            )
        except Exception as exc:  # noqa: BLE001 - benchmark fetch is best-effort.
            histories[benchmark.ticker] = standardize_equity_history(
                ticker=benchmark.ticker,
                exchange="BENCHMARK",
                currency="USD",
                source_symbol=benchmark.yahoo_symbol,
                frame=pd.DataFrame(),
                fetched_at=datetime.now(timezone.utc),
            )
            statuses.append(
                BenchmarkFetchStatus(
                    ticker=benchmark.ticker,
                    source_symbol=benchmark.yahoo_symbol,
                    status="FAIL",
                    row_count=0,
                    message=str(exc),
                )
            )
    return histories, statuses
