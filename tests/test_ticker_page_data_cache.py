"""The bounded generation cache on load_ticker_page_data (plan §5.4).

Identity is the model-state POINTER stat alone: the five loaders are
manifest-first, so an unchanged pointer means an unchanged generation and a
changed pointer (every publish rewrites it last) means a new one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.serve.ticker_page import data as data_module
from golden_vector.serve.ticker_page.data import load_ticker_page_data
from tests.helpers import build_test_paths

_LOADER_NAMES = (
    "load_gold_response",
    "load_score_percentiles",
    "load_performance_series",
    "load_research_series",
    "load_fx_attribution",
)


class _FakeState:
    status = "OK"

    def __init__(self) -> None:
        self.frame = pd.DataFrame()


@pytest.fixture()
def loader_calls(monkeypatch):
    calls = {"n": 0}

    def _fake_loader(paths):
        calls["n"] += 1
        return _FakeState()

    for name in _LOADER_NAMES:
        monkeypatch.setattr(data_module, name, _fake_loader)
    return calls


def _paths_with_pointer(tmp_path):
    paths = build_test_paths(tmp_path / "workspace")
    pointer = paths.latest_model_state_manifest_path
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("{}", encoding="utf-8")
    return paths, pointer


def test_same_pointer_stat_serves_the_cached_generation(tmp_path, loader_calls):
    paths, _ = _paths_with_pointer(tmp_path)

    first = load_ticker_page_data(paths)
    assert loader_calls["n"] == len(_LOADER_NAMES)

    second = load_ticker_page_data(paths)
    assert second is first
    assert loader_calls["n"] == len(_LOADER_NAMES)  # zero re-reads


def test_pointer_rewrite_invalidates_the_cache(tmp_path, loader_calls):
    paths, pointer = _paths_with_pointer(tmp_path)

    first = load_ticker_page_data(paths)
    # Every publish rewrites the pointer last; a longer body guarantees a new
    # stat even on filesystems with coarse mtime granularity.
    pointer.write_text('{"generation": "next"}', encoding="utf-8")

    second = load_ticker_page_data(paths)
    assert second is not first
    assert loader_calls["n"] == 2 * len(_LOADER_NAMES)


def test_missing_pointer_is_cached_until_the_first_publish(tmp_path, loader_calls):
    paths = build_test_paths(tmp_path / "workspace")
    pointer = paths.latest_model_state_manifest_path
    assert not pointer.exists()

    first = load_ticker_page_data(paths)
    again = load_ticker_page_data(paths)
    assert again is first
    assert loader_calls["n"] == len(_LOADER_NAMES)

    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text("{}", encoding="utf-8")
    published = load_ticker_page_data(paths)
    assert published is not first
    assert loader_calls["n"] == 2 * len(_LOADER_NAMES)


def test_transient_corrupt_read_is_not_pinned_under_unchanged_pointer(
    tmp_path, monkeypatch
):
    paths, _ = _paths_with_pointer(tmp_path)
    calls = {name: 0 for name in _LOADER_NAMES}

    def _loader(name):
        def _read(_paths):
            calls[name] += 1
            status = (
                "CORRUPT"
                if name == "load_performance_series" and calls[name] == 1
                else "OK"
            )
            return TickerPageArtifactState(
                status=status,
                reason="temporary read error" if status == "CORRUPT" else None,
                frame=pd.DataFrame(),
            )

        return _read

    for name in _LOADER_NAMES:
        monkeypatch.setattr(data_module, name, _loader(name))

    first = load_ticker_page_data(paths)
    recovered = load_ticker_page_data(paths)
    cached = load_ticker_page_data(paths)

    assert first.performance.status == "CORRUPT"
    assert recovered.performance.status == "OK"
    assert cached is recovered
    assert set(calls.values()) == {2}
