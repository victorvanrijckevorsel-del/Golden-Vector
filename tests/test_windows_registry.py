"""Tests for the centralized window registry (golden_vector/common/windows.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.common import windows as reg


def test_window_sets_and_split():
    assert reg.ALL_WINDOWS == ("6M", "12M", "2Y", "3Y", "5Y")
    assert reg.SCORING_WINDOWS == ("6M", "12M", "3Y")
    assert reg.DISPLAY_WINDOWS == ("2Y", "5Y")
    assert reg.DEFAULT_WINDOW == "12M"
    # scoring + display partition the full set with no overlap.
    assert set(reg.SCORING_WINDOWS) | set(reg.DISPLAY_WINDOWS) == set(reg.ALL_WINDOWS)
    assert not (set(reg.SCORING_WINDOWS) & set(reg.DISPLAY_WINDOWS))


def test_labels_and_aliases():
    assert reg.WINDOW_LABELS == {"6M": "6M", "12M": "1Y", "2Y": "2Y", "3Y": "3Y", "5Y": "5Y"}
    assert reg.window_label("12M") == "1Y"
    # resolve_window normalises display label + case; junk falls back to the default.
    assert reg.resolve_window("1y") == "12M"
    assert reg.resolve_window("12M") == "12M"
    assert reg.resolve_window("3Y") == "3Y"
    assert reg.resolve_window("nonsense") == "12M"
    assert reg.resolve_window("") == "12M"
    assert reg.resolve_window(None) == "12M"


def test_suffix_weeks_scored():
    assert reg.window_suffix("12M") == "12m"
    assert {w: reg.window_weeks(w) for w in reg.ALL_WINDOWS} == {
        "6M": 26, "12M": 52, "2Y": 104, "3Y": 156, "5Y": 260,
    }
    assert {w: reg.is_scored(w) for w in reg.ALL_WINDOWS} == {
        "6M": True, "12M": True, "2Y": False, "3Y": True, "5Y": False,
    }


def test_window_offset_matches_legacy_parser():
    # Registry windows.
    assert reg.window_offset("6M") == pd.DateOffset(months=6)
    assert reg.window_offset("12M") == pd.DateOffset(months=12)
    assert reg.window_offset("2Y") == pd.DateOffset(years=2)
    assert reg.window_offset("3Y") == pd.DateOffset(years=3)
    assert reg.window_offset("5Y") == pd.DateOffset(years=5)
    # General fallback for non-registry horizon strings (e.g. the "1Y" alias).
    assert reg.window_offset("1Y") == pd.DateOffset(years=1)
    assert reg.window_offset("9M") == pd.DateOffset(months=9)


def test_unknown_window_fails_loud():
    assert reg.is_window("7Q") is False
    with pytest.raises(ValueError):
        reg.get_window("7Q")
    with pytest.raises(ValueError):
        reg.window_offset("banana")


def test_serve_windows_reexports_registry():
    # serve.windows must re-export the registry names so existing imports keep working.
    from golden_vector.serve import windows as sw

    assert sw.STRUCTURAL_WINDOWS == reg.ALL_WINDOWS
    assert sw.SCORING_WINDOWS == reg.SCORING_WINDOWS
    assert sw.WINDOW_LABELS == reg.WINDOW_LABELS
    assert sw.resolve_window("1y") == "12M"
    assert sw.window_suffix("3Y") == "3y"
