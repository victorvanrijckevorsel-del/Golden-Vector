"""Milestone D1: column-help registry + Option Trading adoption.

Proves the hover layer's core promises: threshold values come from the loaded
config (never hard-coded template text), the row-level skew hover shows the
actual stored calculation, vague labels are renamed at every site, and the
serve layer only renders persisted fields.
"""

from __future__ import annotations

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.hedge.option_trading import OptionTradingOverviewData
from golden_vector.serve.column_help import column_help_text, help_term, help_th
from golden_vector.serve.option_signal_render import option_signal_skew_hover
from golden_vector.serve.overview_option_trading import (
    _render_liquidity_measurements,
    _render_option_trading_overview_page,
)


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


def test_tradable_tooltip_renders_live_config_thresholds():
    config = _app_config()

    text = column_help_text("tradable_count", app_config=config)

    assert text is not None
    spread = config.hedge_readiness.option_liquidity_tradable_spread_pct
    premium = config.hedge_readiness.option_liquidity_min_premium
    assert f"{spread * 100:g}%" in text
    assert f"{premium:g}" in text
    assert "Higher count is better." in text
    # The chain-vs-slot distinction must be stated so the two tradable rules
    # are never conflated.
    assert "stricter per-bucket rule" in text


def test_changing_config_threshold_changes_tooltip_text():
    config = _app_config()
    tweaked = config.model_copy(
        update={
            "hedge_readiness": config.hedge_readiness.model_copy(
                update={"option_liquidity_tradable_spread_pct": 0.33}
            )
        }
    )

    base_text = column_help_text("tradable_count", app_config=config)
    tweaked_text = column_help_text("tradable_count", app_config=tweaked)

    assert base_text != tweaked_text
    assert "33%" in tweaked_text


def test_tooltip_without_config_still_shows_meaning_and_direction():
    text = column_help_text("median_tradable_spread", app_config=None)

    assert text is not None
    assert "tradable contracts only" in text
    assert "Lower is better." in text


def test_help_th_renders_attributes_and_escapes():
    config = _app_config()

    html = help_th(
        "Skew vs Benchmark",
        key="skew_vs_benchmark",
        app_config=config,
        col_name="skew",
        sort_numeric=True,
    )

    assert html.startswith("<th ")
    assert 'data-col-name="skew"' in html
    assert "data-sort-numeric" in html
    # Transport is the dotted-underline help-term + data-help popover, not
    # the native title= attribute.
    assert 'class="help-term"' in html
    assert "data-help=\"" in html
    assert "title=" not in html
    assert ">Skew vs Benchmark<" in html

    plain = help_th("Notes", col_name="notes")
    assert "help-term" not in plain
    assert ">Notes</th>" in plain


def test_help_term_inline_and_explicit_text():
    config = _app_config()
    # Inline use (not a header) renders the same affordance.
    inline = help_term("Skew vs Benchmark", key="skew_vs_benchmark", app_config=config)
    assert inline.startswith("<span class=\"help-term\"")
    assert "tabindex=\"0\"" in inline
    # Explicit text bypasses the registry for one-off explanations.
    custom = help_term("EV/EBITDA", text="Enterprise value over forward EBITDA.")
    assert "Enterprise value over forward EBITDA." in custom
    # No key, no text -> plain escaped label.
    assert help_term("Plain") == "Plain"


def test_unknown_key_yields_no_tooltip():
    assert column_help_text("not_a_registered_column", app_config=_app_config()) is None


def test_single_stock_skew_hover_shows_full_calculation():
    signal = {
        "ticker": "AU",
        "benchmark_symbol": "GDXJ",
        "option_vehicle_type": "single_stock",
        "signal_horizon_days": 60,
        "name_skew_60d": 0.081,
        "sector_skew_60d": 0.048,
        "skew_residual_60d": 0.033,
    }

    hover = option_signal_skew_hover(signal)

    assert hover is not None
    assert "AU stock skew: 8.1 vol pts" in hover
    assert "Benchmark used: GDXJ" in hover
    assert "GDXJ benchmark skew: 4.8 vol pts" in hover
    assert "Difference: 3.3 vol pts" in hover
    assert "richer than calls versus GDXJ" in hover


