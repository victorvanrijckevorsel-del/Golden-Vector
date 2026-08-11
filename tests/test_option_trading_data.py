from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    write_current_model_state_manifest,
)
from golden_vector.app.run_context import RunContext
from golden_vector.hedge.option_trading import (
    OptionSizingRequest,
    build_option_trading_detail,
    build_option_trading_overview,
)
from golden_vector.hedge.option_artifact_builder import (
    build_option_artifact_inputs,
    scan_option_chains_for_artifacts,
    scan_option_contract_metrics,
)
from golden_vector.hedge.option_artifact_sources import load_option_artifact_source_inputs
from golden_vector.hedge.option_availability import has_usable_option_slots
from golden_vector.contracts.option_artifacts import option_artifact_latest_path
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.serve.option_trading_data import (
    OptionArtifactIntegrityError,
    OptionArtifactStaleSchemaError,
    build_option_trading_detail_data,
    clear_option_trading_cache,
    load_option_trading_data,
    parse_option_sizing_request,
)
from golden_vector.serve.detail_panels import _render_option_trading_panel
from golden_vector.cli import run_option_artifacts
from tests.helpers import build_test_paths, tool_b_output_row


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
        target_horizons_days=(60, 90, 120),
        signal_horizon_days=90,
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
    assert overview.rows[0].iv_skew_signal == pytest.approx(-0.1)
    assert overview.rows[0].iv_rv_ratio_signal == 1.25
    assert overview.rows[0].put_status == "tradable"
    assert overview.rows[0].call_status == "tradable"
    assert overview.rows[0].pnl_put_at_context is not None
    assert overview.rows[0].pnl_call_at_context is not None
    assert {row.ticker for row in overview.rows} == {"AEM", "NEM"}


