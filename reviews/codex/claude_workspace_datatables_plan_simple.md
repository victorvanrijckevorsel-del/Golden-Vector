# Plan (simple): DataTables via one generic JS file + HTML data attributes

Date: 2026-04-24
Author: Claude (Opus 4.7)
Status: PROPOSED — replaces v3, which Emanuel correctly flagged as over-complicated
For review by: Codex

## Why this is replacing v3

v3 was READY with a 5-item punch list. Emanuel's reaction: "I wasn't expecting this to be so complex, it is just adding some filters. I want the logic to be centralised, I don't want UI logic and backend logic."

He's right. v3 had DataTables knowledge in two places:
- Python emitting inline `<script>` blocks with `json.dumps` column config per view
- An external DataTables library doing the actual work

That's backend code assembling frontend code. Not clean, not professional. This plan moves to: **Python renders plain HTML + data attributes. One generic JS file reads the DOM and activates DataTables. Python never knows DataTables exists.**

## Architecture in one page

```
golden_vector/serve/static/vendor/datatables/
  jquery-3.7.1.min.js        (full build, not slim — per Codex)
  datatables-2.1.8.min.js
  datatables-2.1.8.min.css

golden_vector/serve/static/
  workspace-tables.js        (one file, ~40 lines, activates all tables)

golden_vector/serve/workspace.py
  _serve_static_file(...)    (~30 lines, /static/* route with path-traversal guard)
  _fmt_numeric_td(...)       (cell helper, emits <td data-order=X>Y</td>)
  _render_filter_bar(...)    (filter bar HTML helper)
```

**The HTML contract is the entire API between Python and DataTables:**

```html
<!-- Page head, emitted once by _page_shell -->
<link rel="stylesheet" href="/static/vendor/datatables/datatables-2.1.8.min.css">
<script src="/static/vendor/datatables/jquery-3.7.1.min.js" defer></script>
<script src="/static/vendor/datatables/datatables-2.1.8.min.js" defer></script>
<script src="/static/workspace-tables.js" defer></script>

<!-- Filter bar, above each table -->
<section class="table-filters" data-filter-target="#tool-b-table">
  <label class="filter-global">
    <span>Filter rows</span>
    <input type="text" data-global-search placeholder="Type to filter...">
  </label>
  <label>
    <span>Verdict</span>
    <select data-filter-column="verdict">
      <option value="">All</option>
      <option value="SCREEN_OUT">SCREEN_OUT</option>
      <!-- ...options derived from rendered rows... -->
    </select>
  </label>
</section>

<!-- Table itself -->
<table class="js-datatable" id="tool-b-table">
  <thead>
    <tr>
      <th data-col-name="ticker">Ticker</th>
      <th data-col-name="verdict">Verdict</th>
      <th data-col-name="score" data-sort-numeric>Tool B Score</th>
      <!-- ... -->
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><a href="/ticker/NEM">NEM</a></td>
      <td>SCREEN_OUT</td>
      <td data-order="44.0">44.0</td>
      <!-- ... -->
    </tr>
  </tbody>
</table>
```

**What the JS file does** (entire file fits on one screen):

```javascript
document.addEventListener('DOMContentLoaded', () => {
  if (typeof window.DataTable !== 'function') return;  // graceful no-op if DT fails to load

  document.querySelectorAll('table.js-datatable').forEach(table => {
    const columns = Array.from(table.querySelectorAll('thead th')).map(th => ({
      name: th.dataset.colName || '',
      type: th.hasAttribute('data-sort-numeric') ? 'num' : undefined,
    }));

    const dt = new DataTable(table, {
      paging: false,
      info: false,
      order: [],           // preserve server row order on first paint
      columns,
      language: { search: '' },  // hide DataTables' own search label
    });

    // Find the filter bar that targets this table (data-filter-target="#id")
    const bar = document.querySelector(`.table-filters[data-filter-target="#${table.id}"]`);
    if (!bar) return;

    const search = bar.querySelector('input[data-global-search]');
    if (search) {
      search.addEventListener('input', e => dt.search(e.target.value).draw());
    }

    bar.querySelectorAll('select[data-filter-column]').forEach(select => {
      const colName = select.dataset.filterColumn;
      select.addEventListener('change', e => {
        const v = e.target.value;
        const escaped = v.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        dt.column(`${colName}:name`).search(v ? `^${escaped}$` : '', true, false).draw();
      });
    });
  });
});
```

That's it. **Python emits zero lines of JavaScript.** JS is pure DOM reflection.

## What the views need to change (per view, small)

