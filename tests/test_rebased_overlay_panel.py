"""Render-level coverage for the rebased gold/stock/ETF overlay panel.

This chart replaced the old rolling-beta line: the beta NUMBERS now live in the
windowed table above, and this panel answers a different question — "did the
miner actually beat gold AND the gold-miner ETFs over the lookback?". The series
are rebased in the backend (``model.structural.build_rebased_comparison_series``);
the panel only draws them. The assertions below pin the user-facing contract:
every supplied line is drawn, a missing benchmark degrades to one fewer line
(never a crash), and too little data falls back to the unavailable panel.
"""

from __future__ import annotations

import pandas as pd

from golden_vector.serve.charts import _build_multiline_overlay_svg
from golden_vector.serve.detail_panels import _render_rebased_overlay_panel


def _window_dates(n: int = 6) -> list[pd.Timestamp]:
    return list(pd.date_range("2024-01-05", periods=n, freq="W-FRI"))


def _full_overlay() -> dict[str, dict[str, tuple[list, list]]]:
    dates = _window_dates()
    return {
        "12M": {
            "ABC": (dates, [100.0, 110.0, 105.0, 120.0, 118.0, 130.0]),
            "Gold": (dates, [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]),
            "GDX": (dates, [100.0, 105.0, 103.0, 108.0, 107.0, 112.0]),
            "GDXJ": (dates, [100.0, 108.0, 104.0, 114.0, 110.0, 122.0]),
        }
    }


def test_overlay_panel_draws_every_supplied_series_with_a_baseline():
    html = _render_rebased_overlay_panel(
        ticker="ABC",
        rebased_overlay_by_window=_full_overlay(),
        active_window="12M",
    )

    assert "Gold vs Stock vs Gold-Miner ETFs" in html
    assert "indexed to 100" in html
    # One legend chip per line — including the ticker itself.
    for label in ("ABC", "Gold", "GDX", "GDXJ"):
        assert f"&#9632; {label}" in html
    # Four lines drawn, plus the dashed baseline at 100.
    assert html.count("<polyline") == 4
    assert "stroke-dasharray=\"3 3\"" in html
    assert "aria-label=\"Rebased price comparison\"" in html


def test_overlay_panel_degrades_when_a_benchmark_is_missing():
    overlay = _full_overlay()
    # Simulate GDXJ history being unavailable for this ticker.
    overlay["12M"].pop("GDXJ")

    html = _render_rebased_overlay_panel(
        ticker="ABC",
        rebased_overlay_by_window=overlay,
        active_window="12M",
    )

    # Still renders: stock + gold + GDX = three drawable lines.
    assert html.count("<polyline") == 3
    assert "&#9632; GDX" in html
    # GDXJ is now absent EVERYWHERE — no legend chip AND no caption claim that it is shown
    # (the caption must name only the benchmarks that actually drew).
    assert "GDXJ" not in html
    assert "gold-miner ETF (GDX)" in html


def test_overlay_panel_caption_admits_when_no_benchmarks_are_available():
    dates = _window_dates()
    overlay = {
        "12M": {
            "ABC": (dates, [100.0, 110.0, 105.0, 120.0, 118.0, 130.0]),
            "Gold": (dates, [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]),
        }
    }

    html = _render_rebased_overlay_panel(
        ticker="ABC",
        rebased_overlay_by_window=overlay,
        active_window="12M",
    )

    # Two lines draw (gold + stock); the caption must not imply GDX/GDXJ are present.
    assert html.count("<polyline") == 2
    assert "benchmark history was unavailable" in html


def test_overlay_panel_falls_back_when_fewer_than_two_drawable_series():
    dates = _window_dates(3)
    overlay = {
        "12M": {
            # Only gold has data; an all-None stock line is not drawable.
            "Gold": (dates, [100.0, 101.0, 102.0]),
            "ABC": (dates, [None, None, None]),
        }
    }

    html = _render_rebased_overlay_panel(
        ticker="ABC",
        rebased_overlay_by_window=overlay,
        active_window="12M",
    )

    assert "Not Available Yet" in html
    assert "<polyline" not in html


def test_overlay_panel_falls_back_when_window_has_no_overlay():
    html = _render_rebased_overlay_panel(
        ticker="ABC",
        rebased_overlay_by_window={},
        active_window="12M",
    )

    assert "Not Available Yet" in html


def test_multiline_overlay_svg_does_not_crash_on_all_nat_dates():
    # Corrupt input: finite values but every date is NaT. min()/max() would yield NaT and
    # strftime would raise — the builder must skip NaT-dated points and degrade gracefully.
    nat_dates = list(pd.to_datetime([None, None, None]))
    html = _build_multiline_overlay_svg(
        series_by_label={"ABC": (nat_dates, [100.0, 110.0, 120.0])}
    )
    assert html == "<p>No comparison data available.</p>"


def test_multiline_overlay_svg_skips_only_the_nat_dated_points():
    dates = [pd.Timestamp("2024-01-05"), pd.NaT, pd.Timestamp("2024-01-19")]
    html = _build_multiline_overlay_svg(
        series_by_label={
            "ABC": (dates, [100.0, 110.0, 120.0]),
            "Gold": (dates, [100.0, 101.0, 102.0]),
        }
    )
    # Two valid-dated points per line survive; the chart still renders.
    assert "<polyline points=" in html
    assert "NaT" not in html
