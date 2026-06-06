# Plan — Vectorize Tool A structural metrics (kill the ~65-minute refresh stage)

**Author:** Claude Code (Opus 4.8)
**Status:** for Codex review, then build.
**Measured impact:** in the 2026-06-05 refresh, **Tool A took ~65 of the ~70 total minutes** (update-data 3.5m, Tool A 65m, Tool B 2s, Tool C 13s, Tool D 4s, options 32s). Tool A is ~93% of refresh time. This plan targets only Tool A's structural-metric computation; everything else is already fast.

## 1. Root cause (verified first-hand)
`compute_structural_window_metrics` (`golden_vector/model/structural.py:228-262`) is a nested Python loop:
```
for as_of_date in weekly_series.as_of_date.unique()   # ≈1300 weeks (each week has its own as_of_date, line 202-207)
    for window_id in scoring.structural_windows        # ≈3 windows
        build_trailing_window_rows(...)                # a pandas slice/copy of the weekly series (line 474-484)
        compute_regression(full); compute_regression(up); compute_regression(down)   # 3 OLS fits
```
Per ticker ≈ 1300 × 3 ≈ **3,900 iterations**, each doing a **pandas DataFrame slice+copy** plus 3 regressions; × 60 tickers ≈ **234,000 slices + ~700,000 regressions**. The regression itself (`compute_regression`, `:527`) is already a lean closed-form numpy OLS (fast); **the dominant cost is the ~234k pandas slice/copy calls** (≈10ms each ≈ the 65 minutes). This recomputes the *full rolling history* of betas (the metric as-of every week).

## 2. The critical subtlety — windows are CALENDAR-based, not fixed-N-weeks
`_window_start` (`:633-639`) returns `as_of - DateOffset(months=N)` or `DateOffset(years=N)`. `build_trailing_window_rows` (`:482-484`) keeps weeks with `as_of_date ∈ (trailing_start, as_of]`. So each window is a **calendar trailing window** (e.g. "last 12 months", "last 3 years"), whose **number of weeks varies** (51/52/53, gaps, leap years). Therefore:
- A naive `Series.rolling(N).cov()/.var()` (fixed N rows) would **NOT** reproduce the exact weeks → would fail a strict parity test.
- A pandas time-offset rolling (`.rolling('1095D')`) is close but uses **fixed days**, not calendar `DateOffset(years=N)` → tiny boundary differences around leap years → also risks parity failure.
- **The exact-and-fast approach is prefix-sums + `searchsorted`** (below), which reproduces the identical calendar window weeks.

## 3. The fix — prefix-sum (cumulative-sum) + searchsorted, vectorized per ticker
For one ticker's weekly series (already sorted by week date), precompute these aligned arrays once:
`n=1`, `x=gold_ret`, `y=stock_ret`, `xy=x*y`, `xx=x*x`, `yy=y*y`, and regime-masked copies for up (`mu = x>0`) and down (`md = x<0`): `n_u=mu`, `x_u=x*mu`, `y_u=y*mu`, `xy_u=xy*mu`, `xx_u=xx*mu` (and the down analogues).
Take **prefix sums** (`np.cumsum`, prepend 0) of each → `P_n, P_x, P_y, P_xy, P_xx, P_yy` and the up/down sets.

For each window `w` and each as-of index `i`:
- `trailing_start_i = week_date_i - DateOffset(window)` (vectorized over all i, per window).
- `start_idx_i = searchsorted(week_dates, trailing_start_i, side='right')` (first week with date > trailing_start; vectorized).
- Window sum of any accumulator `A` = `P_A[i+1] - P_A[start_idx_i]`. (All vectorized array ops — no Python loop over weeks.)

