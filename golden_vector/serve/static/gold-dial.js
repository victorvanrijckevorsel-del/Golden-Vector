/* gold-dial.js — the gold scenario dial for the ticker page.
 *
 * This is ONE of the three first-party modules covered by the client-side
 * interactivity exception (plan reviews/codex/claude_ticker_page_plan.md §3.1,
 * requirements addendum D-1). Rules it lives by:
 *
 *   - Inputs are ONLY backend-resolved values embedded in the page by
 *     serve/embed.py. No fetches, no state shared with other modules.
 *   - The line formula exists once, here, mirroring model/gold_lines.py:
 *         value(g) = slope * g + intercept
 *   - The ratio guards mirror screening/layer1.py and screening/layer2.py
 *     EXACTLY: forward EBITDA > 0 for EV/EBITDA and stressed leverage,
 *     forward EPS > 0 for forward P/E, market cap > 0 for the AISC margin
 *     yield. An unguarded ratio renders its short reason, never a blank cell.
 *   - formatMetric() below is the SHARED CLIENT FORMATTER for this page: the
 *     later score-builder and option-sizing modules reuse it rather than
 *     forking a second one. It mirrors format_metric() in
 *     serve/ticker_page/corporate.py character for character.
 *   - The module no-ops when its markup is absent (plan §9.5).
 *   - The payload carries TWO availability flags and they are not the same
 *     thing: `enabled` false means no artifact exists, so no price can be
 *     evaluated and the line cells show the reason; `scenario_enabled` false
 *     with `enabled` true means the published values are good AT SPOT but the
 *     slider must not move, so the spot cells are painted and the control is
 *     left inert (redesign plan §4.3 State A).
 *   - The clean state is the browser-normalized slider position captured at
 *     boot — never the exact fractional spot, which a stepped control cannot
 *     hold. No scenario, and no live-region announcement, without a genuine
 *     user event (redesign plan §4.3).
 *
 * The dial moves the Corporate finance section ONLY. Performance, market
 * behaviour, the failing-check sentences and every score stay at spot.
 */
