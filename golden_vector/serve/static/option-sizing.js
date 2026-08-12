// "Work out a position" — the option sizing tool on the ticker page.
//
// This is 1 of the exactly 3 sanctioned client-side modules (plan §3.1). The
// contract fields (strike, ask, multiplier, and the backend's verdict on
// whether the quote is usable at all) arrive resolved in one embedded JSON
// payload. The only arithmetic here is the intrinsic-value ladder the plan
// pins in §9.4: whole contracts from a budget, break-even, and value at
// expiry. Nothing is fetched, nothing is inferred from a beta, and a bad quote
// is never repaired with a mid price.
//
// PARITY LOCK — every rule below is mirrored in Python and machine-checked:
//   fixture : tests/fixtures/option_sizing_parity.json
//   mirror  : tests/test_ticker_page_js_parity.py  (mirror_sizing,
//             mirror_price_band, mirror_ladder)
// The pytest run drives THIS file through node when node is on PATH, so the
// two implementations cannot drift silently.
//
// DOM contract (server-rendered; every piece is optional — a missing piece
// degrades, it never throws):
//   script#option-sizing-payload[type="application/json"]  the payload
//   #option-sizing                                         root container
//     select[data-role="contract"]        option value = contract id
//     input[data-role="budget"]           money input
//     input[type="range"][data-role="price"] share-price slider
//     [data-role="price-out"]             <output> for the slider
//     [data-role="reset"]                 reset button
//     [data-role="result"]                result region
//       [data-role="contracts-line"]      the headline sentence
//       [data-role="ladder"]              <table> (JS owns <tbody>)
//       [data-role="footnote"]            intrinsic-only caveat (optional)
//       [data-role="live"]                the ONE polite live region
(function (global) {
  "use strict";

  var PAYLOAD_ID = "option-sizing-payload";
  var ROOT_ID = "option-sizing";
  var EPS = 1e-9;
  var LIVE_DEBOUNCE_MS = 300;
  var LADDER_OFFSETS = [-0.3, -0.2, -0.1, 0.1, 0.2, 0.3];
  var FOOTNOTE =
    "Value at expiry is intrinsic value only — no time value is assumed, " +
    "so selling before expiry would normally be worth more than these rows show.";

  // ---------------------------------------------------------------- numbers --

  // Half away from zero — not Math.round (which rounds -2.5 up) and not
  // Python's banker's round(). One rule, both languages, pinned by the fixture.
  function roundHalfUp(value) {
    if (!isFinite(value)) return 0;
    return value >= 0 ? Math.floor(value + 0.5) : -Math.floor(-value + 0.5);
  }

  function roundTo(value, decimals) {
    if (!isFinite(value)) return value;
    var factor = Math.pow(10, decimals);
    return roundHalfUp(value * factor) / factor;
  }

  function numberOr(value, fallback) {
    var num = typeof value === "number" ? value : parseFloat(value);
    return isFinite(num) ? num : fallback;
  }

  // The one number formatter: thousands-separated, fixed decimals, a plain
  // ASCII "-" for negatives (never U+2212) so client and server strings match.
  function formatNumber(value, decimals) {
    var places = typeof decimals === "number" && decimals > 0 ? Math.floor(decimals) : 0;
    var num = typeof value === "number" ? value : parseFloat(value);
    if (num === null || num === undefined || !isFinite(num)) return "n/a";
    var negative = num < 0;
    var scaled = roundHalfUp(Math.abs(num) * Math.pow(10, places));
    var digits = String(scaled);
    while (digits.length <= places) digits = "0" + digits;
    var whole = places > 0 ? digits.slice(0, digits.length - places) : digits;
    var frac = places > 0 ? digits.slice(digits.length - places) : "";
    var out = "";
    for (var i = 0; i < whole.length; i += 1) {
      if (i > 0 && (whole.length - i) % 3 === 0) out += ",";
      out += whole.charAt(i);
    }
    if (places > 0) out += "." + frac;
    return (negative && scaled !== 0 ? "-" : "") + out;
  }

  function formatMoney(value, currency, decimals) {
    if (value === null || value === undefined || !isFinite(value)) return "n/a";
    var places = typeof decimals === "number" ? decimals : 2;
    var body = formatNumber(Math.abs(value), places);
    var sign = value < 0 && body !== formatNumber(0, places) ? "-" : "";
    var code = currency || "USD";
    return code === "USD" ? sign + "$" + body : sign + code + " " + body;
  }

  // ------------------------------------------------------------- the model --

  // THE share-price slider band — the single source for the plan's
  // "$0.05 / $0.5 / $1 bands". Step comes from the quoted price's magnitude:
  //     price <  $10  ->  $0.05
  //     $10 to < $100 ->  $0.50
  //     price >= $100 ->  $1
  // The band covers at least the plan's +/-60%, widened to a whole number of
  // steps, and is anchored ON the current price so the slider's default really
  // is the current price rather than the nearest round number to it.
  function priceBand(currentPrice) {
    var raw = numberOr(currentPrice, 0);
    if (!isFinite(raw) || raw <= 0) return null;
    var step = raw < 10 ? 0.05 : raw < 100 ? 0.5 : 1;
    var decimals = step < 1 ? 2 : 0;
    var price = roundTo(raw, decimals);
    if (price <= 0) return null;
    var steps = Math.ceil((price * 0.6) / step - EPS);
    if (steps < 1) steps = 1;
    var low = roundTo(price - steps * step, decimals);
    while (low <= 0 && steps > 1) {
      steps -= 1;
      low = roundTo(price - steps * step, decimals);
    }
    if (low <= 0) low = price; // degenerate: the price is at or below one step
    return {
      min: low,
      max: roundTo(price + steps * step, decimals),
      step: step,
      decimals: decimals,
      default: price
    };
  }

  function contractList(payload) {
    return payload && payload.contracts && payload.contracts.length ? payload.contracts : [];
  }

  function findContract(payload, contractId) {
    var contracts = contractList(payload);
    for (var i = 0; i < contracts.length; i += 1) {
      if (contracts[i] && contracts[i].id === contractId) return contracts[i];
    }
    return contracts.length ? contracts[0] : null;
  }

  function isPut(contract) {
    return String(contract.option_type || "").toUpperCase() === "P";
  }

  function intrinsicAt(contract, sharePrice) {
    var strike = numberOr(contract.strike, 0);
    var value = isPut(contract) ? strike - sharePrice : sharePrice - strike;
    return value > 0 ? value : 0;
  }

  // Break-even per share: strike - ask for puts, strike + ask for calls.
  function breakEvenOf(contract) {
    var strike = numberOr(contract.strike, 0);
    var ask = numberOr(contract.ask, 0);
    return roundTo(isPut(contract) ? strike - ask : strike + ask, 2);
  }

  function labelFor(row) {
    var bits = [];
    if (row.pct !== null && row.pct !== undefined) {
      bits.push((row.pct > 0 ? "+" : "") + formatNumber(row.pct, 0) + "%");
    }
    if (row.break_even) bits.push("break-even");
    if (row.at_price) bits.push("at your price");
    return bits.join(" · ");
  }

  // The ladder: -30/-20/-10%, break-even, +10/+20/+30%, plus the slider's own
  // price, sorted ascending. Share prices are rounded to cents FIRST so the
  // intrinsic value shown always agrees with the share price shown. A row that
  // lands on an existing price is merged into it, never duplicated.
  function buildLadder(payload, contract, sharePrice, contracts, premium) {
    var base = numberOr(payload.current_price, 0);
    var multiplier = numberOr(contract.multiplier, 100);
    var rows = [];
    var i;

    function upsert(price, kind, pct) {
      var rounded = roundTo(price, 2);
      for (var j = 0; j < rows.length; j += 1) {
        if (rows[j].share_price === rounded) {
          if (kind === "break_even") rows[j].break_even = true;
          if (kind === "at_price") rows[j].at_price = true;
          if (pct !== null && rows[j].pct === null) rows[j].pct = pct;
          return rows[j];
        }
      }
      var row = {
        share_price: rounded,
        pct: pct,
        break_even: kind === "break_even",
        at_price: kind === "at_price"
      };
      rows.push(row);
      return row;
    }

    for (i = 0; i < LADDER_OFFSETS.length; i += 1) {
      upsert(base * (1 + LADDER_OFFSETS[i]), "pct", roundTo(LADDER_OFFSETS[i] * 100, 0));
    }
    upsert(breakEvenOf(contract), "break_even", null);
    if (sharePrice !== null && sharePrice !== undefined && isFinite(sharePrice)) {
      upsert(sharePrice, "at_price", null);
    }
    rows.sort(function (a, b) {
      return a.share_price - b.share_price;
    });
    for (i = 0; i < rows.length; i += 1) {
      var intrinsic = roundTo(intrinsicAt(contract, rows[i].share_price), 2);
      rows[i].intrinsic = intrinsic;
      // No position means no outcome to report — zeros here would read as a
      // real result rather than "you own nothing".
      rows[i].value = contracts > 0 ? roundTo(intrinsic * multiplier * contracts, 2) : null;
      rows[i].net = contracts > 0 ? roundTo(intrinsic * multiplier * contracts - premium, 2) : null;
      rows[i].label = labelFor(rows[i]);
    }
    return rows;
  }

  // Same key set as a successful result, so callers (and the parity mirror)
  // never have to branch on which shape they got.
  function disabledResult(payload, contract, reason) {
    return {
      ok: false,
      reason: reason,
      state: "disabled",
      contract_id: contract ? contract.id : null,
      option_type: contract ? (isPut(contract) ? "P" : "C") : null,
      label: contract ? contract.label || null : null,
      strike: contract ? numberOr(contract.strike, null) : null,
      ask: contract ? numberOr(contract.ask, null) : null,
      multiplier: contract ? numberOr(contract.multiplier, null) : null,
      currency: payload.currency || "USD",
      cost_per_contract: null,
      break_even: null,
      price: null,
      price_band: priceBand(payload.current_price),
      footnote: FOOTNOTE,
      contracts: 0,
      capped: false,
      premium: null,
      ladder: [],
      contracts_line: reason,
      announcement: reason
    };
  }

  // budget -> whole contracts -> value at expiry. `budget` may be null (the
  // user has not typed one yet), which is an idle state, not a zero result.
  function computeSizing(payload, contractId, budget, sharePrice) {
    var band = priceBand(payload.current_price);
    var contract = findContract(payload, contractId);
    var currency = payload.currency || "USD";
    if (!contract) {
      return disabledResult(payload, null, "No contract selected.");
    }
    var ask = numberOr(contract.ask, NaN);
    // The backend owns the verdict (ask missing / crossed / below intrinsic /
    // stale). The client only refuses to invent a substitute for it.
    if (contract.quote_ok === false || !isFinite(ask) || ask <= 0) {
      var reason = contract.quote_reason
        ? "This contract cannot be sized: " + contract.quote_reason + "."
        : "This contract cannot be sized: no usable ask price.";
      return disabledResult(payload, contract, reason);
    }
    var multiplier = numberOr(contract.multiplier, 100);
    var maxContracts = numberOr(payload.max_contracts, 10000);
    // Money is cents: rounding the per-contract cost before dividing stops
    // 0.85 * 100 = 85.00000000000001 from turning a clean 2 contracts into 1.
    var costPerContract = roundTo(ask * multiplier, 2);
    var breakEven = breakEvenOf(contract);
    var price = sharePrice === null || sharePrice === undefined ? null : numberOr(sharePrice, null);
    if (price === null && band) price = band.default;
    var money = budget === null || budget === undefined || budget === "" ? null : numberOr(budget, null);

    var common = {
      ok: true,
      reason: null,
      contract_id: contract.id,
      option_type: isPut(contract) ? "P" : "C",
      label: contract.label || null,
      strike: numberOr(contract.strike, 0),
      ask: ask,
      multiplier: multiplier,
      currency: currency,
      cost_per_contract: costPerContract,
      break_even: breakEven,
      price: price === null ? null : roundTo(price, 2),
      price_band: band,
      footnote: FOOTNOTE
    };

    if (money === null || money < 0) {
      common.state = "idle";
      common.contracts = 0;
      common.capped = false;
      common.premium = null;
      common.ladder = buildLadder(payload, contract, price, 0, 0);
      common.contracts_line = "Enter a budget to size a position.";
      common.announcement = common.contracts_line;
      return common;
    }

    // Whole contracts only, divided in cents rather than in binary. Rounding
    // the cost above is what actually does the work here (measured: with a
    // cent-rounded cost the epsilon never changes the answer across every ask
    // from $0.01 to $4.00 and every budget from $0.01 to $2,000); the epsilon
    // is the second net that keeps this line safe if the rounding ever moves.
    var raw = costPerContract > 0 ? Math.floor(money / costPerContract + EPS) : 0;
    var capped = raw > maxContracts;
    var contracts = capped ? maxContracts : raw;
    var premium = roundTo(costPerContract * contracts, 2);
    common.contracts = contracts;
    common.capped = capped;
    common.premium = premium;
    common.ladder = buildLadder(payload, contract, price, contracts, premium);

    if (contracts <= 0) {
      common.state = "zero";
      common.contracts_line =
        "0 contracts — one contract costs " + formatMoney(costPerContract, currency);
      common.announcement = common.contracts_line;
      return common;
    }
    common.state = "sized";
    var noun = contracts === 1 ? " contract" : " contracts";
    common.contracts_line =
      formatNumber(contracts, 0) + noun + " · " + formatMoney(premium, currency) +
      " premium · break-even " + formatMoney(breakEven, currency) +
      (capped ? " · capped at " + formatNumber(maxContracts, 0) + " contracts" : "");
    var atPrice = null;
    for (var i = 0; i < common.ladder.length; i += 1) {
      if (common.ladder[i].at_price) atPrice = common.ladder[i];
    }
    common.announcement =
      formatNumber(contracts, 0) + noun + ", net " +
      (atPrice ? formatMoney(atPrice.net, currency) : "n/a") + " at " +
      formatMoney(common.price, currency);
    return common;
  }

  var api = {
    roundHalfUp: roundHalfUp,
    roundTo: roundTo,
    formatNumber: formatNumber,
    formatMoney: formatMoney,
    priceBand: priceBand,
    breakEvenOf: breakEvenOf,
    intrinsicAt: intrinsicAt,
    buildLadder: buildLadder,
    computeSizing: computeSizing
  };
  if (global) global.GVOptionSizing = api;

  // Pure engine only when there is no DOM (the node parity driver imports this
  // file directly). Everything below needs a document.
  if (typeof document === "undefined" || !document.querySelector) return;

  // ------------------------------------------------------------ DOM layer --

  var warned = false;
  function warnOnce(message, error) {
    if (warned) return;
    warned = true;
    if (global && global.console && global.console.warn) global.console.warn(message, error);
  }

  function readPayload() {
    var node = document.getElementById(PAYLOAD_ID);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent || node.innerText || "");
    } catch (error) {
      warnOnce("option-sizing: payload is not valid JSON; the tool stays inert.", error);
      return null;
    }
  }

  function setText(node, text) {
    if (node) node.textContent = text === null || text === undefined ? "" : String(text);
  }

  function show(node, visible) {
    if (!node) return;
    if (visible) node.removeAttribute("hidden");
    else node.setAttribute("hidden", "hidden");
  }

  function cell(row, text, className) {
    var td = document.createElement("td");
    td.textContent = text;
    if (className) td.className = className;
    row.appendChild(td);
    return td;
  }

  function init() {
    var root = document.getElementById(ROOT_ID);
    var payload = readPayload();
    if (!root || !payload || !contractList(payload).length) return;

    var select = root.querySelector('select[data-role="contract"]');
    var budgetInput = root.querySelector('[data-role="budget"]');
    var priceInput = root.querySelector('[data-role="price"]');
    var priceOut = root.querySelector('[data-role="price-out"]');
    var resultRegion = root.querySelector('[data-role="result"]');
    var contractsLine = root.querySelector('[data-role="contracts-line"]');
    var ladderTable = root.querySelector('[data-role="ladder"]');
    var footnote = root.querySelector('[data-role="footnote"]');
    var live = root.querySelector('[data-role="live"]');
    var reset = root.querySelector('[data-role="reset"]');
    var band = priceBand(payload.current_price);
    var liveTimer = null;

    if (!band) return; // no usable share price: the tool cannot say anything true

    function currentContractId() {
      if (select && select.value) return select.value;
      var contracts = contractList(payload);
      return contracts.length ? contracts[0].id : null;
    }

    function applyMotionPreference() {
      var reduce =
        global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (reduce) {
        root.classList.add("reduced-motion");
        root.setAttribute("data-reduced-motion", "true");
      } else {
        root.classList.remove("reduced-motion");
        root.removeAttribute("data-reduced-motion");
      }
    }

    function announce(sentence) {
      if (!live) return;
      if (liveTimer) global.clearTimeout(liveTimer);
      // Trailing debounce: dragging the slider must not fire one announcement
      // per pixel at a screen-reader user.
      liveTimer = global.setTimeout(function () {
        setText(live, sentence || "");
      }, LIVE_DEBOUNCE_MS);
    }

    function ensureHead(table, currency) {
      if (table.tHead) return;
      var head = table.createTHead();
      var row = head.insertRow(-1);
      var labels = [
        "Share price",
        "Intrinsic / share",
        "Value at expiry",
        "Net P&L"
      ];
      for (var i = 0; i < labels.length; i += 1) {
        var th = document.createElement("th");
        th.scope = "col";
        th.textContent = labels[i];
        row.appendChild(th);
      }
      if (currency && currency !== "USD") row.setAttribute("data-currency", currency);
    }

    function renderLadder(view) {
      if (!ladderTable) return;
      if (!view.ok || !view.ladder.length) {
        show(ladderTable, false);
        var stale = ladderTable.querySelector("tbody");
        if (stale) stale.parentNode.removeChild(stale);
        return;
      }
      show(ladderTable, true);
      ensureHead(ladderTable, view.currency);
      var old = ladderTable.querySelector("tbody");
      if (old) old.parentNode.removeChild(old);
      var body = document.createElement("tbody");
      for (var i = 0; i < view.ladder.length; i += 1) {
        var row = view.ladder[i];
        var tr = document.createElement("tr");
        if (row.break_even) tr.classList.add("is-break-even");
        if (row.at_price) tr.classList.add("is-at-price");
        tr.setAttribute("data-share-price", String(row.share_price));
        if (row.break_even) tr.setAttribute("data-row-kind", "break-even");
        if (row.at_price) tr.setAttribute("data-row-kind", "at-price");
        var priceCell = cell(tr, formatMoney(row.share_price, view.currency), "sz-price");
        if (row.label) {
          var tag = document.createElement("span");
          tag.className = "sz-row-label";
          tag.textContent = " " + row.label;
          priceCell.appendChild(tag);
        }
        cell(tr, formatMoney(row.intrinsic, view.currency), "sz-intrinsic");
        cell(tr, row.value === null ? "n/a" : formatMoney(row.value, view.currency), "sz-value");
        cell(tr, row.net === null ? "n/a" : formatMoney(row.net, view.currency), "sz-net");
        body.appendChild(tr);
      }
      ladderTable.appendChild(body);
    }

    function render() {
      applyMotionPreference();
      var price = priceInput ? numberOr(priceInput.value, band.default) : band.default;
      var budget = budgetInput ? budgetInput.value : null;
      var view = computeSizing(payload, currentContractId(), budget, price);
      setText(priceOut, formatMoney(view.price === null ? price : view.price, view.currency));
      if (priceInput) {
        priceInput.setAttribute(
          "aria-valuetext",
          formatMoney(view.price === null ? price : view.price, view.currency)
        );
      }
      // A bad quote disables the tool with its reason. The contract select
      // stays live so the user can pick a different one.
      var blocked = !view.ok;
      if (budgetInput) budgetInput.disabled = blocked;
      if (priceInput) priceInput.disabled = blocked;
      if (resultRegion) resultRegion.setAttribute("data-state", view.state);
      if (root) root.setAttribute("data-state", view.state);
      setText(contractsLine, view.contracts_line);
      setText(footnote, FOOTNOTE);
      show(footnote, !blocked);
      renderLadder(view);
      announce(view.announcement);
    }

    if (priceInput) {
      priceInput.min = String(band.min);
      priceInput.max = String(band.max);
      priceInput.step = String(band.step);
      priceInput.value = String(band.default);
      priceInput.addEventListener("input", render);
      priceInput.addEventListener("change", render);
    }
    if (budgetInput) budgetInput.addEventListener("input", render);
    if (select) select.addEventListener("change", render);
    if (reset) {
      reset.addEventListener("click", function (event) {
        if (event && event.preventDefault) event.preventDefault();
        if (priceInput) priceInput.value = String(band.default);
        if (budgetInput) budgetInput.value = "";
        render();
      });
    }
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
