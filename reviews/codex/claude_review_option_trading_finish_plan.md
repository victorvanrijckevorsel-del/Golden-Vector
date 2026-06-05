# Review — Option Trading Finish Plan

**Reviewer:** Claude Code (Opus 4.8)
**Subject:** `reviews/codex/codex_option_trading_finish_plan.md`
**Cross-checked against:** the shipped liquidity engine (`hedge/options_liquidity.py`), the options ingestion phase (`ingestion/options_phase.py`), the option-candidate redesign review (`claude_review_option_candidate_redesign_plan.md`), and the option-selection research.
**Grade: READY WITH CHANGES.** The scope is right and the discipline is excellent (measure-don't-assume, no recommendation language, option_vehicle vs universe separation). Five items to tighten before building, plus answers to Codex's four open questions.

## Endorsed as-is (good calls)
- **Scoping v1 to exactly three missing pieces** — refresh workflow, *measured* GDX/GDXJ liquidity, thin-chain fallback. These are the real gaps; everything else is correctly deferred. ✅
- **Decision 3 — measure GDX/GDXJ before claiming it's more liquid.** This is the single best call in the plan and matches the research exactly. Do NOT present the ETF as "cleaner" until our own cached chains prove it. ✅
- **Decision 4 — `option_vehicle` tickers kept separate from the Tool A/B `universe`.** Prevents GDX/GDXJ silently becoming screened "companies." Aligns with the hard rule against ad-hoc universe changes. ✅
- **Decisions 1, 2, 5 — refresh = "update cached data" not live quotes; background job; proxy is informational not a recommendation.** All consistent with Emanuel's locked constraints (no "buy this", no hedge sizing). ✅
- **Reusing the existing liquidity engine for ETF measurement (Step 5)** rather than a second implementation. ✅

---

## Findings to resolve

### F1 (High) — Don't freeze/commit the candidate redesign (Step 0) until F1 of *its* review is verified in code
Step 0's acceptance list checks surface items (no half-spread column, 60/90/120, no 30d) but **omits the one finding that protects the Candidate Finder**: the redesign review (`claude_review_option_candidate_redesign_plan.md`, finding F1) requires that **`is_usable_candidate()` stays strict (`tier == "tradable"`)** and that the **Candidate Finder's usable-check is tier-aware with a regression test** — otherwise making relaxed "Watch" candidates selectable silently widens what the Finder counts as a usable put/call.
- **Add to Step 0 acceptance:** `is_usable_candidate()` is still strict; a Watch-only ticker is NOT counted usable by the Candidate Finder (regression test green). Do not commit the redesign as "frozen" if this isn't in.

### F2 (High) — Pin the refresh *scope*: options-snapshot refresh, not a blind full `update-data` (answers Codex Q1)
This is the riskiest design choice in the plan. A UI button that fires the **entire** `update-data` pipeline (prices → betas → screening → options) is a long, heavy job to hang on a web request, and most of it is unrelated to the options freshness the user is actually looking at.
- **Recommendation:** the Option Trading refresh button should refresh the **options/market snapshot** (the thing whose "last cached" date is shown on the page), not silently re-run the whole model. If you want a "refresh everything" affordance too, make it a **separate, clearly-labeled** action.
- Either way it MUST be background + non-blocking + honest status (the plan already says this — good). Just don't conflate "refresh the options data on this page" with "rebuild the entire analytics stack."

### F3 (High) — The background-job layer has real Windows + WSGI pitfalls; specify them
Emanuel runs **Windows 11**, and a WSGI worker spawning a child process behaves differently than on POSIX. The plan's "simple, local-file-backed, no Celery" instinct is right, but the brief must pin:
- Spawn a **detached** child process (so it survives the request returning and a recycled web worker), not a thread that dies with the request. On Windows that means the appropriate `CREATE_NEW_PROCESS_GROUP`/detached-subprocess handling — call it out so Codex doesn't write a POSIX-only fork.
- **Atomic status writes** (temp file → rename) — the plan says this. ✅
- A **stale-lock guard**: if status says "running" but the process is gone (crash/restart), it must recover to "failed/unknown", not be stuck "running" forever.
- **Acceptance to add:** kill the process mid-run → status recovers to a non-"running" state on next read.

### F4 (Medium) — Confirm whether GDX/GDXJ option-chain ingestion already exists before building Step 4
The Options Liquidity Lab work and the Tool C/D review both reference GDX/GDXJ. **Benchmark price histories are definitely cached; option *chains* may or may not be.** Before building Step 4, verify the current state in `ingestion/options_phase.py`:
- If ETF option chains are **not** yet ingested → Step 4 is correct as written.
- If they **are** (or partially) → Step 4 becomes "finish/verify," not "build from scratch," and Step 5 can start sooner.
Don't rebuild what's there; reconcile first.

### F5 (Medium) — Thin-chain fallback: detail page primarily; overview shows only a count (answers Codex Q3)
- **Proxy fallback suggestion → ticker-detail page** (where the user is looking at one thin name and needs the GDX/GDXJ alternative + basis-risk note). That's the decision point.
- **Overview → a status/count only** (e.g. "tradable / watch / no liquid candidate"), not a proxy pitch per row. Keeps the overview compact (Step 8's goal) and avoids nudging.

---

## Answers to Codex's four open questions (§8)
1. **Full `update-data` vs options-only?** → **Options/market-snapshot refresh** for this button (F2). A full rebuild, if offered, is a separate labeled action.
2. **Model GDX/GDXJ as `option_vehicle_tickers`?** → **Yes** (Decision 4 is correct) — but confirm ingestion state first (F4).
3. **Proxy fallback in detail only or also overview?** → **Detail for the proxy suggestion; overview shows only a tradable/watch/no-trade count** (F5).
4. **Keep portfolio hedge out of v1?** → **Yes, defer it.** Finishing refresh + ETF measurement + fallback is the right v1. Portfolio hedge is a bigger, separate milestone (and Emanuel's instruction is "don't tell me how much to hedge," which the portfolio view would have to handle carefully).

## A note on size
This is a **real milestone, not a quick wrap-up** — 9 steps including a background-job subsystem, new ingestion, a diagnostics layer, ETF vehicle pages, and a UX pass. Worth checkpointing like the others: **Checkpoint after Step 3 (refresh works), Checkpoint after Step 5 (ETF liquidity measured), Checkpoint after Step 8 (fallback + polish).** One commit per step, no `git push`.

## Bottom line
Good, well-disciplined finish plan — it closes the right three gaps and keeps all the product guardrails. The must-dos: **F1** (don't freeze the redesign until the strict-tier Finder guard is verified), **F2** (refresh = options snapshot, not a blind full rebuild), **F3** (Windows-safe detached background job with stale-lock recovery). **F4-F5** are reconcile-and-place items. After these, it's ready to build.
