# Codex Build Brief — Candidate Finder (self-contained)

**For:** Codex
**From:** Claude Code (Opus 4.8)
**Branch:** `dev-vic`
**Full spec (read for schemas/math detail):** `reviews/codex/claude_candidate_finder_plan_v2.md` — **read it including §12 (self-review refinements); §12 supersedes earlier sections where they conflict.** This brief is self-contained enough to build from; the plan has the long-form rationale.
**Status:** reviewed both sides (Codex review of v1 → my v2 → my §12 self-review). Build-ready.

## 0. Pre-flight
Confirm branch `dev-vic`; `pytest -q` baseline (should be 586). First **confirm the plan is sound against the current codebase.** If any instruction is wrong/infeasible, **STOP and write it up** rather than improvising.

## 1. What it is
A point-and-click **multi-criteria screener / candidate finder**. The user picks criteria, sets ascending/descending direction and a weight for each, picks top-N, and optionally a preset lens (bearish/bullish). It produces:
- **View 1** — per-category top-N lists ("top 10 by AISC", "top 10 by down-beta", …).
- **View 2** — a **blended weighted ranking** with a 0–100 **score**, plus each name's per-criterion percentile and a "top-N tally", to surface the best names to **buy puts (or calls) on** as a gold-down (or gold-up) bet.
The score is **"fit to your criteria — not a return forecast."**

## 2. Locked decisions (do NOT re-litigate)
- **Percentile-based blended score**, equal-weight default, user-adjustable weights.
- **One shared `oriented_percentile` helper** (§5) — the SAME one Tool C/D will use.
- **Side-aware "usable options" filter = REUSE `is_usable_candidate()`** from `golden_vector/hedge/options_liquidity.py`. **Do NOT write a second "usable" definition.**
- **Missing-data rule is deterministic** (§6) — `min_criteria_fraction = 0.67` to be rank-eligible; low-coverage rows shown but sorted beneath eligible rows.
- **Mixed-refresh warning** when source refresh runs disagree (§8).
- **Config-driven criteria registry**, registered in `EXPECTED_CONFIG_FILES` (§10).
- **Equity = market cap** for derived ratios (§9) — computed from existing Tool B fields, no new data.
- **Defer** per-criterion threshold filters from v1 (the side-aware options filter is the only filter).
- **Build on existing data now;** Tool C/D criteria plug in later as config entries (no rework). "Adding a criterion is a YAML edit" ONLY when its source field already exists in the joined frame; new metrics/sources need loader+scorer code.
- **Descriptive, not predictive.** No "recommended/best/should buy" language; the rank is a fit score.

## 3. Curated criteria registry (config: `candidate_finder.yaml`)
Each entry: `id, label, source_field, group, default_direction (high_good|low_good), unit`. v1 set:
| Group | Criterion | Source field | Default "good" |
|---|---|---|---|
| Sensitivity | Down-beta | `down_beta_core` | high (put thesis) |
| Sensitivity | Up-beta | `up_beta_core` | high (call thesis) |
| Sensitivity | Gold beta (core) | `structural_delta_core` | high |
| Sensitivity | Downside volatility | `downside_volatility_52w` | high = riskier |
| Quality | Confidence | `confidence_score` | high |
| Fragility | AISC | `aisc_usd_per_oz` (manual store) | high = fragile / low = safe |
| Leverage | Net Debt / EBITDA | `leverage` | high = riskier |
| Leverage | Debt / market cap | `debt_to_mktcap` (derived) | high = riskier |
| Valuation | EBITDA / market cap | `ebitda_to_mktcap` (derived) | high = cheap |
| Valuation | Revenue / market cap | `revenue_to_mktcap` (derived) | high |
| Valuation | EV/EBITDA | `ev_ebitda` | low = cheap |
| Valuation | Forward P/E | `forward_pe` | low = cheap |
| Valuation | FCF yield | `fcf_yield` | high = cheap |
| Upside | Best upside % | `best_upside_pct` | high |
| Size | Market cap | `market_cap_musd` | (either) |
| Options | IV percentile | `iv_percentile_cross_sectional` | low = cheaper |
| Options | IV skew | `iv_skew_60d` | high = crash-risk priced |
| Options | **Usable puts / Usable calls** | via `is_usable_candidate()` | **filter, not a rank** |
| *(future)* | Tool C/D downside-risk rank, fragility rank, headroom | Tool C/D | added when those exist |