def test_build_option_trading_overview_tracks_side_specific_status():
    overview = build_option_trading_overview(
        target_horizons_days=(60, 90, 120),
        signal_horizon_days=90,
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
    assert row.pnl_put_at_context is None


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
    assert first.cache_key.model_state_manifest_hash is not None
    assert {row.ticker for row in first.overview.rows} == {"AEM", "GDX", "GDXJ"}
    assert app_config.hedge_readiness.target_horizons_days == [90, 180, 230, 550]
    assert app_config.hedge_readiness.display_horizons_days == [90, 180, 230, 550]
    assert sorted({slot.horizon_days for slot in first.candidate_slots["AEM"]}) == [
        90,
        180,
        230,
        550,
    ]
    assert {slot.bucket for slot in first.candidate_slots["AEM"]} == {
        "near_atm",
        "directional",
    }
    assert first.overview.rows[0].optionability_tier == "directly_hedgeable"
    assert first.overview.source_context is not None
    assert first.overview.source_context.as_of_date == "2026-05-29"
    assert first.overview.source_context.refresh_run_id == "options-run"
    assert first.overview.source_context.tool_a_refresh_run_ids == ("tool-run-a",)
    assert first.overview.source_context.tool_b_refresh_run_ids == ("tool-run-a",)
    assert first.overview.source_context.context_warnings
    assert any(
        "Refresh context is mixed" in warning
        for warning in first.overview.source_context.context_warnings
    )
    assert any(
        "Tool A uses tool-run-a" in warning
        for warning in first.overview.source_context.context_warnings
    )

    _write_tool_outputs(paths, refresh_run_id="tool-run-b")
    _publish_option_artifacts(paths)
    changed = load_option_trading_data(paths, app_config=app_config)

    assert changed is not first
    assert changed.cache_key is not None
    assert changed.cache_key.tool_a_refresh_run_ids == ("tool-run-b",)


def test_load_option_trading_data_cache_key_tracks_model_state_manifest(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    _write_option_trading_model_state_pointer(paths, marker="first-pointer")

    first = load_option_trading_data(paths, app_config=app_config)
    second = load_option_trading_data(paths, app_config=app_config)
    _write_option_trading_model_state_pointer(paths, marker="second-pointer")
    changed = load_option_trading_data(paths, app_config=app_config)

    assert first is second
    assert changed is not first
    assert first.cache_key is not None
    assert changed.cache_key is not None
    assert first.cache_key.model_state_manifest_hash is not None
    assert changed.cache_key.model_state_manifest_hash is not None
    assert first.cache_key.model_state_manifest_hash != (
        changed.cache_key.model_state_manifest_hash
    )


def test_build_option_trading_detail_data_reuses_cached_overview_row(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")

    data = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(data, ticker="AEM", app_config=app_config)

    assert data.overview.rows
    aem_row = next(row for row in data.overview.rows if row.ticker == "AEM")
    assert detail.row is aem_row
    assert detail.row.pnl_put_at_context == aem_row.pnl_put_at_context
    assert sorted({slot.horizon_days for slot in detail.put_slots}) == [90, 180, 230, 550]
    assert {slot.bucket for slot in detail.put_slots} == {
        "near_atm",
        "directional",
    }
    assert detail.source_context is data.overview.source_context


def test_option_trading_detail_renders_persisted_charts_and_scenarios(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")

    data = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(
        data,
        ticker="AEM",
        app_config=app_config,
        sizing_request=OptionSizingRequest(side="put", horizon_days=90),
    )
    html = _render_option_trading_panel(detail)

    assert data.raw_options_by_ticker == {}
    assert detail.skew_curve_points
    assert detail.oi_strike_points
    assert detail.signal_history_points
    assert detail.sizing is not None
    assert detail.sizing.bundle is not None
    assert "Option Signal Charts" in html
    assert "Skew Curve" in html
    assert "Open Interest by Strike" in html
    assert "Signal History" in html
    assert "option-chart-svg" in html
    assert "IV rank is not available yet" in html
    assert "Scenario Table and Sizing" in html
    assert "Gold Move" in html
    assert "P&amp;L/share Now" in html
    assert "Net P&amp;L Expiry" in html


def test_build_option_trading_detail_does_not_model_watch_candidates():
    watch_candidate = _candidate("AEM", liquidity_tier="watch")

    detail = build_option_trading_detail(
        ticker="AEM",
        tool_a=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "down_beta_core": 1.2,
                    "up_beta_core": 1.0,
                    "confidence_label": "HIGH",
                }
            ]
        ),
        candidate_grids={"AEM": [watch_candidate]},
        overview_row=None,
        risk_free_rate=0.04,
        sizing_request=OptionSizingRequest(
            side="put",
            horizon_days=90,
            bucket="near_atm",
        ),
    )

    assert detail.put_candidates == (watch_candidate,)
    assert detail.put_bundles == ()
    assert detail.sizing is not None
    assert detail.sizing.bundle is None
    assert "No 90d Near-ATM put candidate is available." in detail.sizing.notes


def test_load_option_trading_data_handles_missing_manifest(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app

    data = load_option_trading_data(paths, app_config=app_config)

    assert data.overview.rows == ()
    assert data.overview.reason is not None
    assert "No option artifact snapshot" in data.overview.reason
    assert data.cache_key is None


def test_load_option_trading_data_raises_stale_schema_when_model_state_lacks_new_artifact(
    tmp_path,
):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    payload = load_current_model_state_manifest(paths)
    assert payload is not None
    del payload["artifacts"]["option_signal_summary"]
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        OptionArtifactStaleSchemaError,
        match="missing required option artifact option_signal_summary",
    ):
        load_option_trading_data(paths, app_config=app_config)


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
    assert "No option artifact snapshot" in data.overview.reason
    assert data.cache_key is None


def test_load_option_trading_data_surfaces_corrupt_manifest_artifact(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    payload = load_current_model_state_manifest(paths)
    assert payload is not None
    artifact_path = paths.resolve_repo_relative(
        payload["artifacts"]["option_candidate_slots"]["path"]
    )
    pd.DataFrame(
        [
            {
                "ticker": "BROKEN",
                "schema_version": 1,
                "snapshot_refresh_run_id": "options-run",
                "source_run_id": "tampered",
            }
        ]
    ).to_parquet(artifact_path, index=False)

    # A file whose bytes disagree with the manifest sha is an integrity failure,
    # not a "can't read it" inconvenience: it must escape the friendly empty
    # state so the route can render the loud 503, exactly like a stale schema.
    with pytest.raises(OptionArtifactIntegrityError) as excinfo:
        load_option_trading_data(paths, app_config=app_config)
    assert "sha256 mismatch" in str(excinfo.value)


def test_load_option_trading_data_healthy_artifacts_are_not_flagged_corrupt(tmp_path):
    """Control for the integrity test: untampered artifacts still load normally,
    proving the loud path keys on the mismatch and not on merely being read."""

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")

    data = load_option_trading_data(paths, app_config=app_config)

    assert data.overview.rows != ()
    assert data.cache_key is not None


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
    aem_row = next(row for row in data.overview.rows if row.ticker == "AEM")
    assert aem_row.call_status == "tradable"
    assert aem_row.pnl_call_at_context is not None
    assert detail.call_candidates
    assert detail.call_bundles
    assert detail.call_bundles[0].gold_beta_used == 1.1


def test_option_trading_ladders_come_from_config_default_scenarios(tmp_path):
    """The put/call P&L ladders are threaded from hedge_readiness.default_scenarios
    (one config source) and the call ladder is its sign-mirror. Proven with a
    NON-default ladder so a re-hardcoded ladder or broken config threading fails,
    and pinning the call baseline as +0.0 (not -0.0) guards the negated-zero fix."""
    import yaml

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    # A non-default downside ladder so the assertion can't pass on the shipped defaults.
    hr_path = paths.config_path("hedge_readiness.yaml")
    hr = yaml.safe_load(hr_path.read_text(encoding="utf-8"))
    hr["default_scenarios"] = [0.0, -0.07, -0.12]
    hr_path.write_text(yaml.safe_dump(hr), encoding="utf-8")

    app_config = load_app_config(paths).app
    _write_option_inputs(paths, refresh_run_id="options-run", tool_refresh_run_id="tool-run")
    data = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(data, ticker="AEM", app_config=app_config)

    # Call ladder = sign-mirror of the (non-default) config ladder, baseline +0.0.
    assert [r.gold_pct_change for r in detail.call_bundles[0].rows] == [0.0, 0.07, 0.12]
    assert repr(detail.call_bundles[0].rows[0].gold_pct_change) == "0.0"  # not "-0.0"
    if detail.put_bundles:
        assert [r.gold_pct_change for r in detail.put_bundles[0].rows] == [0.0, -0.07, -0.12]


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


def test_option_artifact_publish_refuses_missing_benchmark_etf_measurement(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=False,
        publish_artifacts=False,
    )

    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")

    assert exit_code == 1
    assert load_current_model_state_manifest(paths) is None


def test_option_detail_shows_proxy_fallback_when_single_name_missing(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
        publish_artifacts=False,
    )
    _make_snapshot_untradable(paths, refresh_run_id="options-run", ticker="AEM")
    _publish_option_artifacts(paths)

    data = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(
        data,
        ticker="AEM",
        app_config=app_config,
        sizing_request=OptionSizingRequest(side="put", horizon_days=90),
    )

    assert detail.sizing is not None
    assert detail.sizing.bundle is None
    assert {fallback.ticker for fallback in detail.proxy_fallbacks} == {"GDX", "GDXJ"}
    assert detail.proxy_fallback_note is None


def test_option_artifact_publish_refuses_proxy_state_when_etfs_unmeasured(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=False,
        publish_artifacts=False,
    )
    _make_snapshot_untradable(paths, refresh_run_id="options-run", ticker="AEM")
    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")

    assert exit_code == 1
    assert load_current_model_state_manifest(paths) is None


def test_option_artifact_reader_matches_shared_builder_for_same_sources(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
        publish_artifacts=False,
    )
    _make_snapshot_untradable(paths, refresh_run_id="options-run", ticker="AEM")

    sources = load_option_artifact_source_inputs(paths, use_model_state=False)
    assert sources is not None
    direct = build_option_artifact_inputs(
        app_config=app_config,
        features=sources.features,
        tool_a=sources.tool_a,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
        manifest=sources.manifest,
    )
    scans = scan_option_chains_for_artifacts(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
    )
    direct_from_scans = build_option_artifact_inputs(
        app_config=app_config,
        features=sources.features,
        tool_a=sources.tool_a,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
        manifest=sources.manifest,
        scans_by_ticker=scans,
    )
    assert _overview_signatures(direct_from_scans.overview.rows) == _overview_signatures(
        direct.overview.rows
    )
    assert _slot_signatures(direct_from_scans.candidate_slots) == _slot_signatures(
        direct.candidate_slots
    )
    assert _slot_signatures(direct_from_scans.call_candidate_slots) == _slot_signatures(
        direct.call_candidate_slots
    )
    assert scan_option_contract_metrics(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
        scans_by_ticker=scans,
    ) == scan_option_contract_metrics(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
    )
    _publish_option_artifacts(paths)

    persisted = load_option_trading_data(paths, app_config=app_config)
    detail = build_option_trading_detail_data(
        persisted,
        ticker="AEM",
        app_config=app_config,
        sizing_request=OptionSizingRequest(side="put", horizon_days=90),
    )

    assert persisted.risk_free_rate == pytest.approx(sources.risk_free_rate)
    assert persisted.risk_free_rate_is_fallback is sources.risk_free_rate_is_fallback
    assert _overview_signatures(persisted.overview.rows) == _overview_signatures(
        direct.overview.rows
    )
    assert _slot_signatures(persisted.candidate_slots) == _slot_signatures(
        direct.candidate_slots
    )
    assert _slot_signatures(persisted.call_candidate_slots) == _slot_signatures(
        direct.call_candidate_slots
    )
    assert _candidate_signatures(persisted.candidate_grids) == _candidate_signatures(
        direct.candidate_grids
    )
    assert _candidate_signatures(
        persisted.call_candidate_grids
    ) == _candidate_signatures(direct.call_candidate_grids)
    assert _measurement_signatures(
        persisted.overview.liquidity_measurements
    ) == _measurement_signatures(direct.overview.liquidity_measurements)
    assert _usable_tickers(persisted.candidate_slots) == _usable_tickers(
        direct.candidate_slots
    )
    assert _usable_tickers(persisted.call_candidate_slots) == _usable_tickers(
        direct.call_candidate_slots
    )
    assert {"GDX", "GDXJ"}.issubset(_usable_tickers(persisted.candidate_slots))
    assert {fallback.ticker for fallback in detail.proxy_fallbacks} == {"GDX", "GDXJ"}


def test_option_artifact_build_reuses_precomputed_chain_scans(tmp_path, monkeypatch):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(paths).app
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        include_benchmarks=True,
        publish_artifacts=False,
    )

    sources = load_option_artifact_source_inputs(paths, use_model_state=False)
    assert sources is not None
    scans = scan_option_chains_for_artifacts(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
    )

    def fail_rescan(*args, **kwargs):
        raise AssertionError("precomputed option-chain scans were not reused")

    monkeypatch.setattr(
        "golden_vector.hedge.option_artifact_builder.scan_option_chain",
        fail_rescan,
    )

    build_option_artifact_inputs(
        app_config=app_config,
        features=sources.features,
        tool_a=sources.tool_a,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        risk_free_rate_is_fallback=sources.risk_free_rate_is_fallback,
        manifest=sources.manifest,
        scans_by_ticker=scans,
    )
    scan_option_contract_metrics(
        app_config=app_config,
        features=sources.features,
        tool_b=sources.tool_b,
        chains=sources.chains,
        risk_free_rate=sources.risk_free_rate,
        manifest=sources.manifest,
        scans_by_ticker=scans,
    )


def test_option_artifact_build_fails_loud_on_stale_feature_rows(tmp_path):
    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        publish_artifacts=False,
    )
    feature_path = paths.options_features_dir / f"{safe_options_file_name('AEM')}.parquet"
    stale = pd.read_parquet(feature_path)
    stale["run_id"] = "older-options-run"
    stale.to_parquet(feature_path, index=False)

    # AEM is in the current manifest (no ERROR marker) but its feature file carries
    # no row for the current run -> the build must FAIL LOUD, never silently drop AEM
    # and publish a clean-looking overview. (Codex options-review H1.)
    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")
    assert exit_code == 1


