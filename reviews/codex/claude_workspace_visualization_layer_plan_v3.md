# Workspace Visualization Layer Plan — v3

Date: 2026-04-23
Author: Claude (Opus 4.7, 1M context)
Status: Final. Codex verdict on v2 was `READY WITH MINOR CHANGES` with six specific corrections. v3 applies all six; v2 is archived.
Supersedes: [claude_workspace_visualization_layer_plan_v2.md](claude_workspace_visualization_layer_plan_v2.md)
Codex reviews folded in:
- [codex_feedback_on_claude_workspace_visualization_layer_plan.md](codex_feedback_on_claude_workspace_visualization_layer_plan.md) (review of v1)
- [codex_review_claude_workspace_visualization_layer_plan_v2.md](codex_review_claude_workspace_visualization_layer_plan_v2.md) (review of v2)

## 0. Purpose and framing

This document defines the visualization additions that should be layered onto the workspace **after the core v1 workspace workflow is operationally complete.** It is a visualization addendum, not the next immediate implementation order.

It depends on the existing [`claude_finish_v1_next_steps_plan.md`](claude_finish_v1_next_steps_plan.md) being executed first. When operational completeness and provenance are in place, the visualization layer gets added on top without introducing new data-source inconsistency.

---

## 1. Tool A Detail Provenance Rule (foundational)

**This is a hard constraint on every Tool A panel on the detail page. It must be in place before the beta-history chart ships, and must be respected by every foundation-backed panel that already exists.**

### The rule

> All Tool A detail panels rendered on one page must be sourced from one coherent snapshot context, anchored on the displayed Tool A row. No panel may silently recompute or re-read from a different refresh than that row. When exact alignment is unavailable, the misaligned panel is **suppressed** and a visible fallback message is shown in its place.

### Two provenance mechanisms

The rule uses two distinct identifiers for two distinct purposes. They must not be conflated.

| Identifier | Carried on | Used to gate |
|---|---|---|
| `snapshot_refresh_run_id` | Every `tool_a_latest.parquet` row; every `tool_b_latest.parquet` row (added in the holistic-fix pass); the foundation manifest | Foundation-backed live-recompute panels (scatter, up/down beta, exploratory ladder, gold-price overlay) |
| `source_run_id` | Every `tool_a_latest.parquet` row; to be added in Phase 1A to every `tool_a_structural_latest.parquet` row | Structural-history artifacts (the new beta-history chart and any future panel that reads the structural-metrics parquet) |

### Panels explicitly covered

The rule applies to all of these, not just the new chart:

1. Weekly return scatter (`_render_scatter_panel`)
2. Up-vs-down beta panel (`_render_up_down_beta_panel`)
3. Exploratory horizon ladder (`_render_exploratory_horizon_panel`)
4. Beta-history chart (new, §5)
5. Beta-history chart's optional gold-price overlay (separate sub-check even when the chart's own provenance is OK)

### Suppression, not banner

When provenance cannot be confirmed, the panel is **removed** from the page and replaced with a visible fallback card that says *why* it was suppressed and what the user should do.

A banner-with-stale-numbers is not acceptable. A banner still leaves contradictory values on the page, which is the exact failure mode this rule exists to prevent.

### Behavior summary by state

| State | Scatter / up-down beta / exploratory ladder | Beta-history chart | Gold overlay on chart |
|---|---|---|---|
| `foundation.refresh_run_id == tool_a_row.snapshot_refresh_run_id` AND structural file `source_run_id == tool_a_row.source_run_id` | Rendered normally | Rendered normally | Rendered normally |
| `foundation.refresh_run_id != tool_a_row.snapshot_refresh_run_id` | Suppressed with fallback | Unaffected (different mechanism) | Suppressed |
| Structural file `source_run_id != tool_a_row.source_run_id` | Unaffected | Suppressed with fallback | Suppressed |
| Foundation manifest missing | Suppressed with fallback | Suppressed if it needed foundation data | Suppressed |

### Fallback state requirements

A suppressed panel must:
- Keep a visible title so the user knows which panel was suppressed.
- State the reason in one plain-English sentence.
- Offer the exact CLI command that would resolve it (e.g., `python main.py tool-a`).
- Not leave blank dead space on the page.

---

## 2. Execution order

### Phase 1 — Operational workspace completion (hard prerequisite)

Visualization layer is blocked on this phase completing. Every item here is mandatory, not optional.

