"""Real-JS behaviour lock for the gold dial's state machine (redesign plan §4.3).

The dial is one of the three sanctioned client modules (ARCHITECTURE_FOUNDATIONS
:40-56), so its *behaviour* — not just its formulas — has to be pinned by running
the shipped file. These tests execute ``golden_vector/serve/static/gold-dial.js``
under node through ``vm.runInNewContext`` with a hand-rolled DOM shim, the same
pattern as the overlay-crosshair shim in ``test_rebased_overlay_panel.py`` and the
drawer shim in ``test_workspace_shell.py``. No jsdom, no npm, no new dependency.

**Node is REQUIRED.** Per the locked Codex decision (2026-08-10), required
JavaScript coverage must fail hard when node is missing — never skip.

The shim reproduces exactly one browser behaviour that the old code got wrong: a
``<input type="range" step="1">`` snaps ``value`` onto its step grid *before* any
script runs. So every fractional-spot case boots with ``input.value = "4477"``
while the payload carries the exact ``4477.4`` — which is precisely the state that
used to open the page in a scenario nobody asked for.

The payload is built by the real ``build_gold_dial_payload`` and every expected
cell string comes from ``mirror_evaluate`` + ``format_metric`` (the pinned parity
mirror), so these tests also re-prove backend/JS agreement at the scenario price.
``finance_source`` is not read by the module at all — the two sources differ only
in which row the server embeds, which the Python payload tests already cover.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd

from golden_vector.serve.ticker_page.corporate import (
    METRIC_FORMATS,
    build_gold_dial_payload,
    format_metric,
)
from tests.test_ticker_page_corporate import _gold_row, mirror_evaluate

DIAL_JS = Path("golden_vector/serve/static/gold-dial.js")

#: A spot the control cannot hold at step 1 — the defect's own reproduction.
FRACTIONAL_SPOT = 4477.4
#: What the browser leaves in ``input.value`` for that spot at step 1.
FRACTIONAL_BASELINE = "4477"
INTEGER_SPOT = 4452.0
INTEGER_BASELINE = "4452"

#: One line metric (client-evaluated at spot) and one card metric.
LINE_METRIC = "forward_revenue_musd"
CARD_METRIC = "ev_ebitda"

#: The server's no-JavaScript fallback for a line-metric spot cell.
PENDING_TEXT = "needs the gold dial (JavaScript)"
#: The server's persisted headline value for the card under test.
CARD_SPOT_TEXT = "6.72×"


def _payload(
    *, spot: float = FRACTIONAL_SPOT, enabled: bool = True, reason: str = "", **overrides
) -> dict:
    row = pd.Series(_gold_row(spot_gold_usd=spot, **overrides))
    return build_gold_dial_payload(
        row,
        ticker="NEM",
        finance_source="our",
        enabled=enabled,
        disabled_reason=reason,
    )


def _expected(payload: dict, metric: str, gold: float) -> str:
    """The cell string the backend mirror says the client must produce."""

    value, guard = mirror_evaluate(payload, metric, gold)
    if value is None:
        return guard
    return format_metric(value, METRIC_FORMATS[metric])


def _scenario_valuetext(gold: float, spot: float = FRACTIONAL_SPOT) -> str:
    """The State-C ``aria-valuetext``: the scenario AND the spot it moved from."""

    return (
        f"{format_metric(gold, 'usd')} per ounce, scenario · "
        f"spot {format_metric(spot, 'usd2')} per ounce"
    )


def _basis_at_rest(spot: float) -> str:
    """The server-rendered ``#gold-dial-basis`` text (corporate.py mirror)."""

    return f"spot {format_metric(spot, 'usd2')} as of 2026-08-11"


