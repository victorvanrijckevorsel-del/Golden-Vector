# Plan: Wire DataTables into the Tool A / Tool B / Combined Views

Date: 2026-04-24
Author: Claude (Opus 4.7)
Status: PROPOSED — awaiting Emanuel's approval before any code is written
For review by: Codex

## Background

Emanuel wants the 60-row Tool A and Tool B tables to behave like Excel:
click a column header to sort, use per-column filter dropdowns to narrow
down (e.g. show only `STRONG_CANDIDATE` verdicts). Today both tables
are static HTML with a single `<select>` sort control on the Combined
view and no per-column sort/filter anywhere.

DataTables is the most mature library for this — server emits plain
HTML with a few extra attributes, a small JS init call turns it into
an Excel-like table. Pure-static pages stay pure-static from the
server's perspective; the interactivity lives entirely in the browser.

This plan ships DataTables to the three overview tables on the
workspace, wired cleanly to our existing table generation so future
column additions/removals pick up the interactivity automatically.

## Goal — what's true after this milestone

- Every column in Tool A, Tool B, and Combined views is **click-to-sort** with a visible direction arrow
- Numeric columns sort **numerically** (e.g. 14.07 sorts between 8.81 and 28.06), not lexicographically
- Every table has a **global search box** (matches any visible cell, live-filters as you type)
- Categorical columns (Verdict, Profile, Confidence, Volatility, Layer 1) have **dropdown value filters** (pick one value from a list, table filters to it)
- The table is **paginated only if >50 rows on screen**; for 60-ticker views, all rows show on one page (no pager noise)
- Existing Screening Parameters panel + ticker search box continue to work **alongside** DataTables (they filter the server-side row set; DataTables filters within the rendered client-side rows)
- Works **offline** (DataTables assets vendored into the repo, not loaded from a CDN)
- Our test suite still passes (currently 257)
- Visual style matches the rest of the workspace (warm beige/brown palette, serif font, bordered panels)

## Out of scope (deliberately)

- SearchPanes (the Excel-style checkbox-per-value filter pane). Expensive extension; basic dropdown filter covers the same user need in a smaller footprint. Revisit after v1 if needed.
- Column show/hide, column reorder, row export buttons. These are DataTables add-on features; not asked for.
- Applying DataTables to the ticker detail page's small reference tables (structural window metrics, latest snapshots). Those are short enough that Excel-like interactivity is overkill.
- Persisting DataTables sort/filter state across page loads. Client-side only; if the user reloads, the table goes back to default sort. Simple and predictable.
- Server-side processing (needed only for >10k rows). Our 60 rows fit comfortably in browser memory.

## Architecture choices

### Vendored, not CDN

`golden_vector/serve/static/vendor/datatables/` will hold:
- `jquery-3.7.1.slim.min.js` (DataTables dependency, ~30 KB slim)
- `datatables-2.1.8.min.js` (~85 KB)
- `datatables-2.1.8.min.css` (~15 KB)