- **1A. Tool A Detail Provenance Rule implemented** (this plan §1). Structural-metrics schema extended with `source_run_id`; detail page provenance check in place; mismatched panels suppressed with visible fallback; tests pass.
- **1B. Source-verification editing in the workspace** (finish plan §5.1).
- **1C. Tool B manual-workflow polish** (finish plan §5.2), including explicit clear-value.
- **1D. Notes polish** (finish plan §5.3).
- **1E. Overview search/filter/sort** (finish plan §5.4).
- **1F. Existing provenance warnings still behaving correctly** — verify across the refresh cycle after each sub-phase edit.

Phase 1 is complete when the workspace is operationally usable day-to-day AND every one of 1A–1F is green.

### Phase 2 — Visualization layer

Starts only after Phase 1 is complete.

- **2A. Multi-lens ranking** (§3). Four lenses: `composite`, `upside_torque`, `fragility`, `cleanliness`.
- **2B. Beta-history chart** (§5). Gated on 1A's provenance mechanism.

### Phase 3 — Release hardening (finish plan §7)

- Full repo review.
- Live smoke checks across `update-data` → `tool-a` → `tool-b` → `workspace`.
- Docs cleanup.

### Phase 4 — Deferred compare view

Specified in §4 for design pre-commitment only. Not built in this cycle.

---

## 3. Multi-lens ranking

### Scope

**Four lenses.** `consistency` and `risk_adjusted` are deferred until their formulas tighten. A future `reliability` lens is also noted but not shipped.

### Cross-cutting rules

These apply to every lens, with no exceptions:

- **If `score_eligible == False` → `lens_score = None`.** A withheld official score is always a withheld lens score.
- **Any non-finite input (NaN, +inf, -inf) → `lens_score = None`.** Never let a nonsense value propagate into a rank.
- Lens score `None` renders as `-` and sorts to the bottom (`na_position="last"`).

### Lens specs

#### `composite` (default)

- **Formula:** `tool_a_score` (already computed).
- **Null-handling:** `None` when `score_eligible == False` (existing Tool A behavior). `None` if `tool_a_score` is non-finite.
- **Clamp:** none.
- **User interpretation:** "Overall Tool A rank — delta, gamma, asymmetry, and confidence combined."
- **Usefulness:** default baseline.
- **Not misleading:** this is the published official score; no derivation.

#### `upside_torque`

- **Formula:** `structural_delta_core × max(up_beta_core − down_beta_core, 0)`
- **Null-handling:** `None` if any of `structural_delta_core`, `up_beta_core`, `down_beta_core` is missing or non-finite.
- **Clamp:** natural clamp to `[0, ∞)` via `max(..., 0)`. Score is `0` when `down_beta_core >= up_beta_core`.
- **Sort direction:** descending.
- **User interpretation:** "Strong gold linkage plus favorable upside-regime participation — who benefits most when gold rallies."
- **Usefulness:** surfaces names that are both high-delta and positively skewed toward up-gold weeks.
- **Not misleading:** uses `up_beta_core` and `down_beta_core` directly. User-facing text avoids the word "gamma" (which would require explaining the sign convention every time).

#### `fragility`

- **Formula:** `max(down_beta_core − up_beta_core, 0)` when `structural_delta_core > scoring_config.delta_bands.low_max`; otherwise `None`.
- **Null-handling:** `None` if any of `structural_delta_core`, `up_beta_core`, `down_beta_core` is missing or non-finite. Also `None` if delta is too low to care about regime fragility.
- **Clamp:** natural `[0, ∞)` via `max(..., 0)`.
- **Sort direction:** descending (most fragile first).
- **User interpretation:** "Negative-skew gap — where a stock's down-gold sensitivity exceeds its up-gold sensitivity."
- **Usefulness:** lets the user invert the Tool A view and see what to be wary of, not just what to buy.
- **Not misleading:** **The lens measures a negative-skew gap, not total stock danger.** User-facing text must say exactly that. A medium-delta name with a large skew gap can outrank a strong-linkage name with a smaller gap — that is correct behavior because the lens is about skew, not about absolute risk. Volatility diagnostics stay in their own card.

#### `cleanliness`

- **Formula:**
  ```
  eligible_r2 = mean(r_squared_<w> for w in {"6m","12m","3y"} if window_status_<w> == "ELIGIBLE" and r_squared_<w> is finite)
  signal_ratio = 1 - (residual_volatility_52w / total_volatility_52w)
  lens_score = eligible_r2 × clamp(signal_ratio, 0, 1)
  ```
