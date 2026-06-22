# Codex Review - Program A Validation Engine Chunk 1

Verdict: **READY WITH CHANGES**

Reviewed scope:

- `reviews/codex/claude_program_a_validation_spec.md` sections 0, 1, 2-E1a/E1b/E2, 4
- `golden_vector/lab/validation.py`
- `tests/test_lab_validation.py`
- `golden_vector/model/pipeline.py`
- `golden_vector/model/structural.py`
- `golden_vector/features/weekly_returns.py`
- `data/lab/variant_ledger.jsonl`

Commands run:

```text
python -m pytest tests/test_lab_validation.py -q
8 passed
```

I also ran a local latest-as-of parity probe against `tool_a_latest.parquet`; the reconstructed latest `structural_delta_core` / `down_beta_core` matched 62 current rows exactly. That parity probe is not committed as a test yet.

Live sanity run reproduced the reported results:

```text
grid: 45 folds, 2004-04-23 through 2026-03-27
E1a: SUPPORTED, n=43, mean_ic=0.6105, share=0.9767
E1b: SUPPORTED, n=44, mean_ic=0.4784, nw_t=18.31, share=1.0, spread=1.1121, spread_t=11.31, ceiling=0.2790
E2:  SUPPORTED, n=41, mean_ic=0.1553, nw_t=6.77, share=0.8293, spread=0.5826, spread_t=3.41, ceiling=0.1495
```

## Findings

### HIGH - Core reconstruction forks the product weighted-median helper and lacks the required committed parity test

Evidence:

- Spec requires no forked math and a latest-as-of parity test: `reviews/codex/claude_program_a_validation_spec.md:44-49`
- Validation duplicates weighted median locally: `golden_vector/lab/validation.py:174-189`
- Product helper is the source of truth: `golden_vector/model/structural.py:1179-1199`
- Product core uses that helper: `golden_vector/model/pipeline.py:414-418`
- Current tests only cover a small synthetic median case: `tests/test_lab_validation.py:111-116`

The local `_weighted_median` currently matches the product helper, and my latest-as-of probe matched the current artifact exactly. The problem is architectural: this module says "no forked logic" but carries a copied implementation of the exact primitive whose drift would invalidate the study.

Fix:

- Import and use `golden_vector.model.structural.weighted_median` directly.
- Add a committed parity test that loads the current structural panel and `tool_a_latest.parquet`, reconstructs the latest W-FRI period, and asserts exact equality for `structural_delta_core` and `down_beta_core`.
- Keep a small synthetic test too, but do not let synthetic coverage replace real product parity.

### HIGH - Registered E1b/E2 baseline comparisons are not implemented

Evidence:

- E1b requires paired baselines against the 12M window and fresh 26w trailing beta: `reviews/codex/claude_program_a_validation_spec.md:110-119`
- E2 requires paired baseline against fresh 26w trailing down-beta: `reviews/codex/claude_program_a_validation_spec.md:134-135`
- `ExperimentVerdict` has `baseline_lines`: `golden_vector/lab/validation.py:68`
- `_validity_experiment` never computes baselines or populates `baseline_lines`: `golden_vector/lab/validation.py:373-475`
- `run_e1b` / `run_e2` only pass the main rank column and spread gate: `golden_vector/lab/validation.py:478-505`

This does not change SUPPORTED / NOT SUPPORTED gates, but it is still a registered part of the card. Without these baselines the result can claim "Tool A works" without saying whether the multi-window core adds anything over a simpler 12M or trailing-beta rule.

Fix:

- Implement the registered paired baseline comparisons as companion outputs.
- For E1b, compare per-fold IC against:
  - the single 12M `structural_delta` window
  - a fresh 26w trailing beta computed from data available at `t`, with the same `>=20` weeks rule
- For E2, compare against fresh 26w trailing down-beta with the same `>=8` down-week rule.
- Add tests where a baseline ties or beats the core and assert the registered warning line appears in `baseline_lines`.

### HIGH - Time-reversal leakage canary is missing

Evidence:

- Spec requires a time-reversal contrast canary and contaminated-run refusal: `reviews/codex/claude_program_a_validation_spec.md:197-199`
- Implemented tests cover Newey-West, basic stats, forward strictness, core reconstruction, label-as-feature, shuffled ranks, and one synthetic truth run: `tests/test_lab_validation.py:20-219`
- There is no time-reversal contrast test and no `contaminated=True` refusal path in this chunk.

This is the canary most directly aimed at the "too good to be true" risk. E1b's t-stat is very high. The current strict-forward boundary looks correct, but the publication guard should still prove that a deliberately contaminated rank beats the honest rank and is rejected.

Fix:

- Add a synthetic contaminated-rank harness that uses forward-window information.
- Assert contaminated mean IC beats honest mean IC by at least 0.15.
- Assert the result is marked `contaminated=True` and cannot be published by the Scorecard build path.

### MED - Tercile spread does not explicitly break ties by ticker

Evidence:

- Spec requires deterministic terciles with ties broken by ticker: `reviews/codex/claude_program_a_validation_spec.md:85-86`
- Implementation builds a rank/outcome frame and sorts only by `rank`: `golden_vector/lab/validation.py:312-320`

Because `sort_values(..., kind="mergesort")` is stable, ties currently inherit the caller's input order. In the main path this may usually be ticker-sorted because `reconstruct_cores_at` groups by ticker, but the helper itself does not enforce the registered rule. If a caller passes the same ranks in a different order, tied names can move across tercile boundaries.

Fix:

- Preserve ticker/index as a column and sort by `rank`, then ticker.
- Add a regression where equal-rank names are shuffled in the input and the spread stays identical.

### MED - Registered robustness slices are not implemented

Evidence:

- Spec requires fixed pre-2010 cohort and 52w-spaced fold grid beside any SUPPORTED verdict: `reviews/codex/claude_program_a_validation_spec.md:80-82`
- `validation.py` only builds the main 26-week grid and main experiments: `golden_vector/lab/validation.py:192-231`, `golden_vector/lab/validation.py:334-505`
- Tests do not cover robustness slices: `tests/test_lab_validation.py:1-219`

These are not gates, but they are pre-registered companion checks. A high headline t-stat should not ship without the fixed-cohort and 52w-grid sensitivity checks beside it.

Fix:

- Add helper paths for fixed-cohort and 52w-spaced folds.
- Report these as companion results, not gate modifiers.
- Add at least one synthetic test proving the 52w grid uses a different fold cadence and does not mutate the main verdict.

### MED - Ledger/config drift is not tested

Evidence:

- Registered variants exist in `data/lab/variant_ledger.jsonl`, including `validation_e1a`, `validation_e1b`, and `validation_e2`.
- Gate constants are hard-coded in `validation.py`: `golden_vector/lab/validation.py:31-39`, `golden_vector/lab/validation.py:354-355`, `golden_vector/lab/validation.py:450-458`, `golden_vector/lab/validation.py:478-505`
- No test loads the ledger and checks that implementation constants match the registered configs.

The code currently appears to match the ledger gates: E1a `0.45/0.80`, E1b spread `0.20`, E2 spread `0.35`, NW `>3`, spread t `>2`, share positive `>=0.70`. But because the purpose of the ledger is to prevent post-hoc drift, there should be a guardrail test.

Fix:

- Add a test that loads `variant_ledger.jsonl`, finds the latest records for `validation_e1a`, `validation_e1b`, and `validation_e2`, and asserts the implementation constants/gates match the registered config.
- Do not change the registered gates inside this fix.

### LOW - Newey-West lag-1 covariance uses an `n-1` denominator variant without documenting it

Evidence:

- Spec requires Newey-West lag-1 with Bartlett weight 0.5: `reviews/codex/claude_program_a_validation_spec.md:50-57`
- Implementation computes `gamma0` as mean over `n` residuals, but `gamma1` as mean over `n-1` lag pairs: `golden_vector/lab/validation.py:106-109`

This is a small finite-sample convention difference, not an obvious blocker. Standard HAC formulas often use `1/n` for lag covariance. With ~40 folds this is only a few percent, but this is a correctness-critical module, so the convention should be explicit and tested.

Fix:

- Either change `gamma1` to `sum(resid[1:] * resid[:-1]) / n`, or document the chosen finite-sample convention and pin it with a numeric test.
- Add a hand-calculated 4- or 5-fold example test for the exact NW formula.

### LOW - Input loading bypasses the manifest/current-state readers

Evidence:

- `load_validation_inputs` globs the first `*latest*.parquet` panel file: `golden_vector/lab/validation.py:517-520`
- It reads the first raw gold parquet and all USD equity files directly: `golden_vector/lab/validation.py:525-529`
- Golden Vector's standing data architecture says readers should resolve through the current-state manifest where possible.

Current local directories only expose one raw gold file and one structural latest file, so this did not break my run. But this module is meant to be a serious scorecard foundation. It should not accidentally pick the wrong artifact if run-stamped latest files or historical variants appear.

Fix:

- Resolve the structural panel and product outputs through the same manifest/current artifact helpers used elsewhere.
- If raw history inputs intentionally bypass the manifest because the validation is a lab process, document that and fail loudly when more than one plausible source exists.

### LOW - `evaluate_predictions` guard is not explicitly tested for the disjoint-grid path

Evidence:

- Spec says calling the weekly evaluator path with `h=26` on this grid must raise: `reviews/codex/claude_program_a_validation_spec.md:56-57`
- Tests prove `newey_west_t` uses fold count: `tests/test_lab_validation.py:20-31`
- There is no test that prevents a future maintainer from routing these fold ICs through `golden_vector/lab/evaluation.py::evaluate_predictions`.

The current engine does not route through `evaluate_predictions`, so this is not an active bug. It is a missing guardrail against reintroducing the exact effective-n trap the spec calls out.

Fix:

- Add a small typed wrapper or explicit test that fold-level Program A results cannot be sent through `evaluate_predictions`.
- At minimum, add a test that monkeypatches `evaluate_predictions` to raise if called during E1b/E2.

## What Looks Correct

- PIT rank extraction uses W-FRI `week_period`, not raw `as_of_date`: `golden_vector/lab/validation.py:132-136`.
- `reconstruct_cores_at` only reads rows inside the target period and takes the latest as-of row within that period: `golden_vector/lab/validation.py:153-160`.
- Forward outcomes are strictly `period > t` and `period <= t + 26`: `golden_vector/lab/validation.py:262`.
- E2's down-week floor is enforced per ticker through `min_weeks=8`: `golden_vector/lab/validation.py:492-505`.
- Main gate constants match the spec for E1a, E1b, and E2.
- `_classify` correctly returns SUPPORTED only when all gates pass, and INCONCLUSIVE only when gates fail and median ceiling is below 0.30: `golden_vector/lab/validation.py:286-299`.
- Split-half ceiling is outcome-vs-outcome and does not use the rank: `golden_vector/lab/validation.py:413-431`.
- The live E1a/E1b/E2 numbers reproduce locally.

## Bottom Line

The core E1a/E1b/E2 engine appears directionally correct and the reported results reproduce. I do not see an obvious PIT leak in the implemented forward window.

However, I would not publish this Scorecard result yet. The missing registered baselines, missing time-reversal canary, missing committed latest-parity test, and forked weighted-median helper are real issues for a pre-registered correctness-critical module. Fix those before treating the numbers as user-facing evidence.