(function () {
  "use strict";

  var PAYLOAD_ID = "gold-dial-payload";
  var INPUT_ID = "gold-dial-input";
  var OUTPUT_ID = "gold-dial-output";
  var RESET_ID = "gold-dial-reset";
  var STATUS_ID = "gold-dial-status";
  var BASIS_ID = "gold-dial-basis";
  var CORPORATE_BASIS_ID = "corporate-finance-gold-basis";
  var SECTION_ID = "corporate-finance";

  var ANNOUNCE_DELAY_MS = 300;

  /* Which persisted constant the cash margin is measured against. Basis-driven
   * selection, never a default: an unrecognised basis makes margin unavailable
   * with a reason rather than guessing AISC. */
  var MARGIN_COST_COLUMN = {
    aisc: "aisc_usd_per_oz",
    cash_cost: "cash_cost_usd_per_oz"
  };

  /* ---------------------------------------------------------------- values */

  function ok(value) {
    if (typeof value !== "number" || !isFinite(value)) {
      return { value: null, reason: "not a finite number here" };
    }
    return { value: value, reason: null };
  }

  function miss(reason) {
    return { value: null, reason: reason };
  }

  function constant(payload, name) {
    var constants = payload.constants || {};
    var raw = constants[name];
    if (raw === null || raw === undefined) {
      return null;
    }
    return raw;
  }

  function lineValue(payload, metric, gold) {
    var lines = payload.lines || {};
    var line = lines[metric];
    if (!line || line.slope === null || line.slope === undefined) {
      return miss("no published line here");
    }
    if (line.intercept === null || line.intercept === undefined) {
      return miss("no published line here");
    }
    return ok(line.slope * gold + line.intercept);
  }

  function ratio(numerator, denominator, guardReason) {
    if (numerator === null || numerator === undefined) {
      return miss("input unavailable here");
    }
    if (denominator === null || denominator === undefined) {
      return miss("input unavailable here");
    }
    if (!(denominator > 0)) {
      return miss(guardReason);
    }
    return ok(numerator / denominator);
  }

  /* Every metric the page can show, evaluated at one gold price. */
  function evaluate(payload, metric, gold) {
    if (payload.lines && Object.prototype.hasOwnProperty.call(payload.lines, metric)) {
      return lineValue(payload, metric, gold);
    }
    if (metric === "margin_usd_per_oz") {
      var column = MARGIN_COST_COLUMN[payload.margin_basis];
      if (!column) {
        return miss("margin cost basis unavailable");
      }
      var cost = constant(payload, column);
      if (cost === null) {
        return miss("cost basis unavailable here");
      }
      return ok(gold - cost);
    }
    if (metric === "margin_pct") {
      var margin = evaluate(payload, "margin_usd_per_oz", gold);
      if (margin.value === null) {
        return margin;
      }
      /* layer1.py: margin_pct needs gold_price_assumption > 0. */
      return ratio(margin.value, gold, "Not meaningful — gold price ≤ 0");
    }
    if (metric === "aisc_margin_yield") {
      /* layer1.py: market_cap_musd must be strictly positive. */
      var aiscMargin = evaluate(payload, "aisc_margin_est_musd", gold);
      if (aiscMargin.value === null) {
        return aiscMargin;
      }
      return ratio(
        aiscMargin.value,
        constant(payload, "market_cap_musd"),
        "Not meaningful — market cap ≤ 0"
      );
    }
    if (metric === "ev_ebitda") {
      /* layer2.py: forward EBITDA must be strictly positive. */
      var ebitda = evaluate(payload, "forward_ebitda_musd", gold);
      if (ebitda.value === null) {
        return ebitda;
      }
      return ratio(
        constant(payload, "enterprise_value_musd"),
        ebitda.value,
        "Not meaningful — EBITDA ≤ 0"
      );
    }
    if (metric === "forward_pe") {
      /* layer2.py: forward EPS must be strictly positive. */
      var eps = evaluate(payload, "forward_eps", gold);
      if (eps.value === null) {
        return eps;
      }
      return ratio(
        constant(payload, "share_price_usd"),
        eps.value,
        "Not meaningful — EPS ≤ 0"
      );
    }
    if (metric === "leverage_stressed") {
      /* Tool D's leverage_stressed_at_g: net debt over FORWARD EBITDA. */
      var stressedEbitda = evaluate(payload, "forward_ebitda_musd", gold);
      if (stressedEbitda.value === null) {
        return stressedEbitda;
      }
      return ratio(
        constant(payload, "net_debt_musd"),
        stressedEbitda.value,
        "Not meaningful — EBITDA ≤ 0"
      );
    }
    return miss("unknown metric");
  }

  /* ------------------------------------------------------------ formatting */

  function groupDigits(text) {
    var parts = String(text).split(".");
    var whole = parts[0];
    var negative = whole.charAt(0) === "-";
    var digits = negative ? whole.slice(1) : whole;
    var chunks = [];
    while (digits.length > 3) {
      chunks.unshift(digits.slice(-3));
      digits = digits.slice(0, -3);
    }
    chunks.unshift(digits);
    var out = (negative ? "-" : "") + chunks.join(",");
    return parts.length > 1 ? out + "." + parts[1] : out;
  }

  /* Minus sign OUTSIDE the currency symbol ("-$3,000m"). Mirrors _currency()
   * in serve/ticker_page/corporate.py. */
  function currency(magnitude, suffix) {
    var tail = suffix || "";
    if (magnitude.charAt(0) === "-") {
      return "-$" + magnitude.slice(1) + tail;
    }
    return "$" + magnitude + tail;
  }

  /* Add one to a plain digit string, growing it when it is all nines. */
  function incrementDigits(text) {
    var out = text.split("");
    var index = out.length - 1;
    while (index >= 0 && out[index] === "9") {
      out[index] = "0";
      index -= 1;
    }
    if (index < 0) {
      out.unshift("1");
    } else {
      out[index] = String(Number(out[index]) + 1);
    }
    return out.join("");
  }

  /* Python's format() rounds a decimal TIE to the even digit ("banker's
   * rounding"); JavaScript's toFixed() rounds ties away from zero. Ties are
   * reachable on real metric values ($2.5m, an 11.25% margin), so a mirror of
   * format_metric() has to mirror its ROUNDING too — otherwise the same
   * published number reads "$2m" in the server-rendered spot cell and "$3m" in
   * the dial's scenario cell.
   *
   * toFixed() is correctly rounded, so asking it for `digits + 20` places
   * reproduces the double's exact decimal expansion wherever a tie is even
   * possible: a tie at N places needs an expansion that terminates at N+1
   * places, which is a handful of digits, never twenty. Python keeps the sign
   * on a negative zero ("-0"), so this does too.
   */
  function toFixedHalfEven(value, digits) {
    if (!isFinite(value) || Math.abs(value) >= 1e15) {
      return value.toFixed(digits);
    }
    var negative = value < 0 || (value === 0 && 1 / value < 0);
    var parts = Math.abs(value).toFixed(Math.min(100, digits + 20)).split(".");
    var fraction = parts[1] || "";
    while (fraction.length < digits + 1) {
      fraction += "0";
    }
    var combined = parts[0] + fraction.slice(0, digits);
    var rest = fraction.slice(digits);
    var lead = rest.charAt(0);
    var roundUp = lead > "5";
    if (lead === "5") {
      roundUp =
        /[1-9]/.test(rest.slice(1)) ||
        Number(combined.charAt(combined.length - 1)) % 2 === 1;
    }
    if (roundUp) {
      combined = incrementDigits(combined);
    }
    var cut = combined.length - digits;
    var magnitude = combined.slice(0, cut) || "0";
    if (digits > 0) {
      magnitude += "." + combined.slice(cut);
    }
    return (negative ? "-" : "") + magnitude;
  }

  /* unit -> formatter. The KEY SET is the shared unit vocabulary: format_metric()
   * in serve/ticker_page/corporate.py holds exactly the same keys with exactly
   * the same bodies, and tests/test_gold_dial_js_behavior.py asserts both the
   * identical key sets and identical output per unit (tie values included). */
  var METRIC_FORMATTERS = {
    musd: function (value) { return currency(groupDigits(toFixedHalfEven(value, 0)), "m"); },
    usd2: function (value) { return currency(groupDigits(toFixedHalfEven(value, 2))); },
    usd_per_oz: function (value) { return currency(groupDigits(toFixedHalfEven(value, 0)), "/oz"); },
    usd: function (value) { return currency(groupDigits(toFixedHalfEven(value, 0))); },
    pct: function (value) { return toFixedHalfEven(value * 100, 1) + "%"; },
    ratio: function (value) { return toFixedHalfEven(value, 2) + "×"; },
    years: function (value) { return toFixedHalfEven(value, 1) + " years"; },
    oz: function (value) { return groupDigits(toFixedHalfEven(value, 0)) + " oz"; },
    days: function (value) { return toFixedHalfEven(value, 0) + " days"; },
    percentile: function (value) { return groupDigits(toFixedHalfEven(value, 0)); }
  };

  function formatMetric(value, unit) {
    if (value === null || value === undefined || !isFinite(value)) {
      return "n/a";
    }
    if (!Object.prototype.hasOwnProperty.call(METRIC_FORMATTERS, unit)) {
      return groupDigits(toFixedHalfEven(value, 2));
    }
    return METRIC_FORMATTERS[unit](value);
  }

  /* -------------------------------------------------------------- painting */

  function readPayload() {
    var node = document.getElementById(PAYLOAD_ID);
    if (!node) {
      return null;
    }
    try {
      return JSON.parse(node.textContent || "null");
    } catch (error) {
      return null;
    }
  }

  function writeCell(cell, payload, metric, gold, reducedMotion) {
    var result = evaluate(payload, metric, gold);
    var unit = (payload.formats || {})[metric] || "";
    cell.textContent =
      result.value === null ? result.reason || "unavailable" : formatMetric(result.value, unit);
    if (result.value === null) {
      cell.setAttribute("data-unavailable", "1");
    } else {
      cell.removeAttribute("data-unavailable");
    }
    if (!reducedMotion) {
      cell.classList.remove("is-updated");
      /* Force a reflow so the class re-applies on every move. */
      void cell.offsetWidth;
      cell.classList.add("is-updated");
    }
  }

  function boot() {
    var payload = readPayload();
    var input = document.getElementById(INPUT_ID);
    var section = document.getElementById(SECTION_ID);
    if (!payload || !input || !section) {
      return; /* markup absent — no-op (plan §9.5) */
    }

    var output = document.getElementById(OUTPUT_ID);
    var reset = document.getElementById(RESET_ID);
    var status = document.getElementById(STATUS_ID);
    var spot = typeof payload.spot_gold_usd === "number" ? payload.spot_gold_usd : null;

    if (payload.enabled !== true || spot === null) {
      input.disabled = true;
      if (reset) {
        reset.disabled = true;
      }
      /* The dial is off for this ticker, so the line cells can never be filled.
       * Replace the server's no-JavaScript fallback with the REASON — telling a
       * user with working JavaScript that they need JavaScript is a lie, and a
       * blank cell hides the degraded state entirely. */
      var pending = section.querySelectorAll('[data-metric][data-basis="spot"]');
      var reason = payload.disabled_reason || "not published for this ticker";
      for (var pendingIndex = 0; pendingIndex < pending.length; pendingIndex += 1) {
        pending[pendingIndex].textContent = reason;
        pending[pendingIndex].setAttribute("data-unavailable", "1");
      }
      return;
    }

    var reducedMotion =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    var spotCells = section.querySelectorAll('[data-metric][data-basis="spot"]');
    var scenarioCells = section.querySelectorAll('[data-metric][data-basis="scenario"]');
    var scenarioHeads = section.querySelectorAll("[data-scenario-head]");
    /* The single headline value per card, hidden while a scenario is shown so a
     * card never stacks two unlabelled numbers (plan §4.4). */
    var headlineSpotCells = section.querySelectorAll("[data-headline-spot]");
    var basis = document.getElementById(BASIS_ID);
    var corporateBasis = document.getElementById(CORPORATE_BASIS_ID);
    var announceTimer = null;

    /* State B (plan §4.3). A range control snaps its value onto its own step
     * grid before this line runs, so the CLEAN STATE is that browser-normalized
     * position — never payload.spot_gold_usd, which is the exact fractional
     * spot a step-1 control cannot hold. Comparing against exact spot is what
     * made the page open in a scenario nobody asked for. */
    var baselineText = String(input.value);
    var baselineGold = Number(baselineText);
    if (!isFinite(baselineGold)) {
      baselineGold = spot;
      baselineText = String(spot);
    }

    /* The exact spot, cents included: the slider position rounds, the reported
     * price does not. Spot cells are still evaluated at `spot` itself. */
    var spotText = formatMetric(spot, "usd2");
    var basisAtRest = basis ? basis.textContent : "";
    var corporateBasisAtRest = corporateBasis ? corporateBasis.textContent : "";
    var configuredStep = Number(input.getAttribute("step"));
    var configuredMinimum = Number(input.getAttribute("min"));
    var scenarioPriceUnit =
      (isFinite(configuredStep) && configuredStep % 1 !== 0) ||
      (isFinite(configuredMinimum) && configuredMinimum % 1 !== 0)
        ? "usd2"
        : "usd";

    function formatScenarioPrice(gold) {
      return formatMetric(gold, scenarioPriceUnit);
    }

    /* Set ONLY inside the input/change/reset handlers. Nothing this module does
     * at boot may look like a user action: no announcement, no scenario. */
    var userActed = false;
    var scenarioActive = false;

    function setHidden(node, hidden) {
      if (hidden) {
        node.setAttribute("hidden", "hidden");
        node.style.display = "none";
      } else {
        node.removeAttribute("hidden");
        node.style.display = "";
      }
    }

    function currentGold() {
      var gold = Number(input.value);
      return isFinite(gold) ? gold : baselineGold;
    }

    /* "Moved" is measured against the baseline the control actually holds, so a
     * value the browser rounded on load is still the clean state. */
    function isMoved() {
      return currentGold() !== baselineGold;
    }

    function announce(message) {
      if (!status || !userActed) {
        return;
      }
      if (announceTimer !== null) {
        window.clearTimeout(announceTimer);
      }
      announceTimer = window.setTimeout(function () {
        status.textContent = message;
      }, ANNOUNCE_DELAY_MS);
    }

    /* Spot cells never move: they are evaluated once, at exact spot. */
    function paintSpotCells() {
      for (var index = 0; index < spotCells.length; index += 1) {
        writeCell(
          spotCells[index],
          payload,
          spotCells[index].getAttribute("data-metric"),
          spot,
          true
        );
      }
    }

    function render(moved, gold) {
      var index;
      for (index = 0; index < headlineSpotCells.length; index += 1) {
        setHidden(headlineSpotCells[index], moved);
      }
      for (index = 0; index < scenarioCells.length; index += 1) {
        setHidden(scenarioCells[index], !moved);
        if (moved) {
          writeCell(
            scenarioCells[index],
            payload,
            scenarioCells[index].getAttribute("data-metric"),
            gold,
            reducedMotion
          );
        } else {
          scenarioCells[index].textContent = "";
          scenarioCells[index].removeAttribute("data-unavailable");
        }
      }
      for (index = 0; index < scenarioHeads.length; index += 1) {
        setHidden(scenarioHeads[index], !moved);
      }
      section.setAttribute("data-scenario-active", moved ? "1" : "0");
      if (output) {
        output.textContent = moved ? formatScenarioPrice(gold) : spotText;
      }
      if (basis) {
        basis.textContent = moved
          ? "scenario · baseline spot " + spotText + "/oz"
          : basisAtRest;
      }
      if (corporateBasis) {
        corporateBasis.textContent = moved
          ? "Scenario " +
            formatScenarioPrice(gold) +
            "/oz · baseline " +
            corporateBasisAtRest.replace(/^Spot gold /, "spot ")
          : corporateBasisAtRest;
      }
      input.setAttribute(
        "aria-valuetext",
        moved
          ? formatScenarioPrice(gold) +
              " per ounce, scenario · spot " +
              spotText +
              " per ounce"
          : spotText + " per ounce, spot"
      );
      if (reset) {
        /* Nothing to reset FROM at the baseline, and disabled keeps it out of
         * the tab order without removing it from the layout. */
        reset.disabled = !moved;
      }
      scenarioActive = moved;
    }

    function onUserInput() {
      userActed = true;
      var moved = isMoved();
      if (!moved && !scenarioActive) {
        /* An event that lands back on the untouched baseline changed nothing —
         * repainting it would announce a state the user never left. */
        return;
      }
      var gold = currentGold();
      render(moved, gold);
      announce(
        moved
          ? "Scenario " +
              formatScenarioPrice(gold) +
              " per ounce. Corporate finance values updated."
          : "Back at spot " + spotText + " per ounce."
      );
    }

    /* Artifact fine, scenario withheld (plan §4.3 State A — spot outside the
     * configured dial range). The published lines were verified AT TRUE SPOT,
     * so the five line cells are evaluated and shown: blanking five trustworthy
     * values because the slider cannot reach their price would destroy data the
     * artifact stands behind. The control itself is inert — no listeners, no
     * announcement, and the server's own aria-valuetext (which already says
     * "scenario unavailable") is left exactly as rendered. */
    if (payload.scenario_enabled !== true) {
      paintSpotCells();
      input.disabled = true;
      if (reset) {
        reset.disabled = true;
      }
      return;
    }

    input.addEventListener("input", onUserInput);
    input.addEventListener("change", onUserInput);
    if (reset) {
      reset.addEventListener("click", function () {
        userActed = true;
        /* The SAVED baseline, never the fractional exact spot: writing 4477.4
         * into a step-1 control snaps it straight back to a "moved" position. */
        input.value = baselineText;
        render(false, baselineGold);
        announce("Reset to spot " + spotText + " per ounce.");
        /* Reset just disabled itself — move focus before it is unreachable. */
        input.focus();
      });
    }

    /* Progressive enhancement: the server intentionally ships the range
     * disabled because without this module it cannot update any values. Only a
     * validated, scenario-capable payload reaches this line, and all listeners
     * are attached before the control becomes interactive. */
    input.disabled = false;

    paintSpotCells();
    render(false, baselineGold); /* boot: clean state, and nothing announced */
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
