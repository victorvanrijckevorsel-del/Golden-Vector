# Review Request — Program A Validation Engine (chunk 1)

**From:** Claude · **To:** Codex · **Date:** 2026-06-12
**Branch:** `dev-vic` (latest commit on top of `main` ce42bc4)

## What this is

The backend for a new "Does-It-Work Scorecard": it measures, out of sample
and walk-forward, whether Golden Vector's ranking tools actually do what they
claim. This is a **correctness-critical statistical module** — a
plausible-but-wrong number here produces a misleading verdict about whether a
tool works, which is the worst kind of bug. Please review it as such.

**Scope of THIS review: chunk 1 only** — the engine + the three price-only
experiments (E1a, E1b, E2) + their tests/canaries. E3/E3b (Tool C
reconstruction), E4 (forward accrual), persistence, and the `/scorecard` page
are **not built yet** — do not review or stub them.

## CRITICAL: this is a pre-registered study — gates are BINDING

The experiment designs, gates, baselines, and verdict rules were locked in
`reviews/codex/claude_program_a_validation_spec.md` (v2) and the variants were
**sha256-registered in `data/lab/variant_ledger.jsonl` BEFORE the code was
written** (after a 4-lens adversarial design review that fixed 4 BLOCKERs).

This means:
- **If you find a gate/threshold is wrong, that is a FINDING to raise — NOT a
  thing to silently change.** Changing a registered gate after seeing results
  is the exact malpractice pre-registration exists to prevent. Flag it; we
  decide with Emanuel whether to register a new variant (which raises the
  multiplicity count and must be disclosed).
- **The implementation must faithfully match the registered spec.** The
  highest-value review question is: *does the code do what
  `claude_program_a_validation_spec.md` §1–§2 says it does?* Any divergence is
  a finding, even if the code's own version looks reasonable.

## Files to read

- `reviews/codex/claude_program_a_validation_spec.md` — the binding spec (read
  §0, §1, §2-E1a/E1b/E2, §4 canaries first).
- `golden_vector/lab/validation.py` — the engine under review (~480 lines).
- `tests/test_lab_validation.py` — unit tests + the two implemented canaries.
- For the "no forked math" check: `golden_vector/model/pipeline.py:407-418`
  (the product's `structural_delta_core`/`down_beta_core` = `weighted_median`
  over ELIGIBLE windows) and `golden_vector/model/structural.py:1179`
  (`weighted_median`). The validation module reconstructs these PIT in
  `reconstruct_cores_at` — confirm it matches.
- `golden_vector/features/weekly_returns.py` — `build_weekly_return_frame`
  (the forward-outcome source; week_period strings).

## Specific review targets (please check each first-hand)

1. **PIT integrity (highest priority).** In `reconstruct_cores_at`, can any
   data from after `period` enter the rank at t? In `forward_realized_beta`,
   is the forward window **strictly** `period < p <= period+26` (the week of t
   must be excluded — verify the boundary, including holiday-stamped weeks)?
   The panel is regenerated each refresh with 2026 code (code-vintage, which
   the spec caveats) — confirm no *data* leakage beyond that.

2. **Core reconstruction parity.** Does `reconstruct_cores_at` reproduce the
   product's core exactly? Specifically: latest as-of row per ticker within
   the W-FRI period; ELIGIBLE windows only; `_weighted_median` with the config
   weight map. Run a parity check at the latest as-of against
   `tool_a_latest.parquet`'s `structural_delta_core` / `down_beta_core` if you
   can (the spec calls for this parity test — it is NOT yet written; flag its
   absence and, if cheap, write the check to confirm).

3. **The t-stat path (the design review's load-bearing fix).** `newey_west_t`
   must use **n = number of folds**, NOT the lab evaluator's
   `effective_n = n/26` (which would yield ~1.7 and return None, voiding every
   gate). Verify the NW lag-1 variance is correct (Bartlett weight 0.5) and
   that nothing routes through `lab/evaluation.py::evaluate_predictions` for
   these disjoint folds. Is the one-sided gate (`nw_t > 3`) applied correctly?

4. **Gate logic vs spec §2.** For E1b: gates are mean-IC NW-t>3, ≥70% folds
   positive, tercile-portfolio spread ≥0.20 with t>2. For E2: same shape,
   spread gate 0.35, **≥8 forward gold-down weeks** floor (per-ticker and
   fold). For E1a: stability IC≥0.45 + ≥80% folds≥0.30, lag **52** (not 26).
   Confirm each constant matches the spec and the registered ledger config.
   Confirm `_classify` implements SUPPORTED-only-if-all-gates,
   INCONCLUSIVE-if-gates-fail-and-ceiling<0.30.

5. **Tercile-portfolio spread + split-half ceiling.** Is
   `tercile_portfolio_spread` deterministic (ties)? Is the split-half ceiling
   (`forward_realized_beta(split="odd"/"even")`) genuinely outcome-vs-outcome
   (never touches the rank), so it can't unblind? Is the split floor sensible?

6. **The canaries (do they test what they claim?).** `test_canary_label_as_
   feature_scores_near_perfect` and `test_canary_shuffled_ranks_rarely_trip`.
   Are they strong, or do they pass vacuously? Note: spec §4 also requires a
   **time-reversal contrast canary** (ΔIC ≥ 0.15) and a 0.90-alarm semantics
   note — these are **not yet implemented**; flag as a gap to close before the
   results are published.

7. **Edge cases / determinism.** Empty folds, NaN handling in
   `spearman_ic`/`_ols_beta`, the grid step-back logic in `build_as_of_grid`
   (does a thin/holiday-split week correctly step back ≤2 weeks?), and whether
   re-running gives identical numbers.

## The real results (sanity-check these, don't trust them blindly)

On live data the engine returns (gates binding, honest):
- **E1a** SUPPORTED — stability IC 0.61, 98% of folds ≥0.30.
- **E1b** SUPPORTED — mean IC 0.48, NW-t 18.3, 100% folds positive, tercile
  spread 1.11 beta units (t=11.3), median split-half ceiling 0.28.
- **E2** SUPPORTED — mean IC 0.155, NW-t 6.8, 83% folds positive, tercile
  spread 0.58 (t=3.4), ceiling 0.15.
- E1b independently agrees with the earlier beta-gap experiment (Tool A's
  structural betas are near-optimal) — a consistency cross-check.

**Is any of this too good to be true?** E1b's NW-t of 18 is very large — is it
real (beta persistence is genuinely strong and the universe is homogeneous),
or is there a subtle leak/overlap inflating it? That is the single most
important thing to pressure-test. (The design review noted fold ICs are
outcome-disjoint but feature-window-overlapping; the NW lag-1 is the
registered correction — is lag-1 enough?)

## How to report

Write findings to `reviews/codex/codex_review_validation_engine.md` with
severity (BLOCKER/HIGH/MED/LOW), file:line, evidence, and a concrete fix.
Per the repo collaboration rule: **read the code, write findings, do not edit
the gates.** If you find a non-gate bug (PIT leak, parity mismatch, NW error,
canary that passes vacuously), a direct fix with a test is welcome — but flag
anything that touches a registered gate/threshold for Emanuel's decision
rather than changing it. If you want to merge findings with mine, note where
we agree/disagree in a comparison table.

Thanks — this is the foundation the whole Scorecard rests on, so deep is
better than fast.
