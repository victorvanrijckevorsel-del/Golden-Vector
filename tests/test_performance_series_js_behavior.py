"""Real-JavaScript lock for progressive Performance series visibility.

The server owns the complete chart and accessible table. This node DOM shim
proves the optional module reveals native controls and changes visual chart
nodes only. Node is required; a missing runtime is a hard test failure.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_performance_series_progressive_enhancement_keeps_table_complete():
    script = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class El {
  constructor(attrs) {
    this.attrs = Object.assign({}, attrs || {});
    this.listeners = {};
    this.style = {};
    this.checked = true;
    this.hidden = Object.prototype.hasOwnProperty.call(this.attrs, "hidden");
  }
  getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attrs, name) ? this.attrs[name] : null; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  removeAttribute(name) {
    delete this.attrs[name];
    if (name === "hidden") this.hidden = false;
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}

const stock = new El({
  "data-performance-series-input": "stock",
  "aria-controls": "performance-chart-nem-1y-rebased"
});
const gold = new El({
  "data-performance-series-input": "gold",
  "aria-controls": "performance-chart-nem-1y-rebased"
});
const root = new El({ hidden: "" });
root.querySelectorAll = function (selector) {
  assert.equal(selector, "[data-performance-series-input]");
  return [stock, gold];
};

const stockLine = new El();
const stockLegend = new El();
const goldLine = new El();
const goldLegend = new El();
const table = new El();
table.textContent = "complete accessible table sentinel";
const svg = new El();
const chart = new El();
chart.querySelectorAll = function (selector) {
  if (selector === ".series-stock, .legend-swatch-stock") return [stockLine, stockLegend];
  if (selector === ".series-gold, .legend-swatch-gold") return [goldLine, goldLegend];
  throw new Error("unexpected visual selector: " + selector);
};
chart.querySelector = function (selector) {
  assert.equal(selector, "svg.overlay-chart");
  return svg;
};

const document = {
  readyState: "complete",
  querySelectorAll(selector) {
    assert.equal(selector, "[data-performance-series]");
    return [root];
  },
  getElementById(id) {
    assert.equal(id, "performance-chart-nem-1y-rebased");
    return chart;
  },
  addEventListener() { throw new Error("complete document must initialise immediately"); }
};

vm.runInNewContext(
  fs.readFileSync("golden_vector/serve/static/performance-series.js", "utf8"),
  { document, console }
);

assert.equal(root.hidden, false);
assert.equal(stockLine.style.display, "");
assert.equal(goldLine.style.display, "");
assert.equal(svg.getAttribute("data-hidden-series"), null);

stock.checked = false;
stock.listeners.change({ currentTarget: stock });
assert.equal(stockLine.style.display, "none");
assert.equal(stockLegend.style.display, "none");
assert.equal(goldLine.style.display, "");
assert.equal(svg.getAttribute("data-hidden-series"), "stock");

gold.checked = false;
gold.listeners.change({ currentTarget: gold });
assert.equal(svg.getAttribute("data-hidden-series"), "stock,gold");
assert.equal(goldLine.style.display, "none");

stock.checked = true;
stock.listeners.change({ currentTarget: stock });
assert.equal(stockLine.style.display, "");
assert.equal(stockLegend.style.display, "");
assert.equal(svg.getAttribute("data-hidden-series"), "gold");

// The module never selects or mutates the chart's accessible table.
assert.equal(table.textContent, "complete accessible table sentinel");
assert.deepEqual(table.style, {});
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=Path.cwd(),
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
