"""Parity lock for the two first-party ticker-page JavaScript modules.

The ticker page is allowed exactly three client-side modules (plan §3.1). Two of
them live here: `static/score-builder.js` (the opt-in comparison engine, plan §7)
and `static/option-sizing.js` (the intrinsic-value position ladder, plan §9.4).
Because those modules do arithmetic in the browser, the arithmetic has to be
pinned somewhere a test can see it — otherwise the only description of the rules
is the JavaScript itself and it can drift silently.

This file is that pin, in three layers:

1. **The mirror.** `mirror_renormalize`, `mirror_score`, `mirror_rank`,
   `mirror_stability` and `mirror_sizing` (plus their helpers) reimplement the
   modules' rules in Python. They are module-level on purpose: the M4 browser
   gate imports them to check what the real page renders.
2. **The fixtures.** `tests/fixtures/score_builder_parity.json` and
   `tests/fixtures/option_sizing_parity.json` hold a payload, a list of user
   steps, and the expected output after each step. The tests assert the stored
   expectations equal the mirror's output, so the fixtures are machine-verified
   rather than hand-trusted, and a rule change cannot quietly rewrite them.
3. **The real JavaScript.** When `node` is on PATH the tests execute the actual
   module files and compare their output to the mirror's, step for step. That is
   the layer that makes this a parity test rather than a Python unit test.

On top of that, `test_hand_derived_*` assert values worked out by hand — the
mirror could agree with itself all day and still be wrong, so a handful of
anchors are computed independently.

Float parity note: both implementations iterate metrics in the same catalog
order, because float addition is not associative and a different summation order
would produce a different last bit.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "golden_vector" / "serve" / "static"
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
SCORE_FIXTURE = FIXTURE_DIR / "score_builder_parity.json"
SIZING_FIXTURE = FIXTURE_DIR / "option_sizing_parity.json"
SCORE_JS = STATIC_DIR / "score-builder.js"
SIZING_JS = STATIC_DIR / "option-sizing.js"

# Mirrors the modules' own constants.
EPS = 1e-9
LADDER_OFFSETS = (-0.3, -0.2, -0.1, 0.1, 0.2, 0.3)
FOOTNOTE = (
    "Value at expiry is intrinsic value only — no time value is assumed, "
    "so selling before expiry would normally be worth more than these rows show."
)

_LEADING_NUMBER = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


# --------------------------------------------------------------------- numbers


def _js_parse_float(value: Any) -> float | None:
    """`parseFloat` semantics, including its tolerance for trailing junk."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if not isinstance(value, str):
        return None
    match = _LEADING_NUMBER.match(value.strip())
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _number_or(value: Any, fallback: Any) -> Any:
    number = _js_parse_float(value)
    return fallback if number is None else number


def mirror_round_half_up(value: float) -> int:
    """Half away from zero — not `Math.round`, and not Python's banker's round."""
    if not math.isfinite(value):
        return 0
    return math.floor(value + 0.5) if value >= 0 else -math.floor(-value + 0.5)


def mirror_round_to(value: float, decimals: int) -> float:
    if not math.isfinite(value):
        return value
    factor = 10.0**decimals
    return mirror_round_half_up(value * factor) / factor


def _clamp_int(value: float, low: int, high: int) -> int:
    if not math.isfinite(value):
        return low
    if value < low:
        return low
    if value > high:
        return high
    return int(value)


def mirror_format_number(value: Any, decimals: int = 0) -> str:
    """Thousands-separated, fixed decimals, plain ASCII '-' (never U+2212)."""
    places = int(decimals) if isinstance(decimals, (int, float)) and decimals > 0 else 0
    number = _js_parse_float(value)
    if number is None:
        return "n/a"
    negative = number < 0
    scaled = mirror_round_half_up(abs(number) * (10.0**places))
    digits = str(scaled)
    while len(digits) <= places:
        digits = "0" + digits
    whole = digits[: len(digits) - places] if places > 0 else digits
    frac = digits[len(digits) - places :] if places > 0 else ""
    out = ""
    for index, char in enumerate(whole):
        if index > 0 and (len(whole) - index) % 3 == 0:
            out += ","
        out += char
    if places > 0:
        out += "." + frac
    return ("-" if negative and scaled != 0 else "") + out


def mirror_format_money(value: Any, currency: str = "USD", decimals: int = 2) -> str:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "n/a"
    body = mirror_format_number(abs(float(value)), decimals)
    sign = "-" if float(value) < 0 and body != mirror_format_number(0, decimals) else ""
    code = currency or "USD"
    return sign + "$" + body if code == "USD" else sign + code + " " + body


# ---------------------------------------------------------------- weight math


def mirror_apportion(keys: list[str], raws: list[float], total: int) -> dict[str, int]:
    """Largest-remainder apportionment; ties broken by key ascending."""
    ordered = sorted(keys)
    if not ordered:
        return {}
    by_key = {key: raws[index] for index, key in enumerate(keys)}
    out: dict[str, int] = {}
    order: list[dict[str, Any]] = []
    floor_sum = 0
    for key in ordered:
        raw = by_key[key]
        if not math.isfinite(raw) or raw < 0:
            raw = 0.0
        base = math.floor(raw)
        out[key] = base
        floor_sum += base
        order.append({"key": key, "frac": raw - base})
    order.sort(key=lambda entry: (-entry["frac"], entry["key"]))
    left = int(total - floor_sum)
    if left > 0:
        for index in range(left):
            out[order[index % len(order)]["key"]] += 1
    elif left < 0:
        for index in range(-left):
            key = order[len(order) - 1 - (index % len(order))]["key"]
            if out[key] > 0:
                out[key] -= 1
    return out


def mirror_renormalize(
    weights: dict[str, int], changed_key: str, new_value: float, budget: int
) -> dict[str, int]:
    """THE weight rule: one weight is set, the rest keep their proportions."""
    source = dict(weights)
    source.setdefault(changed_key, 0)
    others = [key for key in sorted(source) if key != changed_key]
    if not others:
        return {changed_key: int(budget)}
    value = _clamp_int(mirror_round_half_up(new_value), 0, budget)
    remaining = int(budget) - value
    base = sum(source[key] for key in others)
    raws = [
        (source[key] / base) * remaining if base > 0 else remaining / len(others)
        for key in others
    ]
    out = mirror_apportion(others, raws, remaining)
    out[changed_key] = value
    return out


def mirror_activate(weights: dict[str, int], key: str, budget: int) -> dict[str, int]:
    nxt = dict(weights)
    nxt.setdefault(key, 0)
    return mirror_renormalize(nxt, key, mirror_round_half_up(budget / len(nxt)), budget)


def mirror_deactivate(weights: dict[str, int], key: str, budget: int) -> dict[str, int]:
    others = [other for other in sorted(weights) if other != key]
    if not others:
        return {}
    base = sum(weights[other] for other in others)
    raws = [
        (weights[other] / base) * budget if base > 0 else budget / len(others)
        for other in others
    ]
    return mirror_apportion(others, raws, budget)


# ------------------------------------------------------------ the score model


