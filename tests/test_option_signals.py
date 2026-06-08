from typing import Literal, cast

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.hedge.option_signals import (
    build_option_signal_artifacts,
)
from golden_vector.hedge.options_liquidity import OptionContractMetrics
from tests.helpers import build_test_paths


def test_option_signal_summary_uses_sector_relative_skew(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=0.08, skew_90=0.07),
                _feature("GDX", skew_60=0.03, skew_90=0.02, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.04, skew_90=0.03, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2),
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    summary = artifacts.summary.set_index("ticker")

    assert artifacts.publish_blockers == ()
    assert summary.loc["AEM", "benchmark_symbol"] == "GDX"
    assert summary.loc["AEM", "skew_residual_60d"] == 0.05
    assert summary.loc["AEM", "direction_label"] == "DOWNSIDE"
    assert summary.loc["AEM", "data_quality_label"] == "OK"
    assert "vs GDX" in summary.loc["AEM", "headline"]


def test_option_signal_benchmark_is_sector_gauge_not_self_residual(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("GDX", skew_60=0.05, skew_90=0.04, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.04, skew_90=0.03, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    row = artifacts.summary.set_index("ticker").loc["GDX"]

    assert row["benchmark_symbol"] == "GDX"
    assert row["name_skew_60d"] == 0.05
    assert row["sector_skew_60d"] == 0.05
    assert row["skew_residual_60d"] == 0.0
    assert row["direction_label"] == "DOWNSIDE"
    assert "sector puts" in row["direction_reason"]


def test_option_signal_missing_benchmark_blocks_publish(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=0.08, skew_90=0.07),
                _feature("GDX", skew_60=0.03, skew_90=0.02, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2),
            *_metrics("GDX", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    assert artifacts.publish_blockers
    assert "missing GDXJ" in artifacts.publish_blockers[0]


def test_option_signal_stale_benchmark_blocks_publish(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=0.08, skew_90=0.07),
                _feature("GDX", skew_60=0.03, skew_90=0.02, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.04, skew_90=0.03, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2),
            *_metrics("GDX", bid=0.0, ask=0.0),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    assert artifacts.summary.set_index("ticker").loc["GDX", "data_quality_label"] == "STALE_QUOTES"
    assert artifacts.publish_blockers


def test_option_signal_stale_single_name_marks_row_but_does_not_block_publish(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=0.08, skew_90=0.07),
                _feature("GDX", skew_60=0.03, skew_90=0.02, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.04, skew_90=0.03, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=0.0, ask=0.0),
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    assert artifacts.summary.set_index("ticker").loc["AEM", "data_quality_label"] == "STALE_QUOTES"
    assert artifacts.publish_blockers == ()


def test_option_signal_first_run_marks_oi_change_invalid(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=0.08, skew_90=0.07),
                _feature("GDX", skew_60=0.03, skew_90=0.02, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.04, skew_90=0.03, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2),
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    row = artifacts.summary.set_index("ticker").loc["AEM"]

    assert not bool(row["oi_change_valid"])
    assert pd.isna(row["oi_change_put"])
    assert pd.isna(row["oi_change_call"])


def test_option_signal_upside_read_requires_call_activity_confirmation(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=-0.04, skew_90=-0.04),
                _feature("GDX", skew_60=0.00, skew_90=0.00, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.00, skew_90=0.00, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2, put_volume=20, call_volume=20),
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    row = artifacts.summary.set_index("ticker").loc["AEM"]

    assert row["direction_candidate_label"] == "UPSIDE"
    assert row["direction_label"] == "NEUTRAL"
    assert row["activity_label"] == "NO_BULLISH_CONFIRMATION"
    assert "requires call-side activity confirmation" in row["direction_reason"]
    assert "unconfirmed upside" in row["headline"]


def test_option_signal_upside_read_confirms_with_call_activity(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=-0.04, skew_90=-0.04),
                _feature("GDX", skew_60=0.00, skew_90=0.00, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.00, skew_90=0.00, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2, put_volume=5, call_volume=80),
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
    )

    row = artifacts.summary.set_index("ticker").loc["AEM"]

    assert row["direction_candidate_label"] == "UPSIDE"
    assert row["direction_label"] == "UPSIDE"
    assert row["activity_label"] == "CONFIRMS_UPSIDE"


def test_option_signal_iv_rank_requires_min_history(tmp_path):
    app_config = load_app_config(build_test_paths(tmp_path)).app
    history = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "as_of_date": f"2026-05-{day:02d}",
                "quote_snapshot_run_id": f"run-{day}",
                "benchmark_symbol": "GDX",
                "skew_residual_60d": 0.01,
                "skew_residual_90d": 0.01,
                "atm_iv_60d": 0.20 + day / 1000,
                "iv_rv_ratio": 1.0,
            }
            for day in range(1, 21)
        ]
    )
    artifacts = build_option_signal_artifacts(
        app_config=app_config,
        options_features=pd.DataFrame(
            [
                _feature("AEM", skew_60=0.08, skew_90=0.07, atm_iv_60=0.40),
                _feature("GDX", skew_60=0.03, skew_90=0.02, vehicle="benchmark_etf"),
                _feature("GDXJ", skew_60=0.04, skew_90=0.03, vehicle="benchmark_etf"),
            ]
        ),
        contract_metrics=(
            *_metrics("AEM", bid=1.0, ask=1.2),
            *_metrics("GDX", bid=1.0, ask=1.2),
            *_metrics("GDXJ", bid=1.0, ask=1.2),
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-08"},
        prior_history=history,
    )

    row = artifacts.summary.set_index("ticker").loc["AEM"]
    assert row["history_depth"] == 20
    assert row["iv_rank"] == 100.0
    assert row["cost_label"] == "RICH"


def _feature(
    ticker: str,
    *,
    skew_60: float,
    skew_90: float,
    vehicle: str = "single_stock",
    atm_iv_60: float = 0.35,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": "2026-06-08",
        "run_id": "options-run",
        "optionability_tier": "directly_hedgeable",
        "option_vehicle_type": vehicle,
        "iv_skew_60d": skew_60,
        "iv_skew_90d": skew_90,
        "iv_skew_120d": skew_90,
        "atm_iv_60d": atm_iv_60,
        "iv_rv_ratio_60d": 1.4,
    }


def _metrics(
    ticker: str,
    *,
    bid: float,
    ask: float,
    put_volume: int = 20,
    call_volume: int = 20,
) -> tuple[OptionContractMetrics, ...]:
    return (
        _metric(ticker, option_type="P", expiration="2026-08-21", strike=95, delta=-0.25, bid=bid, ask=ask, volume=put_volume),
        _metric(ticker, option_type="C", expiration="2026-08-21", strike=105, delta=0.25, bid=bid, ask=ask, volume=call_volume),
        _metric(ticker, option_type="P", expiration="2026-09-18", strike=90, delta=-0.20, bid=bid, ask=ask, volume=put_volume),
        _metric(ticker, option_type="C", expiration="2026-09-18", strike=110, delta=0.20, bid=bid, ask=ask, volume=call_volume),
    )


def _metric(
    ticker: str,
    *,
    option_type: str,
    expiration: str,
    strike: float,
    delta: float,
    bid: float,
    ask: float,
    volume: int,
) -> OptionContractMetrics:
    mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0
    return OptionContractMetrics(
        ticker=ticker,
        option_type=cast(Literal["P", "C"], option_type),
        expiration=expiration,
        days_to_expiry=74,
        strike=strike,
        underlying_price=100.0,
        bid=bid,
        ask=ask,
        mid=mid,
        last_price=mid,
        open_interest=100,
        volume=volume,
        implied_volatility=0.35,
        delta=delta,
        rel_spread=(ask - bid) / mid if mid else None,
        half_spread_cost_pct=0.10 if mid else None,
        moneyness_pct=abs(strike - 100.0) / 100.0,
        otm_pct=abs(strike - 100.0) / 100.0,
        premium_pct_spot=mid / 100.0 if mid else None,
        near_spot_depth_count=8,
        liquidity_score=0.8,
        liquidity_tier="tradable",
        quote_flags=(),
        is_standard_monthly=True,
    )
