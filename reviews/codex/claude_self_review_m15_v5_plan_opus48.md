# Senior-Engineer Review — M1.5 v5 Plan (independent second pass)

**Reviewer:** Claude Code (Opus 4.8), acting as senior engineer
**Date:** 2026-06-02
**Subject:** `reviews/codex/claude_m15_v5_plan.md` (912 lines)
**Prior review:** `reviews/codex/codex_review_claude_m15_v5_plan.md` (Codex, NEEDS CHANGES, 9 findings)
**Verdict:** **NEEDS CHANGES — but for a different and more serious reason than Codex found.**

---

## The review prompt I held myself to

> Review this plan as a senior engineer who is accountable for the result. Do **not** read the plan in a vacuum — read it against the *actual codebase and working tree it will be implemented on*. For every claim the plan makes about "what exists" or "what needs building," verify it against the real files. Run the code where a behavioural claim can be checked empirically rather than reasoned about. Find: (1) places where the plan contradicts reality, (2) places where the plan contradicts itself, (3) logic/math errors, (4) duplicate or dead specification, (5) work that is silently in-scope or silently dropped. Rank by impact on a real implementer. Reaffirm or challenge the prior reviewer's findings rather than restating them. Prefer concrete file:line evidence and reproducible checks over opinion.

## What I did

- Read the v5 plan, Codex's v5 review, and `CODE_REVIEW.md` end-to-end.
- Read the actual modules the plan touches: `scenarios.py`, `comparison.py`, `black_scholes.py`, `proxy_hedge.py`, `options_phase.py`.
- Ran `git diff HEAD` on the working tree (10 files, **+267 / −30**).
- Ran the comparison sort and a column-existence grep to verify two specific claims empirically.

---

## BLOCKER FINDINGS (must resolve before any planning re-spin)

### C1 — The plan is stale against the working tree. ~5 of its 13 steps are already implemented (uncommitted).

The plan's §1 "Current state (verified 2026-06-02)" describes the **committed HEAD**, not the **working tree the plan will actually run on**. The working tree already contains uncommitted implementations of:

| Plan step | What the plan says to "add/build" | Working-tree reality |
|---|---|---|
| Step 8 / §2i (H2) | "upgrade proxy to 3-tier basis-risk" | **Already done.** `proxy_hedge.py::_basis_risk_label` is fully 3-tier (low/medium/high) with confidence weighting; `map_proxy_hedges` already takes the three thresholds; `config_models.py` already has the 3 fields + validators; `config/hedge_readiness.yaml` already has them; `test_proxy_hedge.py` already has 3-tier tests. |
| Step 9 / §2i (H3) | "add per-ticker error isolation" | **Already done** — and done *correctly* (see C2). `options_phase.py` already wraps the loop in try/except + `test_options_phase.py` has the mid-loop failure test (+71 lines). |
| Step 11 (H1) | "flip cross-sectional IV sort to ascending" | **Already done.** `report.py:327` already reads `ascending=True`. |
| (not in plan scope) | — | **CODE_REVIEW.md M4 (same-day re-run dedup) is already done** in `_append_feature_rows` (dedups on `run_id`). The plan never scoped this; it's already in the tree. |
| Step 2 (partial) | "extend config + yaml" | Proxy fields **already present**; the scenario/ranking/speculation fields are **not yet** present. So step 2 is half-done. |

**Why this is a blocker:** the plan instructs an implementer to *add* code that already exists. Following it literally produces duplicate definitions, merge pain, and a completion report that disagrees with the diff. The whole v5↔v6 review loop is being run on a description of the repo that is one uncommitted changeset out of date.

**Required fix before anything else:** decide what to do with the working tree (commit it as the real "checkpoint A", or stash it), then **rewrite §1 against the true starting point** and **delete or down-scope steps 8, 9, and the H1 part of 11** to "verify already-present; add tests if missing." The 13-step / 18–22 hr estimate must be re-baselined — a meaningful chunk is already done.

### C2 — The plan's H3 `options_phase` pseudocode is a *regression* vs the working tree. Codex finding #8 is already moot.

Codex finding #8 correctly criticised the **plan's** pseudocode (§3, lines 560-572) for incrementing `status_counts[result.status]` *before* the persist/feature step, which double-counts a ticker that fetches OK but fails to persist.

But the **actual working-tree code** already does the right thing: it increments the status **after** the try-block succeeds, and the `except` increments `OPTIONS_STATUS_ERROR` + `continue`s. No double-count.