Then the closed-form **OLS-with-intercept** (identical to `compute_regression`'s centered estimator):
- `n = Sn` (week count in window), `Sxx_c = Sxx - Sx²/n`, `Sxy_c = Sxy - Sx·Sy/n`, `Syy_c = Syy - Sy²/n`.
- `structural_delta (beta) = Sxy_c / Sxx_c`  → **None when `n < 2` or `Sxx_c <= 0`** (matches `INSUFFICIENT_HISTORY` / `MISSING_GOLD_VARIANCE`).
- `intercept_alpha = Sy/n - beta·Sx/n`.
- `r_squared = clip(beta·Sxy_c / Syy_c, 0, 1)` when `Syy_c > 0` else `0.0`.
- `up_beta` / `down_beta`: same formula on the regime-masked sums, using the regime week count `n_u`/`n_d`, returned **None unless `n_u/n_d >= minimum_regime_observations_for_window(window)`** (matches lines 315-333).
- `asymmetry_ratio_core = down_beta - up_beta` when both present (matches line 341-342; preserve the existing `abs(down_beta) < 1e-9` guard at line 346 if it gates anything).
- `week_count = n`; `window_status = ELIGIBLE if n >= minimum_observations_for_window else LOW_OBSERVATION`; `n < 2 → INELIGIBLE/INSUFFICIENT_HISTORY` (matches `_empty_window_metric`, lines 287-296, 335-336).
- `issue_summary` per as-of (the 3-year normalization-issue summary, `summarize_normalization_issues` `:487-509`) — vectorize or keep, but it's cheap; can stay a light pass.

Assemble into a DataFrame with **exactly `STRUCTURAL_WINDOW_COLUMNS`** in the same row order (ticker × as_of × window). Replace the body of `compute_structural_window_metrics` with this; keep the public signature identical.

**Expected: ~65 min → a few seconds.** Output is mathematically identical (cumulative-sum windowing reproduces the same weeks; closed-form OLS equals the centered estimator).

## 4. Also assess `compute_volatility_diagnostics` (`:370-447`)
It loops `for (ticker, as_of_date) ...` computing `annualize_weekly_volatility` / `annualize_downside_volatility` (52-week std × √52). With ~1300 as-of × 60 tickers it's a second per-as-of loop. Std is cheaper than 3 regressions, so it may not dominate — **measure it; if it's a meaningful chunk, vectorize the same way** (rolling/prefix-sum of Σr, Σr², count over the 52-week window for the full std; downside std needs masked sums on `r<0`). If it's <a few seconds total, leave it. Don't change the volatility definition.

## 5. Parity test (the gate — this changes core Tool A math that feeds Tool C and the stack)
- Keep the **old loop implementation available as a reference** (e.g. rename to `_compute_structural_window_metrics_reference` or a test fixture) and assert the new vectorized output **equals** it.
- Fixture: a realistic multi-year weekly series (incl. gaps, a leap-year boundary, a thin-up-regime stretch, a near-zero-gold-variance stretch). Assert per-(as_of,window) equality of `structural_delta`, `intercept_alpha`, `r_squared`, `up_beta`, `down_beta`, `asymmetry_ratio_core`, `week_count`, `window_status`, `window_reason`, and the `None` placements — to tolerance **1e-9** for floats, exact for statuses.
- Edge cases asserted: `n<2` → INSUFFICIENT_HISTORY None; `Sxx_c<=0` → MISSING_GOLD_VARIANCE None; regime `n_u/n_d < min` → up/down None; `Syy_c<=0` → r²=0.
- Re-run the **full suite** (Tool A + Tool C, since Tool C reuses `build_structural_weekly_series` — note that builder is **unchanged**, so Tool C is unaffected, but verify).
- Optional but ideal: a tiny benchmark assertion or logged timing showing the speedup.

## 6. Scope / non-goals
- **In scope:** rewrite the *body* of `compute_structural_window_metrics` (and maybe `compute_volatility_diagnostics`) to vectorized prefix-sum form. Same inputs, same outputs, same columns, same eligibility/threshold semantics.
- **Out of scope / do NOT change:** the window definitions/config (`structural_windows`, `_window_start`), the confidence/eligibility thresholds, `score_eligible` logic, `build_structural_weekly_series` (the weekly builder — leave it; Tool C depends on it), the persisted schema, or any downstream consumer. No model/behaviour change — purely a speed rewrite.
- Confirm whether `RegressionResult.residuals` is consumed anywhere; if only `beta/alpha/r²` feed the output columns, the vectorized path need not materialize residuals.

## 7. Risk / rollback
- The risk is a subtle numeric or boundary mismatch (especially the `searchsorted` side and the inclusive/exclusive window edges, and the regime-min gates). The **old-vs-new parity test is the guardrail** — it must pass to 1e-9 before the old loop is removed. Keep the reference impl until parity is green, then delete.
- Float accumulation order differs (cumsum vs per-window sum), so use float64 and a 1e-9 (not exact) tolerance; if any column needs bit-exactness, note it.

## 8. Build order
1. Add the prefix-sum/searchsorted vectorized implementation alongside the old one (don't delete the old yet).
2. Add the parity test (old vs new) + edge-case tests; iterate until green to 1e-9.
3. Measure Tool A stage time before/after (log it).
4. Assess `compute_volatility_diagnostics`; vectorize if it's a meaningful share.
5. Switch the build to the vectorized path; keep the reference only in the test; remove the dead loop.
6. Full suite green. Stop for review.

---

## Self-review (Claude)
**Grade of this plan: READY (with the two risks below called out for Codex).**

What I'm confident about:
- The diagnosis is verified first-hand (the loop, the calendar windows, the per-week as_of_date, the lean regression). Tool A = 65/70 min is measured, not guessed.
- The closed-form OLS from sufficient statistics (n, Σx, Σy, Σxy, Σx², Σy²) is exactly the centered OLS `compute_regression` computes — same beta/alpha/r². This is standard and safe.
- The prefix-sum + searchsorted approach reproduces the **exact** calendar-window weeks, which the naive `rolling(N)` / `'365D'` approaches would not — that's the key insight that makes parity achievable, and the reason I rejected the simpler-looking rolling-cov approach from my initial brief.

The two real risks I'd flag to Codex (and verify in review):
1. **Window-edge exactness.** `build_trailing_window_rows` uses `as_of > trailing_start` (strict) and `<= as_of`. The `searchsorted(..., side='right')` on `trailing_start` must reproduce that strict-greater boundary exactly, including when a week's date equals `trailing_start` (DateOffset can land exactly on a week date). The parity test must include a fixture where `as_of - DateOffset` lands exactly on an earlier week date, to pin the boundary.
2. **Numerical stability of the centered sums.** `Sxx - Sx²/n` via prefix-sum subtraction can lose precision vs the per-window centered computation when values are tiny (weekly log-returns ~0.0x). 1e-9 tolerance should hold, but if a column ever fails parity, switch that accumulator to a more stable form (e.g. Welford or compute around a shifted origin). Flagged so it's not a surprise.

Minor: the `issue_summary` and `window_status`/`window_reason` strings must match exactly (they're not numeric — exact string parity), and the output **row order** must match (ticker × as_of × window) so any positional test passes. Both are easy but worth an explicit assertion.

Net: the plan is implementation-ready, the parity test is the correct gate, and the two risks are bounded and test-catchable. I'd build it.
