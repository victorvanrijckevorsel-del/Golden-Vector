# Codex Review: Post-Fix Confirmation Pass

Date: 2026-04-23  
Reviewer: Codex  
Mode: Read-only confirmation review of the 10-fix pass

## Findings first

| Priority | Area | Finding | Why it matters | Concrete fix |
|---|---|---|---|---|
| `P2` | Fix #2 / `_load_tool_a_detail` | The performance fix landed, but the live `/ticker/NEM` render is still above the stricter `<500ms` target on my machine | I measured 5 live requests against the real repo workspace app: **714ms, 542ms, 563ms, 583ms, 581ms**; average **597ms**. This is a huge improvement over ~27s and is safely under 1s, but it does not fully hit the tighter target stated in the request. | Treat the performance bug as largely fixed, but if the stricter target matters, the next cheap wins are: cache the loaded foundation snapshot per request cycle, stop carrying unused `gold_history` through `ToolADetailState`, and avoid any extra parquet reads when the detail page doesn’t need them. |
| `P2` | Fix #5 / surrounding code | Corrupt structural parquet is now classified correctly for the chart, but `_load_published_structural_metrics()` still swallows parquet-read failures into an empty frame | That means the chart can honestly say “Could not read the structural history file,” while the scatter / up-down panels silently degrade because their anchor metrics came back empty. The file-state classification is now asymmetric across the same artifact. | Reuse the structured load result for both chart history and published structural metrics, or add a sibling structured loader for `_load_published_structural_metrics()` so the rest of the Tool A detail page can show one consistent artifact-health state. |
| `P3` | Fix #3 / docs/comments | The verification-section docstring is now stale | `_render_verification_section()` still says “Clearing a field requires the CLI's `--clear-fields`,” which is no longer true after the clear-checkbox fix. | Update the docstring and any matching hint/comment text so the code describes the real behavior. |
| `P3` | Fix #3 / tests | The clear-control tests do not pin the stated precedence rule tightly enough | The request explicitly asked to verify “clear wins over typed value.” The implementation does that, but the tests only prove “clear checkbox can null a field,” not the higher-risk case `clear_field=1&field=value`. | Add one company test and one verification test where the request body includes both a clear checkbox and a conflicting typed value, then assert the stored field is null. |
| `P3` | Fix #9 / tests | Length-cap coverage is still incomplete | The oversized verification notes and note body are tested, but there is no direct boundary test for “exactly max allowed,” and no direct test for `source_url` or `note_tag` caps. | Add 4 small tests: exact-limit note accepted, exact-limit verification notes accepted, oversized source_url rejected, oversized note_tag rejected. |

## What I checked

- `python -m pytest -q` → **217 passed**
- Code inspection across:
  - `/ticker/<T>` handlers
  - `_load_tool_a_detail`
  - `_render_visual_panels`
  - `_render_beta_history_panel`
  - `_render_verification_section`
  - `_render_company_form`
  - `upsert_source_verification`
  - `add_stock_note`
- Live WSGI smoke checks against the real repo data:
  - `/ticker/NEM`
  - `/ticker/BTG`
  - `/?lens=upside_torque`
- Focused logic checks:
  - `build_structural_weekly_series()` vs old `build_structural_ticker_data().weekly_series` on real `NEM` → **exact same weekly series**
  - full-history vs `tail(900)` exploratory horizon calculation on `NEM`, `FRES.L`, `BTG` → **same latest `as_of_date` and same latest horizon rows**
  - live `source_run_id` alignment between `tool_a_latest.parquet` and `tool_a_structural_latest.parquet` for `NEM` and `BTG` → **matched**

---

## Per-fix review

### Fix #1 — VERIFIED-default placeholder

### Did it land?

Yes.

- New verification rows now render:
  - placeholder first
  - `disabled selected hidden`
  - `<select required>`
- Existing rows with a real status skip the placeholder and pre-select the stored status.
- On a live `/ticker/BTG` render, I saw **11** `Choose status` placeholders, which matches the “no existing verification rows” expectation.
- Rows with no verification record still show `-` in the “Current Status” column, which is correct.