So: the plan's pseudocode is *worse* than the code that already exists. If an implementer "applies step 9" by following the plan's snippet, they will **regress correct code into the double-counting form Codex warned about.** The plan's H3 snippet must be deleted and replaced with "already implemented at `options_phase.py:97-136`; confirm tests cover summary-count correctness."

### C3 — The `breakeven_gold_pct` comparison fix (step 4 / §3) is both unnecessary and wrong-as-written.

This is subtle and neither the plan nor Codex reasoned it through to the end. I checked it empirically:

```
$ build_comparison_table(..., sort_by='breakeven_gold_pct')   # current code, default descending=True
order: ['NEM', 'AEM']        breakevens: [('NEM', -0.0143), ('AEM', -0.0886)]
```

The **current, unmodified `comparison.py`** already sorts breakeven **closest-to-zero-first** (NEM −1.4% before AEM −8.9%). That is exactly:
- what Codex finding #4 says is correct ("closest-to-zero-first for a put buyer"), and
- what the new test already in the working tree asserts (`test_build_comparison_table_sorts_breakeven_by_smallest_required_drop_first` → `['NEM','AEM']`).

The plan's proposed rewrite sets `_NATURAL_DESCENDING["breakeven_gold_pct"] = False` (ascending), which would produce `['AEM','NEM']` — **most-negative-first**, the opposite of the agreed intent, and it would **fail the test already added to the tree.**

Note also: `comparison.py` is **not** in the working-tree diff — i.e., whoever added the breakeven test correctly left the module alone because the default already works. The plan is the only artifact still claiming a fix is needed.

**Required fix:** drop the comparison.py change from the plan entirely (there is no bug under the agreed "closest-to-zero-is-best" definition). If a `_NATURAL_DESCENDING` dict is still wanted purely for *explicitness*, `breakeven_gold_pct` must map to **`True`/descending** (not `False`), and the plan must keep the `descending` parameter story consistent — the proposed 2-arg `_sort_key(row, sort_by)` silently drops the existing `descending` parameter that `build_comparison_table` passes, which is an unflagged signature change.

---

## HIGH-PRIORITY FINDINGS (new; not in Codex's review)

### H-A — Sensitivity Ranking ranks by `down_beta_12m` but prices with `down_beta_core`. Both columns exist and differ.

`git grep` confirms `down_beta_12m` and `down_beta_core` are **two distinct Tool A columns**. The entire hedge pipeline — `scenarios.py`, `proxy_hedge.py`, `header_context.py`, `report.py` — uses `down_beta_core`. But §2f/§3 sort the new Sensitivity Ranking by `down_beta_12m`, while the same row's "60d Put @ −10% P&L" column is computed via `compute_scenario_bundle`, which uses `down_beta_core`.

So the **ordering metric and the displayed P&L are derived from two different betas.** A ticker could rank #1 by 12-month down-beta yet show a modest P&L because its core beta is lower (or vice versa). For the section billed as "the report's entry point," that's an analytical-coherence bug, not a cosmetic one. **Pick one beta for both the sort and the P&L**, or state explicitly and visibly why the ranking key differs from the pricing beta.

### H-B — Section dataclass names are inconsistent and duplicated.

