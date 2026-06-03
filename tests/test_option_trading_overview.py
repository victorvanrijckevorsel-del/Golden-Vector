from __future__ import annotations

from golden_vector.hedge.option_trading import (
    OptionTradingOverviewData,
    OptionTradingRow,
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
                    put_status="available",
                    call_status="available",
                    pnl_put_at_minus10_60d=1.25,
                    pnl_call_at_plus10_60d=2.50,
                    notes=("candidate ok",),
                ),
            )
        )
    )

    assert "Option Trading" in html
    assert "Descriptive stress-sensitivity view" in html
    assert "Buying puts/calls can be right on direction" in html
    assert "/ticker/AEM?lens=option-trading#option-trading" in html
    assert "option-trading-table" in html
    assert "Plain Beta" in html
    assert "IV Skew 60d" in html
    assert "IV/RV 60d" in html
    assert "8.0%" in html
    assert "downside protection is more expensive" in html
    assert "options look expensive versus how much" in html
    assert "data-filter-column=\"put_status\"" in html
    assert "data-filter-column=\"call_status\"" in html
    assert "Put P&amp;L/share @ Gold -10% (60d)" in html
    assert "Call P&amp;L/share @ Gold +10% (60d, context)" in html
    assert "2.50" in html
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
