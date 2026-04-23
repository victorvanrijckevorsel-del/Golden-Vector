# Phases 1B + 2A + 2B Implementation Summary

Date: 2026-04-23
Author: Claude (Opus 4.7)
Scope: Operational workspace completion (Phase 1B), multi-lens ranking (Phase 2A), and the rolling 12M structural-delta chart (Phase 2B), all built per [plan v3](claude_workspace_visualization_layer_plan_v3.md). Holistic self-review at the end.

Test result: **208 passed in 25.84s** (was 175 at end of Phase 1A).
Live smoke check (against the on-disk `tool_a_latest.parquet` + `tool_a_structural_latest.parquet`): **21/21 behaviors verified** end-to-end.

---

## Phase 1B — Operational workspace completion

| Sub-phase | Scope | Code | Tests added |
|---|---|---|---|
| 1B.1 | Source-verification editing inline in the workspace | `golden_vector/serve/workspace.py` (`_render_verification_section` + new `/ticker/<T>/verification` POST handler) | 5 |
| 1B.2 | Tool B manual-workflow polish: per-field status badges + readiness summary | `_render_company_form` extended | 1 |
| 1B.3 | Notes polish: status badges, OPEN→WATCH→DONE bucketed sort, summary line | `_render_note_section` rewritten | 1 |
| 1B.4 | Overview search/filter/sort: `OverviewFilters` dataclass + filter form | New `OverviewFilters`, `_render_overview_filters_form`, `_overview_sort_key` | 1 |

Key design decisions:

- **Null-on-blank guard reused everywhere.** Every form (company, reporting, verification) treats empty optional inputs as "leave unchanged." Clearing a field requires the CLI's `--clear-fields`. Documented inline in the form hint text.
- **Verification form iterates `REQUIRED_MANUAL_FIELDS`**, not the rows that already exist. This means every Tool B field shows a row whether or not a verification record has been created yet.
- **Status validation** is server-side: `field_name` must be in `REQUIRED_MANUAL_FIELDS`; `verification_status` must be one of `VERIFIED / ESTIMATED / INCOMPLETE`.
- **Readiness summary** counts populated / verified / estimated / explicitly-incomplete / missing on the company form. Uses badges (`badge-verified`, `badge-estimated`, `badge-incomplete`, `badge-needs`, `badge-missing`) for per-field state.
- **Notes sorting**: a stable two-pass sort places OPEN at the top, WATCH next, DONE at the bottom; within each bucket newest first.
- **Overview filters use GET** so URLs are shareable and the back button works. The sort dropdown is a small allow-list (`ticker`, `tool_a_rank`, `tool_b_rank`, `tool_a_score`, `tool_b_score`); unknown values fall back to `ticker`.
- **Sort direction bug** (caught during 1B.4 development): I initially both negated values AND passed `reverse=True`, which canceled out. Fixed by baking direction into the key and never using `reverse`.

---

## Phase 2A — Multi-lens ranking

| Lens | Formula | Notes |
|---|---|---|
| `composite` | `tool_a_score` | Default — keeps the published rank |
| `upside_torque` | `delta_core × max(up_beta_core − down_beta_core, 0)` | Avoids the word "gamma" in user copy |
| `fragility` | `max(down_beta_core − up_beta_core, 0)` gated on `delta_core > delta_bands.low_max` | Negative-skew gap — explicitly NOT total stock danger |
| `cleanliness` | `mean(eligible-window R²) × clamp(1 − residual_vol/total_vol, 0, 1)` | Signal cleanliness — explicitly NOT stock attractiveness |

`consistency` and `risk_adjusted` deferred per v3.

Cross-cutting rules implemented:
- `score_eligible == False` → every lens returns `None`.
- Any non-finite input (NaN, ±inf) → `None`.
- Lens score `None` renders as `-` and sorts to the bottom.
- Unknown lens id falls back to `composite` without error.

