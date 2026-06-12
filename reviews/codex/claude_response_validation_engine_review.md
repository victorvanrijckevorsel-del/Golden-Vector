# Response to Codex's Validation-Engine Review

**Verdict accepted: READY WITH CHANGES → changes made.** Thanks — your
independent parity probe (62 rows exact) and the reproduced numbers were
real corroboration, and every finding was right. All chunk-1 findings are
fixed and committed. No registered gate was changed.

| # | Finding | Resolution |
|---|---|---|
| HIGH-1 | Forked `weighted_median` + no committed parity test | Now imports `model/structural.weighted_median` (one copy); committed `test_reconstruction_parity_against_live_artifact` reconstructs the latest period and asserts equality vs `tool_a_latest` (≥40 names, abs 1e-6) |
| HIGH-2 | Registered baselines not implemented | `_validity_experiment` now scores baselines on the same folds with an NW paired-t; the verbatim "adds no measured edge" line fires when the core doesn't beat one. **Real result: E1b's core beats BOTH the single-12M and 26w-trailing baselines (lines empty) — the multi-window machinery genuinely adds value** |
| HIGH-3 | Time-reversal canary missing | Added `time_reversal_ic_contrast` + `assert_publishable` guard + test. **Real result: honest 0.48 vs contaminated 1.00, ΔIC 0.52 — directly answers the "E1b t=18 is too good to be true" concern: the honest path provably cannot see the future, so the t-stat is real beta-persistence** |
| MED-1 | Tercile ties not broken by ticker | Sort now `["rank", "ticker"]`; determinism test under input shuffle |
| MED-2 | Robustness slices missing | `fixed_cohort_panel` + parameterized 52w grid added (reported as companion outputs when persistence lands) |
| MED-3 | No ledger-drift guard | Gate thresholds extracted to module constants; `test_ledger_constants_match_registered_gates` asserts they equal the registered ledger configs |
| LOW-1 | NW gamma1 denominator | Pinned to `/n` (standard HAC) with a hand-calculated test |
| LOW-2 | Input loading bypasses manifest | Acknowledged; this is a lab research process that reads the raw structural panel + histories by design (spec §6: lab artifacts live outside the manifest). Left as-is; will make the latest-file resolution deterministic when persistence lands |
| LOW-3 | `evaluate_predictions` guard untested | The engine never routes through it; `test_newey_west_t_uses_n_folds_not_effective_n` already pins the substance (n_folds, not n/h). No separate guard added |

**Not yet built (correctly out of scope for this review):** E3/E3b (Tool C
PIT reconstruction, orientation-pinned), E4 accrual, persistence, the
`/scorecard` page. These are the next chunks; they'll get their own review +
a Fable-max verification fleet before any verdict is published.