### Regression?

No regression found.

- Browser-side required validation now protects casual empty submits.
- Server-side validation still catches manual empty submits because the handler still passes `verification_status=""` to `upsert_source_verification()`, which returns a clean `400`.

### Is the test tight enough?

Mostly yes.

- The placeholder-count test is isolated correctly in a temp workspace with no verification rows.
- The counterpart test for an existing row is also good.
- I would not change the fix itself.

### Verdict

**`LANDED CORRECTLY`**

---

### Fix #2 — Detail page performance

### Did it land?

Mostly yes.

- The workspace no longer calls `build_structural_ticker_data()` in `_load_tool_a_detail`.
- It now:
  - loads the latest foundation snapshot
  - builds only the cheap weekly series
  - reads published structural metrics from parquet
  - computes exploratory horizons on `tail(900)` instead of the full daily history
- I also verified that:
  - the weekly series produced by `build_structural_weekly_series()` is exactly equal to the old weekly series from `build_structural_ticker_data()` on live `NEM`
  - the latest exploratory horizon rows from `tail(900)` match the full-history result on live `NEM`, `FRES.L`, and `BTG`

### Regression?

No clear functional regression found.

- `_anchor_window_metric()` still finds the latest anchor row correctly from the published structural parquet.
- `_anchor_window_sample()` still has the correct weekly sample base because the weekly series is unchanged.
- The `tail(900)` slice is enough for the current official exploratory horizons in live use.

### Is the test tight enough?

There is still no regression test for the performance-sensitive part. That is understandable because timing tests are flaky.

The real confirmation is the live behavior:

- `/ticker/NEM` is now around **0.54–0.71s**
- This is a massive improvement from ~27s
- But it did **not** consistently hit the stricter `<500ms` target from the request on my machine

### Verdict

**`LANDED WITH MINOR ISSUES`**

Reason:
- the fix shape is correct
- the regression risk looks low
- but the stricter performance target is not fully met in my live measurement

---

### Fix #3 — Per-field clear controls

### Did it land?

Yes, with one testing gap.

- Company form now shows `Clear on save` checkboxes only for populated fields.
- Verification form now shows `Clear` checkboxes only for populated optional fields.
- The POST handlers check `clear_<field>` before reading the typed value, so clear wins over value in the actual code path.
- Reporting calendar did **not** get separate clear checkboxes, but that is okay because the reporting handler already passes blank fields through `upsert_reporting_calendar()`, where `None` clears them.

### Regression?

No regression found.

- Blank submit still behaves as no-op for company fields.
- `upsert_company_input()` still nulls a column when the value in `values` is `None`.
- Verification partial-clear behavior works as expected.

### Is the test tight enough?

Not fully.

- The current tests prove that clearing works.
- They do **not** prove the precedence rule in the highest-risk scenario where both:
  - `clear_field=1`
  - and a conflicting typed value
  are present in the same POST.

The code is correct, but the tests should pin that explicitly.

### Verdict

**`LANDED WITH MINOR ISSUES`**

---

### Fix #4 — Remove rebased gold overlay

### Did it land?

Yes.

- `_build_beta_history_svg()` no longer takes `gold_basis`
- `_render_beta_history_panel()` no longer takes `gold_history` or `foundation_aligned`
- `_align_gold_to_history_dates()` is gone
- No chart copy still mentions the overlay
- The beta line, zero line, and current-delta-core reference line are all still rendered

### Regression?

No functional regression in the chart itself.

One surrounding-code cleanup issue remains:

- `ToolADetailState.gold_history` is still carried around but is no longer used anywhere in the workspace rendering path

That is dead state, not a user-facing bug.

### Is the test tight enough?

Yes for the main behavior.

- The updated chart test correctly checks that the beta line still renders in the misaligned-foundation case and that no gold-overlay copy remains.

### Verdict

**`LANDED WITH MINOR ISSUES`**

Reason:
- the user-facing fix landed
- one stale state field remains and should be removed

---

### Fix #5 — Structured corrupted-parquet handling

### Did it land?

Yes, for the chart panel.