def test_benchmark_row_skew_hover_shows_absolute_baseline():
    signal = {
        "ticker": "GDXJ",
        "benchmark_symbol": "GDXJ",
        "option_vehicle_type": "benchmark_etf",
        "signal_horizon_days": 60,
        "name_skew_60d": -0.025,
        "sector_skew_60d": -0.025,
        "skew_residual_60d": 0.0,
    }

    hover = option_signal_skew_hover(signal)

    assert hover is not None
    assert "GDXJ put/call skew: -2.5 vol pts" in hover
    assert "sector baseline" in hover
    assert "Difference" not in hover


def test_skew_hover_handles_missing_signal():
    assert option_signal_skew_hover(None) is None
    assert option_signal_skew_hover({}) is None


def test_overview_page_renames_labels_and_carries_tooltips():
    config = _app_config()
    import pandas as pd

    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(rows=(), liquidity_measurements=()),
        option_signal_summary=pd.DataFrame(),
        app_config=config,
    )

    # The empty-rows page still proves filter/label wiring is absent of old names.
    assert "Skew Read" not in html
    assert ">Cost<" not in html


def test_liquidity_table_headers_have_config_sourced_tooltips():
    from golden_vector.hedge.option_trading import OptionLiquidityMeasurement

    config = _app_config()
    measurements = (
        OptionLiquidityMeasurement(
            group_label="Benchmark ETFs",
            ticker_count=2,
            contract_count=10,
            median_rel_spread=0.12,
            median_open_interest=150.0,
            median_volume=12.0,
            median_near_spot_depth=6.0,
            tradable_count=4,
            watch_count=3,
            no_trade_count=3,
        ),
    )

    html = _render_liquidity_measurements(measurements, app_config=config)

    # Label now rides inside the dotted-underline help-term span.
    assert "Tradable<span" in html or ">Tradable</span>" in html
    assert "class=\"help-term\"" in html
    spread = config.hedge_readiness.option_liquidity_tradable_spread_pct
    assert f"{spread * 100:g}%" in html
    # Tooltip text is sourced from the registry, not duplicated in the template.
    assert "valid bid/ask/mid" in html


def test_every_thresholds_callable_resolves_against_real_config():
    """Guard against silent tooltip degradation: a renamed config field would
    make a thresholds callable raise and the sentence silently drop."""

    from golden_vector.serve.column_help import COLUMN_HELP

    config = _app_config()
    checked = 0
    for key, spec in COLUMN_HELP.items():
        if spec.thresholds is None:
            continue
        text = spec.thresholds(config)
        assert isinstance(text, str) and text.strip(), f"empty thresholds for {key}"
        checked += 1
    assert checked >= 5


def test_tool_overview_registry_keys_resolve():
    """Every Tool A/B/C/D header key added in the D2 rollout must resolve to
    real help text against the live config (a renamed config field or a typo'd
    key would silently drop the explanation)."""

    config = _app_config()
    keys = [
        "tool_a_delta", "tool_a_gamma", "tool_a_asymmetry", "tool_a_confidence",
        "tool_a_volatility", "tool_a_score",
        "tool_c_downside_rank", "tool_c_upside_rank", "tool_c_down_beta",
        "tool_c_up_beta", "tool_c_down_hit_rate", "tool_c_up_hit_rate",
        "tool_b_score", "tool_b_enterprise_value", "tool_b_aisc", "tool_b_cash_margin",
        "tool_b_forward_ebitda", "tool_b_forward_pe", "tool_b_ev_ebitda",
        "tool_b_fcf_yield", "tool_b_leverage", "tool_b_reserve_life",
        "tool_d_quality_rank", "tool_d_gold_used", "tool_d_interest_cover",
        "tool_d_survival_distance", "tool_d_breakeven", "tool_d_fcf_breakeven",
        "tool_d_debt_stress", "tool_d_cost_curve", "tool_d_fragility",
        "tool_d_leverage", "tool_d_ev_ebitda_context", "tool_d_fcf_yield_context",
    ]
    for key in keys:
        text = column_help_text(key, app_config=config)
        assert text and text.strip(), f"no help text for {key}"
    # Config-sourced threshold sentences actually appear.
    assert "x" in column_help_text("tool_b_leverage", app_config=config)
    assert "%" in column_help_text("tool_c_down_hit_rate", app_config=config)
