from dataclasses import dataclass
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.replay_manifest import read_manifest
from golden_vector.app.run_context import RunContext
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
    assert (context.run_dir / "snapshots" / "benchmarks" / "GDX.parquet").exists()
    aem_features = pd.read_parquet(paths.options_features_dir / "AEM.parquet")
    assert aem_features.loc[0, "ticker"] == "AEM"
    assert bool(aem_features.loc[0, "options_available"]) is True
    assert aem_features.loc[0, "iv_percentile_cross_sectional"] == 100.0
    manifest = read_manifest(context.run_dir)
    assert manifest["options_manifest_status"] == "captured"


def test_skipped_options_phase_summary_records_operator_choice():
    summary = skipped_options_phase_summary(reason="Operator passed --no-options.")

    assert summary == {
        "options_phase_status": "SKIPPED",
        "options_phase_requested": False,
        "options_phase_skip_reason": "Operator passed --no-options.",
    }


class _OptionsPhaseClient:
    def __init__(self, fixture: pd.DataFrame) -> None:
        self.fixture = fixture

    def fetch_options_expirations(self, symbol: str) -> list[str]:
        if symbol == "AEM":
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
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=120),
            "adj_close_usd": [45 + index * 0.02 for index in range(120)],
            "return_basis_usd": [0.001, -0.002, 0.003, -0.001] * 30,
        }
    )