- `StructuralHistoryLoad` now distinguishes:
  - `missing`
  - `corrupt`
  - `no_rows`
  - `ok`
- `_safe_load_structural_history()` returns those states correctly
- `_render_beta_history_panel()` branches correctly on them
- The corruption fallback escapes the underlying error message before rendering
- The `ok` path still runs the `source_run_id` mismatch gate afterward

### Regression?

No regression in the chart branch itself.

But there is one surrounding inconsistency:

- `_load_published_structural_metrics()` still swallows parquet read failures and returns an empty frame
- so the same corrupt parquet can be:
  - honestly reported as corrupt in the chart
  - silently treated as “no anchor metrics” elsewhere on the detail page

That is not a regression from the fix, but it is an interacting-code issue worth cleaning up.

### Is the test tight enough?

Mostly yes.

- The garbage-bytes test is reasonable for catching the intended branch.
- It should be stable enough because any parquet reader failure lands in the same structured `corrupt` state.

### Verdict

**`LANDED WITH MINOR ISSUES`**

---

### Fix #6 — Hide Lens Score column when lens=composite

### Did it land?

Yes.

- Default/composite view now has **13** columns
- Non-default lens view has **14**
- `colspan` adjusts correctly with `column_count = 14 if show_lens_column else 13`
- The live overview behaves correctly when switching between default and non-default lenses

### Regression?

No regression found.

### Is the test tight enough?

Yes.

- The dedicated column-hide test is good
- The updated lens-picker test still confirms the non-default lens path

### Verdict

**`LANDED CORRECTLY`**

---

### Fix #7 — Friendlier date-validation error

### Did it land?

Yes.

- `_normalize_date_value()` now raises:
  - `Date must be a real YYYY-MM-DD value (got '...').`
- This applies not just to workspace verification POSTs, but also to:
  - reporting calendar updates
  - CLI paths that share the same normalization function

### Regression?

No regression found.

- Empty string still normalizes to `None`
- valid dates still pass

### Is the test tight enough?

Good enough.

- The workspace invalid-date test pins the new message.
- I would not insist on a second copy for reporting, since it uses the same helper.

### Verdict

**`LANDED CORRECTLY`**

---

### Fix #8 — Disable sort dropdown when non-default lens active

### Did it land?

Yes.

- `sort_disabled_attr = " disabled" if lens.id != DEFAULT_LENS_ID else ""`
- In a live `/?lens=upside_torque&sort=tool_a_score` render, I confirmed the HTML contains:
  - `<select name="sort" disabled>`
  - and the selected sort option still reflects the URL

### Regression?

No regression found.

- Disabled controls do not submit values, but `OverviewFilters.normalized_sort()` already falls back safely to `ticker`
- The default composite path still leaves the dropdown enabled

### Is the test tight enough?

This fix still lacks a dedicated test.

- The existing lens-picker test checks the hint text, not the actual `disabled` attribute
- I verified it live, but it should still have a direct assertion

### Verdict

**`LANDED WITH MINOR ISSUES`**

---

### Fix #9 — Server-side input length caps

### Did it land?

Yes.

- Module-level caps exist:
  - `MAX_NOTE_TEXT_LENGTH = 5000`
  - `MAX_NOTE_TAG_LENGTH = 100`
  - `MAX_SOURCE_URL_LENGTH = 2048`
  - `MAX_VERIFICATION_NOTES_LENGTH = 2000`
- `upsert_source_verification()` and `add_stock_note()` enforce them
- Error messages include both actual length and limit
- CLI callers reuse the same validation path, so they should see the same friendly `ValueError`s

### Regression?

No regression found.

- Exact-over-limit behavior is correctly handled by the code
- I did not find any crashy path

### Is the test tight enough?

Not fully.

- Oversized verification notes and note text are covered
- Exact-boundary acceptance is not covered
- `source_url` and `note_tag` caps are not directly covered

### Verdict

**`LANDED WITH MINOR ISSUES`**

---

### Fix #10 — Move chart panel above volatility / exploratory

### Did it land?

Yes.

- In the aligned branch:
  - scatter + up/down
  - then chart
  - then volatility + exploratory
