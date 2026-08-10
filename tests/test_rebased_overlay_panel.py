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

import json
import re
import subprocess
from html import unescape
from pathlib import Path

import pandas as pd

from golden_vector.serve.charts import _build_multiline_overlay_svg
from golden_vector.serve.detail_panels import _render_rebased_overlay_panel


def _overlay_payload(html: str) -> dict:
    """Decode the embedded data-overlay JSON the crosshair JS consumes."""
    match = re.search(r'data-overlay="([^"]+)"', html)
    assert match, "overlay SVG must carry a data-overlay attribute"
    return json.loads(unescape(match.group(1)))


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


def test_overlay_chart_has_percent_gridlines_and_crosshair_data():
    html = _render_rebased_overlay_panel(
        ticker="ABC",
        rebased_overlay_by_window=_full_overlay(),
        active_window="12M",
    )

    # Readable y-axis: gridlines labelled as % change from the rebase start (not raw index nums).
    assert ">0%</text>" in html
    assert ">+30%</text>" in html
    # Hover crosshair hook: the SVG carries the embedded per-series data for overlay-crosshair.js.
    assert 'class="overlay-chart"' in html
    assert "data-overlay=" in html
    assert "byDate" in html  # embedded series points (escaped JSON)
    assert "2024-01-05" in html  # a tick date present in the embedded crosshair data


def test_overlay_embed_pins_the_coordinate_mapping():
    # Decode the data-overlay payload and assert the ACTUAL pixel mapping the crosshair relies on,
    # so a swapped/inverted x_at/y_at or a byDate field-order change fails the test (not silently
    # ships a misaligned crosshair). Fixture spans values 100..130 with base 100.
    payload = _overlay_payload(
        _render_rebased_overlay_panel(
            ticker="ABC", rebased_overlay_by_window=_full_overlay(), active_window="12M"
        )
    )
    assert payload["base"] == 100.0
    # First date sits at the left padding (x=48); the last at width-padding_right (720-24=696).
    assert payload["ticks"][0] == ["2024-01-05", 48.0]
    assert payload["ticks"][-1] == ["2024-02-09", 696.0]
    # One tick per calendar day — keyspace matches byDate exactly (no desync).
    tick_dates = [t[0] for t in payload["ticks"]]
    assert len(tick_dates) == len(set(tick_dates))
    abc = next(s for s in payload["series"] if s["label"] == "ABC")
    # The rebased start (value 100 == base) maps to y=196.0 and the pct label is "0%".
    assert abc["byDate"]["2024-01-05"] == [196.0, 100.0, "0%"]
    # A risen point carries a signed pct produced by the SAME server formatter as the gridlines.
    assert abc["byDate"]["2024-02-09"][1] == 130.0
    assert abc["byDate"]["2024-02-09"][2] == "+30%"


def test_overlay_embed_escapes_html_in_series_labels():
    # The crosshair reads labels from data-overlay; a label with HTML metacharacters must be
    # encoded in the attribute (and never appear raw anywhere in the SVG), so the innerHTML sink
    # in overlay-crosshair.js cannot be fed unescaped markup.
    dates = _window_dates()
    html = _build_multiline_overlay_svg(
        series_by_label={
            "<img src=x onerror=alert(1)>": (dates, [100.0, 110.0, 105.0, 120.0, 118.0, 130.0]),
            "Gold": (dates, [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]),
        }
    )
    assert "<img" not in html  # angle brackets are encoded, so no live <img> tag is emitted
    assert "&lt;img" in html  # the label survives only in escaped form
    payload = _overlay_payload(html)  # and the decoded data still carries the original label
    assert any("<img" in s["label"] for s in payload["series"])


def test_overlay_gridlines_bracket_a_tiny_low_volatility_span():
    # A nearly-flat window (all series within ~1% of 100) must still draw +/- gridlines, not just
    # the lone "0%" baseline label (finer step candidates below 5).
    dates = _window_dates()
    html = _build_multiline_overlay_svg(
        series_by_label={
            "ABC": (dates, [100.0, 100.5, 101.0, 100.8, 100.3, 101.0]),
            "Gold": (dates, [100.0, 99.7, 99.2, 99.5, 99.8, 99.0]),
        }
    )
    assert ">0%</text>" in html
    assert ">+1%</text>" in html
    assert ">-1%</text>" in html


def test_overlay_gridlines_bracket_a_sub_one_percent_span():
    dates = _window_dates()
    html = _build_multiline_overlay_svg(
        series_by_label={
            "ABC": (dates, [100.0, 100.05, 100.10, 100.08, 100.03, 100.10]),
            "Gold": (dates, [100.0, 99.97, 99.92, 99.95, 99.98, 99.90]),
        }
    )

    assert ">0%</text>" in html
    assert ">+0.1%</text>" in html
    assert ">-0.1%</text>" in html