def mirror_config(payload: dict) -> dict:
    return {
        "budget": int(_number_or(payload.get("budget_points"), 100)),
        "min_coverage": float(_number_or(payload.get("min_active_metric_coverage"), 0.6)),
        "min_peers": int(_number_or(payload.get("min_eligible_peers"), 10)),
        "shift_points": int(_number_or(payload.get("rank_stability_shift_points"), 10)),
        "alert_positions": int(_number_or(payload.get("rank_stability_alert_positions"), 3)),
    }


def _metrics(payload: dict) -> list[dict]:
    return list(payload.get("metrics") or [])


def _metric_index(payload: dict) -> dict[str, dict]:
    return {metric["key"]: metric for metric in _metrics(payload) if metric.get("key")}


def _selectable(metric: dict | None) -> bool:
    return bool(metric) and metric.get("available") is not False


def mirror_percentile(peer: dict, key: str, high_is_good: bool) -> float | None:
    """Direction chooses WHICH backend percentile is read — nothing is inverted."""
    values = peer.get("values") if peer else None
    if not isinstance(values, dict):
        return None
    cell = values.get(key)
    if not isinstance(cell, dict):
        return None
    return _js_parse_float(cell.get("pct_high_good") if high_is_good else cell.get("pct_low_good"))


def mirror_active_keys(payload: dict, state: dict) -> list[str]:
    weights = state.get("weights") or {}
    return [
        metric["key"]
        for metric in _metrics(payload)
        if _selectable(metric) and metric["key"] in weights
    ]


def mirror_direction(payload: dict, state: dict, key: str) -> bool:
    directions = state.get("directions") or {}
    if key in directions:
        return bool(directions[key])
    metric = _metric_index(payload).get(key)
    return metric.get("default_high_good") is not False if metric else True


def mirror_score(
    peer: dict, keys: list[str], weights: dict[str, int], directions: dict[str, bool]
) -> dict:
    """One ticker's weighted-average percentile over the metrics it actually has.

    Metrics the company lacks are excluded from ITS budget (plan §7) instead of
    counted as zero, so a data gap never reads as a bad number. With full
    coverage the divisor is the budget, which is the §7 formula exactly.
    """
    total = 0.0
    weight_sum = 0
    available: list[str] = []
    for key in keys:
        pct = mirror_percentile(peer, key, directions[key])
        if pct is None:
            continue
        available.append(key)
        total += weights[key] * pct
        weight_sum += weights[key]
    return {
        "available": available,
        "weight_sum": weight_sum,
        "score": total / weight_sum if weight_sum > 0 else None,
    }


def mirror_rank(payload: dict, state: dict) -> dict:
    """Coverage, ranking and the two tie layers (plan §7)."""
    cfg = mirror_config(payload)
    keys = mirror_active_keys(payload, state)
    directions = {key: mirror_direction(payload, state, key) for key in keys}
    weights = {
        key: _clamp_int(
            mirror_round_half_up(_number_or((state.get("weights") or {}).get(key), 0)),
            0,
            cfg["budget"],
        )
        for key in keys
    }
    ranked: list[dict] = []
    unranked: list[dict] = []
    subject_detail = None
    for peer in payload.get("peers") or []:
        if not peer or not peer.get("ticker"):
            continue
        detail = mirror_score(peer, keys, weights, directions)
        fraction = len(detail["available"]) / len(keys) if keys else 0
        covered = len(detail["available"]) >= 1 and fraction >= cfg["min_coverage"] - EPS
        entry = {
            "ticker": peer["ticker"],
            "detail_url": peer.get("detail_url") or None,
            "available": len(detail["available"]),
            "active": len(keys),
        }
        if covered and detail["score"] is not None:
            entry["score"] = detail["score"]
            ranked.append(entry)
        else:
            entry["note"] = (
                "has none of your weighted metrics"
                if covered
                else "has "
                + mirror_format_number(len(detail["available"]), 0)
                + " of your "
                + mirror_format_number(len(keys), 0)
                + " metrics"
            )
            unranked.append(entry)
        if peer["ticker"] == payload.get("subject"):
            subject_detail = detail
    ranked.sort(key=lambda entry: (-entry["score"], entry["ticker"]))
    unranked.sort(key=lambda entry: entry["ticker"])
    counts: dict[float, int] = {}
    for index, entry in enumerate(ranked):
        entry["rank"] = index + 1
        entry["display_score"] = mirror_round_to(entry["score"], 1)
        counts[entry["display_score"]] = counts.get(entry["display_score"], 0) + 1
    for entry in ranked:
        entry["tied"] = counts[entry["display_score"]] > 1
    return {
        "keys": keys,
        "weights": weights,
        "directions": directions,
        "config": cfg,
        "ranked": ranked,
        "unranked": unranked,
        "subject_detail": subject_detail,
    }


def mirror_contributions(payload: dict, model: dict) -> dict:
    subject = None
    for peer in payload.get("peers") or []:
        if peer and peer.get("ticker") == payload.get("subject"):
            subject = peer
    if subject is None:
        return {"items": [], "missing": []}
    index = _metric_index(payload)
    items: list[dict] = []
    missing: list[dict] = []
    raws: list[float] = []
    for key in model["keys"]:
        pct = mirror_percentile(subject, key, model["directions"][key])
        metric = index.get(key)
        label = metric.get("label") if metric and metric.get("label") else key
        if pct is None:
            missing.append({"key": key, "label": label})
            continue
        raw = model["weights"][key] * ((pct - 50) / 50)
        raws.append(raw)
        items.append(
            {
                "key": key,
                "label": label,
                "percentile": mirror_round_to(pct, 1),
                "weight": model["weights"][key],
                "contribution": mirror_round_to(raw, 1),
            }
        )
    max_abs = max((abs(raw) for raw in raws), default=0.0)
    for item, raw in zip(items, raws):
        item["share"] = mirror_round_to(abs(raw) / max_abs, 3) if max_abs > 0 else 0
        item["sign"] = "neg" if raw < 0 else "pos"
    items.sort(key=lambda item: (-abs(item["contribution"]), item["key"]))
    return {"items": items, "missing": missing}


def _subject_rank(ranked: list[dict], subject: str) -> int | None:
    for entry in ranked:
        if entry["ticker"] == subject:
            return entry["rank"]
    return None


def _blank_stability(cfg: dict) -> dict:
    return {
        "warning": False,
        "key": None,
        "label": None,
        "positions": 0,
        "shift_points": cfg["shift_points"],
        "message": None,
    }


def mirror_stability(payload: dict, state: dict) -> dict:
    """Shift each active weight by +/- the configured points and watch the rank."""
    cfg = mirror_config(payload)
    model = mirror_rank(payload, state)
    base_rank = _subject_rank(model["ranked"], payload.get("subject"))
    if base_rank is None or not model["keys"]:
        return _blank_stability(cfg)
    worst: dict | None = None
    for key in model["keys"]:
        for delta in (cfg["shift_points"], -cfg["shift_points"]):
            target = _clamp_int(model["weights"][key] + delta, 0, cfg["budget"])
            if target == model["weights"][key]:
                continue
            probe_state = {
                "weights": mirror_renormalize(model["weights"], key, target, cfg["budget"]),
                "directions": model["directions"],
            }
            probe_rank = _subject_rank(mirror_rank(payload, probe_state)["ranked"], payload["subject"])
            if probe_rank is None:
                continue
            moved = abs(probe_rank - base_rank)
            if (
                worst is None
                or moved > worst["positions"]
                or (moved == worst["positions"] and key < worst["key"])
            ):
                worst = {"key": key, "positions": moved}
    if not worst or worst["positions"] <= cfg["alert_positions"]:
        return _blank_stability(cfg)
    metric = _metric_index(payload).get(worst["key"])
    label = metric.get("label") if metric and metric.get("label") else worst["key"]
    return {
        "warning": True,
        "key": worst["key"],
        "label": label,
        "positions": worst["positions"],
        "shift_points": cfg["shift_points"],
        "message": (
            "Shifting '"
            + label
            + "' by "
            + mirror_format_number(cfg["shift_points"], 0)
            + " points moves the rank by "
            + mirror_format_number(worst["positions"], 0)
            + (" place" if worst["positions"] == 1 else " places")
            + " — treat this ordering as fragile."
        ),
    }


