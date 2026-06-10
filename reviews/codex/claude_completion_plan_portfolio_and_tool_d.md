# Completion Plan - Portfolio Tool + Corporate Resilience v2

**Owner:** Claude + Codex.  
**Goal:** consolidate the outstanding portfolio and Corporate Resilience findings into one buildable backlog, with the architecture corrected before implementation. This version incorporates Codex's senior-engineering review of the original completion plan.

Primary source reviews:
- `reviews/codex/claude_review_portfolio_full_audit.md`
- `reviews/codex/claude_review_corporate_resilience_v2.md`

## Standing Rules

- **Backend-computed / serve-reads-only.** No valuation, exposure, hedge, or resilience arithmetic in `serve/`.
- **Single source of truth.** One primitive each for scenario math, valuation, pence/FX handling, freshness/alignment, and status combining.
- **No early model-state publish.** The final model-state manifest must remain the single atomic current-state pointer. Downstream refresh steps that need fresh upstream data must accept explicit fresh run artifacts/manifests instead of requiring the current model-state to be republished early.
- **Fail loud, versioned, auditable.** Required inputs use checked reads, schema versions, and friendly stale-data pages.
- **Persist all results.** Do not discard results just because the first UI table should stay short. Large outputs can be shown through expandable tables, filters, scrolling, or CSV export, but the full result must remain accessible.
- **Privacy first.** Portfolio data is private. Tracked config must stay safe by default; local enabling must not require editing a tracked file.
- **Every fix gets a test that would have caught the bug.**
- Full suite green after each phase. Work on `dev-vic`. Do not push unless Emanuel explicitly asks. Stage only touched files, never `git add .`.

## Phase 0 - Privacy And Refresh Contract Safety

This phase comes first because it prevents private portfolio state from leaking into tracked files and protects the manifest architecture before more code is built on top.

1. **Safe local portfolio enable.**
   - Keep tracked `config/portfolio.yaml` at `enabled: false`.
   - Add either a gitignored `config/portfolio.local.yaml` override or a `GV_PORTFOLIO_ENABLED` environment override.
   - Preserve the non-loopback bind refusal when portfolio is enabled.
   - Tests: tracked config false + local/env true enables locally; non-loopback bind is refused; tracked config does not need private changes.

2. **Refresh contract guardrail.**
   - Confirm the final model-state publish remains the last atomic publish in refresh.
   - No portfolio step should need an early current-model-state republish to see fresh data.
   - Tests: a refresh failure before final publish leaves the previous current model-state intact.

## Phase 1 - Portfolio Correctness Foundation

Nothing else is trustworthy until valuation and exposure are correct.

3. **Fresh foundation for portfolio builds.**
   - Current bug: portfolio can value lots against the old model-state foundation instead of the fresh foundation just produced by refresh. This can create nonsense LSE P&L when pence/pounds changed between runs.
   - Correct fix: when `build_portfolio_artifacts(... use_model_state_artifacts=False)` runs inside refresh, resolve the fresh foundation manifest (`latest_foundation_manifest.json`) or accept an explicit foundation manifest path from the refresh orchestrator.
   - Normal UI lot edits should continue to use the current model-state manifest because they are recomputing from the last published coherent build.
   - Do **not** fix this by publishing model-state early and then running portfolio afterward.
   - Test: create an old current model-state foundation and a fresh latest foundation with different LSE price units; refresh-path portfolio build must use the fresh foundation, while current model-state remains unchanged until final publish.

4. **One structured gold-shock primitive.**
   - Extract one shared backend primitive for modeled gold-shock exposure.
   - Suggested output shape: `eligible`, `effective_beta`, `effective_exposure_usd`, `pnl_usd`, `loss_usd`, and `reason`.
   - The primitive should apply the `max(0, down_beta)` floor and the scenario fraction in one place.
   - Use it from portfolio analytics and hedge calculations; delete the local forks.
   - Match the portfolio publishable gate to the hedge engine for negative/low betas.
   - Tests: portfolio and hedge agree on a negative-beta name and a high-beta name; no modeled loss exceeds 100% from a simple linear shock.

5. **Stale FX / missing price / non-OK snapshot as explicit data issues.**
   - Define the policy before coding:
     - stale FX, missing current price, or non-OK snapshot status must create a visible data issue;
     - those lines must be excluded from confident measured-exposure headlines and hedge sizing;
     - local display may remain if the local price is trustworthy, but USD/NAV analytics must be marked degraded.
   - Tests: stale FX and missing price both appear in the data-issues artifact/UI and do not silently count as measured exposure.

