# Plan — Gold-beta explainers (everywhere) + GDX/GDXJ & universe comparison

Author: Claude. For: Emanuel + Codex. Grounded in a 6-area investigation of the live tree.
Goal (Emanuel): make the gold-beta explanation **complete and consistent everywhere**, and
add **GDX/GDXJ + universe** context to the ticker-detail beta charts. Not a quick fix.

## The beta, precisely (source: golden_vector/model/structural.py:641-693, 1136-1176)
- **Gold beta = the OLS slope** of weekly *stock* log-returns on weekly *gold* log-returns
  over a trailing window: `stock_week = α + β·gold_week`. `structural_delta` (Tool A "Delta")
  is the full-sample β.
- **Up beta** = same regression on weeks gold **rose** (gold return > 0); **Down beta** = weeks
  gold **fell** (< 0); flat weeks excluded. Published per window only when the regime has
  enough weeks (`minimum_regime_observations`).
- **It CAN be negative** (no sign constraint; only `None` when gold has zero variance in the
  window). Units: **% stock per 1% gold** (weekly). Negative ⇒ moves opposite to gold.
- Related fields: **alpha** (intercept = expected weekly stock return at zero gold move),
  **gamma = down−up** (positive ⇒ falls harder than it rises; fragile), **asymmetry = up/down**,
  **R²** (share of weekly variance explained; 0–1), **confidence/Status** (eligibility gate).

## Decisions (adopted from the synthesis recommendations)
1. **One canonical wording**: "weeks when gold rose / weeks when gold fell" (beginner-friendly),
   used in help + chart labels + captions. Standardize across the 4 files that currently differ.
2. **Scatter overlays at the ACTIVE window** (6M/12M/3Y), not core-only — correctness over the
   cheaper artifact. Requires a small backend regression helper.
3. **Add up-beta to the portfolio positions table** (currently down-only) for parity — safe.
4. **One shared beta definition** with a generic "shorter windows are noisier" note (no per-window
   help sprawl).
5. **Ship the universe percentile strip AND the GDX/GDXJ bar markers together** in Tier 2.
6. Accessibility: distinguish overlay lines by **dash pattern + color**, not color alone.

---

## Tier 1 — explanation everywhere (central registry + captions)
All beta surfaces route through `column_help.py` keys, so this propagates to all 6 pages:
`tool_a_delta`, `tool_c_down_beta`, `tool_c_up_beta`, `tool_a_gamma`, `tool_a_asymmetry`,
`tool_a_r_squared`, `tool_a_confidence`.

- Enrich each key with: a plain-English **formula** (in `calculation`), **units + sign incl.
  negative** and the asymmetry/window-noise framing (in `details`), keeping `direction`.
- Standardize regime wording to "weeks when gold rose/fell" (also `tool_c.py`,
  `explanations.py`, `disclosures.py`, chart labels).
- Captions (in `detail_panels.py` + `charts.py` SVG labels):
  - **Weekly Return Scatter**: each dot = one week; x = gold's weekly return, y = the stock's;
    the line's **slope = the beta**; how tightly dots hug the line = **R²** (reliability);
    top-right = both up, bottom-left = both down.
  - **Up vs Down Beta**: the same stock measured separately on up- vs down-gold weeks; down > up
    ⇒ falls more than it rises (fragile).
  - **Rolling Structural Delta**: how the full-sample beta has drifted over time.
- Portfolio positions: add `up_beta_core` column for parity.
- Tests: help-registry test that every beta key has a `calculation` mentioning gold/regression;
  caption-presence assertions.

## Tier 2 — GDX/GDXJ + universe comparison (backend computes, serve renders)
Data confirmed: `benchmark_betas_latest.parquet` (GDX core 1.40/1.01, GDXJ 1.58/1.21);
`tool_a_latest.parquet` (62 miners, full beta coverage); GDX/GDXJ weekly returns in
`features/weekly_returns.py`.

- **Backend** (model layer, NOT serve):
  - `compute_benchmark_window_betas(benchmark, gold_history, benchmark_history, window_id)` in
    `structural.py` — regress GDX/GDXJ weekly log-returns on gold over the **active** window via
    the existing `compute_regression`; returns resolved α/β (+ up/down).
  - Backend-resolved **universe percentile** for the stock's down/up beta and the GDX/GDXJ marker
    positions (one rank boundary; serve never ranks).
  - Add `r_squared_core` to `BENCHMARK_BETA_COLUMNS` so the benchmark reference can show fit.
- **Serve** (`workspace_state.py` `_load_tool_a_detail` + `detail_panels.py` + `charts.py`):
  - Extend `ToolADetailState` with `benchmark_betas`, `active_window_benchmark_betas`,
    `universe_distribution` (all backend-resolved).
  - `_build_scatter_svg(..., overlay_lines)`: dashed GDX/GDXJ regression lines on the shared gold
    x-axis + legend; graceful-degrade to the single stock line if unavailable.
  - `_build_dual_bar_svg(..., reference_markers)`: GDX/GDXJ up/down-beta tick marks.
  - New `_build_percentile_strip_svg`: where the stock sits in the 62-miner beta distribution,
    with GDX/GDXJ ticks + a plain caption.
  - New `benchmark_gold_beta` help key; wire `help_th` on new headers.
- **Guardrails/tests**: clone the Tool-D serve-arithmetic static-scan for the new chart/detail
  code (no regression/percentile math in serve); chart-builder unit tests (overlay present when
  betas supplied, single line when absent); degraded-GDXJ (thin history) renders gracefully.

## Sequencing
- **Tier 1 first** (central help + captions + wording + portfolio up-beta + tests) — propagates
  to every page, low risk.
- **Tier 2** (backend helper + ToolADetailState + chart overlays + distribution strip + guardrail)
  — the comparison feature.
