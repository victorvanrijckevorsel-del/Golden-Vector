# Workspace Visualization Layer Plan

Date: 2026-04-23
Author: Claude (Opus 4.7, 1M context)
Status: For Codex to review and correct.

## 0. Why this plan exists

Two inputs:

1. The brainstorm with Emanuel about what the workspace could *show* — three high-leverage ideas:
   - Multi-lens ranking (re-sort by upside torque, fragility, cleanliness, consistency, risk-adjusted)
   - Direct pair / triple compare
   - Per-stock rolling-beta-over-time chart (the paper's most important picture)
2. The existing [`claude_finish_v1_next_steps_plan.md`](claude_finish_v1_next_steps_plan.md), which says workspace completion is the next milestone, no new backend, defer the compare view.

This plan slots the three visualization ideas into the existing plan's milestones, respecting its principles. It does **not** replace the existing plan — it specifies the visualization-layer additions and explains exactly what to build, where, and how.

## 1. Headline mapping

| Existing plan section | Original scope | This plan adds |
|---|---|---|
| 5.1 Source-verification editing | edit verification status, source date, URL, notes | unchanged |
| 5.2 Tool B workflow polish | missing-fields visibility, verified vs estimated, save feedback, clear-value | unchanged |
| 5.3 Notes handling | display, status/tag, browsing | unchanged |
| 5.4 Overview table usability | search/filter/sort | **+ Idea 1: multi-lens ranking** |
| 5.5 Snapshot freshness/provenance | refresh ids, warnings | already shipped in the holistic-fix pass; keep as-is |
| **(new) 5.6 Per-stock structural history** | n/a | **+ Idea 3: rolling structural-delta chart on the detail page** |
| 6.x workflow polish | empty states, refresh flow | unchanged |
| 7.x release hardening | review, smoke checks, docs | unchanged |
| 8 Compare view (deferred) | side-by-side, no new engine | **+ Idea 2: pair/triple compare specified here, built in this slot, not in the workspace milestone** |

So Ideas 1 and 3 land in the workspace-completion milestone. Idea 2 stays deferred per the existing plan and is specified in §4 only as a design pre-commitment so that when we eventually build it, it stays a thin presentation layer.

## 2. Hard constraints (from the existing plan)

These are not optional. Anything in this plan must respect them:

- **No new backend engine.** All views read existing Tool A and Tool B output parquet files plus the existing `tool_a_structural_latest.parquet`. No new pipeline stages, no new model classes.
- **Server-rendered HTML.** No SPA, no client-side framework, no JavaScript build step. SVG charts inline, like the existing scatter and dumbbell.
- **Provenance stays visible.** Every new panel must work cleanly with the score-withheld and missing-alias states already in the workspace.
- **Local-first.** No network calls from the workspace.
- **Don't reintroduce CSV-first workflows.**
- **Tests must stay green** and we add targeted tests for each new piece.

## 3. Idea 1 — Multi-lens ranking on the overview

### What and why

The overview currently sorts by ticker. The Tool A composite `tool_a_score` collapses delta, gamma, asymmetry, and confidence into one number. That hides the trade-off the user cares about. A lens picker lets the user re-sort by the dimension they care about right now — without changing any model output.

Five lenses, all derivable from the existing Tool A row fields. No model changes.

| Lens id | Question it answers | Formula (uses existing columns) |
|---|---|---|
| `composite` (default) | Overall Tool A rank | `tool_a_score` |
| `upside_torque` | Who benefits most when gold rallies? | `structural_delta_core × max(−structural_gamma_core, 0)` (note: with the current sign convention, **negative** gamma = good upside, so we flip the sign) |
| `fragility` | Who falls harder than they rise? | `max(structural_gamma_core, 0) + max(downside_volatility_52w − residual_volatility_52w, 0)` |
| `cleanliness` | Whose price is most explained by gold? | `r_squared_12m × (1 − residual_volatility_52w / total_volatility_52w)` |
| `consistency` | Whose beta is stable across windows? | `delta_stability_score × min(weeks_3y / 156, 1)` |
| `risk_adjusted` | Score per unit of downside vol | `tool_a_score / max(downside_volatility_52w × 100, 1.0)` |

For each lens, a higher value = better (except `fragility`, where the lens *measures* fragility — we display it but rank ascending so the user sees the most fragile names at top of that view).

### How it should work in the UI

- A small "View by" `<select>` at the top of the overview, default = `composite`.
- The form submits via GET → URL becomes `/?lens=upside_torque`.
- Workspace re-sorts the overview table by the chosen lens score, ascending or descending depending on the lens.
- A new **Lens Score** column is added to the overview, replacing nothing (it sits next to the existing Tool A Score column).
- Below the table, a one-line tooltip explaining what the current lens measures.
- Score-ineligible rows have `lens_score = NaN` for all lenses except `composite` (which is already None for those rows). Show as `-` and sort `na_position="last"`.

### Where the code lives

- New module: `golden_vector/serve/lenses.py`
  - `LENS_DEFINITIONS: dict[str, LensSpec]` — id → human title, sort direction, formula function, one-line tooltip
  - `compute_lens_score(row: dict, lens_id: str) -> float | None`
  - `apply_lens(tool_a_outputs: pd.DataFrame, lens_id: str) -> pd.DataFrame` returns a copy with `lens_score` column
- `workspace.py`:
  - Read `?lens=<id>` from query string in the GET `/` handler.
  - Pass to `_render_overview_page` which applies the lens, re-sorts, adds the column header + cell, and renders the lens picker.
  - Default to `composite` when the lens is missing or unknown.
- `tests/test_lenses.py`:
  - One test per lens that pins the formula on a known row.
  - One test that ineligible rows get `None` for lenses other than `composite`.
- `tests/test_workspace_app.py`:
  - One test that `/?lens=upside_torque` re-orders the overview table and shows the lens label in the page header.

### What this is **not**

- Not a new model. The lenses are deterministic re-projections of the published Tool A row.
- Not configurable by the user beyond picking a lens id. Formula tuning is a code change.
- Not weighted across lenses. We rank by one lens at a time.

## 4. Idea 2 — Pair / triple compare (deferred, design pre-commitment only)

This belongs in the existing plan's §8 deferred-compare-view slot. We specify the shape so that when it is finally built, it stays a thin presentation layer and does not regress into a new backend.

### Shape when eventually built

- New route: `/compare?tickers=NEM,GOLD,AEM` (max 3 tickers).
- Reads `tool_a_latest.parquet` and `tool_b_latest.parquet` only. No recomputation.
- Renders:
  - A side-by-side metric grid with the row-winner highlighted per metric.
  - One overlaid weekly-return scatter with two-or-three regression lines (drawn from each ticker's `up_beta_core`/`down_beta_core` or recomputed from the existing `tool_a_structural_latest.parquet` if needed — no new pipeline).
  - An up-vs-down beta dumbbell, one row per ticker.
  - Tool B verdict + score row.
  - A note "Comparing snapshot `<refresh_run_id>`" or a mixed-refresh warning if any picked ticker references a different refresh.
- No new backend code. No new contract. No new manifest.

### Why deferred

The existing plan is firm: the compare view is the very last layer, after Tool A is comfortable to inspect, Tool B is comfortable to maintain, and the workspace is solid. Building it before workspace-completion would break that order.

### What we should do *now*

- Reserve the route name `/compare` (don't accidentally use it for anything else).
- Make sure the lens module from §3 is reusable by the future compare view (the metric-grid winner-highlighting can use the same lens scores).
- That's it.

## 5. Idea 3 — Per-stock rolling-structural-delta chart on the detail page

### What and why

The single most paper-aligned picture I can add. The Guo / Leung / Ward paper's Figure 5 shows implied gold leverage moving over time. The current workspace only shows one snapshot.

The data already exists: `data/intermediate/tool_a_structural/tool_a_structural_latest.parquet` carries `structural_delta` per `(ticker, as_of_date, window_id)`. For the live snapshot, NEM's 12M series has 1,337 weekly observations going back to ~2000. No new pipeline needed.

### How it should work in the UI

A new panel on the per-ticker detail page, sitting below the existing Up vs Down Beta panel:

- Title: "12M Rolling Structural Delta"
- Hint: "How this stock's structural beta to gold has moved over time."
- An SVG line chart:
  - X axis: as_of_date over the entire `tool_a_structural_latest.parquet` history for this ticker, 12M window only.
  - Y axis: `structural_delta`.
  - Light horizontal gridlines at delta = 0 and at the current `structural_delta_core`.
  - Optional second line in a different color: gold price (rebased) on a secondary y-axis. Use the gold history from the latest foundation snapshot (we already load it for the scatter panel).
- Use the same SVG style as the existing `_build_scatter_svg` and `_build_dual_bar_svg`.

For the smoke check: NEM's 12M series should show the spike during 2013 gold sell-off and the more recent dynamics. That's the picture that teaches the user "structural beta is time-varying."

### Where the code lives

- `workspace.py`:
  - New helper `_load_structural_delta_history(paths, ticker, window_id="12M") -> pd.DataFrame` reads the latest structural-metrics parquet, filters to ticker + window, returns sorted (as_of_date, structural_delta, window_status).
  - Drop `INELIGIBLE` and `LOW_OBSERVATION` rows by default; offer a config knob later if needed.
  - New SVG renderer `_build_beta_history_svg(beta_series, gold_price_series=None) -> str`.
  - New panel renderer `_render_beta_history_panel(ticker, history)` slotted into `_render_visual_panels`.
- `tests/test_workspace_app.py`:
  - One test that the panel shows up on the detail page for a ticker with sufficient history.
  - One test that the panel falls back to a clear empty-state message when history is missing.
- `tests/test_structural.py`:
  - Already covers the math; nothing to add here.

### Edge cases

- Some tickers have <2 years of history (e.g., GOLD has 630 weekly rows ≈ 12 years; FRES.L has 936 ≈ 18 years). The chart should auto-scale.
- A new ticker added after `update-data` last ran will have no row in `tool_a_structural_latest.parquet` until `tool-a` runs. Show the empty-state message and prompt to run `tool-a`.
- The chart should not require gold price overlay — that's nice-to-have. Build the beta line first; if time permits, add the gold overlay.

## 6. Order of implementation

1. **Phase A — multi-lens ranking** (§3). Smallest, most contained, gives the user immediate value.
2. **Phase B — beta-over-time chart** (§5). Bigger but uses existing data.
3. **Phase C** — the rest of the existing plan's §5.1 source-verification editing, §5.2 Tool B workflow polish, §5.3 notes handling. These are independent of the visualization additions.
4. **Phase D — release hardening** (existing plan §7).
5. **Phase E — compare view** (§4 design, build only after the workspace is comfortable per the existing plan).

Estimate (very rough):
- Phase A: 2-3 hours of code + tests.
- Phase B: 3-4 hours (most of it is the SVG renderer).
- Phase C: 4-6 hours (covered by the existing plan, no estimate from me here).
- Phase D: 2-3 hours.
- Phase E: deferred.

## 7. Acceptance criteria

A reasonable v1 milestone for *this* plan (not the whole tool) is:

- Overview page has a working lens picker, all five lenses computed correctly, ranking changes with the picker, score-ineligible rows handled cleanly.
- Detail page has a working per-stock beta-history chart for any ticker with eligible 12M structural history, with a clean empty-state for anything else.
- All five lens computations have unit tests that pin the formula.
- The new SVG renderer has at least one test that confirms it produces non-empty output for a known input series.
- Existing 170 tests stay green.
- README mentions the lens picker and the beta-history chart in the workspace section.

## 8. Open questions for Codex to correct

I would like Codex to challenge or confirm each of these:

1. **Lens formulas under the new gamma sign convention.** Gamma is now `down − up`; negative gamma is favorable. My `upside_torque` formula uses `max(−gamma, 0)`. Is that the cleanest reading, or should it use up_beta_core / down_beta_core directly?
2. **Fragility lens.** Is `max(gamma, 0) + max(downside_vol − residual_vol, 0)` the right shape, or should it weight the gamma component more aggressively (because the fragility profile_label is already gated on gamma > 0.15 + down_beta > up_beta)?
3. **Cleanliness lens.** Using `r_squared_12m` (the anchor) instead of an average across windows. Should it use the eligible-window average instead?
4. **Risk-adjusted lens.** `tool_a_score / (downside_vol × 100)` is a Sharpe-like ratio. Is the denominator clamp `max(..., 1.0)` reasonable, or does it produce surprises for very low-downside-vol names?
5. **Score-ineligible handling.** Right now lens scores fall back to `None` for score-withheld rows. Should the lens also be withheld when the underlying input is unreliable (e.g., the residual-vol-based lenses), or is the existing `None` behavior fine?
6. **Lens picker UX.** Five lenses in a `<select>` is the simplest path. Is that enough, or does the user also need the existing tool_a_score column to stay visible alongside the lens score column?
7. **Beta-history chart data source.** I plan to read `tool_a_structural_latest.parquet`. The alternative is to recompute from the latest foundation snapshot in the workspace. The parquet path is faster and matches the snapshot the rank was computed against. Is that the right call, or do you see a provenance gap if a new foundation refresh has happened since `tool-a` ran?
8. **Chart simplicity.** I'm aiming for a single-line chart with optional gold overlay. Does it need a second metric (e.g., R² over time) on the same chart, or is one line enough for v1?
9. **Compare-view deferral.** The existing plan defers the compare view. I am keeping that. Do you agree that pair-compare belongs in the deferred slot, or do you think it should move into the workspace milestone given that the lens module already produces most of the per-ticker scoring needed?
10. **Lens module placement.** I put the lens module under `golden_vector/serve/lenses.py` because it is a presentation-layer concept. Should it instead live under `golden_vector/model/` so it's reusable from the CLI and from the future compare view?

## 9. What I am explicitly *not* proposing

- New ranking weights or model parameters.
- New scoring components.
- A new manifest format.
- Browser-side interactivity (drag-zoom, hover tooltips, etc.).
- Any change to Tool A or Tool B output schemas — both already carry every field the lenses and the chart need.

## 10. One-paragraph summary

Add a multi-lens ranking selector to the overview and a rolling-structural-delta chart to the per-stock detail page, both using existing published outputs. Keep the pair-compare view deferred per the existing plan, but pre-commit to its shape so it stays a thin presentation layer when built. Build in order: lenses, then beta history, then the rest of the existing workspace milestones, then hardening, then deferred compare. Total new backend code: zero.
