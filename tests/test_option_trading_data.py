from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.hedge.option_trading import build_option_trading_overview
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.serve.option_trading_data import (
    build_option_trading_detail_data,
    clear_option_trading_cache,
    load_option_trading_data,
    parse_option_sizing_request,
)
from tests.helpers import build_test_paths


def test_build_option_trading_overview_filters_and_sorts_optionable_rows():
    features = pd.DataFrame(
        [
            _feature("AEM", "directly_hedgeable", put_iv=0.4, call_iv=0.5, iv_rank=40.0),
            _feature("NEM", "directly_hedgeable", put_iv=0.4, call_iv=0.5, iv_rank=30.0),
            _feature("NOOPT", "none", put_iv=None, call_iv=None, iv_rank=None),
        ]
    )
    tool_a = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "structural_delta_core": 1.3,
                "down_beta_core": 1.2,
                "up_beta_core": 1.1,
                "confidence_label": "HIGH",
                "confidence_score": 0.9,
            },
            {
                "ticker": "NEM",
                "structural_delta_core": 1.9,
                "down_beta_core": 1.8,
                "up_beta_core": 1.0,
                "confidence_label": "MEDIUM",
                "confidence_score": 0.7,
            },
        ]
    )

    overview = build_option_trading_overview(
        tool_a=tool_a,
        options_features=features,
        candidate_grids={"AEM": [_candidate("AEM")], "NEM": [_candidate("NEM")]},
        call_candidate_grids={
            "AEM": [_candidate("AEM", option_type="C")],
            "NEM": [_candidate("NEM", option_type="C")],
        },
        risk_free_rate=0.04,
    )

    assert [row.ticker for row in overview.rows] == ["NEM", "AEM"]
    assert overview.rows[0].structural_delta_core == 1.9
    assert overview.rows[0].iv_skew_60d == pytest.approx(-0.1)
    assert overview.rows[0].iv_rv_ratio_60d == 1.25
    assert overview.rows[0].put_status == "tradable"
    assert overview.rows[0].call_status == "tradable"
    assert overview.rows[0].pnl_put_at_minus10_60d is not None
    assert overview.rows[0].pnl_call_at_plus10_60d is not None
    assert {row.ticker for row in overview.rows} == {"AEM", "NEM"}


def test_build_option_trading_overview_tracks_side_specific_status():
    overview = build_option_trading_overview(
        tool_a=pd.DataFrame([{"ticker": "CMCL", "down_beta_core": 1.0}]),
        options_features=pd.DataFrame(
            [_feature("CMCL", "thin", put_iv=None, call_iv=0.5, iv_rank=50.0)]
        ),
        candidate_grids={"CMCL": []},
        risk_free_rate=0.04,
    )

    row = overview.rows[0]
    assert row.put_status == "none"
    assert row.call_status == "none"
    assert row.pnl_put_at_minus10_60d is None


