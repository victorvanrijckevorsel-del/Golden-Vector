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
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.common.numeric import optional_finite_float
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

SOURCE_STATE_CASES = (
    pytest.param("our", FRACTIONAL_SPOT, FRACTIONAL_BASELINE, 4200.0, id="our-view"),
    pytest.param("yahoo", 4321.6, "4322", 4200.0, id="yahoo"),
)

#: One line metric (client-evaluated at spot) and one card metric.
LINE_METRIC = "forward_revenue_musd"
CARD_METRIC = "ev_ebitda"

#: The server's no-JavaScript fallback for a line-metric spot cell.
PENDING_TEXT = "needs the gold dial (JavaScript)"
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

    return f"spot {format_metric(spot, 'usd2')} as of 2026-08-11"


def _card_basis_at_rest(spot: float) -> str:
    """The server-rendered ``.metric-card-basis`` text (``_headline_cards``'s
    ``spot_label``) — the line that would otherwise still say "spot" under a
    scenario-only number."""

    return f"fwd @ spot {format_metric(spot, 'usd')}/oz as of 2026-08-11"


def _card_basis_scenario(gold: float, spot: float = FRACTIONAL_SPOT) -> str:
    """What that same line must say while a scenario is active: the scenario
    price the number was evaluated at, plus the baseline it moved from."""

    return (
        f"fwd @ scenario {format_metric(gold, 'usd')}/oz · baseline "
        + _card_basis_at_rest(spot).removeprefix("fwd @ ")
    )


def _valuetext_at_rest(spot: float) -> str:
    """The server-rendered ``aria-valuetext`` for a live dial (corporate.py)."""

    return f"{format_metric(spot, 'usd2')} per ounce, spot"


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
// The server rendered an aria-valuetext with it, so "the module left the
// server's text alone" is provable rather than merely "wrote no attribute".
const input = new El("input", {
  "aria-valuetext": __VALUETEXT__,
  "min": __MINIMUM__,
  "step": __STEP__
});
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

// All SIX headline cards, each with the basis line the server writes under its
// number ("fwd @ spot $4,477/oz as of 2026-08-11"). Every one of them must move
// to the scenario price while a scenario is active, and back afterwards.
const cardBases = [];
const cards = [];
for (let cardIndex = 0; cardIndex < 6; cardIndex += 1) {
  const cardBasis = new El("p", {"class": "hint metric-card-basis"});
  cardBasis.textContent = __CARD_BASIS__;
  const card = new El("div", {"data-metric-card": "metric" + cardIndex});
  card.querySelector = function (selector) {
    if (selector === ".metric-card-basis") { return cardBasis; }
    throw new Error("unexpected selector: " + selector);
  };
  cardBases.push(cardBasis);
  cards.push(card);
}

const section = new El("section");
section.querySelectorAll = function (selector) {
  if (selector === '[data-metric][data-basis="spot"]') { return [spotCell]; }
  if (selector === '[data-metric][data-basis="scenario"]') { return [scenarioCell, cardScenario]; }
  if (selector === "[data-scenario-head]") { return [scenarioHead]; }
  if (selector === "[data-headline-spot]") { return [cardSpot]; }
  if (selector === "[data-metric-card]") { return cards; }
  // An unmodelled selector must fail loudly rather than silently return nothing.
  throw new Error("unexpected selector: " + selector);
};

function cardBasisTexts() { return cardBases.map(function (node) { return node.textContent; }); }

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
    valuetext: str | None = None,
    minimum: str = "2000",
    step: str = "1",
) -> None:
    """Run the shipped module against the shim and assert node exits clean.

    ``valuetext`` seeds the server-rendered ``aria-valuetext``; the default is
    the live-dial one, and the scenario-unavailable case passes the server's
    own "— scenario unavailable" text so it can be proven untouched.
    """

    assert DIAL_JS.exists(), f"{DIAL_JS} is missing"
    resolved = _payload(spot=spot) if payload is None else payload
    script = (
        _SHIM.replace("__PAYLOAD__", json.dumps(json.dumps(resolved)))
        .replace("__PAYLOAD_NODE__", "payloadNode" if with_payload else "null")
        .replace("__VALUE__", json.dumps(value))
        .replace("__MINIMUM__", json.dumps(minimum))
        .replace("__STEP__", json.dumps(step))
        .replace(
            "__VALUETEXT__",
            json.dumps(_valuetext_at_rest(spot) if valuetext is None else valuetext),
        )
        .replace("__BASIS__", json.dumps(_basis_at_rest(spot)))
        .replace("__CARD_BASIS__", json.dumps(_card_basis_at_rest(spot)))
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

// Every card's basis line is the server's own text, untouched at rest.
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(_card_basis_at_rest(spot))});
}});

// The line-metric spot cell is evaluated at exact spot, not at the snapped position.
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, spot))});
assert.notEqual(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, float(baseline)))});
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
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, spot))});
assert.equal(scenarioCell.classes["is-updated"], true);

assert.equal(output.textContent, "$4,200");
assert.equal(input.attrs["aria-valuetext"], {json.dumps(_scenario_valuetext(4200, spot))});
assert.equal(
  basis.textContent,
  {json.dumps("scenario $4,200 · baseline " + _basis_at_rest(spot))}
);

