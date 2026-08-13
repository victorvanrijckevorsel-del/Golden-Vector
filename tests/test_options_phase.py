import json
from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.replay_manifest import read_manifest
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion import options_phase as options_phase_module
from golden_vector.ingestion.options_phase import (
    run_options_ingestion_phase,
    skipped_options_phase_summary,
)
from tests.helpers import build_test_paths


@dataclass
class _OptionChain:
    puts: pd.DataFrame
    calls: pd.DataFrame


def test_run_options_ingestion_phase_writes_manifest_snapshots_and_features(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    client = _OptionsPhaseClient(pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet"))

    result = run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=loaded.app,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == "PASS"
    assert result.manifest_path == paths.latest_options_manifest_path
    assert paths.latest_options_manifest_path.exists()
    assert (context.run_dir / "snapshots" / "options" / "AEM.parquet").exists()
    assert (context.run_dir / "snapshots" / "options" / "GDX.parquet").exists()
    assert (context.run_dir / "snapshots" / "options" / "GDXJ.parquet").exists()
    assert (context.run_dir / "snapshots" / "benchmarks" / "GDX.parquet").exists()
    aem_features = pd.read_parquet(paths.options_features_dir / "AEM.parquet")
    gdx_features = pd.read_parquet(paths.options_features_dir / "GDX.parquet")
    assert aem_features.loc[0, "ticker"] == "AEM"
    assert bool(aem_features.loc[0, "options_available"]) is True
    assert gdx_features.loc[0, "ticker"] == "GDX"
    assert gdx_features.loc[0, "option_vehicle_type"] == "benchmark_etf"
    assert gdx_features.loc[0, "options_source_symbol"] == "GDX"
    assert result.summary["options_ticker_count"] == (
        result.summary["options_universe_ticker_count"] + 2
    )
    assert result.summary["options_benchmark_ticker_count"] == 2
    latest_manifest = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    assert {
        "AEM",
        "GDX",
        "GDXJ",
    }.issubset({item["ticker"] for item in latest_manifest["snapshots"]})
    # Numeric expiration evidence reaches the manifest, so availability readers
    # never have to parse the message prose.
    entries = {item["ticker"]: item for item in latest_manifest["snapshots"]}
    assert entries["AEM"]["expiration_count_available"] == 2
    assert entries["AEM"]["feature_path"].startswith(
        f"data/runs/{context.run_id}/snapshots/options_features/"
    )
    assert entries["AEM"]["feature_sha256"]
    manifest = read_manifest(context.run_dir)
    assert manifest["options_manifest_status"] == "captured"
    source_asset_names = {
        item["name"]
        for item in manifest["options_manifest_captured"]["source_assets"]
    }
    assert "options:GDX.parquet" in source_asset_names
    assert "options:GDXJ.parquet" in source_asset_names
    assert "options-feature:AEM.parquet" in source_asset_names


def test_run_options_ingestion_phase_continues_after_ticker_pipeline_error(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    client = _OptionsPhaseClient(pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet"))
    original_compute = options_phase_module._compute_feature_row

    def fail_aem_feature(**kwargs):
        if kwargs["ticker"] == "AEM":
            raise RuntimeError("synthetic feature failure")
        return original_compute(**kwargs)

    monkeypatch.setattr(options_phase_module, "_compute_feature_row", fail_aem_feature)

    result = run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=loaded.app,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == "WARN"
    assert result.summary["options_error_count"] == 1
    assert result.manifest_path == paths.latest_options_manifest_path
    assert paths.latest_options_manifest_path.exists()
    manifest = read_manifest(context.run_dir)
    assert manifest["options_manifest_status"] == "captured"


def test_run_options_ingestion_phase_publishes_visible_per_ticker_outage(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    client = _OptionsPhaseClient(fixture, fail_option_symbols=("AEM",))

    result = run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=loaded.app,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == "WARN"
    assert result.manifest_path == paths.latest_options_manifest_path
    assert result.summary["options_vendor_outage_status"] == "PARTIAL_OUTAGE"
    assert result.summary["options_error_count"] == 1
    assert paths.latest_options_manifest_path.exists()
    assert not (paths.options_features_dir / "AEM.parquet").exists()
    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = next(item for item in payload["snapshots"] if item["ticker"] == "AEM")
    assert aem["snapshot_path"] is None
    assert aem["source_refresh_run_id"] is None
    assert aem["attempt_status"] == "ERROR"
    assert "synthetic options outage" in aem["attempt_message"]


def test_partial_outage_carries_one_verified_ticker_bundle(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    day_one = _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    first_manifest = json.loads(
        paths.latest_options_manifest_path.read_text(encoding="utf-8")
    )
    first_aem = _manifest_entry(first_manifest, "AEM")

    day_two = _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
        fail_option_symbols=("AEM",),
    )

    assert day_one.status == "PASS"
    assert day_two.status == "WARN"
    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(payload, "AEM")
    gdx = _manifest_entry(payload, "GDX")
    assert aem["carried_forward"] is True
    assert aem["source_refresh_run_id"] == first_aem["source_refresh_run_id"]
    assert aem["source_as_of_date"] == "2026-05-29"
    assert aem["attempt_status"] == "ERROR"
    assert aem["feature_path"].startswith(
        f"data/runs/{payload['refresh_run_id']}/snapshots/options_features/"
    )
    assert aem["feature_sha256"]
    assert aem["snapshot_path"].startswith(
        f"data/runs/{payload['refresh_run_id']}/snapshots/options/"
    )
    assert gdx["carried_forward"] is False
    assert gdx["source_refresh_run_id"] == payload["refresh_run_id"]
    assert gdx["source_as_of_date"] == "2026-06-01"
    carried = pd.read_parquet(paths.resolve_repo_relative(aem["snapshot_path"]))
    assert set(carried["source_refresh_run_id"]) == {first_aem["source_refresh_run_id"]}
    assert set(carried["source_as_of_date"]) == {"2026-05-29"}
    assert set(carried["carried_forward"]) == {True}
    assert set(carried["attempt_status"]) == {"ERROR"}
    carried_feature = pd.read_parquet(paths.resolve_repo_relative(aem["feature_path"]))
    assert len(carried_feature.index) == 1
    assert carried_feature.loc[0, "run_id"] == first_aem["source_refresh_run_id"]


def test_partial_outage_reranks_the_effective_mixed_feature_cohort(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    iv_column = (
        f"atm_iv_{loaded.app.hedge_readiness.option_signal_horizon_days}d"
    )
    original = options_phase_module._compute_feature_row

    day_values = {
        "2026-05-29": {"AEM": 0.20, "GDX": 0.10, "GDXJ": 0.30},
        "2026-06-01": {"GDX": 0.40, "GDXJ": 0.50},
    }

    def controlled_iv(**kwargs):
        row = original(**kwargs)
        row[iv_column] = day_values[kwargs["as_of_date"].isoformat()][kwargs["ticker"]]
        return row

    monkeypatch.setattr(options_phase_module, "_compute_feature_row", controlled_iv)
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    prior_manifest = json.loads(
        paths.latest_options_manifest_path.read_text(encoding="utf-8")
    )
    prior_aem = _manifest_entry(prior_manifest, "AEM")
    prior_feature = pd.read_parquet(
        paths.resolve_repo_relative(prior_aem["feature_path"])
    )
    assert round(float(prior_feature.loc[0, "iv_percentile_cross_sectional"]), 6) == round(
        200.0 / 3.0,
        6,
    )

    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
        fail_option_symbols=("AEM",),
    )

    manifest = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    effective = {}
    for ticker in ("AEM", "GDX", "GDXJ"):
        entry = _manifest_entry(manifest, ticker)
        row = pd.read_parquet(paths.resolve_repo_relative(entry["feature_path"])).iloc[0]
        effective[ticker] = float(row["iv_percentile_cross_sectional"])

    # AEM was the middle name in the prior generation.  Against the current
    # effective cohort (AEM carried + GDX/GDXJ fresh), it is now the lowest.
    assert round(effective["AEM"], 6) == round(100.0 / 3.0, 6)
    assert round(effective["GDX"], 6) == round(200.0 / 3.0, 6)
    assert effective["GDXJ"] == 100.0
    assert _manifest_entry(manifest, "AEM")["source_refresh_run_id"] == prior_aem[
        "source_refresh_run_id"
    ]
    assert _manifest_entry(manifest, "GDX")["source_refresh_run_id"] == manifest[
        "refresh_run_id"
    ]

    # Re-ranking the effective view must not invent another historical capture.
    aem_history = pd.read_parquet(paths.options_features_dir / "AEM.parquet")
    assert len(aem_history.index) == 1
    assert round(
        float(aem_history.loc[0, "iv_percentile_cross_sectional"]),
        6,
    ) == round(200.0 / 3.0, 6)


def test_successful_zero_expiration_capture_replaces_prior_listed_snapshot(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )

    result = _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
        option_symbols=("GDX", "GDXJ"),
    )

    assert result.status == "PASS"
    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(payload, "AEM")
    assert aem["carried_forward"] is False
    assert aem["attempt_status"] == "EMPTY"
    assert aem["source_refresh_run_id"] == payload["refresh_run_id"]
    assert aem["source_as_of_date"] == "2026-06-01"
    assert aem["expiration_count_available"] == 0
    marker = pd.read_parquet(paths.resolve_repo_relative(aem["snapshot_path"]))
    assert bool(marker.loc[0, "options_available"]) is False


def test_feature_failure_uses_prior_verified_bundle(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    first = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    original = options_phase_module._compute_feature_row

    def fail_aem(**kwargs):
        if kwargs["ticker"] == "AEM":
            raise RuntimeError("synthetic feature failure")
        return original(**kwargs)

    monkeypatch.setattr(options_phase_module, "_compute_feature_row", fail_aem)
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
    )

    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(payload, "AEM")
    assert aem["carried_forward"] is True
    assert aem["source_refresh_run_id"] == _manifest_entry(first, "AEM")[
        "source_refresh_run_id"
    ]
    assert "Feature computation failed" in aem["attempt_message"]


def test_persistence_failure_uses_prior_verified_bundle(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    original = options_phase_module.persist_options_snapshot_frame
    failed = {"value": False}

    def fail_current_aem(**kwargs):
        if (
            kwargs["ticker"] == "AEM"
            and not kwargs.get("carried_forward", False)
            and not failed["value"]
        ):
            failed["value"] = True
            raise OSError("synthetic persistence failure")
        return original(**kwargs)

    monkeypatch.setattr(
        options_phase_module,
        "persist_options_snapshot_frame",
        fail_current_aem,
    )
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
    )

    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(payload, "AEM")
    assert aem["carried_forward"] is True
    assert "Snapshot persistence failed" in aem["attempt_message"]


def test_corrupt_prior_snapshot_is_not_carried(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    prior = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    prior_aem = _manifest_entry(prior, "AEM")
    paths.resolve_repo_relative(prior_aem["snapshot_path"]).write_bytes(b"corrupt")

    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
        fail_option_symbols=("AEM",),
    )

    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(payload, "AEM")
    assert aem["snapshot_path"] is None
    assert aem["source_refresh_run_id"] is None
    assert aem["carried_forward"] is False


def test_corrupt_prior_feature_is_not_carried(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    prior = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    prior_aem = _manifest_entry(prior, "AEM")
    paths.resolve_repo_relative(prior_aem["feature_path"]).write_bytes(b"corrupt")

    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
        fail_option_symbols=("AEM",),
    )

    payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(payload, "AEM")
    assert aem["snapshot_path"] is None
    assert aem["feature_path"] is None
    assert aem["source_refresh_run_id"] is None


def test_next_success_replaces_a_carried_ticker(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 1),
        fail_option_symbols=("AEM",),
    )
    carried = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    assert _manifest_entry(carried, "AEM")["carried_forward"] is True

    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 6, 2),
    )

    latest = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    aem = _manifest_entry(latest, "AEM")
    assert aem["carried_forward"] is False
    assert aem["source_refresh_run_id"] == latest["refresh_run_id"]
    assert aem["source_as_of_date"] == "2026-06-02"
    assert aem["attempt_status"] == "SUCCESS"


def test_full_outage_without_prior_options_publishes_explicit_unavailable_state(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    old_manifest = {"refresh_run_id": "old-options-run", "snapshots": []}
    paths.latest_options_manifest_path.write_text(
        json.dumps(old_manifest),
        encoding="utf-8",
    )
    loaded = load_app_config(paths)
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    client = _OptionsPhaseClient(
        fixture,
        fail_all_options=True,
    )

    result = run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=loaded.app,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == "WARN"
    assert result.manifest_path == paths.latest_options_manifest_path
    assert result.summary["options_vendor_outage_status"] == "FULL_OUTAGE"
    assert result.summary["options_feature_row_count"] == 0
    assert result.summary["options_feature_file_count"] == 0
    assert result.summary["options_unavailable_count"] == result.summary["options_ticker_count"]
    latest = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    assert latest["refresh_run_id"] == context.run_id
    assert latest != old_manifest
    assert all(item["snapshot_path"] is None for item in latest["snapshots"])
    assert all(item["attempt_status"] == "ERROR" for item in latest["snapshots"])
    assert not (paths.options_features_dir / "AEM.parquet").exists()
    manifest = read_manifest(context.run_dir)
    assert manifest["options_manifest_status"] == "captured"


def test_full_outage_carries_every_verified_prior_ticker_bundle(tmp_path):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    fixture = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    _run_phase(
        paths=paths,
        app_config=loaded.app,
        fixture=fixture,
        as_of_date=date(2026, 5, 29),
    )
    prior = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))

    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    result = run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=loaded.app,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=date(2026, 6, 1),
        yahoo_client=_OptionsPhaseClient(fixture, fail_all_options=True),
    )

    assert result.status == "WARN"
    assert result.summary["options_vendor_outage_status"] == "FULL_OUTAGE"
    assert result.summary["options_carried_forward_count"] == result.summary[
        "options_ticker_count"
    ]
    assert result.summary["options_unavailable_count"] == 0
    latest = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    prior_by_ticker = {item["ticker"]: item for item in prior["snapshots"]}
    for item in latest["snapshots"]:
        assert item["carried_forward"] is True
        assert item["attempt_status"] == "ERROR"
        assert item["source_refresh_run_id"] == prior_by_ticker[item["ticker"]][
            "source_refresh_run_id"
        ]
        assert item["snapshot_path"].startswith(
            f"data/runs/{context.run_id}/snapshots/options/"
        )
        assert item["feature_path"].startswith(
            f"data/runs/{context.run_id}/snapshots/options_features/"
        )
    # Re-publishing stored evidence must not invent another historical capture.
    assert len(pd.read_parquet(paths.options_features_dir / "AEM.parquet").index) == 1


