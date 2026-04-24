/**
 * Workspace tables — click-sort + filter bar activation.
 *
 * Reads HTML data attributes emitted by Python and activates DataTables
 * for every `<table class="js-datatable">` on the page. Python never
 * writes a line of DataTables config — all the knowledge lives here.
 *
 * HTML contract:
 *
 *   <table class="js-datatable" id="some-table">
 *     <thead>
 *       <tr>
 *         <th data-col-name="ticker">Ticker</th>
 *         <th data-col-name="score" data-sort-numeric>Score</th>
 *         ...
 *       </tr>
 *     </thead>
 *     <tbody>
 *       <tr>
 *         <td>NEM</td>
 *         <td data-order="89.5">89.5</td>
 *         ...
 *       </tr>
 *     </tbody>
 *   </table>
 *
 *   <section class="table-filters" data-filter-target="#some-table">
 *     <input type="text" data-global-search>
 *     <select data-filter-column="verdict">...</select>
 *   </section>
 *
 * Order of activation: filter bar must appear before the table in the
 * DOM if you want the labels on top, but DataTables finds either
 * arrangement via `data-filter-target`.
 */
document.addEventListener('DOMContentLoaded', () => {
  // Graceful degradation: if DataTables (or jQuery underneath it) failed
  // to load, just leave the plain HTML tables alone. Server-side controls
  // still work regardless.
  if (typeof window.DataTable !== 'function') return;

  document.querySelectorAll('table.js-datatable').forEach((table) => {
    const headerCells = Array.from(table.querySelectorAll('thead th'));
    const columns = headerCells.map((th) => ({
      name: th.dataset.colName || '',
      type: th.hasAttribute('data-sort-numeric') ? 'num' : undefined,
    }));

    const dt = new DataTable(table, {
      paging: false,
      info: false,
      // Preserve the server-emitted DOM order on first paint. Non-default
      // lenses on the Combined view rely on this.
      order: [],
      columns: columns,
      // Hide DataTables' own "Search:" label — we render our own input.
      language: { search: '' },
    });

    // Find the filter bar by matching data-filter-target to this table's
    // id. Iterating and comparing as strings (rather than building a CSS
    // selector with the id interpolated) avoids any selector-escaping
    // trouble if a future table gets a funky id.
    const targetId = '#' + table.id;
    const bar = Array.from(
      document.querySelectorAll('.table-filters[data-filter-target]')
    ).find((el) => el.dataset.filterTarget === targetId);
    if (!bar) return;

    // Live global search across all visible cells.
    const searchInput = bar.querySelector('input[data-global-search]');
    if (searchInput) {
      searchInput.addEventListener('input', (event) => {
        dt.search(event.target.value).draw();
      });
    }

    // Per-column dropdown filters. Empty value means "show all".
    bar.querySelectorAll('select[data-filter-column]').forEach((select) => {
      const columnName = select.dataset.filterColumn;
      if (!columnName) return;
      select.addEventListener('change', (event) => {
        const value = event.target.value;
        // Escape regex metacharacters so future filter values with dots,
        // parens, etc. don't misbehave. Current domain is ASCII-safe but
        // this is cheap insurance.
        const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        dt.column(columnName + ':name')
          .search(value ? '^' + escaped + '$' : '', true, false)
          .draw();
      });
    });
  });
});
