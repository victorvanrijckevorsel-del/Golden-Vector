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
from golden_vector.serve.detail_forms import (
    COMPANY_FORM_FIELDS,
    _render_company_form,
    _render_note_section,
    _render_reporting_form,
    _render_verification_section,
)
from golden_vector.serve.lenses import DEFAULT_LENS_ID
from golden_vector.serve.overview_combined import _render_overview_page
from golden_vector.serve.overview_tool_a import _render_tool_a_overview_page
from golden_vector.serve.overview_tool_b import _render_tool_b_overview_page
from golden_vector.serve.format_helpers import (
    _coerce_form_numeric,
    _coerce_form_text,
    _frame_index_by_ticker,
    _ticker_rows,
)
from golden_vector.screening.manual_store import (
    add_stock_note,
    upsert_company_input,
    upsert_reporting_calendar,
    upsert_source_verification,
)









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