def mirror_encode_state(payload: dict, state: dict) -> str:
    cfg = mirror_config(payload)
    parts = []
    for key in mirror_active_keys(payload, state):
        points = _clamp_int(
            mirror_round_half_up(_number_or((state.get("weights") or {}).get(key), 0)),
            0,
            cfg["budget"],
        )
        parts.append(f"{key}:{points}:{'h' if mirror_direction(payload, state, key) else 'l'}")
    return ",".join(parts)


def mirror_parse_state(payload: dict, raw: str | None) -> dict:
    cfg = mirror_config(payload)
    index = _metric_index(payload)
    weights: dict[str, int] = {}
    directions: dict[str, bool] = {}
    order: list[str] = []
    for entry in (raw or "").split(",") if raw else []:
        bits = entry.split(":")
        if len(bits) != 3:
            continue
        key = bits[0]
        if key not in index or not _selectable(index[key]) or key in weights:
            continue
        if not re.fullmatch(r"[0-9]+", bits[1]) or bits[2] not in ("h", "l"):
            continue
        weights[key] = _clamp_int(int(bits[1]), 0, cfg["budget"])
        directions[key] = bits[2] == "h"
        order.append(key)
    if not order:
        return {"weights": {}, "directions": {}}
    total = sum(weights[key] for key in order)
    if total != cfg["budget"]:
        raws = [
            (weights[key] / total) * cfg["budget"] if total > 0 else cfg["budget"] / len(order)
            for key in order
        ]
        weights = mirror_apportion(order, raws, cfg["budget"])
    return {"weights": weights, "directions": directions}


def _encode_uri_component(value: str) -> str:
    """`encodeURIComponent`: everything but A-Za-z0-9 and -_.!~*'() is escaped."""
    return quote(str(value), safe="!*'()")


def mirror_with_param(href: str, name: str, value: str) -> str:
    """Replace one query parameter and leave every other one exactly as it was."""
    target = href if isinstance(href, str) else ""
    hash_part = ""
    hash_at = target.find("#")
    if hash_at >= 0:
        hash_part = target[hash_at:]
        target = target[:hash_at]
    query_at = target.find("?")
    base = target[:query_at] if query_at >= 0 else target
    query = target[query_at + 1 :] if query_at >= 0 else ""
    kept = []
    for part in query.split("&") if query else []:
        if not part:
            continue
        equals = part.find("=")
        if (part[:equals] if equals >= 0 else part) == name:
            continue
        kept.append(part)
    if value:
        kept.append(name + "=" + _encode_uri_component(value))
    return base + ("?" + "&".join(kept) if kept else "") + hash_part


def mirror_apply_step(payload: dict, state: dict, step: dict) -> dict:
    """One user action. Guards live here: an unavailable metric never activates."""
    cfg = mirror_config(payload)
    index = _metric_index(payload)
    nxt = {
        "weights": dict(state.get("weights") or {}),
        "directions": dict(state.get("directions") or {}),
    }
    action = (step or {}).get("action")
    if not action:
        return nxt
    if action == "reset":
        return {"weights": {}, "directions": {}}
    key = step.get("key")
    metric = index.get(key)
    active = key in nxt["weights"]
    if metric is None:
        return nxt
    if action == "activate":
        if not _selectable(metric) or active:
            return nxt
        nxt["weights"] = mirror_activate(nxt["weights"], key, cfg["budget"])
    elif action == "deactivate":
        if not active:
            return nxt
        nxt["weights"] = mirror_deactivate(nxt["weights"], key, cfg["budget"])
    elif action == "set_weight":
        if not active:
            return nxt
        nxt["weights"] = mirror_renormalize(
            nxt["weights"], key, _number_or(step.get("points"), 0), cfg["budget"]
        )
    elif action == "flip_direction":
        if not _selectable(metric):
            return nxt
        nxt["directions"][key] = not mirror_direction(payload, state, key)
    return nxt


def mirror_evaluate(payload: dict, state: dict) -> dict:
    """The whole result, in the shape `evaluate()` returns in the browser."""
    cfg = mirror_config(payload)
    keys = mirror_active_keys(payload, state)
    if not keys:
        return {
            "status": "empty",
            "message": None,
            "weights": {},
            "keys": [],
            "subject_score": None,
            "subject_rank": None,
            "subject_note": None,
            "ranked_count": 0,
            "ranked": [],
            "unranked": [],
            "contributions": [],
            "missing": [],
            "stability": _blank_stability(cfg),
            "url_state": "",
            "announcement": None,
        }
    model = mirror_rank(payload, state)
    url_state = mirror_encode_state(payload, state)
    if len(model["ranked"]) < cfg["min_peers"]:
        return {
            "status": "not_enough_peers",
            "message": (
                "Not enough comparable miners — "
                + mirror_format_number(len(model["ranked"]), 0)
                + " have enough of your metrics and at least "
                + mirror_format_number(cfg["min_peers"], 0)
                + " are needed."
            ),
            "weights": model["weights"],
            "keys": keys,
            "subject_score": None,
            "subject_rank": None,
            "subject_note": None,
            "ranked_count": len(model["ranked"]),
            "ranked": [],
            "unranked": [],
            "contributions": [],
            "missing": [],
            "stability": _blank_stability(cfg),
            "url_state": url_state,
            "announcement": "Not enough comparable miners for this combination of metrics.",
        }
    subject = payload.get("subject")
    subject_rank = _subject_rank(model["ranked"], subject)
    subject_score = None
    subject_note = None
    contributions = {"items": [], "missing": []}
    stability = _blank_stability(cfg)
    if subject_rank is not None:
        for entry in model["ranked"]:
            if entry["ticker"] == subject:
                subject_score = entry["display_score"]
        contributions = mirror_contributions(payload, model)
        stability = mirror_stability(payload, state)
    else:
        for entry in model["unranked"]:
            if entry["ticker"] == subject:
                subject_note = entry["note"]
    if subject_rank is not None:
        announcement = (
            "Score "
            + mirror_format_number(subject_score, 1)
            + ", rank "
            + mirror_format_number(subject_rank, 0)
            + " of "
            + mirror_format_number(len(model["ranked"]), 0)
        )
    else:
        announcement = f"{subject} is not ranked — " + (
            subject_note or "not enough of your metrics"
        )
    return {
        "status": "ok",
        "message": None,
        "weights": model["weights"],
        "keys": keys,
        "subject_score": subject_score,
        "subject_rank": subject_rank,
        "subject_note": subject_note,
        "ranked_count": len(model["ranked"]),
        "ranked": model["ranked"],
        "unranked": model["unranked"],
        "contributions": contributions["items"],
        "missing": contributions["missing"],
        "stability": stability,
        "url_state": url_state,
        "announcement": announcement,
    }


