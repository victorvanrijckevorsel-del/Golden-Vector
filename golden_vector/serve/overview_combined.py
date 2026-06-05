"""Combined overview rendering and table-filter helpers for the workspace UI."""

from __future__ import annotations

from html import escape
from typing import Any, Callable

import pandas as pd

from golden_vector.serve.format_helpers import (
    _column_unique,
    _fmt_number,
    _fmt_numeric_td,
    _fmt_text,
    _frame_index_by_ticker,
    _metric_card,
    _optional_float,
)
from golden_vector.serve.lenses import (
    DEFAULT_LENS_ID,
    LENS_DEFINITIONS,
    compute_lens_score,
    resolve_lens,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.workspace_state import OverviewFilters, WorkspaceState


def _render_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    filters: OverviewFilters | None = None,
    lens_id: str = DEFAULT_LENS_ID,
    scoring_config: Any = None,
) -> str:
    filters = filters or OverviewFilters()
    lens = resolve_lens(lens_id)
    note_counts = (
        state.stock_notes.groupby("ticker").size().to_dict()
        if not state.stock_notes.empty and "ticker" in state.stock_notes.columns
        else {}
    )
    company_index = _frame_index_by_ticker(state.company_inputs)
    tool_a_index = _frame_index_by_ticker(state.latest_tool_a)
    tool_b_index = _frame_index_by_ticker(state.latest_tool_b)

    # Build per-ticker derived rows (Phase 1B.4 filter/sort source-of-truth).
    derived_rows: list[dict[str, Any]] = []
    for ticker in state.tool_b_tickers:
        tool_a_row = tool_a_index.get(ticker, {})
        tool_b_row = tool_b_index.get(ticker, {})
        lens_score = (
            compute_lens_score(tool_a_row, lens_id=lens.id, scoring_config=scoring_config)
            if scoring_config is not None and tool_a_row
            else None
        )
        derived_rows.append(
            {
                "ticker": ticker,
                "company_row": company_index.get(ticker, {}),
                "tool_a_row": tool_a_row,
                "tool_b_row": tool_b_row,
                "profile_label": str(tool_a_row.get("profile_label") or "").strip().upper(),
                "verdict": str(tool_b_row.get("screening_verdict") or "").strip().upper(),
                "confidence_label": str(tool_a_row.get("confidence_label") or "").strip().upper(),
                "volatility_context": str(tool_a_row.get("volatility_context") or "").strip().upper(),
                "tool_a_rank": _optional_float(tool_a_row.get("tool_a_rank")),
                "tool_b_rank": _optional_float(tool_b_row.get("tool_b_rank")),
                "tool_a_score": _optional_float(tool_a_row.get("tool_a_score")),
                "tool_b_score": _optional_float(tool_b_row.get("tool_b_score")),
                "lens_score": lens_score,
                "note_count": int(note_counts.get(ticker, 0)),
            }
        )

    # Apply filters.
    search_term = filters.normalized_search()
    profile_filter = filters.normalized_profile()
    verdict_filter = filters.normalized_verdict()
    confidence_filter = filters.normalized_confidence()

    filtered_rows = []
    for row in derived_rows:
        if search_term and search_term not in row["ticker"]:
            continue
        if profile_filter and row["profile_label"] != profile_filter:
            continue
        if verdict_filter and row["verdict"] != verdict_filter:
            continue
        if confidence_filter and row["confidence_label"] != confidence_filter:
            continue
        filtered_rows.append(row)

    # Sort. When a non-default lens is selected, sort by lens_score in the lens's
    # direction (per plan v3 §3 "Re-sort the table by lens_score, direction per lens").
    # When the lens is the default composite, the user's sort dropdown picks the order.
    if lens.id != DEFAULT_LENS_ID:
        ascending = not lens.sort_descending
        filtered_rows.sort(
            key=lambda r: (
                (1, 0.0)
                if r["lens_score"] is None
                else (0, r["lens_score"] if ascending else -r["lens_score"])
            )
        )
    else:
        sort_key = filters.normalized_sort()
        filtered_rows.sort(key=_overview_sort_key(sort_key))

    # Available filter values from the actual data so the dropdown reflects what exists.
    profile_values = sorted({r["profile_label"] for r in derived_rows if r["profile_label"]})
    verdict_values = sorted({r["verdict"] for r in derived_rows if r["verdict"]})
    confidence_values = sorted({r["confidence_label"] for r in derived_rows if r["confidence_label"]})

    # Hide the Lens Score column when lens is the default (composite), since it
    # would just duplicate the Tool A Score column. Both reviewers flagged this.
    show_lens_column = lens.id != DEFAULT_LENS_ID
    rows_html: list[str] = []
    for row in filtered_rows:
        company_row = row["company_row"]
        tool_a_row = row["tool_a_row"]
        tool_b_row = row["tool_b_row"]
        lens_cell = (
            f"<td>{_fmt_number(row['lens_score'], decimals=2)}</td>"
            if show_lens_column
            else ""
        )
        lens_cell_dt = (
            _fmt_numeric_td(row['lens_score'], decimals=2) if show_lens_column else ""
        )
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            f"{_fmt_numeric_td(company_row.get('production_oz'), decimals=0)}"
            f"{_fmt_numeric_td(company_row.get('aisc_usd_per_oz'), decimals=0)}"
            f"{_fmt_numeric_td(tool_a_row.get('structural_delta_core'), decimals=2)}"
            f"{_fmt_numeric_td(tool_a_row.get('structural_gamma_core'), decimals=2)}"
            f"{_fmt_numeric_td(tool_a_row.get('asymmetry_ratio_core'), decimals=2)}"
            f"<td>{_fmt_text(tool_a_row.get('confidence_label'))}</td>"
            f"<td>{_fmt_text(tool_a_row.get('volatility_context'))}</td>"
            f"{_fmt_numeric_td(tool_a_row.get('tool_a_score'), decimals=1)}"
            f"{lens_cell_dt}"
            f"<td>{_fmt_text(tool_a_row.get('profile_label'))}</td>"
            f"{_fmt_numeric_td(tool_b_row.get('tool_b_score'), decimals=1)}"
            f"<td>{_fmt_text(tool_b_row.get('screening_verdict'))}</td>"
            f"{_fmt_numeric_td(row['note_count'], decimals=0)}"
            "</tr>"
        )

    column_count = 14 if show_lens_column else 13
    no_match_row = ""
    if not rows_html:
        no_match_row = (
            f"<tr><td colspan=\"{column_count}\" class=\"hint\">"
            "No tickers match the current filters. Clear them to see the full universe."
            "</td></tr>"
        )

    body = [
        "<h1>Golden Vector Workspace</h1>",
        "<p>This is the local working view for Tool B manual inputs, notes, and the latest structural Tool A output. "
        "Tool A is now structural-first, while the old horizon-return view is shown only as exploratory context.</p>",
    ]
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        _render_overview_filters_form(
            filters=filters,
            profile_values=profile_values,
            verdict_values=verdict_values,
            confidence_values=confidence_values,
            visible_count=len(filtered_rows),
            total_count=len(derived_rows),
            lens=lens,
        )
    )
    lens_score_header_cell = (
        f"<th data-col-name=\"lens_score\" data-sort-numeric>Lens Score ({escape(lens.title)})</th>"
        if show_lens_column
        else ""
    )
    # Filter-bar options must come from `filtered_rows` (post server-side
    # filters), not `derived_rows`, so the DataTables dropdown never
    # offers a value that doesn't exist in the currently rendered table.
    # The existing `*_values` sets above are intentionally built from
    # `derived_rows` — they feed the SERVER-side filter form where the
    # user needs to see all possible values to pick one.
    combined_filter_options = _collect_filter_options(
        filtered_rows,
        [
            ("profile", "profile_label"),
            ("confidence", "confidence_label"),
            ("volatility", "volatility_context"),
            ("verdict", "verdict"),
        ],
    )
    body.append("<h2>Universe Overview</h2>")
    body.append(_render_filter_bar(
        target_table_id="combined-table",
        options=combined_filter_options,
        column_labels={
            "profile": "Profile",
            "confidence": "Confidence",
            "volatility": "Volatility",
            "verdict": "Tool B Verdict",
        },
    ))
    body.append(
        "<table id=\"combined-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"production\" data-sort-numeric>Production</th>"
        "<th data-col-name=\"aisc\" data-sort-numeric>AISC</th>"
        "<th data-col-name=\"delta\" data-sort-numeric>Structural Delta</th>"
        "<th data-col-name=\"gamma\" data-sort-numeric>Gamma</th>"
        "<th data-col-name=\"asymmetry\" data-sort-numeric>Asymmetry</th>"
        "<th data-col-name=\"confidence\">Confidence</th>"
        "<th data-col-name=\"volatility\">Volatility</th>"
        "<th data-col-name=\"tool_a_score\" data-sort-numeric>Tool A Score</th>"
        f"{lens_score_header_cell}"
        "<th data-col-name=\"profile\">Profile</th>"
        "<th data-col-name=\"tool_b_score\" data-sort-numeric>Tool B Score</th>"
        "<th data-col-name=\"verdict\">Tool B Verdict</th>"
        "<th data-col-name=\"notes\" data-sort-numeric>Notes</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}{no_match_row}</tbody>"
        "</table>"
    )
    body.append(
        "<p class=\"hint\">Use <code>python main.py update-data</code> to refresh market data. "
        "Use the stock links above to edit Tool B inputs and inspect the structural Tool A explanation cards.</p>"
    )
    return _page_shell("Golden Vector Workspace", "".join(body), active_nav="combined")