def test_option_artifact_publish_is_all_or_nothing_on_signal_history_failure(tmp_path, monkeypatch):
    # A good publish, then a run where the atomic history+alias publish raises while
    # staging (the signal-history shrink guard trips). Both the latest aliases AND
    # the accumulated signal history must stay byte-identical to the last good run --
    # a failed run never leaves aliases ahead of a failed build, nor advances the
    # history past a failed alias flip. (Codex H2 + options-UI review HIGH: the
    # publish is now atomic across history + aliases together.)
    import golden_vector.ingestion.persist_option_artifacts as persist_mod
    from golden_vector.hedge.option_signals import option_signal_history_path

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        publish_artifacts=False,
    )
    assert run_option_artifacts(paths, parent_refresh_id="parent-A") == 0
    overview_alias = option_artifact_latest_path(paths, "option_trading_overview")
    good_alias_bytes = overview_alias.read_bytes()
    history_path = option_signal_history_path(paths)
    good_history_bytes = history_path.read_bytes()

    def _boom(*args, **kwargs):
        raise RuntimeError("signal-history shrink guard tripped")

    monkeypatch.setattr(persist_mod, "prepare_option_signal_history", _boom)

    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-B")

    assert exit_code == 1
    assert overview_alias.read_bytes() == good_alias_bytes  # aliases never flipped past the failure
    assert history_path.read_bytes() == good_history_bytes  # history never advanced past the failure