# ----------------------------------------------------------------- the sizing


def mirror_price_band(current_price: Any) -> dict | None:
    """The plan's $0.05 / $0.5 / $1 step bands, anchored ON the current price."""
    raw = _number_or(current_price, 0)
    if not math.isfinite(raw) or raw <= 0:
        return None
    step = 0.05 if raw < 10 else (0.5 if raw < 100 else 1)
    decimals = 2 if step < 1 else 0
    price = mirror_round_to(raw, decimals)
    if price <= 0:
        return None
    steps = math.ceil((price * 0.6) / step - EPS)
    if steps < 1:
        steps = 1
    low = mirror_round_to(price - steps * step, decimals)
    while low <= 0 and steps > 1:
        steps -= 1
        low = mirror_round_to(price - steps * step, decimals)
    if low <= 0:
        low = price
    return {
        "min": low,
        "max": mirror_round_to(price + steps * step, decimals),
        "step": step,
        "decimals": decimals,
        "default": price,
    }


def _contracts(payload: dict) -> list[dict]:
    return list(payload.get("contracts") or [])


def _find_contract(payload: dict, contract_id: str | None) -> dict | None:
    contracts = _contracts(payload)
    for contract in contracts:
        if contract and contract.get("id") == contract_id:
            return contract
    return contracts[0] if contracts else None


def _is_put(contract: dict) -> bool:
    return str(contract.get("option_type") or "").upper() == "P"


def mirror_intrinsic(contract: dict, share_price: float) -> float:
    strike = _number_or(contract.get("strike"), 0)
    value = strike - share_price if _is_put(contract) else share_price - strike
    return value if value > 0 else 0


def mirror_break_even(contract: dict) -> float:
    strike = _number_or(contract.get("strike"), 0)
    ask = _number_or(contract.get("ask"), 0)
    return mirror_round_to(strike - ask if _is_put(contract) else strike + ask, 2)


def _row_label(row: dict) -> str:
    bits = []
    if row.get("pct") is not None:
        bits.append(("+" if row["pct"] > 0 else "") + mirror_format_number(row["pct"], 0) + "%")
    if row.get("break_even"):
        bits.append("break-even")
    if row.get("at_price"):
        bits.append("at your price")
    return " · ".join(bits)


def mirror_ladder(
    payload: dict, contract: dict, share_price: float | None, contracts: int, premium: float
) -> list[dict]:
    """-30/-20/-10%, break-even, +10/+20/+30% and the slider price, ascending."""
    base = _number_or(payload.get("current_price"), 0)
    multiplier = _number_or(contract.get("multiplier"), 100)
    rows: list[dict] = []

    def upsert(price: float, kind: str, pct: float | None) -> None:
        rounded = mirror_round_to(price, 2)
        for row in rows:
            if row["share_price"] == rounded:
                if kind == "break_even":
                    row["break_even"] = True
                if kind == "at_price":
                    row["at_price"] = True
                if pct is not None and row["pct"] is None:
                    row["pct"] = pct
                return
        rows.append(
            {
                "share_price": rounded,
                "pct": pct,
                "break_even": kind == "break_even",
                "at_price": kind == "at_price",
            }
        )

    for offset in LADDER_OFFSETS:
        upsert(base * (1 + offset), "pct", mirror_round_to(offset * 100, 0))
    upsert(mirror_break_even(contract), "break_even", None)
    if share_price is not None and math.isfinite(float(share_price)):
        upsert(float(share_price), "at_price", None)
    rows.sort(key=lambda row: row["share_price"])
    for row in rows:
        intrinsic = mirror_round_to(mirror_intrinsic(contract, row["share_price"]), 2)
        row["intrinsic"] = intrinsic
        row["value"] = (
            mirror_round_to(intrinsic * multiplier * contracts, 2) if contracts > 0 else None
        )
        row["net"] = (
            mirror_round_to(intrinsic * multiplier * contracts - premium, 2)
            if contracts > 0
            else None
        )
        row["label"] = _row_label(row)
    return rows


def _disabled_result(payload: dict, contract: dict | None, reason: str) -> dict:
    return {
        "ok": False,
        "reason": reason,
        "state": "disabled",
        "contract_id": contract.get("id") if contract else None,
        "option_type": ("P" if _is_put(contract) else "C") if contract else None,
        "label": (contract.get("label") or None) if contract else None,
        "strike": _number_or(contract.get("strike"), None) if contract else None,
        "ask": _number_or(contract.get("ask"), None) if contract else None,
        "multiplier": _number_or(contract.get("multiplier"), None) if contract else None,
        "currency": payload.get("currency") or "USD",
        "cost_per_contract": None,
        "break_even": None,
        "price": None,
        "price_band": mirror_price_band(payload.get("current_price")),
        "footnote": FOOTNOTE,
        "contracts": 0,
        "capped": False,
        "premium": None,
        "ladder": [],
        "contracts_line": reason,
        "announcement": reason,
    }


def mirror_sizing(
    payload: dict, contract_id: str | None, budget: Any, share_price: Any
) -> dict:
    """budget -> whole contracts -> intrinsic-only value at expiry (plan §9.4)."""
    band = mirror_price_band(payload.get("current_price"))
    contract = _find_contract(payload, contract_id)
    currency = payload.get("currency") or "USD"
    if contract is None:
        return _disabled_result(payload, None, "No contract selected.")
    ask = _js_parse_float(contract.get("ask"))
    if contract.get("quote_ok") is False or ask is None or ask <= 0:
        reason = (
            "This contract cannot be sized: " + contract["quote_reason"] + "."
            if contract.get("quote_reason")
            else "This contract cannot be sized: no usable ask price."
        )
        return _disabled_result(payload, contract, reason)
    multiplier = _number_or(contract.get("multiplier"), 100)
    max_contracts = _number_or(payload.get("max_contracts"), 10000)
    cost_per_contract = mirror_round_to(ask * multiplier, 2)
    break_even = mirror_break_even(contract)
    price = None if share_price is None else _js_parse_float(share_price)
    if price is None and band:
        price = band["default"]
    money = None if budget is None or budget == "" else _js_parse_float(budget)

    common = {
        "ok": True,
        "reason": None,
        "contract_id": contract.get("id"),
        "option_type": "P" if _is_put(contract) else "C",
        "label": contract.get("label") or None,
        "strike": _number_or(contract.get("strike"), 0),
        "ask": ask,
        "multiplier": multiplier,
        "currency": currency,
        "cost_per_contract": cost_per_contract,
        "break_even": break_even,
        "price": None if price is None else mirror_round_to(price, 2),
        "price_band": band,
        "footnote": FOOTNOTE,
    }

    if money is None or money < 0:
        common["state"] = "idle"
        common["contracts"] = 0
        common["capped"] = False
        common["premium"] = None
        common["ladder"] = mirror_ladder(payload, contract, price, 0, 0)
        common["contracts_line"] = "Enter a budget to size a position."
        common["announcement"] = common["contracts_line"]
        return common

    # Divided in cents, not in binary: rounding the cost above is what does the
    # work, and EPS is the second net if that rounding ever moves.
    raw = math.floor(money / cost_per_contract + EPS) if cost_per_contract > 0 else 0
    capped = raw > max_contracts
    contracts = int(max_contracts) if capped else int(raw)
    premium = mirror_round_to(cost_per_contract * contracts, 2)
    common["contracts"] = contracts
    common["capped"] = capped
    common["premium"] = premium
    common["ladder"] = mirror_ladder(payload, contract, price, contracts, premium)

    if contracts <= 0:
        common["state"] = "zero"
        common["contracts_line"] = "0 contracts — one contract costs " + mirror_format_money(
            cost_per_contract, currency
        )
        common["announcement"] = common["contracts_line"]
        return common
    common["state"] = "sized"
    noun = " contract" if contracts == 1 else " contracts"
    common["contracts_line"] = (
        mirror_format_number(contracts, 0)
        + noun
        + " · "
        + mirror_format_money(premium, currency)
        + " premium · break-even "
        + mirror_format_money(break_even, currency)
        + (
            " · capped at " + mirror_format_number(max_contracts, 0) + " contracts"
            if capped
            else ""
        )
    )
    at_price = None
    for row in common["ladder"]:
        if row["at_price"]:
            at_price = row
    common["announcement"] = (
        mirror_format_number(contracts, 0)
        + noun
        + ", net "
        + (mirror_format_money(at_price["net"], currency) if at_price else "n/a")
        + " at "
        + mirror_format_money(common["price"], currency)
    )
    return common


