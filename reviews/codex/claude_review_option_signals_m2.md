# Claude review — Codex Option Signals Milestone 2 (+ M1 fixes)

**Reviewer:** Claude Code (Opus 4.8), first-hand (read every file) + ran the new market-hours guard live.
**Scope:** the M1 follow-up fixes (F1/F2/F3) + Milestone 2 — the market-hours refresh scheduler (`0100f31`, `a0937db`).
**Verdict: APPROVE — strong and complete.** All three M1 findings resolved; M2 is well-built and honestly scoped. No blockers.

## M1 fixes — all three landed

- **F1 (the asymmetry) — RESOLVED, exactly as recommended.** `_confirmed_direction_label(direction_candidate, activity_label)` now downgrades an **UPSIDE** skew read to **NEUTRAL** unless the Activity lane independently `CONFIRMS_UPSIDE`; **DOWNSIDE** stays a pure skew read. This is the asymmetric evidence bar from the v2 plan: equity skew is structurally downside-biased, so a bullish read must clear a higher bar (call-side activity confirmation) while a bearish read doesn't. The direction now genuinely depends on the activity lane per-side, not a mirror-image threshold.
- **F2 (friendly stale page) — RESOLVED.** `workspace.py:501` catches `OptionArtifactStaleSchemaError` and renders a calm "your local Option Trading data is from the previous version — run refresh" page, alongside the Tool B stale guard. A post-migration old artifact no longer surfaces as a raw 500.
- **F3 (edge tests) — RESOLVED.** `test_option_signals.py` grew (asymmetric-label + no-prior-snapshot OI paths); M2 adds `test_market_hours_refresh.py`. The 17 signal+scheduler tests pass.

## M2 — the market-hours scheduler

The whole point of M2: the option signals only carry information when fetched **while the US options market is open** (live two-sided quotes). A pre-market refresh fetches ~8% two-sided quotes and the signals fail-closed. M2 makes "refresh during market hours" automatic instead of manual.

What it does, and what I verified:

- **`market-hours-refresh` CLI command** gated on a DST-aware Eastern-Time decision. `market_hours_refresh_decision` converts any instant to `America/New_York` (DST-correct via `ZoneInfo`), requires a US trading day, and requires the time inside **10:00–15:45 ET** (default; configurable). Returns RUN/SKIP + a human reason. I ran it live: at **11:15 ET Monday it returned RUN** ("inside market hours") — the gate works.
- **Proper NYSE holiday calendar** — New Year/MLK/Presidents/Good Friday/Memorial/Juneteenth/July-4/Labor/Thanksgiving/Christmas, with observed-day shifts and **Good Friday via the Meeus/Jones/Butcher Easter algorithm**. Honestly scoped: a docstring states it does **not** model early-close half-days — it's a refresh guardrail, not an exchange-calendar package. Fair.
- **`run_market_hours_refresh` gates correctly** — validates the window (start<end), calls the decision, prints RUN/SKIP, and on SKIP `return 0` **without refreshing** (unless `--force`); supports `--dry-run`. Only runs the real `run_refresh(...)` when in-window or forced. So a scheduled task that fires off-hours simply no-ops.
- **`install-market-hours-refresh-task`** builds the Windows Task Scheduler `schtasks` commands (2×/day, MON–FRI, at local times mapping into US hours) and **does NOT execute them unless `--apply`** is passed — `--times` lets you customize. The scheduler stays **outside** the web server (server still only reads).
- **Docs** (`docs/option_signal_market_hours_refresh.md`) cover setup and explicitly note the key distinction: **"stock/foundation data remains daily-close based; option signals are market-hours option-chain snapshots."**

## Correctly scoped OUT (good)
Early-close half-day modeling, intraday re-fetch loops, a full exchange-calendar dependency — none added, all noted.

## Bottom line
M1 + M2 together make the option-signals feature **build-complete**: sector-relative skew headline, four transparent lanes, fail-closed on the benchmark, asymmetric direction bar, schema-migrated artifacts with a fail-loud + friendly stale guard, and now an automatic market-hours refresh so the signals are fetched when they actually carry information.

**The one thing we have never done: see the signals populate on real in-hours data.** Every test so far ran on stale/pre-market data and (correctly) fail-closed. The market is open now — the next step is the real acceptance test.
