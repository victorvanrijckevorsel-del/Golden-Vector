"""Render-level coverage for the rebased gold/stock/ETF overlay chart.

The old ``_render_rebased_overlay_panel`` wrapper was DELETED in M3c — the M3a
Performance section (``golden_vector/serve/ticker_page/sections.py``
``render_performance_section``) replaced that chart on the ticker page. The SVG
builder ``_build_multiline_overlay_svg`` is unchanged and still used, so every
assertion that pinned the *chart's* contract lives on here, addressed directly at
the builder: every supplied line is drawn, the percent gridlines bracket the span,
the crosshair embed carries the exact coordinate mapping, and corrupt dates
degrade instead of crashing.

The builder is now shared by three display modes — ``indexed`` (this file's
original subject), ``price`` (currency levels) and ``count`` (open interest) — so
the last block pins what each mode says about its own units, and that the default
mode still renders the rebased contract byte-for-byte.
"""

from __future__ import annotations

import json
import re
import subprocess
from html import unescape
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.serve.charts import _build_multiline_overlay_svg


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


def _full_series() -> dict[str, tuple[list, list]]:
    return _full_overlay()["12M"]


def _axis_labels(html: str) -> list[str]:
    """The y-axis gridline labels (the trailing two entries are the date labels)."""
    return re.findall(r'class="chart-label">([^<]+)</text>', html)


def _aria_label(html: str) -> str:
    return re.search(r'<svg [^>]*aria-label="([^"]+)"', html).group(1)


def _caption(html: str) -> str:
    return re.search(r"<caption>([^<]+)</caption>", html).group(1)


def _polyline_points(html: str) -> list[list[str]]:
    """Return each independently drawn line segment's coordinate pairs."""

    return [points.split() for points in re.findall(r'<polyline points="([^"]*)"', html)]


def _price_series() -> dict[str, tuple[list, list]]:
    """A share-price series in currency levels — nowhere near 100."""
    return {"Stock": (_window_dates(), [6.10, 6.40, 6.25, 6.80, 6.55, 7.05])}


def test_overlay_chart_draws_every_supplied_series_with_a_baseline():
    html = _build_multiline_overlay_svg(
        series_by_label=_full_series(),
        series_keys={"ABC": "stock", "Gold": "gold", "GDX": "gdx", "GDXJ": "gdxj"},
    )

    # One labelled line-pattern swatch per series — including the ticker itself.
    for label in ("ABC", "Gold", "GDX", "GDXJ"):
        assert f">{label}</span>" in html
    assert html.count('class="chart-legend-line"') == 4
    for key in ("stock", "gold", "gdx", "gdxj"):
        assert f'class="series-{key}" stroke-width="2"' in html
    # Four lines drawn, plus the dashed baseline at 100.
    assert html.count("<polyline") == 4
    assert "stroke-dasharray=\"3 3\"" in html
    assert "aria-label=\"Rebased price comparison\"" in html


def test_overlay_chart_has_percent_gridlines_and_crosshair_data():
    html = _build_multiline_overlay_svg(series_by_label=_full_series())

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
    payload = _overlay_payload(_build_multiline_overlay_svg(series_by_label=_full_series()))
    # indexed keeps the two-number tooltip: raw level + the percent label
    assert payload["labelOnly"] is False
    # Nothing in the embed the crosshair does not read: "base" was dead weight
    # that invited percent arithmetic back into the browser.
    assert "base" not in payload
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


def test_overlay_chart_degrades_when_a_benchmark_is_missing():
    series = _full_series()
    # Simulate GDXJ history being unavailable for this ticker.
    series.pop("GDXJ")

    html = _build_multiline_overlay_svg(
        series_by_label=series,
        series_keys={"ABC": "stock", "Gold": "gold", "GDX": "gdx", "GDXJ": "gdxj"},
    )

    # Still renders: stock + gold + GDX = three drawable lines.
    assert html.count("<polyline") == 3
    assert ">GDX</span>" in html
    assert 'class="series-gdx" stroke-width="2"' in html
    # GDXJ is now absent EVERYWHERE — no legend chip, nothing claiming it was drawn.
    assert "GDXJ" not in html