_SHIM = r"""
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class El {
  constructor(name, attrs) {
    this.name = name;
    this.attrs = Object.assign({}, attrs || {});
    this.listeners = {};
    this.style = {};
    this.classes = {};
    this.textContent = "";
    this.hidden = "hidden" in this.attrs;
    this.disabled = false;
    this.offsetWidth = 0;
    this.focusCount = 0;
    const self = this;
    this.classList = {
      add(name) { self.classes[name] = true; },
      remove(name) { delete self.classes[name]; },
      contains(name) { return Boolean(self.classes[name]); }
    };
  }
  setAttribute(key, value) {
    this.attrs[key] = String(value);
    if (key === "hidden") { this.hidden = true; }
  }
  getAttribute(key) { return key in this.attrs ? this.attrs[key] : null; }
  hasAttribute(key) { return key in this.attrs; }
  removeAttribute(key) {
    delete this.attrs[key];
    if (key === "hidden") { this.hidden = false; }
  }
  addEventListener(name, fn) { this.listeners[name] = fn; }
  focus() { this.focusCount += 1; doc.activeElement = this; }
}

var doc;
const timers = new Map();
let nextTimer = 1;
let reducedMotionQuery = null;

const payloadNode = new El("script");
payloadNode.textContent = __PAYLOAD__;

// The browser has ALREADY snapped the position onto the step grid by the time
// the module runs — that is the whole point of the fractional-spot cases.
const input = new El("input");
input.value = __VALUE__;
const output = new El("output");
const reset = new El("button");
reset.disabled = true;   // the server now renders it disabled at rest
const status = new El("p");
const basis = new El("span");
basis.textContent = __BASIS__;

const spotCell = new El("td", {"data-metric": "__LINE_METRIC__", "data-basis": "spot"});
spotCell.textContent = __PENDING__;
const scenarioCell = new El("td", {
  "data-metric": "__LINE_METRIC__", "data-basis": "scenario", hidden: "hidden"
});
const cardScenario = new El("p", {
  "data-metric": "__CARD_METRIC__", "data-basis": "scenario", hidden: "hidden"
});
const cardSpot = new El("p", {"data-headline-spot": "1"});
cardSpot.textContent = __CARD_SPOT__;
const scenarioHead = new El("th", {"data-scenario-head": "1", hidden: "hidden"});

const section = new El("section");
section.querySelectorAll = function (selector) {
  if (selector === '[data-metric][data-basis="spot"]') { return [spotCell]; }
  if (selector === '[data-metric][data-basis="scenario"]') { return [scenarioCell, cardScenario]; }
  if (selector === "[data-scenario-head]") { return [scenarioHead]; }
  if (selector === "[data-headline-spot]") { return [cardSpot]; }
  // An unmodelled selector must fail loudly rather than silently return nothing.
  throw new Error("unexpected selector: " + selector);
};

const NODES = {
  "gold-dial-payload": __PAYLOAD_NODE__,
  "gold-dial-input": input,
  "gold-dial-output": output,
  "gold-dial-reset": reset,
  "gold-dial-status": status,
  "gold-dial-basis": basis,
  "corporate-finance": section
};

doc = {
  readyState: "complete",
  activeElement: null,
  listeners: {},
  getElementById(id) { return NODES[id] || null; },
  addEventListener(name, fn) { this.listeners[name] = fn; }
};

const win = {
  matchMedia(query) { reducedMotionQuery = query; return {matches: __REDUCED__}; },
  setTimeout(fn) { const id = nextTimer; nextTimer += 1; timers.set(id, fn); return id; },
  clearTimeout(id) { timers.delete(id); }
};

function flush() {
  const pending = Array.from(timers.values());
  timers.clear();
  pending.forEach(function (fn) { fn(); });
}

function slide(value) { input.value = value; input.listeners.input(); }

vm.runInNewContext(
  fs.readFileSync("golden_vector/serve/static/gold-dial.js", "utf8"),
  {document: doc, window: win, console}
);

__BODY__
"""