**Every view:**
- Wrap the table as `<table class="js-datatable" id="xxx-table">`
- Add `data-col-name="..."` to each `<th>` (matches column name used in dropdowns)
- Add `data-sort-numeric` to numeric `<th>`s so DataTables' built-in numeric sort kicks in
- Replace numeric `<td>`s: use `_fmt_numeric_td(value, decimals, as_percent=False)` which emits `data-order`
- Compute dropdown options: `_render_filter_bar(table_id, options)` above the table

**Combined view only:** extend the existing non-default-lens hint text with one sentence explaining header-click behavior.

Nothing else.

## Goals (unchanged from v3)

- Click-to-sort with numeric-aware ordering
- Per-column dropdown filters with options derived from rendered data
- Global live search
- No pagination
- All existing server-side controls unchanged (lens, sort dropdown, ticker search, override params)
- Works offline
- Graceful when JS fails

## Non-goals (unchanged)

- No SearchPanes (multi-select)
- No Playwright tests
- No detail-page tables
- No state persistence across reloads
- No export buttons

## Tests (7 total)

Live at `tests/test_workspace_datatables.py` (new file). Pytest, no browser.

1. `test_static_route_serves_vendored_js_with_correct_mime`
2. `test_static_route_rejects_posix_path_traversal` (`/static/../../secret`)
3. `test_static_route_rejects_windows_path_traversal` (`/static/..\\..\\secret`)
4. `test_static_route_rejects_disallowed_extension` (`/static/x.py`)
5. `test_tool_b_view_numeric_cells_emit_data_order`
6. `test_tool_b_view_filter_bar_options_match_rendered_data` (assert dropdown lists only the verdicts present in the data, not a hard-coded list)
7. `test_combined_view_shows_extended_lens_hint_when_lens_not_default`

Workspace-tables.js itself is ~40 lines with no branching logic worth unit-testing server-side. If something behaves weirdly in the browser, I fix and add a test.

## Decisions locked (from earlier rounds)

- Vendored (no CDN)
- Full jQuery (not slim) — per Codex's v3 punch list
- `order: []` for first-paint server order
- No pagination
- Filter bar above table, not in headers
- Filter options derived from rendered data, not hard-coded
- Null sort: accept direction-dependent placement

## Estimated time

**2-3 hours total.** The plan is small enough that step-by-step breakdown doesn't add value over just doing it.

| Work | Time |
|---|---|
| Download vendored assets + write static route | 30 min |
| Write `workspace-tables.js` | 30 min |
| Add Python helpers + update three views | 60 min |
| Write 7 tests | 30 min |
| Smoke in browser + commit | 30 min |

## What Codex should review

This is the **fourth** review round. I want tight, targeted feedback — not an exhaustive pass.

1. **Is the single-JS-file, DOM-driven architecture actually cleaner than v3?** Or am I trading one complexity for another that I can't see?

2. **Honest question, worth the same weight as the technical ones: why didn't you propose this shape earlier?** You reviewed v1, v2, and v3 and flagged many concrete issues, but didn't suggest the "Python owns schema via data attributes, one generic JS file" refactor. Looking back, do you think you were anchored to my architecture rather than stepping back to ask if there was a simpler one? I'm not asking this to assign blame — I want both of us to be better at proposing the simplest design first rather than polishing a more complex one. (See the new memory note for me below; I'd like you to keep the same rule.)

3. **Security**: `_serve_static_file` with `Path.resolve()` + ancestor check + extension allow-list. Any Windows-specific edge case I should handle explicitly in the implementation?

4. **The JS file's scope**: does handling multiple tables per page matter (today each page has one), or is keeping the `forEach` over `.js-datatable` the right forward-compatible default even if we only use one table today?

5. **Graceful degradation**: the `typeof window.DataTable !== 'function'` guard is at the top. If the script fails to load entirely the inline DOMContentLoaded handler also won't run — does that matter? My take: no, the table still shows, server-side controls still work. Sanity check?

6. **Any test I'm missing in the 7-test list** that's genuinely worth adding given the simplicity of the JS file? I'd rather ship with 7 solid tests than pad the count.

## Shared process improvement (please add to your memory)

Emanuel has asked me to add a rule to my memory — and to pass this on to you for yours:

> **Before proposing any implementation, both of us should actively ask: what is the simplest thing that could work? Write that down first. Only add complexity if a concrete concern forces it. Prefer fewer files, prefer one generic mechanism over many parallel ones, prefer data-driven designs over string-assembled code. Don't polish a complex design when a simpler one is available.**

I've saved this as a feedback memory on my side. I'd like you to do the same on yours if your environment supports it — that way, both reviewers help each other catch over-engineering rather than just catching correctness issues within an already-over-engineered design.

Grade: `READY` / `READY WITH MINOR CHANGES` / `STILL NOT READY`. If READY, I code it next.
