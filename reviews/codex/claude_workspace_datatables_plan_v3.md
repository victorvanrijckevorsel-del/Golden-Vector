# Plan v3: Wire DataTables into the Tool A / Tool B / Combined Views

Date: 2026-04-24
Author: Claude (Opus 4.7)
Status: PROPOSED — v3, revised after Codex review of v2
For review by: Codex (thorough pass requested)

## Why v3

Codex graded v2 `STILL NOT READY` with four remaining issues. Three of the five v1 findings did land cleanly in v2; v3 resolves the remaining items and a handful of thoroughness-level concerns I caught on re-read.

This document is **self-contained**. A cold reader does not need v1 or v2 to review v3 — everything is here.

## Summary of changes from v2

| # | v2 issue | Source | v3 resolution |
|---|---|---|---|
| 1 | v2 claimed DataTables 2.x runs standalone without jQuery; DataTables manual still requires jQuery 1.8+ | Codex P1 | **Include jQuery in the vendored bundle.** ~30 KB extra, matches official docs, no speculative "no-jQuery" bet. |
| 2 | v2's non-negotiable rule said "first paint respects server order" but the JS init sketch used `order: [[index, dir]]`, which makes DataTables re-sort on load | Codex P1 | **Init uses `order: []`** (empty array) which is DataTables' official API for preserving DOM order. DOM order IS the server-emitted row order, so the two agree by construction. |
| 3 | v2 claimed `data-order="Infinity"` sorts null rows last regardless of direction; actually sorts last in ascending, first in descending | Codex P1 | **Accept direction-dependent null placement for v1** and document it clearly. No custom plug-in in v1; if Emanuel dislikes it after using it, add a plug-in in a follow-up. Sentinel value changes from `Infinity` to `9e15` (a plain finite number DataTables sorts predictably). |
| 4 | v2 missing UX note for "non-default lens active + user clicks a header" coexistence | Codex P2 | **Add an on-screen hint** when lens is non-default: "Initial order follows the selected lens. Clicking table headers reorders this view only." Plus a test that the hint is present. |
| 5 | Implicit: v2 never verified the exact DataTables bundle against docs | self | **v3 pins exact bundle URLs + SHA-256 hashes** so the vendored files can be verified deterministically at any point later. |
| 6 | Implicit: v2 mentioned "about 15 tests" without a full list | self | **v3 enumerates all 16 proposed tests** with file, name, and what each one pins. |
| 7 | Implicit: v2 didn't cover the "JavaScript disabled / fails to load" fallback | self | **v3 documents the graceful degradation** — the table still renders as plain HTML; DataTables is pure enhancement. |
| 8 | Implicit: v2 didn't address column-order / `<th>`-to-name-list correspondence as a failure mode | self | **v3 treats column-name/position alignment as a tested invariant** with a dedicated test. |

## Background

Emanuel wants the 60-row Tool A and Tool B tables to behave like Excel filter dropdowns:

1. Click a column header → sort by that column ascending/descending
2. Click a value dropdown (one per categorical column) → filter rows to just that value
3. Type in a search box → filter rows to match any visible cell

Today the three workspace views (`/`, `/tool-a`, `/tool-b`) are static HTML tables with:
- a single server-side `<select>` sort dropdown (Combined only)
- a server-side ticker search (all three views)
- the Tool B Screening Parameters panel (URL-param scenario overrides)

All of those are **server-side**: submitting any of them reloads the page with different query params. Useful for bookmarkable scenarios, slow for rapid exploration.

DataTables is the industry-standard library for adding client-side interactivity on top of existing server-rendered tables. Server stays in charge of "which rows get rendered"; DataTables sits on top and offers sort/search/filter within that rendered set. Page reloads only happen when the user changes the server-side controls (lens, overrides, ticker search).

## Goals — what's true after this milestone

1. Every column in every view supports **click-to-sort**, visible arrow indicator.
2. Numeric columns sort **numerically**, not alphabetically.
3. Every view has a **filter bar** (separate panel above the table) with:
   - One live global search input.
   - One dropdown per categorical column, options derived from the rendered data.