def test_run_options_ingestion_phase_computes_features_without_snapshot_readback(
    tmp_path,
    monkeypatch,
):
    paths = build_test_paths(tmp_path)
    loaded = load_app_config(paths)
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    client = _OptionsPhaseClient(pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet"))

    monkeypatch.setattr(
        options_phase_module.pd,
        "read_parquet",
        lambda *_, **__: (_ for _ in ()).throw(
            AssertionError("feature computation should use the in-memory snapshot")
        ),
    )

    result = run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=loaded.app,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=date(2026, 5, 29),
        yahoo_client=client,
    )

    assert result.status == "PASS"
    assert (paths.options_features_dir / "AEM.parquet").exists()


def test_append_feature_rows_replaces_existing_row_for_same_run(tmp_path):
    paths = build_test_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    row = {
        "ticker": "AEM",
        "run_id": context.run_id,
        "as_of_date": "2026-05-29",
        "atm_iv_60d": 0.40,
    }

    options_phase_module._append_feature_rows(
        paths=paths,
        run_context=context,
        feature_rows=[row],
    )
    options_phase_module._append_feature_rows(
        paths=paths,
        run_context=context,
        feature_rows=[{**row, "atm_iv_60d": 0.45}],
    )

    frame = pd.read_parquet(paths.options_features_dir / "AEM.parquet")
    assert len(frame.index) == 1
    assert frame.loc[0, "atm_iv_60d"] == 0.45


