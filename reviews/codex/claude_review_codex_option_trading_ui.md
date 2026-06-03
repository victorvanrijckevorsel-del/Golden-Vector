# Review — Codex Option Trading UI (v1a, steps 1–4)

**Reviewer:** Claude Code (Opus 4.8), senior-engineer pass — READ-ONLY (no code changed, no fixes applied)
**Date:** 2026-06-02
**Range:** `ba41896^..d4f4f0a` (8 commits)
**Scope:** v1a only — structured cache layer, `/option-trading` tab, put detail panel, markdown-page retirement. **v1b (calls + sizing calculator) is intentionally not in this range.**

## Grade: READY WITH MINOR CHANGES

This is genuinely good work. The architecture matches the v2 plan, the separation of concerns is clean, the cache contract resolves the v1-review finding, escaping/redirects are robust, and the empty/stale states fail closed. Nothing here blocks shipping v1a. The items below are refinements — two worth doing before v1b builds on top, the rest opportunistic.

## What I reviewed
- Read end-to-end: `hedge/option_trading.py`, `serve/option_trading_data.py`, `serve/overview_option_trading.py`, and the diffs for `serve/detail_page.py`, `serve/detail_panels.py`, `serve/workspace.py`, `serve/page_shell.py`, `serve/http_helpers.py`.
- Read the three test files; traced data flow producer→consumer.
- **Ran** `python -m pytest tests/test_option_trading_data.py tests/test_option_trading_overview.py tests/test_option_trading_routes.py -q` → **13 passed in 17.24s.** (Did not re-run the full suite; Codex reports 533 passing.)

## Findings (by severity)

### M1 (Medium, architecture/efficiency) — the detail builder recomputes the whole overview to fetch one row
`build_option_trading_detail` calls `build_option_trading_overview(...)` over **all** optionable tickers just to `next(...)` out a single row (`golden_vector/hedge/option_trading.py:125-133`), and the data layer then calls this on **every** `/ticker/<T>` request (`golden_vector/serve/workspace.py:206-214`). But `load_option_trading_data` has **already** built and cached `data.overview` (`serve/option_trading_data.py:121-139`). So each ticker page rebuilds every overview row (each of which computes a put-context scenario) to use one.

It's *correct* (same inputs → same row), but it's wasted work and a latent divergence risk: the overview's `pnl_put_at_minus10_60d` and the detail row's are computed by two independent passes. Recommend the data layer pass the cached row (`next(r for r in data.overview.rows if r.ticker == …)`) into the detail builder, or have `build_option_trading_detail` accept an optional precomputed overview. This is the one place the "single source of truth for the row" intent isn't fully realized (the *candidate grids* are correctly shared — good — but the *row* is not).

### M2 (Medium, honesty) — the r=0 risk-free fallback is silent in the UI
When the manifest has no `risk_free_rate`, the data layer substitutes `0.0` (`serve/option_trading_data.py:111-112`) and proceeds. The CLI markdown report discloses this fallback (M5/F-3), but the Option Trading tab and detail panel show the resulting numbers with **no disclosure** that a 0% rate was used. For a real-money decision surface, the same honesty the report has should carry to the UI. Recommend threading a `risk_free_rate_is_fallback` flag through `OptionTradingData` → overview/detail and rendering a small note when true. (Low frequency, but silent when it happens.)

### L1 (Low) — module-level cache is unbounded
`_CACHE` (`serve/option_trading_data.py:52`) accumulates one entry per unique provenance key for the life of the process; nothing evicts old keys after a data refresh. Fine for a personal local server, but over a long-running session it grows. Consider keeping only the latest key (or a tiny LRU).

### L2 (Low) — every ticker detail now depends on option-data loading
`/ticker/<T>` always calls `load_option_trading_data` + `build_option_trading_detail_data` and always renders the panel (`serve/detail_page.py:89`), even for a user only looking at Tool A or for a non-optionable foreign listing. It's cached after the first (expensive) build and the panel degrades gracefully (`row is None` → reason), so this is acceptable — just note the new coupling: the combined detail page won't render until the option layer loads.

### L3 (Low) — stale-feature guard only applies when `run_id` exists
`_load_features` correctly drops a ticker whose feature rows don't match the manifest `refresh_run_id` (fail-closed, good), but when the `run_id` **column is absent** it falls back to `iloc[-1]` with no staleness check (`serve/option_trading_data.py:233-238`). Current data has `run_id`, so this is latent; worth a comment that the guard is conditional on the column.

### L4 (Low, UX) — "Call Status" column with no call data yet (v1a)
The overview shows a **Call Status** column (`overview_option_trading.py:71`) and the row model carries `pnl_call_at_plus10_60d` (always `None` in v1a). A user sees call *availability* but no call P&L and no call detail until v1b — mildly confusing ("why is there call info I can't use?"). Options: hide the call column until v1b, or add a one-line "calls arrive in the next update" hint. Honest either way; just a polish call.

### Test gaps (Low)
Coverage is genuinely good (cache key, missing manifest, stale rows, redirect, download, lens-preserving switcher). Missing:
- **Malformed manifest JSON** (only *missing* manifest is tested; `_read_options_manifest` catches `JSONDecodeError` → confirm with a test).
- **Invalid lens fallback** (`?lens=garbage` → default, panel still renders, `active_nav="combined"`).
- **Overview-vs-detail consistency** — a test pinning `overview row.pnl_put == detail row.pnl_put` would catch the M1 divergence risk if the two passes ever drift.
- **r=0 disclosure** (pairs with M2).

