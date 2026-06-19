"""Unit tests for the shared structural-window resolver (serve/windows.py)."""

from __future__ import annotations

from golden_vector.serve.windows import (
    DEFAULT_WINDOW,
    r2_band,
    resolve_window,
    window_is_reliable,
    window_metrics,
)


def test_resolve_window_normalises_aliases_and_defaults():
    assert resolve_window("6m") == "6M"
    assert resolve_window("1Y") == "12M"  # the display alias maps to the stored id
    assert resolve_window("12m") == "12M"
    assert resolve_window("3Y") == "3Y"
    assert resolve_window("") == DEFAULT_WINDOW
    assert resolve_window("garbage") == DEFAULT_WINDOW
    assert resolve_window(None) == DEFAULT_WINDOW


def test_r2_band_thresholds():
    assert r2_band(0.55) == ("strong", True)
    assert r2_band(0.30) == ("moderate", True)
    assert r2_band(0.15) == ("weak", False)
    assert r2_band(0.02) == ("none", False)
    assert r2_band(None) == ("—", False)


def test_window_is_reliable_treats_ELIGIBLE_as_usable():
    """Regression for the shipped Phase-1 bug: Tool A writes window_status='ELIGIBLE'
    for usable windows, so an ELIGIBLE window with a strong fit must be reliable (it was
    being muted because only ('','OK') counted)."""
    strong_eligible = {"r_squared": 0.54, "status": "ELIGIBLE", "weeks": 52}
    assert window_is_reliable(strong_eligible) is True
    # weak fit stays muted even when ELIGIBLE
    assert window_is_reliable({"r_squared": 0.12, "status": "ELIGIBLE", "weeks": 52}) is False
    # a problem status stays muted even with a strong fit
    assert window_is_reliable({"r_squared": 0.54, "status": "LOW_OBSERVATION", "weeks": 52}) is False
    assert window_is_reliable({"r_squared": 0.54, "status": "INELIGIBLE", "weeks": 52}) is False
    # a thin sample stays muted
    assert window_is_reliable({"r_squared": 0.54, "status": "ELIGIBLE", "weeks": 8}) is False
    # plain OK / empty still count as usable (defensive)
    assert window_is_reliable({"r_squared": 0.54, "status": "OK", "weeks": 52}) is True


def test_window_metrics_reads_the_selected_window_columns():
    row = {
        "up_beta_12m": 0.69, "down_beta_12m": 0.66, "structural_delta_12m": 1.2,
        "gamma_12m": -0.03, "asymmetry_ratio_12m": 1.04, "r_squared_12m": 0.54,
        "weeks_12m": 52, "window_status_12m": "ELIGIBLE",
        "up_beta_3y": 1.14, "down_beta_3y": 0.81,
    }
    m = window_metrics(row, "12M")
    assert m["up_beta"] == 0.69 and m["down_beta"] == 0.66 and m["r_squared"] == 0.54
    assert m["status"] == "ELIGIBLE"
    m3y = window_metrics(row, "3Y")
    assert m3y["up_beta"] == 1.14 and m3y["down_beta"] == 0.81
