# Plan: Active-Window Switcher on the Tool A Detail Page

Date: 2026-04-24
Author: Claude (Opus 4.7)
Status: PROPOSED
For review by: Codex

## Why

The Tool A detail page today shows one snapshot — the ticker's canonical anchor window (usually 12M). The scatter plot, up/down beta bars, scorecards, narrative, volatility, and rolling delta chart are all locked to that one window. Emanuel wants to flip between 6M / 12M / 3Y and see **everything** adapt, including the rolling chart becoming a multi-line view with toggleable lines.

The data is already there. `tool_a_structural_latest.parquet` stores metrics for all three windows across ~25 years of rolling dates. This is pure UI work.

Emanuel's constraint: **most calculation in the back end**, keep it simple. This plan takes that literally — **zero new JavaScript**. Everything is server-rendered Python reading from existing parquet.

## Goals

- Three-tab switcher at the top of the detail page: `6M | 12M | 3Y`. Click → whole page re-renders for that window.
- Default on first load = the ticker's canonical anchor window (`anchor_window_id`).
- When active window ≠ canonical, show a small label ("Viewing 6M — canonical anchor is 12M").
- Rolling structural delta chart shows all three lines (6M / 12M / 3Y). Active line drawn thickest. Legend has per-line hide/show toggles.
- Scatter plot, up/down beta bars, scorecards, and narrative all reflect the active window.
- Volatility diagnostics recomputed on-the-fly from the active window's weekly returns sample.
- Keep everything bookmarkable: `?window=6m&hide=12m,3y`.

## Non-goals

- No new JavaScript. Legend toggles and window switching are anchor links.
- No pipeline changes. All data already persisted.
- No change to `reporting_calendar`, Tool B, notes, or any other panel on the detail page.
- Not adding vol for arbitrary windows (only 6M / 12M / 3Y — matching the structural windows).

## Non-negotiable design rules

1. Zero JavaScript added in this change.
2. All math runs in Python.
3. URL parameters are the only state. Reload-safe, bookmarkable.
4. Existing canonical page (`/ticker/NEM` with no params) renders exactly as it does today.

## Architecture

### URL contract

```
/ticker/NEM                         → default view (canonical anchor window, all lines visible)
/ticker/NEM?window=6m              → active window is 6M
/ticker/NEM?window=3y&hide=6m      → active window 3Y, 6M line hidden from rolling chart
/ticker/NEM?window=12m&hide=6m,3y  → active window 12M, only 12M line visible
```

`window` values: `6m` / `12m` / `3y` (case-insensitive). Invalid → fallback to canonical anchor.
`hide` values: comma-separated subset of the three windows. Invalid → ignored.

### What's read from where

| Field needed | Source |
|---|---|
| Per-window structural delta / gamma / asymmetry / r² / up_beta / down_beta / weeks | Existing `structural_window_metrics` dataframe already loaded in `ToolADetailState` (has one row per window per ticker) |
| Canonical anchor window id | `tool_a_latest.parquet` → `anchor_window_id` column (per-ticker) |
| Weekly returns sample (for scatter + vol) | Existing `weekly_series` dataframe already loaded |
| Rolling 6M / 12M / 3Y delta time series (for chart lines) | `tool_a_structural_latest.parquet` — just filter by `window_id` |
| Confidence, Tool A Score, Profile, Volatility Context | `tool_a_latest.parquet` — these are cross-window aggregates (see note below) |

### What gets recomputed per window

Only volatility. The pipeline persists `total_volatility_52w / residual_volatility_52w / downside_volatility_52w` which are 52-week specific. For 6M and 3Y we recompute from the already-loaded `weekly_series` — 3 numpy calls, microseconds per page load.

Method: for the active window W:
- Subset last N weekly observations (26 for 6M, 52 for 12M, 156 for 3Y)
- `total_vol_annualized = std(weekly_log_returns) * sqrt(52)`
- `downside_vol = std(negative-only weekly_log_returns) * sqrt(52)`
- `residual_vol = std(regression_residuals) * sqrt(52)` — regress stock returns vs gold returns over the same subset