## 4. Derived market-cap ratios (equity = market cap)
Computed in the data layer from existing Tool B + manual fields (guard `market_cap_musd > 0`; null not zero):
`debt_to_mktcap = net_debt_musd / market_cap_musd`, `ebitda_to_mktcap = forward_ebitda_musd / market_cap_musd`, `revenue_to_mktcap = forward_revenue_musd / market_cap_musd`, `netincome_to_mktcap = forward_net_income_musd / market_cap_musd`.

## 5. The scoring engine (the heart — pure, testable)
- **`oriented_percentile(series, *, high_good) -> Series`** (in `features/percentile_ranks.py`, shared with Tool C/D):
  `series.rank(pct=True, ascending=high_good, method="average") * 100`. Missing excluded from the pool (NaN in → NaN out). This is the SINGLE convention — do not also use `100 − x` inversion.
- **Percentile peer group = the POST-filter set** (§12 #1): compute percentiles over the names surviving the hard options filter, not the whole universe. View 1 and View 2 use the same pool.
- **Blended score:** `score(s) = Σ_{i∈present(s)} wᵢ·Pᵢ(s) / Σ_{i∈present(s)} wᵢ`, weights normalized over selected criteria, renormalized over present.
- **Top-N tally:** count of selected categories where the name is in the top-N.
- **Required tests:** high-good, low-good, ties (average), all-missing (→NaN), one-value (→100), negative values, missing-data renormalization.

## 6. Missing-data rule (deterministic)
`criteria_fraction = present/selected`. A row is **rank-eligible** only if `criteria_fraction ≥ 0.67` (config). **Rank-ineligible rows are shown but ALWAYS sorted beneath all eligible rows**, regardless of raw score, with a visible "scored on K of N" flag. (Prevents a 1-of-5 name topping the list.) Score-ineligible Tool A betas (`score_eligible=False`) are treated as **low-confidence/missing** for those beta criteria (§12 #8).

## 7. Filters
- **Side-aware "usable options"** (primary): inputs `has_usable_put_candidate` / `has_usable_call_candidate`, true only when a side candidate passes **`is_usable_candidate()`** (Tradable tier + sensible moneyness). **Options side is its own toggle (puts / calls / either)** that the preset lens initializes but the user can change independently of criterion directions (§12 #3). "thin/no-usable" names are excluded for that side.
- Per-criterion threshold filters: **deferred** (not in v1).

## 8. Freshness / mixed-refresh (do not just rely on a cache key)
On load, compare refresh run ids: Tool A `snapshot_refresh_run_id`, Tool B `snapshot_refresh_run_id`, options manifest `refresh_run_id`, manual-store hash (heterogeneous — compare what exists). If they disagree, render a loud banner **above** the rankings naming which source is out of step ("rankings mix data from different refreshes — re-run the tools"). Default = warn loudly (not hard-block). The composite cache key still prevents stale-cache reuse.

## 9. The two views + UX
- **View 1** — per-category top-N lists.
- **View 2** — blended ranking table: score, per-criterion percentiles, top-N tally, "scored on K of N" flag, **eligible block above a low-coverage block**. Weight sliders re-rank live.
- **Preset lenses** (convenience): Bearish/put (down-beta high, AISC high, IV %ile low, usable-puts side…) and Bullish/call (up-beta high, AISC low, FCF yield high, usable-calls side…). Sets sensible directions + the options side; user-overridable.
- **Screen spec in the URL** (GET, no mutation, bookmarkable).
- **Input guards (§12 #4):** empty criteria selection → "pick at least one criterion"; all-zero/unset weights → equal weights; single criterion → score = that percentile. Never crash/divide-by-zero.
- **Score tooltip (§12 #5):** "Score = your weighted-average percentile across the criteria you chose (0–100). Higher = better fit. Not a return forecast."
- Server-side math only; DataTables for display.

## 10. Config registration (R5 — required, with tests)
Add `config/candidate_finder.yaml` + `CandidateFinderConfig` in `contracts/config_models.py` + the `candidate_finder` field on `AppConfig`, AND register `("candidate_finder","candidate_finder.yaml")` in `app/config.py::EXPECTED_CONFIG_FILES` so it's validated + hashed into provenance. Test that it loads.

## 11. Module layout
```
golden_vector/
  features/percentile_ranks.py     # NEW — shared oriented_percentile (reused by Tool C/D)
  model/candidate_finder.py        # NEW — pure scoring engine (blend, rank-eligibility, tally, missing-data)
  serve/candidate_finder_data.py   # NEW — join latest A/B/options/manual + derived ratios + side-aware usable flags + refresh-alignment + cache
  serve/candidate_finder_page.py   # NEW — builder controls + View 1 + View 2 + presets
  serve/workspace.py               # EDIT — /candidate-finder route + nav
  serve/page_shell.py              # EDIT — nav entry
  contracts/config_models.py       # EDIT — CandidateFinderConfig + AppConfig field
  app/config.py                    # EDIT — register candidate_finder.yaml
  cli.py                           # EDIT — `candidate-finder` command (spec file → ranked parquet)
config/candidate_finder.yaml       # NEW — criteria registry + presets + defaults (top_n=10, min_criteria_fraction=0.67)
tests/  test_percentile_ranks, test_candidate_finder_scoring, test_candidate_finder_data, test_candidate_finder_routes, test_candidate_finder_config
```

## 12. Build order (batched; checkpoints = stop & report)
- **Batch 1 — config + scoring engine:** `candidate_finder.yaml` + `CandidateFinderConfig` + register in `EXPECTED_CONFIG_FILES` (test it loads); the shared `oriented_percentile` helper + full test matrix; the pure `candidate_finder` engine (blend, rank-eligibility, tally, deterministic missing-data). → **CHECKPOINT A: stop & report.**
- **Batch 2 — data layer + CLI:** `candidate_finder_data.py` (join latest outputs + derived market-cap ratios + side-aware usable flags via `is_usable_candidate()` + refresh-alignment status + composite cache); `candidate-finder` CLI (spec file → ranked parquet). Tests incl. a mixed-refresh case. → **CHECKPOINT B: stop & report** (paste sample ranked output).
- **Batch 3 — UI tab:** builder controls, View 1 + View 2 (eligible vs low-coverage split), preset lenses, lens-aware usable-options toggle, URL spec, mixed-refresh banner, score tooltip, input guards. → **CHECKPOINT C: completion report.**

## 13. Acceptance criteria
- Tab + CLI produce View 1 + View 2 from structured data, **server-side math only.**
- Options filter is **side-aware via `is_usable_candidate()`** (no second definition); puts for bearish, calls for bullish; "thin" excluded for that side.
- Equal-weight default; weight changes re-rank; percentiles oriented via the **single** `oriented_percentile` contract (tested matrix), computed over the **post-filter** pool.
- Rows below `min_criteria_fraction` are rank-ineligible and **sorted beneath** eligible rows, with a visible flag.
- Derived market-cap ratios correct (market_cap>0 guard; null not zero).
- `candidate_finder.yaml` registered in `EXPECTED_CONFIG_FILES`, validated into `AppConfig`, hashed into provenance (tested).
- Mixed-refresh condition renders a loud warning above the rankings (tested).
- Score labeled "fit-to-criteria, not a return forecast"; input guards prevent crashes.
- Full suite green; no live data in tests.

## 14. Out of scope (v1)
NLP/chat; saved named screens (URL spec is shareable); per-criterion threshold filters; Tool C/D criteria population (config-only when they exist); backtesting; any "recommended/best" language.

## 15. Build rhythm & git rules
Continuous build with **deep self-review after every step, deeper at each checkpoint** (log to `reviews/codex/codex_candidate_finder_progress.md`): read your staged diff hunk-by-hunk (scoped files only, no stray edits); `pytest -q` green, count ≥ baseline + new; verify acceptance; confirm the single shared `oriented_percentile` and the reuse of `is_usable_candidate()` (no duplication); confirm no recommendation language and no auto-prescription. One commit per step + a self-review-fixes commit per batch. **No `git push`** (Emanuel pushes). No amend/rebase/force-push. **Stop at Checkpoints A/B/C** to report, and on any genuine blocker.

## Done =
All 3 batches shipped; the shared `oriented_percentile` + the reuse of `is_usable_candidate()` confirmed; config registered; full suite green; completion report written; stopped at the checkpoints for review. Tool C/D criteria can later be added by config once those tools exist.