def test_option_artifact_publish_refuses_while_refresh_lock_held(tmp_path):
    # Single-writer guard: while another run holds the refresh lock, a standalone
    # option publish must refuse and republish nothing, so two publishes can never
    # interleave their grouped alias/history swaps. (Codex re-review HIGH.)
    from golden_vector.serve.option_refresh import (
        acquire_refresh_lock,
        complete_options_refresh,
    )

    clear_option_trading_cache()
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    _write_option_inputs(
        paths,
        refresh_run_id="options-run",
        tool_refresh_run_id="tool-run",
        publish_artifacts=False,
    )
    assert run_option_artifacts(paths, parent_refresh_id="parent-A") == 0
    overview_alias = option_artifact_latest_path(paths, "option_trading_overview")
    good_bytes = overview_alias.read_bytes()

    held = acquire_refresh_lock(paths, command=["refresh"])
    assert held.started and not held.already_running
    try:
        exit_code = run_option_artifacts(paths, parent_refresh_id="parent-B")
    finally:
        complete_options_refresh(paths, job_id=held.status.job_id, return_code=0)

    assert exit_code != 0  # refused while the lock was held
    assert overview_alias.read_bytes() == good_bytes  # nothing republished under the lock

    # With the lock released, a publish succeeds again.
    assert run_option_artifacts(paths, parent_refresh_id="parent-C") == 0


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


