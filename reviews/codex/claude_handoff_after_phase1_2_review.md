# Handoff to Codex — after the Phase 0/1/2 review

**From:** Claude Code. **Branch:** `dev-vic`. **Status of your staged batch:** reviewed, APPROVE WITH CHANGES.
**Read first:** `reviews/codex/claude_review_completion_phases_1_2.md` (full findings, every one with file:line, all adversarially verified). 851 tests pass; the issues below are gaps, not failures.

There are three things to do, in order.

---

## Step 1 — Action the review (before anything else)

Your Phase 0/1/2 work is correct on the bulk of the plan, but fix these first (recommended order):

1. **H1 (HIGH, real correctness gap)** — `STALE_FX` / non-OK-snapshot lines with a healthy beta are flagged but still counted in the confident measured-exposure headline (`tool_a_coverage_value_usd`, `modeled_gold_down_10_loss_usd`) and in GDX hedge sizing. `_tool_a_exposure_fields` (analytics.py:85) never sees `position_status`. Route `STALE_FX`/non-OK lines to a distinct `"Degraded data"` bucket excluded from those headlines and from `_effective_gold_exposure_usd` (m4_artifacts.py:368-384), while still showing local value. Add the item-5 **exclusion** regression test: a healthy-beta (e.g. 1.5, HIGH) + stale-FX line, assert it is NOT in `Measured beta` and is excluded from the headline + hedge sizing. (`MISSING_PRICE`/`MISSING_FX`/`CURRENCY_MISMATCH` are already correctly excluded — leave those.)
2. **M1** — single-source the min-beta gate: thread `app_config.hedge_readiness.down_beta_min_for_scenario` into the portfolio callers (analytics + m4_artifacts) instead of the hardcoded `DEFAULT_GOLD_DOWN_MIN_BETA`. At minimum add a drift-guard test asserting `DEFAULT_GOLD_DOWN_MIN_BETA == HedgeReadinessConfig().down_beta_min_for_scenario`.
3. **M3** — wrap the per-lot valuation (pipeline.py:184) in `try/except ValueError` → a `_missing_value(status="INVALID_INPUT")` data issue, so a `NaN`/zero-share lot degrades one line instead of aborting the whole build. Add a test.
4. **M2** — fix or document `effective_exposure_usd` in the clamp regime (gold_shock.py:114) — either sum un-clamped `value×effective_beta` for the exposure headline, or document the semantic + add a beta>10 hedge-path test.
5. **Test fidelity** — strengthen item-3 (use LSE pence/pound units across the two foundations + assert model-state unchanged), item-4 (one cross-engine portfolio-vs-hedge agreement test on a neg-beta and a high-beta name), item-7 (>12 rows so a re-added `[:N]` is caught), item-9 (a serve-render assertion of the zero-exposure card), and add the two missing Tool D tests (`latest_gold_price_from_history` direct unit test; `tool_d.version == 2` at loading level).
6. Nits N1–N8 as convenient (see the review).
7. **Note on the refuted item:** the currency `.strip().upper()` compare (pipeline.py:421) is SAFE — pence conversion is upstream in `standardize.py`. **Do not "fix" it.** A one-line clarifying comment is the most that's warranted.

**Do not commit.** Leave everything staged; Claude reviews and commits/pushes (per our workflow). Ping when Step 1 is done so Claude can commit the corrected batch.

---

## Step 2 — Continue the completion plan (Phase 3 next)

`reviews/codex/claude_completion_plan_portfolio_and_tool_d.md` is the source of truth. After Step 1:

- **Phase 3 — Portfolio Manifest, Pruning, And Test Hardening (items 11+).** This is the next build target: serve the manifest-resolved run-stamped reconciliation CSV (not the mutable `_latest.csv` alias), pruning/retention, and the test-hardening items.
- **Phase 4 — Corporate Resilience v2 Verification.** Largely already done in this staged batch (F1 ladder order, F2 serve-no-arithmetic test, F3 breakeven column, F4 no-persist test all landed). Treat Phase 4 as verification only — confirm nothing regressed; no new build expected.
- **Phase 6 — Options / Discovery Finish.** Build after Phase 3, in the order Codex's own Phase-6 review recommended (#25 → #27a → #23 → #22 → #24 → #26 → #27b/#27c). See `reviews/codex/codex_review_completion_plan_phase6.md`.
- **Phase 5 — Deferred Portfolio Features.** Net-new feature work — **do NOT start without Emanuel's explicit product approval.**

---

## Step 3 — The next big feature track: gold-price dial + auto-pull fundamentals

`reviews/codex/claude_gold_dial_and_fundamentals_plan.md` is the plan. Its Phase-1 (staleness) dependency is now satisfied by your work. **But do not start building it yet** — it is gated on two things:

1. **Your review of that plan first.** A review prompt was prepared; produce `reviews/codex/codex_review_claude_gold_dial_and_fundamentals_plan.md` (honest/critical, backend-first, completeness). Verify the dual-store data model (`fetched_fundamentals` + the user's overrides), the gold-dial reuse of Tool D's `compute_tool_d_outputs` pattern (no forked gold math), ranking determinism, the yfinance financials mapping, and the two-comparison-axes (gold price × data source) composition.
2. **Two open product decisions from Emanuel** (still pending): the "normalized gold" value (proposed: gold's trailing 3-yr average, overridable), and confirming "Our view" (official + corrections) as the default ranking layer.

Once both clear, build **Phase A (the gold dial) first** — it ships independently and fixes most of the EV/EBITDA confusion on its own; **Phase B (auto-pull)** follows.

---

## Standing conventions
- `dev-vic` only; never commit to `main`. Codex builds + leaves staged; **Claude commits/pushes.**
- Never touch / print the sensitive portfolio data (`data/manual/portfolio/`, `data/manual/holdings/`); keep tracked `config/portfolio.yaml` at `enabled: false`.
- Backend computes, serve renders (the architecture guardrail your Tool D work already respects).
