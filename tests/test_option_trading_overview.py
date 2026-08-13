from __future__ import annotations

import json

from golden_vector.app.config import load_app_config
from golden_vector.hedge.option_trading import (
    OptionLiquidityMeasurement,
    OptionTradingOverviewData,
    OptionTradingRow,
    OptionTradingSourceContext,
)
from golden_vector.serve.overview_option_trading import (
    _render_horizon_selector,
    _render_option_trading_overview_page,
    _resolve_selected_horizon,
    _selected_side,
)
from tests.helpers import build_test_paths, source_date_n_trading_days_old


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
                    iv_skew_signal=0.08,
                    iv_rv_ratio_signal=1.25,
                    optionability_tier="directly_hedgeable",
                    put_status="tradable",
                    call_status="tradable",
                    pnl_put_at_context=1.25,
                    pnl_call_at_context=2.50,
                        notes=("candidate ok",),
                        current_stock_price=174.96,
                        source_as_of_date="2026-05-27",
                        captured_at_utc="2026-05-27T20:00:00Z",
                        carried_forward=True,
                        display_staleness_trading_days=3,
                        display_freshness_status="STALE",
                ),
            ),
            source_context=OptionTradingSourceContext(
                as_of_date="2026-06-01",
                refresh_run_id="options-run",
                tool_a_refresh_run_ids=("tool-run",),
                tool_b_refresh_run_ids=("tool-run",),
                context_warnings=(
                    "Refresh context is mixed: options snapshot uses options-run; "
                    "Tool A uses tool-run; Tool B uses tool-run. Scenario betas and "
                    "fundamentals may lag the option chains. Run python main.py "
                    "refresh to realign the full model outputs.",
                ),
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
    assert '<div class="terminal-density">' in html
    assert '<select name="option_horizon">' not in html
    assert 'class="btn btn-primary"' not in html
    assert "Latest available option data is shown per ticker" in html
    assert "Latest available" in html
    assert "Stored snapshot" in html
    assert "May 27, 2026" in html
    assert "collected May 27, 4:00 PM ET" in html
    assert "3 US trading days old" in html
    assert "Refresh context is mixed" in html
    assert "Run python main.py refresh" in html
    assert "Method" in html
    assert "Last is informational only" in html
    assert "/ticker/AEM?lens=option-trading#option-trading" in html
    assert "option-trading-table" in html
    assert "Stock Price" in html
    assert "174.96" in html
    assert "Gold Sensitivity Confidence" in html
    assert "IV %ile" in html
    assert "IV Skew 60d" not in html
    assert "IV/RV 60d" not in html
    assert "data-filter-column=\"put_status\"" in html
    assert "data-filter-column=\"call_status\"" in html
    assert "data-filter-column=\"optionability\"" not in html
    assert "Tradable candidate" in html
    assert "Latest Available" in html
    assert "May 27, 2026" in html
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
    assert '<div class="terminal-density">' in html


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
                    iv_skew_signal=None,
                    iv_rv_ratio_signal=None,
                    optionability_tier="directly_hedgeable",
                    put_status="none",
                    call_status="none",
                    pnl_put_at_context=None,
                    pnl_call_at_context=None,
                    notes=(),
                    current_stock_price=50.0,
                ),
            )
        )
    )

    assert "No liquid candidate" in html
    assert ">none<" not in html


# ---- Part A: overview horizon selector ----


def _per_horizon_row() -> OptionTradingRow:
    return OptionTradingRow(
        ticker="AEM",
        structural_delta_core=1.3,
        down_beta_core=1.4,
        up_beta_core=1.1,
        confidence_label="HIGH",
        confidence_score=0.9,
        iv_percentile_cross_sectional=40.0,
        iv_skew_signal=0.08,
        iv_rv_ratio_signal=1.25,
        optionability_tier="directly_hedgeable",
        put_status="tradable",
        call_status="tradable",
        pnl_put_at_context=1.25,
        pnl_call_at_context=2.50,
        notes=("candidate ok",),
        current_stock_price=174.96,
        most_liquid_put_expiration="ML-PUT-EXP",
        most_liquid_call_expiration="ML-CALL-EXP",
        per_horizon_status_json=json.dumps(
            {
                "P": {"230": {"status": "watch", "expiration": "EXP-230", "dte": 225}},
                "C": {},
            }
        ),
    )


def test_resolve_selected_horizon_validates_against_display_horizons():
    assert _resolve_selected_horizon(None, (90, 180, 230)) == "most_liquid"
    assert _resolve_selected_horizon("230", (90, 180, 230)) == "230"
    assert _resolve_selected_horizon("999", (90, 180, 230)) == "most_liquid"  # not configured
    assert _resolve_selected_horizon("most_liquid", (90, 180, 230)) == "most_liquid"


def test_selected_side_reads_persisted_map_not_recomputed():
    row = _per_horizon_row()
    per = json.loads(row.per_horizon_status_json)
    # Default = today's behaviour: overall status + most-liquid expiry.
    assert _selected_side(row, "put", selected_horizon="most_liquid", per_horizon=per) == (
        "tradable",
        "ML-PUT-EXP",
    )
    # Specific horizon = that horizon's stamped status + expiry.
    assert _selected_side(row, "put", selected_horizon="230", per_horizon=per) == (
        "watch",
        "EXP-230",
    )
    # A horizon with no stamped candidate is honestly "none", never faked.
    assert _selected_side(row, "call", selected_horizon="230", per_horizon=per) == ("none", None)


def test_horizon_selector_lists_configured_horizons():
    html = _render_horizon_selector("230", (90, 180, 230, 550))
    assert 'class="segmented-control"' in html
    assert 'href="/option-trading"' in html
    assert (
        'href="/option-trading?option_horizon=230" aria-current="true">230d</a>'
        in html
    )
    assert ">90d</a>" in html and ">550d</a>" in html
    assert "<select" not in html
    assert "<button" not in html