def _render_overview_filters_form(
    *,
    filters: OverviewFilters,
    profile_values: list[str],
    verdict_values: list[str],
    confidence_values: list[str],
    visible_count: int,
    total_count: int,
    lens: Any,
) -> str:
    def _options(values: list[str], current: str) -> str:
        opts = ["<option value=\"\">All</option>"]
        for value in values:
            selected = " selected" if value == current else ""
            opts.append(f"<option value=\"{escape(value)}\"{selected}>{escape(value)}</option>")
        return "".join(opts)

    sort_options_html = "".join(
        f"<option value=\"{escape(key)}\"{' selected' if key == filters.normalized_sort() else ''}>{escape(label)}</option>"
        for key, label in OverviewFilters.SORT_OPTIONS
    )
    lens_options_html = "".join(
        f"<option value=\"{escape(spec.id)}\"{' selected' if spec.id == lens.id else ''}>{escape(spec.title)}</option>"
        for spec in LENS_DEFINITIONS.values()
    )

    # When a non-default lens is active the sort dropdown is functionally ignored,
    # so we visually disable it (codex/Claude both flagged the half-state). The
    # hint below is kept for redundancy.
    sort_disabled_attr = " disabled" if lens.id != DEFAULT_LENS_ID else ""
    sort_disabled_note = (
        "<p class=\"hint\">Sort dropdown is ignored while a non-default lens is active; "
        "the initial table order follows the lens's score. Clicking a column header "
        "reorders this view only (not persisted across reloads).</p>"
        if lens.id != DEFAULT_LENS_ID
        else ""
    )

    return (
        "<section class=\"panel overview-filters\">"
        "<form method=\"get\" action=\"/\" class=\"overview-filters-form\">"
        f"<label><span>View by lens</span><select name=\"lens\">{lens_options_html}</select></label>"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(filters.search)}\" placeholder=\"NEM\"></label>"
        f"<label><span>Profile</span><select name=\"profile\">{_options(profile_values, filters.normalized_profile())}</select></label>"
        f"<label><span>Tool B Verdict</span><select name=\"verdict\">{_options(verdict_values, filters.normalized_verdict())}</select></label>"
        f"<label><span>Confidence</span><select name=\"confidence\">{_options(confidence_values, filters.normalized_confidence())}</select></label>"
        f"<label><span>Sort by</span><select name=\"sort\"{sort_disabled_attr}>{sort_options_html}</select></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">Showing {visible_count} of {total_count} tickers.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/\">Reset</a>"
        "</div>"
        "</form>"
        f"<p class=\"hint\"><strong>{escape(lens.title)}:</strong> {escape(lens.hint)}</p>"
        f"{sort_disabled_note}"
        "</section>"
    )