def test_overlay_gridlines_stay_bounded_for_huge_rebased_spans():
    dates = _window_dates(2)
    html = _build_multiline_overlay_svg(
        series_by_label={
            "ABC": (dates, [100.0, 1_000_000_000.0]),
            "Gold": (dates, [100.0, 120.0]),
        }
    )

    assert 'class="overlay-chart"' in html
    assert html.count("<text") <= 20
    assert len(html) < 20_000


def test_overlay_crosshair_js_escapes_labels_and_has_no_percent_math():
    # Pin the JS contract that complements the server embed: labels are HTML-escaped before the
    # innerHTML write, and the percent is READ from the embed (no fmtPct recomputation in browser).
    js = Path("golden_vector/serve/static/overlay-crosshair.js").read_text(encoding="utf-8")
    assert "function esc(" in js
    assert "esc(s.label)" in js  # label escaped before entering innerHTML
    assert "esc(pt[2])" in js  # pre-formatted pct read from the embed
    assert "esc(s.series)" in js  # semantic series key escaped in the class attribute
    assert "s.color" not in js  # colour literals left the JS contract (semantic classes only)
    assert "fmtPct" not in js  # no percent arithmetic duplicated in JS


def test_overlay_crosshair_js_runtime_escapes_clamps_and_dismisses():
    script = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class Element {
  constructor(tag) {
    this.tag = tag;
    this.attrs = {};
    this.children = [];
    this.listeners = {};
    this.style = {};
    this.hidden = false;
    this.className = "";
    this.innerHTML = "";
    this.rect = { left: 0, top: 0, width: 200, height: 240 };
    this.viewBox = { baseVal: { width: 720, height: 240 } };
  }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] || null; }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  getBoundingClientRect() { return this.rect; }
}

const svg = new Element("svg");
svg.setAttribute("data-overlay", JSON.stringify({
  top: 20,
  bottom: 212,
  ticks: [["2024-01-01", 48], ["2024-01-02", 696]],
  series: [{
    label: "<img src=x onerror=alert(1)>",
    series: "gold\" onclick=\"alert(1)",
    byDate: {
      "2024-01-02": [88, 100.1, "<pct>"]
    }
  }]
}));

const document = {
  readyState: "complete",
  body: new Element("body"),
  listeners: {},
  querySelectorAll(selector) { return selector === "svg.overlay-chart" ? [svg] : []; },
  createElement(tag) {
    const el = new Element(tag);
    if (tag === "div") el.rect = { left: 0, top: 0, width: 80, height: 30 };
    return el;
  },
  createElementNS(_ns, tag) { return new Element(tag); },
  addEventListener(name, fn) { this.listeners[name] = fn; }
};
const window = {
  innerWidth: 200,
  innerHeight: 100,
  listeners: {},
  addEventListener(name, fn) { this.listeners[name] = fn; }
};

vm.runInNewContext(
  fs.readFileSync("golden_vector/serve/static/overlay-crosshair.js", "utf8"),
  { document, window, console }
);

const tip = document.body.children[0];
svg.listeners.mousemove({ clientX: 196, clientY: 95 });
assert.equal(tip.hidden, false);
assert.ok(tip.innerHTML.includes("&lt;img src=x onerror=alert(1)&gt;"));
assert.ok(!tip.innerHTML.includes("<img"));
assert.ok(tip.innerHTML.includes("(&lt;pct&gt;)"));
// The semantic series key flows through esc() into the class attribute of the
// innerHTML sink: a double-quote breakout attempt must arrive fully encoded.
assert.ok(tip.innerHTML.includes("legend-swatch-gold&quot; onclick=&quot;alert(1)"));
assert.ok(!tip.innerHTML.includes("onclick=\"alert"));
assert.equal(tip.style.left, "102px");
assert.equal(tip.style.top, "51px");

const firstLeft = tip.style.left;
tip.innerHTML = "SENTINEL";
svg.listeners.mousemove({ clientX: 190, clientY: 90 });
assert.equal(tip.innerHTML, "SENTINEL");
assert.notEqual(tip.style.left, firstLeft);

window.listeners.blur();
assert.equal(tip.hidden, true);
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


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


def test_overlay_panel_falls_back_when_series_have_only_one_dated_point():
    dates = [pd.Timestamp("2024-01-05")]
    overlay = {
        "12M": {
            "Gold": (dates, [100.0]),
            "ABC": (dates, [100.0]),
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