# ---------------------------------------------------------------- the harness

NODE_DRIVER = """
"use strict";
var fs = require("fs");
var path = require("path");
var staticDir = process.argv[2];
require(path.join(staticDir, "score-builder.js"));
require(path.join(staticDir, "option-sizing.js"));
var job = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
var SB = globalThis.GVScoreBuilder;
var OS = globalThis.GVOptionSizing;
if (!SB || !OS) { throw new Error("modules did not export their engines"); }
var out = { score_builder: [], option_sizing: [] };
job.score_builder.forEach(function (scenario) {
  var state = { weights: {}, directions: {} };
  var results = [];
  scenario.steps.forEach(function (step) {
    state = SB.applyStep(scenario.payload, state, step);
    results.push(SB.evaluate(scenario.payload, state));
  });
  out.score_builder.push(results);
});
job.option_sizing.forEach(function (scenario) {
  var results = [];
  scenario.steps.forEach(function (step) {
    results.push(
      OS.computeSizing(
        scenario.payload,
        step.contract_id,
        step.budget === undefined ? null : step.budget,
        step.price === undefined ? null : step.price
      )
    );
  });
  out.option_sizing.push({
    price_band: OS.priceBand(scenario.payload.current_price),
    steps: results
  });
});
out.url_states = [];
(job.url_cases || []).forEach(function (item) {
  var parsed = SB.parseState(item.payload, item.raw);
  out.url_states.push({ state: parsed, encoded: SB.encodeState(item.payload, parsed) });
});
out.links = (job.link_cases || []).map(function (item) {
  return SB.withParam(item.href, item.name, item.value);
});
process.stdout.write(JSON.stringify(out));
"""


NO_MARKUP_DRIVER = """
"use strict";
var path = require("path");
var staticDir = process.argv[2];
var warnings = [];
function load(payloadText) {
  warnings.length = 0;
  global.window = {
    addEventListener: function () {},
    matchMedia: function () { return { matches: false }; },
    setTimeout: setTimeout,
    clearTimeout: clearTimeout,
    console: { warn: function (message) { warnings.push(String(message)); } },
    location: { search: "", pathname: "/ticker/NEM", hash: "" },
    history: { replaceState: function () {} }
  };
  global.document = {
    readyState: "complete",
    getElementById: function (id) {
      if (payloadText !== null && /payload$/.test(id)) return { textContent: payloadText };
      return null;
    },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    addEventListener: function () {}
  };
  ["score-builder.js", "option-sizing.js"].forEach(function (name) {
    var file = require.resolve(path.join(staticDir, name));
    delete require.cache[file];
    require(file);
  });
  return {
    exported: !!(global.window.GVScoreBuilder && global.window.GVOptionSizing),
    warnings: warnings.slice()
  };
}
var out = {};
["absent", "malformed"].forEach(function (mode) {
  try {
    out[mode] = load(mode === "absent" ? null : "{not json");
  } catch (error) {
    out[mode] = { threw: String((error && error.message) || error) };
  }
});
process.stdout.write(JSON.stringify(out));
"""


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _scenario(fixture: dict, name: str) -> dict:
    return next(item for item in fixture["scenarios"] if item["name"] == name)


def _replay_score(scenario: dict) -> list[dict]:
    state = {"weights": {}, "directions": {}}
    out = []
    for step in scenario["steps"]:
        state = mirror_apply_step(scenario["payload"], state, step)
        out.append(mirror_evaluate(scenario["payload"], state))
    return out


def _run_node(job: dict, tmp_path: Path) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - depends on the machine, not the code
        pytest.skip("node is not on PATH; the real-JS half of the parity check needs it")
    driver = tmp_path / "parity_driver.js"
    driver.write_text(NODE_DRIVER, encoding="utf-8")
    job_file = tmp_path / "job.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    result = subprocess.run(
        [node, str(driver), str(STATIC_DIR), str(job_file)],
        capture_output=True,
        text=True,
        # node writes UTF-8; without this Windows decodes the pipe as cp1252 and
        # the "·" and "—" in the rendered sentences come back mangled.
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"node driver failed:\n{result.stderr}"
    return json.loads(result.stdout)


# ------------------------------------------------------------------- the tests


def test_fixtures_and_modules_exist() -> None:
    for path in (SCORE_JS, SIZING_JS, SCORE_FIXTURE, SIZING_FIXTURE):
        assert path.is_file(), f"missing {path}"


def test_modules_cite_their_parity_fixture() -> None:
    """A module that stops naming its fixture is a module nobody will re-pin."""
    assert "tests/fixtures/score_builder_parity.json" in SCORE_JS.read_text(encoding="utf-8")
    assert "tests/fixtures/option_sizing_parity.json" in SIZING_JS.read_text(encoding="utf-8")


def test_score_builder_fixture_matches_mirror() -> None:
    fixture = _load(SCORE_FIXTURE)
    assert fixture["scenarios"], "fixture has no scenarios"
    for scenario in fixture["scenarios"]:
        actual = _replay_score(scenario)
        for index, step in enumerate(scenario["steps"]):
            assert actual[index] == step["expected"], (
                f"{scenario['name']} step {index} ({step['action']} {step.get('key')}) "
                "does not match the mirror"
            )


def test_url_state_fixture_matches_mirror() -> None:
    fixture = _load(SCORE_FIXTURE)
    assert fixture["url_cases"], "fixture has no URL cases"
    for case in fixture["url_cases"]:
        payload = _scenario(fixture, case["scenario"])["payload"]
        parsed = mirror_parse_state(payload, case["raw"])
        assert parsed["weights"] == case["expected_weights"], case["raw"]
        assert parsed["directions"] == case["expected_directions"], case["raw"]
        assert mirror_encode_state(payload, parsed) == case["expected_encoded"], case["raw"]
    for case in fixture["link_cases"]:
        assert mirror_with_param(case["href"], case["name"], case["value"]) == case["expected"]


