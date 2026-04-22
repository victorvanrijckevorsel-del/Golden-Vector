"""Builds the fetch plan for the raw foundation pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from golden_vector.contracts.config_models import UniverseConfig, UniverseTicker

FX_SYMBOL_BY_CURRENCY: dict[str, str] = {
    "AUD": "AUDUSD=X",
    "CAD": "CADUSD=X",
    "EUR": "EURUSD=X",
    "GBP": "GBPUSD=X",
    "SEK": "SEKUSD=X",
    "USD": "USD",
    "ZAR": "ZARUSD=X",
}


@dataclass(frozen=True)
class EquityFetchTarget:
    ticker: str
    exchange: str | None
    currency: str
    yahoo_symbol: str


@dataclass(frozen=True)
class FxFetchTarget:
    base_currency: str
    quote_currency: str
    yahoo_symbol: str


@dataclass(frozen=True)
class GoldFetchTarget:
    yahoo_symbol: str


@dataclass(frozen=True)
class MarketSnapshotTarget:
    ticker: str
    currency: str
    yahoo_symbol: str


@dataclass(frozen=True)
class FoundationRegistry:
    equity_targets: list[EquityFetchTarget]
    fx_targets: list[FxFetchTarget]
    gold_target: GoldFetchTarget
    market_snapshot_targets: list[MarketSnapshotTarget]

    def summary(self) -> dict[str, object]:
        return {
            "equity_target_count": len(self.equity_targets),
            "fx_target_count": len(self.fx_targets),
            "market_snapshot_target_count": len(self.market_snapshot_targets),
            "equity_tickers": [target.ticker for target in self.equity_targets],
            "fx_pairs": [target.yahoo_symbol for target in self.fx_targets],
            "gold_symbol": self.gold_target.yahoo_symbol,
            "market_snapshot_tickers": [
                target.ticker for target in self.market_snapshot_targets
            ],
        }


def build_foundation_registry(
    universe: UniverseConfig,
    gold_symbol: str = "GC=F",
) -> FoundationRegistry:
    foundation_tickers = _foundation_enabled_tickers(universe)
    if not foundation_tickers:
        raise ValueError(
            "Universe config must contain at least one active ticker enabled for Tool A or Tool B."
        )

    equity_targets = [
        EquityFetchTarget(
            ticker=ticker.ticker,
            exchange=ticker.exchange,
            currency=ticker.currency,
            yahoo_symbol=ticker.ticker,
        )
        for ticker in foundation_tickers
    ]

    fx_targets = [
        FxFetchTarget(
            base_currency=currency,
            quote_currency="USD",
            yahoo_symbol=FX_SYMBOL_BY_CURRENCY[currency],
        )
        for currency in _foundation_enabled_non_usd_currencies(universe)
        if currency in FX_SYMBOL_BY_CURRENCY
    ]

    market_snapshot_targets = [
        MarketSnapshotTarget(
            ticker=ticker.ticker,
            currency=ticker.currency,
            yahoo_symbol=ticker.ticker,
        )
        for ticker in foundation_tickers
        if ticker.tool_b_enabled
    ]

    return FoundationRegistry(
        equity_targets=equity_targets,
        fx_targets=fx_targets,
        gold_target=GoldFetchTarget(yahoo_symbol=gold_symbol),
        market_snapshot_targets=market_snapshot_targets,
    )


def find_universe_ticker(universe: UniverseConfig, ticker: str) -> UniverseTicker:
    for item in universe.tickers:
        if item.ticker == ticker:
            return item
    raise KeyError(f"Ticker not found in universe config: {ticker}")


def missing_fx_currencies(universe: UniverseConfig) -> list[str]:
    configured = _foundation_enabled_non_usd_currencies(universe)
    return [currency for currency in configured if currency not in FX_SYMBOL_BY_CURRENCY]


def _foundation_enabled_tickers(universe: UniverseConfig) -> list[UniverseTicker]:
    return [
        ticker
        for ticker in universe.tickers
        if ticker.active and (ticker.tool_a_enabled or ticker.tool_b_enabled)
    ]


def _foundation_enabled_non_usd_currencies(universe: UniverseConfig) -> list[str]:
    return sorted(
        {
            ticker.currency
            for ticker in _foundation_enabled_tickers(universe)
            if ticker.currency != "USD"
        }
    )
