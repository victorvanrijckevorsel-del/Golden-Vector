"""Codex options-review fixes for the option artifact source loaders.

- H3: a per-ticker feature failure records the ticker with an ERROR marker; the
  feature loader skips it instead of failing the whole build.
- H1: a healthy manifest ticker whose feature file has no row for the current run
  fails loud, never silently drops the ticker from the candidate/signal universe.
"""

import pandas as pd
import pytest

from golden_vector.hedge.option_artifact_sources import load_options_features
from golden_vector.ingestion.persist_options import safe_options_file_name
from tests.helpers import build_test_paths


def _write_feature(paths, ticker: str, run_id: str, *, drop: str | None = None) -> None:
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    path = paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet"
    row = {
        "ticker": ticker,
        "run_id": run_id,
        "optionability_tier": "directly_hedgeable",
        "underlying_price": 50.0,
        "atm_iv_90d": 0.4,
    }
    if drop is not None:
        row.pop(drop, None)
    pd.DataFrame([row]).to_parquet(path, index=False)


def test_load_options_features_skips_error_marked_ticker(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_feature(paths, "GDX", "run-1")
    # AEM errored this run: recorded with an ERROR marker and NO feature file.
    manifest = {
        "refresh_run_id": "run-1",
        "snapshots": [
            {"ticker": "GDX", "feature_status": "OK"},
            {"ticker": "AEM", "feature_status": "ERROR"},
        ],
    }

    features = load_options_features(paths=paths, manifest=manifest)

    assert set(features["ticker"]) == {"GDX"}  # AEM skipped cleanly, no raise


def test_load_options_features_fails_loud_on_healthy_ticker_missing_row(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_feature(paths, "GDX", "older-run")  # stale: carries no row for run-1
    manifest = {
        "refresh_run_id": "run-1",
        "snapshots": [{"ticker": "GDX", "feature_status": "OK"}],
    }

    with pytest.raises(ValueError, match="no row for refresh run"):
        load_options_features(paths=paths, manifest=manifest)


def test_load_options_features_fails_loud_on_missing_required_column(tmp_path):
    # A feature file missing a required base column (optionability_tier) must fail
    # loud at read, not silently drop the ticker downstream (audit M11).
    paths = build_test_paths(tmp_path)
    _write_feature(paths, "GDX", "run-1", drop="optionability_tier")
    manifest = {
        "refresh_run_id": "run-1",
        "snapshots": [{"ticker": "GDX", "feature_status": "OK"}],
    }

    with pytest.raises(Exception, match="optionability_tier"):
        load_options_features(paths=paths, manifest=manifest)
