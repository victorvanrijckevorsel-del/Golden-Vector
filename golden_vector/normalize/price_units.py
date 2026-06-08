"""Shared price-unit helpers for vendor feeds and portfolio valuation."""

from __future__ import annotations

from dataclasses import dataclass


MINOR_UNIT_CURRENCY_TAGS = frozenset({"GBp", "GBX", "ZAc", "ZAX", "ILA"})


@dataclass(frozen=True)
class PriceUnitAdjustment:
    feed_currency: str | None
    scale_factor: float
    minor_unit_adjusted: bool

    def apply(self, price: float) -> float:
        return float(price) * self.scale_factor


def price_unit_adjustment(feed_currency: object) -> PriceUnitAdjustment:
    """Return the vendor price scale for feeds quoted in minor units.

    The currency tag is intentionally case-sensitive: Yahoo's ``GBp`` is pence,
    while ``GBP`` is pounds. Treating those as equal would divide valid pound
    quotes by 100.
    """

    cleaned = str(feed_currency or "").strip()
    if cleaned in MINOR_UNIT_CURRENCY_TAGS:
        return PriceUnitAdjustment(
            feed_currency=cleaned,
            scale_factor=0.01,
            minor_unit_adjusted=True,
        )
    return PriceUnitAdjustment(
        feed_currency=cleaned or None,
        scale_factor=1.0,
        minor_unit_adjusted=False,
    )
