"""Portfolio valuation primitives with explicit currency and unit provenance."""

from __future__ import annotations

import math
from dataclasses import dataclass

from golden_vector.normalize.price_units import PriceUnitAdjustment, price_unit_adjustment


@dataclass(frozen=True)
class ValuationInput:
    quantity: float
    price_local: float
    price_currency: str
    fx_rate_to_usd: float
    feed_currency: str | None = None


@dataclass(frozen=True)
class ValuationResult:
    price_local_major: float
    market_value_local: float
    market_value_usd: float
    price_currency: str
    fx_rate_to_usd: float
    price_scale_factor: float
    minor_unit_adjusted: bool


def value_line(input_value: ValuationInput) -> ValuationResult:
    """Value one line, preserving the old API during the boundary split."""

    if input_value.feed_currency:
        return value_raw_feed_quote(input_value)
    return value_major_unit_price(input_value)


def value_major_unit_price(input_value: ValuationInput) -> ValuationResult:
    """Value one line whose price is already in the currency's major unit."""

    return _value_with_adjustment(
        input_value,
        PriceUnitAdjustment(
            feed_currency=None,
            scale_factor=1.0,
            minor_unit_adjusted=False,
        ),
    )


def value_raw_feed_quote(input_value: ValuationInput) -> ValuationResult:
    """Value one raw vendor quote after applying its explicit feed unit scale."""

    if not input_value.feed_currency:
        raise ValueError("feed_currency is required when valuing a raw feed quote")
    return _value_with_adjustment(
        input_value,
        price_unit_adjustment(input_value.feed_currency),
    )


def _value_with_adjustment(
    input_value: ValuationInput,
    adjustment: PriceUnitAdjustment,
) -> ValuationResult:
    _require_positive("quantity", input_value.quantity)
    _require_positive("price_local", input_value.price_local)
    _require_positive("fx_rate_to_usd", input_value.fx_rate_to_usd)
    price_major = adjustment.apply(input_value.price_local)
    _require_positive("price_local after unit adjustment", price_major)
    market_value_local = input_value.quantity * price_major
    market_value_usd = market_value_local * input_value.fx_rate_to_usd
    return ValuationResult(
        price_local_major=price_major,
        market_value_local=market_value_local,
        market_value_usd=market_value_usd,
        price_currency=input_value.price_currency,
        fx_rate_to_usd=input_value.fx_rate_to_usd,
        price_scale_factor=adjustment.scale_factor,
        minor_unit_adjusted=adjustment.minor_unit_adjusted,
    )


def _require_positive(name: str, value: float) -> None:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be positive")