def test_overview_horizon_selector_changes_only_status_columns(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    horizon = sorted(app_config.hedge_readiness.display_horizons_days)[0]
    row = OptionTradingRow(
        ticker="AEM",
        structural_delta_core=1.3,
        down_beta_core=1.4,
        up_beta_core=1.1,
        confidence_label="HIGH",
        confidence_score=0.9,
        iv_percentile_cross_sectional=40.0,
        iv_skew_signal=0.08,
        iv_rv_ratio_signal=1.25,
        optionability_tier="directly_hedgeable",
        put_status="tradable",
        call_status="tradable",
        pnl_put_at_context=1.25,
        pnl_call_at_context=2.50,
        notes=("candidate ok",),
        current_stock_price=174.96,
        most_liquid_put_expiration="ML-PUT-EXP",
        per_horizon_status_json=json.dumps(
            {"P": {str(horizon): {"status": "watch", "expiration": "EXP-H", "dte": horizon - 5}}, "C": {}}
        ),
    )
    overview = OptionTradingOverviewData(rows=(row,))

    default_html = _render_option_trading_overview_page(overview, app_config=app_config)
    # Default selection + the most-liquid expiry are shown; the per-horizon expiry is not.
    assert 'href="/option-trading" aria-current="true">Most liquid</a>' in default_html
    assert "ML-PUT-EXP" in default_html
    assert "EXP-H" not in default_html

    horizon_html = _render_option_trading_overview_page(
        overview, app_config=app_config, option_horizon=str(horizon)
    )
    # The selected horizon's stamped put expiry now shows; the signal columns are
    # untouched by the selector (still rendered, horizon-agnostic).
    assert (
        f'href="/option-trading?option_horizon={horizon}" '
        f'aria-current="true">{horizon}d</a>' in horizon_html
    )
    assert "EXP-H" in horizon_html
    assert "Skew vs Benchmark" in horizon_html and "IV %ile" in horizon_html


# ---------------------------------------------------------------------------
# generation carry: the row columns are frozen, the generation is not
# ---------------------------------------------------------------------------


#: The row cell exactly -- the page lead also contains the words "stored
#: snapshots", so a bare substring match would not prove which one rendered.
_STORED_CELL = '<span class="hint cell-sub">Stored snapshot'
_CURRENT_CELL = '<span class="hint cell-sub">Current snapshot'


def _carried_generation_manifest(as_of_date: str) -> dict[str, object]:
    """A published manifest whose option domain is a carried-forward snapshot."""

    return {
        "state": "complete",
        "freshness_domains": {
            "option_artifacts": {
                "status": "CARRIED_FORWARD",
                "as_of_date": as_of_date,
                "reason": "The options provider failed for every ticker in this refresh.",
            }
        },
    }


def _fresh_looking_row(as_of_date: str) -> OptionTradingRow:
    """A row exactly as a skipped build leaves it: stamped current, and wrong.

    ``carried_forward`` is False and the display columns say LATEST because the
    LAST build that ran stamped them on the day it ran. Nothing rebuilt them.
    """

    return OptionTradingRow(
        ticker="AEM",
        structural_delta_core=1.3,
        down_beta_core=1.4,
        up_beta_core=1.1,
        confidence_label="HIGH",
        confidence_score=0.9,
        iv_percentile_cross_sectional=40.0,
        iv_skew_signal=0.08,
        iv_rv_ratio_signal=1.25,
        optionability_tier="directly_hedgeable",
        put_status="tradable",
        call_status="tradable",
        pnl_put_at_context=1.25,
        pnl_call_at_context=2.50,
        notes=("candidate ok",),
        current_stock_price=174.96,
        source_as_of_date=as_of_date,
        captured_at_utc=f"{as_of_date}T20:00:00Z",
        carried_forward=False,
        display_staleness_trading_days=0,
        display_freshness_status="LATEST",
    )


def test_carried_generation_relabels_rows_and_fires_the_stale_banner():
    """Regression: rows claimed "Current snapshot" through a full vendor outage.

    The row's own columns are frozen at LATEST, so both the label and the
    >=3-trading-day banner have to read the generation's age instead.
    """

    as_of = source_date_n_trading_days_old(3)
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(rows=(_fresh_looking_row(as_of),)),
        model_state_manifest=_carried_generation_manifest(as_of),
    )

    assert _STORED_CELL in html
    assert _CURRENT_CELL not in html
    assert "1 ticker(s) use option snapshots at least 3 US trading days old" in html
    assert "3 US trading days old" in html


def test_a_one_day_old_carried_generation_labels_stored_without_the_banner():
    """The healthy control: same frozen-column row, one trading day of carry."""

    as_of = source_date_n_trading_days_old(1)
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(rows=(_fresh_looking_row(as_of),)),
        model_state_manifest=_carried_generation_manifest(as_of),
    )

    assert _STORED_CELL in html
    assert _CURRENT_CELL not in html
    assert "ticker(s) use option snapshots at least" not in html
    assert "US trading days old" not in html


def test_a_current_generation_still_labels_rows_current():
    """The other control: nothing carried, so the row's own verdict stands."""

    as_of = source_date_n_trading_days_old(0)
    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(rows=(_fresh_looking_row(as_of),)),
        model_state_manifest={
            "state": "complete",
            "freshness_domains": {
                "option_artifacts": {"status": "OK", "as_of_date": as_of}
            },
        },
    )

    assert _CURRENT_CELL in html
    assert _STORED_CELL not in html
    assert "US trading days old" not in html