def _run(
    body: str,
    *,
    payload: dict | None = None,
    value: str = FRACTIONAL_BASELINE,
    spot: float = FRACTIONAL_SPOT,
    with_payload: bool = True,
    reduced_motion: bool = False,
) -> None:
    """Run the shipped module against the shim and assert node exits clean."""

    assert DIAL_JS.exists(), f"{DIAL_JS} is missing"
    resolved = _payload(spot=spot) if payload is None else payload
    script = (
        _SHIM.replace("__PAYLOAD__", json.dumps(json.dumps(resolved)))
        .replace("__PAYLOAD_NODE__", "payloadNode" if with_payload else "null")
        .replace("__VALUE__", json.dumps(value))
        .replace("__BASIS__", json.dumps(_basis_at_rest(spot)))
        .replace("__PENDING__", json.dumps(PENDING_TEXT))
        .replace("__CARD_SPOT__", json.dumps(CARD_SPOT_TEXT))
        .replace("__LINE_METRIC__", LINE_METRIC)
        .replace("__CARD_METRIC__", CARD_METRIC)
        .replace("__REDUCED__", "true" if reduced_motion else "false")
        .replace("__BODY__", body)
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# state B — untouched spot (the fractional case that used to open a scenario)
# ---------------------------------------------------------------------------


def test_fractional_spot_boots_clean_with_one_value_per_card_and_no_announcement():
    payload = _payload()
    body = f"""
// Nothing was announced, and nothing was even queued to announce.
assert.equal(status.textContent, "");
flush();
assert.equal(status.textContent, "");

assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(scenarioCell.hidden, true);
assert.equal(scenarioCell.textContent, "");
assert.equal(cardScenario.hidden, true);
assert.equal(scenarioHead.hidden, true);

// ONE value per card: the persisted headline stays, untouched.
assert.equal(cardSpot.hidden, false);
assert.equal(cardSpot.textContent, {json.dumps(CARD_SPOT_TEXT)});

// The control reports the EXACT spot even though its position is the snapped one.
assert.equal(input.value, {json.dumps(FRACTIONAL_BASELINE)});
assert.equal(output.textContent, {json.dumps(format_metric(FRACTIONAL_SPOT, "usd2"))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(FRACTIONAL_SPOT, "usd2") + " per ounce, spot")}
);
assert.equal(basis.textContent, {json.dumps(_basis_at_rest(FRACTIONAL_SPOT))});

// The line-metric spot cell is evaluated at exact spot, not at the snapped position.
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, FRACTIONAL_SPOT))});
assert.notEqual(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, 4477.0))});
assert.equal(reducedMotionQuery, "(prefers-reduced-motion: reduce)");
"""
    _run(body, payload=payload)


def test_an_input_event_at_the_baseline_changes_nothing():
    """A no-op event (focus, a keypress that cannot move a bounded control) must
    not manufacture a scenario or an announcement."""

    body = """
input.listeners.input();
input.listeners.change();
flush();

assert.equal(status.textContent, "");
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(scenarioCell.hidden, true);
assert.equal(cardScenario.hidden, true);
assert.equal(cardSpot.hidden, false);
assert.equal(scenarioHead.hidden, true);
assert.equal(output.textContent, "$4,477.40");
"""
    _run(body)


# ---------------------------------------------------------------------------
# state C — an active scenario, entered only by a genuine move
# ---------------------------------------------------------------------------


def test_genuine_movement_activates_the_scenario_and_announces_once_debounced():
    payload = _payload()
    body = f"""
slide("4200");

// Debounced: the live region stays silent until the user stops moving.
assert.equal(status.textContent, "");
flush();
assert.equal(
  status.textContent,
  "Scenario $4,200 per ounce. Corporate finance values updated."
);

assert.equal(section.attrs["data-scenario-active"], "1");
assert.equal(reset.disabled, false);

// ONE value per card: the spot headline gives way to the scenario one.
assert.equal(cardSpot.hidden, true);
assert.equal(cardSpot.style.display, "none");
assert.equal(cardScenario.hidden, false);
assert.equal(cardScenario.textContent, {json.dumps(_expected(payload, CARD_METRIC, 4200.0))});

// The expanded table keeps BOTH, labelled: spot cell untouched, scenario column shown.
assert.equal(scenarioHead.hidden, false);
assert.equal(scenarioCell.hidden, false);
assert.equal(scenarioCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, 4200.0))});
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, FRACTIONAL_SPOT))});
assert.equal(scenarioCell.classes["is-updated"], true);

assert.equal(output.textContent, "$4,200");
assert.equal(input.attrs["aria-valuetext"], {json.dumps(_scenario_valuetext(4200))});
assert.equal(
  basis.textContent,
  {json.dumps("scenario $4,200 · baseline " + _basis_at_rest(FRACTIONAL_SPOT))}
);

// A keyboard step fires input then change: same handler, still one announcement.
input.value = "4201";
input.listeners.input();
input.listeners.change();
flush();
assert.equal(
  status.textContent,
  "Scenario $4,201 per ounce. Corporate finance values updated."
);
"""
    _run(body, payload=payload)


def test_a_scenario_that_cannot_be_evaluated_renders_its_guard_not_a_blank():
    """The stressed miner: forward EBITDA goes negative below break-even, so the
    card must say why rather than show zero, blank or infinity."""

    payload = _payload(
        line_slope_forward_ebitda_musd=1.0, line_intercept_forward_ebitda_musd=-5000.0
    )
    body = f"""
slide("2000");
assert.equal(cardScenario.hidden, false);
assert.equal(cardScenario.textContent, {json.dumps(_expected(payload, CARD_METRIC, 2000.0))});
assert.equal(cardScenario.attrs["data-unavailable"], "1");
assert.equal(cardSpot.hidden, true);
"""
    _run(body, payload=payload)


def test_reduced_motion_suppresses_the_update_flash():
    body = """
slide("4200");
assert.equal(scenarioCell.hidden, false);
assert.equal(scenarioCell.classes["is-updated"], undefined);
"""
    _run(body, reduced_motion=True)


# ---------------------------------------------------------------------------
# state D — returned and reset
# ---------------------------------------------------------------------------


def test_manual_return_to_the_baseline_clears_the_scenario_completely():
    payload = _payload()
    body = f"""
slide("4200");
flush();
slide({json.dumps(FRACTIONAL_BASELINE)});

assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(scenarioCell.hidden, true);
assert.equal(scenarioCell.textContent, "");
assert.equal(cardScenario.hidden, true);
assert.equal(scenarioHead.hidden, true);
assert.equal(cardSpot.hidden, false);
assert.equal(cardSpot.style.display, "");
assert.equal(output.textContent, {json.dumps(format_metric(FRACTIONAL_SPOT, "usd2"))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(FRACTIONAL_SPOT, "usd2") + " per ounce, spot")}
);
assert.equal(basis.textContent, {json.dumps(_basis_at_rest(FRACTIONAL_SPOT))});
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, FRACTIONAL_SPOT))});

// A user action DID happen, so this one is announced.
flush();
assert.equal(
  status.textContent,
  {json.dumps("Back at spot " + format_metric(FRACTIONAL_SPOT, "usd2") + " per ounce.")}
);
"""
    _run(body, payload=payload)


def test_reset_restores_the_saved_baseline_and_never_the_fractional_spot():
    body = f"""
slide("4200");
flush();
reset.listeners.click();

// The SAVED baseline: writing 4477.4 back would snap straight to a moved position.
assert.equal(input.value, {json.dumps(FRACTIONAL_BASELINE)});
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(scenarioCell.hidden, true);
assert.equal(cardScenario.hidden, true);
assert.equal(scenarioHead.hidden, true);
assert.equal(cardSpot.hidden, false);
assert.equal(output.textContent, {json.dumps(format_metric(FRACTIONAL_SPOT, "usd2"))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(FRACTIONAL_SPOT, "usd2") + " per ounce, spot")}
);

// Focus leaves the control that just disabled itself.
assert.equal(input.focusCount, 1);
assert.equal(doc.activeElement, input);

flush();
assert.equal(
  status.textContent,
  {json.dumps("Reset to spot " + format_metric(FRACTIONAL_SPOT, "usd2") + " per ounce.")}
);

// ...and the reset state is the clean state: no loop back into a scenario.
input.listeners.input();
flush();
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(cardSpot.hidden, false);
"""
    _run(body)


# ---------------------------------------------------------------------------
# integer spot, missing payload, disabled dial, out-of-range spot
# ---------------------------------------------------------------------------


def test_integer_spot_behaves_identically():
    """The fractional fix must not regress the on-grid case."""

    payload = _payload(spot=INTEGER_SPOT)
    body = f"""
assert.equal(status.textContent, "");
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(cardSpot.hidden, false);
assert.equal(output.textContent, {json.dumps(format_metric(INTEGER_SPOT, "usd2"))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(INTEGER_SPOT, "usd2") + " per ounce, spot")}
);
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, INTEGER_SPOT))});

slide("4300");
flush();
assert.equal(section.attrs["data-scenario-active"], "1");
assert.equal(cardSpot.hidden, true);
assert.equal(reset.disabled, false);

reset.listeners.click();
assert.equal(input.value, {json.dumps(INTEGER_BASELINE)});
assert.equal(cardSpot.hidden, false);
assert.equal(reset.disabled, true);
flush();
assert.equal(
  status.textContent,
  {json.dumps("Reset to spot " + format_metric(INTEGER_SPOT, "usd2") + " per ounce.")}
);
"""
    _run(body, payload=payload, value=INTEGER_BASELINE, spot=INTEGER_SPOT)


def test_a_missing_payload_leaves_the_server_rendered_page_untouched():
    body = f"""
assert.equal(spotCell.textContent, {json.dumps(PENDING_TEXT)});
assert.equal(cardSpot.hidden, false);
assert.equal(cardSpot.textContent, {json.dumps(CARD_SPOT_TEXT)});
assert.equal(scenarioCell.hidden, true);
assert.equal(status.textContent, "");
assert.equal(input.attrs["aria-valuetext"], undefined);
assert.equal(section.attrs["data-scenario-active"], undefined);
assert.equal(input.listeners.input, undefined);
"""
    _run(body, with_payload=False)


def test_a_disabled_dial_replaces_the_no_javascript_fallback_with_the_reason():
    reason = "linearity residual 41.2 exceeded tolerance at $6,000"
    body = f"""
assert.equal(input.disabled, true);
assert.equal(reset.disabled, true);
assert.equal(spotCell.textContent, {json.dumps(reason)});
assert.equal(spotCell.attrs["data-unavailable"], "1");
assert.equal(cardSpot.hidden, false);
assert.equal(status.textContent, "");
assert.equal(input.listeners.input, undefined);
"""
    _run(body, payload=_payload(enabled=False, reason=reason))


def test_a_spot_above_the_configured_range_still_boots_clean():
    """The browser clamps the position to max; the payload keeps the true spot.
    The clamped position is the baseline, so no scenario is manufactured."""

    payload = _payload(spot=7000.0)
    body = f"""
assert.equal(status.textContent, "");
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(cardSpot.hidden, false);
// Cells still report the TRUE spot, never the clamped control position.
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, 7000.0))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(7000.0, "usd2") + " per ounce, spot")}
);

slide("5900");
flush();
assert.equal(section.attrs["data-scenario-active"], "1");
assert.equal(cardSpot.hidden, true);
"""
    _run(body, payload=payload, value="6000", spot=7000.0)
