# Code Review — Codex M1.5 v6, Checkpoint A (Batches 1–2, steps 0–6)

**Reviewer:** Claude Code (Opus 4.8), senior-engineer pass
**Date:** 2026-06-02
**Scope:** commits `5452152`..`8f71091` (9 commits, +1702/−155 across 22 files) — Step 0 baseline + steps 1–6 + two self-review commits.
**Method:** read every new/edited source file end-to-end; verified migrations against the originals via `git diff`; checked math by hand; reviewed the new test inventory. Did **not** run a fresh suite (Codex reports 500 passing; tree is clean and committed).
**Verdict:** **Strong work — APPROVE TO CONTINUE to Batch 3, after addressing M-1 (it will bite the CLI step) and ideally M-2.** No critical bugs. The rest are maintainability/robustness items that are cheaper to fix now than after the report rewrite.

---

## Summary

Plan fidelity is high and Codex's self-review claims check out: scoped files only, no duplicate helper definitions left behind, `_helpers.py` is dependency-light (only `pandas`), and both new modules use `down_beta_core` for ranking *and* pricing (the H-A fix). The three v6 "traps" are all respected — `comparison.py` is untouched, the options status-count still increments after the try, and the strategy P&L computes intrinsic internally.

Math verified by hand:
- **Black-Scholes call** (`black_scholes.py`): `S·N(d1) − K·e^(−rT)·N(d2)`, `spot=0 → 0.0`, guards mirror the put. Put-call parity holds analytically. ✅
- **Strategy P&L** (`scenarios.py`): intrinsic computed inside `_intrinsic_value` from the strategy's option type, so strategy/intrinsic can't desync (the M-D fix). The LONG_PUT path is numerically **identical** to the old code (`intrinsic − premium`), so no regression — consistent with the existing `test_scenarios.py` still passing. ✅
- **`down_beta_min_for_scenario`** is correctly threaded into `_skip_reason` (the H-C fix); the module constant is now only the param default, not the live threshold. ✅
- **Proxy migration** preserved `strip=True, require_string=True`, matching the old `_indexed_by_ticker` semantics exactly. ✅

Config validation is genuinely good: `ordered_proxy_basis_bands`, 0–1 confidence bound, protection-level fraction + uniqueness checks. Test coverage on the two new modules matches the v6 step-6 list closely.

**Note on scope:** `report.py` is *not* yet refactored into builders+emitter, and the new modules are *not* yet wired in. That is correct for Checkpoint A — it's Batch 3 (step 8). Not a finding.

---

## Findings

### M-1 (Medium) — Duplicate speculation-cap config field; reconcile before the CLI step
**Files:** `config_models.py` (`max_tickers_speculation_section` pre-existing **and** new `speculation_max_tickers_default`); `config/hedge_readiness.yaml` (both keys present, both `15`).

Step 2 added `speculation_max_tickers_default: int = 15`, but the pre-existing `max_tickers_speculation_section: int = 15` was left in place. There are now **two config fields meaning the same thing**, both populated in the YAML.

**Why it matters:** in Batch 3, step 7 wires `--speculation-max-tickers` to "fall back to config." If the flag falls back to `speculation_max_tickers_default` while `speculation_section.py` actually reads `max_tickers_speculation_section` (or vice-versa), the CLI flag and the section will disagree and the cap will appear not to work. This is exactly the kind of stale-duplicate the v6 plan set out to avoid.

**Fix:** decide the canonical field. Recommended: keep `speculation_max_tickers_default` (matches the `ranking_max_tickers_default` naming and the new flag), repoint `speculation_section.py` to it, and **remove `max_tickers_speculation_section`** from both the model and the YAML. Update any test that referenced the old name. Do this at the start of Batch 3 before wiring the flag.

### M-2 (Medium) — Portfolio scenario math decides "apply downside?" by substring-matching a human-readable reason
**File:** `portfolio_totals.py:190-197` (`_holding_value_at_scenario`).

```python
if (holding.down_beta_core is None
        or (holding.skipped_reason is not None
            and "down-beta unavailable or too small" in holding.skipped_reason)):
    return holding.current_notional          # treat as flat (no gold sensitivity)
```

The logic is **currently correct** (the substring is present exactly when `down_beta_core is None or <= down_beta_min_for_scenario`), but it couples the scenario math to the exact wording of a skip-reason string. If anyone rephrases that reason later, holdings with a too-small beta will silently start receiving modeled downside — a wrong number with no test failure (the unit test asserts a specific string today).

**Fix:** carry the decision as data, not prose. Add an explicit boolean to `HoldingResolved` (e.g. `downside_modelable: bool`) set in `_resolve_holding`, and branch on that. This also removes the fragile string dependency entirely.

