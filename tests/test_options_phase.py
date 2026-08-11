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
    manifest = read_manifest(context.run_dir)
    assert manifest["options_manifest_status"] == "captured"
    source_asset_names = {
        item["name"]
        for item in manifest["options_manifest_captured"]["source_assets"]
    }
    assert "options:GDX.parquet" in source_asset_names
    assert "options:GDXJ.parquet" in source_asset_names


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
    aem_features = pd.read_parquet(paths.options_features_dir / "AEM.parquet")
    assert aem_features.loc[0, "options_fetch_status"] == "ERROR"
    assert "synthetic options outage" in aem_features.loc[0, "options_fetch_message"]


def test_run_options_ingestion_phase_full_outage_keeps_latest_manifest(tmp_path):
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

    assert result.status == "FAIL"
    assert result.manifest_path is None
    assert result.summary["options_vendor_outage_status"] == "FULL_OUTAGE"
    assert result.summary["options_feature_row_count"] == 0
    assert result.summary["options_feature_file_count"] == 0
    assert json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8")) == old_manifest
    assert not (paths.options_features_dir / "AEM.parquet").exists()
    manifest = read_manifest(context.run_dir)
    assert manifest["options_manifest_status"] == "not-applicable"


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
