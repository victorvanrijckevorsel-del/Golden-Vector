import pandas as pd

from golden_vector.contracts.config_models import BenchmarkTicker
from golden_vector.ingestion.fetch_benchmarks import fetch_benchmark_histories


def test_fetch_benchmark_histories_standardizes_active_benchmarks():
    client = _BenchmarkClient(
        pd.DataFrame(
            [
                {
                    "Date": "2026-05-28",
                    "Open": 40.0,
                    "High": 41.0,
                    "Low": 39.0,
                    "Close": 40.5,
                    "Adj Close": 40.5,
                    "Volume": 1000,
                }
            ]
        )
    )
    benchmarks = [BenchmarkTicker(ticker="GDX", yahoo_symbol="GDX")]

    histories, statuses = fetch_benchmark_histories(client, benchmarks)

    assert statuses[0].status == "PASS"
    assert statuses[0].row_count == 1
    assert histories["GDX"].loc[0, "ticker"] == "GDX"
    assert histories["GDX"].loc[0, "currency"] == "USD"
    assert histories["GDX"].loc[0, "feed_currency"] == "USD"
    assert histories["GDX"].loc[0, "exchange"] == "BENCHMARK"
    assert histories["GDX"].loc[0, "source_symbol"] == "GDX"


def test_fetch_benchmark_histories_skips_inactive_benchmarks():
    histories, statuses = fetch_benchmark_histories(
        _BenchmarkClient(pd.DataFrame()),
        [BenchmarkTicker(ticker="GDX", yahoo_symbol="GDX", active=False)],
    )

    assert histories == {}
    assert statuses == []


class _BenchmarkClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_history(self, symbol: str, period: str = "max", interval: str = "1d") -> pd.DataFrame:
        assert symbol == "GDX"
        assert period == "max"
        return self.frame

    def fetch_fast_info(self, symbol: str) -> dict[str, object]:
        assert symbol == "GDX"
        return {"currency": "USD"}