### M-3 (Medium) — `hedge_cost_by_protection` is scenario-independent but stored on every scenario row
**File:** `portfolio_totals.py:33-37, 173-179`.

`_hedge_cost_at_level` depends only on `current_notional`, `protection_level`, `current_stock_price`, and `candidate.mid` — **not** on `gold_pct_change`. So the same dict is recomputed and stored identically on all 5 `PortfolioScenarioRow`s. This both wastes work and, more importantly, **implies to a reader (and to the Batch-3 emitter) that hedge cost varies by scenario**, which it doesn't.

**Fix:** compute hedge cost once and hoist it to `PortfolioTotalsData` (e.g. `hedge_cost_by_protection: dict[float, float]` at the top level), leaving `PortfolioScenarioRow` to carry only scenario-varying figures. Cleaner data model for the report.

### M-4 (Medium) — `skipped_reason` / `holdings_skipped` is overloaded across two different meanings
**Files:** `portfolio_totals.py:233-256` (`_skip_reasons`), `:90-102` (`holdings_skipped`).

A dollar-exposure holding with no price gets `skipped_reason="no hedge-cost inputs"` yet **still contributes** to `current_total_value` and to scenario loss (correctly). But it lands in `holdings_skipped`, so the Batch-3 report could read "skipped: TICKER — no hedge-cost inputs" and imply it was dropped from the totals, when only its hedge cost was.

**Fix:** distinguish "excluded from totals" (missing notional) from "excluded from hedge cost only." Either split into two lists, or annotate each reason with which aspect it affects, so the emitter can phrase it honestly. (Pairs naturally with the M-2 boolean refactor — make the resolution carry per-aspect flags.)

### L-1 (Low) — `compute_portfolio_totals(risk_free_rate=…)` is accepted then discarded
**File:** `portfolio_totals.py:61` (`_ = risk_free_rate`).

Hedge cost uses the market mid premium, not a BS recompute, so the rate genuinely isn't needed here. The param exists because the v6 plan signature listed it. Either drop it from the signature, or keep it with a one-line comment that it's reserved for a future BS-based hedge-cost mode. As-is it's a dead parameter.

### L-2 (Low) — `rank=0` sentinel in `_build_row`
**File:** `sensitivity_ranking.py:142`. `rank=0` is used to mean "rankable, will be numbered later," then overwritten in `reranked`. It works, but a boolean (`is_rankable`) reads more honestly than a magic 0. Optional.

### L-3 (Low) — Three near-identical order-preserving dedup helpers
**Files:** `sensitivity_ranking.py:193` (`_unique_notes`), `portfolio_totals.py:314` (`_unique_reasons`), `speculation_section.py` (`_unique_annotations`). This is the same kind of duplication step 4 just consolidated for the float/index helpers. Consider adding `unique_preserving_order(values)` to `_helpers.py` and collapsing all three. Low priority, but it's the exact pattern `_helpers.py` exists to prevent.

---

## What I checked and found clean (no action)
- BS call price + parity, spot=0 behaviour.
- Strategy enum / `compute_strategy_pnl` / `_intrinsic_value` / `_mark_to_market_pnl` — sign rules correct for all 4 strategies; LONG_PUT path unchanged.
- `_skip_reason` threshold threading (H-C).
- Helper migration in all 4 modules — behaviour-preserving (proxy kept strict ticker semantics; the others differ only in skipping empty-string ticker keys, which is an improvement).
- Both new modules use `down_beta_core` for sort key and P&L column (H-A).
- Config validators (ordered bands, confidence 0–1, protection fractions, uniqueness).
- Test inventory: sensitivity (7), portfolio (9), strategy math (3) — covers the planned cases including dollar-without-price, low-beta-counts-notional, ceil rounding, risk-free fallback note, unknown-sort rejection.

---

## Recommendation to Codex
1. **Fix M-1 first, at the top of Batch 3**, before wiring `--speculation-max-tickers` — otherwise the flag will silently fight the section.
2. Apply **M-2** (boolean instead of string match) and **M-3** (hoist hedge cost) now, while `portfolio_totals.py` is fresh and before the emitter consumes its shape in step 8 — both change the dataclass shape, so doing them pre-integration avoids reworking the emitter.
3. **M-4** can be folded into the M-2 refactor (carry per-aspect flags).
4. L-1/L-2/L-3 are opportunistic — fix if cheap, otherwise note and move on.
5. Re-run the full suite after the fixes; update `test_portfolio_totals.py` for the new dataclass shape. Then proceed to Batch 3.

Nothing here blocks continuing — the foundation and the two new modules are solid. These are refinements that are simply cheapest to land before the report rewrite builds on top of them.