// ALL SIX card basis lines now say scenario — a card must never print a
// scenario-only number under "fwd @ spot ...".
assert.equal(cardBases.length, 6);
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(_card_basis_scenario(4200.0, spot))});
}});
assert.ok(!cardBasisTexts().some(function (text) {{ return text.indexOf("fwd @ spot") === 0; }}));

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
    rest_basis = _basis_at_rest(INTEGER_SPOT)
    card_basis = (
        f"fwd @ scenario {scenario_text}/oz · baseline "
        + _card_basis_at_rest(INTEGER_SPOT).removeprefix("fwd @ ")
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
  {json.dumps(f"scenario {scenario_text} · baseline {rest_basis}")}
);
assert.equal(
  status.textContent,
  {json.dumps(f"Scenario {scenario_text} per ounce. Corporate finance values updated.")}
);
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(card_basis)});
}});
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
    rest_basis = _basis_at_rest(FRACTIONAL_SPOT)
    card_basis = (
        f"fwd @ scenario {scenario_text}/oz · baseline "
        + _card_basis_at_rest(FRACTIONAL_SPOT).removeprefix("fwd @ ")
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
  {json.dumps(f"scenario {scenario_text} · baseline {rest_basis}")}
);
assert.equal(
  status.textContent,
  {json.dumps(f"Scenario {scenario_text} per ounce. Corporate finance values updated.")}
);
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(card_basis)});
}});
"""
    _run(
        body,
        payload=_payload(spot=FRACTIONAL_SPOT),
        value="4477.5",
        spot=FRACTIONAL_SPOT,
        minimum="2000.5",
        step="1",
    )


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
assert.equal(cardBasisTexts()[0], {json.dumps(_card_basis_scenario(4200.0))});
slide({json.dumps(FRACTIONAL_BASELINE)});

// Byte-exact restoration: the server's wording is captured, never rebuilt.
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(_card_basis_at_rest(FRACTIONAL_SPOT))});
}});

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
assert.equal(cardBasisTexts()[0], {json.dumps(_card_basis_scenario(4200.0, spot))});
reset.listeners.click();

// The SAVED baseline: writing 4477.4 back would snap straight to a moved position.
assert.equal(input.value, {json.dumps(baseline)});
// Reset restores the server's card basis text byte-exact, exactly like a manual return.
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(_card_basis_at_rest(spot))});
}});
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
assert.equal(
  input.attrs["aria-valuetext"],
  {json.dumps(_valuetext_at_rest(FRACTIONAL_SPOT))}
);
assert.equal(section.attrs["data-scenario-active"], undefined);
assert.equal(input.listeners.input, undefined);
"""
    _run(body, with_payload=False)


def test_a_disabled_dial_replaces_the_no_javascript_fallback_with_the_reason():
    """ARTIFACT unavailable (``enabled`` False): no price can be evaluated at
    all, so the no-JavaScript fallback becomes the real reason rather than a
    blank or a lie about needing JavaScript."""

    reason = "linearity residual 41.2 exceeded tolerance at $6,000"
    body = f"""
assert.equal(input.disabled, true);
assert.equal(reset.disabled, true);
assert.equal(spotCell.textContent, {json.dumps(reason)});
assert.equal(spotCell.attrs["data-unavailable"], "1");
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
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(_card_basis_at_rest(FRACTIONAL_SPOT))});
}});
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

    The published lines were verified at true spot, so the five line cells must
    show their evaluated values; overwriting them with the reason would destroy
    five numbers the artifact stands behind. The control is inert instead: no
    listeners, no scenario, no announcement, and the server's own strings stay."""

    reason = (
        "spot gold $7,000.00 is outside the configured dial range $2,000–$6,000"
    )
    payload = _payload(spot=7000.0, scenario_enabled=False, scenario_reason=reason)
    server_valuetext = format_metric(7000.0, "usd2") + " per ounce, spot — scenario unavailable"
    body = f"""
// The five line cells carry EVALUATED values at true spot — never the reason,
// never the no-JavaScript fallback, never a blank.
assert.equal(spotCell.textContent, {json.dumps(_expected(payload, LINE_METRIC, 7000.0))});
assert.notEqual(spotCell.textContent, {json.dumps(reason)});
assert.notEqual(spotCell.textContent, {json.dumps(PENDING_TEXT)});
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
assert.equal(scenarioCell.hidden, true);
assert.equal(scenarioCell.textContent, "");
assert.equal(cardScenario.hidden, true);
assert.equal(scenarioHead.hidden, true);
assert.equal(cardSpot.hidden, false);

// Nothing announced, and the server's aria-valuetext + card basis lines stand.
assert.equal(status.textContent, "");
assert.equal(input.attrs["aria-valuetext"], {json.dumps(server_valuetext)});
cardBasisTexts().forEach(function (text) {{
  assert.equal(text, {json.dumps(_card_basis_at_rest(7000.0))});
}});
"""
    _run(
        body,
        payload=payload,
        value="6000",
        spot=7000.0,
        valuetext=server_valuetext,
    )
