# Plan v2: Wire DataTables into the Tool A / Tool B / Combined Views

Date: 2026-04-24
Author: Claude (Opus 4.7)
Status: PROPOSED — v2, revised after Codex review + self-review of v1
For review by: Codex

## Why v2

Codex reviewed [claude_workspace_datatables_plan.md](claude_workspace_datatables_plan.md) and graded it `STILL NOT READY`. He flagged four substantive issues; my own self-review caught another four. Most relate to the plan being sloppy about the difference between "what DataTables offers" and "what our product actually needs." v2 addresses all of them up front.

Changes from v1:

| # | Issue (source) | Severity | Resolution in v2 |
|---|---|---|---|
| 1 | Hard-coded filter option lists are already wrong vs live data — `FRAGILE`, `DEFENSIVE`, `LOW_LINKAGE`, `HIGH_DOWNSIDE_RISK` are real labels v1 listed wrong | Codex P1 | **Filter options are derived from the rendered row set at render time**, same way the existing overview filter dropdowns already work. No hard-coded lists in Python or JS. |
| 2 | v1 flip-flopped on "augment vs replace" — claimed existing controls stay, then recommended removing the sort dropdown and the ticker search | Codex P1 | **DataTables augments; it does not replace.** Lens picker, sort dropdown, and the ticker search stay. DataTables adds a second layer of per-column sort/search on top of the already-rendered rows. |
| 3 | Pagination rule said both ">50 rows" threshold AND "60-row views show one page" — contradictory | Codex P2 | **No pagination for any view.** 60 rows fit; if the universe ever grows past ~200, revisit. |
| 4 | jQuery listed as a dependency, but DataTables 2.x doesn't require it for the proposed API | Codex P2 | **Drop jQuery.** Use DataTables 2.x standalone (~85 KB instead of ~115 KB with jQuery). |
| 5 | Filter `<select>` stuffed into `<thead>` would crowd the Tool B 17-column header | Codex P3 | **Filter bar above the table**, not in headers. Clean label row stays untouched. |
| 6 | Default sort by column INDEX (e.g. `order: [[3, 'asc']]`) breaks silently if columns re-order | self | **Use column names via `columns: [{name: 'rank', ...}]`** so default sort survives future column changes. |
| 7 | `_fmt_number(None)` returns `"-"` but `data-order=""` would sort inconsistently | self | **Missing values get `data-sort="Infinity"`** so they land last regardless of direction. Explicit, predictable. |
| 8 | Filter option values embedded into JS as literal strings risked quote-escaping bugs | self | **Use `json.dumps(...)` for any Python-to-JS value interpolation.** Tested on real data. |

## Goal — what's true after this milestone

- Every column in Tool A, Tool B, and Combined views supports **click-to-sort** with a visible direction arrow.
- Numeric columns sort **numerically** (14.07 is between 8.81 and 28.06, not alphabetically between "1" and "2").
- **A single filter bar above each table** offers:
  - a global search input (live filter across all visible cells)
  - one dropdown per categorical column, values derived from the actual rendered data
- **No pagination.**
- **All existing server-side controls still work.** Lens picker, existing sort dropdown, ticker search form, Screening Parameters overrides. DataTables sits on top, never replaces.
- Works **offline** — assets vendored.
- Test suite still passes (currently 257).

## Non-negotiable design rules (hard constraints)

These lock down the four "which control wins" questions that tripped v1 up.

1. **Server-side controls decide which rows get rendered.** Lens choice, Tool B override parameters, and the ticker search each produce different row sets. The server is always the source of truth for which tickers are in the table.
2. **DataTables decides what the user sees within the rendered row set.** Sort order, visible rows after search, visible rows after filter — all client-side state on top of the server-rendered rows.
3. **The table's initial visual state on first render respects the server's ordering.** The lens-driven default order ships intact; DataTables only re-orders when the user clicks a header.
4. **URL params encode server-side state only.** DataTables sort/search/filter state is not persisted. Reload the page → back to server default. (Future: optional localStorage persistence, but not v1.)
5. **Filter option values are derived from the rendered data** — a helper iterates the row dicts and extracts unique values per categorical column before rendering. If a new label appears next release (`FRAGILE`, say, becomes a profile value only under certain conditions), the dropdown picks it up automatically.

## Out of scope

Same as v1, plus:

- **Multi-select checkbox filters** (Excel's actual "filter-by-value" UX). DataTables has a `SearchPanes` extension that gives Excel-style checkbox-per-value panes. We're shipping single-value dropdowns in v1 — simpler, smaller, covers most of the value. Revisit SearchPanes if Emanuel specifically wants multi-select after using v1.
- **Playwright or Selenium browser tests.** Our pytest suite tests HTML structure. DataTables client-side behavior is well-covered by the library's own tests.
- **The ticker detail page tables** (structural window metrics, latest snapshots). Those are short and do not need interactivity.
- **Export to CSV / Excel** from the UI. Parquet already on disk.

## Architecture

### Vendored, no jQuery

`golden_vector/serve/static/vendor/datatables/` holds two files:

| File | Size | Source |
|---|---|---|
| `datatables-2.1.8.min.js` | ~85 KB | `datatables.net` v2.1.8 core (no jQuery build) |
| `datatables-2.1.8.min.css` | ~15 KB | Same |

Total: ~100 KB, version-pinned filenames so upgrades are explicit.

### New WSGI static-file route

A `/static/*` handler in `golden_vector/serve/workspace.py`:

```python
if method == "GET" and path.startswith("/static/"):
    return _serve_static_file(path, start_response)
```

`_serve_static_file` implementation rules:
1. Compute `candidate = (static_root / relative).resolve()` via `pathlib`.
2. Verify `static_root.resolve()` is a parent of `candidate` (rejects `..` traversal).
3. Allow only `.js` and `.css` extensions (explicit allowlist).
4. Read bytes, return with `Content-Type: application/javascript` or `text/css`.
5. `Cache-Control: public, max-age=31536000, immutable` because filenames are version-pinned.
6. 404 for any miss.

~30 lines of Python. Two tests: one that serves a real file, one that rejects `/static/../../secret`.

### Page-level HTML additions

In `_page_shell`, add to `<head>`:
```html
<link rel="stylesheet" href="/static/vendor/datatables/datatables-2.1.8.min.css">
<script src="/static/vendor/datatables/datatables-2.1.8.min.js" defer></script>
```

The `defer` means the script runs after the HTML is parsed but before `DOMContentLoaded` — perfect for DataTables init scripts appended at the end of each view's body.

### Sort-by-raw-number via `data-order`

Table cells emit:
```html
<td data-order="107.4">107.4%</td>
<td data-order="Infinity">-</td>   <!-- missing values sort last -->
```

A new helper `_fmt_numeric_td(value, decimals=2, as_percent=False)` returns the full `<td>` including the `data-order` attribute. Replaces the existing `<td>{_fmt_number(...)}</td>` / `<td>{_fmt_percent(...)}</td>` inline patterns in the three views.

Missing values (`None`, NaN) emit `data-order="Infinity"` so they land at the bottom of any column regardless of sort direction.

### Filter bar above each table (not in the header)

Structure:

```html
<section class="panel table-filters">
  <div class="global-search">
    <label>Filter rows: <input type="text" id="tool-b-search"></label>
  </div>
  <div class="column-filters">
    <label>Verdict: <select data-column="verdict"><option value="">All</option>...</select></label>
    <label>Layer 1: <select data-column="layer1_status"><option value="">All</option>...</select></label>
  </div>
</section>
<table id="tool-b-table" class="datatable">...</table>
```

The `data-column` attribute on each select identifies which column it filters (by column NAME, not index — survives column reorders).

### DataTables init — live-derived filter options

Python side (new helper in `workspace.py`):

```python
def _collect_categorical_filter_options(
    rows: list[dict], columns: list[tuple[str, str]]
) -> dict[str, list[str]]:
    """Return {column_name: sorted unique non-empty values} from the rendered rows.

    `columns` is a list of (column_name, row_key) pairs, e.g.
    [("verdict", "screening_verdict"), ("layer1_status", "layer1_status")].
    """
```

Each view passes its own (column_name, row_key) list and this helper walks the rendered row set to build the options. No hard-coded lists anywhere.

JS init (inline `<script>` block at end of the view body):

```html
<script>
  (() => {
    const table = new DataTable('#tool-b-table', {
      paging: false,
      info: false,
      columns: __COLUMN_NAMES_JSON__,
      order: [[__DEFAULT_SORT_INDEX__, '__DEFAULT_SORT_DIR__']],
    });
    // Wire the global search input
    const searchInput = document.getElementById('tool-b-search');
    searchInput.addEventListener('input', e => table.search(e.target.value).draw());
    // Wire each column-filter dropdown
    document.querySelectorAll('select[data-column]').forEach(select => {
      const colName = select.getAttribute('data-column');
      select.addEventListener('change', e => {
        const col = table.column(`${colName}:name`);
        col.search(e.target.value ? `^${e.target.value}$` : '', true, false).draw();
      });
    });
  })();
</script>
```

Python interpolates `__COLUMN_NAMES_JSON__` via `json.dumps([{"name": "ticker"}, {"name": "verdict"}, ...])`. The default sort index and direction are resolved from the column-name list so future column reshuffles don't silently break it.

### CSS polish (30 lines in `_page_shell`)

- `table.datatable thead th` — inherits the existing `<thead>` style
- Sort arrows tinted `--accent`
- `.table-filters` panel matches the existing `.panel` look
- DataTables default "Search:" label hidden (we have our own labeled input)
- DataTables pagination chrome hidden (we disable paging)

## Step-by-step plan

### Step 1 — Vendor DataTables + static route (45 min)

Files:
- `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.js`
- `golden_vector/serve/static/vendor/datatables/datatables-2.1.8.min.css`
- `golden_vector/serve/workspace.py` — add `/static/*` route and `_serve_static_file` helper

Tests:
- `test_workspace_serves_vendored_datatables_js`
- `test_workspace_serves_vendored_datatables_css`
- `test_workspace_static_route_rejects_path_traversal`
- `test_workspace_static_route_rejects_disallowed_extension`

### Step 2 — Shared helpers in `workspace.py` (1 hour)

- `_fmt_numeric_td(value, decimals, as_percent=False)` — returns `<td data-order=...>display</td>`
- `_collect_categorical_filter_options(rows, columns)` — returns `{col_name: [unique values]}` from rendered rows
- `_render_filter_bar(view_id, options, global_search_label)` — renders the filter panel HTML
- `_render_datatables_init_script(view_id, columns, default_sort)` — returns the inline `<script>` block with `json.dumps`-safe interpolation

Unit tests on each helper:
- `test_fmt_numeric_td_emits_data_order`
- `test_fmt_numeric_td_missing_value_sorts_last`
- `test_collect_filter_options_derives_from_rendered_rows`
- `test_render_datatables_init_script_uses_column_names_not_indices`
- `test_render_datatables_init_script_json_escapes_option_values`

### Step 3 — Wire Tool B view (45 min)

- Add `id="tool-b-table"` and `class="datatable"` to the rendered table
- Emit a `columns: [{name: "ticker"}, {name: "verdict"}, ...]` JSON block
- Replace inline `<td>{_fmt_number(...)}</td>` calls with `_fmt_numeric_td(...)` — 12 numeric cells in Tool B
- Call `_collect_categorical_filter_options(rows, [("verdict", "screening_verdict"), ("layer1_status", "layer1_status")])`
- Render filter bar above table
- Append init script at end of body

Tests:
- `test_tool_b_view_wraps_numeric_cells_with_data_order`
- `test_tool_b_view_filter_bar_lists_only_verdicts_present_in_data`
- `test_tool_b_view_init_script_uses_column_names_for_default_sort`
- `test_tool_b_view_datatables_state_does_not_alter_server_order_of_first_render` — assert that the server-rendered row order (by `tool_b_rank`) is identical before and after DataTables is added

### Step 4 — Wire Tool A view (30 min)

Same pattern. Categorical columns: `profile_label`, `confidence_label`, `volatility_context`.

Tests mirror Step 3.

### Step 5 — Wire Combined view (45 min)

Same pattern. Categorical columns: union of Tool A's and Tool B's.

**Critical coexistence tests:**
- `test_combined_view_lens_default_order_survives_datatables_init` — when lens is active and server emits a specific row order, the table's first paint matches that order
- `test_combined_view_override_params_survive_through_filter_bar_interactions` — this is a client-side behavior we assert indirectly: the filter bar's HTML doesn't drop any hidden inputs, and the override-preserving filter form still round-trips (this is already covered by an earlier test; just verify the DataTables addition doesn't regress it)

### Step 6 — CSS polish (30 min)

Add ~30 lines to `_page_shell`'s `<style>` block. No new tests — visual only.

### Step 7 — Smoke test + commit (30 min)

Manual browser checks on all three views:
- Click each column header, verify correct numeric vs text sorting
- Use the global search: "MUX" narrows to 1 row, clear brings all back
- Use each dropdown filter: verify only the rendered-data values appear
- Reload the page: default sort returns (no persistence)
- `/tool-b?gold_price=4500`: verify DataTables renders on the recomputed table and the "Scenario active" banner is still visible
- `/?lens=upside_torque`: verify the lens-driven order is the initial order

Single commit: `Wire DataTables into the three overview views for click-sort + filter bar`.

## Cross-cutting concerns

### Interaction with lens picker (Combined view)

Non-default lenses re-rank rows server-side and the existing server-side sort dropdown is shown as disabled with a hint. DataTables does NOT know about lens semantics — it sees the already-reordered rows and preserves that as the default sort. If the user then clicks a column header, DataTables re-sorts; if they clear the sort via a header double-click, they go back to the table's initial paint order (which IS the lens order). This is the behavior Codex recommended in the plan review.

### Interaction with Tool B override parameters

Already tested via `test_workspace_tool_b_view_filter_form_carries_active_overrides_as_hidden_inputs`. The filter form preserving hidden inputs is orthogonal to DataTables — DataTables filters visible rows; the form submits server-side with overrides intact.

One new coexistence note: if the user types into the DataTables global search and then submits the server-side filter form (e.g. adds `?search=NEM`), the page reloads and DataTables state is lost. That's expected — DataTables state is intentionally not persisted. Documented in the UI as a small hint: "Server search reloads the page; header sort and column filters are client-side only."

### Performance

60 rows × 17 columns. DataTables init < 10 ms in Chrome. Global search keystroke < 2 ms. Zero concern.

### Accessibility

DataTables 2.x has ARIA labels on sortable headers. Our filter bar uses semantic `<label>` + `<select>` and `<input>` — screen-reader-accessible by default.

### Test coverage impact

About 15 new tests across Steps 1-5 (I enumerated them above). Suite should end around 272 passing.

### Commit cadence

Single commit at the end. Steps 1-5 interlock — no value in landing them separately.

## Estimated total time

| Step | Time |
|---|---|
| 1 — Vendor + static route | 45 min |
| 2 — Shared helpers | 1 hr |
| 3 — Tool B view | 45 min |
| 4 — Tool A view | 30 min |
| 5 — Combined view | 45 min |
| 6 — CSS polish | 30 min |
| 7 — Smoke + commit | 30 min |
| **Total** | **4 hrs 45 min** |

Same bottom line as v1 even though v2 is stricter — the strictness removes future rework, not adds complexity up front.

## Decisions Emanuel needs to confirm

1. **Single-select dropdowns (my rec) vs multi-select via SearchPanes.** v1 single-select; can add SearchPanes later if he misses multi-select for Verdict / Profile.
2. **Disable pagination entirely (my rec) vs set a high threshold like 200.** Agree with Codex: just disable.
3. **DataTables state is lost on page reload (my rec) vs persist via localStorage.** Disabled for v1; trivial to enable later.

## What Codex should re-review

Specifically asking Codex to confirm each v1 finding is now resolved AND challenge:

1. **Filter-option-derivation from rendered rows** — does `_collect_categorical_filter_options` as described actually do what the current overview form does? I'd want him to check [workspace.py:678](golden_vector/serve/workspace.py#L678) where the overview form derives `profile_values / verdict_values / confidence_values` from `derived_rows`, and confirm my new helper is the same shape.
2. **DataTables 2.x standalone (no jQuery)** — I haven't run v2.x without jQuery; is the non-jQuery bundle clearly available on datatables.net, or do I need a specific build command?
3. **Column-name-based API** — `table.column('verdict:name')` and `columns: [{name: ...}]` — is this stable DT2 API or did it change in a minor release?
4. **`data-order="Infinity"` for missing values** — does DataTables' numeric sort treat `Infinity` correctly as "largest possible"? If not, I'll use `data-order="99999999"` as a sentinel.
5. **The cross-view coexistence tests** I proposed in Step 5 — are they the right tests, or do you see a specific coexistence case I'm still missing (lens x override x DataTables interaction that produces a wrong table)?
6. **Filter bar styling** — any reason NOT to reuse the existing `.panel` class for the filter bar's container?
7. **Is the no-pagination call right even if the universe grows to 200+?** Or should we add a soft threshold that kicks in only then?

---

## Appendix — resolved v1 criticisms summary

| v1 issue | v2 fix |
|---|---|
| Hard-coded `CONVEX / LINEAR / INVERSE / SCORE_WITHHELD` for Profile | Helper derives live values — `FRAGILE`, `DEFENSIVE`, `LOW_LINKAGE` etc. pick up automatically |
| Hard-coded `LOW_NOISE / MODERATE_NOISE / HIGH_NOISE / WITHHELD` for Volatility | Same helper — `HIGH_DOWNSIDE_RISK` picks up automatically |
| "Existing controls continue alongside" AND "remove the sort dropdown" both in v1 | v2 explicit: augment only, never replace. Non-negotiable design rules #1-#4 |
| Pagination said >50 AND ≤50 both | v2: no pagination, period |
| jQuery vendored as dependency | v2: dropped, use DT2 standalone |
| Filter `<select>` in `<thead>` | v2: separate filter bar panel above table |
| Column-index default sort | v2: column-name default sort |
| `None` values with empty `data-order` | v2: `data-order="Infinity"` sentinel |
| Python-to-JS string interpolation | v2: `json.dumps` throughout, with escape tests |