6. **Currency/unit validation at the valuation boundary.**
   - Validate snapshot currency/unit against the lot `buy_currency` using the shared price-unit/currency helper.
   - Do not compare raw strings ad hoc.
   - On mismatch, surface a data issue and avoid publishing a false P&L number.
   - Tests: mismatch is visible and previous artifacts/store remain intact.

## Phase 2 - Portfolio Honesty And UX

7. **Render all data issues without hiding them.**
   - Drop fixed truncation like `[:12]`.
   - For paired exposures/correlation pairs, persist all rows and expose the full set via CSV, expandable section, or filterable table rather than dumping a huge unbounded table into the first viewport.

8. **Honest caveats and labels.**
   - Gold -10% loss: label as a linear estimate and note that real selloffs can be worse.
   - USD P&L: label as blending stock movement and FX movement.
   - Concentration: show both equity-weight and NAV-weight, clearly labeled, plus top-3 concentration.
   - Tests: page render contains the key caveats.

9. **Zero-exposure hedge card.**
   - Show "no measured gold exposure to hedge" instead of "OK / $0 / 0 puts".
   - Tests: zero measured exposure renders the specific message and does not look like a valid hedge recommendation.

10. **Small UX/data nits.**
   - Drop redundant `position_weight_fraction` if `nav_weight_fraction` is the consumed field.
   - Render the computed resilience-coverage line.
   - Do not render raw `str(exc)` in a generic 500 handler.
   - Gate `/portfolio` at the route level.
   - Use one sign convention for per-position and summary gold-loss.
   - Add a pence/GBp hint on manual buy-price entry for LSE tickers.

## Phase 3 - Portfolio Manifest, Pruning, And Test Hardening

11. **Reconciliation CSV through the manifest.**
   - Serve the manifest-resolved run-stamped CSV artifact, not the mutable `_latest.csv` alias.
   - Add a stale-schema/freshness gate.

12. **Portfolio artifacts in central alignment/freshness.**
   - Portfolio artifacts already belong in the model-state artifact map.
   - The missing piece is the shared alignment/freshness summary: include portfolio lines, positions, summary, reconciliation, and benchmark artifacts so stale portfolio state creates one central warning.

13. **Safe retention for run-stamped holdings artifacts.**
   - Lot edits can accumulate parquet/CSV copies of private holdings.
   - Default pruning to dry-run.
   - Protect every artifact referenced by retained model states.
   - Protect the latest portfolio artifacts.
   - Never delete the manual source-of-truth store.
   - Test: a referenced holdings artifact is never deleted.

14. **Remaining test gaps.**
   - Missing-price / no-snapshot line path.
   - Served stale-schema 503 end-to-end.
   - Tracked-file account-number scan.
   - Empty-book path.
   - One focused regression test per Phase 1/2 fix.

## Phase 4 - Corporate Resilience v2 Verification

These were called out in Claude's Tool D review. If already implemented, this phase is verification only; do not rebuild.

15. **Failure ladder order.**
   - Highest survival line breaks first as gold falls.
   - Keep or add the regression test.

16. **Serve-layer guardrail.**
   - Assert `serve/overview_tool_d.py` contains no resilience arithmetic and only renders backend-computed Tool D output.
   - Keep or add the static guardrail test.

17. **Breakeven gold headline column.**
   - Breakeven gold (= AISC) should be visible as its own headline column, not only inside the ladder.
   - Keep or add render/schema coverage.

18. **Override does not persist.**
   - A scenario call like `compute_tool_d_outputs(gold_price=G)` must not mutate the persisted spot parquet.
   - Keep or add the regression test.

## Phase 5 - Deferred Portfolio Features

These are net-new product work, not bug fixes. Confirm scope with Emanuel before starting.

19. **Broker auto-import (broker TBD).**
   - **NOTE (2026-06-09): Emanuel does NOT necessarily use IBKR. The earlier `ibkr_*`-named export was a setup-session label, not a confirmed broker. Confirm the actual broker and its export format before building. Manual entry remains the way for now.**
   - Parse the broker's positions/trades export into broker lines.
   - Group dual listings by company.
   - Add real cash in NAV.
   - Wire two-stage reconciliation against broker account totals.
   - Cost basis for P&L still needs the broker's trades/lots export or manual entry.

20. **Real cash in NAV.**
   - NAV = equities + cash.
   - Cash is excluded from gold-shock exposure.
   - This replaces the current `cash_value = 0` scaffold.

21. **FX-aware USD P&L.**
   - Convert cost at buy-date FX.
   - Show alongside local P&L, with local P&L still leading.

## Phase 6 - Options / Discovery Finish (decided with Emanuel; patched per Codex Phase-6 review)

Decided deferred items from the repo sweep — they finish the options / put-speculation discovery surface Emanuel actually uses. Not portfolio/Tool D bug fixes. Do after Phases 0-1. Backend-computed / serve-reads-only throughout. **Recommended order within Phase 6 (per Codex):** 25 -> 27a -> 23 -> 22 -> 24 -> 26 -> 27b/27c.

