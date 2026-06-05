# Review — Candidate Finder, Batches 1 & 2 (Checkpoints A + B)

**Reviewer:** Claude Code (Opus 4.8), read-only review.
**Scope:** commits `a160889` (scoring foundation), `6265494` (harden inputs), `3ba00f4` (data layer + CLI).
**Verdict: APPROVE — continue to Batch 3 (the UI).** This is excellent work. The scoring engine is correct, the two risks I was specifically watching for are both handled right, and the test coverage hits the exact edge cases. No correctness bugs found.

## The two critical risks — both resolved correctly
1. **Reuse of `is_usable_candidate()` (no duplication).** `_has_usable_slots()` in `candidate_finder_data.py:315` checks `slot.candidate is not None` — and a bucket slot only gets a `.candidate` when `is_usable_candidate()` passed inside `options_liquidity._slot_for_bucket`. So `has_usable_put/call_candidate` **reuses the shared options gate by construction**, with no second definition. The exact drift risk we've been guarding against — avoided. ✅
2. **Post-filter percentile pool (§12 #1).** `run_candidate_finder_screen` applies `_apply_options_filter(...)` → `peer_frame`, *then* calls `rank_candidates(peer_frame, ...)`. Percentiles are computed over the names that survive the filter, not the whole universe. View 1 and View 2 share that pool. ✅

## What I verified
**Scoring engine (`model/candidate_finder.py`) — correct:**
- **One shared `oriented_percentile`** (`features/percentile_ranks.py`): `rank(pct=True, ascending=high_good, method="average")*100`, missing excluded, one-value→100. The single convention. ✅
- **Blended score**: weighted sum of present-criterion percentiles ÷ present weight (renormalized over present). ✅
- **Deterministic missing-data rule**: `_is_rank_eligible` = `present/selected ≥ 0.67`; `_sort_rows` puts **rank-ineligible rows beneath all eligible rows regardless of score**; `_assign_ranks` only numbers eligible rows. A 1-of-5 name can't top the list. ✅ (§6/R3)
- **Score-ineligible Tool A betas masked** (`_criterion_values`): when `score_eligible=False`, the beta fields become missing → counted as low-coverage, not ridden to the top. ✅ (§12 #8)
- **Input guards**: empty selection → guard warning; all-zero weights → equal; single criterion → score = that percentile; duplicate/unknown criterion ignored with a warning; invalid direction/weight defaulted. ✅ (§12 #4)
- **Top-N tally** and per-criterion top-N lists (View 1) — correct, stable sort.

**Data layer (`serve/candidate_finder_data.py`) — correct:**
- Joins active universe ← Tool A / Tool B / options / manual store on uppercased ticker; all criteria source fields preserved (Tool A betas, Tool B fundamentals, AISC/net-debt from manual, IV signals). ✅
- **Derived market-cap ratios** (`_ratio_series`): `values/denominator` guarded by `denominator > 0` and `values.notna()` → null (not zero) when market cap ≤ 0 or numerator missing. ✅ (§4)
- **Mixed-refresh alignment**: compares Tool A / Tool B / options refresh ids → WARN with a naming message when they disagree; `run_candidate_finder_screen` inserts it at the **front** of the warnings (surfaces above the rankings). ✅ (§8)
- **Composite cache key** (Tool A + Tool B + options ids + manual hash). ✅
- Config registered: `candidate_finder.yaml` + `CandidateFinderConfig` + `AppConfig` field + `EXPECTED_CONFIG_FILES` (with `test_candidate_finder_config.py`). ✅ (R5)

**Tests (ran them — 23 passed):** the names confirm the right things are tested — `..._sinks_low_coverage_rows`, `..._all_zero_weights_falls_back_to_equal`, `..._single_criterion_score_equals_percentile`, `..._score_ineligible_treats_tool_a_beta_as_missing`, `..._empty_selection_returns_guard_warning`, plus the percentile matrix (high/low-good, ties, all-missing, one-value, negatives).

## Findings (all Low — none blocking)
- **L-1 — manual-store freshness is recorded but not actively flagged.** `_alignment` records `manual_store_hash`/`as_of` but doesn't compare the manual store against anything (there's no Tool-B-recorded manual hash to compare to here), so a manual edit newer than Tool B isn't surfaced as a mismatch — only Tool A/B/options run ids are compared. Acceptable for v1; worth wiring once Tool B's manual provenance is readable (matches the §12 #6 intent of naming *which* source is stale).
- **L-2 — alignment WARN could over-trigger** if `latest_tool_a` ever contained rows from >1 snapshot run id (it shouldn't — "latest" is one snapshot). Edge; fine.
- **L-3 (harden, optional) — add a producer↔consumer contract test** that every criterion `source_field` in `candidate_finder.yaml` resolves to a real column in the joined frame (or a derived ratio). The data tests likely cover the common ones, but a dedicated contract test would catch a future renamed field silently turning a criterion into all-missing — the same silent-drift class we hardened elsewhere.
- **Nit** — `_read_optional_parquet` uses a broad `except Exception` (consistent with the rest of the codebase; fine).

## Process
Clean: three logical commits (foundation → harden → data+CLI), stopped correctly at Checkpoint B. The brief's per-step discipline was followed this time.

## Bottom line
The hard part — the scoring math, the missing-data integrity, and the shared-primitive reuse — is **done right**. Proceed to **Batch 3 (the UI)**: the two views, preset lenses, the side-aware options toggle, the mixed-refresh banner, and the score tooltip. Optionally fold in **L-3** (the criteria contract test) while the data layer is fresh. The Candidate Finder is on track to be exactly the "rank the best names to bet against" tool, and Tool C/D ranks will slot in later as config criteria with no rework.
