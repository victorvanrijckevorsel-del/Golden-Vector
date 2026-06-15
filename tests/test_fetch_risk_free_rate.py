from datetime import date

import pandas as pd

from golden_vector.ingestion.fetch_risk_free_rate import fetch_risk_free_rate


def test_fetch_risk_free_rate_converts_irx_percent_to_decimal():
    client = _RiskFreeClient(
        pd.DataFrame(
            [
                {"Date": "2026-05-28", "Close": 4.25},
                {"Date": "2026-05-29", "Close": 4.32},
            ]
        )
    )

    rate = fetch_risk_free_rate(
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert rate == 0.0432


def test_fetch_risk_free_rate_handles_sub_one_percent_yield():
    # Low-rate regime: ^IRX prints a yield BELOW 1% (e.g. 0.50 = 0.50%). The old
    # magnitude heuristic left this as decimal 0.50 (= 50%), a 100x error feeding
    # Black-Scholes. It must convert to 0.005 like any other percent yield.
    client = _RiskFreeClient(pd.DataFrame([{"Date": "2026-05-29", "Close": 0.50}]))

    rate = fetch_risk_free_rate(
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert rate == 0.005


class _RiskFreeClient:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def fetch_history(self, symbol: str, period: str = "max", interval: str = "1d") -> pd.DataFrame:
        assert symbol == "^IRX"
        assert period == "5d"
        return self.frame