### What does NOT change across windows

- **Confidence, Tool A Score, Profile** are cross-window aggregates computed in the pipeline. They cannot be recomputed per-window without reimplementing the aggregation logic. They stay constant regardless of active window. We label them visually with a subtle tag: "aggregate across all windows" or similar.
- **Volatility Context label** (LOW_NOISE / MODERATE_NOISE / HIGH_NOISE): this is a function of residual vol. Since residual vol changes with window, the context label also recomputes. The thresholds live in `config/scoring.yaml` already.

### What replaces the old narrative text

Narrative cards today use pre-computed strings (`delta_explanation`, `gamma_explanation`, etc.) baked in the pipeline around the canonical anchor values. These strings embed numeric values like "core = 0.59". When the user picks a different window, those strings no longer match the displayed numbers.

Solution: a small new Python helper `_describe_structural_metrics(window_metrics, thresholds) -> dict[str, str]` that regenerates the narrative from an arbitrary window's numbers. The logic is a handful of tier-based `if/elif` templates (low/medium/high delta, positive/negative gamma, etc.) plus interpolating the current numeric value. Backend code, tested.

Call site: when active window == canonical anchor, we COULD reuse the pre-computed pipeline narratives for consistency. Simpler: just always call the helper. One code path, one behavior. Slight risk of drift from the pipeline's phrasing, acceptable because the concepts and templates will mirror each other.

### Chart rendering (rolling delta)

Today: `_render_beta_history_panel` draws one line (12M rolling delta) using the `_build_beta_history_svg` helper, pulled from `tool_a_structural_latest.parquet` filtered to `window_id == '12M'`.

Tomorrow:
- Same data source, but load all three window_ids' series
- `_build_beta_history_svg` accepts a list of (window_id, series, is_active, is_hidden) tuples
- Draw each non-hidden series as a line; active window drawn with thicker stroke; hidden windows omitted entirely
- Y-axis spans the union of visible series values
- Legend below the chart has three `<a>` links, one per window. Each link computes the new URL with that window toggled in the `hide` param. Clicking reloads the page with the toggle applied.
- Hidden window's legend entry is styled as strikethrough text so the user can see which are hidden.

### Scatter / up-down beta panels

`_render_scatter_panel` today: weekly_series over "official 12M anchor sample". Change to slice by active window's week count.

`_render_up_down_beta_panel`: already window-keyed via the parquet's `up_beta_6m / down_beta_6m / up_beta_12m / ...` columns. Just pass the active window id.

### Top scorecards

Two groups, rendered with a subtle divider:

**Window-specific (recomputes with switcher):**
- Structural Delta, Gamma, Asymmetry, R², Weeks, Up Beta, Down Beta, Volatility (total / residual / downside / context)

**Aggregate (stable across switcher):**
- Confidence, Tool A Score, Profile, Canonical Anchor

Small "Active window: 6M" header on the window-specific group so the user sees which numbers are scoped.

## Step-by-step plan

### Step 1 — URL-param plumbing + window resolution (30 min)

- New helper `_resolve_active_window(query, canonical_anchor) -> str` in `workspace.py`: reads `window` param, validates against `{6M, 12M, 3Y}`, falls back to canonical anchor.
- New helper `_parse_hidden_windows(query) -> set[str]`: reads `hide` param, returns set of valid window ids.
- New helper `_toggle_hide_url(ticker, current_hidden, target_window, active_window) -> str`: computes the URL that flips `target_window` in or out of the hidden set.
- Thread `active_window` and `hidden_windows` through the detail-page render signature.

**Tests (3):**
1. `test_resolve_active_window_uses_canonical_when_param_missing`
2. `test_resolve_active_window_honors_valid_param_case_insensitive`
3. `test_parse_hidden_windows_ignores_invalid_values`

### Step 2 — Volatility + narrative helpers (45 min)

