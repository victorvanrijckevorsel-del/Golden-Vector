"""Detail edit forms for the workspace ticker page."""

from __future__ import annotations

from html import escape
from typing import Any

from golden_vector.screening.manual_data import REQUIRED_MANUAL_FIELDS
from golden_vector.serve.format_helpers import (
    _fmt_note_tag,
    _fmt_text,
    _format_form_value,
    _humanize_column_name,
)


VERIFICATION_STATUS_OPTIONS: tuple[str, ...] = ("VERIFIED", "ESTIMATED", "INCOMPLETE")

NOTE_STATUS_OPTIONS: tuple[str, ...] = ("OPEN", "WATCH", "DONE")

CompanyFieldSpec = tuple[str, str, str]

ReportingFieldSpec = tuple[str, str]

COMPANY_FORM_FIELDS: list[CompanyFieldSpec] = [
    ("production_oz", "Production (oz)", "number"),
    ("aisc_usd_per_oz", "AISC (USD/oz)", "number"),
    ("cash_cost_usd_per_oz", "Cash Cost (USD/oz)", "number"),
    ("royalty_rate", "Royalty Rate (%)", "number"),
    ("sustaining_capex_musd", "Sustaining Capex (M USD)", "number"),
    ("da_musd", "D&A (M USD)", "number"),
    ("interest_expense_musd", "Interest Expense (M USD)", "number"),
    ("tax_rate", "Tax Rate (%)", "number"),
    ("reserve_life_years", "Reserve Life (Years)", "number"),
    ("net_debt_musd", "Net Debt (M USD)", "number"),
    ("ebitda_ltm_musd", "EBITDA LTM (M USD)", "number"),
]

REPORTING_FORM_FIELDS: list[ReportingFieldSpec] = [
    ("next_financial_report_date", "Next Financial Report Date"),
    ("next_production_report_date", "Next Production Report Date"),
    ("notes", "Reporting Notes"),
]