def test_parse_option_sizing_request_accepts_long_dated_display_horizon(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app

    request = parse_option_sizing_request(
        {"horizon": ["230"]},
        app_config=app_config,
    )

    assert request.horizon_days == 230
    assert request.notes == ()


def _write_option_inputs(
    paths,
    *,
    refresh_run_id: str,
    tool_refresh_run_id: str,
    risk_free_rate: float | None = 0.04,
    include_benchmarks: bool = True,
    publish_artifacts: bool = True,
    up_beta_core: float = 1.1,
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
    _write_tool_outputs(
        paths,
        refresh_run_id=tool_refresh_run_id,
        up_beta_core=up_beta_core,
    )
    if publish_artifacts:
        _publish_option_artifacts(paths)


def _write_tool_outputs(
    paths,
    *,
    refresh_run_id: str,
    up_beta_core: float = 1.1,
) -> None:
    tool_a_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=tool_a_context,
        tool_a_outputs=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "structural_delta_core": 1.3,
                    "down_beta_core": 1.4,
                    "up_beta_core": up_beta_core,
                    "confidence_label": "HIGH",
                    "confidence_score": 0.9,
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": tool_a_context.run_id,
                }
            ]
        ),
    )
    tool_b_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=tool_b_context,
        tool_b_outputs=pd.DataFrame(
            [
                tool_b_output_row(
                    "AEM",
                    share_price_usd=50.0,
                    snapshot_refresh_run_id=refresh_run_id,
                    source_run_id=tool_b_context.run_id,
                )
            ]
        ),
    )


def _publish_option_artifacts(paths) -> None:
    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")
    assert exit_code == 0
    write_current_model_state_manifest(
        paths=paths,
        config_hash="hash",
        parent_refresh_id="parent-refresh",
    )


def _write_option_trading_model_state_pointer(paths, *, marker: str) -> None:
    paths.latest_model_state_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = load_current_model_state_manifest(paths)
    assert payload is not None
    payload["marker"] = marker
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _make_snapshot_untradable(paths, *, refresh_run_id: str, ticker: str) -> None:
    snapshot_path = (
        paths.runs_dir
        / refresh_run_id
        / "snapshots"
        / "options"
        / f"{safe_options_file_name(ticker)}.parquet"
    )
    frame = pd.read_parquet(snapshot_path)
    frame["bid"] = 0.0
    frame["ask"] = 0.0
    frame.to_parquet(snapshot_path, index=False)


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


