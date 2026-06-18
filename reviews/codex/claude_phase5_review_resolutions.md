# Resolutions — Codex review of the Phase 5 backtest spec

Date: 2026-06-18
Source: `reviews/codex/codex_review_phase5_backtest_spec.md` (Codex; verdict **NEEDS CHANGES**, 7
blockers + 5 MEDIUM + 2 LOW). Applied by Claude to the spec → **v3** (no product code touched; this is
a planning doc). Codex's two code claims were verified first-hand before applying:
`validation.py` already has `spearman_ic`/`newey_west_t`/`tercile_portfolio_spread`; `requirements.txt`
has no scipy/sklearn/statsmodels — both true.

## Blocking list → resolutions

| # | Codex blocker | Resolution (spec §) |
|---|---------------|---------------------|
| 1 | Fold geometry open while lag-1 NW-t assumes disjoint folds; no cross-fold label-overlap assert | **Froze** `min_train_weeks=260, test_weeks=1, step_weeks=H` (single as-of obs one horizon apart → lag-1 valid), stamped expected counts (≈74 H=8 / ≈45 H=13), added `assert_no_test_label_overlap_across_folds` (§1 As-of grid). |
| 2 | Gauntlet includes constant baselines undefined under Spearman; E2 baseline missing | Dropped equal-weight + buy-and-hold to **reported references** (IC≡0), paired gauntlet now **4 real baselines, beat ≥3 of 4**, each registered with label/benchmark/orientation/missing-policy/statistic; E2 all-history convexity baseline defined (§3, §2 E2). |
| 3 | N_eff required-IC not a binding gate | New **gate 6** on every experiment: `|IC| ≥ required_ic_floor AND IR_ceiling ≥ 0.3` else cap at PARTIAL; full derivation frozen (§4, §6). |
| 4 | Ledger can't do role/family/DSR denominator; "DSR diagnostic but floor" contradiction | Added `trial_family_id` + `role` (headline/robustness) + `dsr_n_trials` (phase-wide role-aware count, a small ledger extension in §8); DSR now **reported, caps performance wording only**, not a gate (§1). |
| 5 | E4 grain unpinned; verdict precedence ambiguous; NULL overclaims | Pinned E4 grain (GDX, 8w, gold-down scope, label at feature grain) + an **ordered verdict-precedence table** (canary→SUPPORTED→INCONCLUSIVE→NULL-only-if-measurable→PARTIAL/NOT-SUPPORTED) so the NULL ships only on a measurable incremental fail (§2 E4, §6). |
| 6 | E2 forward-asymmetry label not buildable | Defined exactly: per-name mean `fwd_alpha_gdx_Hw` in forward gold-up test episodes − mean in gold-down, ≥4 per side, ≥15 names/fold coverage, skip+report otherwise (§2 E2). |
| 7 | Ledoit–Wolf N_eff formula/dependency unpinned (repo is numpy/math-only) | Pinned a **pure-numpy** Ledoit–Wolf shrinkage toward constant-correlation + participation ratio `(Σλ)²/Σλ²`, with frozen return input (trailing-104w-beta residuals), window (as-of 2024-12-27), and missing-data policy — **no new dependency** (§4). |

## MEDIUM / LOW → resolutions
- **Scorecard schema/render contract** — enumerated required artifact fields + a scorecard-v2 bump (or separate reader) + render-level tests for N_eff/DSR/canaries/caveat/NOT-tested (§8). 
- **GDXJ scope** — every label is "vs GDX"; GDXJ-relative is deferred robustness + on the NOT-tested list (§0, §10).
- **Convexity `>0` threshold** — added "absolute convexity sign/threshold as a classifier" to NOT-tested (§0).
- **Noise ceiling** — pinned Spearman–Brown-corrected `2r/(1+r)` (raw reported too) + min names/folds (§1).
- **p-values** — added a pure-python `t_to_p_one_sided(t, df)` to the new-code list (§8).
- **One-copy (LOW)** — corrected the v2 error: `newey_west_t`/`tercile_portfolio_spread` already exist in `validation.py` → **reuse/extract, not new** (§8).
- **Scorecard copy (LOW)** — Phase-5 section scoped to "these behaviour-engine lenses", not "every ranking the product shows" (§8, §0).

## §11 questions → Codex's answers, now frozen in v3
Target IR 0.3 / transfer 0.5 (co-signed); lag-1 valid given the frozen fold geometry; DSR
reported-not-gated; fold params `260/1/H`. **No open design questions remain** — only the mechanical
freeze step: compute N_eff on the pinned pre-window, publish the numeric `required_ic_floor`, co-sign
it, then register the variant configs.

Spec is now **proposed FREEZE-READY** (v3) pending Codex's re-confirmation of the v3 deltas.