- **Null-handling:** `None` if `eligible_r2` cannot be computed (no eligible window has a finite R²). `None` if `total_volatility_52w` is missing, non-finite, or `<= 0`. `None` if `residual_volatility_52w` is missing or non-finite.
- **Clamp:** `signal_ratio` clamped to `[0, 1]`. `eligible_r2` already in `[0, 1]`. Final score in `[0, 1]`.
- **Sort direction:** descending.
- **User interpretation:** "Clean-signal measure — how much of this stock's weekly movement is actually explained by gold, averaged across eligible windows."
- **Usefulness:** surfaces structurally clean names regardless of torque magnitude.
- **Not misleading:** **The lens measures signal cleanliness, not stock attractiveness.** User-facing text must say exactly that. A lower-torque but cleaner name can outrank a high-torque noisy name — that is correct behavior because the lens is about signal-to-noise, not about upside.

### Deferred lenses

- `consistency` — deferred because `delta_stability_score` has magic weights that want tightening first.
- `risk_adjusted` — deferred because the denominator scaling is arbitrary and the composition is too ambiguous.
- `reliability` — noted but not prioritized; a confidence-based trust ranking that might be worth adding after `cleanliness` ships.

### UI behavior

- A small "View by" `<select>` above the overview, default = `composite`. Submits via GET → `/?lens=<id>`.
- **The existing Tool A Score column stays visible.** A new Lens Score column is added next to it.
- Re-sort the table by `lens_score`, direction per lens.
- Below the table, a one-line lens hint: the interpretation sentence above.
- Unknown or missing lens id falls back to `composite` without error.

### Code placement

- New module: `golden_vector/serve/lenses.py`.
- Public surface: `LENS_DEFINITIONS`, `apply_lens(tool_a_outputs, lens_id)`.
- No config changes, no CLI changes, no new dependencies.

### Documentation requirement

- README must state that lenses are **view-only presentation layers**, not official Tool A outputs.

---

## 4. Pair-compare (deferred)

Design shape unchanged. Recap:

- Route `/compare?tickers=NEM,GOLD,AEM` (max 3).
- Reads `tool_a_latest.parquet` and `tool_b_latest.parquet` only — plus the structural-metrics parquet if the provenance rule is satisfied.
- Side-by-side metric grid with per-row winner highlight. Overlaid scatter. Dumbbell of up vs down beta. Tool B row.
- **Subject to the Tool A Detail Provenance Rule.** All three rows must share a `snapshot_refresh_run_id`; if they don't, the compare view suppresses the misaligned rows.
- Built only in Phase 4.

Nothing implemented in this plan.

---

## 5. Beta-history chart

### Gate

Phase 1A's provenance mechanism must be in place and tested first.

### Data source

- Read `data/intermediate/tool_a_structural/tool_a_structural_latest.parquet`.
- After the Phase 1A schema extension, this file carries `source_run_id` per row.
- Verify the structural file's `source_run_id` matches the `tool_a_latest.parquet` row's `source_run_id`.
  - Match → render.
  - Mismatch or missing → suppress with fallback message and CLI suggestion.

### Chart

One panel on the detail page, below Up vs Down Beta.

- **Title:** "12M Rolling Structural Delta"
- **Hint:** "How this stock's weekly structural beta to gold has moved over time."
- **Single line only.** No R² overlay, no second metric.
- **Optional gold-price overlay:** rendered only when the gold history's `snapshot_refresh_run_id` matches the Tool A row's `snapshot_refresh_run_id` AND the beta-history provenance is OK. Otherwise omit the overlay but keep the beta line.
- **Data filter:** `window_id == "12M"` AND `window_status == "ELIGIBLE"`.
- **Axes:** x = `as_of_date`; y = `structural_delta`. Gridlines at `y = 0` and current `structural_delta_core`.
- **SVG style:** consistent with existing `_build_scatter_svg` and `_build_dual_bar_svg`.

### Empty states (all must be visually distinct)

| State | Message |
|---|---|
| Structural file missing | "Structural history file is missing. Run `python main.py tool-a` to generate it." |
| `source_run_id` mismatch | "Structural history is out of sync with the published Tool A row. Re-run `python main.py tool-a` to realign." |
| No eligible 12M rows for this ticker | "This ticker does not have enough clean 12M structural history to plot yet." |
| `score_eligible == False` on the current Tool A row | Chart rendered with a watermark: "Current snapshot score for this stock is withheld; historical series shown for context only." |

### Code placement

- Workspace helpers:
  - `_load_structural_delta_history(paths, ticker, window_id="12M") -> pd.DataFrame`
  - `_structural_history_matches_tool_a(structural_history, tool_a_row) -> bool`
  - `_build_beta_history_svg(series, gold_series=None) -> str`
  - `_render_beta_history_panel(ticker, tool_a_row, structural_history, gold_history_aligned: bool)` — handles all four empty states plus the normal render.