def test_count_mode_preserves_a_mid_series_gap_as_disconnected_visible_segments():
    dates = _window_dates(3)
    html = _build_multiline_overlay_svg(
        series_by_label={"Total open interest": (dates, [1200.0, None, 1800.0])},
        mode="count",
        unit="contracts",
        title="Open interest over time",
    )

    # Each complete capture remains a separate one-point polyline. A circle makes
    # that one-point segment visible; no SVG element connects across the missing day.
    segments = _polyline_points(html)
    assert len(segments) == 2
    assert [len(segment) for segment in segments] == [1, 1]
    assert html.count("<circle") == 2
    assert all('class="series-gdx"' in circle for circle in re.findall(r"<circle[^>]+>", html))


def test_leading_missing_values_keep_one_contiguous_polyline():
    dates = _window_dates(4)
    html = _build_multiline_overlay_svg(
        series_by_label={"ABC": (dates, [None, None, 100.0, 105.0])}
    )

    assert [len(segment) for segment in _polyline_points(html)] == [2]
    assert "<circle" not in html


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

// A labelOnly chart (price/count modes): the server pre-formats the WHOLE value,
// so the tooltip must print the label alone — never "51.0 (USD 51.00)".
const svg2 = new Element("svg");
svg2.setAttribute("data-overlay", JSON.stringify({
  top: 20,
  bottom: 212,
  labelOnly: true,
  ticks: [["2024-01-02", 696]],
  series: [{
    label: "NEM",
    series: "stock",
    byDate: { "2024-01-02": [88, 51.0, "USD 51.00"] }
  }]
}));

