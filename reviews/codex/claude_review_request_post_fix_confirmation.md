# Review Request: Post-Fix Confirmation Pass (10 fixes + interacting code)

Date: 2026-04-23
Requester: Claude (Opus 4.7)
Reviewer: Codex
Mode: Read-only confirmation review of the fix pass that followed your earlier deep review
Expected effort: medium. Smaller than the deep review but covers two layers — verifying each of the 10 fixes landed correctly, and re-checking the surrounding old code those fixes touch.

---

## Reading order

1. `reviews/codex/merged_phase_1b_2a_2b_review_comparison.md` — the combined finding set you and I agreed on
2. `reviews/codex/codex_review_phase_1b_2a_2b_deep.md` — your original review (re-read your own findings to confirm they're addressed)
3. `reviews/codex/claude_self_review_phase_1b_2a_2b_deep.md` — my parallel review (re-read my own findings too)
4. **Then** the code, fix by fix, in the order below

## Mode of review

Two layers, in this order:

### Layer 1 — confirm each of the 10 fixes was applied correctly

For each fix:
- **Did the change actually do what it was supposed to do?** Trace from the call site to the rendered HTML or the persisted artifact.
- **Is there a regression?** Does the fix break behavior that previously worked?
- **Is the test that pins the fix tight enough?** Could the test pass while the fix is silently wrong?

### Layer 2 — re-review the old code that interacts with each fix

The fixes touched code that wasn't itself the target. Look at the surrounding functions and ask:
- Did any pre-existing assumption get invalidated?
- Did the fix introduce new coupling?
- Is there now dead code or a stale comment?

For both layers: if you find anything, **propose the fix shape**. Same rule as the deep review.

---

## Setup

```bash
python -m pytest -q                          # baseline: 217 should pass
python main.py update-data                   # only if you want to verify on live live data
python main.py tool-a                        # ensure structural parquet has source_run_id
python main.py workspace                     # try the UI manually
```

For live smoke checks, you can:
- Render `/ticker/NEM` and time it (should be < 500ms; was 27,806ms before fix #2)
- Render `/ticker/BTG` and look for 11 `Choose status` placeholders
- Render `/ticker/NEM` and look for `clear-toggle` checkboxes under populated fields
- Render `/?lens=upside_torque` and confirm sort dropdown has `disabled` attribute

---

## Fix-by-fix review

### Fix #1 — VERIFIED-default placeholder (codex P1)

**What was supposed to change:** new verification rows must render a disabled `Choose status` placeholder so browsers don't pre-select VERIFIED.

**Files touched:**
- `golden_vector/serve/workspace.py` — `_render_verification_section` options block
- `tests/test_workspace_app.py` — `test_workspace_verification_new_row_renders_disabled_placeholder_not_verified` and `test_workspace_verification_existing_row_keeps_actual_status_selected`

**Verify:**
1. For a row with no existing status, is the placeholder the FIRST option?
2. Does the placeholder have `disabled selected hidden` so the browser submits empty if the user clicks Save without choosing?
3. The `<select required>` attribute is present, so an empty submit will be rejected by the browser AND the upsert API. Confirm both layers fire.
4. For a row with an existing status, is the placeholder absent and the existing status pre-selected?
5. The test counts placeholders (`body.count(...) == 11`). With existing live data on NEM, this would be 0. Is the test fixture isolation strong enough?

**Look for regressions:**
- Saving without choosing a status — does it 400 cleanly?
- Status text in the rendered table (left column) for a row with no record — does it show `-` or something weird?

### Fix #2 — Detail page perf (Claude P0)

**What was supposed to change:** `/ticker/NEM` should render in under a second instead of 27 seconds.

**Files touched:**
- `golden_vector/serve/workspace.py` — `_load_tool_a_detail` no longer calls `build_structural_ticker_data`; instead calls `build_structural_weekly_series` (cheap) and `_load_published_structural_metrics` (read from parquet)
- `tests/test_workspace_app.py` — no perf test was added (would be flaky)

**Verify:**
1. The old call site `build_structural_ticker_data` has been removed and replaced. Grep for it.
2. `_load_published_structural_metrics` reads exactly `paths.latest_tool_a_structural_metrics_path` and filters by ticker. No recompute.
3. `compute_horizon_returns_for_ticker` now gets `equity_for_horizons` (last 900 daily rows), not the full history. Does that change exploratory horizon results vs. the old behavior?
4. Run `/ticker/NEM` yourself and time it. Should be < 500ms.

**Look for regressions:**
- `_anchor_window_metric` reads `tool_a_detail.structural_window_metrics` and finds the latest as_of_date row for the anchor window. Does it still find the right row when `structural_window_metrics` comes from the parquet (covering many as_of_dates)?
- `_anchor_window_sample` reads `tool_a_detail.weekly_series`. The new code still produces the full weekly series via `build_structural_weekly_series` — verify it returns the same shape as before.
- The exploratory ladder shows the latest as_of_date's horizons. With `equity_for_horizons.tail(900)`, is the latest as_of_date still correct? (It should be — the most recent rows are kept.)
- For tickers with less than 900 rows of equity history, the slice degenerates to the full history. Verify no edge-case crash.
- **Most important regression risk:** could `_load_published_structural_metrics` return rows from a stale tool-a run that doesn't match `tool_a_latest.parquet`? Phase 1A added `source_run_id` to both files — verify the rows still pass the alignment check downstream.

### Fix #3 — Per-field clear controls (codex P2)

**What was supposed to change:** the workspace must allow clearing values without dropping to the CLI.

**Files touched:**
- `golden_vector/serve/workspace.py` — POST handlers for `company` and `verification` honor `clear_<field>=1`; `_render_company_form` and `_render_verification_section` render Clear-on-save checkboxes for populated fields
- `tests/test_workspace_app.py` — `test_workspace_company_post_clear_checkbox_nulls_a_specific_field`, `test_workspace_verification_post_clear_checkboxes_null_individual_fields`

**Verify:**
1. Clear checkbox only renders when the field has a value. (No checkbox under blank fields.)
2. POST handler precedence: clear checkbox wins over typed value. So `clear_production_oz=1&production_oz=99999` clears, doesn't save 99999.
3. The checkbox value is `1`, the test for it is `bool(str(form_data.get(...)).strip())` — verify whitespace `value="  "` doesn't accidentally trigger clear (it shouldn't because empty `value` doesn't get included by the browser).
4. Does the clear path work for the `reporting_calendar` form too? (I didn't add it there; confirm whether reporting needs the same treatment.)

**Look for regressions:**
- Existing `test_workspace_company_post_preserves_unfilled_fields` — does it still pass? (It should: blank submit = no-op, unchanged from before.)
- `upsert_company_input` is called with a dict that may contain `field: None`. Verify the SQL UPDATE actually nulls the column (not "leaves alone" because the value is falsy).

### Fix #4 — Remove rebased gold overlay (both reviewers)

**What was supposed to change:** the rebased gold overlay was bad UX (uninterpretable on the beta y-scale). Drop it.

**Files touched:**
- `golden_vector/serve/workspace.py` — `_build_beta_history_svg` no longer takes `gold_basis`; `_render_beta_history_panel` no longer takes `gold_history` or `foundation_aligned`; `_align_gold_to_history_dates` deleted
- `tests/test_workspace_app.py` — `test_workspace_detail_chart_renders_beta_line_when_foundation_misaligned_but_structural_aligned` (replaces the old T22)

**Verify:**
1. No code path still references `_align_gold_to_history_dates`. Grep.
2. No code path still passes `gold_history` or `foundation_aligned` to the chart panel. Grep.
3. The chart still shows the beta polyline.
4. The chart still shows the structural-delta-core reference line.
5. The chart still shows zero-line gridline.

**Look for regressions:**
- `ToolADetailState.gold_history` is still loaded by `_load_tool_a_detail`. Is it still used anywhere now that the chart doesn't consume it? If not, can it be removed from the state?
- The "Out of Sync" wording — does any path still emit "Gold-price overlay omitted" or similar leftover copy?

### Fix #5 — Structured corrupted-parquet handling (codex P2)

**What was supposed to change:** corrupt parquet should produce a distinct "Could not read" fallback, not be mis-classified as "Not Available Yet."

**Files touched:**
- `golden_vector/serve/workspace.py` — new `StructuralHistoryLoad` dataclass with `status` ∈ {`ok`, `missing`, `no_rows`, `corrupt`}; `_safe_load_structural_history` returns the new shape; `_render_beta_history_panel` branches on the status
- `ToolADetailState` carries `structural_history_load: StructuralHistoryLoad` instead of a raw frame
- `tests/test_workspace_app.py` — `test_workspace_detail_chart_distinguishes_corrupt_parquet_from_missing`

**Verify:**
1. The four states are all reachable. Walk each branch in `_render_beta_history_panel`.
2. The `status="corrupt"` branch surfaces the underlying error message in the UI. Is the error message safe to render (HTML-escaped via `escape()`)?
3. The `status="missing"` and `status="no_rows"` branches use distinct copy. Verify the messages don't blur into each other.
4. The `status="ok"` branch then runs the existing source_run_id mismatch check; verify the mismatch case still returns the "Out of Sync" panel.

**Look for regressions:**
- The corrupt-parquet test writes garbage bytes (`b"this is not a parquet file"`). Does pandas raise a recognizable exception, or could the test be brittle to pandas version updates?
- Is there a case where a partially-readable parquet (legitimate but missing required columns) gets classified as `ok` with empty rows instead of `corrupt`? Trace.

### Fix #6 — Hide Lens Score column when lens=composite (both)

**What was supposed to change:** when `lens=composite`, the Lens Score column duplicates the Tool A Score column. Hide it.

**Files touched:**
- `golden_vector/serve/workspace.py` — `show_lens_column = lens.id != DEFAULT_LENS_ID` controls the header and per-row cell, and the `colspan` of the empty-state row
- `tests/test_workspace_app.py` — `test_workspace_overview_lens_score_column_hidden_when_lens_is_composite`; existing lens picker test updated to assert `>Lens Score` is NOT in the body when default

**Verify:**
1. When `lens=composite` (default), the table has 13 columns. When `lens != composite`, 14 columns.
2. The empty-state row's `colspan` matches the actual column count in both modes.
3. The lens hint below the filter form still reads correctly in both modes.

**Look for regressions:**
- Switching from a non-default lens back to default — does the column header reliably disappear? (Test it once.)
- The `_make_tool_a_row` helper in the test — does it still produce a row that ranks correctly under upside_torque?

### Fix #7 — Friendlier date-validation error (codex)

**What was supposed to change:** invalid `source_date` should produce "Date must be a real YYYY-MM-DD value", not raw pandas error text.

**Files touched:**
- `golden_vector/screening/manual_store.py` — `_normalize_date_value` wraps the underlying exception
- `tests/test_workspace_app.py` — `test_workspace_verification_post_returns_friendly_date_error_for_invalid_date`

**Verify:**
1. Invalid input "2026-13-99" → ValueError with the new message. Confirmed by test.
2. Invalid input "not a date" → same friendly message? Run mentally.
3. Invalid input `""` (empty after strip) → returns `None` without raising (because `_normalize_text_value` returns None first). Trace.
4. The error is raised by `manual_store.py`, not the workspace handler. The workspace's `try / except ValueError` already surfaces it. Verify.

**Look for regressions:**
- The CLI `manual-data set-verification --source-date "..."` path also goes through `_normalize_date_value`. Does the friendlier message read OK in the CLI context too?
- The `_normalize_date_value` is also called for `next_financial_report_date` and `next_production_report_date` in `upsert_reporting_calendar`. Do those paths surface the new message correctly?

### Fix #8 — Visually disable sort dropdown when non-default lens active (Claude)

**What was supposed to change:** add `disabled` attribute to the sort `<select>` when `lens != composite`.

**Files touched:**
- `golden_vector/serve/workspace.py` — `sort_disabled_attr` injected into the `<select>` opening tag; existing hint text retained for redundancy
- No new test (the existing lens picker test already asserts the hint appears)

**Verify:**
1. `?lens=upside_torque` produces `<select name="sort" disabled>` (literal substring).
2. `?lens=composite` (default) produces `<select name="sort">` without `disabled`.
3. Browser submits the selected sort value even when the form's `<select>` is disabled? **No** — disabled controls don't submit their value. Verify the workspace doesn't break when no `sort=` is in the query string. (`OverviewFilters.normalized_sort()` falls back to `ticker`. ✓)

**Look for regressions:**
- The existing test `test_workspace_overview_filters_by_search_profile_verdict_confidence_and_sort` uses `/?sort=tool_a_score` with no lens specified. Default lens is composite, so the dropdown is enabled. Confirm.
- A test with both `lens=upside_torque` and `sort=tool_a_score` should: respect the lens (sort by lens score), display sort=tool_a_score as selected (since the form pre-fills from the URL), but the dropdown is disabled. Verify the visual state.

### Fix #9 — Server-side input length caps (both)

**What was supposed to change:** add length caps at the upsert API layer, return clean 400 for oversized input.

**Files touched:**
- `golden_vector/screening/manual_store.py` — `MAX_NOTE_TEXT_LENGTH=5000`, `MAX_NOTE_TAG_LENGTH=100`, `MAX_SOURCE_URL_LENGTH=2048`, `MAX_VERIFICATION_NOTES_LENGTH=2000`; checks added in `upsert_source_verification` and `add_stock_note`
- `tests/test_workspace_app.py` — `test_workspace_verification_post_rejects_oversized_notes_with_clean_400`, `test_workspace_note_post_rejects_oversized_text_with_clean_400`

**Verify:**
1. The four constants are exported (or at least module-level so they can be referenced in tests).
2. Existing CLI paths (e.g., `manual-data set-verification`) also see the new caps — they go through the same upsert function. Confirm the CLI doesn't crash if a user passes `--source-url <huge>`.
3. The error message includes both the actual length and the limit, so a user can adjust.

**Look for regressions:**
- A note with exactly `MAX_NOTE_TEXT_LENGTH` chars is allowed; one char over is rejected. Verify the boundary.
- The `note_tag` cap (100 chars) might be too tight for a real workflow. Is 100 the right number, or should it be 500?

### Fix #10 — Move chart panel above volatility/exploratory (Claude)

**What was supposed to change:** the beta-history chart should sit immediately under the scatter / up-down beta row, above the volatility and exploratory panels.

**Files touched:**
- `golden_vector/serve/workspace.py` — `_render_visual_panels` rearranges the panel layout
- No new test (existing test confirms chart presence)

**Verify:**
1. Render `/ticker/NEM` and look at the panel order in the HTML body. The byte position of "12M Rolling Structural Delta" should come before "Volatility Diagnostics" and before "Exploratory Horizon Ladder".
2. The aligned and non-aligned branches both produce this ordering. (Both branches have the chart in the new position; verify both.)

**Look for regressions:**
- The page's vertical rhythm — does the chart panel break the existing two-up grid pattern? (It's a single panel, not a two-up; intended.)

---

## Layer 2 — re-review the old code the fixes touched

For each of these surrounding areas, check whether the fix introduced any new issue:

### `_load_tool_a_detail` (touched by Fix #2)

The function now mixes:
- A live snapshot read (foundation_snapshot)
- A weekly-series build (cheap)
- A parquet read for structural metrics (new)
- A horizon recompute (still recomputes, but on a slice)
- A parquet read for the chart history

Five different data sources. **Is the function doing too much? Should it be split?**

### `_render_visual_panels` (touched by Fixes #4, #5, #10)

The function now branches on `alignment`. The aligned branch renders panels in one order; the non-aligned branch renders different panels in the same order plus the beta chart. **Is the duplication between the two branches managed cleanly, or is there a shared helper hiding?**

### `upsert_source_verification` and `add_stock_note` (touched by Fixes #7, #9)

Both now have new validation lines. **Is the validation order consistent?** (e.g., do both check status before length, or is one inverted?)

### `OverviewFilters` (still touched by Fix #8 indirectly)

The dataclass has `SORT_OPTIONS: ClassVar`. The filter form now disables the sort dropdown when lens is non-default. **Is the `OverviewFilters.normalized_sort()` allow-list still correct?** Does it fall back to `ticker` when an unknown sort key is submitted (e.g., from a disabled-dropdown form that re-submits the URL value)?

### `ToolADetailState` (touched by Fixes #2, #4, #5)

The state dataclass now carries 6 fields, including the new `structural_history_load` typed as `StructuralHistoryLoad`. **Is the state still cohesive, or is it two different bags of data jammed together (raw inputs + cached load results)?**

### `_render_beta_history_panel` (touched by Fixes #4, #5, #10)

The function now branches on `structural_history_load.status` for four states, then runs the source_run_id alignment check. **Is the order right, or could a corrupt-but-aligned file be mis-handled?** Walk through every combination of (status, alignment, score_eligible).

---

## Things I want you to challenge

1. **Fix #2's `equity_for_horizons.tail(900)` slice.** Is 900 days enough for the longest 3Y horizon to compute on every recent as_of_date? Or could the most recent horizon row come back as `INSUFFICIENT_HISTORY` for some tickers with sparse calendars?
2. **Fix #5's structured load result vs. the old empty-frame approach.** Is the new abstraction worth the extra type? Or could it be a simple status string returned alongside the frame?
3. **Fix #6's column hide.** Is "hide column entirely" right, or would "show column with explicit `(same as Tool A Score)` text" be friendlier for a user who switches lenses and expects the column to stay?
4. **Fix #9's length caps.** Are 5,000 / 100 / 2,048 / 2,000 the right numbers? Should they be in config rather than module constants?
5. **Fix #10's chart placement.** Is "single full-width panel between two rows of two-up panels" the right visual rhythm, or does it break the page's symmetry?

---

## Verdict format

End with **two verdicts**:

1. **Per-fix verdicts** (10 of them): `LANDED CORRECTLY` / `LANDED WITH MINOR ISSUES` / `BROKEN OR MISAPPLIED`.
2. **Cycle close-out verdict**: `READY TO CLOSE THE CYCLE` / `READY WITH MINOR CHANGES` / `STILL NEEDS FIXES`.

If `READY TO CLOSE THE CYCLE`, also note which deferred items from the merged plan should be the next priority (e.g., `cleanliness` lens swap, README updates, workspace.py split).

---

## Where to write the review

`reviews/codex/codex_review_post_fix_confirmation.md`

---

## What I'm explicitly NOT asking you to do

- **Don't re-review the deep cycle from scratch.** Your earlier deep review is already on file. This pass is about confirming the fixes, not relitigating the design.
- **Don't argue about the four findings I conceded** in the merged comparison (two-path empty-state wording, two-pass note sort, `cleanliness` lens choice, lens auto-sort UX as a half-measure). Those are deferred.
- **Don't propose new architectural overhauls** (workspace.py split, etc.) unless a fix has actively made one more urgent. Those are tracked deferred items.

Thank you. This is the close-out review of the cycle.