## What I checked and found correct (no action)
- **Separation of concerns (Codex's Q1):** math/selection/ranking live in the pure builders (`hedge/option_trading.py`); load+cache in `serve/option_trading_data.py`; presentation in `overview_option_trading.py` / `detail_panels.py`. The renderer does **no** data normalization or ranking — it consumes finished dataclasses. Route logic does not leak into data loading. This is the right boundary and extends cleanly for Tool C/D.
- **Cache contract (Codex's Q2):** composite key over options-manifest `refresh_run_id` + Tool A + Tool B `snapshot_refresh_run_id`s (`option_trading_data.py:179-200`) — resolves the v1 finding; invalidates when any upstream changes; fails closed on missing/malformed manifest, missing parquet, and unparsable as-of date.
- **Candidate grids are the single source** shared by overview and detail (`option_trading_data.py:113-138`) — overview and detail candidates cannot diverge (only the *row* recompute does — see M1).
- **Escaping/robustness (Codex's Q3):** ticker hrefs use `quote(..., safe='')` + `escape(href, quote=True)`; text/notes/expirations escaped; the window switcher now preserves `lens`/anchor across 6M/12M/3Y (regression-tested). No injection surface spotted.
- **Routing (Codex's Q5):** `/option-trading` nav integrates cleanly; `/hedge-readiness` → 302 redirect; raw `latest.md` served as an attachment with a fixed server path (no traversal). Lens fallback via `resolve_detail_lens` is sound.
- **Markdown retirement:** the regex renderer is gone from the option path; the tab renders from structured data only. This was the core goal — achieved.
- **Practical value (Codex's Q4):** for v1a the tab is decision-useful — optionable-only, ranked by gold-downside sensitivity, per-side availability, put P&L context, drill-down to candidate grids + scenarios with honest "100-share contract until the calculator lands" labeling. Not over-built.

## Open questions / assumptions
1. **Scope:** I assumed this review covers **v1a only**; calls and the sizing calculator (v1b) are expected to be absent. The `call_status`/`pnl_call` fields are present-but-unused by design (per v2 §2f). Confirm.
2. **Panel always-on:** the Option Trading panel renders on *every* ticker detail page, with the lens only setting nav focus/anchor (per v2 §2g). Confirmed intended?
3. **M2 disclosure:** is surfacing the r=0 fallback in the UI in-scope for v1a polish, or deferred to v1b alongside the calculator?

## Bottom line
Ship-ready as v1a. Before v1b builds the detail further, I'd do **M1** (stop recomputing the overview in the detail path — reuse the cached row) and **M2** (disclose the r=0 fallback), since both touch the shapes v1b will extend. Everything else is opportunistic. No critical bugs; architecture is the right shape for the calls/calculator work to land on.

---

## Instructions to Codex — next actions (run autonomously to completion)

**Work straight through to the end. Do NOT stop and wait for Emanuel at the checkpoints.** This supersedes the "STOP and wait" wording in `claude_codex_option_trading_implementation_brief.md` — the checkpoints are now *deeper-review milestones*, not pauses. Keep coding until all of v1b is finished and the completion report is written.

### Order of work
1. **Apply this review's M1 and M2 first** (one commit each):
   - **M1:** have `build_option_trading_detail_data` reuse the already-cached `data.overview` row instead of `build_option_trading_detail` recomputing the whole overview. Add a test pinning `overview row.pnl_put == detail row.pnl_put`.
   - **M2:** thread a `risk_free_rate_is_fallback` flag from `option_trading_data` → overview/detail and render a small note when a 0% rate was substituted. Add a test.
   - Also close the Low test gaps where cheap (malformed manifest, invalid-lens fallback).
2. **Then continue per the brief:** Batch 3 (steps 5–6: generic `OptionCandidate` model + calls) → Batch 4 (steps 7–8: GET sizing calculator + polish).

### Review cadence (the important part)
- **After EVERY step — deep self-review of that step's code:** read the full staged diff hunk-by-hunk; run `python -m pytest -q` (must stay green, count ≥ baseline + new); verify the step against v2 §5 acceptance; run the trap checklist (no frontend math; no markdown regex; calculator is a no-mutation GET; per-side status from candidate availability not the put tier; overview number == detail number; calls scaled by `up_beta_core`; `OptionCandidate` rename keeps the CLI report working). Fix everything found, commit as `... step <N> self-review fixes` (or log "no findings"), then continue.
- **At EACH checkpoint (C, then D) — an even deeper, holistic review** before moving on: re-read the whole batch's diff as one change; check architecture/separation of concerns, data correctness and stale/empty/malformed handling, escaping/routing robustness, naming consistency (puts/calls/scenarios/speculation), dead code/unused imports/duplication, and that no earlier behaviour regressed (puts byte-for-byte; combined detail page unaffected). Write the checkpoint findings + fixes into `reviews/codex/codex_option_trading_progress.md`. Then **keep going** — do not wait.

### Rules (unchanged)
- One commit per step + one self-review-fixes commit per batch + checkpoint review notes in the progress log.
- **No `git push`** (Emanuel pushes). No amend/rebase/force-push. No live Yahoo in tests.
- **Stop only on a genuine blocker** (a plan instruction that's wrong/impossible, or a failure you can't resolve in ~15 min) — write it up and halt. Otherwise run to completion through Checkpoint D and the final completion report.