const document = {
  readyState: "complete",
  body: new Element("body"),
  listeners: {},
  querySelectorAll(selector) { return selector === "svg.overlay-chart" ? [svg, svg2] : []; },
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
svg.listeners.pointermove({ clientX: 196, clientY: 95 });
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

// Performance visibility changes are read from the SVG at pointer time. A
// hidden visual series must also leave the crosshair even on the same snapped
// date; the complete accessible table is server HTML and is never involved.
svg.setAttribute("data-hidden-series", "gold\" onclick=\"alert(1)");
svg.listeners.pointermove({ clientX: 196, clientY: 95 });
assert.ok(!tip.innerHTML.includes("&lt;img"));
assert.equal(tip.innerHTML, "<strong>2024-01-02</strong>");
svg.setAttribute("data-hidden-series", "");
svg.listeners.pointermove({ clientX: 196, clientY: 95 });
assert.ok(tip.innerHTML.includes("&lt;img src=x onerror=alert(1)&gt;"));

const firstLeft = tip.style.left;
tip.innerHTML = "SENTINEL";
svg.listeners.pointermove({ clientX: 190, clientY: 90 });
assert.equal(tip.innerHTML, "SENTINEL");
assert.notEqual(tip.style.left, firstLeft);

window.listeners.blur();
assert.equal(tip.hidden, true);

// The labelOnly chart re-opens the tooltip and prints the pre-formatted value
// alone; the indexed chart above already proved the "level (percent)" form.
svg2.listeners.pointermove({ clientX: 196, clientY: 95 });
assert.equal(tip.hidden, false);
assert.ok(tip.innerHTML.includes("NEM: USD 51.00"));
assert.ok(!tip.innerHTML.includes("51.0 ("));
assert.ok(!tip.innerHTML.includes("("));
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# display modes: the same builder, told explicitly what its values MEAN
# ---------------------------------------------------------------------------


def test_price_mode_labels_axis_crosshair_and_table_in_the_callers_currency():
    """Share-price levels are currency, not an index: the axis, the embedded
    crosshair label and the accessible cell must all carry the currency the
    CALLER supplied, produced by one formatter so they cannot diverge."""
    html = _build_multiline_overlay_svg(
        series_by_label=_price_series(),
        series_keys={"Stock": "stock"},
        data_table_id="chart-data-price",
        mode="price",
        unit="USD",
    )

    axis = _axis_labels(html)
    assert "USD 6.20" in axis and "USD 7.00" in axis
    payload = _overlay_payload(html)
    # the tooltip prints the pre-formatted label ALONE in this mode (one flag
    # shared with the table logic, proven at runtime by the node test above)
    assert payload["labelOnly"] is True
    # Currency labels need a wider gutter than "+30%": the first tick starts at
    # padding_left=76 here, against 48 for indexed (pinned in the default-mode
    # test) — the two modes must not silently share one gutter again.
    assert payload["ticks"][0][1] == 76.0
    stock = payload["series"][0]["byDate"]
    assert stock["2024-01-05"] == [pytest.approx(196.0, abs=40.0), 6.1, "USD 6.10"]
    assert stock["2024-02-09"][2] == "USD 7.05"
    # the table twin prints the SAME formatted value — units included, nothing truncated
    assert '<td class="numeric">USD 6.10</td>' in html
    assert '<td class="numeric">USD 7.05</td>' in html
    assert '<th scope="col" class="numeric">Stock</th>' in html
    assert '<th scope="row">2024-01-05</th>' in html
    assert _aria_label(html) == "Share price over time (USD)"
    assert _caption(html) == "Share price over time — USD per share"
    assert 'aria-label="Share price over time — chart data table"' in html


def test_price_mode_never_speaks_of_indexing_or_percent_change():
    html = _build_multiline_overlay_svg(
        series_by_label=_price_series(),
        data_table_id="chart-data-price",
        mode="price",
        unit="USD",
    )

    # "tabindex" on the scroll region is the only legitimate "index" substring.
    for wrong in ("Rebased", "rebase", "indexed", "Index", "%"):
        assert wrong not in html, wrong
    assert html.count("index") == html.count("tabindex")


def test_price_mode_draws_no_base_100_baseline_and_frames_the_real_prices():
    """A dashed line at 100 under a $7 stock would claim a rebase that never
    happened AND flatten the line; price mode must scale to the data alone."""
    html = _build_multiline_overlay_svg(
        series_by_label=_price_series(), mode="price", unit="USD"
    )

    assert "stroke-dasharray=\"3 3\"" not in html
    axis = [label for label in _axis_labels(html) if label.startswith("USD ")]
    assert axis, "price mode must still label its gridlines"
    assert all(6.0 <= float(label.removeprefix("USD ")) <= 7.2 for label in axis), axis
    # the drawn line uses the full plot height, not a sliver near a 100 baseline
    ys = [float(pair.split(",")[1]) for pair in re.search(r'points="([^"]+)"', html).group(1).split()]
    assert max(ys) - min(ys) > 100


def test_price_mode_honours_a_non_usd_currency_from_the_caller():
    """The currency is the caller's artifact fact; the builder never assumes USD."""
    html = _build_multiline_overlay_svg(
        series_by_label=_price_series(),
        data_table_id="chart-data-price",
        mode="price",
        unit="CAD",
    )

    assert "USD" not in html
    assert "CAD 6.20" in _axis_labels(html)
    assert _caption(html) == "Share price over time — CAD per share"


def test_sub_cent_price_mode_keeps_distinct_values_everywhere():
    dates = _window_dates(3)
    html = _build_multiline_overlay_svg(
        series_by_label={"Stock": (dates, [0.001, 0.0015, 0.002])},
        series_keys={"Stock": "stock"},
        data_table_id="chart-data-sub-cent-price",
        mode="price",
        unit="USD",
    )

    stock = _overlay_payload(html)["series"][0]["byDate"]
    assert stock["2024-01-05"][1:] == [0.001, "USD 0.0010"]
    assert stock["2024-01-12"][1:] == [0.0015, "USD 0.0015"]
    assert stock["2024-01-19"][1:] == [0.002, "USD 0.0020"]
    assert '<td class="numeric">USD 0.0010</td>' in html
    assert '<td class="numeric">USD 0.0015</td>' in html
    assert '<td class="numeric">USD 0.0020</td>' in html
    price_axis = [label for label in _axis_labels(html) if label.startswith("USD ")]
    assert len(price_axis) == len(set(price_axis))
    assert all(re.fullmatch(r"USD \d+\.\d{4}", label) for label in price_axis)


def test_tenth_dollar_price_mode_uses_three_decimals():
    dates = _window_dates(2)
    html = _build_multiline_overlay_svg(
        series_by_label={"Stock": (dates, [0.1, 0.15])},
        mode="price",
        unit="USD",
    )

    stock = _overlay_payload(html)["series"][0]["byDate"]
    assert stock["2024-01-05"][1:] == [0.1, "USD 0.100"]
    assert stock["2024-01-12"][1:] == [0.15, "USD 0.150"]


def test_count_mode_labels_plain_counts_and_owns_its_zero_baseline():
    dates = _window_dates()
    html = _build_multiline_overlay_svg(
        series_by_label={
            "Put open interest": (dates, [1200.0, 1400.0, 1500.0, 1450.0, 1600.0, 1800.0]),
        },
        data_table_id="chart-data-oi",
        mode="count",
        unit="contracts",
        title="Open interest over time",
    )

    axis = _axis_labels(html)
    assert "1,500" in axis and "0" in axis  # thousands separated, zero anchored
    assert "stroke-dasharray=\"3 3\"" in html  # the zero line stays meaningful for counts
    # the unit reaches the screen-reader label too — the axis is invisible there
    assert _aria_label(html) == "Open interest over time (contracts)"
    assert _caption(html) == "Open interest over time — contracts"
    assert '<td class="numeric">1,800</td>' in html
    for wrong in ("Rebased price comparison", "indexed value", "%"):
        assert wrong not in html, wrong


def test_count_mode_never_labels_two_gridlines_the_same():
    """A thin open-interest window (0–2 contracts) spans ~3 units, for which the
    1/2/5 step chooser picks 0.5 — finer than a whole contract. Rounded to the
    mode's own zero decimals that prints "0", "0", "1", "2", "2": two identical
    labels at different heights, which is an unreadable axis. The mode's
    precision is the floor for its own grid step."""
    dates = _window_dates()
    html = _build_multiline_overlay_svg(
        series_by_label={
            "Put open interest": (dates, [1.0, 2.0, 2.0, 1.0, 2.0, 2.0]),
        },
        mode="count",
        unit="contracts",
        title="Open interest over time",
    )

    # the trailing two chart-labels are the date labels, not gridlines
    labels = _axis_labels(html)[:-2]
    assert labels == ["0", "1", "2"], labels
    assert len(labels) == len(set(labels))
    # the control: a wide span was never at risk and keeps its unique labels
    wide = _axis_labels(
        _build_multiline_overlay_svg(
            series_by_label={"Put open interest": (dates, [1200.0, 1400.0, 1500.0, 1450.0, 1600.0, 1800.0])},
            mode="count",
            unit="contracts",
        )
    )[:-2]
    assert len(wide) == len(set(wide)), wide


def test_unit_bearing_modes_fail_loud_without_a_unit_and_reject_unknown_modes():
    """An unlabelled currency/count chart is a degraded state for the CALLER to
    disclose — the builder must never invent or omit the unit silently."""
    for mode in ("price", "count"):
        with pytest.raises(ValueError, match="requires an explicit unit"):
            _build_multiline_overlay_svg(series_by_label=_price_series(), mode=mode)
        with pytest.raises(ValueError, match="requires an explicit unit"):
            _build_multiline_overlay_svg(
                series_by_label=_price_series(), mode=mode, unit="   "
            )
    with pytest.raises(ValueError, match="unknown overlay display mode"):
        _build_multiline_overlay_svg(series_by_label=_price_series(), mode="bogus")


def test_default_mode_is_still_the_indexed_comparison():
    """Back-compat guard: callers that pass no mode keep the rebased contract."""
    html = _build_multiline_overlay_svg(
        series_by_label=_full_series(), data_table_id="chart-data-indexed"
    )

    assert _aria_label(html) == "Rebased price comparison"
    assert _caption(html) == (
        "Rebased price comparison — indexed value (change vs the rebase start)"
    )
    assert '<td class="numeric">100.0 (0%)</td>' in html
    assert "stroke-dasharray=\"3 3\"" in html
    # ...including its narrower 48px gutter (price mode widens to 76 for "USD 6.20")
    assert _overlay_payload(html)["ticks"][0][1] == 48.0


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