def _overview_sort_key(sort_key: str) -> Callable[[dict[str, Any]], Any]:
    """Build a sort key function.

    Direction is baked into the key (ascending naturally; descending via negation),
    so callers should always sort without ``reverse``. Missing values land in a
    second bucket and therefore appear at the bottom regardless of direction.
    """

    def _present_or_missing(value: float | None, ascending: bool) -> tuple[int, float]:
        if value is None:
            return (1, 0.0)
        return (0, value if ascending else -value)

    if sort_key == "ticker":
        return lambda r: (0, r["ticker"])
    if sort_key == "tool_a_rank":
        return lambda r: _present_or_missing(r["tool_a_rank"], ascending=True)
    if sort_key == "tool_b_rank":
        return lambda r: _present_or_missing(r["tool_b_rank"], ascending=True)
    if sort_key == "tool_a_score":
        return lambda r: _present_or_missing(r["tool_a_score"], ascending=False)
    if sort_key == "tool_b_score":
        return lambda r: _present_or_missing(r["tool_b_score"], ascending=False)
    return lambda r: (0, r["ticker"])


def _render_provenance_warnings(state: WorkspaceState) -> str:
    notices: list[str] = []

    if not state.tool_a_alias_present:
        notices.append(
            "Tool A latest output is missing. Run <code>python main.py tool-a</code> to publish a current snapshot."
        )
    if not state.tool_b_alias_present:
        notices.append(
            "Tool B latest output is missing. Run <code>python main.py tool-b --gold-price &lt;X&gt;</code> to publish a current snapshot."
        )

    foundation_run_id = (
        str(state.foundation_manifest.get("refresh_run_id"))
        if state.foundation_manifest and state.foundation_manifest.get("refresh_run_id")
        else None
    )
    tool_a_run_ids = _column_unique(state.latest_tool_a, "snapshot_refresh_run_id")
    tool_b_run_ids = _column_unique(state.latest_tool_b, "snapshot_refresh_run_id")

    mismatched_sources: list[str] = []
    if foundation_run_id:
        if tool_a_run_ids and foundation_run_id not in tool_a_run_ids:
            mismatched_sources.append(
                f"Tool A row(s) reference snapshot {sorted(tool_a_run_ids)[0]} while the current foundation manifest is {foundation_run_id}"
            )
        if tool_b_run_ids and foundation_run_id not in tool_b_run_ids:
            mismatched_sources.append(
                f"Tool B row(s) reference snapshot {sorted(tool_b_run_ids)[0]} while the current foundation manifest is {foundation_run_id}"
            )
    if tool_a_run_ids and tool_b_run_ids and not tool_a_run_ids.intersection(tool_b_run_ids):
        mismatched_sources.append(
            "Tool A and Tool B rows reference different snapshot refresh runs"
        )
    for message in mismatched_sources:
        notices.append(
            f"{escape(message)}. The page may mix data from different refreshes; rerun <code>python main.py update-data</code> followed by <code>tool-a</code> and <code>tool-b</code> to align."
        )

    if not notices:
        return ""
    return (
        "<div class=\"flash\">"
        + "".join(f"<p>{notice}</p>" for notice in notices)
        + "</div>"
    )