- New helper `_compute_window_volatility(weekly_series, gold_series, window_weeks) -> VolatilityDiagnostics` (small dataclass with total / residual / downside / context_label).
- New helper `_describe_structural_metrics(active_window_metrics, thresholds, context_labels) -> dict[str, str]` returning the 4-5 narrative card bodies regenerated from the active window's numbers.

**Tests (4):**
4. `test_compute_window_volatility_matches_pipeline_52w_for_12m_window` (sanity: given the same 52 weekly observations, our on-the-fly calc should match the persisted `total_volatility_52w` within rounding)
5. `test_compute_window_volatility_uses_26_weeks_for_6m`
6. `test_describe_structural_metrics_low_delta_produces_low_linkage_narrative`
7. `test_describe_structural_metrics_negative_gamma_produces_favorable_narrative`

### Step 3 — Window switcher + card-group rendering (45 min)

- New helper `_render_window_switcher(ticker, active, canonical, hidden_windows) -> str`: emits a 3-link tab row at the top of the detail page.
- Update `_render_ticker_page` to call the switcher and pass `active_window` through to the visual panels.
- Top scorecards split into two groups (window-specific / aggregate) with a divider and group label.
- Show a "Viewing 6M — canonical anchor is 12M" note when active_window ≠ canonical_anchor.

**Tests (3):**
8. `test_ticker_page_default_active_window_is_canonical_anchor`
9. `test_ticker_page_with_window_6m_shows_6m_metrics_in_scorecards`
10. `test_ticker_page_with_non_canonical_window_shows_anchor_mismatch_label`

### Step 4 — Scatter + up/down beta panel updates (30 min)

- `_render_scatter_panel` accepts `active_window` and slices `weekly_series` to the window's week count.
- `_render_up_down_beta_panel` accepts `active_window` and reads `up_beta_<window>` / `down_beta_<window>` from the tool_a row.

**Tests (2):**
11. `test_scatter_panel_uses_last_26_weeks_for_6m`
12. `test_up_down_beta_panel_reads_window_specific_fields`

### Step 5 — Rolling delta chart: 3 lines + legend toggles (1 hr)

- `_build_beta_history_svg` extended to draw multiple lines, each with a different color; active line thicker; hidden lines omitted.
- New `_render_rolling_chart_legend(ticker, active_window, hidden_windows) -> str` emits the three legend links.
- `_render_beta_history_panel` calls both, passes through active/hidden state.

**Tests (3):**
13. `test_rolling_chart_draws_all_three_lines_when_no_hide_param`
14. `test_rolling_chart_omits_hidden_line`
15. `test_rolling_chart_legend_link_toggles_only_target_window`

### Step 6 — Smoke + commit (30 min)

- Live browser pass on `/ticker/NEM`, `/ticker/AAUC.TO`, `/ticker/WAF.AX`:
  - Default loads with canonical window active
  - Click 6M tab → all panels shift
  - Click legend 12M → line hides, URL has `hide=12m`
  - Back button → returns to previous state
  - Bookmark `?window=3y&hide=6m` → restores exactly
- Run full suite
- Single commit

**Tests (1):**
16. `test_full_page_roundtrip_with_window_and_hide_params_is_bookmarkable` (asserts 200 + correct panels on a `?window=6m&hide=12m,3y` URL)

## Total estimate

| Step | Time |
|---|---|
| 1 — URL plumbing + resolution | 30 min |
| 2 — Vol + narrative helpers | 45 min |
| 3 — Switcher + card-group rendering | 45 min |
| 4 — Scatter + beta panel updates | 30 min |
| 5 — Rolling chart multi-line + legend toggles | 1 hr |
| 6 — Smoke + commit | 30 min |
| **Total** | **~4 hr** |

16 new tests. Suite should land around 298 passing (from 282).

## Decisions locked from earlier conversation

1. Default active window = ticker's canonical anchor. ✓
2. Line-toggle state NOT persisted across navigation (URL-param only). ✓
3. Volatility recomputes with active window. ✓
4. "Viewing 6M — canonical anchor is 12M" label when they differ. ✓
5. Confidence / Tool A Score / Profile stay constant (cross-window aggregates). ✓

## What I explicitly considered and rejected