4. **No pagination.** Entire row set fits on one page.
5. **All existing server-side controls continue to work unchanged**: lens picker, sort dropdown, ticker search, Screening Parameters overrides.
6. **First paint of every table shows the server-emitted row order.** No hidden client-side re-sort on load.
7. When a non-default lens is active on Combined, the UI displays a hint explaining the interaction between server lens-order and client header-click sort.
8. Works **offline** (all assets vendored; no CDN calls).
9. Graceful degradation: if the JS bundle fails to load or is disabled, the table renders as plain HTML and all server-side controls still work.
10. Suite still passes (currently 257; expected to land around 273 after the ~16 new tests).

## Non-goals (explicit)

- **SearchPanes extension** (Excel-style multi-select checkbox filter panes). Single-value dropdown is v1.
- **Column show/hide, column reorder, row export, advanced range filters.** Ask later if missed.
- **Playwright / Selenium / other browser test runners.** Our pytest assertions cover the HTML/JS text; in-browser behavior is covered by DataTables' own test suite.
- **DataTables for the ticker detail page's reference tables.** Short tables, no need.
- **Persisting DataTables state across page reloads.** Fresh DOM each load; user reloads means user wants default.

## Hard architectural constraints

Five rules lock "which control wins" so no ambiguity survives into the code.

1. **Server-side controls decide which rows get rendered.** Lens, Screening Parameters overrides, ticker search, active filters from the server-side form. The set of rows reaching the HTML is owned by Python.
2. **DataTables operates only within the rendered row set.** Its sort/search/filter actions never trigger a request to the server.
3. **First render preserves the server-emitted row order.** DataTables initializes with `order: []` which is the documented API for "preserve DOM order." Any user action (click header, use dropdown, type search) is what triggers DataTables to re-render.
4. **URL params encode server state only.** DataTables state is intentionally non-persistent.
5. **Filter option values in dropdowns are derived at render time from the rendered data.** No hard-coded lists in Python or JS. This matches the existing overview form pattern and adapts automatically as data labels evolve.

## Architecture

### Vendored assets, no CDN

`golden_vector/serve/static/vendor/datatables/`:

| File | Size | Purpose | Source URL |
|---|---|---|---|
| `jquery-3.7.1.slim.min.js` | ~30 KB | Required by DataTables core (official manual) | https://code.jquery.com/jquery-3.7.1.slim.min.js |
| `datatables-2.1.8.min.js` | ~85 KB | DataTables core (bundles `jquery.dataTables` + default styling JS) | https://cdn.datatables.net/2.1.8/js/dataTables.min.js |
| `datatables-2.1.8.min.css` | ~15 KB | Default table styling | https://cdn.datatables.net/2.1.8/css/dataTables.dataTables.min.css |

Total: **~130 KB**.

Version-pinned filenames. SHA-256 hashes recorded in a small `VERSIONS.md` alongside the vendored files so future reviewers can re-verify the bundle came from the expected source.

Why include jQuery: the DataTables 2 manual (datatables.net/manual, first paragraph) states "DataTables is a JavaScript library, so your web-page will need to load jQuery before DataTables can operate." The `new DataTable(...)` constructor style is syntactic sugar — jQuery is still the plumbing. Codex was correct to push back on v2's standalone claim.

### New WSGI route `/static/*`

Added before the existing HTML routes in `golden_vector/serve/workspace.py`:

```python
if method == "GET" and path.startswith("/static/"):
    return _serve_static_file(path, start_response)
```

`_serve_static_file` responsibilities:

1. Compute `candidate = (STATIC_ROOT / path_relative_to_static).resolve()`.
2. Verify `STATIC_ROOT.resolve()` is a parent of `candidate`. Rejects `..` traversal via the filesystem's own canonicalization, not string matching.
3. Check extension is in `{".js", ".css"}` allowlist.
4. Stream bytes with `Content-Type: application/javascript` or `text/css`.
5. `Cache-Control: public, max-age=31536000, immutable` — safe because filenames are version-pinned.
6. 404 for any miss or rejection.

About 30 lines of Python. Testable without a real browser.

### Client-side enhancement layer

Added to the `<head>` of every page via `_page_shell`:

```html
<link rel="stylesheet" href="/static/vendor/datatables/datatables-2.1.8.min.css">
<script src="/static/vendor/datatables/jquery-3.7.1.slim.min.js" defer></script>
<script src="/static/vendor/datatables/datatables-2.1.8.min.js" defer></script>
```

