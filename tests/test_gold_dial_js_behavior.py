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
script runs. Fractional-spot cases therefore boot with a snapped control
position while their payload keeps the exact price — precisely the state that
used to open the page in a scenario nobody asked for.

The payload is built by the real ``build_gold_dial_payload`` and every expected
cell string comes from ``mirror_evaluate`` + ``format_metric`` (the pinned parity
mirror), so these tests also re-prove backend/JS agreement at the scenario price.
``finance_source`` is intentionally not read by the module. Distinct Our View and
Yahoo sentinels still run through clean boot, movement, and Reset to prove the
selected row reaches the same source-agnostic state machine.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.common.numeric import optional_finite_float
from golden_vector.serve.ticker_page.corporate import (
    METRIC_FORMATS,
    METRIC_UNITS,
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

SOURCE_STATE_CASES = (
    pytest.param("our", FRACTIONAL_SPOT, FRACTIONAL_BASELINE, 4200.0, id="our-view"),
    pytest.param("yahoo", 4321.6, "4322", 4200.0, id="yahoo"),
)

#: One persisted line metric (client-evaluated only for scenarios) and one card metric.
LINE_METRIC = "forward_revenue_musd"
CARD_METRIC = "ev_ebitda"

#: The server's v2 persisted true-spot value for a line-metric spot cell. It is
#: intentionally different from slope * FRACTIONAL_SPOT, proving JavaScript does
#: not overwrite the producer's actual spot evaluation with its fitted line.
SERVER_SPOT_TEXT = "$26,267m"
#: What ``_spot_dial_cell`` ships when the artifact has no usable row.
UNAVAILABLE_TEXT = "Unavailable — see reason above"
#: The server's persisted headline value for the card under test.
CARD_SPOT_TEXT = "6.72×"


def _payload(
    *,
    spot: float = FRACTIONAL_SPOT,
    finance_source: str = "our",
    enabled: bool = True,
    reason: str = "",
    scenario_enabled: bool = True,
    scenario_reason: str = "",
    **overrides,
) -> dict:
    """The real server payload. ``enabled`` is ARTIFACT availability;
    ``scenario_enabled`` is whether the slider may move (see
    ``_dial_and_scenario_state``) — the two states behave differently and both
    are exercised below."""

    row = pd.Series(
        _gold_row(
            spot_gold_usd=spot,
            finance_source=finance_source,
            **overrides,
        )
    )
    return build_gold_dial_payload(
        row,
        ticker="NEM",
        finance_source=finance_source,
        enabled=enabled,
        disabled_reason=reason,
        scenario_enabled=scenario_enabled,
        scenario_reason=scenario_reason,
        spot_gold_usd=optional_finite_float(spot),
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

    del spot
    return "spot"


def _dial_basis_scenario(spot: float) -> str:
    return f"scenario · baseline spot {format_metric(spot, 'usd2')}/oz"


def _corporate_basis_at_rest(spot: float) -> str:
    """The one section-level gold basis shared by all six headline cards."""

    return f"Spot gold {format_metric(spot, 'usd2')}/oz as of 2026-08-11"


def _corporate_basis_scenario(
    gold: float,
    spot: float = FRACTIONAL_SPOT,
    *,
    scenario_unit: str = "usd",
) -> str:
    """Scenario price plus the exact spot context it moved from."""

    return (
        f"Scenario {format_metric(gold, scenario_unit)}/oz · baseline "
        + _corporate_basis_at_rest(spot).replace("Spot gold ", "spot ", 1)
    )


def _valuetext_at_rest(spot: float) -> str:
    """The server-rendered ``aria-valuetext`` for a live dial (corporate.py)."""

    return f"{format_metric(spot, 'usd2')} per ounce, spot"


#: The node prelude both shims share — one DOM element stub, not two that can
#: drift apart. ``doc`` is declared by each shim that follows it; ``El.focus``
#: only resolves it when a test actually focuses something.
_DOM_PRELUDE = r"""
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
"""

_SHIM = (
    _DOM_PRELUDE
    + r"""
var doc;
const timers = new Map();
let nextTimer = 1;
let reducedMotionQuery = null;

const payloadNode = new El("script");
payloadNode.textContent = __PAYLOAD__;

// The browser has ALREADY snapped the position onto the step grid by the time
// the module runs — that is the whole point of the fractional-spot cases.
// The server rendered an aria-valuetext with it, so "the module left the
// server's text alone" is provable rather than merely "wrote no attribute".
const input = new El("input", {
  "aria-valuetext": __VALUETEXT__,
  "min": __MINIMUM__,
  "step": __STEP__
});
input.value = __VALUE__;
input.disabled = true;  // the server ships an honest no-JavaScript spot control
const output = new El("output");
const reset = new El("button");
reset.disabled = true;   // the server now renders it disabled at rest
const status = new El("p");
const basis = new El("span");
basis.textContent = __BASIS__;

const spotCell = new El("td", {"data-metric": "__LINE_METRIC__", "data-basis": "spot"});
spotCell.textContent = __PENDING__;

// The scenario column exists ONLY where the server rendered one. With
// scenario_enabled False, corporate.py emits NO scenario cell, NO card scenario
// span and NO scenario header at all (_scenario_cell and _moving_table both
// return ""), and the line cell's no-JavaScript fallback becomes "Unavailable —
// see reason above" instead of the needs-JavaScript text (_spot_dial_cell).
// Building those nodes unconditionally would let assertions describe markup the
// real page cannot contain.
const scenarioCells = __SCENARIO_ENABLED__ ? [
  new El("td", {"data-metric": "__LINE_METRIC__", "data-basis": "scenario", hidden: "hidden"}),
  new El("p", {"data-metric": "__CARD_METRIC__", "data-basis": "scenario", hidden: "hidden"})
] : [];
const scenarioCell = scenarioCells[0] || null;
const cardScenario = scenarioCells[1] || null;
const scenarioHeads = __SCENARIO_ENABLED__
  ? [new El("th", {"data-scenario-head": "1", hidden: "hidden"})]
  : [];
const scenarioHead = scenarioHeads[0] || null;
const cardSpot = new El("p", {"data-headline-spot": "1"});
cardSpot.textContent = __CARD_SPOT__;

// One section-level basis replaces the six repeated per-card dates.
const corporateBasis = new El("span");
corporateBasis.textContent = __CORPORATE_BASIS__;

const section = new El("section");
section.querySelectorAll = function (selector) {
  if (selector === '[data-metric][data-basis="spot"]') { return [spotCell]; }
  if (selector === '[data-metric][data-basis="scenario"]') { return scenarioCells; }
  if (selector === "[data-scenario-head]") { return scenarioHeads; }
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
  "corporate-finance-gold-basis": corporateBasis,
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
)


def _run(
    body: str,
    *,
    payload: dict | None = None,
    value: str = FRACTIONAL_BASELINE,
    spot: float = FRACTIONAL_SPOT,
    with_payload: bool = True,
    reduced_motion: bool = False,
    valuetext: str | None = None,
    minimum: str = "2000",
    step: str = "1",
    card_metric: str = CARD_METRIC,
) -> None:
    """Run the shipped module against the shim and assert node exits clean.

    ``valuetext`` seeds the server-rendered ``aria-valuetext``; the default is
    the live-dial one, and the scenario-unavailable case passes the server's
    own "— scenario unavailable" text so it can be proven untouched.

    The fixture's markup follows the payload: ``scenario_enabled`` controls
    whether scenario nodes exist, while ``enabled`` controls whether the server
    can publish a persisted spot value. The shim never offers the module a node
    or initial value the server would not emit.
    """

    assert DIAL_JS.exists(), f"{DIAL_JS} is missing"
    resolved = _payload(spot=spot) if payload is None else payload
    scenario_enabled = bool(resolved.get("scenario_enabled"))
    script = (
        _SHIM.replace("__PAYLOAD__", json.dumps(json.dumps(resolved)))
        .replace("__SCENARIO_ENABLED__", "true" if scenario_enabled else "false")
        .replace("__PAYLOAD_NODE__", "payloadNode" if with_payload else "null")
        .replace("__VALUE__", json.dumps(value))
        .replace("__MINIMUM__", json.dumps(minimum))
        .replace("__STEP__", json.dumps(step))
        .replace(
            "__VALUETEXT__",
            json.dumps(_valuetext_at_rest(spot) if valuetext is None else valuetext),
        )
        .replace("__BASIS__", json.dumps(_basis_at_rest(spot)))
        .replace("__CORPORATE_BASIS__", json.dumps(_corporate_basis_at_rest(spot)))
        .replace(
            "__PENDING__",
            json.dumps(SERVER_SPOT_TEXT if resolved.get("enabled") else UNAVAILABLE_TEXT),
        )
        .replace("__CARD_SPOT__", json.dumps(CARD_SPOT_TEXT))
        .replace("__LINE_METRIC__", LINE_METRIC)
        .replace("__CARD_METRIC__", card_metric)
        .replace("__REDUCED__", "true" if reduced_motion else "false")
        .replace("__BODY__", body)
    )
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        cwd=Path.cwd(),
        text=True,
        # Asserted strings carry "×", "—" and "$"; the platform codepage would
        # mangle both the comparison and any failure message node prints.
        encoding="utf-8",
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


# ---------------------------------------------------------------------------
# formatter parity — EVERY unit, tie values included
# ---------------------------------------------------------------------------

#: Values chosen so the Python/JS comparison can actually fail. The first block
#: is exact decimal TIES at the places the formatters round to (0/1/2 dp): they
#: are the whole point, because ``format()`` rounds a tie to the even digit and
#: ``toFixed()`` rounds it away from zero, so ``$2.5m`` used to render "$2m" on
#: the server and "$3m" in the dial. ``0.1125`` is the pct tie (×100 = 11.25),
#: ``-0.0`` locks the sign Python keeps, and the rest are ordinary near-tie and
#: grouping values that must NOT be disturbed by half-even rounding.
_FORMAT_PROBE_VALUES: tuple[float, ...] = (
    0.5,
    2.5,
    4.5,
    -2.5,
    1234.5,
    -1234.5,
    0.1125,
    11.25,
    0.0625,
    0.0,
    -0.0,
    -0.4,
    1.005,
    2.675,
    1234.545,
    1234567.89,
    -3000.0,
    0.375,
)

#: The probe shim: the SHIPPED module, booted over one scenario cell per case, so
#: the strings compared below come out of the real ``formatMetric`` through the
#: real paint path. ``slope`` 0 makes each cell's evaluated value exactly its
#: ``intercept``, which is how a fixed value is fed to a formatter that is only
#: reachable from inside the module's closure.
_FORMAT_PROBE_SHIM = (
    _DOM_PRELUDE
    + r"""
var doc;

const CASES = __CASES__;

const payloadNode = new El("script");
payloadNode.textContent = __PAYLOAD__;

const input = new El("input", {"min": "2000", "step": "1"});
input.value = "4000";

const cells = CASES.map(function (metric) {
  return new El("td", {
    "data-metric": metric,
    "data-basis": "scenario",
    "hidden": "hidden"
  });
});

const section = new El("section");
section.querySelectorAll = function (selector) {
  if (selector === '[data-metric][data-basis="scenario"]') { return cells; }
  if (selector === "[data-scenario-head]") { return []; }
  if (selector === "[data-headline-spot]") { return []; }
  throw new Error("unexpected selector: " + selector);
};

const NODES = {
  "gold-dial-payload": payloadNode,
  "gold-dial-input": input,
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
  matchMedia(query) { return {matches: false}; },
  setTimeout(fn) { return 1; },
  clearTimeout(id) {}
};

vm.runInNewContext(
  fs.readFileSync("golden_vector/serve/static/gold-dial.js", "utf8"),
  {document: doc, window: win, console}
);

// Trigger the sanctioned scenario path. Spot cells are intentionally no longer
// a formatting probe because JavaScript must preserve their persisted content.
input.value = "4001";
input.listeners.input();

console.log(JSON.stringify(cells.map(function (cell) { return cell.textContent; })));
"""
)


def _js_metric_format_units() -> tuple[str, ...]:
    """The unit vocabulary the SHIPPED module declares, read from its one table."""

    source = DIAL_JS.read_text(encoding="utf-8")
    match = re.search(r"var METRIC_FORMATTERS = \{(.*?)\n  \};", source, re.S)
    assert match is not None, "gold-dial.js no longer declares one METRIC_FORMATTERS table"
    return tuple(re.findall(r"^\s+(\w+): function", match.group(1), re.M))


def _js_formatted(cases: list[tuple[str, str, float]], *, spot: float) -> list[str]:
    """Run the shipped module over ``(metric, unit, value)`` probes."""

    assert DIAL_JS.exists(), f"{DIAL_JS} is missing"
    payload = _payload(spot=spot)
    # The slope carries the value's SIGN, not just zero: IEEE 754 says
    # (+0) + (-0) == +0, so a plain 0.0 slope would quietly turn a -0.0 probe
    # into +0.0 before the formatter ever saw it and the signed-zero case would
    # pass by accident. copysign keeps every other value exact (±0 * g = ±0).
    payload["lines"] = {
        metric: {"slope": math.copysign(0.0, value), "intercept": value}
        for metric, _unit, value in cases
    }
    payload["formats"] = {metric: unit for metric, unit, _value in cases}
    script = _FORMAT_PROBE_SHIM.replace(
        "__CASES__", json.dumps([metric for metric, _unit, _value in cases])
    ).replace("__PAYLOAD__", json.dumps(json.dumps(payload)))
    result = subprocess.run(
        ["node", "-e", script],
        check=False,
        cwd=Path.cwd(),
        text=True,
        # The formatted strings carry "×" and "$": decoding node's stdout with
        # the platform codepage mangles them into a false mismatch.
        encoding="utf-8",
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_two_formatters_declare_the_same_unit_vocabulary():
    """A unit added on one side only is the drift this pair exists to prevent:
    an undeclared unit silently falls through to the generic 2-dp path, which
    prints a plausible-looking WRONG string instead of failing."""

    assert set(_js_metric_format_units()) == set(METRIC_UNITS)
    # And the payload's per-metric formats stay inside that shared vocabulary.
    assert set(METRIC_FORMATS.values()) <= set(METRIC_UNITS)


def test_every_unit_formats_identically_in_python_and_the_shipped_js():
    """One assertion per (unit, value) pair, ties included — the shipped module's
    real output against ``format_metric``'s, never a re-implementation of either."""

    cases: list[tuple[str, str, float]] = []
    expected: list[str] = []
    for unit_index, unit in enumerate(METRIC_UNITS):
        for value_index, value in enumerate(_FORMAT_PROBE_VALUES):
            cases.append((f"probe{unit_index}x{value_index}", unit, value))
            expected.append(format_metric(value, unit))
    produced = _js_formatted(cases, spot=FRACTIONAL_SPOT)
    assert len(produced) == len(expected)
    mismatches = [
        f"{unit} {value!r}: python={want!r} js={got!r}"
        for (_metric, unit, value), want, got in zip(cases, expected, produced)
        if want != got
    ]
    assert not mismatches, "formatter drift: " + "; ".join(mismatches)


def test_the_generic_fallback_path_also_rounds_the_python_way():
    """An unknown unit is the one path neither vocabulary covers; both sides must
    still land on the same grouped 2-dp string."""

    cases = [("probeUnknown", "not_a_unit", 0.125), ("probeUnknown2", "not_a_unit", 1234.565)]
    produced = _js_formatted(cases, spot=FRACTIONAL_SPOT)
    assert produced == [format_metric(0.125, "not_a_unit"), format_metric(1234.565, "not_a_unit")]


# ---------------------------------------------------------------------------
# state B — untouched spot (the fractional case that used to open a scenario)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("finance_source", "spot", "baseline", "scenario_gold"), SOURCE_STATE_CASES
)
def test_fractional_spot_boots_clean_with_one_value_per_card_and_no_announcement(
    finance_source: str,
    spot: float,
    baseline: str,
    scenario_gold: float,
):
    del scenario_gold  # Shared source matrix; this state remains at its baseline.
    payload = _payload(spot=spot, finance_source=finance_source)
    assert payload["finance_source"] == finance_source
    assert payload["spot_gold_usd"] == spot
    body = f"""
// Nothing was announced, and nothing was even queued to announce.
assert.equal(status.textContent, "");
flush();
assert.equal(status.textContent, "");

assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(input.disabled, false);
assert.equal(reset.disabled, true);
assert.equal(scenarioCell.hidden, true);
assert.equal(scenarioCell.textContent, "");
assert.equal(cardScenario.hidden, true);
assert.equal(scenarioHead.hidden, true);

// ONE value per card: the persisted headline stays, untouched.
assert.equal(cardSpot.hidden, false);
assert.equal(cardSpot.textContent, {json.dumps(CARD_SPOT_TEXT)});

// The control reports the EXACT spot even though its position is the snapped one.
assert.equal(input.value, {json.dumps(baseline)});
assert.equal(output.textContent, {json.dumps(format_metric(spot, "usd2"))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(spot, "usd2") + " per ounce, spot")}
);
assert.equal(basis.textContent, {json.dumps(_basis_at_rest(spot))});

// The single section-level basis is the server's own text, untouched at rest.
assert.equal(corporateBasis.textContent, {json.dumps(_corporate_basis_at_rest(spot))});

// The persisted true-spot cell survives boot byte-for-byte. The fitted line is
// deliberately non-collinear here, so client evaluation would change the value.
assert.equal(spotCell.textContent, {json.dumps(SERVER_SPOT_TEXT)});
assert.notEqual(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, spot))});
assert.equal(reducedMotionQuery, "(prefers-reduced-motion: reduce)");
"""
    _run(body, payload=payload, value=baseline, spot=spot)


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


@pytest.mark.parametrize(
    ("finance_source", "spot", "baseline", "scenario_gold"), SOURCE_STATE_CASES
)
def test_genuine_movement_activates_the_scenario_and_announces_once_debounced(
    finance_source: str,
    spot: float,
    baseline: str,
    scenario_gold: float,
):
    assert scenario_gold == 4200.0
    payload = _payload(spot=spot, finance_source=finance_source)
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
assert.equal(spotCell.textContent, {json.dumps(SERVER_SPOT_TEXT)});
assert.equal(scenarioCell.classes["is-updated"], true);

assert.equal(output.textContent, "$4,200");
assert.equal(input.attrs["aria-valuetext"], {json.dumps(_scenario_valuetext(4200, spot))});
assert.equal(
  basis.textContent,
  {json.dumps(_dial_basis_scenario(spot))}
);

// The one shared basis now states scenario and exact spot baseline.
assert.equal(
  corporateBasis.textContent,
  {json.dumps(_corporate_basis_scenario(4200.0, spot))}
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
    _run(body, payload=payload, value=baseline, spot=spot)


def test_fractional_step_keeps_the_scenario_price_exact_in_every_user_surface():
    scenario_gold = 4477.5
    scenario_text = format_metric(scenario_gold, "usd2")
    spot_text = format_metric(INTEGER_SPOT, "usd2")
    corporate_basis = _corporate_basis_scenario(
        scenario_gold,
        INTEGER_SPOT,
        scenario_unit="usd2",
    )
    body = f"""
slide("4477.5");
flush();

assert.equal(output.textContent, {json.dumps(scenario_text)});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(f"{scenario_text} per ounce, scenario · spot {spot_text} per ounce")}
);
assert.equal(
  basis.textContent,
  {json.dumps(_dial_basis_scenario(INTEGER_SPOT))}
);
assert.equal(
  status.textContent,
  {json.dumps(f"Scenario {scenario_text} per ounce. Corporate finance values updated.")}
);
assert.equal(corporateBasis.textContent, {json.dumps(corporate_basis)});
"""
    _run(
        body,
        payload=_payload(spot=INTEGER_SPOT),
        value=INTEGER_BASELINE,
        spot=INTEGER_SPOT,
        step="0.5",
    )


def test_fractional_grid_origin_keeps_scenario_price_exact_with_integer_step():
    """A fractional ``min`` makes every legal grid point fractional even when

    ``step`` itself is an integer; display precision must follow the full grid.
    """

    scenario_gold = 4478.5
    scenario_text = format_metric(scenario_gold, "usd2")
    spot_text = format_metric(FRACTIONAL_SPOT, "usd2")
    corporate_basis = _corporate_basis_scenario(
        scenario_gold,
        FRACTIONAL_SPOT,
        scenario_unit="usd2",
    )
    body = f"""
slide("4478.5");
flush();

assert.equal(output.textContent, {json.dumps(scenario_text)});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(f"{scenario_text} per ounce, scenario · spot {spot_text} per ounce")}
);
assert.equal(
  basis.textContent,
  {json.dumps(_dial_basis_scenario(FRACTIONAL_SPOT))}
);
assert.equal(
  status.textContent,
  {json.dumps(f"Scenario {scenario_text} per ounce. Corporate finance values updated.")}
);
assert.equal(corporateBasis.textContent, {json.dumps(corporate_basis)});
"""
    _run(
        body,
        payload=_payload(spot=FRACTIONAL_SPOT),
        value="4477.5",
        spot=FRACTIONAL_SPOT,
        minimum="2000.5",
        step="1",
    )


@pytest.mark.parametrize(
    ("metric", "scenario", "overrides", "expected"),
    (
        (
            "margin_pct",
            "0",
            {},
            "Not meaningful — gold price ≤ 0",
        ),
        (
            "aisc_margin_yield",
            "4200",
            {"market_cap_musd": 0.0},
            "Not meaningful — market cap ≤ 0",
        ),
        (
            "ev_ebitda",
            "2000",
            {
                "line_slope_forward_ebitda_musd": 1.0,
                "line_intercept_forward_ebitda_musd": -5000.0,
            },
            "Not meaningful — EBITDA ≤ 0",
        ),
        (
            "leverage_stressed",
            "2000",
            {
                "line_slope_forward_ebitda_musd": 1.0,
                "line_intercept_forward_ebitda_musd": -5000.0,
            },
            "Not meaningful — EBITDA ≤ 0",
        ),
        (
            "forward_pe",
            "2000",
            {
                "line_slope_forward_eps": 0.001,
                "line_intercept_forward_eps": -3.0,
            },
            "Not meaningful — EPS ≤ 0",
        ),
    ),
)
def test_invalid_scenario_ratios_render_explicit_professional_guards(
    metric: str,
    scenario: str,
    overrides: dict[str, float],
    expected: str,
):
    """Every invalid ratio names the failed denominator, never zero or blank."""

    payload = _payload(**overrides)
    body = f"""
slide({json.dumps(scenario)});
assert.equal(cardScenario.hidden, false);
assert.equal(cardScenario.textContent, {json.dumps(expected)});
assert.equal(cardScenario.attrs["data-unavailable"], "1");
assert.equal(cardSpot.hidden, true);
"""
    _run(body, payload=payload, card_metric=metric, minimum="0")


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
assert.equal(corporateBasis.textContent, {json.dumps(_corporate_basis_scenario(4200.0))});
slide({json.dumps(FRACTIONAL_BASELINE)});

// Byte-exact restoration: the server's wording is captured, never rebuilt.
assert.equal(
  corporateBasis.textContent,
  {json.dumps(_corporate_basis_at_rest(FRACTIONAL_SPOT))}
);

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
assert.equal(spotCell.textContent, {json.dumps(SERVER_SPOT_TEXT)});

// A user action DID happen, so this one is announced.
flush();
assert.equal(
  status.textContent,
  {json.dumps("Back at spot " + format_metric(FRACTIONAL_SPOT, "usd2") + " per ounce.")}
);
"""
    _run(body, payload=payload)


@pytest.mark.parametrize(
    ("finance_source", "spot", "baseline", "scenario_gold"), SOURCE_STATE_CASES
)
def test_reset_restores_the_saved_baseline_and_never_the_fractional_spot(
    finance_source: str,
    spot: float,
    baseline: str,
    scenario_gold: float,
):
    assert scenario_gold == 4200.0
    payload = _payload(spot=spot, finance_source=finance_source)
    body = f"""
slide("4200");
flush();
assert.equal(
  corporateBasis.textContent,
  {json.dumps(_corporate_basis_scenario(4200.0, spot))}
);
reset.listeners.click();

// The SAVED baseline: writing 4477.4 back would snap straight to a moved position.
assert.equal(input.value, {json.dumps(baseline)});
// Reset restores the server's card basis text byte-exact, exactly like a manual return.
assert.equal(corporateBasis.textContent, {json.dumps(_corporate_basis_at_rest(spot))});
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(scenarioCell.hidden, true);
assert.equal(cardScenario.hidden, true);
assert.equal(scenarioHead.hidden, true);
assert.equal(cardSpot.hidden, false);
assert.equal(output.textContent, {json.dumps(format_metric(spot, "usd2"))});
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(format_metric(spot, "usd2") + " per ounce, spot")}
);

// Focus leaves the control that just disabled itself.
assert.equal(input.focusCount, 1);
assert.equal(doc.activeElement, input);

flush();
assert.equal(
  status.textContent,
  {json.dumps("Reset to spot " + format_metric(spot, "usd2") + " per ounce.")}
);

// ...and the reset state is the clean state: no loop back into a scenario.
input.listeners.input();
flush();
assert.equal(section.attrs["data-scenario-active"], "0");
assert.equal(reset.disabled, true);
assert.equal(cardSpot.hidden, false);
"""
    _run(body, payload=payload, value=baseline, spot=spot)


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
assert.equal(spotCell.textContent, {json.dumps(SERVER_SPOT_TEXT)});

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
assert.equal(spotCell.textContent, {json.dumps(SERVER_SPOT_TEXT)});
assert.equal(cardSpot.hidden, false);
assert.equal(cardSpot.textContent, {json.dumps(CARD_SPOT_TEXT)});
assert.equal(scenarioCell.hidden, true);
assert.equal(status.textContent, "");
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(_valuetext_at_rest(FRACTIONAL_SPOT))}
);
assert.equal(section.attrs["data-scenario-active"], undefined);
assert.equal(input.listeners.input, undefined);
"""
    _run(body, with_payload=False)


def test_a_disabled_dial_preserves_the_server_unavailable_state():
    """ARTIFACT unavailable: JavaScript does not rewrite the server spot cell."""

    reason = "linearity residual 41.2 exceeded tolerance at $6,000"
    body = f"""
// No artifact means no scenario either, so the server emitted no scenario
// column here and the line cell shipped its "Unavailable" fallback.
assert.equal(scenarioCells.length, 0);
assert.equal(scenarioHeads.length, 0);

assert.equal(input.disabled, true);
assert.equal(reset.disabled, true);
assert.equal(spotCell.textContent, {json.dumps(UNAVAILABLE_TEXT)});
assert.equal(spotCell.attrs["data-unavailable"], undefined);
assert.equal(cardSpot.hidden, false);
assert.equal(status.textContent, "");
assert.equal(input.listeners.input, undefined);
assert.equal(input.listeners.change, undefined);
assert.equal(reset.listeners.click, undefined);
// the server's own value text and card basis lines stand untouched
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(_valuetext_at_rest(FRACTIONAL_SPOT))}
);
assert.equal(
  corporateBasis.textContent,
  {json.dumps(_corporate_basis_at_rest(FRACTIONAL_SPOT))}
);
"""
    _run(
        body,
        payload=_payload(
            enabled=False, reason=reason, scenario_enabled=False, scenario_reason=reason
        ),
    )


def test_a_spot_outside_the_range_keeps_its_true_spot_values_and_an_inert_control():
    """SCENARIO unavailable, artifact FINE (``enabled`` True,
    ``scenario_enabled`` False — spot outside the configured dial range).

    The five actual Tool-B spot values were persisted by v2, so JavaScript must
    preserve them rather than replace them with either a fitted-line value or
    the reason. The control is inert instead: no
    listeners, no scenario, no announcement, and the server's own strings stay."""

    reason = "spot gold $7,000.00 is outside the configured dial range $2,000–$6,000"
    payload = _payload(spot=7000.0, scenario_enabled=False, scenario_reason=reason)
    server_valuetext = format_metric(7000.0, "usd2") + " per ounce, spot — scenario unavailable"
    body = f"""
// The server rendered NO scenario column for this state, so there is nothing
// for the module to reveal — the absence itself is the contract.
assert.equal(scenarioCells.length, 0);
assert.equal(scenarioHeads.length, 0);

// The five line cells retain the server's persisted true-spot values — never
// the reason, never a fresh client calculation, never a blank.
assert.equal(spotCell.textContent, {json.dumps(SERVER_SPOT_TEXT)});
assert.notEqual(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, 7000.0))});
assert.notEqual(spotCell.textContent, {json.dumps(reason)});
assert.notEqual(spotCell.textContent, {json.dumps(UNAVAILABLE_TEXT)});
assert.notEqual(spotCell.textContent, "");
assert.equal(spotCell.attrs["data-unavailable"], undefined);
assert.equal(cardSpot.hidden, false);
assert.equal(cardSpot.textContent, {json.dumps(CARD_SPOT_TEXT)});

// The control is dead: disabled, unbound, nothing to reset from.
assert.equal(input.disabled, true);
assert.equal(reset.disabled, true);
assert.equal(input.listeners.input, undefined);
assert.equal(input.listeners.change, undefined);
assert.equal(reset.listeners.click, undefined);

// Dispatching an input event changes NOTHING (there is nothing bound to it).
input.value = "5900";
if (input.listeners.input) {{ input.listeners.input(); }}
if (input.listeners.change) {{ input.listeners.change(); }}
flush();
assert.equal(section.attrs["data-scenario-active"], undefined);
assert.equal(cardSpot.hidden, false);

// Nothing announced, and the server's aria-valuetext + card basis lines stand.
assert.equal(status.textContent, "");
assert.equal(input.attrs["aria-valuetext"], {json.dumps(server_valuetext)});
assert.equal(corporateBasis.textContent, {json.dumps(_corporate_basis_at_rest(7000.0))});
"""
    _run(
        body,
        payload=payload,
        value="6000",
        spot=7000.0,
        valuetext=server_valuetext,
    )