def _candidate(
    ticker: str,
    *,
    option_type: str = "P",
    liquidity_tier: str = "tradable",
):
    from golden_vector.hedge.candidate_puts import CandidatePut

    strike = 45.0 if option_type == "P" else 55.0
    delta = -0.25 if option_type == "P" else 0.25
    return CandidatePut(
        ticker=ticker,
        horizon_days=90,
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
        liquidity_tier=liquidity_tier,
        otm_pct=0.10,
    )


def _overview_signatures(rows) -> list[tuple[object, ...]]:
    return sorted(
        (
            row.ticker,
            _round_optional(row.structural_delta_core),
            _round_optional(row.down_beta_core),
            _round_optional(row.up_beta_core),
            row.confidence_label,
            _round_optional(row.confidence_score),
            _round_optional(row.iv_percentile_cross_sectional),
            _round_optional(row.iv_skew_signal),
            _round_optional(row.iv_rv_ratio_signal),
            row.optionability_tier,
            row.put_status,
            row.call_status,
            _round_optional(row.pnl_put_at_context),
            _round_optional(row.pnl_call_at_context),
            tuple(row.notes),
            _round_optional(row.current_stock_price),
            row.option_vehicle_type,
        )
        for row in rows
    )


def _measurement_signatures(measurements) -> list[tuple[object, ...]]:
    return sorted(
        (
            measurement.group_label,
            measurement.ticker_count,
            measurement.contract_count,
            _round_optional(measurement.median_rel_spread),
            _round_optional(measurement.median_open_interest),
            _round_optional(measurement.median_volume),
            _round_optional(measurement.median_near_spot_depth),
            measurement.tradable_count,
            measurement.watch_count,
            measurement.no_trade_count,
        )
        for measurement in measurements
    )


def _slot_signatures(slots_by_ticker) -> list[tuple[object, ...]]:
    return sorted(
        (
            slot.ticker,
            slot.option_type,
            slot.horizon_days,
            _round_optional(slot.target_delta),
            slot.expiration,
            slot.days_to_expiry,
            slot.status,
            slot.reason,
            _candidate_signature(slot.candidate),
            _candidate_signature(slot.rejected_candidate),
            slot.listed_contract_count,
            slot.tradable_contract_count,
            slot.bucket,
            slot.liquidity_tier,
        )
        for ticker_slots in slots_by_ticker.values()
        for slot in ticker_slots
    )


def _candidate_signatures(candidates_by_ticker) -> list[tuple[object, ...]]:
    return sorted(
        signature
        for candidates in candidates_by_ticker.values()
        for signature in (_candidate_signature(candidate) for candidate in candidates)
        if signature is not None
    )


def _candidate_signature(candidate) -> tuple[object, ...] | None:
    if candidate is None:
        return None
    return (
        candidate.ticker,
        candidate.option_type,
        candidate.horizon_days,
        candidate.expiration,
        candidate.days_to_expiry,
        _round_optional(candidate.strike),
        _round_optional(candidate.bid),
        _round_optional(candidate.ask),
        _round_optional(candidate.mid),
        candidate.open_interest,
        candidate.volume,
        _round_optional(candidate.implied_volatility),
        _round_optional(candidate.delta),
        _round_optional(candidate.delta_gap),
        _round_optional(candidate.premium_pct_spot),
        _round_optional(candidate.underlying_price),
        _round_optional(candidate.last_price),
        candidate.bucket,
        candidate.liquidity_tier,
        _round_optional(candidate.rel_spread),
        _round_optional(candidate.half_spread_cost_pct),
        _round_optional(candidate.liquidity_score),
        _round_optional(candidate.moneyness_pct),
        _round_optional(candidate.otm_pct),
        tuple(candidate.quote_flags),
    )


def _usable_tickers(slots_by_ticker) -> set[str]:
    return {
        str(ticker)
        for ticker, slots in slots_by_ticker.items()
        if has_usable_option_slots(slots)
    }


def _round_optional(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(value), 8)


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