- §2d declares `SensitivityRankingData`; §3's `build_sensitivity_ranking` returns `SensitivityRankingBlock`. Same fields, two names. `HedgeReadinessSections` references the `Data` name, the module builds the `Block` name → they won't line up.
- `SensitivityRow` is fully defined twice (§2f and §3) — same maintenance hazard Codex flagged for `PortfolioTotalsData` (#7), just not caught for this type.
- The `…Data` (aggregate, §2d) vs `…Block` (module, §3) suffix split runs through the doc. Pick one suffix convention and **one definition site per type**, then reference it.

### H-C — "Config-driven `down_beta_min_for_scenario`" won't actually take effect as specified.

The real skip logic lives in `scenarios.py::_skip_reason`, which reads the **module constant** `DOWN_BETA_MIN_FOR_SCENARIO`. The plan adds a `down_beta_min_for_scenario` *parameter* to `compute_scenario_bundle` (§3) but never says to thread it into `_skip_reason`. An implementer who only touches the public signature will leave the threshold hardcoded — the config field becomes dead. Also §3 types it as a plain `float` param while §4d reads `config.down_beta_min_for_scenario` (config object). **Specify: thread the value into `_skip_reason`, and choose float-param XOR config-object consistently.**

---

## MEDIUM-PRIORITY FINDINGS (new)

### M-A — `target_notional` is undefined in the §2g hedge-cost formula.
`hedge_cost_at_X% = sum(ceil(target_notional / (strike × 100)) × candidate.mid × 100 …)` uses a variable that is never defined anywhere in the plan. (This is separate from — and underneath — Codex #3's contradiction about *which* rule to use. Even after Codex's rule is chosen, the formula needs a defined input.)

### M-B — Two CODE_REVIEW.md findings explicitly scoped to M1.5 were silently dropped.
`CODE_REVIEW.md` recommended doing **M1 (gold-scenario sign-convention reconciliation)** and **M5 (surface the r=0 risk-free fallback)** *"during M1.5."* Neither appears in the v5 plan: §2j's data-quality-guardrails list omits the r=0 annotation, and step 2's config work omits reconciling `default_scenarios` (negative) with `gold_down_scenarios` (positive). Either re-include them or explicitly defer with a reason — right now they've vanished without a decision.

### M-C — `build_sensitivity_ranking(risk_free_rate: float)` types the rate as non-optional, but it can be `None`.
Per CODE_REVIEW M5, `^IRX` fetch failure leaves `risk_free_rate=None` → the pipeline falls back to `r=0`. The §3 signature lies (`float`). Type it `float | None` and define the behaviour (skip, or annotate r=0).

### M-D — `compute_strategy_pnl` is a 2-way sign flip dressed as 4 cases, and intrinsic/strategy can desync.
LONG_PUT and LONG_CALL return the identical formula (`intrinsic − premium`); SHORT_PUT and SHORT_CALL return the identical formula (`premium − intrinsic`). The put/call distinction lives **entirely** in the caller-supplied `intrinsic_value`. Nothing stops a caller passing call-intrinsic with `LONG_PUT` and getting a silently wrong number. For a primitive being added "for correctness," either compute intrinsic *inside* the function (take `option_type`, `strike`, `underlying`) so strategy and intrinsic can't desync, or document the caller contract loudly. As written, the enum adds API surface without adding safety.

---

## LOW-PRIORITY / CONSISTENCY

- **L-1:** §2c shows `--ranking-max-tickers  Default: 60`, but §3's argparse uses `default=None` (config fallback). Two different "defaults" stated for one flag.
- **L-2:** Dependency-injection style is inconsistent across the three new builders — `compute_portfolio_totals` takes a `config` object; `build_sensitivity_ranking` and `compute_scenario_bundle` take unpacked params. Not a bug, but pick a convention.
- **L-3:** Confirmed Codex #6 (stale counts: 5 flags not 4; 10 config fields not 7) and Codex risk #7 (`--quantity` flag vs `default_scenario_quantity` field name mismatch). Real, low-impact.

---

## On Codex's 9 findings

All 9 are valid **as critiques of the plan text**, with one important caveat: **finding #8 (options double-count) is moot against the working tree** — the real code already increments after the try. Codex reviewed the plan's pseudocode without checking the tree, so it flagged a regression the plan would *introduce* rather than a bug that exists. My C1/C2 supersede it: the fix is not "restructure the pseudocode," it's "delete the pseudocode and point at the already-correct code."

Codex finding #4 (breakeven sort) is directionally right about *intent* but, as C3 shows, the implementation conclusion ("flip the dict to True") is unnecessary because the current default already yields that order, and the plan's own proposed value (`False`) is the wrong one.

---

## Bottom line

The four contradictions Codex found are real text bugs, but they're downstream of a bigger problem: **the plan no longer matches the repository.** A reviewer grading the prose will keep finding paper cuts; an implementer running the steps will hit duplicate code and one outright regression.

**Recommended sequence:**
1. **Reconcile the working tree first** — commit the uncommitted +267/−30 as the genuine post-H1/H2/H3/M4 baseline (or stash it deliberately), then re-snapshot §1 against reality.
2. **Re-baseline scope** — steps 8, 9, the H1 part of 11, and half of step 2 are done. Cut them to "verify + test-gap-fill." Re-estimate (it's materially less than 18–22 hrs now).
3. **Then** apply Codex's edits #1–#7, #9, drop #8 (moot) and the comparison fix (C3), and resolve my H-A through M-D.
4. Only after the plan describes the actual repo should it go back for a READY grade.

This is recoverable in one focused cleanup pass — the *architecture* is sound (Codex and I agree on that). The issue is purely that the plan and the tree have drifted apart.