UX:
- New "View by lens" `<select>` in the overview filter form.
- Default Tool A Score column is **kept** alongside the new Lens Score column (codex's UX invariant).
- When the active lens is non-default, the table is auto-sorted by lens score in the lens's direction; the user's `sort=...` is ignored and a hint says so.
- Each lens carries a one-sentence description rendered below the filter form.

Tests:
- 15 lens-formula tests (`tests/test_lenses.py` — null/clamp/eligible-row/withheld coverage for all four lenses).
- 2 UX tests in `tests/test_workspace_app.py` (`test_workspace_overview_lens_picker_reorders_table_by_lens_score`, `test_workspace_overview_unknown_lens_falls_back_to_composite`).

Module placement: `golden_vector/serve/lenses.py` — view-only, no model writes, no persistence, no CLI integration.

---

## Phase 2B — Rolling 12M structural delta chart

Data source: `data/intermediate/tool_a_structural/tool_a_structural_latest.parquet` (`source_run_id` column added in Phase 1A).

Provenance behavior (per v3 §1, §5):

| State | Chart body | Gold overlay |
|---|---|---|
| Foundation aligned + structural file `source_run_id == tool_a_row.source_run_id` | Renders | Renders |
| Foundation aligned + structural mismatch | "Out of Sync" panel | – |
| Foundation aligned + no eligible 12M rows for ticker | "Not Available Yet" panel | – |
| Foundation aligned + structural file missing | "Not Available Yet" panel | – |
| Foundation misaligned + structural OK | Beta line renders | Suppressed with visible note |
| Foundation misaligned + structural missing | "Not Available Yet" panel | – |
| Score-withheld row | Chart still renders with "context only" watermark | Same as alignment dictates |

Decision: **separate "Out of Sync" and "Not Available Yet" wording** so a user can distinguish a stale file from a missing one. Out-of-sync is reserved for the `source_run_id` mismatch case.

SVG chart implementation:
- Single `<polyline>` for the beta line (≈1300 weekly points for NEM 12M; rendered at 720×240).
- Optional gold-price overlay as a dashed line, rebased to the chart band so it visually fits.
- Horizontal dashed gridlines at `y = 0` and at the current `structural_delta_core`.
- Date labels at the chart's left and right edges.
- Y-axis labels for the dynamic min/max.
- No interactivity (server-rendered SVG only).

Tests added (6 in `tests/test_workspace_app.py`):
- T12: missing structural file → "Not Available Yet" panel.
- T13: structural file `source_run_id` mismatch → "Out of Sync" panel.
- T15: aligned + eligible 12M rows → SVG chart renders.
- T16: score-withheld row → chart renders with the "context only" watermark.
- T21: ticker has rows but none ELIGIBLE → "Not Available Yet" empty state.
- T22: foundation misaligned + structural OK → beta line renders, gold overlay explicitly suppressed with a visible note.

---

## Holistic self-review

### Issues found and fixed during this pass

1. **Sort direction bug (Phase 1B.4)** — I initially both negated values in the key and passed `reverse=True` to `list.sort`. Caught by my own test (`test_workspace_overview_filters_by_search_profile_verdict_confidence_and_sort` failed with `7982 < 7804`). Fixed by baking direction into the key and never using `reverse`.
2. **WSGI test helper didn't split query string** — `PATH_INFO` was getting the whole `"/?search=NEM"` string, so the route check `path == "/"` failed. Fixed `_call_wsgi_app` to `partition("?")`.
3. **`SORT_OPTIONS` declared as a dataclass field instead of `ClassVar`** — worked accidentally but smelled wrong. Cleaned up with `from typing import ClassVar` and `SORT_OPTIONS: ClassVar[...] = ...`.
4. **Globals-based path injection for the chart panel** — my first attempt at threading `paths` and `gold_history` through the render chain used module-level dicts. Rewrote to extend `ToolADetailState` with `gold_history` and `structural_history_12m` fields, threading them through `_load_tool_a_detail`. Cleaner, no globals.
5. **Empty-state wording collision** — the chart's "missing file" empty state initially used the "Out of Sync" wording, which broke the existing aligned-baseline test (which asserts `"Out of Sync" not in body`). Split into two distinct wordings: `"— Out of Sync"` for `source_run_id` mismatch only, `"— Not Available Yet"` for missing-file or no-eligible-rows.
6. **Test typo** — asserted `"12 rolling structural delta"` instead of `"12m rolling structural delta"` in T15. Fixed.

### Live smoke-check results (real data)

Run via Python directly against the on-disk `tool_a_latest.parquet` + `tool_a_structural_latest.parquet`:

- **Overview defaults**: lens picker present, all four lenses in dropdown, all three filters present, sort dropdown present, all 8 tickers visible, both Tool A Score and Lens Score columns rendered.
- **Lens switch (`?lens=upside_torque`)**: column header changes to "Lens Score (Upside torque)", sort-disabled hint appears, lens-description text shows.
- **Profile filter (`?profile=CONVEX`)**: only BTG visible (the only CONVEX name), "Showing 1 of …" message correct.
- **Detail page `/ticker/NEM`**: Source Verification section with all 11 field rows + 11 hidden `field_name` inputs + status `<select>` per row. Tool B readiness summary line. Note section with summary. Beta-history panel with `<polyline points=...>` rendered. No "Out of Sync" text on the aligned page.
- **Detail page `/ticker/FRES.L`** (foreign currency): renders fully, beta-history chart present.

### Things I did **not** ship in this pass

- The `consistency` and `risk_adjusted` lenses (deferred per v3).
- Pair-compare view (deferred per v3 / finish plan).
- R² overlay on the beta-history chart (deferred — chart is one line per v3).
- Browser-side interactivity (out of scope per v3).

### What codex should focus on in a review

1. **Provenance integration across phases.** Did the new chart panel correctly respect Phase 1A's two provenance mechanisms (`source_run_id` for the chart, `snapshot_refresh_run_id` for the gold overlay)? Live smoke says yes; please re-verify.
2. **Lens module purity.** Does `golden_vector/serve/lenses.py` stay strictly read-only with respect to the published Tool A row? Any backdoor that could let a lens score leak into a persisted artifact?
3. **Verification form null-on-blank correctness.** Same regression pattern as the company form. Test `test_workspace_verification_post_preserves_unfilled_optional_fields` covers it; please confirm the test's assertions are tight enough.
4. **Overview filter combinatorics.** Can search + profile filter + lens + sort produce a surprising result? In particular, when `lens != composite` AND `sort != ticker`, does the page sensibly explain why the sort is being ignored?
5. **Test file size.** `test_workspace_app.py` is now 1,467 lines with 30 tests. Is that becoming unwieldy? Should it be split (e.g. `test_workspace_overview.py`, `test_workspace_detail.py`, `test_workspace_forms.py`)?
6. **Chart performance.** `_align_gold_to_history_dates` does an O(N×M) lookup for the gold overlay. With ~1300 history dates and ~6500 gold dates the chart still renders in milliseconds, but `np.searchsorted` would be cleaner. Worth fixing now or later?
7. **CSS sprawl.** I added several new CSS rules (badges, verification-form layout, overview filters, note styles). Is the inline `<style>` block getting too long?

### What plan v3 promised vs what shipped

| Plan v3 §6 test ID | Description | Status |
|---|---|---|
| T1 | `composite` lens matches `tool_a_score` | ✓ |
| T2 | `upside_torque` formula on a known row | ✓ |
| T3 | `upside_torque` returns 0 / None edge cases | ✓ (3 cases) |
| T4 | `fragility` returns None when `delta_core <= low_max` | ✓ |
| T5 | `fragility` positive when `down > up` and gated | ✓ |
| T6 | `cleanliness` averages R² across eligible windows | ✓ |
| T7 | `cleanliness` returns None on missing/0/non-finite vol | ✓ |
| T8 | `cleanliness` clamps `signal_ratio` | ✓ |
| T9 | Every lens returns None for `score_eligible=False` | ✓ |
| T10 | `?lens=upside_torque` reorders table | ✓ |
| T11 | Tool A Score column kept alongside Lens Score | ✓ |
| T12 | Detail warns when structural file is missing | ✓ ("Not Available Yet") |
| T13 | Detail warns on `source_run_id` mismatch | ✓ ("Out of Sync") |
| T14 | Foundation-misaligned suppresses scatter / up-down / exploratory | ✓ (Phase 1A, plus 2 new state tests for FOUNDATION_MISSING and TOOL_A_MISSING_REFRESH) |
| T15 | Beta-history panel renders for aligned ticker | ✓ |
| T16 | Withheld-score watermark on chart | ✓ |
| T17 | `persist_tool_a_structural_metrics` writes `source_run_id` | ✓ (Phase 1A) |
| T18 | Missing `tool_a_latest` overview warning | ✓ (existing) |
| T19 | Missing `tool_b_latest` overview warning | ✓ (existing) |
| T20 | Mixed refresh overview warning | ✓ (existing) |
| T21 | "No eligible 12M rows" fallback | ✓ |
| T22 | Gold overlay suppressed on foundation mismatch | ✓ |
| T23 | Visible fallback card for every suppressed panel | ✓ (Phase 1A + Phase 2B) |

All 23 tests in plan v3 §6 are implemented and green.

### Acceptance criteria check (plan v3 §7)

- [x] Lens picker with four lenses; Tool A Score column stays visible.
- [x] Each lens's formula pinned by a test.
- [x] Every lens returns `None` for score-withheld / non-finite / missing-input rows.
- [x] Beta-history chart renders when aligned.
- [x] Beta-history chart suppressed (with visible fallback) when not aligned.
- [x] No new visualization silently uses a different refresh than the displayed Tool A row.
- [x] Foundation-ahead → suppression, not banner.
- [x] Structural mismatch → chart suppressed.
- [x] Missing structural file → clear warning.
- [x] Score-withheld names stay clearly withheld.
- [x] Mixed-refresh overview warnings still pass.
- [x] Every suppressed panel leaves a visible fallback card.
- [x] Gold overlay omitted when not provenance-safe.
- [x] All previous tests still pass (175 → 208).
- [x] Tests for the new behavior added.
- [ ] README updated (deferred — minor doc note for after codex review).
- [ ] Architecture map test count updated (deferred — same).

The two unchecked boxes are documentation updates that I'll batch after codex confirms the implementation.

---

## Final state

Test count: **208 passed**
Live smoke checks: **21/21**
Phase 1B sub-phases (1B.1–1B.4): all green.
Phase 2A: all green.
Phase 2B: all green.
Holistic self-review: 6 bugs found and fixed during the pass; no remaining issues identified.

Ready for codex to review.
