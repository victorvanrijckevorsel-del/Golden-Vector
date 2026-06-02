from __future__ import annotations

import json
from datetime import date

import pandas as pd

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
                "down_beta_core": 1.2,
                "up_beta_core": 1.1,
                "confidence_label": "HIGH",
                "confidence_score": 0.9,
            },
            {
                "ticker": "NEM",
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
    assert overview.rows[0].put_status == "available"
    assert overview.rows[0].call_status == "available"
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
    assert row.put_status == "thin"
    assert row.call_status == "thin"
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
    assert data.overview.rows[0].call_status == "available"
    assert data.overview.rows[0].pnl_call_at_plus10_60d is not None
    assert detail.call_candidates
    assert detail.call_bundles
    assert detail.call_bundles[0].gold_beta_used == 1.1


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


def _write_option_inputs(
    paths,
    *,
    refresh_run_id: str,
    tool_refresh_run_id: str,
    risk_free_rate: float | None = 0.04,
) -> None:
    paths.ensure_runtime_dirs()
    snapshot_path = paths.runs_dir / refresh_run_id / "snapshots" / "options" / "AEM.parquet"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    _chain("AEM").to_parquet(snapshot_path, index=False)
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": refresh_run_id,
                "as_of_date": "2026-05-29",
                "risk_free_rate": risk_free_rate,
                "snapshots": [
                    {
                        "ticker": "AEM",
                        "options_available": True,
                        "snapshot_path": snapshot_path.relative_to(paths.repo_root).as_posix(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    feature = _feature("AEM", "directly_hedgeable", put_iv=0.4, call_iv=0.5, iv_rank=40.0)
    feature["run_id"] = refresh_run_id
    feature["underlying_price"] = 50.0
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([feature]).to_parquet(
        paths.options_features_dir / f"{safe_options_file_name('AEM')}.parquet",
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
    for horizon in (30, 60, 90):
        row[f"put_iv_25d_{horizon}d"] = put_iv
        row[f"call_iv_25d_{horizon}d"] = call_iv
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
    )


def _chain(ticker: str) -> pd.DataFrame:
    rows = []
    for expiration, strike, days in (
        ("2026-06-27", 47.5, 29),
        ("2026-07-31", 45.0, 62),
        ("2026-08-29", 42.5, 92),
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
        rows.append(
            {
                "ticker": ticker,
                "expiration": expiration,
                "option_type": "C",
                "strike": 55.0,
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