def _render_company_form(
    *,
    ticker: str,
    company_row: dict[str, Any],
    verification_rows: list[dict[str, Any]] | None = None,
    return_to: str | None = None,
) -> str:
    verification_status_by_field = {
        str(row.get("field_name") or "").strip(): str(row.get("verification_status") or "").strip().upper()
        for row in (verification_rows or [])
        if row.get("field_name")
    }

    total_fields = len(COMPANY_FORM_FIELDS)
    present_count = 0
    verified_count = 0
    estimated_count = 0
    incomplete_verifications = 0
    missing_fields: list[str] = []

    fields_html: list[str] = []
    for field_name, label, input_type in COMPANY_FORM_FIELDS:
        raw_value = company_row.get(field_name)
        value = _format_form_value(field_name, raw_value)
        step_attr = " step=\"0.01\"" if input_type == "number" else ""
        is_present = bool(value.strip())
        clear_checkbox_html = (
            f"<label class=\"clear-toggle\">"
            f"<input type=\"checkbox\" name=\"clear_{escape(field_name)}\" value=\"1\"> Clear on save"
            f"</label>"
            if is_present
            else ""
        )
        verification_status = verification_status_by_field.get(field_name, "")
        # Badge derivation, per plan v3 §1B.2 ("visibility of verified vs estimated vs incomplete"):
        # - present + VERIFIED → VERIFIED
        # - present + ESTIMATED → ESTIMATED
        # - present + INCOMPLETE (explicit) → INCOMPLETE
        # - present + (no verification row yet) → NEEDS VERIFICATION
        # - missing value altogether → MISSING
        if not is_present:
            badge_text, badge_class = "MISSING", "badge-missing"
            missing_fields.append(field_name)
        elif verification_status == "VERIFIED":
            badge_text, badge_class = "VERIFIED", "badge-verified"
            verified_count += 1
        elif verification_status == "ESTIMATED":
            badge_text, badge_class = "ESTIMATED", "badge-estimated"
            estimated_count += 1
        elif verification_status == "INCOMPLETE":
            badge_text, badge_class = "INCOMPLETE", "badge-incomplete"
            incomplete_verifications += 1
        else:
            badge_text, badge_class = "NEEDS VERIFICATION", "badge-needs"
        if is_present:
            present_count += 1
        fields_html.append(
            "<label>"
            f"<span>{escape(label)} <em class=\"badge {badge_class}\">{badge_text}</em></span>"
            f"<input name=\"{escape(field_name)}\" type=\"{escape(input_type)}\" value=\"{escape(value)}\"{step_attr}>"
            f"{clear_checkbox_html}"
            "</label>"
        )

    updated_at = _fmt_text(company_row.get("updated_at_utc"))
    missing_summary = (
        f"<span class=\"hint\">Missing: {escape(', '.join(missing_fields))}.</span>"
        if missing_fields
        else "<span class=\"hint\">All required fields populated.</span>"
    )
    clear_hint = (
        "<p class=\"hint\">Blank numeric fields are left unchanged on save. "
        "To clear a value, tick the <em>Clear on save</em> checkbox under that field. "
        "(The CLI <code>--clear-fields</code> path remains available for batch use.)</p>"
    )
    return (
        "<section class=\"panel\">"
        "<h2>Company Inputs</h2>"
        f"<p><strong>Last Updated:</strong> {updated_at}</p>"
        f"<p class=\"tool-b-readiness\">"
        f"<strong>Corporate Finance readiness:</strong> {present_count}/{total_fields} fields populated · "
        f"{verified_count} verified · {estimated_count} estimated · "
        f"{incomplete_verifications} explicitly incomplete · "
        f"{len(missing_fields)} missing. {missing_summary}"
        "</p>"
        f"{clear_hint}"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/company\" class=\"form-grid\">"
        f"{_return_to_input(return_to)}"
        f"{''.join(fields_html)}"
        "<div class=\"form-actions\"><button type=\"submit\">Save Company Inputs</button></div>"
        "</form>"
        "</section>"
    )


def _render_reporting_form(
    *,
    ticker: str,
    reporting_row: dict[str, Any],
    return_to: str | None = None,
) -> str:
    fields_html = [
        "<label>"
        f"<span>{escape(label)}</span>"
        f"<input name=\"{escape(field_name)}\" type=\"date\" value=\"{escape(_format_form_value(field_name, reporting_row.get(field_name)))}\">"
        "</label>"
        for field_name, label in REPORTING_FORM_FIELDS[:2]
    ]
    fields_html.append(
        "<label class=\"full-width\">"
        "<span>Reporting Notes</span>"
        f"<textarea name=\"notes\" rows=\"3\">{escape(_format_form_value('notes', reporting_row.get('notes')))}</textarea>"
        "</label>"
    )
    updated_at = _fmt_text(reporting_row.get("updated_at_utc"))
    return (
        "<section class=\"panel\">"
        "<h2>Reporting Calendar</h2>"
        f"<p><strong>Last Updated:</strong> {updated_at}</p>"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/reporting\" class=\"form-grid\">"
        f"{_return_to_input(return_to)}"
        f"{''.join(fields_html)}"
        "<div class=\"form-actions\"><button type=\"submit\">Save Reporting Calendar</button></div>"
        "</form>"
        "</section>"
    )