Total additional repo weight: ~130 KB. Vendoring means:
- Works offline (Emanuel's primary workflow)
- No surprise breakage if a CDN changes or deprecates a version
- Deterministic builds

Versions pinned in filenames so future upgrades are explicit.

### New WSGI static-file route

The workspace app currently serves only HTML. Adding a small `/static/*` handler that reads from `golden_vector/serve/static/` and returns with the right Content-Type. About 20 lines of Python. Served locally from the same port 8765.

### DataTables initialization lives in a tiny inline `<script>` block

Not a separate file — the init config differs slightly per view (which columns are filterable, which are numeric). Inline keeps the view code and its DataTables config in one place. Total JS per page: ~15 lines.

### Sort-by-raw-number via `data-order` attributes

The server emits HTML like:
```html
<td data-order="107.4">107.4%</td>
<td data-order="66.14">66.14</td>
```

DataTables reads `data-order` as the sort key but displays the formatted cell text. This keeps our existing `_fmt_number` / `_fmt_percent` helpers unchanged and gives numerically correct sorting for free.

For text columns (Ticker, Verdict, Confidence) we just let DataTables sort the visible text — same as alphabetical.

For the Rank column (which is already a numeric string like "1", "2"), `data-order` still useful so empty/`-` cells land at the bottom consistently.

### Per-column dropdown filters

DataTables supports per-column filter UI via its API. For each categorical column, we inject a `<select>` into the column header area, populated with the distinct values in that column. Selecting a value triggers `column.search(...)`.

Columns that get dropdown filters:

| View | Column | Options |
|---|---|---|
| Combined + Tool A | Profile | CONVEX / LINEAR / INVERSE / SCORE_WITHHELD |
| Combined + Tool A | Confidence | HIGH / MEDIUM / LOW / WITHHELD |
| Combined + Tool A | Volatility | LOW_NOISE / MODERATE_NOISE / HIGH_NOISE / WITHHELD |
| Combined + Tool B | Verdict | STRONG_CANDIDATE / WATCHLIST / SCREEN_OUT / INCOMPLETE |
| Combined + Tool B | Layer 1 | PASS / FAIL / INCOMPLETE |

Numeric columns don't get dropdown filters (the global search covers substring matches; a numeric range filter is a rabbit hole).

### CSS override to match our aesthetic

DataTables ships with a clean baseline CSS. We override:
- Header background to match `--accent-soft` (warm beige)
- Sort-arrow color to `--accent` (brown)
- Focus/hover states to match
- Pagination chrome suppressed (we disable pagination below threshold)

About 30 lines of CSS in `_page_shell`'s `<style>` block.

## Step-by-step plan

### Step 1 — Vendor DataTables + add `/static/*` route (45 min)

**New directory:** `golden_vector/serve/static/vendor/datatables/`

Download and commit (pinned versions):
- `jquery-3.7.1.slim.min.js`
- `datatables.min.js` (v2.1.8, with `dt-core` preset so we get sort + basic filter, nothing heavier)
- `datatables.min.css`

**Code change — `golden_vector/serve/workspace.py`:**

Add a route handler before the existing HTML routes:

```python
if method == "GET" and path.startswith("/static/"):
    return _serve_static_file(paths_to_static, path, start_response)
```

`_serve_static_file`:
- Normalize path, reject `..` traversal
- Map MIME types for `.js`, `.css`
- Stream with `200 OK` or `404 Not Found`
- Long cache headers (`Cache-Control: public, max-age=31536000`) since files are version-pinned

**Tests (in `tests/test_workspace_app.py`):**
- `test_workspace_serves_vendored_datatables_js` → GET `/static/vendor/datatables/datatables-2.1.8.min.js` returns 200 + `application/javascript`
- `test_workspace_static_route_rejects_path_traversal` → GET `/static/../../secret` returns 404

### Step 2 — Helper layer in `workspace.py` (1 hour)

Two helpers to keep the view render functions clean:

**`_format_numeric_cell(value, decimals) -> str`**

Returns `<td data-order="X">Y</td>` where X is the raw number and Y is the formatted display. Replaces inline `f"<td>{_fmt_number(...)}</td>"` patterns that already exist in the three views. Preserves exact display behavior; only adds `data-order`.

**`_render_datatables_init_script(table_id, columns_config) -> str`**

Emits a `<script>` block with the DataTables `new DataTable(...)` call for a given table. `columns_config` is a small data structure naming:
- which columns have dropdown filters and what options
- which columns are numeric (for fallback typing)
- default sort column and direction

One central config function keeps Tool A / Tool B / Combined initialization consistent.

### Step 3 — Wire Tool B view (45 min)

Add `id="tool-b-table"` and `class="datatable"` to the generated `<table>`.

Replace all numeric `<td>` cells with `_format_numeric_cell` output so sort-by-number works.

Append `_render_datatables_init_script(...)` to the rendered body. Config:

```python
columns_config = {
    "table_id": "tool-b-table",
    "dropdown_filters": [
        ("Verdict", [...verdict values...]),
        ("Layer 1", ["PASS", "FAIL", "INCOMPLETE"]),
    ],
    "default_sort": ("Rank", "asc"),
    "paging_threshold": 50,  # disable paging if <50 rows
}
```

**Tests:**
- `test_tool_b_view_emits_datatables_init_script` → response body contains `new DataTable("#tool-b-table"`
- `test_tool_b_view_numeric_cells_carry_data_order` → spot-check that "Peer P/E Target" column has `data-order="..."`
- `test_tool_b_view_verdict_column_has_dropdown_filter_options` → init script mentions all 4 verdict values

### Step 4 — Wire Tool A view (30 min)

Same pattern. Config differs:
- `default_sort` = ("Rank", "asc") same as Tool B
- Dropdown filters: Profile, Confidence, Volatility

### Step 5 — Wire Combined view (45 min)

Same pattern. Config includes ALL dropdown filters from both Tool A and Tool B (Profile, Confidence, Volatility, Verdict, Layer 1).

**Open question for Emanuel**: the Combined view currently has a server-side sort dropdown (`?sort=tool_a_score` etc.). Once DataTables is in, click-to-sort on headers makes that dropdown redundant. Two options:
- (a) Remove the server-side sort dropdown. One way to sort: click the header.
- (b) Keep it as a "default sort" pre-selector that DataTables honors on load.

My recommendation: **(a)** — removing it simplifies the UI and the one-way-to-do-things principle is clean. The lens picker stays (it changes ranking math, not just display order).

### Step 6 — Styling polish (30 min)

CSS overrides to match our aesthetic:
- `.dataTables_wrapper` inherits our panel look
- Sort arrows in `--accent` color
- Header hover in `--accent-soft`
- Search box styled consistently with our existing inputs

**Open question for Emanuel**: DataTables has its own "Search:" input above the table. Our views already have a ticker search form below the Screening Parameters panel. Three options:
- (a) Keep both. DataTables search is live-as-you-type client-side; our server-side search re-renders the page.
- (b) Hide the DataTables search; keep ours.
- (c) Hide ours; keep DataTables search (and reword the hint).

My recommendation: **(c)** — DataTables search is strictly better UX (instant, searches all columns not just ticker) and removing ours removes clutter. Loses server-side bookmarkability via `?search=X` but that's a low-usage feature.

### Step 7 — Full smoke test + commit (30 min)

Open `/tool-b`, click every column header to confirm correct numeric vs text sorting. Try the Verdict dropdown: "STRONG_CANDIDATE" should filter to 9 rows. Try the global search: "MUX" filters to 1 row. Reload the page: default sort returns.

Repeat for `/tool-a` and `/`.

**Single commit**: `Wire DataTables into Tool A / Tool B / Combined views for click-sort + per-column filters`.

## Cross-cutting concerns

### Interaction with existing URL-param overrides

Nothing changes server-side. `/tool-b?gold_price=4500` still triggers the in-memory recompute; DataTables just styles the resulting table. URL params and DataTables state are orthogonal.

### Performance

DataTables on 60 rows with 17 columns is instant (sub-5ms in the browser). No perf concerns at this scale.

### Accessibility

DataTables has reasonable a11y out of the box (ARIA labels on sort buttons, keyboard navigation). We're not adding custom widgets that would need bespoke a11y work.

### Test coverage impact

About 8 new tests, each small. Suite should end around 265 passing.

### Commit cadence

One commit after Step 7. Steps 1-6 are tightly coupled (the route enables the JS, which enables the helpers, which enable the three views). No value in landing them independently.

## Estimated total time

| Step | Time |
|---|---|
| 1 — Vendor + static route | 45 min |
| 2 — Helper layer | 1 hr |
| 3 — Tool B view | 45 min |
| 4 — Tool A view | 30 min |
| 5 — Combined view | 45 min |
| 6 — Styling | 30 min |
| 7 — Smoke + commit | 30 min |
| **Total** | **4 hrs 45 min** |

## Decisions Emanuel needs to confirm

1. **Vendored DataTables assets (my rec)** vs CDN — vendored means offline works, a few extra files in the repo
2. **Remove server-side sort dropdown on Combined (my rec)** vs keep it as a DataTables pre-selector
3. **Hide our ticker search box (my rec: keep DataTables global search, drop ours)** vs keep both
4. **Pagination threshold of 50 rows (my rec)** vs always paginated vs never paginated

If any of these land differently, the plan adjusts but the overall shape stays.

## What Codex should review

Specifically asking Codex to challenge:

1. **Is vendoring DataTables the right call, or would a CDN link with a local fallback be cleaner?** I picked vendored for offline-first; is there a reason to prefer CDN?
2. **Is `data-order` on numeric `<td>` the right sort-key strategy, or should I use `columns.type: "num-fmt"`?** Both work; `data-order` is explicit per cell but verbose. DataTables' type-based sort is cleaner but requires a plugin for custom formats.
3. **Is the `_render_datatables_init_script` + `columns_config` abstraction worth it, or would three nearly-identical inline scripts be more honest?** Abstraction adds one layer to trace; inline would be more repetitive but easier to read per-view.
4. **Should dropdown filters live in the `<thead>` row or in a separate filter bar above the table?** DataTables supports both. Header is tighter but can crowd the label; above-table is more visible but takes vertical space.
5. **Any security concerns with the new static-file route?** I plan to reject `..` traversal and scope to `golden_vector/serve/static/`, but worth a second look.
6. **Any test gap I should close before shipping?** I listed 8 tests but browser behavior is only tested by reading the init script text — should I add a playwright-based smoke test?
7. **Anything about the friend's Excel workflow this might break for Emanuel?** His mental model is Excel filters. DataTables is closer to that than the current server-side `<select>`, but is there a specific Excel behavior users will miss?

---

## Appendix — sample DataTables init (for reference)

This is what the inline `<script>` block would look like for Tool B:

```html
<script src="/static/vendor/datatables/jquery-3.7.1.slim.min.js"></script>
<script src="/static/vendor/datatables/datatables-2.1.8.min.js"></script>
<link rel="stylesheet" href="/static/vendor/datatables/datatables-2.1.8.min.css">
<script>
  const table = new DataTable('#tool-b-table', {
    paging: false,       // 60 rows fits on one screen
    info: false,         // hide "Showing 1 to 60 of 60"
    order: [[3, 'asc']], // default sort: Rank column ascending
    language: { search: 'Filter rows:' },
  });
  // Inject dropdown filter for Verdict column (index 1)
  const verdictHeader = table.column(1).header();
  const select = document.createElement('select');
  select.innerHTML = '<option value="">All verdicts</option>'
    + ['STRONG_CANDIDATE','WATCHLIST','SCREEN_OUT','INCOMPLETE']
        .map(v => `<option>${v}</option>`).join('');
  select.addEventListener('change', e => {
    table.column(1).search(e.target.value ? '^' + e.target.value + '$' : '', true, false).draw();
  });
  verdictHeader.appendChild(select);
</script>
```

Repeated for Layer 1 (Tool B), Profile / Confidence / Volatility (Tool A), etc.
