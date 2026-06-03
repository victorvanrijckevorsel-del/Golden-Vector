"""Shared plain-English disclosures for hedge and option-trading surfaces."""

LONG_OPTION_PREMIUM_CAVEAT = (
    "Buying puts/calls can be right on direction and still lose money if the "
    "move is too small or too slow - option premiums include a cost for "
    "volatility risk. For single stocks this cost is usually milder than for "
    "indexes, but it still matters."
)

OPTION_REPRICE_ASSUMPTION = (
    "Value Now and P&L Now are instant Black-Scholes model values using "
    "unchanged days-to-expiry and constant implied volatility; they are not "
    "live market quotes."
)

EXTREME_DOWNSIDE_SCENARIO_CAVEAT = (
    "approximate - linear beta can understate real downside; operating "
    "leverage / balance-sheet stress can make moves non-linear"
)

SENSITIVITY_RANKING_CAVEAT = (
    "Descriptive stress-sensitivity view: how a stock has behaved when gold "
    "fell, not a forecast of returns."
)