def _render_verification_section(
    *,
    ticker: str,
    verification_rows: list[dict[str, Any]],
    return_to: str | None = None,
) -> str:
    """Editable source-verification section.

    Iterates the canonical REQUIRED_MANUAL_FIELDS list so every Tool B field
    shows a row whether or not a verification record exists yet. Each row
    carries its own inline form that POSTs to /ticker/<T>/verification.
    Optional source_date / source_url / notes use blank-as-no-op semantics:
    empty inputs are not sent to the upsert API, so existing values are not
    nulled out. To clear an existing optional value, tick the per-field
    "Clear" checkbox before saving (Fix #3, post-deep-review).
    """

    existing_by_field = {
        str(row.get("field_name") or "").strip(): row
        for row in verification_rows
        if row.get("field_name")
    }

    rows_html: list[str] = []
    for field_name in REQUIRED_MANUAL_FIELDS:
        row = existing_by_field.get(field_name, {})
        status = _fmt_text(row.get("verification_status"))
        source_date = _format_form_value("source_date", row.get("source_date"))
        source_url = _format_form_value("source_url", row.get("source_url"))
        notes = _format_form_value("notes", row.get("notes"))
        updated = _fmt_text(row.get("updated_at_utc"))
        existing_status = str(row.get("verification_status") or "").strip().upper()
        # If no verification record exists yet, render a disabled placeholder
        # as the first <option> so browsers don't visually pre-select VERIFIED
        # (codex P1 trust-bug fix). The `required` attribute on the <select>
        # then forces the user to pick a real status before saving.
        options_parts: list[str] = []
        if not existing_status:
            options_parts.append(
                "<option value=\"\" disabled selected hidden>Choose status</option>"
            )
        for option in VERIFICATION_STATUS_OPTIONS:
            selected = " selected" if option == existing_status else ""
            options_parts.append(f"<option value=\"{option}\"{selected}>{option}</option>")
        options_html = "".join(options_parts)
        label = _humanize_column_name(field_name)
        # Per-field clear checkboxes appear only when there's a current value to clear.
        date_clear_html = (
            "<label class=\"clear-toggle\"><input type=\"checkbox\" name=\"clear_source_date\" value=\"1\"> Clear</label>"
            if source_date
            else ""
        )
        url_clear_html = (
            "<label class=\"clear-toggle\"><input type=\"checkbox\" name=\"clear_source_url\" value=\"1\"> Clear</label>"
            if source_url
            else ""
        )
        notes_clear_html = (
            "<label class=\"clear-toggle\"><input type=\"checkbox\" name=\"clear_notes\" value=\"1\"> Clear</label>"
            if notes
            else ""
        )
        # Collapse each field's edit form behind a <details> so the panel is a compact
        # one-row-per-field table by default (Field · Status · Edit), expanding to the full
        # form only on click. Keeps every edit affordance while reclaiming the vertical space.
        # `updated` is already HTML-escaped by _fmt_text — do not escape twice.
        updated_summary = (
            f"<span class=\"hint\"> · updated {updated}</span>"
            if updated and updated != "-"
            else ""
        )
        rows_html.append(
            "<tr>"
            f"<td>{escape(label)}<br><span class=\"hint\">{escape(field_name)}</span></td>"
            f"<td>{status}</td>"
            f"<td>"
            f"<details class=\"verification-edit\">"
            f"<summary>Edit{updated_summary}</summary>"
            f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/verification\" class=\"verification-form\">"
            f"{_return_to_input(return_to)}"
            f"<input type=\"hidden\" name=\"field_name\" value=\"{escape(field_name)}\">"
            f"<label class=\"verification-cell\"><span>Status</span>"
            f"<select name=\"verification_status\" required>{options_html}</select></label>"
            f"<label class=\"verification-cell\"><span>Source Date</span>"
            f"<input name=\"source_date\" type=\"date\" value=\"{escape(source_date)}\">{date_clear_html}</label>"
            f"<label class=\"verification-cell\"><span>Source URL</span>"
            f"<input name=\"source_url\" type=\"url\" value=\"{escape(source_url)}\">{url_clear_html}</label>"
            f"<label class=\"verification-cell full-width\"><span>Notes</span>"
            f"<textarea name=\"notes\" rows=\"2\">{escape(notes)}</textarea>{notes_clear_html}</label>"
            f"<div class=\"verification-actions\">"
            f"<button type=\"submit\">Save</button>"
            f"</div>"
            f"</form>"
            f"</details>"
            f"</td>"
            "</tr>"
        )

    hint = (
        "<p class=\"hint\">One row per required Corporate Finance field. Blank Source Date / URL / Notes are left unchanged on save. "
        "To clear an existing value, tick the <em>Clear</em> checkbox under that field before saving.</p>"
    )
    return (
        "<section class=\"panel\">"
        "<h2>Source Verification</h2>"
        f"{hint}"
        "<table class=\"verification-table\">"
        "<thead><tr><th>Field</th><th>Current Status</th><th>Edit</th></tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
        "</section>"
    )


