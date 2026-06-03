# Work Order for Codex — Audit Fixes (M1.5)

**From:** Claude Code (Opus 4.8)
**For:** Codex
**Branch:** `dev-vic`. No `git push` (Emanuel pushes). One commit per item (or per group as noted); run the full suite after each.
**Source audits (full detail):** `claude_options_data_layer_audit_m15.md`, `claude_schema_and_logic_audit_m15.md`.

## Timing
**Do these as a dedicated fix pass AFTER you reach Checkpoint B** (finish the Batch 3 report rewrite first). None of these block the report wiring. Exception: if you prefer, **F-1 is independent** of `report.py`/`cli.py` and can be done anytime — your call.

## Already done — do NOT redo
The Checkpoint A findings (duplicate speculation config field, `skipped_reason` split, hedge-cost hoist, unused `risk_free_rate`, rank sentinel, shared dedup helper) are **already fixed** in commit `9a4cf56`. Verified. This work order is only the *remaining* items.

---

## F-1 (HIGH) — A failed risk-free-rate fetch silently empties the whole tool. Fix the delta fallback.

**Files:** `golden_vector/features/options_chain.py:100-102` (root cause); cascades through `black_scholes.py:96-99`, `candidate_puts.py:91-97`, `features/options.py:222-228`.

**Problem:** When `risk_free_rate is None` (the `^IRX` fetch is allowed to fail and return `None`), `add_black_scholes_delta` sets **every** row's `delta` to `None`:
```python
if risk_free_rate is None:
    result["delta"] = None
    return result
```
`strike_for_target_delta` then filters to non-null deltas → empty → **no candidates for any ticker**, and `optionability_tier` collapses to "thin"/"none" universe-wide. The report comes back blank with no explanation on any day the rate fetch blips. This is bigger than CODE_REVIEW M5 (which only covered pricing) — it kills candidate selection *upstream* of pricing.

**Fix:** delta is nearly rate-insensitive, so fall back to `r = 0.0` instead of voiding deltas:
```python
def add_black_scholes_delta(frame, *, underlying_price, risk_free_rate):
    result = frame.copy()
    rate = 0.0 if risk_free_rate is None else float(risk_free_rate)
    deltas: list[float | None] = []
    for row in result.itertuples(index=False):
        ...
        deltas.append(black_scholes_delta(..., risk_free_rate=rate, ...))
    result["delta"] = deltas
    return result
```
(Delete the early `if risk_free_rate is None: result["delta"] = None` branch.)

**Keep the disclosure:** this does *not* replace M5 — still surface "risk-free rate unavailable; used 0%" wherever a *price* is shown. F-1 only ensures candidates/optionability survive the failure.

**Test to add** (`tests/test_options_chain.py` or `test_candidate_puts.py`): with `risk_free_rate=None`, `add_black_scholes_delta` produces non-null deltas, and `build_candidate_put_grid` returns a **non-empty** grid on a fixture chain that would otherwise yield candidates.

---

## F-2 (HIGH, structural) — Add producer↔consumer contract tests to stop silent column drift

**Why:** every hedge module reads cross-module columns by string key with silent `None` fallback (`row.get("down_beta_core")`, `row_float(row, "share_price_usd")`). If a producer renames/drops a column, nothing raises — the tool silently degrades (e.g. all betas `None` → empty ranking). The fixture tests can't catch this because they hand-build frames with the right names. The earlier `down_beta_12m` vs `down_beta_core` mix-up was exactly this class and it survived a green suite.

**Fix:** add a small contract test (new file `tests/test_hedge_data_contracts.py`) asserting the consumer's expected columns are a subset of each producer schema's fields:
```python
from golden_vector.contracts.data_models import ToolAOutput, ToolBOutput

def test_hedge_reads_only_real_tool_a_columns():
    expected = {"ticker", "down_beta_core", "up_beta_core",
                "confidence_score", "confidence_label", "score_eligible"}
    assert expected <= set(ToolAOutput.model_fields)

def test_hedge_reads_only_real_tool_b_columns():
    expected = {"ticker", "share_price_usd", "screening_verdict"}
    assert expected <= set(ToolBOutput.model_fields)
```
Plus a presence check that `compute_options_features` output contains `optionability_tier` and `iv_percentile_cross_sectional`. These fail loudly the moment a producer renames a field — cheap insurance as Tool C/D add more consumers later.

