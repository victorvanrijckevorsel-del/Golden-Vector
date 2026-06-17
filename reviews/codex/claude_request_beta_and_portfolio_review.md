# Codex review request — gold-beta explainers + window-aware comparison + portfolio P&L

**From:** Claude (implementation agent). **To:** Codex (reviewer).
**Scope (git range):** `39a0a3b..HEAD` on `main` (everything after the last Codex-reviewed
options-UI work). Five commits:

- `6c27619` feat(portfolio): Snowball+HL combined gold-lot apply-writer
- `99cb765` fix(portfolio): use the quote currency (not cost currency) for imported lots
- `80ba2dd` feat(portfolio): show cost & P&L in GBP per position (fixes dashes on .AX rows)
- `a61e343` feat(serve): explain the gold beta everywhere — formula, units, sign incl. negative
- `7d61988` feat(detail): window-aware gold-beta comparison vs GDX/GDXJ + miner universe

Run `git log --oneline 39a0a3b..HEAD` and `git diff 39a0a3b..HEAD` to see the full change set.

## How to review (per repo canon)
Read the code **first-hand, file by file** — do not trust this summary or my tests over what the
tree says now. Be exhaustive: report every finding including nits, classified HIGH / MEDIUM / LOW,
each with `file:line` and a concrete fix. Write your findings to
`reviews/codex/codex_review_beta_and_portfolio_work.md`. Do **not** edit code while reviewing
unless it literally crashes the app; if you do fix, do it on `dev-vic` and list exactly what you
changed so we don't both touch the same lines.

## What this work does
1. **Beta explained everywhere (Tier 1):** the central help registry (`column_help.py`) now gives
   the gold beta a plain-English formula (`stock_week = α + β·gold_week`), units (% stock per 1%
   gold), and states it **can be negative**. Enriched keys: `tool_a_delta`, `tool_c_down_beta`,
   `tool_c_up_beta`, plus a new `benchmark_gold_beta`. Scatter + up/down-beta captions rewritten in
   `detail_panels.py`.
2. **Window-aware comparison (Tier 2):** new ticker-detail panel "How its gold beta compares" —
   the stock vs GDX, GDXJ, and the 62-miner universe, as down-beta + up-beta distribution strips.
   Switching the window (6M/12M/3Y) must re-base **all three** to the same period.
3. **Portfolio currency/P&L:** real combined Snowball(IBKR)+HL(ISA) gold lots; schema-v2 dual
   currency (GBP cost on AUD-quoted `.AX` tickers); per-position cost/P&L surfaced in GBP.

## Key files
- `golden_vector/model/benchmark_comparison.py` (NEW) — the resolver. ALL comparison math
  (percentile, rank, axis-domain, marker position, window→column mapping) is meant to live here.
- `golden_vector/portfolio/benchmark_betas.py` — now persists per-window GDX/GDXJ betas
  (`down_beta_6m/12m/3y`, `up_beta_…`) that the builder already computed.
- `golden_vector/serve/charts.py` — `_build_beta_strip_svg` (render-only).
- `golden_vector/serve/detail_panels.py` — `_render_beta_comparison_panel`, `_comparison_markers`,
  `_ordinal_percentile`, rewritten beta captions.
- `golden_vector/serve/workspace_state.py` / `workspace.py` — `ToolADetailState
  .benchmark_comparison_by_window`, `_resolve_benchmark_comparison` (reads the already-loaded
  `latest_tool_a` frame, threaded through the 5 detail call sites).
- `golden_vector/portfolio/snowball_apply.py`, `pipeline.py`, `serve/portfolio_page.py`.
- Tests: `tests/test_benchmark_comparison.py`, `test_column_help.py`, `test_portfolio_m1.py`,
  `test_workspace_horizon_switcher.py`, `test_portfolio_valuation_v2.py`,
  `test_portfolio_snowball_apply.py`.

## Specific things to verify / try to refute
**Architecture — backend computes, serve renders (the hard rule):**
1. Is there ANY arithmetic, ratio, ranking, percentile, coalesce/fallback, or basis decision in
   `serve/` (`charts.py`, `detail_panels.py`, `workspace_state.py`, `portfolio_page.py`)? The strip
   builder should only map a backend-supplied 0..1 position to a pixel. Try to find math that leaked.
2. Is the serve-arithmetic guardrail (`test_comparison_math_is_not_duplicated_in_the_serve_layer`)
   bypassable? Are the forbidden tokens the right ones, or can math hide (e.g. pandas method-call
   arithmetic, a hand-rolled min/max loop)?

**Window-basis correctness (the user's explicit requirement):**
3. Do the stock, GDX/GDXJ, and the universe distribution ALL read the SAME window's column inside
   one resolve call? Any path where a benchmark silently falls back to `*_core` for a non-core window?
4. **Basis-mismatch trap:** the scatter + "Up vs Down Beta" panels use `anchor_metric`
   (`structural_window_metrics`, latest as_of per window). The comparison panel uses
   `tool_a_latest`'s `*_{window}` columns. Could the same stock + same window show two DIFFERENT
   beta numbers on one page (e.g. different as_of_date)? Is that a real user-facing inconsistency?

**Math:**
5. `_percentile` (inclusive `<=`, tie handling), `_position` (clamp + degenerate domain),
   `_domain` (spans universe ∪ subject ∪ benchmarks), negative betas, NA/inf exclusion. Does
   `universe_down_n`/`universe_up_n` match the denominator actually used? Is the subject (which is
   itself in the universe) double-counted in a wrong way?

**Per-window benchmark artifact:**
6. Are the persisted per-window GDX/GDXJ betas correct (same OLS basis as the miner universe)?
   Is "`down_beta_core` == the anchor-window column" correct and not a bug? Does adding 6 columns to
   `BENCHMARK_BETA_COLUMNS` break any reader (`reader.py` strict schema, `m4_artifacts.py`,
   `analytics.py`, `pipeline.py`, `model_state.py`)?

**Efficiency (the user asked for "most efficient"):**
7. Confirm `tool_a_latest` is read once per detail request now (threaded frame), not twice. Any
   remaining redundant compute in the request path? Should the per-window comparison be precomputed
   /persisted instead of resolved per request?

**Portfolio currency:**
8. Dual-currency cost (GBP cost on AUD-quoted ticker): is `pnl_local` correctly suppressed when
   cost currency ≠ quote currency, and GBP cost/P&L computed via the cost currency's own FX (not the
   quote FX)? Is FX staleness handled fail-loud (excluded, not just flagged)? Is the combined
   ISA+IBKR lot set additive and not double-counting?

**Tests prove behavior:**
9. Do exclusion tests use a healthy control row? Are ties + NA + negative values exercised? Are
   user-facing strings asserted at render level? Anything that could pass by accident?

## Build/run
- Tests: `python -m pytest -q` (currently 1296 green). Ruff: `python -m ruff check golden_vector tests` (clean).
- The benchmark artifact was rebuilt offline from cached data (no paid fetch).

Please be adversarial. If something is correct, say what you verified; if not, give the smallest fix.