def _render_note_section(
    *,
    ticker: str,
    note_rows: list[dict[str, Any]],
    return_to: str | None = None,
) -> str:
    open_count = sum(1 for r in note_rows if str(r.get("note_status") or "").upper() == "OPEN")
    watch_count = sum(1 for r in note_rows if str(r.get("note_status") or "").upper() == "WATCH")
    done_count = sum(1 for r in note_rows if str(r.get("note_status") or "").upper() == "DONE")
    summary = (
        f"<p class=\"hint\">{len(note_rows)} note(s) total · "
        f"{open_count} open · {watch_count} watch · {done_count} done. "
        f"Use <code>python main.py manual-note list --ticker {escape(ticker)}</code> for the full history.</p>"
    )

    if not note_rows:
        note_table = "<p>No stock notes yet.</p>"
    else:
        # Sort: OPEN first, then WATCH, then DONE; within a status, newest first.
        status_order = {"OPEN": 0, "WATCH": 1, "DONE": 2}

        def _sort_key(r: dict[str, Any]) -> tuple[int, str]:
            return (
                status_order.get(str(r.get("note_status") or "").upper(), 3),
                str(r.get("updated_at_utc") or ""),
            )

        sorted_rows = sorted(note_rows, key=_sort_key)
        sorted_rows.reverse()  # newest first within each bucket
        # Then reorder by status_order ascending while preserving newest-first inside.
        sorted_rows = sorted(
            sorted_rows,
            key=lambda r: status_order.get(str(r.get("note_status") or "").upper(), 3),
        )

        note_table = (
            "<table class=\"note-table\">"
            "<thead><tr><th>Status</th><th>Tag</th><th>Note</th><th>Updated</th></tr></thead>"
            "<tbody>"
            + "".join(
                "<tr>"
                f"<td><span class=\"badge note-badge note-{escape(str(row.get('note_status') or 'OPEN').lower())}\">"
                f"{_fmt_text(row.get('note_status'))}</span></td>"
                f"<td>{_fmt_note_tag(row.get('note_tag'))}</td>"
                f"<td class=\"note-text\">{_fmt_text(row.get('note_text'))}</td>"
                f"<td>{_fmt_text(row.get('updated_at_utc'))}</td>"
                "</tr>"
                for row in sorted_rows
            )
            + "</tbody></table>"
        )
    return (
        "<section class=\"panel\">"
        "<h2>Stock Notes</h2>"
        f"{summary}"
        f"{note_table}"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/note\" class=\"note-form\">"
        f"{_return_to_input(return_to)}"
        "<label class=\"full-width\"><span>Note</span><textarea name=\"note_text\" rows=\"3\" required></textarea></label>"
        "<label><span>Tag</span><input name=\"note_tag\" type=\"text\" placeholder=\"e.g. FOLLOW_UP\"></label>"
        "<label><span>Status</span>"
        "<select name=\"note_status\">"
        + "".join(
            f"<option value=\"{option}\">{option}</option>" for option in NOTE_STATUS_OPTIONS
        )
        + "</select></label>"
        "<div class=\"form-actions\"><button type=\"submit\">Add Note</button></div>"
        "</form>"
        "</section>"
    )


def _return_to_input(return_to: str | None) -> str:
    value = str(return_to or "").strip()
    if not value:
        return ""
    return f"<input type=\"hidden\" name=\"return_to\" value=\"{escape(value, quote=True)}\">"
