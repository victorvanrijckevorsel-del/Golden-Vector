"""Shared overview helpers for workspace tables and provenance notices."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd

from golden_vector.serve.format_helpers import (
    _column_unique,
    _fmt_text,
)
from golden_vector.serve.ui.status import notice, status_strip
from golden_vector.serve.workspace_state import WorkspaceState


def note_counts_by_ticker(notes: pd.DataFrame) -> dict[str, int]:
    """Per-ticker note counts for the Notes badge — ONE copy shared by the Tool A and
    Tool B overviews (a display count over already-loaded note rows, not model math),
    so the same notebook can't show different badge counts on the two screens."""
    if notes.empty or "ticker" not in notes.columns:
        return {}
    return notes.groupby("ticker").size().to_dict()


def _render_provenance_warnings(state: WorkspaceState) -> str:
    notices: list[str] = []

    if not state.tool_a_alias_present:
        notices.append(
            "Gold Sensitivity output is missing. Run <code>python main.py tool-a</code> "
            "to publish a current snapshot."
        )
    if not state.tool_b_alias_present:
        notices.append(
            "Corporate Finance output is missing. Run <code>python main.py tool-b "
            "--gold-price &lt;X&gt;</code> to publish a current snapshot."
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
                "Gold Sensitivity row(s) reference snapshot "
                f"{sorted(tool_a_run_ids)[0]} while the current foundation manifest "
                f"is {foundation_run_id}"
            )
        if tool_b_run_ids and foundation_run_id not in tool_b_run_ids:
            mismatched_sources.append(
                "Corporate Finance row(s) reference snapshot "
                f"{sorted(tool_b_run_ids)[0]} while the current foundation manifest "
                f"is {foundation_run_id}"
            )
    if tool_a_run_ids and tool_b_run_ids and not tool_a_run_ids.intersection(tool_b_run_ids):
        mismatched_sources.append(
            "Gold Sensitivity and Corporate Finance rows reference different snapshot refresh runs"
        )
    for message in mismatched_sources:
        notices.append(
            f"{escape(message)}. The page may mix data from different refreshes; rerun "
            "<code>python main.py update-data</code> followed by <code>tool-a</code> and "
            "<code>tool-b</code> to align."
        )

    if not notices:
        return ""
    return notice("warning", "".join(f"<p>{item}</p>" for item in notices))


def _render_refresh_summary(manifest: dict[str, Any] | None) -> str:
    """One compact data-status strip (plan 10.2/10.4); manifest interpretation
    and every visible value are unchanged from the metric-card version."""
    if not manifest:
        return notice(
            "neutral", "No validated local market-data snapshot is available yet."
        )
    return status_strip(
        (
            ("Refresh Run", _fmt_text(manifest.get("refresh_run_id"))),
            ("Snapshot As Of", _fmt_text(manifest.get("snapshot_as_of_date"))),
            ("Foundation Status", _fmt_text(manifest.get("foundation_status"))),
        ),
        label="Latest market snapshot status",
    )


def _collect_filter_options(
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Derive dropdown options for categorical columns from rendered rows."""
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
    """Render the table-local DataTables filter bar."""
    labels = column_labels or {}
    dropdowns: list[str] = []
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
