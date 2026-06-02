# Review — Codex Option Trading UI (FULL milestone, steps 1–8 + post-fixes)

**Reviewer:** Claude Code (Opus 4.8), senior-engineer pass — READ-ONLY (no code changed, no fixes applied)
**Date:** 2026-06-02
**Range:** `ba41896^..0377cef` (17 commits: v1a steps 1–4, v1b steps 5–8, completion report, post-completion fixes)
**Relationship to prior review:** supersedes `claude_review_codex_option_trading_ui.md` (v1a-only). This pass focuses on the new v1b work (generic candidate model, calls, sizing calculator) and confirms my prior M1/M2 were applied.

## Grade: READY WITH MINOR CHANGES

This is a strong, complete milestone. The engine generalization is clean and financially correct, calls are modeled properly, the sizing calculator is safe (GET-only, validated, no-mutation — and *tested* to write nothing), and Codex resolved **every** finding from my v1a review (M1 cached row, M2 r=0 disclosure) plus all the test gaps I noted (malformed manifest, invalid lens, no-mutation, fallbacks). The remaining items are all **Low / cosmetic** — none blocks shipping. Ship it; treat the items below as opportunistic cleanups.

## What I reviewed
- Read end-to-end: `hedge/scenarios.py`, `hedge/candidate_puts.py` (now `OptionCandidate`), and the v1b diffs for `hedge/option_trading.py`, `serve/option_trading_data.py`, `serve/workspace.py`.
- Verified the financial math by hand (put/call beta, breakeven, budget sizing, low-beta skip).
- Reviewed the new test inventory and **ran** the in-scope suite:
  `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_routes.py tests/test_option_trading_overview.py tests/test_hedge_modules.py tests/test_scenarios.py tests/test_strategy_generic_math.py -q` → **55 passed in 14.83s** (matches Codex's report; full suite 548 per Codex).

## Prior findings — confirmed resolved
- **M1 (recompute overview in detail):** fixed. `build_option_trading_detail_data` looks up `overview_row` from the cached `data.overview.rows` and passes it in (`serve/option_trading_data.py:70-89`); `build_option_trading_detail` no longer rebuilds the overview. ✓
- **M2 (silent r=0 fallback):** fixed. `risk_free_rate_is_fallback = risk_free_rate is None` is threaded through `OptionTradingData` → overview/detail and surfaced; covered by `test_..._discloses_risk_free_rate_fallback`. ✓
- **Test gaps:** malformed manifest, invalid-lens fallback, and a no-mutation calculator test are all now present. ✓

## Findings (all Low / cosmetic)

### L1 — Module name `candidate_puts.py` is now misleading
The module hosts `OptionCandidate`, `build_candidate_grid(option_type=…)`, and call selection, but is still named `candidate_puts.py` (`golden_vector/hedge/candidate_puts.py`). The back-compat alias `CandidatePut = OptionCandidate` (`:42`) is fine for not breaking the CLI report, but the filename now mis-describes its contents. **Recommend a future rename** to `option_candidates.py` (with a re-export shim) once the dust settles — not now, to avoid churn mid-milestone. (You flagged this yourself; agreed it's acceptable for now.)

### L2 — First-request latency now builds put *and* call grids for the whole optionable set
`load_option_trading_data` builds both `candidate_grids` and `call_candidate_grids` for ~22 optionable tickers on the first uncached request (`serve/option_trading_data.py`). It's cached on the composite provenance key thereafter, so steady-state is fine, but the first hit after a data refresh roughly doubled. Acceptable for a local single-user server; note it in case the first paint ever feels slow (then consider lazy per-ticker call-grid building).

### L3 — `down_beta_min_for_scenario` config field is applied to up-beta for calls
Call bundles pass `gold_beta_min_for_scenario=down_beta_min_for_scenario` (`hedge/option_trading.py`, call-bundle block). It works correctly (the skip message is strategy-aware — "Up-beta is too small…"), but a put-named config threshold gates call scenarios. Cosmetic; consider a neutral name (`gold_beta_min_for_scenario`) or a separate up-beta floor if you ever want different sensitivity for the two sides.

### L4 — `build_option_trading_detail_data` reason handling reads muddy
It rebuilds the result with `reason=data.overview.reason` (`serve/option_trading_data.py:90-100`), which can overwrite the detail's own "not optionable" reason. **No user-facing bug** — `_render_option_trading_panel` defaults to "This ticker is not optionable in the latest snapshot" when `row is None` — but the precedence is non-obvious. A one-line comment or `detail.reason or data.overview.reason` would clarify intent.

### L5 (UX) — The ticker detail page is getting long
A single `/ticker/<T>` page now stacks Tool A panel + Tool B panel + Option Trading (puts + calls + calculator) + company/reporting/verification/notes forms. The `#option-trading` anchor and the puts/calls segmentation mitigate it, but density is worth watching as Tool C/D add panels. Not a change request — a design note for the next tool.

## What I checked and found correct (no action)
- **Engine generalization (Codex Q1/Q2):** `compute_scenario_bundle` now takes a generic `gold_beta` with back-compat `down_beta_core`/`down_beta_min_for_scenario` aliases and a `down_beta_used` property alias (`scenarios.py:64-93, 57-61`) — the shipped CLI report path is preserved. Strategy dispatch for intrinsic, P&L, mark-to-market, and BS pricing is correct for all four strategies.
- **Calls are financially correct:** calls use `up_beta_core`, positive gold scenarios `(0, +5, +10, +15, +20)%`, the call BS price, and `+0.25Δ` selection (`option_trading.py` call-bundle block; `candidate_puts.py:67-71`). The call **breakeven** `((strike+premium)/price − 1)/up_beta` with the `<0 → annotation` guard (`scenarios.py:306-310`) is algebraically right and symmetric to the put.
- **Low-beta skip prevents fake scenarios** for both sides, with strategy-specific messages (`scenarios.py:201-215`) — a near-zero up-beta correctly blocks a call thesis, not just puts.
- **Sizing math (Codex Q3):** contracts mode = `quantity`; budget mode = `floor(budget / (mid×100))` with `premium_spend` and `leftover_cash`, honest notes when mid is missing or budget < one contract (`option_trading.py build_option_sizing_result`). Net P&L is a **linear rescale** of the cached per-contract bundle (`_rescale_bundle`) — no Black-Scholes recompute, no cache invalidation. Matches the plan exactly.
- **GET calculator is safe (Codex Q5):** `parse_option_sizing_request` validates side/horizon/mode/quantity/budget, falls back with **visible notes** on every invalid input, and even strips `$`/`,` from budget. The route only renders — `test_..._calculator_get_writes_no_files` proves no mutation. ✓
- **Cache & stale safety (Codex Q2/Q4):** composite key (options manifest + Tool A + Tool B refresh ids) is unchanged and correct; stale feature rows are dropped when `run_id` mismatches; missing/malformed manifest and missing parquet fail closed (now tested).
- **Overview info design (Codex Q6):** default sort is still `down_beta_core` desc; call figures are context columns, not a ranking basis.
- **Test quality:** behavior-focused (rendered output, cache reuse, redirect, no-mutation, fallbacks, stale rows, skipped-scenario explanations), not brittle full-HTML snapshots.

## Open questions / assumptions
1. **Module rename:** is renaming `candidate_puts.py → option_candidates.py` something you want queued for a cleanup pass, or left as-is with the alias indefinitely?
2. **Up-beta floor:** do you want a distinct minimum-beta threshold for calls vs puts, or is the shared 0.10 fine? (Currently shared.)
3. **Scope:** I assumed short puts/calls remain math-only (not surfaced) and spreads/Greeks/vol-skew stay out of scope per the plan. Confirmed.

## Bottom line
Ready to keep and build on. The put→option generalization is a clean base for future strategy work (short legs, spreads) without re-plumbing, the calculator is safe and honest, and the financial math is correct on both sides. The only real follow-up I'd schedule is the **L1 module rename** (cosmetic, for clarity) — everything else is optional. No structural changes needed before more options tooling lands on top.
