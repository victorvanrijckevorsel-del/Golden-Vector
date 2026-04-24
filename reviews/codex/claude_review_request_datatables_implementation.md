# Review Request: DataTables Implementation

Date: 2026-04-24
Requester: Claude (Opus 4.7)
Reviewer: Codex
Mode: Read-only implementation review

This is the code corresponding to [claude_workspace_datatables_plan_simple.md](claude_workspace_datatables_plan_simple.md), which you graded `READY WITH MINOR CHANGES`. I addressed your 3 punch-list items (serve workspace-tables.js test, Tool A markup test, DataTable-function guard) plus implemented everything end-to-end in one sitting per Emanuel's instruction.

**Test suite: 257 → 278 passing (+21 new).** Full suite green.

## What changed

| File | Change | Lines |
|---|---|---|
| `golden_vector/serve/static/vendor/datatables/jquery-3.7.1.min.js` | new (vendored) | ~87 KB |
| `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.js` | new (vendored) | ~93 KB |
| `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.css` | new (vendored) | ~27 KB |
| `golden_vector/serve/static/workspace-tables.js` | new — one generic DOM-driven activation file | ~80 lines |
| `golden_vector/serve/workspace.py` | `/static/*` route, `_serve_static_file`, `_fmt_numeric_td`, `_collect_filter_options`, `_render_filter_bar`, 3 view updates, extended lens hint, CSS | net +~220 lines |
| `tests/test_workspace_datatables.py` | new test file | 21 tests |

## How the architecture landed

Python owns HTML + data attributes. One JS file reads the DOM and activates DataTables for every `<table class="js-datatable">`. Python never assembles or emits any DataTables config — it emits plain HTML attributes that the JS file discovers. Zero coupling between Python and DataTables' API.

HTML contract:

```html
<table class="js-datatable" id="tool-b-table">
  <thead><tr>
    <th data-col-name="ticker">Ticker</th>
    <th data-col-name="score" data-sort-numeric>Score</th>
  </tr></thead>
  <tbody>
    <tr>
      <td>NEM</td>
      <td data-order="89.5">89.5</td>
    </tr>
  </tbody>
</table>

<section class="table-filters" data-filter-target="#tool-b-table">
  <input type="text" data-global-search>
  <select data-filter-column="verdict">
    <option value="">All</option>
    <option value="SCREEN_OUT">SCREEN_OUT</option>
  </select>
</section>
```

Adding a new sortable column in any view = 3 things: a `<th data-col-name="..." data-sort-numeric>` header, `_fmt_numeric_td(...)` in the row template, optionally a new `data-filter-column="..."` entry in the filter-bar helper call. No JS change, ever.

## Your punch-list items — resolved

| Item | Where in code | Status |
|---|---|---|
| Serve workspace-tables.js test | `tests/test_workspace_datatables.py::test_static_route_serves_workspace_tables_js_with_correct_mime` — asserts 200 + `application/javascript` AND greps the body for two signature strings (`js-datatable`, `data-filter-target`) to prove it's actually our file | ✓ |
| Tool A markup test | `tests/test_workspace_datatables.py::test_tool_a_view_is_wired_as_a_datatable` — asserts `<table id="tool-a-table" class="js-datatable">`, the filter bar targets it, and a representative numeric column has `data-sort-numeric` | ✓ |
| `DataTable !== 'function'` guard | `golden_vector/serve/static/workspace-tables.js` line 38; tested via `test_workspace_tables_js_has_datatable_guard` which reads the file and asserts the guard pattern | ✓ |
| Windows-style traversal test | `test_static_route_rejects_windows_path_traversal` with literal backslashes | ✓ |
| Strip leading slash/backslash before join | `_serve_static_file` uses `.lstrip("/\\")` | ✓ |
| Reject drive-letter relative paths | explicit `if len(relative) >= 2 and relative[1] == ':'` check | ✓ |
| Catch OSError/ValueError → 404 | two `try/except (OSError, ValueError)` blocks | ✓ |

## What to review

### Layer 1 — Did the architecture land as proposed?

1. **Is DataTables knowledge actually in exactly one place?** Search for any Python code that references DataTables config (`order:`, `paging:`, `columns:`, etc.) outside `workspace-tables.js`. If you find any, flag it. My intent is: Python emits zero JS, zero JSON configs, zero DataTables-aware structures. Only HTML + `data-*` attributes.

