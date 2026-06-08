# Claude review — Portfolio M4 (hedge sizing, correlation, value-over-time, reconciliation CSV)

**Reviewer:** Claude Code (Opus 4.8), first-hand — read `m4_artifacts.py` in full, the pipeline integration, the serve rendering, the manifest registration, and the CSV endpoint; ran the suite.
**Scope:** M4 — the GDX/GDXJ hedge-sizing card, the correlation map + paired-exposures, the value-over-time chart, the reconciliation CSV export (plus the M2/M3 F5 follow-up).
**Verdict: APPROVE — excellent, faithful M4, and the honesty discipline is exemplary.** The hedge-sizing math (the piece I most wanted to check) is correct and fail-closed. Minor findings below; none block. **This completes the planned portfolio milestones (M1–M4).**

## Verified first-hand — the hedge-sizing math (the high-risk piece)
- `effective_gold_exposure = Σ(value_usd × down_beta_core)` over **Measured-beta** positions only. (`m4_artifacts.py:360-368`)
- `modeled_short_notional = effective_exposure / benchmark_down_beta`; `modeled_put_contracts = ceil(notional / (benchmark_price × 100))`. Dimensionally and logically correct — dividing by GDX's (lower, large-cap) beta scales the notional **up** to match the book's gold sensitivity. (`:159-160`)
- **Fail-closed**: `hedge_status = UNAVAILABLE` when `benchmark_status != OK`, or beta ≤ 0 / missing, or price ≤ 0 / missing. The page then shows **"GDX hedge size unavailable"** with the reason, never a divide-by-bad-number. (`:149-157`, `portfolio_page.py:162-200`)
- Labeled **"modeled hedge size only"**, never "recommended"; carries the basis-risk note ("GDX/GDXJ are sector proxies… can under-cover high-beta small-caps… a modeled hedge size, not a recommendation"). (`:13-16`)

## Verified first-hand — the rest of M4
- **Correlation:** pairwise daily-return correlation over covered names; **honest gates** — `INSUFFICIENT_HISTORY` under 30 overlapping observations, `UNAVAILABLE` on zero-variance/NaN, never a fabricated number. Heatmap + a top **paired-exposures** table (ranked by combined NAV weight), with the caveat **"In a gold selloff, correlations often move toward 1.0."** (`build_correlation_frame`, `portfolio_page.py:209-258`)
- **Value-over-time:** current `total_shares` valued back over each covered name's `close_usd`, intersected to dates where **all** covered names have data (no gaps), SVG coords **precomputed in the backend**. Labeled exactly right: **"Market value of today's holdings, covered names (X% of book) — not profit/loss."** Honest about what it is and what it covers. (`build_value_history_frame`, `portfolio_page.py:270-306`)
- **Reconciliation CSV:** raw lots joined to canonical positions, written atomically as `.csv` (`write_portfolio_csv_pair`), exposed via a "Download reconciliation CSV" link. The `/portfolio/reconciliation.csv` endpoint is **gated behind `portfolio.enabled`** (403 when off) — the new privacy surface is correctly closed. (`build_reconciliation_export_frame`, `workspace.py:144-159`)
- **Architecture intact:** all four M4 frames built in the backend pipeline (loading `normalized_equity_histories`), persisted via `write_portfolio_artifact_pair`, registered in `PORTFOLIO_ARTIFACTS` + the manifest, and read by `reader.py` via `resolve_current_model_artifact_path`. The serve page only reads + renders. Backend-computed / serve-reads-only holds.
- **M2/M3 F5 resolved:** the summary panel now states **"NAV = entered stock positions; broker cash is added at import."**

## Findings (minor — none block)
**F7 — MINOR (test coverage): the hedge-sizing math + fail-closed paths have no dedicated test.** The two M4 tests cover artifact-writing + value-history coverage, but not (a) `notional == exposure / beta` on known inputs, (b) `hedge_status == UNAVAILABLE` when the benchmark is non-OK / beta missing, or (c) correlation `INSUFFICIENT_HISTORY` under 30 obs. The hedge math is the highest-risk M4 piece — add one focused test for the arithmetic + the fail-closed branch.

**F8 — NOTE: the value-over-time line is bounded by the *shortest* covered history.** `dropna(how="any")` keeps only dates where every covered name has data, so the recently-added Astral/Celsius (~1y) cap the whole line to ~1y even though older names have decades. This is honest (no gaps), but a beginner may wonder why the line is short — consider a one-line note ("window limited by the newest holding") or, later, an option to show the longest-common-window per subset.

**F6 (carryover) — NIT: redundant weight column likely lingers.** The UI now consistently uses `nav_weight_fraction`, but the M1 `position_weight_fraction` column probably still exists in the positions artifact alongside it. UI is consistent; the artifact column is just redundant. Drop it or comment it when convenient.

**(opt) correlation paired-exposure ranks by combined NAV weight, not correlation×weight** — fine for an all-correlated gold book (everything's ~0.7–0.9), but for a mixed book it would surface big-but-uncorrelated pairs. Acceptable; note it.

## Bottom line
A careful, honest M4 that completes the portfolio tool: correct + fail-closed hedge sizing (modeled, not recommended, with basis risk stated), honest correlation (real-history-gated, selloff caveat, paired-exposures), a value-over-time chart that tells the exact truth about what it shows, and a reconciliation CSV behind the privacy gate — all backend-computed, manifest-registered, serve-reads-only. Address **F7** (a hedge-math + fail-closed test); **F8/F6/correlation-rank** are notes/nits. **M1–M4 are now all built and reviewed.**

_Full suite: **829 passed** (up from 826 at M2/M3), zero regressions._