---

## 6. Test plan

No lens ships without a formula test. No chart state ships without a provenance test. No panel ships without a mismatched-source suppression test.

| # | Test | Covers | File | Phase |
|---|---|---|---|---|
| T1 | `composite` lens matches `tool_a_score` row-for-row | Lens formula | `tests/test_lenses.py` | 2A |
| T2 | `upside_torque` formula on a known row with `up > down` | Lens formula | `tests/test_lenses.py` | 2A |
| T3 | `upside_torque` returns `0` when `up == down`, `None` when inputs missing or non-finite | Null + clamp + non-finite | `tests/test_lenses.py` | 2A |
| T4 | `fragility` returns `None` when `delta_core <= low_max` | Gate | `tests/test_lenses.py` | 2A |
| T5 | `fragility` returns positive value when `down > up` and gated delta | Lens formula | `tests/test_lenses.py` | 2A |
| T6 | `cleanliness` averages R² across eligible windows only | Lens formula | `tests/test_lenses.py` | 2A |
| T7 | `cleanliness` returns `None` when `total_volatility_52w == 0` or missing or non-finite | Null + non-finite | `tests/test_lenses.py` | 2A |
| T8 | `cleanliness` clamps `signal_ratio` when `residual > total` | Clamp safety | `tests/test_lenses.py` | 2A |
| T9 | Every lens returns `None` for a `score_eligible=False` row | Withheld default | `tests/test_lenses.py` | 2A |
| T10 | Overview with `?lens=upside_torque` reorders table and shows lens label | Routing | `tests/test_workspace_app.py` | 2A |
| T11 | Overview keeps the Tool A Score column alongside the Lens Score column | UX invariant | `tests/test_workspace_app.py` | 2A |
| T12 | Detail page warns when `tool_a_structural_latest.parquet` is missing | Provenance empty state | `tests/test_workspace_app.py` | 2B |
| T13 | Detail page warns when structural file's `source_run_id` mismatches Tool A row's | Provenance mismatch | `tests/test_workspace_app.py` | 2B |
| **T14** | **Detail page suppresses scatter / up-down-beta / exploratory panels when foundation manifest has moved past the Tool A row** | **Phase 1A provenance suppression** | `tests/test_workspace_app.py` | 1A |
| T15 | Beta-history panel renders for an aligned ticker with eligible 12M rows | Chart render | `tests/test_workspace_app.py` | 2B |
| T16 | Beta-history panel shows withheld-score watermark when `score_eligible=False` | Withheld state on chart | `tests/test_workspace_app.py` | 2B |
| **T17** | **`persist_tool_a_structural_metrics` writes `source_run_id` column** | **Schema extension** | `tests/test_persist_tool_a.py` | 1A |
| T18 | Missing `tool_a_latest.parquet` triggers overview warning (existing) | Retained | `tests/test_workspace_app.py` | (existing) |
| T19 | Missing `tool_b_latest.parquet` triggers overview warning (existing) | Retained | `tests/test_workspace_app.py` | (existing) |
| T20 | Mixed refresh across Tool A and Tool B triggers overview warning (existing) | Retained | `tests/test_workspace_app.py` | (existing) |
| **T21** | **Beta-history panel shows the "no eligible 12M rows" fallback when the ticker has no eligible history** | **Empty state** | `tests/test_workspace_app.py` | 2B |
| **T22** | **Gold overlay on the beta-history chart is suppressed when foundation refresh and chart provenance disagree** | **Gold overlay suppression** | `tests/test_workspace_app.py` | 2B |
| **T23** | **Every suppressed panel leaves a visible fallback card with a title, a reason, and a CLI suggestion — never blank space** | **Visible fallback** | `tests/test_workspace_app.py` | 1A (primary); 2B (extends) |

**Total new/extended tests: 20.** Plus three retained from the holistic-fix pass.

Bold rows (T14, T17, T21, T22, T23) are codex's explicit additions from the v2 review.

---

## 7. Acceptance criteria

### Functional

- [ ] Overview has the lens picker with four lenses; Tool A Score column stays visible.
- [ ] Each lens's formula is pinned by a test.
- [ ] Every lens returns `None` for score-withheld rows, for non-finite inputs, and for score-eligible rows where a required input is missing.
- [ ] Detail page renders the beta-history chart when the structural file's `source_run_id` aligns with the Tool A row's `source_run_id`.
- [ ] Detail page suppresses the chart (and every foundation-backed panel) with a visible fallback when alignment fails.

### Provenance and trust