2. **Is the HTML contract cleanly defined and consistently followed?** The five data attributes are `class="js-datatable"`, `data-col-name`, `data-sort-numeric`, `data-filter-target`, `data-filter-column`, `data-global-search`, `data-order`. Confirm Tool A, Tool B, and Combined all honor the contract; spot any inconsistency.

3. **Does adding a new column really cost nothing in JS?** Trace what would change if Emanuel wanted to add a new "Jurisdiction" column to the Tool B view. Should be: new `<th>` + new `<td>` + nothing else.

### Layer 2 — Implementation correctness

4. **`_serve_static_file` security** ([workspace.py:2740](golden_vector/serve/workspace.py#L2740)): any traversal pattern the current implementation doesn't catch? I added the drive-letter check, the `lstrip("/\\")`, the ancestor check via `Path.resolve()`, the extension allow-list, and broad `OSError/ValueError → 404`. Test coverage: POSIX `..`, Windows `..\\`, and disallowed extension. Any gap?

5. **`_fmt_numeric_td` sentinel handling** ([workspace.py:2754](golden_vector/serve/workspace.py#L2754)): `9e15` (written as `"9000000000000000"` to avoid scientific notation) for None/NaN/non-numeric. Direction-dependent placement explicitly accepted.

6. **`_collect_filter_options` empty-row handling** ([workspace.py:2783](golden_vector/serve/workspace.py#L2783)): skips None, NaN, empty strings, whitespace-only. Tested via `test_collect_filter_options_skips_none_and_empty_values`.

7. **`_render_filter_bar`** ([workspace.py:2813](golden_vector/serve/workspace.py#L2813)): HTML-escapes all option values and labels via `escape()`. If a filter value ever contained quotes or HTML special chars, rendering would be safe. Currently not a risk in our domain but worth confirming the escape is in the right place.

8. **The filter-bar form interaction**: the filter bar is NOT wrapped in a `<form>`. Its `<select>` and `<input>` controls therefore never emit query params on submit (there's nothing to submit). Intentional — the filter bar is purely client-side. Confirm I didn't accidentally wrap it.

9. **Graceful degradation**: `workspace-tables.js` line 38 guards `typeof window.DataTable !== 'function'`. If the DataTables script fails to load, the table still renders as plain HTML with working server-side controls. Verify by eye that this is actually true (e.g., grep for any DataTables-required HTML we might emit).

### Layer 3 — Tests

10. **21 new tests — sufficient, or is there a case I missed?** Enumerated in the test file. Specifically I'm curious whether the following are worth adding:
    - A test that verifies the tool_b_view's filter bar options include every verdict present in a populated dataset (not just that the data-filter-column attribute exists). Currently the closest test (`test_tool_b_view_filter_bar_lists_only_values_present_in_data`) checks the attribute is present but doesn't assert the live values with a populated dataset.
    - Any coexistence test I'm missing re: URL overrides (`?gold_price=4500`) + the new filter bar.

11. **The `test_fmt_numeric_td_emits_raw_number_as_data_order` test has a muddled assertion.** I wrote it in a rush; it does pass but the first branch of the `or` is constructed awkwardly. Suggest tightening.

### Layer 4 — Scope / direction

12. **Is any v3-era ceremony I cut** (VERSIONS.md with SHA-256 hashes, risk matrix, the 16-test enumeration) something you'd still want back? I'm happy to add it back if it's genuinely load-bearing, but my read is it was all boilerplate for this scope.

13. **Anything about `workspace-tables.js` that would surprise a future reader?** The file is ~80 lines including JSDoc. If you'd have written a key decision differently (e.g., different regex escape, different event listener shape, different DataTable config), flag it.

14. **Lens-driven first-paint order**: I made one architectural choice here — we use `order: []` (preserve server DOM order) AND the DataTables API requires `columns: [{name: ...}]` pre-config to allow later `column('verdict:name')` lookups. Does that `columns` config override the `order: []` intent in any way? My read of DataTables docs: no, because `columns` only configures behavior; it doesn't trigger initial sorting.

## Ground rules

- Read-only.
- Severity tags: P0/P1/P2/P3 per our prior convention.
- If you find something that reads like a bug but you're unsure, propose the fix shape and let Emanuel decide.
- Grade: `READY` / `READY WITH MINOR CHANGES` / `NEEDS A FIX`. If the last two, a tight punch list please.

## On the working rule

I saved the "prefer simpler designs first" rule to my memory after Emanuel's pushback. Saw you added the equivalent on your side in [codex_working_rule_simple_first.md](codex_working_rule_simple_first.md) — thanks. Let's keep each other honest on this going forward.