def test_skipped_options_phase_summary_records_operator_choice():
    summary = skipped_options_phase_summary(reason="Operator passed --no-options.")

    assert summary == {
        "options_phase_status": "SKIPPED",
        "options_phase_requested": False,
        "options_phase_skip_reason": "Operator passed --no-options.",
    }


class _OptionsPhaseClient:
    def __init__(
        self,
        fixture: pd.DataFrame,
        *,
        option_symbols: tuple[str, ...] = ("AEM", "GDX", "GDXJ"),
        fail_option_symbols: tuple[str, ...] = (),
        fail_all_options: bool = False,
    ) -> None:
        self.fixture = fixture
        self.option_symbols = {symbol.upper() for symbol in option_symbols}
        self.fail_option_symbols = {symbol.upper() for symbol in fail_option_symbols}
        self.fail_all_options = fail_all_options

    def fetch_options_expirations(self, symbol: str) -> list[str]:
        if self.fail_all_options or symbol.upper() in self.fail_option_symbols:
            raise RuntimeError(f"synthetic options outage for {symbol}")
        if symbol.upper() in self.option_symbols:
            return sorted(self.fixture["expiration"].astype(str).unique().tolist())
        return []

    def fetch_fast_info(self, symbol: str) -> dict[str, object]:
        return {"last_price": 50.0}

    def fetch_option_chain(self, symbol: str, expiration: str) -> _OptionChain:
        rows = self.fixture[self.fixture["expiration"].astype(str) == expiration]
        puts = rows[rows["option_type"] == "P"].drop(columns=["option_type"])
        calls = rows[rows["option_type"] == "C"].drop(columns=["option_type"])
        return _OptionChain(puts=puts.reset_index(drop=True), calls=calls.reset_index(drop=True))

    def fetch_history(self, symbol: str, period: str = "max", interval: str = "1d") -> pd.DataFrame:
        if symbol == "^IRX":
            return pd.DataFrame([{"Date": "2026-05-29", "Close": 4.3}])
        return pd.DataFrame(
            [
                {
                    "Date": "2026-05-29",
                    "Open": 40.0,
                    "High": 41.0,
                    "Low": 39.0,
                    "Close": 40.5,
                    "Adj Close": 40.5,
                    "Volume": 1000,
                }
            ]
        )


def _price_history() -> pd.DataFrame:
    # return_basis_usd is a USD price LEVEL, not a return series.
    prices = [100.0]
    for step in ([0.001, -0.002, 0.003, -0.001] * 30)[:119]:
        prices.append(prices[-1] * (1 + step))
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=120),
            "adj_close_usd": [45 + index * 0.02 for index in range(120)],
            "return_basis_usd": prices,
        }
    )


def _run_phase(
    *,
    paths,
    app_config,
    fixture: pd.DataFrame,
    as_of_date: date,
    fail_option_symbols: tuple[str, ...] = (),
    option_symbols: tuple[str, ...] = ("AEM", "GDX", "GDXJ"),
):
    context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    return run_options_ingestion_phase(
        paths=paths,
        run_context=context,
        app_config=app_config,
        normalized_equity_histories={"AEM": _price_history()},
        as_of_date=as_of_date,
        yahoo_client=_OptionsPhaseClient(
            fixture,
            fail_option_symbols=fail_option_symbols,
            option_symbols=option_symbols,
        ),
    )


def _manifest_entry(manifest: dict[str, object], ticker: str) -> dict[str, object]:
    return next(
        item
        for item in manifest["snapshots"]
        if item["ticker"] == ticker
    )