- [ ] **No visualization silently uses a different refresh than the displayed Tool A row.** Enforced by §1; tested by T12, T13, T14, T16, T22, T23.
- [ ] When foundation has moved ahead of the Tool A row, scatter / up-down-beta / exploratory panels are **suppressed**, not banner-rendered.
- [ ] When the structural-history file's `source_run_id` mismatches the Tool A row's, the beta-history chart is suppressed.
- [ ] Missing `tool_a_structural_latest.parquet` produces a clear warning rather than a blank panel.
- [ ] Score-withheld names stay clearly withheld under every lens and on the beta-history chart.
- [ ] Mixed-refresh warnings at the overview level (T18, T19, T20) still pass.
- [ ] Every suppressed panel leaves a visible fallback card with title + reason + CLI suggestion. No blank dead space anywhere.
- [ ] Optional gold-price overlay on the beta-history chart is omitted when provenance is not safe.

### v1-inheritance gate

- [ ] **All Phase 1 items from `claude_finish_v1_next_steps_plan.md` are complete** (5.1 source verification, 5.2 Tool B polish, 5.3 notes, 5.4 overview, 5.5 provenance) before the visualization layer counts toward v1 completion. The visualization layer passing its own checklist is not sufficient.

### Presentation-layer boundary

- [ ] Lenses are explicitly documented (README) as **view-only presentation layers**, not official Tool A outputs.
- [ ] No lens score is persisted to any parquet or CSV file.
- [ ] No lens score is consumed by any backend code.

### Quality gates

- [ ] All 170 existing tests still pass.
- [ ] The 20 new/extended tests in §6 all pass.
- [ ] README documents the lens picker, the four lenses, and the beta-history panel with the provenance behavior.
- [ ] `docs/golden_vector_architecture_map.md` updated with the new test count and a one-line mention of the visualization layer.

### Explicit non-goals

- No pair-compare implementation (deferred).
- No `consistency`, `risk_adjusted`, or `reliability` lens.
- No R² overlay on the beta-history chart.
- No client-side interactivity.
- No schema changes to `tool_a_latest.parquet` or `tool_b_latest.parquet` beyond what already shipped.

---

## 8. What changed from v2

Six tightenings per codex's v2 review. Nothing else.

| # | Change | Where in v3 |
|---|---|---|
| 1 | Live-recompute panels on foundation-ahead state are **suppressed**, not banner-rendered. Open question #2 from v2 is closed. | §1 "Suppression, not banner"; §7 "When foundation has moved ahead…" |
| 2 | The provenance rule explicitly enumerates every foundation-backed panel: scatter, up-down beta, exploratory ladder, beta-history chart, gold overlay. | §1 "Panels explicitly covered" |
| 3 | The two provenance mechanisms are named separately and used for distinct purposes: `snapshot_refresh_run_id` for foundation-backed panels, `source_run_id` for structural-history artifacts. | §1 "Two provenance mechanisms" |
| 4 | Lens wording tightened: `fragility` = "negative-skew gap, not total stock danger"; `cleanliness` = "clean-signal measure, not stock attractiveness"; non-finite inputs → `None` explicitly for every lens. | §3 lens specs; §3 "Cross-cutting rules" |
| 5 | Three new tests added: T21 (no eligible 12M rows fallback), T22 (gold overlay suppressed on mismatch), T23 (every suppressed panel leaves a visible fallback). | §6 test table |
| 6 | Acceptance criteria inherit Phase 1 of the broader finish plan. Visualization layer passing its own checklist is not sufficient for v1 completion. | §7 "v1-inheritance gate" |

Everything else from v2 is retained verbatim: lens set of four, deferred `consistency` and `risk_adjusted`, `serve/lenses.py` placement, single-line beta chart, deferred compare view.

Open question #1 from v2 (dim vs drop `LOW_OBSERVATION` rows on the chart) is resolved in favor of **drop** — consistent with the "signal cleanliness" framing of the chart and matching the filter already listed in §5.

---

## 9. Summary (one paragraph)

> Add multi-lens ranking and a rolling structural-delta history chart **only after** the core workspace workflow is operationally complete and provenance-safe. Keep both additions strictly presentation-layer only, built from published Tool A / Tool B artifacts tied to one coherent refresh context. Four lenses to start (`composite`, `upside_torque`, `fragility`, `cleanliness`); `consistency` and `risk_adjusted` are deferred. When the foundation snapshot has moved past the displayed Tool A row, every live-recompute panel is **suppressed with a visible fallback**, never banner-rendered. Keep the compare view deferred until the workspace is already a solid day-to-day tool.
