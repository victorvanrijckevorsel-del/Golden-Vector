# Shared-spine holistic audit — record + fixes

**Author:** Claude · **Date:** 2026-06-15 · **Branch:** `dev-vic`
**Method:** 5-lens multi-agent audit (manifest/publish · serve-purity · one-copy · units · config)
across ALL tools, each HIGH/MED finding then independently verified with a concrete trigger
(default-refuted). Scope chosen by Emanuel: the shared spine / cross-cutting seams, not each
feature's internals. 19 agents; verifiers recalibrated several severities.

## Fixed directly (confirmed, contained, verified-safe)

| # | Sev | Finding | Fix |
|---|-----|---------|-----|
| U-rate | **HIGH** | `fetch_risk_free_rate` used a magnitude heuristic (`/100 only if > 1.0`); in a low-rate regime a sub-1% ^IRX yield (e.g. 0.50%) was read as 50% — a 100× error feeding every Black-Scholes delta/discount. | `^IRX` is always a percent → convert **unconditionally** `/100`; dropped the heuristic; rewrote the test that encoded the bug. |
| cfg-scen | **HIGH** | Option Trading put ladder hardcoded `(0,-0.05,…)` ≠ `config.default_scenarios`; serve never threaded it → editing config moved Hedge/Speculation but not Option Trading (twin drift). Call ladder was a separate magic tuple. | Added `put_gold_scenarios` param threaded from `hedge_readiness.default_scenarios`; call ladder = its sign-mirror. One config source for both. |
| scorecard | MED | Scorecard reader opened the mutable `scorecard_latest.parquet` directly (table-vs-meta torn-read), the same class fixed in the Lab dial (commit 21a0fdc B2). | Read meta first, resolve the table via `meta['run_stamped_artifact']`, fall back to latest only when absent. + torn-alias regression test. |
| contract-mult | MED | `OPTION_CONTRACT_MULTIPLIER = 100` forked across 3 modules + 3 bare `* 100.0` literals. | One `common/options.py`; imported at all sites; bare literals named. |
| note-count | MED | `stock_notes.groupby("ticker").size()` duplicated verbatim in Tool A + Tool B overviews. | One `note_counts_by_ticker` in `overview_helpers` (already imported by both). |
| dead-knob | MED | `ToolCConfig.rolling_volatility_weeks` validated + shipped but never read; `structural.py` hardcodes `52`. Threading it would mislabel the `_52w` basis columns. | **Deleted** the inert knob (config model + YAML + validator + test). The 52-observation basis stays fixed + correctly labelled. |
| pct-frac | MED | `value > 1.0 → /100` percent→fraction heuristic forked across 5 screening/manual sites. | One `common/numeric.percent_to_fraction`; routed all 5 (kept None/raise/field-gating at call sites). (The risk-free site is NOT this heuristic — its unit is known, fixed separately above.) |
| as_float | MED | Two divergent `as_float` in the options stack (`options_chain` used `pd.to_numeric`; `_helpers` used `optional_float`). | Collapsed `options_chain.as_float/as_int` onto `common/numeric.optional_float/optional_int`; updated the one external importer. |
| cf-guard | MED | Candidate Finder serve surface (gold-basis + rank decision) had no canon-required static-scan guardrail. | Added a guardrail asserting it delegates to `compute_tool_b_in_memory` / `compute_tool_d_outputs` and contains no forked Tool B/D formula tokens. |
| NIT | — | Stale `overview_tool_a.py: {.fillna(}` sweep exception (no `.fillna(` there anymore); bare `252.0/365.25` day-count literals in `features/options.py`. | Removed the dead exception; used `TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR`. |

## Flagged, NOT auto-fixed (verifier judged the fix big / risky / defective)
- **detail_panels per-request OLS** (serve, MED): `_compute_window_volatility` refits OLS per request for
  non-anchor windows (admittedly drifts from the pipeline). The correct fix is to persist per-window
  volatility in the Tool A model + serve-read — a model-schema + persistence + manifest + serve-gating
  change (a milestone, not a bundled edit). It is currently a SANCTIONED, documented tradeoff. **Recommend
  a dedicated change.**
- **EV/EBITDA forked** (one-copy, downgraded LOW): Tool B (no cap) vs Tool D (config cap). The cap is
  documented to users (not an unlabelled split), so it's a maintainability risk, not a wrong number; the
  extraction must preserve Tool D's `value <= 0` net-cash guard. **Recommend a careful dedicated extraction.**
- **Broad serve-guardrail token-list broadening** (serve, downgraded LOW): the proposed fix collides with
  `set.add()` / legitimate display `.groupby()`. The right move is per-surface guardrails (done for
  candidate_finder above) + formula-fragment tokens, not bare method names. **Partially addressed.**
- Minor NITs left (lower value): `_is_missing` forked 5× (edge-case), `USD_MILLIONS` literal, the headline
  −0.10 gold-shock constant forked 4×, function-default-args restating config, `overview_scorecard` custom
  `_fmt`/`(x or 0)*100`. Batchable later.

## Verification
Ruff clean across `golden_vector/` + `tests/`. Full suite run after the fixes (see commit). No artifact
rebuild required (all changes are reader / serve / constant / config-shape; no build-output schema change).
