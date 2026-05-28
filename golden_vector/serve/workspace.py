"""Thin local workspace UI for Tool B manual inputs and structural Tool A outputs."""

from __future__ import annotations

from html import escape
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server



from golden_vector.serve.screening_overrides import (
    ScreeningOverrideError,
    ScreeningOverrides,
    parse_query_overrides,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.screening.manual_data import (
    REQUIRED_MANUAL_FIELDS,
)
from golden_vector.serve.workspace_state import (
    OverviewFilters,
    ToolADetailState,
    WorkspaceState,
    _load_tool_a_detail,
    _load_workspace_state,
    _parse_ticker_route,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.http_helpers import (
    _flash_message,
    _html_response,
    _read_form_data,
    _redirect_response,
    _render_error_page,
    _serve_static_file,
)
from golden_vector.serve.detail_panels import (
    _canonical_anchor_window,
    _detail_alignment,
    _render_latest_panels,
    _render_window_switcher,
    _resolve_active_window,
    _resolve_visible_windows,
)
from golden_vector.serve.lenses import DEFAULT_LENS_ID
from golden_vector.serve.overview_combined import _render_overview_page
from golden_vector.serve.overview_tool_a import _render_tool_a_overview_page
from golden_vector.serve.overview_tool_b import _render_tool_b_overview_page
from golden_vector.serve.format_helpers import (
    _coerce_form_numeric,
    _coerce_form_text,
    _fmt_note_tag,
    _fmt_text,
    _format_form_value,
    _frame_index_by_ticker,
    _humanize_column_name,
    _ticker_rows,
)
from golden_vector.screening.manual_store import (
    add_stock_note,
    upsert_company_input,
    upsert_reporting_calendar,
    upsert_source_verification,
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



def create_workspace_app(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    tool_b_tickers: list[str],
) -> Callable[..., Iterable[bytes]]:
    normalized_tickers = sorted(
        {
            str(ticker).strip().upper()
            for ticker in tool_b_tickers
            if str(ticker).strip()
        }
    )
    allowed_tickers = set(normalized_tickers)

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = str(environ.get("PATH_INFO", "/")) or "/"

        try:
            if method == "GET" and path.startswith("/static/"):
                return _serve_static_file(path, start_response)

            if method == "GET" and path in ("/", "/combined"):
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                overview_filters = OverviewFilters(
                    search=query.get("search", [""])[0],
                    profile=query.get("profile", [""])[0],
                    verdict=query.get("verdict", [""])[0],
                    confidence=query.get("confidence", [""])[0],
                    sort=query.get("sort", [""])[0],
                )
                lens_id = query.get("lens", [""])[0] or DEFAULT_LENS_ID
                return _html_response(
                    start_response,
                    _render_overview_page(
                        state,
                        flash=flash,
                        filters=overview_filters,
                        lens_id=lens_id,
                        scoring_config=app_config.scoring,
                    ),
                )

            if method == "GET" and path == "/tool-a":
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                return _html_response(
                    start_response,
                    _render_tool_a_overview_page(
                        state,
                        flash=flash,
                        search=query.get("search", [""])[0],
                    ),
                )

            if method == "GET" and path == "/tool-b":
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                try:
                    overrides = parse_query_overrides(query)
                except ScreeningOverrideError as exc:
                    return _html_response(
                        start_response,
                        _render_tool_b_overview_page(
                            state,
                            flash=None,
                            search=query.get("search", [""])[0],
                            app_config=app_config,
                            paths=paths,
                            overrides=ScreeningOverrides(),
                            override_error=str(exc),
                        ),
                        status="400 Bad Request",
                    )
                return _html_response(
                    start_response,
                    _render_tool_b_overview_page(
                        state,
                        flash=flash,
                        search=query.get("search", [""])[0],
                        app_config=app_config,
                        paths=paths,
                        overrides=overrides,
                    ),
                )

            if path.startswith("/ticker/"):
                ticker, action = _parse_ticker_route(path)
                if ticker not in allowed_tickers:
                    return _html_response(
                        start_response,
                        _render_error_page(f"{ticker} is not an active Tool B ticker."),
                        status="404 Not Found",
                    )

                if method == "GET" and action is None:
                    state = _load_workspace_state(paths, normalized_tickers)
                    tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker)
                    query = parse_qs(str(environ.get("QUERY_STRING", "")))
                    flash = _flash_message(query.get("saved", [""])[0])
                    # Resolve the active structural window for this page
                    # render. Defaults to the ticker's canonical anchor.
                    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
                    canonical_anchor = _canonical_anchor_window(tool_a_row)
                    active_window = _resolve_active_window(
                        query.get("window", [""])[0], canonical_anchor,
                    )
                    visible_windows = _resolve_visible_windows(
                        query.get("show", [""])[0], active_window,
                    )
                    return _html_response(
                        start_response,
                        _render_ticker_page(
                            state,
                            ticker=ticker,
                            tool_a_detail=tool_a_detail,
                            flash=flash,
                            active_window=active_window,
                            canonical_anchor=canonical_anchor,
                            visible_windows=visible_windows,
                            app_config=app_config,
                        ),
                    )

                if method == "POST":
                    form_data = _read_form_data(environ)

                    if action == "company":
                        try:
                            company_values: dict[str, object] = {}
                            for field_name, _, _ in COMPANY_FORM_FIELDS:
                                # An explicit "clear this field" checkbox always wins
                                # over the typed value. Empty inputs are still skipped
                                # (blank-as-no-op), so the user has two clear paths:
                                # leave alone (blank), or clear (checkbox).
                                if str(form_data.get(f"clear_{field_name}", [""])[0]).strip():
                                    company_values[field_name] = None
                                    continue
                                raw_value = str(form_data.get(field_name, [""])[0]).strip()
                                if not raw_value:
                                    continue
                                company_values[field_name] = _coerce_form_numeric(raw_value)
                            if not company_values:
                                return _redirect_response(
                                    start_response,
                                    f"/ticker/{ticker}?saved=company",
                                )
                            upsert_company_input(paths, ticker=ticker, values=company_values)
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker)
                            return _html_response(
                                start_response,
                                _render_ticker_page(
                                    state,
                                    ticker=ticker,
                                    tool_a_detail=tool_a_detail,
                                    flash=None,
                                    error=str(exc),
                                ),
                                status="400 Bad Request",
                            )
                        return _redirect_response(
                            start_response,
                            f"/ticker/{ticker}?saved=company",
                        )

                    if action == "reporting":
                        try:
                            reporting_values = {
                                "next_financial_report_date": _coerce_form_text(
                                    form_data.get("next_financial_report_date", [""])[0]
                                ),
                                "next_production_report_date": _coerce_form_text(
                                    form_data.get("next_production_report_date", [""])[0]
                                ),
                                "notes": _coerce_form_text(
                                    form_data.get("notes", [""])[0]
                                ),
                            }
                            upsert_reporting_calendar(
                                paths,
                                ticker=ticker,
                                values=reporting_values,
                            )
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker)
                            return _html_response(
                                start_response,
                                _render_ticker_page(
                                    state,
                                    ticker=ticker,
                                    tool_a_detail=tool_a_detail,
                                    flash=None,
                                    error=str(exc),
                                ),
                                status="400 Bad Request",
                            )
                        return _redirect_response(
                            start_response,
                            f"/ticker/{ticker}?saved=reporting",
                        )

                    if action == "verification":
                        try:
                            field_name = str(form_data.get("field_name", [""])[0]).strip()
                            if field_name not in REQUIRED_MANUAL_FIELDS:
                                raise ValueError(
                                    f"Unsupported verification field_name: {field_name or '<blank>'}"
                                )
                            verification_status = str(
                                form_data.get("verification_status", [""])[0]
                            ).strip().upper()
                            # Only include optional fields when the user actually typed
                            # something — matches the null-on-blank guard used for the
                            # company and reporting forms.
                            verification_values: dict[str, object] = {}
                            for optional_field in ("source_date", "source_url", "notes"):
                                # Same blank-as-no-op + explicit-clear pattern as the
                                # company form. The checkbox forces a None even when
                                # the input has a value typed in, so the user can
                                # clear from the workspace without dropping to CLI.
                                if str(form_data.get(f"clear_{optional_field}", [""])[0]).strip():
                                    verification_values[optional_field] = None
                                    continue
                                raw_value = str(form_data.get(optional_field, [""])[0]).strip()
                                if raw_value:
                                    verification_values[optional_field] = raw_value
                            upsert_source_verification(
                                paths,
                                ticker=ticker,
                                field_name=field_name,
                                verification_status=verification_status,
                                values=verification_values,
                            )
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker)
                            return _html_response(
                                start_response,
                                _render_ticker_page(
                                    state,
                                    ticker=ticker,
                                    tool_a_detail=tool_a_detail,
                                    flash=None,
                                    error=str(exc),
                                ),
                                status="400 Bad Request",
                            )
                        return _redirect_response(
                            start_response,
                            f"/ticker/{ticker}?saved=verification",
                        )

                    if action == "note":
                        try:
                            add_stock_note(
                                paths,
                                ticker=ticker,
                                note_text=str(form_data.get("note_text", [""])[0]),
                                note_tag=_coerce_form_text(
                                    form_data.get("note_tag", [""])[0]
                                ),
                                note_status=str(
                                    form_data.get("note_status", ["OPEN"])[0] or "OPEN"
                                ).upper(),
                            )
                        except ValueError as exc:
                            state = _load_workspace_state(paths, normalized_tickers)
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker)
                            return _html_response(
                                start_response,
                                _render_ticker_page(
                                    state,
                                    ticker=ticker,
                                    tool_a_detail=tool_a_detail,
                                    flash=None,
                                    error=str(exc),
                                ),
                                status="400 Bad Request",
                            )
                        return _redirect_response(
                            start_response,
                            f"/ticker/{ticker}?saved=note",
                        )

                return _html_response(
                    start_response,
                    _render_error_page("Unsupported workspace route."),
                    status="404 Not Found",
                )

            return _html_response(
                start_response,
                _render_error_page("Page not found."),
                status="404 Not Found",
            )
        except Exception as exc:
            return _html_response(
                start_response,
                _render_error_page(
                    "The workspace hit an unexpected error.",
                    detail=str(exc),
                ),
                status="500 Internal Server Error",
            )

    return app