22. **Render the three option-signal charts (data already persisted; no renderer today).**
   - Exact artifacts (written by `build_option_artifact_frames`, loaded into `OptionTradingData`): `option_skew_curve_points` (per-delta IV skew curve), `option_oi_strike_points` (open interest by strike ladder), `option_signal_history_points` (history).
   - Render path: `GET /ticker/{ticker}?lens=option-trading` -> `build_option_trading_detail_data` -> `_with_option_signal_payloads` -> `_render_option_trading_panel` (today renders only the signal card + name-vs-sector skew table, not the three charts). Serve renders persisted frames only; do NOT scan raw chains.
   - History chart: render `skew_residual_60d` / `atm_iv_60d` / `iv_rv_ratio`. **NOT an IV-rank sparkline** — `_history_points_frame` sets `iv_rank=None` for every row today (verified, option_signals.py:712-733); a real IV-rank history is a separate backend computation + test, not just a renderer. Show a calm "IV rank not available yet / limited history" state.
   - Empty/insufficient -> calm fail-closed state, never a fabricated chart.
   - Tests: (a) the three charts render when data present + the "not enough history" state when not; (b) **artifact schema/column tests** that each frame carries the columns the renderer consumes (skew: ticker/horizon/delta/side/iv/liquidity; oi: ticker/strike/side/OI/volume/DTE/expiry; history: ticker/as_of/skew/atm_iv/iv_rv) — guards against the producer/consumer drift that broke Candidate Finder before.

23. **High-IV ("lottery") puts: flag, don't silently drop — across ALL paths.**
   - The ~300% IV ceiling lives in MORE than one place (verified): the configurable candidate/liquidity cap (`config/hedge_readiness.yaml:18-19` -> `OptionLiquiditySettings.max_implied_volatility`, `option_quote_is_tradable`) AND a HARD-CODED bound in the signal-area filter (`option_signals.py:341`, `0.01 <= iv <= 3.0`). Changing only candidate YAML leaves the signal charts still dropping high-IV contracts.
   - Fix: put ALL IV bounds (candidate, liquidity, feature, AND the signal-area filter) + an extreme-IV warning threshold in validated config. Split "candidate tradability" from "data-quality flag": surface high-IV with a flag (`extreme_iv` / `lottery_like`), do NOT drop — unless missing/zero/obviously corrupt.
   - Tests: selected candidates, contract metrics/quote flags, AND option-signal frames all surface (flagged) a deep-OTM high-IV put rather than dropping it.

24. **Surface put-P&L scenarios in Option Trading; retire the dedicated hedge web page.**
   - There is **no standalone persisted put-P&L artifact** (corrected). The scenario math is on demand: reuse `compute_scenario_bundle` over the PERSISTED selected candidate artifacts (`hedge/option_trading.py` — `build_option_trading_detail` builds `put_bundles`/`call_bundles`); serve renders the `OptionSizingResult` (`detail_panels._render_option_sizing_result` already renders a sizing scenario table). Make the "if gold drops X%, the put is worth Y, P&L = Z" view prominent on the Option Trading detail page from that path.
   - Retire the dedicated `/hedge-readiness` web page (M2): it already redirects to `/option-trading`; **retain the `/hedge-readiness/latest.md` markdown download route** (behind the portfolio gate); document the redirect as intentional; remove the orphaned M2 justification.
   - Test: the Option Trading detail page renders the scenario table from a PERSISTED candidate artifact (not a raw-chain scan).

25. **`score_eligible` rank-with-note — scoped to the speculation ranking ONLY.**
   - Change ONLY `hedge/sensitivity_ranking.py:156` (`is_rankable = score_eligible and down_beta is not None`) so a valid-down_beta-but-score-ineligible ticker is ranked **with a note** ("score withheld; downside beta shown for context") and gets **no Tool A score**.
   - Do NOT globally disable score eligibility in Tool A, Tool C, lenses, or Candidate Finder (`candidate_finder.py:299-301` masks Tool A criteria on `score_eligible` — leave it). If a Finder bearish preset later wants this, add a per-criterion `honor_score_eligible: false` field for that criterion only.
   - Test: a score-ineligible-but-valid-down-beta ticker appears in the sensitivity ranking, annotated, with no Tool A score.

26. **Close ONLY the old workspace side-by-side Compare View backlog.**
   - Remove the dangling "deferred compare view / to last" references in the OLD WORKSPACE plans/docs (Candidate Finder is the compare surface). No build.
   - Do NOT remove `hedge/comparison.py`, the CLI `--comparison-sort-by` flag, or the markdown comparison section in `hedge/report.py` — that is the hedge-readiness report's comparison, which stays.

