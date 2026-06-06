# Tool A Performance — diagnosis + fix (the ~40-minute refresh bottleneck)

**Author:** Claude Code (Opus 4.8)
**Symptom:** a full refresh spends ~40 minutes in the Tool A stage alone (≈40s × 60 tickers), making the daily refresh painful.

## Root cause (read first-hand)
The slowness is **not** the math — `compute_regression` (`structural.py:527`) is already a lean closed-form numpy OLS (microseconds per call). The slowness is the **shape of the loop** in `compute_structural_window_metrics` (`structural.py:228-262`):

```
for each as_of_date (≈1300 weekly dates of history)        # line 240
    for each window (≈3)                                   # line 246
        build_trailing_window_rows(...)   # a pandas slice/filter of the weekly series  (line 247)
        compute_regression(full)          # 3 OLS fits per iteration (lines 297, 319, 327)
        compute_regression(up); compute_regression(down)
```

Per ticker that's ~1300 × 3 ≈ **3,900 iterations**, each doing a **pandas DataFrame slice** (`build_trailing_window_rows`) plus 3 regressions. × 60 tickers = **~234,000 DataFrame slices + ~700,000 regressions**, all in nested Python loops. The dominant cost is the **repeated pandas slicing** (~10ms each × 234k ≈ the 40 minutes), not the regressions. It recomputes the full *rolling history* of betas (the metric as of every week, for the detail-page time view), which is why it's O(weeks × windows × tickers).

## The fix — vectorize the rolling beta (same output, ~100-1000× faster)
A trailing-window OLS slope *is* `cov(stock, gold) / var(gold)` over that window — which pandas computes **vectorized over the whole series at once**:

- **`structural_delta` (full beta):** `stock.rolling(window).cov(gold) / gold.rolling(window).var()` — one vectorized op produces the value at **every** as_of_date, replacing ~1300 sliced loop iterations per ticker. (Identical to the centered-OLS slope `compute_regression` returns.)
- **`up_beta` / `down_beta` (regime-conditional):** the up-subset changes per window, but it's still fully vectorizable with **rolling masked sums** — with `m = (gold > 0)`:
  `beta_up = (Σ xy·m − Σx·m·Σy·m / Σm) / (Σ x²·m − (Σx·m)² / Σm)` over the rolling window, where every `Σ(...)` is a `rolling(window).sum()` of a precomputed column. Same for `down` with `m = (gold < 0)`.
- **r²/alpha** (if needed for confidence) follow from the same rolling sums.

This replaces the nested Python loop + 234k DataFrame slices with **a handful of vectorized rolling operations per ticker** (run in C). Expected: **40 min → a few seconds**, with **mathematically identical** betas (the closed-form OLS-with-intercept equals cov/var with centering).

## Optional further simplification (only if the full history isn't displayed)
If the Tool A detail page only needs the **latest** (and maybe a short recent window) rather than the full ~1300-week beta history, also compute only the as_of_dates that are actually consumed. That's a complementary reduction — **but verify what `serve/workspace_state.py` / the Tool A detail page reads from `latest_tool_a_structural_metrics_path` before trimming history.** The vectorization above is the safe primary win and works regardless.

## Must-have: a parity test (this changes core Tool A math)
Because betas feed Tool C and the whole stack, the change must be **output-identical**:
- A test that runs the **old loop** and the **new vectorized** path on the same fixture and asserts `structural_delta_core`, `up_beta_core`, `down_beta_core`, `asymmetry_ratio_core`, `downside_volatility_52w` match to a tight tolerance (e.g. 1e-9) across multiple as_of_dates and the regime-thin edge cases (windows with < min_regime_observations → None, zero gold variance → None).
- Keep the eligibility/confidence/`score_eligible` semantics unchanged.
- Re-run the full suite (Tool A + Tool C, since Tool C reuses these).

## Recommendation
This is a self-contained, high-value optimization (turns the daily refresh from ~an hour into minutes) and it's **math-sensitive**, so it should be built as its own focused task with the parity test gating it. Hand to Codex as: *"Vectorize `compute_structural_window_metrics` per this brief — rolling cov/var for the full beta, rolling masked sums for up/down betas — preserving exact output, gated by an old-vs-new parity test."* I'll review the parity proof (this is the one I'll scrutinize, like the atomic-publish and option-parity work).
