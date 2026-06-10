# Handoff to Codex — Phase 6, chunk 2 (#22 option charts + #24 scenario tables)

**Status:** chunk-1 (#25/#27a/#23) is reviewed, fixes verified, and being committed by Claude now (suite running). Chunk 2 touches different files (serve/option-trading, not config/liquidity), so you can start immediately without waiting on or conflicting with that commit.

**Specs (read both):** the Phase 6 section of `reviews/codex/claude_completion_plan_portfolio_and_tool_d.md` (#22, #24) and `reviews/codex/codex_review_completion_plan_phase6.md` (the plan was patched to match your own review — these are the precise artifact/reader names).

## FOR CODEX — build, in this order

### #22 — Render the three option charts from the persisted frames
- **Exact artifacts (already produced; render them, do NOT re-scan raw chains):** `option_skew_curve_points`, `option_oi_strike_points`, `option_signal_history_points`.
- **History chart fields:** render `skew_residual_60d`, `atm_iv_60d`, `iv_rv_ratio` — **NOT `iv_rank`** (it is `None` for every row per `option_signals.py:712-733`); show a calm "IV rank not available yet" state instead.
- **Exact reader path:** `GET /ticker/{ticker}?lens=option-trading` → `build_option_trading_detail_data` → `_with_option_signal_payloads` → `_render_option_trading_panel` (`serve/detail_page.py` → `serve/option_trading_data.py` → `serve/detail_panels.py`).
- **Backend computes, serve renders:** the frames are already built backend-side; the serve layer only formats/plots — no analytics in serve.
- **Tests:** add schema/column tests asserting each of the three frames carries the columns the renderer consumes (skew: ticker/horizon/delta/side/iv/liquidity; oi: ticker/strike/side/OI/volume/DTE/expiry; history: ticker/as_of/skew/atm_iv/iv_rv). This also closes chunk-1's open nit **N4** — while you're adding the column tests, normalize the `skew_curve` `quote_flags` column to `''` (not `None`) for consistency with the oi frame, and cover the empty case.

### #24 — Option Trading scenario tables (reuse, don't rebuild)
- **Reuse `compute_scenario_bundle`** over the persisted selected candidates — do **NOT** add a new persisted P&L artifact, and do **NOT** scan raw chains. The computation stays in `golden_vector/hedge/option_trading.py`; serve only renders the `OptionSizingResult`.
- **Retain the `/hedge-readiness/latest.md` markdown download route** (do not remove it).
- **Test:** assert the Option Trading detail page renders the scenario table from a **persisted candidate artifact**, not a raw chain scan.

## Carry-forward discipline (applies here too)
- Backend computes / serve only renders (no arithmetic, no chain-scanning, in serve).
- No forked math — reuse `compute_scenario_bundle`, don't copy it.
- Tests prove the behavior and exercise the real reader path (a chart test must assert the frame actually reaches the renderer, not just that the frame exists).
- No silent caps/truncation; if a chart has limited data, show the calm empty state, don't hide it.

## Conventions
- `dev-vic` only. Build + leave everything **staged**; **Claude reviews and commits** — do not commit yourself.
- Do NOT touch `candidate_finder.py` / `tool_a` / `tool_c` / lenses.
- Never touch/print `data/manual/*`.
- **Ping when chunk 2 is staged and the suite is green.** Claude will verify first-hand and commit, then hand off chunk 3 (#26 compare-view cleanup, #27b vendor outage, #27c lint/type).
