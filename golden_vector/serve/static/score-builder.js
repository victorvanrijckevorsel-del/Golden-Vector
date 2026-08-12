// "Compare on your own terms" — the opt-in score builder on the ticker page.
//
// This is 1 of the exactly 3 sanctioned client-side modules (plan §3.1). Every
// input it reads is already resolved by the backend: the percentiles, the
// catalog, the budget and the thresholds all arrive in one embedded JSON
// payload. The only arithmetic here is the combine rule the plan pins in §7 —
// a weighted average of backend percentiles — plus the integer weight budget.
// No fetches, no derived state shared with other modules, no formula that does
// not exist once on the backend side.
//
// PARITY LOCK — every rule below is mirrored in Python and machine-checked:
//   fixture : tests/fixtures/score_builder_parity.json
//   mirror  : tests/test_ticker_page_js_parity.py  (mirror_renormalize,
//             mirror_score, mirror_rank, mirror_stability)
// The pytest run drives THIS file through node when node is on PATH, so the
// two implementations cannot drift silently. Change a rule here and you must
// change the mirror, or the parity test fails.
//
// DOM contract (server-rendered; every piece is optional — a missing piece
// degrades, it never throws):
//   script#score-builder-payload[type="application/json"]   the payload
//   #score-builder                                          root container
//     [data-metric-key="<key>"]                             one row per metric
//       input[data-role="activate"]                         checkbox
//       button[data-role="direction"][aria-pressed]         higher/lower toggle
//       input[type="range"][data-role="weight"]             0..budget, step 1
//       [data-role="weight-points"]                         <output> for above
//     [data-role="reset"]                                   reset button
//   #score-builder-result                                   result region
//     [data-role="opt-in"]        server-rendered "pick a metric" prompt
//     [data-role="message"]       whole-result message (too few peers)
//     [data-role="subject-score"] [data-role="subject-rank"]
//     [data-role="subject-note"]  subject-unranked explanation
//     [data-role="contributions"] contribution bars (list)
//     [data-role="ranked-list"]   every miner, ranked then unranked
//     [data-role="stability-warning"]
//     [data-role="live"]          the ONE polite live region
//
// Opt-in (Q24): with zero active metrics the module renders nothing and leaves
// the server's prompt in place. It only takes over the result region once the
// user has activated at least one metric.
(function (global) {
  "use strict";

  var PAYLOAD_ID = "score-builder-payload";
  var ROOT_ID = "score-builder";
  var RESULT_ID = "score-builder-result";
  var STATE_PARAM = "sb";
  // Fractions are compared with a tolerance so that 3/5 >= 0.6 answers the same
  // way in JavaScript and in Python instead of hinging on the last bit.
  var EPS = 1e-9;
  var LIVE_DEBOUNCE_MS = 300;

  // ---------------------------------------------------------------- numbers --

  // Half away from zero. Deliberately NOT Math.round (which rounds -2.5 to -2)
  // and NOT Python's round() (which is banker's rounding) — one rule, both
  // languages, so the parity fixture can pin it.
  function roundHalfUp(value) {
    if (!isFinite(value)) return 0;
    return value >= 0 ? Math.floor(value + 0.5) : -Math.floor(-value + 0.5);
  }

  function roundTo(value, decimals) {
    if (!isFinite(value)) return value;
    var factor = Math.pow(10, decimals);
    return roundHalfUp(value * factor) / factor;
  }

  function clampInt(value, low, high) {
    if (!isFinite(value)) return low;
    if (value < low) return low;
    if (value > high) return high;
    return value;
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

  function sortedKeys(map) {
    var keys = [];
    for (var key in map) {
      if (Object.prototype.hasOwnProperty.call(map, key)) keys.push(key);
    }
    keys.sort();
    return keys;
  }

  // ------------------------------------------------------------ weight math --

  // Largest-remainder apportionment: floor every raw share, then hand the
  // leftover whole points to the largest fractional parts (ties broken by key
  // ascending). The integer total is EXACTLY `total`, always.
  function apportion(keys, raws, total) {
    var out = {};
    var order = [];
    var floorSum = 0;
    var i;
    var ordered = keys.slice().sort();
    var byKey = {};
    for (i = 0; i < keys.length; i += 1) byKey[keys[i]] = raws[i];
    if (!ordered.length) return out;
    for (i = 0; i < ordered.length; i += 1) {
      var raw = byKey[ordered[i]];
      if (!isFinite(raw) || raw < 0) raw = 0;
      var base = Math.floor(raw);
      out[ordered[i]] = base;
      floorSum += base;
      order.push({ key: ordered[i], frac: raw - base });
    }
    order.sort(function (a, b) {
      if (b.frac > a.frac) return 1;
      if (b.frac < a.frac) return -1;
      return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
    });
    var left = total - floorSum;
    if (left > 0) {
      for (i = 0; i < left; i += 1) out[order[i % order.length].key] += 1;
    } else if (left < 0) {
      // Defensive only (floors can never overshoot a well-formed input): peel
      // points back off the smallest fractional parts first.
      var need = -left;
      for (i = 0; i < need; i += 1) {
        var key = order[order.length - 1 - (i % order.length)].key;
        if (out[key] > 0) out[key] -= 1;
      }
    }
    return out;
  }

  // THE renormalization rule (plan §7). One metric's weight is set to
  // `newValue`; every other active metric keeps its relative proportion of what
  // is left of the budget, rounded by largest remainder so the total is exactly
  // the budget. A single active metric always holds the whole budget.
  function renormalize(weights, changedKey, newValue, budget) {
    var source = {};
    var keys = sortedKeys(weights);
    var i;
    for (i = 0; i < keys.length; i += 1) source[keys[i]] = weights[keys[i]];
    if (!Object.prototype.hasOwnProperty.call(source, changedKey)) {
      source[changedKey] = 0;
      keys.push(changedKey);
      keys.sort();
    }
    var others = [];
    for (i = 0; i < keys.length; i += 1) {
      if (keys[i] !== changedKey) others.push(keys[i]);
    }
    var out = {};
    if (!others.length) {
      out[changedKey] = budget;
      return out;
    }
    var value = clampInt(roundHalfUp(newValue), 0, budget);
    var remaining = budget - value;
    var base = 0;
    for (i = 0; i < others.length; i += 1) base += source[others[i]];
    var raws = [];
    for (i = 0; i < others.length; i += 1) {
      // All other weights sitting at zero carries no proportion to preserve, so
      // the remainder is split evenly rather than being lost.
      raws.push(base > 0 ? (source[others[i]] / base) * remaining : remaining / others.length);
    }
    out = apportion(others, raws, remaining);
    out[changedKey] = value;
    return out;
  }

  // Activating a metric gives it an equal share of the budget (budget / N for
  // the new active count) and renormalizes the rest through the same rule.
  function activateWeight(weights, key, budget) {
    var next = {};
    var keys = sortedKeys(weights);
    for (var i = 0; i < keys.length; i += 1) next[keys[i]] = weights[keys[i]];
    if (!Object.prototype.hasOwnProperty.call(next, key)) next[key] = 0;
    var count = sortedKeys(next).length;
    return renormalize(next, key, roundHalfUp(budget / count), budget);
  }

  // Deactivating returns the metric's points to the rest, proportionally.
  function deactivateWeight(weights, key, budget) {
    var others = [];
    var keys = sortedKeys(weights);
    var i;
    for (i = 0; i < keys.length; i += 1) {
      if (keys[i] !== key) others.push(keys[i]);
    }
    if (!others.length) return {};
    var base = 0;
    for (i = 0; i < others.length; i += 1) base += weights[others[i]];
    var raws = [];
    for (i = 0; i < others.length; i += 1) {
      raws.push(base > 0 ? (weights[others[i]] / base) * budget : budget / others.length);
    }
    return apportion(others, raws, budget);
  }

  // -------------------------------------------------------------- the model --

  function config(payload) {
    return {
      budget: numberOr(payload.budget_points, 100),
      minCoverage: numberOr(payload.min_active_metric_coverage, 0.6),
      minPeers: numberOr(payload.min_eligible_peers, 10),
      shiftPoints: numberOr(payload.rank_stability_shift_points, 10),
      alertPositions: numberOr(payload.rank_stability_alert_positions, 3)
    };
  }

  function numberOr(value, fallback) {
    var num = typeof value === "number" ? value : parseFloat(value);
    return isFinite(num) ? num : fallback;
  }

  function metricList(payload) {
    return payload && payload.metrics && payload.metrics.length ? payload.metrics : [];
  }

  function metricIndex(payload) {
    var index = {};
    var metrics = metricList(payload);
    for (var i = 0; i < metrics.length; i += 1) {
      if (metrics[i] && metrics[i].key) index[metrics[i].key] = metrics[i];
    }
    return index;
  }

  // A metric marked unavailable for the whole page (e.g. Tool D content in
  // Yahoo mode) can never be activated, so it can never enter a score.
  function isSelectable(metric) {
    return !!metric && metric.available !== false;
  }

  // Direction decides WHICH backend percentile is read. Nothing is inverted
  // client-side: both orientations are computed on the backend because ties
  // make 100 - p inexact (plan §7).
  function percentileFor(peer, key, highIsGood) {
    if (!peer || !peer.values) return null;
    var cell = peer.values[key];
    if (!cell || typeof cell !== "object") return null;
    var raw = highIsGood ? cell.pct_high_good : cell.pct_low_good;
    var num = typeof raw === "number" ? raw : parseFloat(raw);
    return isFinite(num) ? num : null;
  }

  // Active metrics in catalog order, dropping anything unselectable.
  function activeKeys(payload, state) {
    var metrics = metricList(payload);
    var out = [];
    for (var i = 0; i < metrics.length; i += 1) {
      var metric = metrics[i];
      if (!isSelectable(metric)) continue;
      if (state.weights && Object.prototype.hasOwnProperty.call(state.weights, metric.key)) {
        out.push(metric.key);
      }
    }
    return out;
  }

  function directionOf(payload, state, key) {
    if (state.directions && Object.prototype.hasOwnProperty.call(state.directions, key)) {
      return !!state.directions[key];
    }
    var metric = metricIndex(payload)[key];
    return metric ? metric.default_high_good !== false : true;
  }

  // One ticker's score: the weighted average of the percentiles it actually
  // has. Metrics the company lacks are excluded from ITS budget (plan §7)
  // rather than counted as a zero — a data gap must not read as a bad number.
  // With full coverage the divisor IS the budget, which is the §7 formula.
  function scoreTicker(peer, keys, weights, directions) {
    var total = 0;
    var weightSum = 0;
    var available = [];
    for (var i = 0; i < keys.length; i += 1) {
      var key = keys[i];
      var pct = percentileFor(peer, key, directions[key]);
      if (pct === null) continue;
      available.push(key);
      total += weights[key] * pct;
      weightSum += weights[key];
    }
    return {
      available: available,
      weight_sum: weightSum,
      score: weightSum > 0 ? total / weightSum : null
    };
  }

  function peerList(payload) {
    return payload && payload.peers && payload.peers.length ? payload.peers : [];
  }

  // Ranking + coverage + ties, exactly per plan §7.
  function rankAll(payload, state) {
    var cfg = config(payload);
    var keys = activeKeys(payload, state);
    var directions = {};
    var weights = {};
    var i;
    for (i = 0; i < keys.length; i += 1) {
      directions[keys[i]] = directionOf(payload, state, keys[i]);
      // Read-time guard: one NaN weight would poison every score in the cohort.
      weights[keys[i]] = clampInt(roundHalfUp(numberOr(state.weights[keys[i]], 0)), 0, cfg.budget);
    }
    var peers = peerList(payload);
    var ranked = [];
    var unranked = [];
    var subjectDetail = null;
    for (i = 0; i < peers.length; i += 1) {
      var peer = peers[i];
      if (!peer || !peer.ticker) continue;
      var detail = scoreTicker(peer, keys, weights, directions);
      var fraction = keys.length ? detail.available.length / keys.length : 0;
      var covered = detail.available.length >= 1 && fraction >= cfg.minCoverage - EPS;
      var entry = {
        ticker: peer.ticker,
        detail_url: peer.detail_url || null,
        available: detail.available.length,
        active: keys.length
      };
      if (covered && detail.score !== null) {
        entry.score = detail.score;
        ranked.push(entry);
      } else {
        // Truthful reasons, two shapes: not enough of the user's metrics, or
        // enough of them but none carrying any weight.
        entry.note = covered
          ? "has none of your weighted metrics"
          : "has " + formatNumber(detail.available.length, 0) + " of your " +
            formatNumber(keys.length, 0) + " metrics";
        unranked.push(entry);
      }
      if (peer.ticker === payload.subject) subjectDetail = detail;
    }
    ranked.sort(function (a, b) {
      if (b.score > a.score) return 1;
      if (b.score < a.score) return -1;
      return a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0;
    });
    unranked.sort(function (a, b) {
      return a.ticker < b.ticker ? -1 : a.ticker > b.ticker ? 1 : 0;
    });
    // Two tie layers, two rules (plan §7): the ORDER is always total and
    // deterministic (score desc, ticker asc); the "tied" marker says the scores
    // are indistinguishable at the 0.1 the page displays. Rounding is monotone,
    // so equal displayed scores are always adjacent here.
    var counts = {};
    for (i = 0; i < ranked.length; i += 1) {
      ranked[i].rank = i + 1;
      ranked[i].display_score = roundTo(ranked[i].score, 1);
      var bucket = String(ranked[i].display_score);
      counts[bucket] = (counts[bucket] || 0) + 1;
    }
    for (i = 0; i < ranked.length; i += 1) {
      ranked[i].tied = counts[String(ranked[i].display_score)] > 1;
    }
    return {
      keys: keys,
      weights: weights,
      directions: directions,
      config: cfg,
      ranked: ranked,
      unranked: unranked,
      subject_detail: subjectDetail
    };
  }

  // Signed, weight-aware, neutral at the 50th percentile (plan §7, pinned).
  function contributionsFor(payload, model) {
    var subject = null;
    var peers = peerList(payload);
    var i;
    for (i = 0; i < peers.length; i += 1) {
      if (peers[i] && peers[i].ticker === payload.subject) subject = peers[i];
    }
    if (!subject) return { items: [], missing: [] };
    var index = metricIndex(payload);
    var items = [];
    var missing = [];
    for (i = 0; i < model.keys.length; i += 1) {
      var key = model.keys[i];
      var pct = percentileFor(subject, key, model.directions[key]);
      var metric = index[key];
      var label = metric && metric.label ? metric.label : key;
      if (pct === null) {
        missing.push({ key: key, label: label });
        continue;
      }
      var value = model.weights[key] * ((pct - 50) / 50);
      items.push({
        key: key,
        label: label,
        percentile: roundTo(pct, 1),
        weight: model.weights[key],
        contribution: roundTo(value, 1),
        raw: value
      });
    }
    var maxAbs = 0;
    for (i = 0; i < items.length; i += 1) {
      if (Math.abs(items[i].raw) > maxAbs) maxAbs = Math.abs(items[i].raw);
    }
    for (i = 0; i < items.length; i += 1) {
      // Bars scale by |contribution| against the largest one, so a 1-point
      // metric can never look as influential as an 80-point one.
      items[i].share = maxAbs > 0 ? roundTo(Math.abs(items[i].raw) / maxAbs, 3) : 0;
      items[i].sign = items[i].raw < 0 ? "neg" : "pos";
      delete items[i].raw;
    }
    items.sort(function (a, b) {
      var da = Math.abs(a.contribution);
      var db = Math.abs(b.contribution);
      if (db > da) return 1;
      if (db < da) return -1;
      return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
    });
    return { items: items, missing: missing };
  }

  function subjectRankIn(ranked, subject) {
    for (var i = 0; i < ranked.length; i += 1) {
      if (ranked[i].ticker === subject) return ranked[i].rank;
    }
    return null;
  }

  // Stability probe: shift each active weight by ±shift_points (clamped to the
  // budget), renormalize the others by the SAME rule, and see how far the
  // subject's rank travels. A ranking that moves more than the configured
  // number of places on a single nudge is fragile and must say so.
  function stability(payload, state) {
    var cfg = config(payload);
    var model = rankAll(payload, state);
    var baseRank = subjectRankIn(model.ranked, payload.subject);
    var blank = { warning: false, key: null, label: null, positions: 0, shift_points: cfg.shiftPoints, message: null };
    if (baseRank === null || !model.keys.length) return blank;
    var index = metricIndex(payload);
    var worst = null;
    for (var i = 0; i < model.keys.length; i += 1) {
      var key = model.keys[i];
      var deltas = [cfg.shiftPoints, -cfg.shiftPoints];
      for (var d = 0; d < deltas.length; d += 1) {
        var target = clampInt(model.weights[key] + deltas[d], 0, cfg.budget);
        if (target === model.weights[key]) continue;
        var probeState = {
          weights: renormalize(model.weights, key, target, cfg.budget),
          directions: model.directions
        };
        var probe = rankAll(payload, probeState);
        var probeRank = subjectRankIn(probe.ranked, payload.subject);
        if (probeRank === null) continue;
        var moved = Math.abs(probeRank - baseRank);
        if (
          worst === null ||
          moved > worst.positions ||
          (moved === worst.positions && key < worst.key)
        ) {
          worst = { key: key, positions: moved };
        }
      }
    }
    if (!worst || worst.positions <= cfg.alertPositions) return blank;
    var metric = index[worst.key];
    var label = metric && metric.label ? metric.label : worst.key;
    return {
      warning: true,
      key: worst.key,
      label: label,
      positions: worst.positions,
      shift_points: cfg.shiftPoints,
      message:
        "Shifting '" + label + "' by " + formatNumber(cfg.shiftPoints, 0) +
        " points moves the rank by " + formatNumber(worst.positions, 0) +
        (worst.positions === 1 ? " place" : " places") +
        " — treat this ordering as fragile."
    };
  }

  // The whole result in one object — the same shape the Python mirror returns,
  // which is what the parity fixture compares.
  function evaluate(payload, state) {
    var cfg = config(payload);
    var keys = activeKeys(payload, state);
    if (!keys.length) {
      return {
        status: "empty",
        message: null,
        weights: {},
        keys: [],
        subject_score: null,
        subject_rank: null,
        subject_note: null,
        ranked_count: 0,
        ranked: [],
        unranked: [],
        contributions: [],
        missing: [],
        stability: { warning: false, key: null, label: null, positions: 0, shift_points: cfg.shiftPoints, message: null },
        url_state: "",
        announcement: null
      };
    }
    var model = rankAll(payload, state);
    var urlState = encodeState(payload, state);
    if (model.ranked.length < cfg.minPeers) {
      return {
        status: "not_enough_peers",
        message:
          "Not enough comparable miners — " + formatNumber(model.ranked.length, 0) +
          " have enough of your metrics and at least " + formatNumber(cfg.minPeers, 0) +
          " are needed.",
        weights: model.weights,
        keys: keys,
        subject_score: null,
        subject_rank: null,
        subject_note: null,
        ranked_count: model.ranked.length,
        ranked: [],
        unranked: [],
        contributions: [],
        missing: [],
        stability: { warning: false, key: null, label: null, positions: 0, shift_points: cfg.shiftPoints, message: null },
        url_state: urlState,
        announcement:
          "Not enough comparable miners for this combination of metrics."
      };
    }
    var subjectRank = subjectRankIn(model.ranked, payload.subject);
    var subjectScore = null;
    var subjectNote = null;
    var contributions = { items: [], missing: [] };
    var stable = { warning: false, key: null, label: null, positions: 0, shift_points: cfg.shiftPoints, message: null };
    if (subjectRank !== null) {
      for (var i = 0; i < model.ranked.length; i += 1) {
        if (model.ranked[i].ticker === payload.subject) subjectScore = model.ranked[i].display_score;
      }
      contributions = contributionsFor(payload, model);
      stable = stability(payload, state);
    } else {
      for (var u = 0; u < model.unranked.length; u += 1) {
        if (model.unranked[u].ticker === payload.subject) subjectNote = model.unranked[u].note;
      }
    }
    var announcement =
      subjectRank !== null
        ? "Score " + formatNumber(subjectScore, 1) + ", rank " + formatNumber(subjectRank, 0) +
          " of " + formatNumber(model.ranked.length, 0)
        : payload.subject + " is not ranked — " + (subjectNote || "not enough of your metrics");
    return {
      status: "ok",
      message: null,
      weights: model.weights,
      keys: keys,
      subject_score: subjectScore,
      subject_rank: subjectRank,
      subject_note: subjectNote,
      ranked_count: model.ranked.length,
      ranked: model.ranked,
      unranked: model.unranked,
      contributions: contributions.items,
      missing: contributions.missing,
      stability: stable,
      url_state: urlState,
      announcement: announcement
    };
  }

  // ------------------------------------------------------------- URL state --

  // sb=key:pts:dir,... — only ACTIVE metrics, catalog order, dir h|l.
  function encodeState(payload, state) {
    var keys = activeKeys(payload, state);
    var parts = [];
    for (var i = 0; i < keys.length; i += 1) {
      var key = keys[i];
      // Raw integer, never formatNumber: a thousands separator would be a comma
      // and commas separate entries in this encoding.
      var points = clampInt(roundHalfUp(numberOr(state.weights[key], 0)), 0, config(payload).budget);
      parts.push(key + ":" + String(points) + ":" + (directionOf(payload, state, key) ? "h" : "l"));
    }
    return parts.join(",");
  }

  // Hostile-input tolerant: unknown keys dropped, malformed entries ignored,
  // duplicates keep the first, and points that do not sum to the budget are
  // renormalized instead of rejected.
  function parseState(payload, raw) {
    var cfg = config(payload);
    var index = metricIndex(payload);
    var weights = {};
    var directions = {};
    var order = [];
    var entries = typeof raw === "string" && raw.length ? raw.split(",") : [];
    for (var i = 0; i < entries.length; i += 1) {
      var bits = entries[i].split(":");
      if (bits.length !== 3) continue;
      var key = bits[0];
      if (!Object.prototype.hasOwnProperty.call(index, key)) continue;
      if (!isSelectable(index[key])) continue;
      if (Object.prototype.hasOwnProperty.call(weights, key)) continue;
      if (!/^[0-9]+$/.test(bits[1])) continue;
      if (bits[2] !== "h" && bits[2] !== "l") continue;
      weights[key] = clampInt(parseInt(bits[1], 10), 0, cfg.budget);
      directions[key] = bits[2] === "h";
      order.push(key);
    }
    if (!order.length) return { weights: {}, directions: {} };
    var total = 0;
    for (i = 0; i < order.length; i += 1) total += weights[order[i]];
    if (total !== cfg.budget) {
      var raws = [];
      for (i = 0; i < order.length; i += 1) {
        raws.push(total > 0 ? (weights[order[i]] / total) * cfg.budget : cfg.budget / order.length);
      }
      weights = apportion(order, raws, cfg.budget);
    }
    return { weights: weights, directions: directions };
  }

  // Replace (or add, or drop) one query parameter without disturbing the rest —
  // financials_source, window, the option params and the anchor all survive.
  function withParam(href, name, value) {
    var target = typeof href === "string" ? href : "";
    var hash = "";
    var hashAt = target.indexOf("#");
    if (hashAt >= 0) {
      hash = target.slice(hashAt);
      target = target.slice(0, hashAt);
    }
    var queryAt = target.indexOf("?");
    var base = queryAt >= 0 ? target.slice(0, queryAt) : target;
    var query = queryAt >= 0 ? target.slice(queryAt + 1) : "";
    var kept = [];
    var parts = query ? query.split("&") : [];
    for (var i = 0; i < parts.length; i += 1) {
      if (!parts[i]) continue;
      var eq = parts[i].indexOf("=");
      var partName = eq >= 0 ? parts[i].slice(0, eq) : parts[i];
      if (partName === name) continue;
      kept.push(parts[i]);
    }
    if (value) kept.push(name + "=" + encodeURIComponent(value));
    return base + (kept.length ? "?" + kept.join("&") : "") + hash;
  }

  // ------------------------------------------------------------ transitions --

  // Every user action goes through here — the DOM handlers below and the parity
  // driver both call it, so there is exactly one implementation of "what does
  // clicking this do". Guards live here: an unavailable metric can never be
  // activated, and an inactive metric has no weight to set.
  function applyStep(payload, state, step) {
    var cfg = config(payload);
    var index = metricIndex(payload);
    var next = { weights: {}, directions: {} };
    var keys = sortedKeys(state.weights || {});
    var i;
    for (i = 0; i < keys.length; i += 1) next.weights[keys[i]] = state.weights[keys[i]];
    var dirs = sortedKeys(state.directions || {});
    for (i = 0; i < dirs.length; i += 1) next.directions[dirs[i]] = state.directions[dirs[i]];
    if (!step || !step.action) return next;
    var key = step.key;
    var metric = Object.prototype.hasOwnProperty.call(index, key) ? index[key] : null;
    var active = Object.prototype.hasOwnProperty.call(next.weights, key);
    if (step.action === "reset") return { weights: {}, directions: {} };
    if (!metric) return next;
    if (step.action === "activate") {
      if (!isSelectable(metric) || active) return next;
      next.weights = activateWeight(next.weights, key, cfg.budget);
    } else if (step.action === "deactivate") {
      if (!active) return next;
      next.weights = deactivateWeight(next.weights, key, cfg.budget);
    } else if (step.action === "set_weight") {
      if (!active) return next;
      next.weights = renormalize(next.weights, key, numberOr(step.points, 0), cfg.budget);
    } else if (step.action === "flip_direction") {
      if (!isSelectable(metric)) return next;
      next.directions[key] = !directionOf(payload, state, key);
    }
    return next;
  }

  var api = {
    roundHalfUp: roundHalfUp,
    roundTo: roundTo,
    formatNumber: formatNumber,
    apportion: apportion,
    renormalize: renormalize,
    activateWeight: activateWeight,
    deactivateWeight: deactivateWeight,
    scoreTicker: scoreTicker,
    applyStep: applyStep,
    rankAll: rankAll,
    stability: stability,
    evaluate: evaluate,
    encodeState: encodeState,
    parseState: parseState,
    withParam: withParam
  };
  if (global) global.GVScoreBuilder = api;

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
      warnOnce("score-builder: payload is not valid JSON; the builder stays inert.", error);
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

  function init() {
    var root = document.getElementById(ROOT_ID);
    var payload = readPayload();
    if (!root || !payload || !metricList(payload).length) return;

    var result = document.getElementById(RESULT_ID);
    var rows = root.querySelectorAll("[data-metric-key]");
    var cfg = config(payload);
    var index = metricIndex(payload);
    var state = { weights: {}, directions: {} };
    var liveTimer = null;

    var parts = {
      optIn: result ? result.querySelector('[data-role="opt-in"]') : null,
      message: result ? result.querySelector('[data-role="message"]') : null,
      score: result ? result.querySelector('[data-role="subject-score"]') : null,
      rank: result ? result.querySelector('[data-role="subject-rank"]') : null,
      note: result ? result.querySelector('[data-role="subject-note"]') : null,
      contributions: result ? result.querySelector('[data-role="contributions"]') : null,
      list: result ? result.querySelector('[data-role="ranked-list"]') : null,
      warning: result ? result.querySelector('[data-role="stability-warning"]') : null,
      live: result ? result.querySelector('[data-role="live"]') : null
    };

    function controls(row) {
      return {
        activate: row.querySelector('input[data-role="activate"]'),
        direction: row.querySelector('button[data-role="direction"]'),
        weight: row.querySelector('input[data-role="weight"]'),
        output: row.querySelector('[data-role="weight-points"]')
      };
    }

    function isActive(key) {
      return Object.prototype.hasOwnProperty.call(state.weights, key);
    }

    // Reduced motion is a user setting, not a preference we get to override:
    // the class is the contract the stylesheet keys transitions off.
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

    function syncControls() {
      for (var i = 0; i < rows.length; i += 1) {
        var row = rows[i];
        var key = row.getAttribute("data-metric-key");
        var metric = index[key];
        var parts2 = controls(row);
        var selectable = isSelectable(metric);
        var active = selectable && isActive(key);
        var points = active ? state.weights[key] : 0;
        var high = directionOf(payload, state, key);
        row.setAttribute("data-active", active ? "true" : "false");
        if (parts2.activate) {
          parts2.activate.checked = active;
          parts2.activate.disabled = !selectable;
        }
        if (parts2.weight) {
          parts2.weight.min = "0";
          parts2.weight.max = String(cfg.budget);
          parts2.weight.step = "1";
          parts2.weight.value = String(points);
          parts2.weight.disabled = !active;
          parts2.weight.setAttribute(
            "aria-valuetext",
            formatNumber(points, 0) + " of " + formatNumber(cfg.budget, 0) + " points"
          );
        }
        setText(parts2.output, formatNumber(points, 0));
        if (parts2.direction) {
          parts2.direction.setAttribute("aria-pressed", high ? "true" : "false");
          parts2.direction.textContent = high ? "Higher is better" : "Lower is better";
          parts2.direction.disabled = !selectable;
        }
      }
    }

    function announce(sentence) {
      if (!parts.live) return;
      if (liveTimer) global.clearTimeout(liveTimer);
      // Trailing debounce: dragging a slider must not fire one announcement per
      // pixel at a screen-reader user.
      liveTimer = global.setTimeout(function () {
        setText(parts.live, sentence || "");
      }, LIVE_DEBOUNCE_MS);
    }

    function renderContributions(items) {
      if (!parts.contributions) return;
      parts.contributions.textContent = "";
      for (var i = 0; i < items.length; i += 1) {
        var item = items[i];
        var li = document.createElement("li");
        li.className = "sb-contribution";
        li.setAttribute("data-metric-key", item.key);
        li.setAttribute("data-sign", item.sign);
        var label = document.createElement("span");
        label.className = "sb-contribution-label";
        label.textContent = item.label;
        var track = document.createElement("span");
        track.className = "sb-bar-track";
        var fill = document.createElement("span");
        // Sign colour comes from the stylesheet (classes pos/neg) — the only
        // inline style is the bar's own length, which is data, not decoration.
        fill.className = "sb-bar " + item.sign;
        fill.style.width = formatNumber(item.share * 100, 1) + "%";
        track.appendChild(fill);
        var value = document.createElement("span");
        value.className = "sb-contribution-value";
        value.textContent =
          formatNumber(item.contribution, 1) + " (" + formatNumber(item.weight, 0) + " pts)";
        li.appendChild(label);
        li.appendChild(track);
        li.appendChild(value);
        parts.contributions.appendChild(li);
      }
    }

    function renderList(view) {
      if (!parts.list) return;
      parts.list.textContent = "";
      var sb = view.url_state;
      var i;
      for (i = 0; i < view.ranked.length; i += 1) {
        var entry = view.ranked[i];
        var li = document.createElement("li");
        li.setAttribute("data-ticker", entry.ticker);
        if (entry.ticker === payload.subject) li.className = "is-subject";
        var rank = document.createElement("span");
        rank.className = "sb-rank";
        rank.textContent = "#" + formatNumber(entry.rank, 0);
        li.appendChild(rank);
        li.appendChild(tickerNode(entry, sb));
        var score = document.createElement("span");
        score.className = "sb-score";
        score.textContent = formatNumber(entry.display_score, 1);
        li.appendChild(score);
        if (entry.tied) {
          var tied = document.createElement("span");
          tied.className = "sb-tied";
          tied.textContent = "tied";
          li.appendChild(tied);
        }
        parts.list.appendChild(li);
      }
      for (i = 0; i < view.unranked.length; i += 1) {
        var row = view.unranked[i];
        var item = document.createElement("li");
        item.className = "is-unranked";
        item.setAttribute("data-ticker", row.ticker);
        var marker = document.createElement("span");
        marker.className = "sb-rank";
        marker.textContent = "unranked";
        item.appendChild(marker);
        item.appendChild(tickerNode(row, sb));
        var note = document.createElement("span");
        note.className = "sb-note";
        note.textContent = row.note;
        item.appendChild(note);
        parts.list.appendChild(item);
      }
    }

    // The comparison definition travels with every link out of the list, so
    // clicking a peer never loses the weights the user just built (plan §9.4).
    function tickerNode(entry, sb) {
      if (!entry.detail_url) {
        var span = document.createElement("span");
        span.className = "sb-ticker";
        span.textContent = entry.ticker;
        return span;
      }
      var link = document.createElement("a");
      link.className = "sb-ticker";
      link.href = withParam(entry.detail_url, STATE_PARAM, sb);
      link.textContent = entry.ticker;
      return link;
    }

    function pushUrl(sb) {
      if (!global.history || !global.history.replaceState || !global.location) return;
      var here = global.location.pathname + global.location.search;
      try {
        global.history.replaceState(null, "", withParam(here, STATE_PARAM, sb) + global.location.hash);
      } catch (error) {
        warnOnce("score-builder: could not update the address bar.", error);
      }
    }

    function render() {
      applyMotionPreference();
      syncControls();
      var view = evaluate(payload, state);
      pushUrl(view.url_state);
      if (!result) return;
      if (view.status === "empty") {
        // Opt-in: hand the region back to the server's prompt untouched.
        show(parts.optIn, true);
        show(parts.message, false);
        show(parts.warning, false);
        if (parts.list) parts.list.textContent = "";
        if (parts.contributions) parts.contributions.textContent = "";
        setText(parts.score, "");
        setText(parts.rank, "");
        setText(parts.note, "");
        announce("");
        return;
      }
      show(parts.optIn, false);
      if (view.status === "not_enough_peers") {
        show(parts.message, true);
        setText(parts.message, view.message);
        show(parts.warning, false);
        if (parts.list) parts.list.textContent = "";
        if (parts.contributions) parts.contributions.textContent = "";
        setText(parts.score, "");
        setText(parts.rank, "");
        setText(parts.note, "");
        announce(view.announcement);
        return;
      }
      show(parts.message, false);
      setText(parts.score, view.subject_score === null ? "" : formatNumber(view.subject_score, 1));
      setText(
        parts.rank,
        view.subject_rank === null
          ? ""
          : "#" + formatNumber(view.subject_rank, 0) + " of " + formatNumber(view.ranked_count, 0) + " ranked"
      );
      setText(parts.note, view.subject_note || "");
      show(parts.note, !!view.subject_note);
      renderContributions(view.contributions);
      renderList(view);
      show(parts.warning, view.stability.warning);
      setText(parts.warning, view.stability.message || "");
      announce(view.announcement);
    }

    function step(action, key, points) {
      state = applyStep(payload, state, { action: action, key: key, points: points });
      render();
    }

    for (var r = 0; r < rows.length; r += 1) {
      (function (row) {
        var key = row.getAttribute("data-metric-key");
        var handles = controls(row);
        if (handles.activate) {
          handles.activate.addEventListener("change", function () {
            step(handles.activate.checked ? "activate" : "deactivate", key, null);
          });
        }
        if (handles.weight) {
          handles.weight.addEventListener("input", function () {
            step("set_weight", key, parseFloat(handles.weight.value));
          });
        }
        if (handles.direction) {
          handles.direction.addEventListener("click", function () {
            step("flip_direction", key, null);
          });
        }
      })(rows[r]);
    }

    var reset = root.querySelector('[data-role="reset"]');
    if (reset) {
      reset.addEventListener("click", function (event) {
        if (event && event.preventDefault) event.preventDefault();
        step("reset", null, null);
      });
    }

    if (global.location && global.location.search) {
      var query = global.location.search.replace(/^\?/, "").split("&");
      for (var q = 0; q < query.length; q += 1) {
        var eq = query[q].indexOf("=");
        if (eq >= 0 && query[q].slice(0, eq) === STATE_PARAM) {
          state = parseState(payload, decodeURIComponent(query[q].slice(eq + 1).replace(/\+/g, " ")));
        }
      }
    }
    render();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : this);