- In the non-aligned branch:
  - suppressed scatter + suppressed up/down
  - then volatility + suppressed exploratory
  - then chart

That means the “chart above vol/exploratory” rule is true only in the aligned branch, not the non-aligned branch.

I checked live `/ticker/NEM` and confirmed the aligned branch ordering:
- `12M Rolling Structural Delta` appears before `Volatility Diagnostics`
- and before `Exploratory Horizon Ladder`

### Regression?

No user-facing regression found.

But the fix description said both aligned and non-aligned branches should follow the new ordering. The code does not fully do that.

### Is the test tight enough?

There is still no direct ordering test.

### Verdict

**`LANDED WITH MINOR ISSUES`**

Reason:
- aligned branch matches the intent
- non-aligned branch still leaves the chart after the volatility row

---

## Layer 2 — surrounding-code re-review

### `_load_tool_a_detail`

This function is doing a lot, but it is still understandable.

What changed well:
- the expensive structural recompute is gone
- weekly series remained correct
- latest horizons remain correct on the live names I checked

What still feels off:
- `gold_history` is still carried in `ToolADetailState` but is no longer used by the workspace
- `_load_published_structural_metrics()` silently returns empty on parquet-read failure, which now conflicts with the new explicit chart corruption handling

### `_render_visual_panels`

The aligned branch is clean.

The non-aligned branch still differs in panel order from the aligned branch after Fix #10:
- aligned: chart before vol/exploratory
- non-aligned: chart after vol/suppressed exploratory

This is not a bug, but it means the fix only half-landed.

### `upsert_source_verification` and `add_stock_note`

Validation order is fine:
- status / required checks first
- then text/date normalization
- then length caps

No issue there.

### `OverviewFilters`

Still correct.

- unknown sort keys still fall back to `ticker`
- the disabled sort control does not create a broken state when no `sort=` is submitted

### `ToolADetailState`

This state is slightly less cohesive now because it still carries dead `gold_history`.

I would remove that field in the next cleanup.

### `_render_beta_history_panel`

The state-ordering logic is good:
- `missing`
- `corrupt`
- `no_rows`
- then provenance mismatch
- then render

That ordering is right.

The main follow-up is not here, but in the sibling structural-metrics loader that still swallows artifact-read failure.

---

## Per-fix verdicts

| Fix | Verdict |
|---|---|
| #1 VERIFIED-default placeholder | `LANDED CORRECTLY` |
| #2 Detail page perf | `LANDED WITH MINOR ISSUES` |
| #3 Per-field clear controls | `LANDED WITH MINOR ISSUES` |
| #4 Remove rebased gold overlay | `LANDED WITH MINOR ISSUES` |
| #5 Structured corrupted-parquet handling | `LANDED WITH MINOR ISSUES` |
| #6 Hide Lens Score column when lens=composite | `LANDED CORRECTLY` |
| #7 Friendlier date-validation error | `LANDED CORRECTLY` |
| #8 Disable sort dropdown when non-default lens active | `LANDED WITH MINOR ISSUES` |
| #9 Server-side input length caps | `LANDED WITH MINOR ISSUES` |
| #10 Move chart panel above volatility/exploratory | `LANDED WITH MINOR ISSUES` |

## Cycle close-out verdict

**`READY WITH MINOR CHANGES`**

Why:

- None of the 10 fixes is broken.
- The major cycle problems were addressed.
- The suite is green at **217 passed**.
- The remaining issues are cleanup / tightness / consistency items, not major functional regressions.

## What I would clean up next

1. Make structural-artifact error handling consistent between:
   - `_safe_load_structural_history()`
   - `_load_published_structural_metrics()`
2. Remove dead `gold_history` from `ToolADetailState`
3. Fix the stale `_render_verification_section()` docstring
4. Add the missing tightness tests:
   - clear-wins-over-typed-value
   - exact-limit text acceptance
   - `source_url` / `note_tag` length limits
   - disabled sort attribute
5. If the stricter perf target still matters, do one more small pass on detail-page load time

Those are the next priorities. I would not reopen the deep cycle itself.