- **"Add 6M and 3Y volatility to the pipeline"** — unnecessary. We load `weekly_series` anyway; 3 numpy calls beats persisting more columns.
- **"Regenerate cross-window aggregates (Confidence / Score / Profile) per active window"** — requires duplicating pipeline aggregation logic. Those metrics are *by design* cross-window. Label them as such instead.
- **"Use JavaScript for the legend toggles so the chart updates without reload"** — would require computing SVG in JS or re-rendering from a data payload. Anchor-link reloads are ~50ms locally and keep all math in Python. Emanuel explicitly asked for backend-heavy. Keep it simple.
- **"Cache the computed vol / narrative across page loads"** — microseconds per call, no cache needed.
- **"Make the narrative helper fully config-driven"** — tier thresholds already live in `config/scoring.yaml`. Helper reads from there. No new config files.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Narrative regeneration doesn't byte-match pipeline narratives for canonical anchor | High (expected) | Low | Semantic consistency is enough. Tested for directional correctness, not string equality. |
| 6M volatility is statistically noisy (26 obs) | Certain | Low | Display with "(n=26 weeks)" sub-label so user sees sample size. |
| Rolling chart y-axis scaling looks wrong with 3 lines of different ranges | Medium | Low | Union of all visible series min/max. Visual QA in Step 6. |
| URL-param parsing has an edge case (e.g., duplicate `window` params) | Low | Low | `parse_qs(...)[key][0]` pattern (same as rest of the workspace). |
| Someone bookmarks a URL with an unknown window value | Low | Low | Fall back to canonical anchor silently. |

## Decisions Emanuel needs to confirm

1. **Cross-window aggregates (Confidence / Score / Profile) stay visible but labeled as "aggregate across all windows"** — my recommendation. Alternative: hide them on non-canonical windows. I prefer keeping visible because score and profile are the main ranking signals; hiding them would be more confusing than labeling them.

2. **Volatility context label recomputes with window** (thresholds from `config/scoring.yaml`). My recommendation. Alternative: keep the pipeline's label across all windows. Keeping it constant would be inconsistent with the number right next to it.

Both minor. If both land as I propose, the plan stands.

## What Codex should review

1. **Is the design actually as simple as it can be?** Specifically, is the URL-param/anchor-link approach the right call, or is there a simpler shape I've missed?
2. **Does "most calculation in the back end" hold?** I've committed to zero new JS. Any surface where this is silently violated?
3. **Is the narrative regeneration helper a reasonable seam?** The pipeline has its own narrative logic today; duplicating the template logic in the workspace creates a drift risk. Is the tradeoff worth it, or should I extract a shared narrative-generation helper used by both?
4. **Volatility recomputation**: should 6M vol be suppressed entirely when `weeks_6m < 26` (insufficient observations)? My plan renders it with a sample-size label. Alternative: refuse to compute below a threshold.
5. **Chart line colors**: I didn't specify. Any accessibility concern I should address up front (colorblind-safe palette, patterns instead of colors)?
6. **URL param ergonomics**: anchor links that toggle `hide` by computing new URLs are slightly tricky to implement correctly (need to preserve all other params). Is there a cleaner abstraction I should propose?
7. **Is there anything in this plan that breaks our recently saved "prefer simpler designs first" rule?** Honest check welcome.

## Self-review before submitting to Codex

I re-read this plan with the "simple first" memory rule in mind. Two things to honestly flag:

- **Step 5 is the largest single step (~1 hr).** It's warranted — multi-line SVG rendering with y-scale union + legend toggle URL construction isn't trivial. But if Codex spots a simpler shape for the chart (e.g., three separate small charts stacked instead of one multi-line chart), I'm open to it.
- **The 16-test count** is probably more than strictly needed. I listed them granularly because the review cycle has taught me to be explicit; real implementation may collapse some (e.g., #11 + #12 into one).

Nothing else reads as over-engineered. Zero JS, 3 existing parquet files, 2 new helpers, 1 new switcher, 6 small view-level edits. That's the floor for this feature.
