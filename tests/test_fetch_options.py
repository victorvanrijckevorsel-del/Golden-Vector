from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from golden_vector.ingestion.fetch_options import (
    OPTIONS_STATUS_EMPTY,
    OPTIONS_STATUS_ERROR,
    OPTIONS_STATUS_SUCCESS,
    fetch_options_chain,
)

FIXTURE_PATH = Path("tests/fixtures/options/aem_chain_20260529.parquet")


@dataclass
class _OptionChain:
    puts: pd.DataFrame
    calls: pd.DataFrame


def test_fetch_options_chain_standardizes_fixture_chain():
    fixture = pd.read_parquet(FIXTURE_PATH)
    client = _OptionsClient(fixture=fixture, underlying_price=50.0)

    result = fetch_options_chain(
        ticker="AEM",
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == OPTIONS_STATUS_SUCCESS
    assert result.options_available is True
    assert len(result.frame.index) == len(fixture.index)
    assert set(result.frame["option_type"]) == {"P", "C"}
    assert set(result.frame["expiration"]) == {"2026-06-19", "2026-07-17"}
    assert result.frame["ticker"].unique().tolist() == ["AEM"]
    assert result.frame["as_of_date"].unique().tolist() == ["2026-05-29"]
    assert result.frame["underlying_price"].unique().tolist() == [50.0]
    assert result.frame.loc[result.frame["bid"] == 0.0, "mid"].isna().all()
    assert result.frame["days_to_expiry"].min() == 21


def test_fetch_options_chain_returns_empty_when_no_expirations():
    client = _OptionsClient(fixture=pd.DataFrame(), underlying_price=50.0, expirations=[])

    result = fetch_options_chain(
        ticker="AAUC.TO",
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == OPTIONS_STATUS_EMPTY
    assert result.options_available is False
    assert result.frame.empty
    assert result.message == "No listed options returned by Yahoo."


def test_fetch_options_chain_returns_error_when_underlying_price_missing():
    fixture = pd.read_parquet(FIXTURE_PATH)
    client = _OptionsClient(fixture=fixture, underlying_price=None)

    result = fetch_options_chain(
        ticker="AEM",
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == OPTIONS_STATUS_ERROR
    assert result.frame.empty
    assert result.message == "Could not determine underlying price."


class _OptionsClient:
    def __init__(
        self,
        *,
        fixture: pd.DataFrame,
        underlying_price: float | None,
        expirations: list[str] | None = None,
    ) -> None:
        self.fixture = fixture
        self.underlying_price = underlying_price
        self.expirations = expirations

    def fetch_options_expirations(self, symbol: str) -> list[str]:
        if self.expirations is not None:
            return self.expirations
        return sorted(self.fixture["expiration"].astype(str).unique().tolist())

    def fetch_fast_info(self, symbol: str) -> dict[str, object]:
        if self.underlying_price is None:
            return {}
        return {"last_price": self.underlying_price}

    def fetch_option_chain(self, symbol: str, expiration: str) -> _OptionChain:
        rows = self.fixture[self.fixture["expiration"].astype(str) == expiration]
        puts = rows[rows["option_type"] == "P"].drop(columns=["option_type"])
        calls = rows[rows["option_type"] == "C"].drop(columns=["option_type"])
        return _OptionChain(puts=puts.reset_index(drop=True), calls=calls.reset_index(drop=True))