27. **Auditability + resilience — split into three separate commits.**
   - **27a — option-candidate policy config migration:** move OTM ranges, bucket gates, lottery thresholds, IV hard/soft bounds, and the implied-vs-modeled verdict thresholds into validated, hashed YAML config. **Do this BEFORE #23** so the IV behavior is configured first.
   - **27b — single-vendor outage behavior:** define full-outage vs per-ticker outage; whether publish fails closed or publishes visible FAIL rows; a Yahoo option-data outage must fail **loud** (visible data issue), not a silent empty chart. No live-vendor tests. (A fallback vendor is a separate later design.)
   - **27c — lint/type baseline:** add `ruff` first with a minimal config (no `pyproject.toml` exists yet; `requirements.txt` lacks these); add `mypy`/`pyright` only if scoped non-disruptively. Keep the diff reviewable.

## Deferred / Forgotten Items Found During Codex Sweep

These are not necessarily part of the portfolio/Tool D completion build, but they should be explicitly owned or consciously deferred so they do not vanish.

1. **Candidate Finder per-criterion threshold filters.**
   - Deferred from Candidate Finder v1.
   - Useful later, but not required for portfolio completion.

2. **Option row-level stale carry-forward.**
   - Deferred from Option Signals v2.
   - Current design fail-closes stale option signals. Carry-forward is a future data-contract milestone only if Emanuel wants mixed fresh/held option rows.

3. **Option IV history maturity.**
   - 52-week IV percentile / longer IV history was deferred until enough option snapshots exist.
   - Do not fake it before the history is real.

4. **Saved candidate screens / trade journal.**
   - Deferred from Candidate Finder and Option Trading.
   - Product decision needed: useful only after the portfolio/import workflow is stable.

5. **Per-lens Tool D gold dial inside Candidate Finder.**
   - Deferred from Tool C/D build.
   - Now that Tool D has a scenario control, this can be revisited later, but v1 Finder should keep using persisted spot Tool D rank unless a new data contract is designed.

6. **Options refresh scalability / historical option archive.**
   - Earlier performance work deliberately kept full-chain fetches.
   - A real historical option-chain archive remains a separate design problem; pruning must not erase snapshots Emanuel expects to analyze later.

7. **Tool A detail pinning to published snapshot.**
   - Previously deferred because it requires reading per-run snapshots.
   - Current warnings help, but a future correctness pass can pin detail calculations to the exact snapshot behind the published row.

8. **Portfolio import and cash are the biggest remaining product gap.**
   - Manual portfolio works, but the "real book" remains incomplete until IBKR import and cash are added.
   - Keep this as the next product milestone after correctness/privacy fixes, not inside the bug-fix phase.

9. **Option risk-free-rate fallback disclosure.**
   - Earlier option audits flagged the `risk_free_rate=None` path and the r=0 fallback.
   - If the fallback is still reachable, the UI/report should disclose it calmly and a fixture test should prove candidate generation does not go empty just because the rate is missing.

10. **Options strategy expansion remains out of scope.**
   - Calls/short strategies/spreads/extra Greeks were intentionally kept math-only or deferred in M1.5/Option Trading.
   - Do not surface them as product features without a new plan; they need UX, risk language, and tests, not just math primitives.

11. **Workspace comparison / extra Tool A lenses.**
   - Pair-compare, `consistency`, `risk_adjusted`, and a possible `reliability` lens were deferred in older workspace plans.
   - These are presentation/product polish, not correctness blockers. Revisit only after portfolio correctness and data freshness are stable.

12. **README / architecture-map updates.**
   - Older review cycles deferred small documentation updates after major architecture changes.
   - Once this completion plan lands, update docs to reflect: Candidate Finder as home, Combined removed, portfolio privacy/local-enable, model-state manifest, options data center, and Tool D survival model.

## Definition Of Done

- Every audit/review finding is addressed or consciously deferred with a note.
- Every fix has a test that would have caught it.
- Full suite green.
- Portfolio values correctly after `update-data` and after a UI lot edit.
- London holdings price in pounds, not pence.
- Hedge/exposure/correlation/charts read fresh, correct data.
- Private portfolio enablement does not require tracked config edits.
- Corporate Resilience v2 keeps survival-line math in the backend and has the serve-no-arithmetic guardrail locked by a test.

## Sequencing / Self-Review

Phase 0 first, then Phase 1. Correct valuation and privacy are prerequisites; nothing else is trustworthy until those are fixed. Phases 2 and 3 are quality and robustness passes. Phase 4 is verification only if the Tool D fixes are already landed. Phase 5 is net-new feature work and should not start without Emanuel's explicit product approval.
