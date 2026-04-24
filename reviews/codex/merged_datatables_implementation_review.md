# Merged Review: DataTables Implementation

Date: 2026-04-24
Sources:
- [claude_review_datatables_implementation.md](claude_review_datatables_implementation.md) — self-review
- [codex_review_datatables_implementation.md](codex_review_datatables_implementation.md) — Codex pass

Both grades: **NEEDS A FIX** (Codex) / **READY WITH MINOR CHANGES** (Claude). Codex's is stricter and correct — two P1 items that neither grade individually captures without the other viewpoint.

## Findings table

| # | Severity | Source | Finding | Fixed in this pass |
|---|---|---|---|---|
| 1 | **P1** | Codex | Combined view missing `volatility` filter dropdown | ✓ |
| 2 | **P1** | Codex | Combined filter options built from `derived_rows` (pre-filter) — violates live-derivation contract | ✓ |
| 3 | P2 | **Both** | `test_fmt_numeric_td_emits_raw_number_as_data_order` muddled with no-op `.replace()` and nonsense `as_percent=True` on 107.4 | ✓ |
| 4 | P2 | **Both** | Filter-option test weak — only asserts attribute presence, doesn't prove live-derivation | ✓ |
| 5 | P3 | Claude | Empty-state `<tr colspan=17>` row might confuse DataTables on zero-row pages | Deferred (documented decision: no real impact today) |
| 6 | P3 | Claude | No click-to-sort discoverability hint on Tool A / Tool B | Deferred (separate polish) |
| 7 | P3 | Claude | Dead `if not values: pass` block in `_render_filter_bar` | ✓ |
| 8 | P3 | Claude | `workspace-tables.js` embeds `table.id` in CSS selector string | ✓ |

## What each reviewer caught that the other missed

**Codex only (critical):**
- P1 #1 + #2. I was looking at file-level consistency ("does each view have the data attributes?") but didn't trace data flow through the Combined view. Codex traced `derived_rows → filtered_rows → filter options` and caught that the Combined filter bar wired `derived_rows` (wrong) AND omitted `volatility` entirely. These are the architectural violations — the kind of bugs review is supposed to find.

**Claude only (minor):**
- 4 P3 polish items Codex didn't flag. Three of them are real (dead code block, CSS selector fragility, colspan edge case) but none are ship-blockers.

**Both caught:**
- The muddled `_fmt_numeric_td` test and weak filter-option test. Both were obvious to both of us.

**Reviewer calibration note:** Codex went deeper into data flow; I went broader on code-level polish. Complementary but if either reviewer works alone, the P1s could be missed if only I review (I missed them) or the P3s could linger if only Codex reviews. The dual-review pattern earned its keep this round.

## Fixes applied this pass

### P1 #1 + #2 — Combined view filter bar

Code: [workspace.py](golden_vector/serve/workspace.py) `_render_overview_page`.

- Added `"volatility_context"` as a flat key on `derived_rows` (matching `profile_label`, `confidence_label`, `verdict`)
- `combined_filter_options` now built via `_collect_filter_options(filtered_rows, [...])` with all four columns (profile, confidence, volatility, verdict)
- Comment in the code explicitly contrasts this with the pre-existing `profile_values / verdict_values / confidence_values` which stay derived from `derived_rows` because they feed the server-side form (where the user needs all possible values to pick one)

Live-verified via browser: Combined view at `/` now shows 4 dropdowns with real values including `HIGH_DOWNSIDE_RISK` and `FRAGILE` / `DEFENSIVE` / `LOW_LINKAGE` — the exact labels Codex flagged as missing from hard-coded v1 lists.

### P2 #3 — rewritten numeric-td test

Replaced single muddled test with two tight ones:
- `test_fmt_numeric_td_plain_number_emits_raw_data_order`: exact equality `<td data-order="66.14">66.14</td>`
- `test_fmt_numeric_td_percent_keeps_raw_fraction_as_data_order`: exact equality `<td data-order="0.18">18.0%</td>`

### P2 #4 — strengthened filter-option tests

Three new tests prove live-derivation:
1. `test_tool_b_filter_bar_dropdown_lists_only_verdicts_present_in_data` — populates Tool B parquet with exactly one verdict (WATCHLIST + PASS), asserts dropdown has those AND explicitly NOT the other possible values (SCREEN_OUT, STRONG_CANDIDATE, FAIL, INCOMPLETE)
2. `test_combined_filter_bar_includes_volatility_dropdown` — regression guard for Codex's P1 #1
3. `test_combined_filter_bar_derives_options_from_filtered_rows_not_derived` — regression guard for Codex's P1 #2: two tickers with different verdicts, server-side filter narrows to one, asserts dropdown reflects only the narrowed set

### P3 #7 — dead `pass` block

`_render_filter_bar`: the `if not values: pass` block was a no-op. Deleted; moved the comment above the `for` loop.

### P3 #8 — CSS selector safety

`workspace-tables.js`: instead of interpolating `table.id` into a CSS attribute selector string (which would break for IDs with special chars), now iterates `.table-filters[data-filter-target]` elements and compares `dataset.filterTarget` as a plain string.

## Deferred

- **P3 #5** (empty-state colspan): no current-data impact. Revisit only if a view legitimately renders zero rows.
- **P3 #6** (click-to-sort hint on Tool A/B): separate polish item, one line of copy, not in scope for this debug pass.

## Verification

- Full pytest suite: **282 passed** (was 278 pre-fix, +4 new tests)
- Live smoke on `/`: 4 dropdowns, 5 profile values, 3 confidence values, 4 volatility values, 3 verdict values — all from rendered data
- Live smoke on `/tool-a` and `/tool-b`: unchanged

## Cycle status

Ready to ship. Both P1 findings resolved, both P2s resolved, two cheap P3s resolved, two P3s deliberately deferred with rationale. If Codex wants a third pass to confirm, happy to run it; otherwise merge to main.