def run_workspace_server(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    tool_b_tickers: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
) -> int:
    app = create_workspace_app(
        paths,
        app_config=app_config,
        tool_b_tickers=tool_b_tickers,
    )
    with make_server(host, port, app) as server:
        print(f"Golden Vector workspace running at http://{host}:{port}")
        print("Press Ctrl+C to stop.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("Golden Vector workspace stopped.")
    return 0




























def _render_ticker_page(
    state: WorkspaceState,
    *,
    ticker: str,
    tool_a_detail: ToolADetailState,
    flash: str | None,
    error: str | None = None,
    active_window: str = "12M",
    canonical_anchor: str = "12M",
    visible_windows: list[str] | None = None,
    app_config: AppConfig | None = None,
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    verification_rows = _ticker_rows(state.source_verification, ticker)
    note_rows = _ticker_rows(state.stock_notes, ticker)
    if visible_windows is None:
        visible_windows = [active_window]

    body = [f"<p><a href=\"/\">Back to workspace</a></p>", f"<h1>{escape(ticker)}</h1>"]
    body.append(_render_window_switcher(ticker=ticker, active=active_window, canonical=canonical_anchor))
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if error:
        body.append(f"<div class=\"flash\">{escape(error)}</div>")
    alignment = _detail_alignment(tool_a_row, state.foundation_manifest)
    body.append(
        _render_latest_panels(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_b_row=tool_b_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            visible_windows=visible_windows,
            app_config=app_config,
        )
    )
    body.append(
        _render_company_form(
            ticker=ticker,
            company_row=company_row,
            verification_rows=verification_rows,
        )
    )
    body.append(_render_reporting_form(ticker=ticker, reporting_row=reporting_row))
    body.append(_render_verification_section(ticker=ticker, verification_rows=verification_rows))
    body.append(_render_note_section(ticker=ticker, note_rows=note_rows))
    return _page_shell(f"Golden Vector Workspace - {ticker}", "".join(body), active_nav="combined")

























































def _render_company_form(
    *,
    ticker: str,
    company_row: dict[str, Any],
    verification_rows: list[dict[str, Any]] | None = None,
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
        f"<strong>Tool B readiness:</strong> {present_count}/{total_fields} fields populated · "
        f"{verified_count} verified · {estimated_count} estimated · "
        f"{incomplete_verifications} explicitly incomplete · "
        f"{len(missing_fields)} missing. {missing_summary}"
        "</p>"
        f"{clear_hint}"
        f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/company\" class=\"form-grid\">"
        f"{''.join(fields_html)}"
        "<div class=\"form-actions\"><button type=\"submit\">Save Company Inputs</button></div>"
        "</form>"
        "</section>"
    )


def _render_reporting_form(*, ticker: str, reporting_row: dict[str, Any]) -> str:
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
        f"{''.join(fields_html)}"
        "<div class=\"form-actions\"><button type=\"submit\">Save Reporting Calendar</button></div>"
        "</form>"
        "</section>"
    )


def _render_verification_section(
    *,
    ticker: str,
    verification_rows: list[dict[str, Any]],
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
        rows_html.append(
            "<tr>"
            f"<td>{escape(label)}<br><span class=\"hint\">{escape(field_name)}</span></td>"
            f"<td>{status}</td>"
            f"<td>"
            f"<form method=\"post\" action=\"/ticker/{escape(ticker)}/verification\" class=\"verification-form\">"
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
            f"<span class=\"hint\">Last updated: {updated}</span>"
            f"<button type=\"submit\">Save</button>"
            f"</div>"
            f"</form>"
            f"</td>"
            "</tr>"
        )

    hint = (
        "<p class=\"hint\">One row per required Tool B field. Blank Source Date / URL / Notes are left unchanged on save. "
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


def _render_note_section(*, ticker: str, note_rows: list[dict[str, Any]]) -> str:
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
