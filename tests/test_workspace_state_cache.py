"""Loader memoization contract (deep-review perf fix, 2026-08-11).

The two per-request loaders memoize on a (path, mtime_ns, size) signature of
every input file. These tests prove the three things that make that safe:
unchanged inputs are NOT re-read, ANY input change invalidates, and degraded
loads are never cached. Route-level freshness (a save is visible on the next
GET) is additionally covered by the existing form round-trip tests in
test_redesign_routes.py, which run through the same cache.
"""

from __future__ import annotations

import os

import pytest

from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.screening.manual_store import upsert_company_input
from golden_vector.serve import workspace_state
from golden_vector.serve.workspace_state import (
    _load_tool_a_detail,
    _load_workspace_state,
    clear_workspace_state_cache,
)
from tests.helpers import build_test_paths
from tests.test_workspace_app import (
    _repo_app_config,
    _write_latest_foundation_snapshot,
    _write_latest_outputs,
)


@pytest.fixture(autouse=True)
def _isolated_cache():
    clear_workspace_state_cache()
    yield
    clear_workspace_state_cache()


def _full_paths(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    _write_latest_foundation_snapshot(paths)
    _write_latest_outputs(paths)
    return paths


def test_state_loader_reads_once_for_unchanged_inputs(tmp_path, monkeypatch):
    paths = _full_paths(tmp_path)
    calls = {"n": 0}
    real = workspace_state.read_current_model_parquet

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(workspace_state, "read_current_model_parquet", counting)

    first = _load_workspace_state(paths, ["NEM"])
    reads_first = calls["n"]
    assert reads_first > 0
    second = _load_workspace_state(paths, ["NEM"])

    assert calls["n"] == reads_first, "cache hit must not re-read artifacts"
    assert second.latest_tool_a.equals(first.latest_tool_a)
    # The per-request views are distinct objects: a renderer's column edit
    # cannot write into the cached frame.
    assert second.latest_tool_a is not first.latest_tool_a


def test_state_loader_recomputes_after_a_manual_save(tmp_path, monkeypatch):
    paths = _full_paths(tmp_path)
    calls = {"n": 0}
    real = workspace_state.read_current_model_parquet

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(workspace_state, "read_current_model_parquet", counting)

    _load_workspace_state(paths, ["NEM"])
    reads_first = calls["n"]
    upsert_company_input(paths, ticker="NEM", values={"aisc_usd_per_oz": 1234.0})
    state = _load_workspace_state(paths, ["NEM"])

    assert calls["n"] > reads_first, "a store write must invalidate the cache"
    row = state.company_inputs.loc[state.company_inputs["ticker"] == "NEM"].iloc[0]
    assert float(row["aisc_usd_per_oz"]) == 1234.0


def test_detail_loader_computes_once_then_invalidates_on_artifact_change(
    tmp_path, monkeypatch
):
    paths = _full_paths(tmp_path)
    app_config = _repo_app_config()
    calls = {"n": 0}
    real = workspace_state.compute_horizon_returns_for_ticker

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(workspace_state, "compute_horizon_returns_for_ticker", counting)

    first = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")
    assert first.foundation_error is None
    assert calls["n"] == 1
    second = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")
    assert calls["n"] == 1, "cache hit must not recompute horizons"
    assert second.weekly_series.equals(first.weekly_series)

    # Any signature file changing (here: the tool_a alias mtime) invalidates.
    alias = paths.latest_tool_a_snapshot_parquet_path
    stat = os.stat(alias)
    os.utime(alias, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")
    assert calls["n"] == 2, "an artifact change must invalidate the detail cache"


def test_detail_loader_never_caches_degraded_loads(tmp_path, monkeypatch):
    paths = _full_paths(tmp_path)
    app_config = _repo_app_config()
    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise OSError("foundation unavailable (transient)")

    monkeypatch.setattr(
        workspace_state, "resolve_current_foundation_manifest_path", boom
    )

    first = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")
    second = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")

    assert first.foundation_error is not None
    assert second.foundation_error is not None
    assert calls["n"] == 2, "degraded loads must retry, never serve from cache"


def test_distinct_tickers_get_distinct_detail_entries(tmp_path):
    paths = _full_paths(tmp_path)
    app_config = _repo_app_config()

    nem = _load_tool_a_detail(paths, app_config=app_config, ticker="NEM")
    other = _load_tool_a_detail(paths, app_config=app_config, ticker="ZZZ")

    assert nem.foundation_error is None
    # ZZZ has no history in the fixture: its detail state must not leak NEM's.
    assert other.weekly_series.empty or not other.weekly_series.equals(nem.weekly_series)
