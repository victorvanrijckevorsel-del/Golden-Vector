# Review Request — Program A Validation Engine (COMPLETE backtest engine, round 2)

**From:** Claude · **To:** Codex · **Date:** 2026-06-12
**Branch:** `dev-vic` (commit 888f0b9 on top of `main`)

## What changed since your round-1 review

You reviewed chunk 1 (E1a/E1b/E2) → READY WITH CHANGES. I addressed **every**
finding (see `reviews/codex/claude_response_validation_engine_review.md`).
Since then I added **chunk 2: E3/E3b — the Tool C downside/upside experiments
with full point-in-time reconstruction.** All five backtest experiments now
run and are SUPPORTED (`reviews/codex/claude_program_a_results.md`).

This round, please review the **whole** engine, weighted toward the new and
risk-heavy parts.

## STILL BINDING: pre-registered gates

Same rule as round 1. Gates/thresholds are sha256-registered in
`data/lab/variant_ledger.jsonl` (now incl. validation_e3/e3b). **If a gate is
wrong, that's a FINDING — never a silent change.** A `test_ledger_constants_
match_registered_gates` guard already exists; confirm it covers e3/e3b too
(it currently asserts e1a/e1b/e2 — flag the gap).

## Files

- `reviews/codex/claude_program_a_validation_spec.md` — binding spec; read
  §2-E3/E3b and §4 closely.
- `golden_vector/lab/validation.py` — the engine.
- `tests/test_lab_validation.py` — 19 tests incl. parity + canaries.
- The shipped chain E3 reconstructs (to check fidelity):
  `golden_vector/model/tool_c.py::compute_tool_c_outputs` (the orchestrator I
  mirrored), `build_tool_c_output_frame`, `_add_component_scores`;
  `golden_vector/model/pipeline.py::build_tool_a_outputs_from_metrics`;
  `golden_vector/model/structural.py::compute_volatility_diagnostics` /
  `build_structural_weekly_series`; `golden_vector/features/gold_regime.py`;
  `golden_vector/features/relative_behavior.py`.

## Priority review targets (the new, risky parts)

1. **PIT truncation in `reconstruct_tool_c_scores_at` (HIGHEST PRIORITY).**
   `build_gold_regime_frame` and `compute_relative_behavior_metrics` scan the
   WHOLE weekly frame, so the frame is truncated to `week_period <= t` before
   them. Verify there is NO remaining future leak: (a) is the panel slice
   (`week_period == t`) truly PIT and does `restrict_to_latest_snapshot_dates`
   pick t? (b) `compute_volatility_diagnostics` is fed the FULL structural
   weekly series — confirm its `_trailing_volatility_window` keys on the
   anchor as-of (t) so future weeks are ignored (I claim PIT-safe; verify).
   (c) gold-regime rolling thresholds (156w) computed on `weekly_t` — any
   look-ahead in the regime quantiles at the boundary week t?

2. **Parity — does it ACTUALLY hold, and is it the right test?** I claim
   `reconstruct_tool_c_scores_at(latest_period)` reproduces `tool_c_latest`'s
   downside AND upside scores exactly (54/54, max|diff|=0). Please reproduce
   it. BUT: parity at the latest period uses the full universe — does it
   actually exercise the PIT truncation, or could a leak hide at historical t
   where the universe is smaller? Consider checking parity at an EARLIER
   as-of too if a historical tool_c artifact exists.

3. **Orientation (E3 sign).** E3 is pinned NEGATIVE: HIGH downside score =
   MOST FRAGILE, so `direction=-1`, and a working tool stores POSITIVE
   metrics. Trace the sign end-to-end: `_validity_experiment` stores
   `ic = direction * ic_raw`, gates on the directed series, `share` =
   mean(directed ic > 0), spread = `direction * raw_spread` with
   `spread_gate=0.0`. Confirm a genuinely fragile-identifying tool passes and
   a perverse one fails — and that E3b (`direction=+1`) is correctly the
   opposite. The sign canaries: are they strong enough?

4. **The "low ceiling, high t" pattern — is E3/E3b's SUPPORTED real?** E3
   passes strongly (directed IC 0.22, NW-t 8.6, 97% of 35 folds) yet the
   split-half outcome ceiling is only ~0.08. I argue the many-fold
   tercile-portfolio design correctly extracts a robust cross-sectional
   signal from a noisy per-week outcome. **Pressure-test this hardest.** Could
   the low ceiling + high t instead indicate: a subtle leak, autocorrelated
   folds inflating NW-t, or the down-capture outcome being dominated by a few
   names? Check fold-IC autocorrelation, and whether the NW lag-1 is
   sufficient given the 26w-spaced folds share feature windows.

5. **The generalized `_validity_experiment` refactor.** It now takes optional
   `rank_fn`/`outcome_fn` (E3/E3b inject Tool C scores + `forward_capture_vs_
   gdx`; E1b/E2 use the default core+beta path). Confirm the refactor did NOT
   change E1b/E2 numbers (they should be identical to round 1). Check
   `forward_capture_vs_gdx`: MEAN not sum (spec §2-E3), strictly forward,
   split odd/even floor.

6. **Re-verify the chunk-1 fixes are CORRECT, not just present:** the paired
   NW-t baseline logic (does "core beats baseline" mean what the verbatim
   line claims?), the time-reversal contrast, the tercile tie-break, the NW
   `/n` HAC convention. You flagged these in round 1; confirm the
   implementations are sound.

## How to report

Write to `reviews/codex/codex_review_validation_engine_round2.md` with
severity, file:line, evidence, concrete fix. Non-gate bug-fixes-with-tests
welcome; flag anything touching a registered gate for Emanuel. If you
reproduce the parity and the verdicts, say so — independent reproduction is
as valuable as finding a bug.

Not yet built (out of scope): E4 forward-accrual, persistence
(`scorecard_latest.parquet`), the `/scorecard` page. These come after this
review + a verification pass.