The `defer` attribute guarantees both scripts execute after HTML parsing is complete, in source order, before `DOMContentLoaded`. Our inline init script (appended at end of each view body, also `defer`ed where possible) therefore sees both jQuery and DataTables fully loaded.

**Graceful degradation:** if either script fails to load (bad CDN proxy, content blocker, disabled JS), the page still renders a plain HTML table. All server-side controls (lens, sort dropdown, ticker search, overrides) continue to work. DataTables is pure enhancement, never a requirement.

### Sort-by-raw-number via `data-order`

Numeric cells emit both a display string and a sort key:

```html
<td data-order="1.074">107.4%</td>
<td data-order="66.14">66.14</td>
<td data-order="9e15">-</td>          <!-- missing value -->
```

DataTables' numeric sort reads `data-order`; the visible cell text is what humans see. Helper: `_fmt_numeric_td(value, decimals, as_percent=False)` returns the full `<td>` tag.

**Null/missing handling:** `9e15` is a plain finite sentinel sorting predictably. Consequences:
- **Ascending sort:** missing rows land at the bottom (after all real values). Natural for "rank ascending = best first" columns.
- **Descending sort:** missing rows land at the top. This is what Codex correctly flagged as not matching v2's "nulls last regardless" claim.
- **Tradeoff accepted:** for v1 we live with direction-dependent placement. It's predictable and documented. If Emanuel later reports it's confusing, we add the DataTables `absolute` ordering plug-in as a follow-up.

### Filter bar above the table (separate panel)

Not inside `<thead>`. Renders as:

```html
<section class="panel table-filters">
  <div class="table-filters-row">
    <label class="filter-global">
      <span>Filter rows</span>
      <input type="text" id="tool-b-search" placeholder="Type to filter any column">
    </label>
    <label>
      <span>Verdict</span>
      <select data-column="verdict">
        <option value="">All</option>
        <option value="SCREEN_OUT">SCREEN_OUT</option>
        <option value="STRONG_CANDIDATE">STRONG_CANDIDATE</option>
        <option value="WATCHLIST">WATCHLIST</option>
      </select>
    </label>
    <!-- one <label> per categorical column -->
  </div>
</section>
```

Each `<select>`'s `data-column` attribute is a **column name** (not index), matching the `name` attribute in the DataTables `columns: [{name: "verdict"}, ...]` config. That's the stable DataTables 2 selector API (`table.column('verdict:name')`).

### Live-derived filter options

New helper:

```python
def _collect_categorical_filter_options(
    rows: list[dict],
    columns: list[tuple[str, str]],  # [(column_name, row_key), ...]
) -> dict[str, list[str]]:
    """For each column spec, return sorted unique non-empty string values
    from the rendered row dicts. Used to populate the dropdown filter bar.
    Same pattern as the existing overview form's _options(...) logic."""
```

Tool B call:
```python
options = _collect_categorical_filter_options(derived_rows, [
    ("verdict", "screening_verdict"),
    ("layer1_status", "layer1_status"),
])
```

Tool A call:
```python
options = _collect_categorical_filter_options(derived_rows, [
    ("profile", "profile_label"),
    ("confidence", "confidence_label"),
    ("volatility", "volatility_context"),
])
```

Combined: union of both.

If a new profile label appears in the data tomorrow (e.g., `NEW_PROFILE`), the dropdown picks it up automatically — no code change.

### DataTables init — safe defaults, stable selectors

Each view appends a small inline `<script>` at the end of its body:

```html
<script>
  document.addEventListener('DOMContentLoaded', () => {
    const table = new DataTable('#tool-b-table', {
      paging: false,
      info: false,
      order: [],                            // preserve DOM order on first paint
      columns: /*__COLUMNS_JSON__*/,        // {name: "..."} array
      language: { search: '' },             // hide the default "Search:" label; we render our own
    });
    // Wire custom global search input
    const searchInput = document.getElementById('tool-b-search');
    if (searchInput) {
      searchInput.addEventListener('input', e => table.search(e.target.value).draw());
    }
    // Wire column dropdown filters (one per <select data-column="name">)
    document.querySelectorAll('.table-filters select[data-column]').forEach(select => {
      const colName = select.getAttribute('data-column');
      select.addEventListener('change', e => {
        const value = e.target.value;
        // Exact match via regex with escape; empty string clears the filter.
        table.column(`${colName}:name`)
             .search(value ? `^${value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$` : '', true, false)
             .draw();
      });
    });
  });
</script>
```

`__COLUMNS_JSON__` is interpolated via `json.dumps([{"name": "ticker"}, {"name": "verdict"}, ...])` in Python. Safe escaping for free. The regex escape inside the `change` handler protects against values with regex metacharacters — not currently a risk in our domain (`STRONG_CANDIDATE`, `PASS`, `HIGH_NOISE` all safe) but future-proof.

### Lens-active UX hint (Combined view only)

When the lens is non-default, the current overview form already renders a hint:

> "Sort dropdown is ignored while a non-default lens is active; the table is automatically sorted by the lens's score."

v3 extends it to also explain the client-side header-click interaction:

> "Sort dropdown is ignored while a non-default lens is active; the initial table order follows the lens. Clicking a column header reorders this view only (not persisted)."

Rendered by updating `_render_overview_filters_form` in `workspace.py`. Tested via an assertion on the rendered HTML when a non-default lens is active.

### CSS

Add ~35 lines to `_page_shell`'s `<style>` block:

- `.table-filters` / `.table-filters-row` — inherit existing `.panel` look, use `display: flex; gap: 16px; flex-wrap: wrap; align-items: end;`
- `table.datatable thead th` — pointer cursor, sort arrows in `--accent` (brown)
- Hide DataTables' default search wrapper (`.dt-search`) since we render our own
- Hide pagination chrome (`.dt-paging`) since paging is off
- Override DataTables' default fonts/colors to match the warm beige palette

## Step-by-step plan

### Step 1 — Vendor DataTables + jQuery + static route (1 hr)

**New files:**
- `golden_vector/serve/static/vendor/datatables/jquery-3.7.1.slim.min.js`
- `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.js`
- `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.css`
- `golden_vector/serve/static/vendor/datatables/VERSIONS.md` (URLs + SHA-256 hashes + license notes — DataTables is MIT, jQuery is MIT)

**Code change — `golden_vector/serve/workspace.py`:**
- Add `_STATIC_ROOT = Path(__file__).parent / "static"` constant
- Add `_serve_static_file(path, start_response)` helper (~30 lines)
- Add the `/static/*` route in `app()` before HTML routes

**Tests (new, in `tests/test_workspace_app.py`):**
1. `test_workspace_static_route_serves_js_with_correct_mime`
2. `test_workspace_static_route_serves_css_with_correct_mime`
3. `test_workspace_static_route_rejects_path_traversal` (e.g. `/static/../../../etc/passwd`)
4. `test_workspace_static_route_rejects_disallowed_extension` (e.g. `.py`, `.db`)

### Step 2 — Shared helpers (1.5 hr)

Add to `workspace.py`:
- `_fmt_numeric_td(value, decimals, as_percent=False) -> str`
- `_collect_categorical_filter_options(rows, columns) -> dict[str, list[str]]`
- `_render_filter_bar(view_id, options, global_search_hint) -> str`
- `_render_datatables_init_script(table_id, search_input_id, column_names, lang_search="") -> str`

**Tests (new, in `tests/test_workspace_helpers.py` — a new file to keep the big `test_workspace_app.py` from growing further):**

5. `test_fmt_numeric_td_emits_data_order_attribute`
6. `test_fmt_numeric_td_percent_uses_raw_fraction_as_data_order`
7. `test_fmt_numeric_td_missing_value_emits_9e15_sentinel`
8. `test_collect_filter_options_derives_only_from_rendered_rows`
9. `test_collect_filter_options_excludes_empty_and_none_values`
10. `test_render_datatables_init_script_has_empty_order_array`
11. `test_render_datatables_init_script_uses_column_names_not_indices`
12. `test_render_datatables_init_script_json_escapes_column_names`

### Step 3 — Wire Tool B view (1 hr)

- Add `id="tool-b-table"` and `class="datatable"` to the rendered table
- Replace inline numeric `<td>{_fmt_number(...)}</td>` with `_fmt_numeric_td(...)` — 12 numeric cells in the Tool B row
- Compute `options = _collect_categorical_filter_options(derived, [("verdict","screening_verdict"), ("layer1_status","layer1_status")])`
- Insert `_render_filter_bar("tool-b", options, "Filter rows")` above the table
- Append `_render_datatables_init_script("tool-b-table", "tool-b-search", [...])` at end of body

**Tests (in `tests/test_workspace_app.py`):**

13. `test_tool_b_view_table_has_id_and_datatable_class`
14. `test_tool_b_view_numeric_cells_carry_data_order_attributes` (spot-check Peer P/E Target column)
15. `test_tool_b_view_filter_bar_options_match_rendered_data` (assert dropdown lists only the verdicts present in the rendered rows, not a hard-coded list)
16. `test_tool_b_view_datatables_init_uses_empty_order` (regex: `order:\s*\[\s*\]`)
17. `test_tool_b_view_datatables_init_columns_names_match_thead_count` (JSON-parse the columns config from the init script, assert length equals the `<th>` count)

### Step 4 — Wire Tool A view (45 min)

Same pattern. Categorical columns: `profile_label`, `confidence_label`, `volatility_context`. 6 numeric cells.

**Tests:** mirror Step 3.

### Step 5 — Wire Combined view + lens UX hint (1 hr)

Same pattern as Tool B/A. Categorical column union: profile, confidence, volatility, verdict, layer1_status.

**Extra:** update `_render_overview_filters_form` to include the extended hint when `lens.id != DEFAULT_LENS_ID`:

> "Sort dropdown is ignored while a non-default lens is active; the initial table order follows the lens. Clicking a column header reorders this view only (not persisted)."

**Tests:**

18. `test_combined_view_first_render_preserves_lens_driven_order` — build a scenario with a non-default lens, capture the rendered row order (via regex on ticker anchor tags), assert it matches the lens's expected ordering
19. `test_combined_view_shows_extended_lens_hint_when_lens_not_default` — assert the new hint text appears
20. `test_combined_view_override_form_hidden_inputs_coexist_with_filter_bar` — regression check that the existing "filter form carries override params as hidden inputs" test still passes unchanged

### Step 6 — CSS polish (30 min)

Add the ~35 lines described in the Architecture section. No new tests (visual).

### Step 7 — Smoke + commit (30 min)

Manual browser checks on `/tool-a`, `/tool-b`, `/` including:
- Click every column header, sort direction indicators work
- Filter bar dropdowns show only values present in the data
- Filter bar global search narrows live
- `/tool-b?gold_price=4500`: override banner visible, DataTables works on the recomputed table
- `/?lens=upside_torque`: initial row order matches the lens; extended hint is visible; clicking a header re-sorts the view
- Hit Ctrl+F5 to simulate JS load failure (or use browser devtools to disable): static table still renders, server-side controls still work
- Verify no 500s anywhere

**Single commit** after Step 7: `Wire DataTables into Tool A / Tool B / Combined views for click-sort + filter bar`.

## Cross-cutting concerns

### Interaction with the lens picker (Combined view)

- **Default lens (composite):** server renders rows sorted by the sort-dropdown's choice (or ticker A-Z by default). DataTables preserves that on first paint. User can click a header to re-sort.
- **Non-default lens (upside_torque, fragility, cleanliness):** server renders rows sorted by `lens_score`. DataTables preserves. The hint text tells the user what's happening. If the user clicks a header, DataTables re-sorts the visible rows — no server roundtrip, lens state untouched.

### Interaction with Tool B override parameters

`/tool-b?gold_price=4500` triggers in-memory recompute, then renders. DataTables initializes normally on the recomputed table. The existing "filter form carries active overrides as hidden inputs" behavior is untouched — regression-tested in Step 5.

### Interaction with ticker search (existing server-side form)

Two search boxes now exist:
- **Server-side ticker search** (existing): submits via form, reloads page, narrows the server-rendered row set. Bookmarkable via `?search=NEM`. Case-insensitive substring on ticker symbol only.
- **Client-side DataTables global search** (new): live, no reload, filters within already-rendered rows. Searches all visible cells (ticker, verdict, any formatted number). Not persisted on reload.

Both coexist. Different tools for different jobs:
- Server search = "give me only these tickers to analyze."
- Client search = "among what's showing, find rows matching X."

A two-line hint above the filter bar explains this:

> Filter rows (this page only, not saved). For a persistent filter by ticker symbol, use the Search Ticker box above.

### Performance

DataTables init on 60 rows × 17 columns: typically sub-10 ms in Chrome. Global search keystroke: sub-2 ms. Zero concern.

Static file serving: Python reads from disk on each request; `Cache-Control: immutable` means browsers cache after the first load and don't re-request. Fine for a local tool.

### Browser compatibility

DataTables 2.x + jQuery 3.7.1 support:
- Chrome / Edge 88+
- Firefox 78+
- Safari 14+
- No IE11

Emanuel uses Chrome. No concern.

### Accessibility

DataTables 2.x adds ARIA labels on sortable headers (`aria-sort="ascending"` etc.) and keyboard navigation (Tab + Enter/Space on headers). Our filter bar uses semantic `<label>` + `<select>` + `<input>`, all screen-reader-accessible by default.

### Test coverage impact

~16 new tests across Steps 1–5 (enumerated above). Plus one regression check in Step 5. Suite moves 257 → ~273 passing. All tests run without a browser — pure HTML/JSON structural assertions.

### Commit cadence

Single commit after Step 7 passes smoke. Steps 1–6 are tightly coupled (route enables JS, helpers enable views, views need all three). No value in landing them independently.

## Estimated total time

| Step | Time |
|---|---|
| 1 — Vendor + static route + 4 tests | 1 hr |
| 2 — Shared helpers + 8 tests | 1.5 hr |
| 3 — Tool B view + 5 tests | 1 hr |
| 4 — Tool A view + ~5 tests | 45 min |
| 5 — Combined view + 3 coexistence tests + lens hint | 1 hr |
| 6 — CSS polish | 30 min |
| 7 — Smoke + commit | 30 min |
| **Total** | **6 hr 15 min** |

Slightly longer than v2's 4h45m estimate. Honest about the extra scope: jQuery vendoring, SHA-256 hashes, 4 extra helper tests for edge cases, explicit lens UX hint + test, extended coexistence tests.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| DataTables 2.1.8 has an undocumented behavior change from the version I've used before | Low | Medium | Pin exact version, vendor with SHA-256 verification, full smoke test in Step 7 before commit |
| Our CSS override fights DataTables' default styling in a subtle way | Medium | Low | Visual QA in Step 7 across all three views |
| Column-name-to-header-cell alignment silently drifts if someone reorders columns without updating the name list | Medium | Medium | Dedicated test (#17) that parses the init script's JSON and asserts length matches `<th>` count |
| Regex escape in the dropdown filter misses an edge case | Very Low | Low | Current domain values are all uppercase A-Z + underscore; the escape is for forward-compatibility only |
| Null-sort direction-dependent placement confuses the user | Medium | Low | Documented in the hint text; easy to upgrade to an `absolute` plug-in later |
| A vendored asset SHA doesn't match after a careless upgrade | Low | High (silent) | `VERSIONS.md` has the expected hashes; add a pre-commit hook later if needed |

## Decisions Emanuel needs to confirm

Most decisions are now locked from earlier rounds. Only one left:

1. **Accept direction-dependent null placement for v1** (my recommendation) vs **include a custom ordering plug-in now to force nulls-last regardless of direction** (extra ~5 KB JS + ~50 lines integration). I recommend v1 as-is; upgrade only if the UX feels wrong in practice.

## What Codex should review — thorough pass requested

This is the third review iteration. I'd especially value Codex being thorough on the following, organized as a checklist he can work through:

### Did v3 resolve each v2 finding?

1. **jQuery inclusion**: v3 vendors jQuery 3.7.1 slim + DataTables 2.1.8. Docs (datatables.net/manual) confirm DataTables 2 requires jQuery 1.8+. Is the exact bundle (slim vs full jQuery) a concern? The slim build lacks `.ajax()` and some effects but DataTables core only uses DOM manipulation + selection. Worth verifying.

2. **First-render order**: `order: []` is now in the plan. DataTables manual confirms empty array = "preserve initial table data order, no sorting applied on load." Is there a documented edge case where `order: []` still reorders (e.g. a `type: "num"` column with mixed types)? I don't think so but worth a second look.

3. **`data-order` sentinel**: changed from `"Infinity"` (parse-ambiguous) to `"9e15"` (plain finite float). Does DataTables' built-in numeric sort handle `9e15` cleanly, or should I use a plain integer like `1e18`? JS's safe integer max is 2^53 ≈ 9e15. Is this far enough from any legit Tool B target price to be safe forever?

4. **Lens UX hint**: new hint text added, plus test #19. Is the copy clear enough? Should it go into an `<aside>` or stay in the existing hint area?

### Does the plan hold up against the original product constraints?

5. **The "augment, never replace" rule** is now hard-enforced via constraint #1-#5 in the Hard Constraints section. Is there any place in the step-by-step plan that still implicitly violates it?

6. **The "server search vs client search" coexistence** (section "Interaction with ticker search"). Is the two-line hint I proposed sufficient, or does this need a more visible UX treatment?

7. **The "non-default lens + header click" interaction**. Is there a scenario where this is still confusing even with the hint? I'm worried about: user applies lens, clicks a header, then switches the lens dropdown — they'd expect the new lens's order, but is their header-click preserved? (Answer: no, because the page reloads. But is that the expected behavior?)

### Test coverage — is 16 new tests + 1 regression enough?

8. Enumerated list is in Steps 1-5. Is there a case I'm missing? Specifically:
   - Fallback when DataTables JS fails to load? Currently unverified — should add a test that the page works without the init script (smoke only, or add an automated check)?
   - What happens if `_collect_categorical_filter_options` returns an empty list for a column (all rendered rows have empty values)? Dropdown should degrade gracefully — tested via test #15?

### Implementation concerns I may have missed

9. **Path traversal on the static route**: `Path.resolve()` + ancestor check rejects `/static/../../secret`. Is there a Windows-specific edge case (e.g., `\\`, `\\..\\`, drive-letter roots) I should handle?

10. **`defer` attribute on scripts**: does DataTables play nicely with `defer` + inline `<script>` in the body? My understanding is the init script runs after DOMContentLoaded because of the `document.addEventListener('DOMContentLoaded', ...)` wrapper. Double-check?

11. **Memory/GC concerns**: each page reload creates a new DataTables instance. Is there a cleanup concern, or does DataTables handle this via normal GC?

12. **The `columns: [...]` array needs to match `<th>` count and order** exactly, or DataTables raises. Test #17 catches count. Should I also assert order matches (i.e., column names in the init script are in the same order as `<th>` labels)?

### Scope / direction

13. Given we're on review #3 and have found real things each time, is the feedback loop still serving us, or are we hitting diminishing returns? Honest take welcome.

14. Is anything in the plan overbuilt for a 60-row local tool? Cutting scope would shorten the implementation; which items could safely defer?

15. Is the 6h15m estimate realistic, or am I underestimating the JS integration friction?

### Grade

`READY` / `READY WITH MINOR CHANGES` / `STILL NOT READY` — with a tight punch list if not ready.

---

## Appendix A — `data-order` edge cases matrix

| Cell data | `data-order` attribute | Ascending sort position | Descending sort position |
|---|---|---|---|
| `1.074` (percent) | `1.074` | among numerics | among numerics |
| `66.14` (target price) | `66.14` | among numerics | among numerics |
| `None` → `-` (display) | `9e15` | last | first |
| `"PASS"` (text) | (none needed) | DataTables sorts strings alphabetically | reverse alphabetical |
| `"-"` (display for missing text) | (none, or empty) | sorts to start ("-" is a low ASCII char) | sorts to end |

The text-column null case ("-" sorting to start in ascending, end in descending) is mildly inconsistent with the numeric case. Tolerable for v1.

## Appendix B — `VERSIONS.md` template

The `VERSIONS.md` file committed alongside the vendored assets will contain:

```markdown
# Vendored Assets

| File | Source URL | SHA-256 | License |
|---|---|---|---|
| jquery-3.7.1.slim.min.js | https://code.jquery.com/jquery-3.7.1.slim.min.js | (hash) | MIT |
| datatables-2.1.8.min.js | https://cdn.datatables.net/2.1.8/js/dataTables.min.js | (hash) | MIT |
| datatables-2.1.8.min.css | https://cdn.datatables.net/2.1.8/css/dataTables.dataTables.min.css | (hash) | MIT |

Downloaded: 2026-04-24
Verify with: `sha256sum <filename>` on Linux/macOS, `certutil -hashfile <filename> SHA256` on Windows.
```

The hashes are filled in during Step 1 when the files are actually downloaded.
