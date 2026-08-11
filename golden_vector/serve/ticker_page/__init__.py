"""Redesigned ticker-page serve package (plan §13 M2/M3).

Read-only spine: every number rendered here comes from one of the five
persisted ticker-page artifacts resolved through the model-state loaders.
No arithmetic, coalescing, or eligibility resolution happens in this package —
the model layer emits display-ready columns and the sections only format them.
"""

from golden_vector.serve.ticker_page.data import TickerPageData, load_ticker_page_data
from golden_vector.serve.ticker_page.sections import (
    render_cost_downside_card,
    render_currency_attribution_block,
    render_performance_section,
)

__all__ = [
    "TickerPageData",
    "load_ticker_page_data",
    "render_cost_downside_card",
    "render_currency_attribution_block",
    "render_performance_section",
]