def _render_refresh_summary(manifest: dict[str, Any] | None) -> str:
    if not manifest:
        return (
            "<div class=\"panel\">"
            "<h2>Latest Market Snapshot</h2>"
            "<p>No validated local market-data snapshot is available yet.</p>"
            "</div>"
        )
    refresh_run_id = _fmt_text(manifest.get("refresh_run_id"))
    snapshot_as_of_date = _fmt_text(manifest.get("snapshot_as_of_date"))
    foundation_status = _fmt_text(manifest.get("foundation_status"))
    return (
        "<div class=\"panel metric-grid\">"
        f"{_metric_card('Refresh Run', refresh_run_id)}"
        f"{_metric_card('Snapshot As Of', snapshot_as_of_date)}"
        f"{_metric_card('Foundation Status', foundation_status)}"
        "</div>"
    )


def _collect_filter_options(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Derive dropdown options for categorical columns from rendered rows.

    `columns` is a list of (column_name, row_key) pairs. For each pair,
    the helper walks `rows`, collects non-empty string values found at
    `row[row_key]`, and returns them sorted under `column_name`. Pattern
    matches the existing overview form's `profile_values / verdict_values /
    confidence_values` derivation so the dropdown only ever lists values
    that actually appear in the rendered table.
    """
    out: dict[str, list[str]] = {}
    for column_name, row_key in columns:
        seen: set[str] = set()
        for row in rows:
            value = row.get(row_key)
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
            except TypeError:
                pass
            text = str(value).strip()
            if text:
                seen.add(text)
        out[column_name] = sorted(seen)
    return out


def _render_filter_bar(
    *,
    target_table_id: str,
    options: dict[str, list[str]],
    column_labels: dict[str, str] | None = None,
    global_search_hint: str = "Filter rows (this page only)",
) -> str:
    """Render the `<section class="table-filters">` bar above a table.

    `options` maps column_name → sorted list of values to offer in the
    dropdown. `column_labels` optionally overrides the user-facing label
    for each column; otherwise the raw column name is titlecased.

    The filter bar is generic — `workspace-tables.js` finds it via the
    `data-filter-target` attribute and wires DataTables to its controls.
    """
    labels = column_labels or {}
    dropdowns: list[str] = []
    # Columns with no values (no data in the rendered rows) still render
    # a dropdown with only the "All" option so the bar's layout stays
    # consistent as data shifts.
    for column_name, values in options.items():
        label_text = labels.get(column_name) or column_name.replace("_", " ").title()
        option_tags = "<option value=\"\">All</option>" + "".join(
            f"<option value=\"{escape(value)}\">{escape(value)}</option>"
            for value in values
        )
        dropdowns.append(
            "<label class=\"filter-column\">"
            f"<span>{escape(label_text)}</span>"
            f"<select data-filter-column=\"{escape(column_name)}\">{option_tags}</select>"
            "</label>"
        )
    return (
        f"<section class=\"panel table-filters\" data-filter-target=\"#{escape(target_table_id)}\">"
        "<div class=\"table-filters-row\">"
        "<label class=\"filter-global\">"
        f"<span>{escape(global_search_hint)}</span>"
        "<input type=\"text\" data-global-search placeholder=\"Type to filter any column\">"
        "</label>"
        f"{''.join(dropdowns)}"
        "</div>"
        "</section>"
    )