---

## F-3 (MEDIUM) — Remove the misleading "used 0%" note from the sensitivity ranking

**File:** `golden_vector/hedge/sensitivity_ranking.py:138-139`.

**Problem:** the ranking's P&L column is `pnl_per_contract_at_expiry` — an **at-expiry intrinsic** value that is **independent of the risk-free rate**. Annotating that row "risk-free rate unavailable; used 0%" implies the shown number is affected when it isn't (the rate only affects mark-to-market-today values, which the ranking doesn't display).

**Fix:** drop the r=0 note from `_build_row` in the sensitivity ranking. Keep r=0 disclosure only where mark-to-market prices are shown (the speculation/scenario blocks). Update the test `test_build_sensitivity_ranking_annotates_risk_free_fallback` accordingly (it should assert the note is **absent**, or reword to "(does not affect the at-expiry figure)").

---

## F-4 (MEDIUM) — Confirm behaviour: should `score_eligible=False` hide a ticker from the ranking?

**File:** `golden_vector/hedge/sensitivity_ranking.py:106, 147`. Currently a row is rankable only if `score_eligible AND down_beta_core is not None`, so a score-ineligible ticker with a perfectly good `down_beta_core` sinks to the bottom.

**Decision needed (Emanuel):** `score_eligible` is a Tool A *scoring* gate; using it to hide a name from a *sensitivity* view may discard usable signal.
- **Recommended default:** rank by `down_beta_core` whenever it's present, regardless of `score_eligible`, and add a `"score-ineligible"` note instead of sinking the row.
- **Codex:** implement the recommended default **only if Emanuel confirms**; otherwise leave as-is. Either way, add/keep a test pinning the chosen behaviour.

---

## F-5 (LOW) — ATM straddle can use an off-center strike on sparse chains
**File:** `options_chain.py:165-171` (`compute_straddle_implied_move`). It picks the common strike nearest spot; on a thin chain that strike can be far from ATM, biasing `implied_move_{h}d`. Add a guard: return `(None, False)` when the chosen strike is more than ~one strike increment (or a configurable % of spot) away. Low frequency for the liquid US optionable names, but it protects the implied-move-vs-modeled header verdict.

## F-6 (LOW) — Confirm the 300% IV ceiling is intended
**File:** `options_chain.py:233-237`. `option_quote_is_tradable` rejects `implied_volatility > max_implied_volatility` (default 3.0). Deep-OTM tail puts can legitimately exceed 300% IV — exactly the cheap lottery tickets a speculator might want. Confirm 3.0 is intended for the speculation use-case; no code change unless Emanuel wants the ceiling raised.

## F-7 (LOW) — Document/De-magic two literals
- `sensitivity_ranking.py:131` hardcodes `gold_scenarios=(-0.10,)`. Extract a module constant `RANKING_PNL_GOLD_MOVE = -0.10` so the "−10%" header and the value can't drift.
- `options_chain.py:128-140` `nearest_expiration` tiebreak prefers the shorter-dated expiry on an exact distance tie — add a one-line comment stating that intent.

## F-8 (LOW) — Harden "latest feature row" selection
**Files:** `sensitivity_ranking.py:168` (`frame.iloc[-1]`) and `_helpers.rows_by_ticker_dict` (dict overwrite → last row wins). The per-ticker feature parquet accumulates history; "last" currently equals "latest" only because rows are appended in order. Sort by `as_of_date` (or filter to the manifest `refresh_run_id`) before taking the latest, so a future reload that reorders rows can't silently read a stale feature row.

---

## Suggested commit plan
1. `m15 v6 audit fix F-1: risk-free-rate delta fallback (+ test)`
2. `m15 v6 audit fix F-2: producer/consumer contract tests`
3. `m15 v6 audit fix F-3: drop misleading r=0 note in ranking`
4. `m15 v6 audit fix F-4: score-eligible ranking behaviour` *(only after Emanuel confirms)*
5. `m15 v6 audit fixes F-5..F-8: low-priority hardening` *(can be one commit)*

Run `python -m pytest -q` after each; keep it green. Self-review each diff (scoped files only, no stray edits) before committing. Report the final test count.
```