def test_load_option_trading_data_uses_composite_cache_key(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run-a")

    first = load_option_trading_data(paths, app_config=app_config)
    second = load_option_trading_data(paths, app_config=app_config)

    assert first is second
    assert first.cache_key is not None
    assert first.cache_key.options_refresh_run_id == "options-run"
    assert first.cache_key.tool_a_refresh_run_ids == ("tool-run-a",)
    assert [row.ticker for row in first.overview.rows] == ["AEM"]
    assert app_config.hedge_readiness.target_horizons_days == [60, 90, 120]
    assert app_config.hedge_readiness.display_horizons_days == [60, 90, 120]
    assert sorted({slot.horizon_days for slot in first.candidate_slots["AEM"]}) == [
        60,
        90,
        120,
    ]
    assert {slot.bucket for slot in first.candidate_slots["AEM"]} == {
        "near_atm",
        "directional",
    }
    assert first.overview.rows[0].optionability_tier == "directly_hedgeable"
    assert first.overview.source_context is not None
    assert first.overview.source_context.as_of_date == "2026-05-29"
    assert first.overview.source_context.refresh_run_id == "options-run"

    _write_tool_outputs(paths, refresh_run_id="tool-run-b")
    changed = load_option_trading_data(paths, app_config=app_config)

    assert changed is not first
    assert changed.cache_key is not None
    assert changed.cache_key.tool_a_refresh_run_ids == ("tool-run-b",)


def test_build_option_trading_detail_data_reuses_cached_overview_row(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")

    data = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(data, ticker="AEM", app_config=app_config)

    assert data.overview.rows
    assert detail.row is data.overview.rows[0]
    assert detail.row.pnl_put_at_minus10_60d == data.overview.rows[0].pnl_put_at_minus10_60d
    assert sorted({slot.horizon_days for slot in detail.put_slots}) == [60, 90, 120]
    assert {slot.bucket for slot in detail.put_slots} == {
        "near_atm",
        "directional",
    }
    assert detail.source_context is data.overview.source_context


def test_load_option_trading_data_handles_missing_manifest(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app

    data = load_option_trading_data(paths, app_config=app_config)

    assert data.overview.rows == ()
    assert data.overview.reason is not None
    assert "No options snapshot" in data.overview.reason
    assert data.cache_key is None


def test_load_option_trading_data_handles_malformed_manifest(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text("{not-json", encoding="utf-8")

    data = load_option_trading_data(paths, app_config=app_config)

    assert data.overview.rows == ()
    assert data.overview.reason is not None
    assert "No options snapshot" in data.overview.reason
    assert data.cache_key is None


def test_load_option_trading_data_flags_missing_risk_free_rate_fallback(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        risk_free_rate=None,
    )

    data = load_option_trading_data(paths, app_config=app_config)

    assert data.risk_free_rate == 0.0
    assert data.risk_free_rate_is_fallback is True
    assert data.overview.risk_free_rate_is_fallback is True


def test_load_option_trading_data_builds_call_context_from_up_beta(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")

    data = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(data, ticker="AEM", app_config=app_config)

    assert data.call_candidate_grids["AEM"]
    assert all(candidate.option_type == "C" for candidate in data.call_candidate_grids["AEM"])
    assert data.overview.rows[0].call_status == "tradable"
    assert data.overview.rows[0].pnl_call_at_plus10_60d is not None
    assert detail.call_candidates
    assert detail.call_bundles
    assert detail.call_bundles[0].gold_beta_used == 1.1


def test_load_option_trading_data_surfaces_benchmark_etf_option_rows(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
    )

    data = load_option_trading_data(paths, app_config=app_config)
    tickers = {row.ticker for row in data.overview.rows}
    gdx = next(row for row in data.overview.rows if row.ticker == "GDX")

    assert {"GDX", "GDXJ"}.issubset(tickers)
    assert gdx.option_vehicle_type == "benchmark_etf"
    assert "Benchmark ETF option vehicle." in gdx.notes
    assert data.candidate_slots["GDX"]
    assert data.call_candidate_slots["GDX"]
    assert any(
        measurement.group_label == "Benchmark ETFs"
        for measurement in data.overview.liquidity_measurements
    )
    benchmark_measurement = next(
        measurement
        for measurement in data.overview.liquidity_measurements
        if measurement.group_label == "Benchmark ETFs"
    )
    single_stock_measurement = next(
        measurement
        for measurement in data.overview.liquidity_measurements
        if measurement.group_label == "Single-stock miners"
    )
    assert benchmark_measurement.tradable_count > 0
    assert (
        benchmark_measurement.tradable_count
        + benchmark_measurement.watch_count
        + benchmark_measurement.no_trade_count
        == benchmark_measurement.contract_count
    )
    assert (
        single_stock_measurement.tradable_count
        + single_stock_measurement.watch_count
        + single_stock_measurement.no_trade_count
        == single_stock_measurement.contract_count
    )


def test_load_option_trading_data_shows_missing_benchmark_etf_measurement(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=False,
    )

    data = load_option_trading_data(paths, app_config=app_config)
    benchmark_measurement = next(
        measurement
        for measurement in data.overview.liquidity_measurements
        if measurement.group_label == "Benchmark ETFs"
    )

    assert benchmark_measurement.ticker_count == 0
    assert benchmark_measurement.contract_count == 0
    assert benchmark_measurement.tradable_count == 0


def test_load_option_trading_data_ignores_stale_feature_rows(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    feature_path = paths.options_features_dir / f"{safe_options_file_name('AEM')}.parquet"
    stale = pd.read_parquet(feature_path)
    stale["run_id"] = "older-options-run"
    stale.to_parquet(feature_path, index=False)

    data = load_option_trading_data(paths, app_config=app_config)

    assert data.options_features.empty
    assert data.overview.rows == ()
    assert "No options feature snapshot" in (data.overview.reason or "")


def test_parse_option_sizing_request_budget_mode_ignores_unused_quantity(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app

    request = parse_option_sizing_request(
        {
            "size_mode": ["budget"],
            "budget": ["500"],
            "quantity": ["0"],
        },
        app_config=app_config,
    )

    assert request.size_mode == "budget"
    assert request.budget == 500.0
    assert request.quantity == app_config.hedge_readiness.default_scenario_quantity
    assert "Invalid quantity" not in " ".join(request.notes)


def test_parse_option_sizing_request_accepts_display_only_120d_horizon(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app

    request = parse_option_sizing_request(
        {"horizon": ["120"]},
        app_config=app_config,
    )

    assert request.horizon_days == 120
    assert request.notes == ()


def _write_option_inputs(
    paths,
    *,
    refresh_run_id: str,
    tool_refresh_run_id: str,
    risk_free_rate: float | None = 0.04,
    include_benchmarks: bool = False,
) -> None:
    paths.ensure_runtime_dirs()
    snapshot_dir = paths.runs_dir / refresh_run_id / "snapshots" / "options"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    tickers = ["AEM", "GDX", "GDXJ"] if include_benchmarks else ["AEM"]
    snapshot_items = []
    for ticker in tickers:
        snapshot_path = snapshot_dir / f"{safe_options_file_name(ticker)}.parquet"
        _chain(ticker).to_parquet(snapshot_path, index=False)
        snapshot_items.append(
            {
                "ticker": ticker,
                "options_available": True,
                "snapshot_path": snapshot_path.relative_to(paths.repo_root).as_posix(),
            }
        )
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": refresh_run_id,
                "as_of_date": "2026-05-29",
                "risk_free_rate": risk_free_rate,
                "snapshots": snapshot_items,
            }
        ),
        encoding="utf-8",
    )
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    for ticker in tickers:
        feature = _feature(
            ticker,
            "directly_hedgeable",
            put_iv=0.4,
            call_iv=0.5,
            iv_rank=40.0,
        )
        feature["run_id"] = refresh_run_id
        feature["underlying_price"] = 50.0
        feature["option_vehicle_type"] = (
            "benchmark_etf" if ticker in {"GDX", "GDXJ"} else "single_stock"
        )
        feature["options_source_symbol"] = ticker
        pd.DataFrame([feature]).to_parquet(
            paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet",
            index=False,
        )
    _write_tool_outputs(paths, refresh_run_id=tool_refresh_run_id)


def _write_tool_outputs(paths, *, refresh_run_id: str) -> None:
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    paths.output_tool_b_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "structural_delta_core": 1.3,
                "down_beta_core": 1.4,
                "up_beta_core": 1.1,
                "confidence_label": "HIGH",
                "confidence_score": 0.9,
                "snapshot_refresh_run_id": refresh_run_id,
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "share_price_usd": 50.0,
                "snapshot_refresh_run_id": refresh_run_id,
            }
        ]
    ).to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)


def _feature(
    ticker: str,
    tier: str,
    *,
    put_iv: float | None,
    call_iv: float | None,
    iv_rank: float | None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": ticker,
        "as_of_date": date(2026, 5, 29).isoformat(),
        "optionability_tier": tier,
        "iv_percentile_cross_sectional": iv_rank,
        "underlying_price": 50.0,
    }
    for horizon in (60, 90, 120):
        row[f"put_iv_25d_{horizon}d"] = put_iv
        row[f"call_iv_25d_{horizon}d"] = call_iv
        row[f"iv_skew_{horizon}d"] = (
            None if put_iv is None or call_iv is None else put_iv - call_iv
        )
        row[f"iv_rv_ratio_{horizon}d"] = 1.25 if put_iv is not None else None
    return row


def _candidate(ticker: str, *, option_type: str = "P"):
    from golden_vector.hedge.candidate_puts import CandidatePut

    strike = 45.0 if option_type == "P" else 55.0
    delta = -0.25 if option_type == "P" else 0.25
    return CandidatePut(
        ticker=ticker,
        horizon_days=60,
        expiration="2026-07-31",
        days_to_expiry=60,
        strike=strike,
        bid=1.15,
        ask=1.25,
        mid=1.20,
        open_interest=500,
        volume=50,
        implied_volatility=0.40,
        delta=delta,
        delta_gap=0.01,
        premium_pct_spot=1.20 / 50.0,
        underlying_price=50.0,
        option_type=option_type,
        bucket="near_atm",
        liquidity_tier="tradable",
        otm_pct=0.10,
    )


def _chain(ticker: str) -> pd.DataFrame:
    rows = []
    for expiration, strike, days in (
        ("2026-06-27", 47.5, 29),
        ("2026-07-31", 48.0, 62),
        ("2026-07-31", 42.5, 62),
        ("2026-08-29", 48.0, 92),
        ("2026-08-29", 42.5, 92),
        ("2026-09-30", 48.0, 124),
        ("2026-09-30", 42.5, 124),
    ):
        rows.append(
            {
                "ticker": ticker,
                "expiration": expiration,
                "option_type": "P",
                "strike": strike,
                "bid": 1.15,
                "ask": 1.25,
                "lastPrice": 1.20,
                "volume": 20,
                "openInterest": 500,
                "impliedVolatility": 0.40,
                "days_to_expiry": days,
                "underlying_price": 50.0,
            }
        )
    for expiration, strike, days in (
        ("2026-06-27", 52.5, 29),
        ("2026-07-31", 52.0, 62),
        ("2026-07-31", 60.0, 62),
        ("2026-08-29", 52.0, 92),
        ("2026-08-29", 60.0, 92),
        ("2026-09-30", 52.0, 124),
        ("2026-09-30", 60.0, 124),
    ):
        rows.append(
            {
                "ticker": ticker,
                "expiration": expiration,
                "option_type": "C",
                "strike": strike,
                "bid": 1.10,
                "ask": 1.30,
                "lastPrice": 1.20,
                "volume": 20,
                "openInterest": 500,
                "impliedVolatility": 0.40,
                "days_to_expiry": days,
                "underlying_price": 50.0,
            }
        )
    return pd.DataFrame(rows)
