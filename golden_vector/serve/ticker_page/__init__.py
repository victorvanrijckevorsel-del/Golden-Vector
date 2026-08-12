"""Redesigned ticker-page serve package (plan §13 M2/M3).

Read-only spine: every number rendered here comes from one of the five
persisted ticker-page artifacts resolved through the model-state loaders.
No arithmetic, coalescing, or eligibility resolution happens in this package —
the model layer emits display-ready columns and the sections only format them.
"""

from golden_vector.serve.ticker_page.behaviour import (
    LabRequest,
    clear_lab_render_cache,
    parse_lab_request,
    render_market_behaviour_section,
    render_window_switcher,
)
from golden_vector.serve.ticker_page.compare import (
    COMPARE_SECTION_ID,
    SCORE_BUILDER_PAYLOAD_ID,
    SCORE_BUILDER_STATE_PARAM,
    build_score_builder_payload,
    render_compare_section,
)
from golden_vector.serve.ticker_page.corporate import (
    GOLD_DIAL_PAYLOAD_ID,
    YAHOO_RESILIENCE_REASON,
    build_gold_dial_payload,
    render_corporate_finance_section,
    render_gold_dial_control,
)
from golden_vector.serve.ticker_page.data import TickerPageData, load_ticker_page_data
from golden_vector.serve.ticker_page.options import (
    SIZING_PAYLOAD_ID,
    TARGET_WINDOW_PARAM,
    build_sizing_payload,
    render_options_section,
    resolve_options_availability,
    resolve_target_window,
)
from golden_vector.serve.ticker_page.sections import (
    render_cost_downside_card,
    render_currency_attribution_block,
    render_performance_section,
)

__all__ = [
    "COMPARE_SECTION_ID",
    "GOLD_DIAL_PAYLOAD_ID",
    "LabRequest",
    "SCORE_BUILDER_PAYLOAD_ID",
    "SCORE_BUILDER_STATE_PARAM",
    "SIZING_PAYLOAD_ID",
    "TARGET_WINDOW_PARAM",
    "TickerPageData",
    "YAHOO_RESILIENCE_REASON",
    "build_gold_dial_payload",
    "build_score_builder_payload",
    "build_sizing_payload",
    "clear_lab_render_cache",
    "load_ticker_page_data",
    "parse_lab_request",
    "render_compare_section",
    "render_options_section",
    "resolve_options_availability",
    "resolve_target_window",
    "render_corporate_finance_section",
    "render_cost_downside_card",
    "render_currency_attribution_block",
    "render_gold_dial_control",
    "render_market_behaviour_section",
    "render_performance_section",
    "render_window_switcher",
]
