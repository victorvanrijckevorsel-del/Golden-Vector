# v3 distribution strip — adversarial review record + fixes

**Author:** Claude · **Date:** 2026-06-15 · **Branch:** `dev-vic`
**Method:** 4-lens adversarial Workflow (serve-purity · consistency · edge · tests), each HIGH/MED
finding then independently verified with a concrete trigger. Run AFTER the user asked whether I'd
actually self-reviewed v3 — I had only done a light grep-and-ship, and the panel caught a real bug the
grep could never find. Lesson: "render-only" is a claim to attack, not a reason to skip the loop.

## The core bug (found by 3 lenses independently; one held it HIGH)
The strip mixed two return bases on ONE x-axis: the **ticks** plotted the raw per-week **log-return**
alpha (`point["alpha"]` = `fwd_log_ret − fwd_bench_log_ret`), but the **median marker** plotted the
persisted `median_alpha`, which the build computes in **simple-return** space (`median(exp(α)−1)`). On a
shared axis whose lo/hi came from the log ticks, the simple-basis median was geometrically misplaced —
and at the large alphas the strip exists to surface it went **off-canvas and silently vanished** (e.g. a
+69% log spread with a +99% simple median → marker clipped past the right edge) while the aria-label
still announced "median +99%". Violates the canon "One normalize boundary for units/scale" + "Label every
number with its basis". The v3 tests missed it because the fixture used tiny alphas (0.05) where log ≈
simple to sub-pixel.

## Fixes (all applied + verified)

| # | Sev | Fix |
|---|-----|-----|
| F1 | HIGH | **Backend computes:** persist `alpha_simple = exp(α)−1` per episode (`build_episode_artifact`, `EPISODE_COLUMNS`, `_EPISODE_REQUIRED`, surfaced on points). The strip now plots + labels ticks from `alpha_simple`, so ticks and the persisted simple-return median share ONE basis (no `exp()` at the render boundary). `DIAL_SCHEMA_VERSION` 2→3. |
| F2 | MED | Clamp the median marker x into `[left, width-right]` so it can never draw off-canvas / vanish. |
| F3 | MED | Strip-basis test now uses large divergent alphas and asserts the marker x falls **within** the tick range (shared axis). |
| F4 | MED | Persisted-median test now sets the persisted median **≠** the median of the ticks (−7% vs +10%), so a serve-recompute regression fails (was a pass-by-accident: 0.05 == median of ticks). |
| F5 | LOW | Guardrail extended to forbid `/len(` / `/ len(` (hand-rolled mean) in serve; the recompute case is also caught behaviorally by F4. `sorted(` left allowed (legit display ordering). |
| F6 | LOW/NIT | New tests: GDXJ strip (reads `median_alpha_gdxj`, not gdx), all-NaN alphas → strip absent, all-negative spread → zero stays on-axis + lag colour. Suppressed the redundant `+0%` lo label on all-positive spreads (collision nit). |

## Real-run verification (post-rebuild)
`alpha_simple` present in episodes (log 0.0391 → simple 0.0399 ✓). PRU/gold_down/13w strip: persisted
median +25%, 158 ticks, marker x=398 within [42,742] — the marker now sits with the ticks it summarizes.
Lab + parity + gold-profile + page suites 86 green; ruff clean.

## Process note
The same panel verdicts: serve-purity NEEDS_CHANGES; consistency/edge/tests APPROVE_WITH_CHANGES. The
min()/max()-for-scaling line was explicitly cleared as legitimate axis geometry (matches the dots chart),
not analytics — the only real leak was the basis mismatch, now fixed in the build.
