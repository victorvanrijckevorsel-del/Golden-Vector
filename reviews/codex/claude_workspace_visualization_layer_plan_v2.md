# Workspace Visualization Layer Plan — v2

Date: 2026-04-23
Author: Claude (Opus 4.7, 1M context)
Status: Revised in response to [codex_feedback_on_claude_workspace_visualization_layer_plan.md](codex_feedback_on_claude_workspace_visualization_layer_plan.md).
Supersedes: [claude_workspace_visualization_layer_plan.md](claude_workspace_visualization_layer_plan.md).

## 0. Purpose and framing

This document defines the visualization additions that should be layered onto the workspace **after the core v1 workspace workflow is operationally complete.** It is a visualization addendum, not the next immediate implementation order.

It depends on the existing [`claude_finish_v1_next_steps_plan.md`](claude_finish_v1_next_steps_plan.md) being executed first. When operational completeness and provenance are in place, the visualization layer gets added on top without introducing new data-source inconsistency.

What v2 changes compared to v1 (summary of codex's corrections applied):

1. **Execution order inverted.** Operational workspace completion runs first; visualization second.
2. **Tool A Detail Provenance Rule added** as a hard constraint (§1), enforced before the history chart ships.
3. **Lens rollout simplified.** Four lenses only (`composite`, `upside_torque`, `fragility`, `cleanliness`). `consistency` and `risk_adjusted` are deferred until their formulas are tightened.
4. **Every lens formula fully specified** with null-handling, clamps, a plain-English interpretation, and a usefulness rationale.
5. **Tests reframed** around provenance and trust, not rendering.
6. **Acceptance criteria strengthened** with explicit trust/provenance cases.
7. **Compare view stays deferred** (unchanged from v1).

---

## 1. Tool A Detail Provenance Rule (foundational)

**This is a hard constraint on every Tool A panel on the detail page. It must be in place before the beta-history chart ships.**

### The rule

> All Tool A detail panels rendered on one page must be sourced from one coherent snapshot context. No panel may silently recompute or re-read from a different refresh than the displayed Tool A row. If exact alignment is unavailable, the page must warn clearly and either suppress the misaligned panel or mark it explicitly as out-of-sync.

### Practical meaning

A Tool A detail page today draws from up to three sources:
1. The published Tool A row (`tool_a_latest.parquet`) carrying `snapshot_refresh_run_id` and `source_run_id`.
2. The structural-metrics parquet (`tool_a_structural_latest.parquet`) — currently has no provenance columns.
3. A live recomputation from the latest foundation snapshot (used today for the scatter panel and exploratory horizon ladder).

Any panel that reads (2) or (3) without checking its run-id alignment against (1) can silently display stale or mismatched data.

### What the rule requires, concretely

1. **Extend the structural-metrics output schema** to carry `source_run_id` (the Tool A run that produced it) on every row. This is a one-column add to `STRUCTURAL_WINDOW_COLUMNS` plus a matching populate step in `execute_tool_a_profile_pipeline` and `persist_tool_a_structural_metrics`.
2. **Add a workspace-level provenance check** when loading the detail page:
   - Read `tool_a_latest.parquet` row's `source_run_id` for the ticker.
   - Read `tool_a_structural_latest.parquet` row's `source_run_id` for the ticker.
   - Match = detail panels render normally.
   - Mismatch or missing structural file = page renders without the misaligned panels plus a clear notice: "Structural metrics file is out of sync with the published Tool A row for this ticker. Re-run `python main.py tool-a` to realign."
3. **Live-recomputed panels stay, but only when the underlying foundation snapshot matches the Tool A row's `snapshot_refresh_run_id`.** If the foundation manifest has moved ahead of the Tool A row, the scatter panel and exploratory horizon ladder are either suppressed or rendered with an explicit "out-of-sync" watermark. This is codex's Cx-3 from the holistic review and is the same fix for a broader class of issues.

### When the rule is satisfied

- Every Tool A panel on the detail page, including the new beta-history chart, must pass the provenance check or be explicitly suppressed with a user-visible warning.
- There is no "just render it anyway" path.

**The beta-history chart in §5 is gated on this rule being implemented and tested first.**

---

## 2. Execution order (revised)

This replaces the v1 order entirely.

### Phase 1 — Operational workspace completion (from existing v1 finish plan)

Visualization layer is blocked on this phase completing.

1. **Source-verification editing in the workspace** (existing plan §5.1).
2. **Tool B manual-workflow polish** (existing plan §5.2).
3. **Notes polish** (existing plan §5.3).
4. **Overview search/filter/sort** (existing plan §5.4).
5. **Provenance warnings** — already shipped in the holistic-fix pass. Verify still behaving correctly after Phase 1 edits.
6. **Tool A Detail Provenance Rule implemented** (this plan §1). Schema extended; detail page provenance check in place; mismatched panels suppressed with a warning; tests pass.

Phase 1 is complete when the workspace is operationally usable day-to-day AND the provenance rule is enforced.

### Phase 2 — Visualization layer

Only starts after Phase 1 is complete.

1. **2A — Multi-lens ranking** (§3). Four lenses only: `composite`, `upside_torque`, `fragility`, `cleanliness`.
2. **2B — Beta-history chart** (§5). Gated on the provenance rule.

### Phase 3 — Release hardening (existing plan §7)

1. Full repo review.
2. Live smoke checks across the refresh cycle.
3. Docs cleanup.

### Phase 4 — Deferred compare view

Specified in §4 for design pre-commitment only. Not built in this plan.

---

## 3. Multi-lens ranking — v2

### Scope

**Four lenses only.** `consistency` and `risk_adjusted` from v1 are deferred — their formulas were too loose.

### Lens spec

Every lens must have: (a) explicit null-handling, (b) explicit clamp behavior, (c) a one-sentence plain-English interpretation for the user, (d) a usefulness rationale, (e) a reason it is not misleading.

For all lenses:

- **If `score_eligible == False` → `lens_score = None`.** A withheld official score is always a withheld lens score. This is codex's default answer to Claude's open question 5 and it simplifies every lens.
- Lens score `None` renders as `-` and sorts to the bottom (`na_position="last"`).

#### `composite` (default)

- **Formula:** `tool_a_score` (already computed).
- **Null-handling:** `None` when `score_eligible == False` (the existing Tool A behavior).
- **Clamp:** none; natural range is roughly `[0, 100]`.
- **User interpretation:** "Overall Tool A rank — delta, gamma, asymmetry, and confidence combined."
- **Usefulness:** default baseline; what the user sees today.
- **Not misleading:** this is the published official score, no derivation.

#### `upside_torque`

- **Formula:** `structural_delta_core × max(up_beta_core − down_beta_core, 0)`
- **Null-handling:** `None` if any of `structural_delta_core`, `up_beta_core`, `down_beta_core` is `None`.
- **Clamp:** natural clamp to `[0, ∞)` via the `max(..., 0)` term. Score is `0` whenever down-gold regime beta equals or exceeds up-gold regime beta.
- **User interpretation:** "Strong gold linkage plus favorable upside-regime participation — who benefits most when gold rallies."
- **Usefulness:** surfaces names that are both high-delta and positively skewed toward up-gold weeks. Matches the intuition the paper's convex-upside idea points at without misreading the gamma sign convention.
- **Not misleading:** uses `up_beta_core` and `down_beta_core` directly, which the user sees in the existing Up vs Down Beta panel. Explanation avoids the word "gamma" — that's a technical term the user shouldn't need for a ranking lens (per codex answer #1).

#### `fragility`

- **Formula:** `max(down_beta_core − up_beta_core, 0)` **only when** `structural_delta_core > scoring_config.delta_bands.low_max`; otherwise `None`.
- **Null-handling:** `None` if `structural_delta_core`, `up_beta_core`, or `down_beta_core` is `None`. Also `None` if delta is too low to care about regime fragility.
- **Clamp:** natural `[0, ∞)` via `max(..., 0)`.
- **Sort direction:** descending (most fragile first).
- **User interpretation:** "Who falls harder than they rise with gold — stocks whose down-regime beta exceeds their up-regime beta."
- **Usefulness:** directly targets the "fragile" profile the code already labels. Lets the user invert the Tool A view to see what to avoid, not just what to buy.
- **Not misleading:** gated on `delta_core > low_max` so low-linkage names can't rank as fragile. The scalar is just the gap in regime beta — no mixing of volatility into the scalar. Volatility diagnostics stay visible in their own card. This is codex's answer #2: gamma-driven, volatility not bundled.

#### `cleanliness`

- **Formula:**
  ```
  eligible_r2 = mean(r_squared_<w> for w in {"6m","12m","3y"} if window_status_<w> == "ELIGIBLE")
  signal_ratio = 1 - (residual_volatility_52w / total_volatility_52w)
  lens_score = eligible_r2 × clamp(signal_ratio, 0, 1)
  ```
- **Null-handling:** `None` if no eligible window has an R² value (no non-null entries to average). `None` if `total_volatility_52w` is `None`, `0`, or not finite. `None` if `residual_volatility_52w` is `None`.
- **Clamp:** `signal_ratio` is clamped to `[0, 1]` so a pathological `residual_vol > total_vol` can't flip the sign. `eligible_r2` is already in `[0, 1]`. Final score is in `[0, 1]`.
- **User interpretation:** "How much of this stock's weekly movement is actually explained by gold, averaged across the eligible windows."
- **Usefulness:** surfaces the cleanest structural exposures regardless of torque magnitude. A low-delta name with R² ≈ 0.7 is a cleaner signal than a high-delta name with R² ≈ 0.2.
- **Not misleading:** uses an eligible-window R² aggregate, not just the anchor (codex answer #3). The clamp prevents pathological outputs. Explicitly `None` when inputs are missing.

### Deferred lenses

Spelled out so v3 can revisit:

- **`consistency`** — intended to measure cross-window stability of delta. `delta_stability_score` already exists; the lens would be `delta_stability_score × min(weeks_3y/156, 1)`. Deferred because the `delta_stability_score` formula itself has magic weights that want tightening first.
- **`risk_adjusted`** — intended to be a Sharpe-like `tool_a_score / downside_vol`. Codex judged this as "too arbitrary for first implementation" and the denominator scaling was arbitrary. Deferred.

Neither is implemented in v2.

### UI behavior

- A small "View by" `<select>` above the overview, default = `composite`. Submits via GET → `/?lens=<id>`.
- The overview keeps the existing **Tool A Score** column (the official score stays visible always — codex answer #6). A new **Lens Score** column is added next to it.
- Re-sort the table by `lens_score`, direction per-lens (`descending` for `composite`, `upside_torque`, `cleanliness`; `descending` for `fragility` so the most fragile names surface first).
- Below the table, a one-line lens hint: the interpretation sentence above.
- Unknown or missing lens id falls back to `composite` without error.

### Code placement

- New module: `golden_vector/serve/lenses.py` (codex answer #10: presentation-layer concept, stays under `serve/`).
- Public surface:
  - `LENS_DEFINITIONS: dict[str, LensSpec]` where `LensSpec` is a small dataclass with `id`, `title`, `hint`, `sort_descending: bool`, `compute: Callable[[dict], float | None]`.
  - `apply_lens(tool_a_outputs: pd.DataFrame, lens_id: str) -> pd.DataFrame` returns a copy with a `lens_score` column and applied ordering.
- No new dependencies, no config changes, no CLI changes.

### What multi-lens is not

- Not a new model output. Lenses are deterministic re-projections of the published Tool A row, computed at render time.
- Not persisted. The `lens_score` is in memory only for the overview render.
- Not available over the API (there is no API). Only in the overview UI.

---

## 4. Pair-compare (deferred)

Design shape unchanged from v1. Recap:

- Route `/compare?tickers=NEM,GOLD,AEM` (max 3).
- Reads `tool_a_latest.parquet` and `tool_b_latest.parquet` only — plus the structural-metrics parquet if the provenance rule from §1 is satisfied.
- Side-by-side metric grid with per-row winner highlight. Overlaid scatter. Dumbbell of up vs down beta. Tool B row.
- **Subject to the Tool A Detail Provenance Rule.** All three rows must share a `snapshot_refresh_run_id`; if they don't, the compare view shows a mixed-refresh warning and either suppresses the misaligned rows or marks them explicitly.
- Built only in Phase 4 — later, after workspace is a solid day-to-day tool.

Nothing implemented in this plan.

---

## 5. Beta-history chart — v2

### Gate

**This panel is blocked on the Tool A Detail Provenance Rule being implemented and tested (see §1).** It does not ship until the provenance check can reliably detect when `tool_a_structural_latest.parquet` and `tool_a_latest.parquet` disagree.

### Data source

- Read `data/intermediate/tool_a_structural/tool_a_structural_latest.parquet`.
- After §1's schema extension, this file carries `source_run_id` per row.
- Before rendering, verify the structural file's `source_run_id` for the target ticker matches the `source_run_id` on the `tool_a_latest.parquet` row for the same ticker.
  - Match → render the chart.
  - Mismatch or missing file → render a clear empty-state notice and a call to action ("Re-run `python main.py tool-a` to align the structural history with the published Tool A row").

### Chart

One panel on the detail page, below the existing Up vs Down Beta panel.

- **Title:** "12M Rolling Structural Delta"
- **Hint:** "How this stock's weekly structural beta to gold has moved over time."
- **Single line only for v1** (codex answer #8): no R² overlay, no second metric.
- **Optional gold-price overlay:** only if the gold history comes from the same `snapshot_refresh_run_id` as the Tool A row. If not, skip the overlay and show just the beta line.
- **Data filter:** `window_id == "12M"` and `window_status == "ELIGIBLE"`. Drop `INELIGIBLE` and `LOW_OBSERVATION` rows; they would read as noise or artificial extremes.
- **Axes:** x = `as_of_date`; y = `structural_delta`. Light horizontal grid at `y = 0` and at the current `structural_delta_core`.
- **SVG style:** consistent with existing `_build_scatter_svg` and `_build_dual_bar_svg`.

### Empty states

- Structural file missing → "Structural history file is missing. Run `python main.py tool-a` to generate it."
- `source_run_id` mismatch → "Structural history is out of sync with the published Tool A row. Re-run `python main.py tool-a` to realign."
- No eligible 12M rows for this ticker → "This ticker does not have enough clean 12M structural history to plot yet."
- `score_eligible == False` on the current Tool A row → render the chart with a watermark "The current snapshot score for this stock is withheld; historical series shown for context only."

### Code placement

- `workspace.py`:
  - `_load_structural_delta_history(paths, ticker, window_id="12M") -> pd.DataFrame` — reads the parquet, filters to ticker + window + ELIGIBLE, returns `(as_of_date, structural_delta, source_run_id)` sorted by date.
  - `_structural_history_matches_tool_a(structural_history, tool_a_row) -> bool` — checks `source_run_id` equality.
  - `_build_beta_history_svg(series) -> str` — single-line SVG renderer.
  - `_render_beta_history_panel(ticker, tool_a_row, structural_history)` — handles all four empty states plus the normal render. Returns an HTML fragment.

### What the chart is not

- Not interactive. No tooltips, no zoom.
- Not multi-ticker. One ticker at a time; pair-compare is §4.
- Not a regression line. Just the published 12M `structural_delta` time series.

---

## 6. Test plan (provenance-focused)

Codex was explicit: rendering-only tests aren't enough. The test plan must cover the repo's real remaining trust weaknesses.

### Required test coverage

| # | Test | Covers | File |
|---|---|---|---|
| T1 | `composite` lens matches `tool_a_score` row-for-row | Lens formula | `tests/test_lenses.py` (new) |
| T2 | `upside_torque` formula on a known row with `up > down` | Lens formula | `tests/test_lenses.py` |
| T3 | `upside_torque` returns 0 when `up == down`, `None` when inputs missing | Null-handling + clamp | `tests/test_lenses.py` |
| T4 | `fragility` returns `None` when `delta_core <= low_max` | Gate behavior | `tests/test_lenses.py` |
| T5 | `fragility` returns positive value when `down > up` | Lens formula | `tests/test_lenses.py` |
| T6 | `cleanliness` averages R² across eligible windows only | Lens formula | `tests/test_lenses.py` |
| T7 | `cleanliness` returns `None` when `total_volatility_52w == 0` or missing | Null-handling | `tests/test_lenses.py` |
| T8 | `cleanliness` clamps `signal_ratio` when `residual > total` | Clamp safety | `tests/test_lenses.py` |
| T9 | Every lens returns `None` for a `score_eligible=False` row | Withheld default (codex answer #5) | `tests/test_lenses.py` |
| T10 | Overview page with `?lens=upside_torque` reorders table and shows lens label | Routing | `tests/test_workspace_app.py` |
| T11 | Overview keeps the Tool A Score column alongside the Lens Score column | UX invariant (codex answer #6) | `tests/test_workspace_app.py` |
| T12 | Detail page warns when `tool_a_structural_latest.parquet` is missing | Provenance, empty state | `tests/test_workspace_app.py` |
| T13 | Detail page warns when structural file's `source_run_id` disagrees with Tool A row's `source_run_id` | Provenance mismatch (codex req #2, #6) | `tests/test_workspace_app.py` |
| T14 | Detail page suppresses live-recompute panels when foundation snapshot has moved past the Tool A row | Provenance rule §1 | `tests/test_workspace_app.py` |
| T15 | Beta-history panel renders for an aligned ticker with eligible 12M rows | Chart render | `tests/test_workspace_app.py` |
| T16 | Beta-history panel shows the withheld-score watermark when `score_eligible=False` | Withheld state on chart | `tests/test_workspace_app.py` |
| T17 | `persist_tool_a_structural_metrics` writes `source_run_id` column | Schema extension | `tests/test_persist_tool_a.py` (extend) |
| T18 | Missing `tool_a_latest.parquet` triggers overview warning (existing test, keep) | Already passing | `tests/test_workspace_app.py` |
| T19 | Missing `tool_b_latest.parquet` triggers overview warning (existing test, keep) | Already passing | `tests/test_workspace_app.py` |
| T20 | Mixed refresh across Tool A and Tool B triggers overview warning (existing test, keep) | Already passing | `tests/test_workspace_app.py` |

### Coverage categories summary

- **Lens formula + null + clamp** — T1–T9 (nine tests).
- **Lens UX** — T10, T11 (two tests).
- **Provenance — source file alignment** — T12, T13, T14, T17 (four tests).
- **Chart behavior** — T15, T16 (two tests).
- **Retained provenance tests** — T18, T19, T20 (three tests, already in the suite).

Total new/extended tests: **17** (T1–T17). Plus three retained tests carried from the holistic-fix pass.

### Test plan principle

No lens ships without a formula test. No chart state ships without a provenance test. No panel ships without a mismatched-source suppression test. Rendering-only tests are insufficient.

---

## 7. Acceptance criteria (strengthened)

The visualization layer is "ready to call v1" when every one of these is true:

### Functional

- [ ] Overview has the lens picker with four lenses and the Tool A Score column still visible.
- [ ] Each lens's formula is pinned by a test.
- [ ] Lens score is `None` (rendered as `-`, sorted last) for every `score_eligible=False` row across every lens.
- [ ] Detail page renders the beta-history chart when the structural file's `source_run_id` aligns with the Tool A row's `source_run_id`.
- [ ] Detail page suppresses the chart with a clear message when they don't align.

### Provenance and trust

- [ ] **No new visualization silently uses a different refresh than the displayed Tool A row.** Enforced by §1 and tested by T12–T14, T16.
- [ ] Missing `tool_a_structural_latest.parquet` produces a clear warning rather than a blank panel.
- [ ] Score-withheld names stay clearly withheld under every lens and on the beta-history chart.
- [ ] Mixed-refresh states remain visible after the visualization additions (T20 still passes).
- [ ] Live-recompute Tool A detail panels either match the displayed Tool A row's refresh or are visibly out-of-sync.

### Quality gates

- [ ] All 170 existing tests still pass.
- [ ] The 17 new/extended tests listed in §6 all pass.
- [ ] README documents the lens picker, the four lenses, and the beta-history panel with the provenance behavior.
- [ ] `docs/golden_vector_architecture_map.md` updated with the new test count and a one-line mention of the visualization layer.

### Explicit non-goals (for this visualization-layer v1)

- No pair-compare implementation (deferred).
- No `consistency` or `risk_adjusted` lens (deferred until formulas tighten).
- No R² overlay on the beta-history chart (deferred).
- No client-side interactivity (deferred / not planned for v1).
- No schema changes to `tool_a_latest.parquet` or `tool_b_latest.parquet` (only `tool_a_structural_latest.parquet` gets `source_run_id` added, per §1).

---

## 8. What changed from v1 (explicit diff)

| Topic | v1 | v2 |
|---|---|---|
| Framing | "Visualization plan that slots into the existing plan" | "Visualization addendum; depends on operational completion first" |
| Execution order | Lenses → beta chart → rest of workspace → hardening → compare | Operational workspace → provenance rule → lenses → beta chart → hardening → deferred compare |
| Provenance rule | Implicit | Explicit §1, foundational, enforced |
| Lens count | Five (all five at once) | Four (`composite`, `upside_torque`, `fragility`, `cleanliness`) |
| `upside_torque` formula | Used `max(-gamma, 0)` and leaked "gamma" terminology into user text | Uses `up_beta_core − down_beta_core` directly; user text avoids "gamma" |
| `fragility` formula | `max(gamma, 0) + max(downside_vol − residual_vol, 0)` | `max(down_beta_core − up_beta_core, 0)` gated on `delta_core > low_max`; volatility kept out of the scalar |
| `cleanliness` formula | `r_squared_12m × (1 − residual/total)` | Eligible-window R² mean × clamped signal ratio with full null safety |
| `consistency` lens | Included | Deferred until formula tightens |
| `risk_adjusted` lens | Included | Deferred |
| Tool A Score column | Replaced by Lens Score | Kept alongside Lens Score (codex answer #6) |
| Beta-chart provenance | "Reads the parquet; assume same run" | Requires `source_run_id` match; suppress on mismatch |
| Beta chart extras | Optional gold overlay + maybe R² | Single line only, gold overlay only if refresh-aligned |
| Tests | 1 per lens, 1 for chart render, 1 for empty state | 9 lens tests, 6 provenance tests, 2 chart-state tests, schema test, plus retained provenance tests |
| Acceptance criteria | "Renders correctly + existing tests pass" | Adds explicit provenance and withheld-score gates |
| Structural-metrics schema | Read-only | `source_run_id` column added to enable the provenance check |
| Compare view | Deferred | Deferred (unchanged) |

---

## 9. Open questions (remaining)

Only two questions remain open after codex's feedback; both are narrow.

1. **Does the beta-history chart need a config flag to control whether `LOW_OBSERVATION` windows are drawn in a dimmed color vs dropped entirely?** v2 drops them. Alternative: draw them faintly so the user sees where the series started becoming meaningful. Not essential for v1 but worth asking.
2. **When the live-recompute panels (scatter, exploratory horizon) detect that the foundation snapshot has moved past the Tool A row, should the page actively refuse to render those panels or render them with an explicit "source moved ahead" banner?** v2 leaves this as an implementation detail. I slightly prefer the banner because it keeps the page informative while making the mismatch undeniable.

---

## 10. Summary (one paragraph, codex's wording adopted)

> Add multi-lens ranking and a rolling structural-delta history chart **only after** the core workspace workflow is operationally complete and provenance-safe. Keep both additions strictly presentation-layer only, built from published Tool A / Tool B artifacts tied to one coherent refresh context. Four lenses to start (`composite`, `upside_torque`, `fragility`, `cleanliness`); `consistency` and `risk_adjusted` are deferred until their formulas tighten. Keep the compare view deferred until the workspace is already a solid day-to-day tool.
