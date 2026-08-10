"""Unit tests for the shared structural-window resolver (serve/windows.py)."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import ConfidenceThresholds
from golden_vector.serve.windows import (
    DEFAULT_WINDOW,
    DISPLAY_WINDOWS,
    SCORING_WINDOWS,
    STRUCTURAL_WINDOWS,
    r2_band,
    render_window_selector,
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


_BANDS = ConfidenceThresholds()


def test_r2_band_thresholds():
    assert r2_band(0.55, thresholds=_BANDS) == ("strong", True)
    assert r2_band(0.30, thresholds=_BANDS) == ("moderate", True)
    assert r2_band(0.15, thresholds=_BANDS) == ("weak", False)
    assert r2_band(0.02, thresholds=_BANDS) == ("none", False)
    assert r2_band(None, thresholds=_BANDS) == ("—", False)


def test_window_is_reliable_treats_ELIGIBLE_as_usable():
    """Regression for the shipped Phase-1 bug: Tool A writes window_status='ELIGIBLE'
    for usable windows, so an ELIGIBLE window with a strong fit must be reliable (it was
    being muted because only ('','OK') counted). Reliability = status_ok AND fit_ok; the
    per-window sample-size floor lives in config and is enforced upstream via the status
    (a thin window is written LOW_OBSERVATION, not ELIGIBLE) — there is no serve weeks gate."""
    strong_eligible = {"r_squared": 0.54, "status": "ELIGIBLE", "weeks": 52}
    assert window_is_reliable(strong_eligible, thresholds=_BANDS) is True
    # weak fit stays muted even when ELIGIBLE
    assert window_is_reliable({"r_squared": 0.12, "status": "ELIGIBLE", "weeks": 52}, thresholds=_BANDS) is False
    # a thin sample is muted via its status (the model routes it to LOW_OBSERVATION) — this
    # is the canonical degraded-data signal, NOT a hardcoded serve week floor.
    assert window_is_reliable({"r_squared": 0.54, "status": "LOW_OBSERVATION", "weeks": 8}, thresholds=_BANDS) is False
    assert window_is_reliable({"r_squared": 0.54, "status": "INELIGIBLE", "weeks": 52}, thresholds=_BANDS) is False
    # plain OK / explicit empty still count as usable (defensive legacy blank status),
    # but a missing/null status is degraded, not silently treated as trustworthy.
    assert window_is_reliable({"r_squared": 0.54, "status": "OK", "weeks": 52}, thresholds=_BANDS) is True
    assert window_is_reliable({"r_squared": 0.54, "status": "", "weeks": 52}, thresholds=_BANDS) is True
    assert window_is_reliable({"r_squared": 0.54, "status": None, "weeks": 52}, thresholds=_BANDS) is False
    assert window_is_reliable({"r_squared": 0.54, "status": pd.NA, "weeks": 52}, thresholds=_BANDS) is False
    assert window_is_reliable({"r_squared": 0.54, "weeks": 52}, thresholds=_BANDS) is False


def test_window_metrics_reads_the_selected_window_columns():
    row = {
        "up_beta_12m": 0.69, "down_beta_12m": 0.66, "structural_delta_12m": 1.2,
        "gamma_12m": -0.03, "asymmetry_ratio_12m": 1.04, "r_squared_12m": 0.54,
        "weeks_12m": 52, "window_status_12m": "ELIGIBLE",
        "up_beta_3y": 1.14, "down_beta_3y": 0.81,
        # display-only windows
        "up_beta_2y": 1.31, "down_beta_2y": 1.02, "structural_delta_2y": 1.6,
        "gamma_2y": 0.05, "asymmetry_ratio_2y": 1.28, "r_squared_2y": 0.41,
        "weeks_2y": 104, "window_status_2y": "ELIGIBLE",
        "up_beta_5y": 1.45, "down_beta_5y": 1.10, "r_squared_5y": 0.33,
        "weeks_5y": 143, "window_status_5y": "LOW_OBSERVATION",
    }
    m = window_metrics(row, "12M")
    assert m["up_beta"] == 0.69 and m["down_beta"] == 0.66 and m["r_squared"] == 0.54
    assert m["status"] == "ELIGIBLE"
    m3y = window_metrics(row, "3Y")
    assert m3y["up_beta"] == 1.14 and m3y["down_beta"] == 0.81
    # the new display-only windows read their own *_2y / *_5y columns
    m2y = window_metrics(row, "2Y")
    assert m2y["up_beta"] == 1.31 and m2y["down_beta"] == 1.02 and m2y["r_squared"] == 0.41
    assert m2y["weeks"] == 104 and m2y["status"] == "ELIGIBLE"
    m5y = window_metrics(row, "5Y")
    assert m5y["up_beta"] == 1.45 and m5y["down_beta"] == 1.10 and m5y["status"] == "LOW_OBSERVATION"
    # a thin 5Y window (LOW_OBSERVATION) is muted even with a moderate fit; a healthy
    # control (2Y ELIGIBLE, moderate fit) stays reliable.
    assert window_is_reliable(m5y, thresholds=_BANDS) is False
    assert window_is_reliable(m2y, thresholds=_BANDS) is True


def test_scoring_and_display_window_split_is_consistent():
    # The exported split must cover the full ordered selector set with no overlap.
    assert set(SCORING_WINDOWS).isdisjoint(set(DISPLAY_WINDOWS))
    assert set(SCORING_WINDOWS) | set(DISPLAY_WINDOWS) == set(STRUCTURAL_WINDOWS)
    assert set(DISPLAY_WINDOWS) == {"2Y", "5Y"}


def test_render_window_selector_offers_all_five_windows_with_1y_label():
    html = render_window_selector("2Y", search="GOLD")
    # five tabs, in selector order, with 12M shown under the "1Y" label
    for window in STRUCTURAL_WINDOWS:
        assert f"window={window}" in html
    assert ">1Y</a>" in html  # 12M renders as 1Y
    assert ">2Y</a>" in html and ">5Y</a>" in html
    # the active window carries the 'active' class; the search term is preserved
    assert "window-tab active" in html and "window=2Y" in html
    assert "search=GOLD" in html


def test_r2_bands_come_from_config_not_literals():
    """Deep-review F3: editing the config MUST change the banding (the old
    literals ignored config entirely; the dead fit_* keys are gone)."""
    custom = ConfidenceThresholds(
        gold_link_r2_strong=0.9, gold_link_r2_moderate=0.6, gold_link_r2_weak=0.3
    )
    assert r2_band(0.55, thresholds=_BANDS) == ("strong", True)
    assert r2_band(0.55, thresholds=custom) == ("weak", False)
    assert r2_band(0.65, thresholds=custom) == ("moderate", True)