def test_option_sizing_fixture_matches_mirror() -> None:
    fixture = _load(SIZING_FIXTURE)
    assert fixture["scenarios"], "fixture has no scenarios"
    for scenario in fixture["scenarios"]:
        assert scenario["price_band"] == mirror_price_band(scenario["payload"]["current_price"])
        for index, step in enumerate(scenario["steps"]):
            actual = mirror_sizing(
                scenario["payload"], step["contract_id"], step.get("budget"), step.get("price")
            )
            assert actual == step["expected"], (
                f"{scenario['name']} step {index} ({step['contract_id']}) "
                "does not match the mirror"
            )


def test_real_javascript_matches_the_python_mirror(tmp_path: Path) -> None:
    """The load-bearing half: run the actual browser modules and compare."""
    score = _load(SCORE_FIXTURE)
    sizing = _load(SIZING_FIXTURE)
    job = {
        "score_builder": [
            {"payload": scenario["payload"], "steps": scenario["steps"]}
            for scenario in score["scenarios"]
        ],
        "option_sizing": [
            {"payload": scenario["payload"], "steps": scenario["steps"]}
            for scenario in sizing["scenarios"]
        ],
        "url_cases": [
            {"payload": _scenario(score, case["scenario"])["payload"], "raw": case["raw"]}
            for case in score["url_cases"]
        ],
        "link_cases": score["link_cases"],
    }
    produced = _run_node(job, tmp_path)
    for index, case in enumerate(score["url_cases"]):
        payload = _scenario(score, case["scenario"])["payload"]
        parsed = mirror_parse_state(payload, case["raw"])
        assert produced["url_states"][index]["state"] == parsed, (
            f"score-builder.js parses {case['raw']!r} differently from the mirror"
        )
        assert produced["url_states"][index]["encoded"] == mirror_encode_state(payload, parsed)
    for index, case in enumerate(score["link_cases"]):
        assert produced["links"][index] == mirror_with_param(
            case["href"], case["name"], case["value"]
        ), f"score-builder.js rewrites {case['href']!r} differently from the mirror"
    for index, scenario in enumerate(score["scenarios"]):
        expected = _replay_score(scenario)
        actual = produced["score_builder"][index]
        for step_index, step in enumerate(scenario["steps"]):
            assert actual[step_index] == expected[step_index], (
                f"score-builder.js disagrees with the mirror in {scenario['name']} "
                f"at step {step_index} ({step['action']} {step.get('key')})"
            )
    for index, scenario in enumerate(sizing["scenarios"]):
        actual = produced["option_sizing"][index]
        assert actual["price_band"] == mirror_price_band(scenario["payload"]["current_price"])
        for step_index, step in enumerate(scenario["steps"]):
            expected = mirror_sizing(
                scenario["payload"], step["contract_id"], step.get("budget"), step.get("price")
            )
            assert actual["steps"][step_index] == expected, (
                f"option-sizing.js disagrees with the mirror in {scenario['name']} "
                f"at step {step_index} ({step['contract_id']})"
            )


