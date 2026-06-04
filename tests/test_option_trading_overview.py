from __future__ import annotations

from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingOverviewData,
    OptionTradingRow,
    OptionTradingSourceContext,
)
from golden_vector.serve.overview_option_trading import _render_option_trading_overview_page


def test_option_trading_overview_renders_structured_rows_and_filters():
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(
            rows=(
                OptionTradingRow(
                    ticker="AEM",
                    structural_delta_core=1.3,
                    down_beta_core=1.4,
                    up_beta_core=1.1,
                    confidence_label="HIGH",
                    confidence_score=0.9,
                    iv_percentile_cross_sectional=40.0,
                    iv_skew_60d=0.08,
                    iv_rv_ratio_60d=1.25,
                    optionability_tier="directly_hedgeable",
                    put_status="tradable",
                    call_status="tradable",
                    pnl_put_at_minus10_60d=1.25,
                    pnl_call_at_plus10_60d=2.50,
                    notes=("candidate ok",),
                    current_stock_price=174.96,
                ),
            ),
            source_context=OptionTradingSourceContext(
                as_of_date="2026-06-01",
                refresh_run_id="options-run",
            ),
            liquidity_measurements=(
                OptionLiquidityMeasurement(
                    group_label="Benchmark ETFs",
                    ticker_count=2,
                    contract_count=120,
                    median_rel_spread=0.08,
                    median_open_interest=300.0,
                    median_volume=40.0,
                    median_near_spot_depth=12.0,
                    tradable_count=80,
                    watch_count=30,
                    no_trade_count=10,
                ),
                OptionLiquidityMeasurement(
                    group_label="Single-stock miners",
                    ticker_count=1,
                    contract_count=30,
                    median_rel_spread=0.18,
                    median_open_interest=80.0,
                    median_volume=8.0,
                    median_near_spot_depth=4.0,
                    tradable_count=4,
                    watch_count=8,
                    no_trade_count=18,
                ),
            ),
        )
    )

    assert "Option Trading" in html
    assert "Cached options snapshot: 2026-06-01; screening only" in html
    assert "Method" in html
    assert "Last is informational only" in html
    assert "/ticker/AEM?lens=option-trading#option-trading" in html
    assert "option-trading-table" in html
    assert "Stock Price" in html
    assert "174.96" in html
    assert "Tool A Confidence" in html
    assert "IV %ile" in html
    assert "IV Skew 60d" not in html
    assert "IV/RV 60d" not in html
    assert "data-filter-column=\"put_status\"" in html
    assert "data-filter-column=\"call_status\"" in html
    assert "data-filter-column=\"optionability\"" not in html
    assert "Tradable candidate" in html
    assert "Snapshot Date" in html
    assert "2026-06-01" in html
    assert "Cached Liquidity Check" in html
    assert "Benchmark ETFs" in html
    assert "Single-stock miners" in html
    assert "Tradable" in html
    assert "Watch" in html
    assert "No-trade" in html
    assert ">80<" in html
    assert ">18<" in html
    assert "8.0%" in html
    assert "If Benchmark ETFs show zero contracts" in html
    assert "Proxy alternatives stay hidden unless this cached check supports them." in html
    assert "Put P&amp;L/share @ Gold -10% (60d)" not in html
    assert "Call P&amp;L/share @ Gold +10% (60d, context)" not in html
    assert "2.50" not in html
    assert "Optionability" not in html
    assert "candidate ok" in html
    assert "markdown-report" not in html


def test_option_trading_overview_renders_empty_state():
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(rows=(), reason="No options snapshot exists yet.")
    )

    assert "No options snapshot exists yet." in html
    assert "python main.py update-data" in html
    assert "option-trading-table" not in html


def test_option_trading_overview_discloses_risk_free_rate_fallback():
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(
            rows=(),
            reason="No rows.",
            risk_free_rate_is_fallback=True,
        )
    )

    assert "Risk-free rate was missing" in html
    assert "0% rate fallback" in html


def test_option_trading_overview_hides_raw_thin_status_label():
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(
            rows=(
                OptionTradingRow(
                    ticker="FSM",
                    structural_delta_core=1.2,
                    down_beta_core=1.4,
                    up_beta_core=1.1,
                    confidence_label="HIGH",
                    confidence_score=0.9,
                    iv_percentile_cross_sectional=77.0,
                    iv_skew_60d=None,
                    iv_rv_ratio_60d=None,
                    optionability_tier="directly_hedgeable",
                    put_status="none",
                    call_status="none",
                    pnl_put_at_minus10_60d=None,
                    pnl_call_at_plus10_60d=None,
                    notes=(),
                    current_stock_price=50.0,
                ),
            )
        )
    )

    assert "No liquid candidate" in html
    assert ">none<" not in html