def test_modules_no_op_without_their_markup(tmp_path: Path) -> None:
    """Plan §9.5: a page that does not render a module's markup must be unharmed.

    Both modules ship on every ticker page, including ones with no options
    section and no peer cohort. Landing on such a page must produce silence, not
    a console full of exceptions — and a payload that fails to parse must warn
    exactly once per module rather than on every interaction.
    """
    node = shutil.which("node")
    if not node:  # pragma: no cover - depends on the machine, not the code
        pytest.skip("node is not on PATH; this check runs the real modules")
    driver = tmp_path / "no_markup.js"
    driver.write_text(NO_MARKUP_DRIVER, encoding="utf-8")
    result = subprocess.run(
        [node, str(driver), str(STATIC_DIR)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, f"node driver failed:\n{result.stderr}"
    produced = json.loads(result.stdout)
    # No markup at all: no exception, no console noise, engines still exported.
    assert "threw" not in produced["absent"], produced["absent"]
    assert produced["absent"]["exported"] is True
    assert produced["absent"]["warnings"] == []
    # A payload that is not JSON: one warning per module, then silence.
    assert "threw" not in produced["malformed"], produced["malformed"]
    assert produced["malformed"]["exported"] is True
    assert len(produced["malformed"]["warnings"]) == 2, produced["malformed"]["warnings"]


def test_fixture_covers_the_cases_it_is_supposed_to_prove() -> None:
    """Guard against a fixture that quietly stops exercising the hard branches."""
    score = _load(SCORE_FIXTURE)
    seen = {
        "tie": False,
        "unranked": False,
        "partial_but_ranked": False,
        "stability_on": False,
        "stability_off": False,
        "not_enough_peers": False,
        "subject_unranked": False,
        "unavailable_metric_ignored": False,
        "empty": False,
    }
    for scenario in score["scenarios"]:
        for step in scenario["steps"]:
            expected = step["expected"]
            if any(entry["tied"] for entry in expected["ranked"]):
                seen["tie"] = True
            if expected["unranked"]:
                seen["unranked"] = True
            for entry in expected["ranked"]:
                if entry["available"] < entry["active"]:
                    seen["partial_but_ranked"] = True
            if expected["stability"]["warning"]:
                seen["stability_on"] = True
            elif expected["status"] == "ok" and expected["subject_rank"] is not None:
                seen["stability_off"] = True
            if expected["status"] == "not_enough_peers":
                seen["not_enough_peers"] = True
            if expected["status"] == "ok" and expected["subject_rank"] is None:
                seen["subject_unranked"] = True
            if expected["status"] == "empty":
                seen["empty"] = True
            if step["action"] == "activate" and step.get("key") and step["key"] not in expected["keys"]:
                seen["unavailable_metric_ignored"] = True
    missing = [name for name, hit in seen.items() if not hit]
    assert not missing, f"the score-builder fixture no longer covers: {missing}"

    sizing = _load(SIZING_FIXTURE)
    kinds = {"disabled": False, "zero": False, "idle": False, "sized": False, "capped": False}
    for scenario in sizing["scenarios"]:
        for step in scenario["steps"]:
            expected = step["expected"]
            kinds[expected["state"]] = True
            if expected["capped"]:
                kinds["capped"] = True
    missing = [name for name, hit in kinds.items() if not hit]
    assert not missing, f"the option-sizing fixture no longer covers: {missing}"


# --- hand-derived anchors: values worked out independently of the mirror ------


def test_hand_derived_weight_budget_rules() -> None:
    budget = 100
    # One metric holds the whole budget.
    first = mirror_activate({}, "a", budget)
    assert first == {"a": 100}
    # Two metrics split it evenly.
    second = mirror_activate(first, "b", budget)
    assert second == {"a": 50, "b": 50}
    # A third takes an equal share; the other two keep their proportions.
    third = mirror_activate(second, "c", budget)
    assert third == {"a": 34, "b": 33, "c": 33}
    assert sum(third.values()) == budget
    # Setting one weight renormalizes the others proportionally: 60 points to
    # split, a gets 34/67 * 60 = 30.45 and b gets 33/67 * 60 = 29.55, so the
    # single leftover point goes to b's larger remainder — not to the larger
    # weight. That is what "largest remainder" means, and it is why the total
    # is exactly 100 rather than 99.
    moved = mirror_renormalize(third, "c", 40, budget)
    assert moved == {"a": 30, "b": 30, "c": 40}
    assert sum(moved.values()) == budget
    # Deactivating returns the points proportionally.
    dropped = mirror_deactivate(moved, "c", budget)
    assert sum(dropped.values()) == budget
    assert dropped == {"a": 50, "b": 50}
    # Dropping to one metric hands it the whole budget back.
    assert mirror_deactivate(dropped, "b", budget) == {"a": 100}
    assert mirror_deactivate({"a": 100}, "a", budget) == {}


def test_hand_derived_weights_always_total_the_budget() -> None:
    """Largest-remainder rounding must never lose or invent a point."""
    budget = 100
    weights: dict[str, int] = {}
    keys = [f"m{index:02d}" for index in range(19)]
    for key in keys:
        weights = mirror_activate(weights, key, budget)
        assert sum(weights.values()) == budget, f"activating {key} broke the budget"
    for value in (0, 1, 33, 67, 99, 100):
        probe = mirror_renormalize(weights, keys[0], value, budget)
        assert sum(probe.values()) == budget
        assert probe[keys[0]] == value
    for key in keys[:-1]:
        weights = mirror_deactivate(weights, key, budget)
        assert sum(weights.values()) == budget, f"deactivating {key} broke the budget"


def test_hand_derived_direction_reads_the_payload_never_inverts() -> None:
    """100 - p is inexact when percentiles tie, so both orientations are given."""
    peer = {"ticker": "X", "values": {"m": {"pct_high_good": 92.0, "pct_low_good": 9.0}}}
    assert mirror_percentile(peer, "m", True) == 92.0
    assert mirror_percentile(peer, "m", False) == 9.0  # not 8.0
    assert mirror_percentile(peer, "missing", True) is None
    assert mirror_percentile({"ticker": "Y", "values": {"m": None}}, "m", True) is None


def test_hand_derived_score_is_a_weighted_average_percentile() -> None:
    keys = ["a", "b"]
    weights = {"a": 70, "b": 30}
    directions = {"a": True, "b": True}
    peer = {
        "ticker": "X",
        "values": {
            "a": {"pct_high_good": 80.0, "pct_low_good": 20.0},
            "b": {"pct_high_good": 40.0, "pct_low_good": 60.0},
        },
    }
    # (70*80 + 30*40) / 100 = 68.0
    assert mirror_score(peer, keys, weights, directions)["score"] == 68.0
    # A missing metric is excluded from this company's budget, not zero-filled:
    # a 70-weight metric alone scores 80, not 56.
    partial = {"ticker": "Y", "values": {"a": {"pct_high_good": 80.0, "pct_low_good": 20.0}}}
    detail = mirror_score(partial, keys, weights, directions)
    assert detail["score"] == 80.0
    assert detail["weight_sum"] == 70
    assert detail["available"] == ["a"]


def test_hand_derived_coverage_and_tie_rules() -> None:
    fixture = _load(SCORE_FIXTURE)
    scenario = next(item for item in fixture["scenarios"] if item["name"] == "main")
    payload = scenario["payload"]
    state = {"weights": {"up_beta_core": 50, "down_beta_core": 50}, "directions": {}}
    view = mirror_evaluate(payload, state)
    # 3/5 == 0.6 passes; 1/2 == 0.5 does not.
    assert view["ranked_count"] == 11
    assert [entry["ticker"] for entry in view["unranked"]] == ["LOWCOV"]
    assert view["unranked"][0]["note"] == "has 1 of your 2 metrics"
    # NEM: (50*72.0 + 50*70.0) / 100 = 71.0
    assert view["subject_score"] == 71.0
    assert view["subject_rank"] == 2
    tied = sorted(entry["ticker"] for entry in view["ranked"] if entry["tied"])
    assert tied == ["BBB", "CCC"]  # both 60.0, ordered by ticker ascending
    assert [entry["rank"] for entry in view["ranked"][:2]] == [1, 2]
    assert view["announcement"] == "Score 71.0, rank 2 of 11"


def test_hand_derived_contribution_formula() -> None:
    fixture = _load(SCORE_FIXTURE)
    scenario = next(item for item in fixture["scenarios"] if item["name"] == "main")
    payload = scenario["payload"]
    state = {"weights": {"up_beta_core": 50, "down_beta_core": 50}, "directions": {}}
    view = mirror_evaluate(payload, state)
    by_key = {item["key"]: item for item in view["contributions"]}
    # 50 * (72 - 50) / 50 = 22.0 ; 50 * (70 - 50) / 50 = 20.0
    assert by_key["up_beta_core"]["contribution"] == 22.0
    assert by_key["down_beta_core"]["contribution"] == 20.0
    assert by_key["up_beta_core"]["sign"] == "pos"
    assert by_key["up_beta_core"]["share"] == 1.0
    # 20/22 = 0.909..., rounded to three places
    assert by_key["down_beta_core"]["share"] == 0.909
    assert [item["key"] for item in view["contributions"]] == ["up_beta_core", "down_beta_core"]


def test_hand_derived_stability_warning_text() -> None:
    fixture = _load(SCORE_FIXTURE)
    scenario = next(item for item in fixture["scenarios"] if item["name"] == "stability")
    payload = scenario["payload"]
    state = {"weights": {"up_beta_core": 50, "ev_ebitda": 50}, "directions": {}}
    view = mirror_evaluate(payload, state)
    # Every miner scores exactly 50.0 at a 50/50 split, so the order is decided
    # by the tie-break alone — the most fragile ranking there is.
    assert view["subject_rank"] == 1
    assert all(entry["tied"] for entry in view["ranked"])
    assert view["stability"]["warning"] is True
    assert view["stability"]["key"] == "ev_ebitda"
    assert view["stability"]["message"] == (
        "Shifting 'EV/EBITDA' by 10 points moves the rank by 6 places "
        "— treat this ordering as fragile."
    )
    # A single metric carrying the whole budget cannot be shifted into trouble.
    steady = mirror_evaluate(payload, {"weights": {"up_beta_core": 100}, "directions": {}})
    assert steady["stability"]["warning"] is False
    assert steady["stability"]["message"] is None


def test_hand_derived_url_state_round_trip() -> None:
    fixture = _load(SCORE_FIXTURE)
    payload = _scenario(fixture, "main")["payload"]
    state = {
        "weights": {"up_beta_core": 60, "ev_ebitda": 40},
        "directions": {"up_beta_core": False},
    }
    encoded = mirror_encode_state(payload, state)
    # Catalog order, not alphabetical. up_beta_core carries the user's flip
    # (default higher-good, encoded 'l'); ev_ebitda was never touched and falls
    # back to its catalog default of lower-good.
    assert encoded == "up_beta_core:60:l,ev_ebitda:40:l"
    assert mirror_parse_state(payload, encoded) == {
        "weights": {"up_beta_core": 60, "ev_ebitda": 40},
        "directions": {"up_beta_core": False, "ev_ebitda": False},
    }
    # Hostile input: unknown key, malformed entry, bad direction, unavailable
    # metric, and points that do not add up.
    parsed = mirror_parse_state(
        payload,
        "not_a_metric:50:h,up_beta_core:xx:h,down_beta_core:10:x,survival_distance:50:h,"
        "up_beta_core:30:h,ev_ebitda:30:l",
    )
    assert parsed["weights"] == {"up_beta_core": 50, "ev_ebitda": 50}
    assert parsed["directions"] == {"up_beta_core": True, "ev_ebitda": False}
    assert mirror_parse_state(payload, "") == {"weights": {}, "directions": {}}
    assert mirror_parse_state(payload, None) == {"weights": {}, "directions": {}}


def test_hand_derived_unavailable_metric_can_never_be_activated() -> None:
    fixture = _load(SCORE_FIXTURE)
    payload = next(item for item in fixture["scenarios"] if item["name"] == "main")["payload"]
    state = {"weights": {"up_beta_core": 100}, "directions": {}}
    after = mirror_apply_step(
        payload, state, {"action": "activate", "key": "survival_distance"}
    )
    assert after["weights"] == {"up_beta_core": 100}
    assert mirror_evaluate(payload, after)["keys"] == ["up_beta_core"]


def test_hand_derived_number_formatting() -> None:
    assert mirror_format_number(1234567.891, 2) == "1,234,567.89"
    assert mirror_format_number(-240, 2) == "-240.00"  # ASCII '-', not U+2212
    assert "−" not in mirror_format_number(-240, 2)
    # Half away from zero, in both directions: Python's round() would give 2
    # and 2, and JavaScript's Math.round would give 3 and -2. Neither is used.
    assert mirror_format_number(2.5, 0) == "3"
    assert mirror_format_number(-2.5, 0) == "-3"
    assert mirror_format_number(0.5, 0) == "1"
    assert mirror_format_number(-0.001, 2) == "0.00"  # never "-0.00"
    assert mirror_format_number(float("inf"), 2) == "n/a"
    assert mirror_format_number(None, 2) == "n/a"
    assert mirror_format_money(-240.0, "USD") == "-$240.00"
    assert mirror_format_money(1020, "AUD") == "AUD 1,020.00"


def test_hand_derived_price_bands() -> None:
    """The plan's $0.05 / $0.5 / $1 bands, and the default really is the price."""
    cheap = mirror_price_band(4.2)
    assert cheap["step"] == 0.05
    assert cheap["default"] == 4.2
    assert cheap["min"] == 1.65 and cheap["max"] == 6.75  # +/-60% widened to whole steps
    assert (cheap["default"] - cheap["min"]) / cheap["step"] == pytest.approx(51.0)
    mid = mirror_price_band(12.34)
    assert mid["step"] == 0.5
    assert mid["default"] == 12.34
    assert mid["min"] == 4.84 and mid["max"] == 19.84
    dear = mirror_price_band(250)
    assert dear["step"] == 1 and dear["default"] == 250
    assert dear["min"] == 100 and dear["max"] == 400
    assert mirror_price_band(0) is None
    assert mirror_price_band(None) is None
    # The band never opens below zero.
    assert mirror_price_band(0.08)["min"] > 0


def test_hand_derived_sizing_math() -> None:
    fixture = _load(SIZING_FIXTURE)
    scenario = next(item for item in fixture["scenarios"] if item["name"] == "main")
    payload = scenario["payload"]
    # 0.85 * 100 = 85.00000000000001 in binary; 170 must still buy 2 contracts.
    exact = mirror_sizing(payload, "P-12-near_atm", 170, 12.34)
    assert exact["cost_per_contract"] == 85.0
    assert exact["contracts"] == 2
    assert exact["premium"] == 170.0
    # Break-even: puts strike - ask.
    assert exact["break_even"] == 11.15
    # Calls: strike + ask.
    call = mirror_sizing(payload, "C-13-near_atm", 1000, 12.34)
    assert call["break_even"] == 13.62
    assert call["contracts"] == 16  # floor(1000 / 62.00)
    assert call["premium"] == 992.0
    # Whole contracts only, and the shortfall says what one costs.
    short = mirror_sizing(payload, "P-12-near_atm", 50, 12.34)
    assert short["contracts"] == 0
    assert short["contracts_line"] == "0 contracts — one contract costs $85.00"
    # A crossed quote is never repaired with a mid price.
    crossed = mirror_sizing(payload, "P-15-crossed", 1000, 12.34)
    assert crossed["ok"] is False
    assert crossed["ladder"] == []
    assert crossed["contracts_line"] == (
        "This contract cannot be sized: crossed quote (bid above ask)."
    )


def test_hand_derived_ladder_rows() -> None:
    fixture = _load(SIZING_FIXTURE)
    payload = next(item for item in fixture["scenarios"] if item["name"] == "main")["payload"]
    view = mirror_sizing(payload, "P-12-near_atm", 1000, 10.5)
    prices = [row["share_price"] for row in view["ladder"]]
    assert prices == sorted(prices)
    # -30/-20/-10% of 12.34, break-even, the slider price, +10/+20/+30%.
    assert prices == [8.64, 9.87, 10.5, 11.11, 11.15, 13.57, 14.81, 16.04]
    labels = {row["share_price"]: row["label"] for row in view["ladder"]}
    assert labels[11.15] == "break-even"
    assert labels[10.5] == "at your price"
    assert labels[8.64] == "-30%"
    assert labels[13.57] == "+10%"
    by_price = {row["share_price"]: row for row in view["ladder"]}
    # 11 contracts at $85.00 = $935.00 premium.
    assert view["contracts"] == 11 and view["premium"] == 935.0
    # Intrinsic is the only value at expiry (Q34): max(12 - 10.50, 0) = 1.50.
    assert by_price[10.5]["intrinsic"] == 1.5
    assert by_price[10.5]["value"] == 1650.0  # 1.50 * 100 * 11
    assert by_price[10.5]["net"] == 715.0  # 1650 - 935
    # The break-even row nets exactly zero, which is what makes it break-even.
    assert by_price[11.15]["net"] == 0.0
    # Above the strike a put expires worthless and the loss is the whole premium.
    assert by_price[13.57]["intrinsic"] == 0
    assert by_price[13.57]["net"] == -935.0
    assert view["announcement"] == "11 contracts, net $715.00 at $10.50"
    assert "intrinsic value only" in view["footnote"]


def test_hand_derived_no_position_reports_no_outcome() -> None:
    fixture = _load(SIZING_FIXTURE)
    payload = next(item for item in fixture["scenarios"] if item["name"] == "main")["payload"]
    idle = mirror_sizing(payload, "P-12-near_atm", None, 12.34)
    assert idle["state"] == "idle"
    assert idle["contracts_line"] == "Enter a budget to size a position."
    # Zeros would read as a real result; there is no position to report.
    assert all(row["value"] is None and row["net"] is None for row in idle["ladder"])
    # The break-even and the intrinsic column are still true without a budget.
    assert any(row["break_even"] for row in idle["ladder"])


def test_hand_derived_contract_cap() -> None:
    fixture = _load(SIZING_FIXTURE)
    payload = next(item for item in fixture["scenarios"] if item["name"] == "main")["payload"]
    capped = mirror_sizing(payload, "P-12-near_atm", 100_000_000, 12.34)
    assert capped["capped"] is True
    assert capped["contracts"] == payload["max_contracts"]
    assert "capped at 10,000 contracts" in capped["contracts_line"]
