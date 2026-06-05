"""Thin local workspace UI for Tool B manual inputs and structural Tool A outputs."""

from __future__ import annotations

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
    _load_tool_a_detail,
    _load_workspace_state,
    _parse_ticker_route,
)
from golden_vector.serve.http_helpers import (
    _download_file_response,
    _flash_message,
    _html_response,
    _no_content_response,
    _read_form_data,
    _redirect_response,
    _render_error_page,
    _serve_static_file,
)
from golden_vector.serve.detail_panels import (
    _canonical_anchor_window,
    _resolve_active_window,
    _resolve_visible_windows,
)
from golden_vector.serve.detail_forms import COMPANY_FORM_FIELDS
from golden_vector.serve.detail_page import (
    DETAIL_OPTION_TRADING_LENS_ID,
    render_detail_page,
    resolve_detail_lens,
)
from golden_vector.serve.lenses import DEFAULT_LENS_ID
from golden_vector.serve.option_trading_data import (
    build_option_trading_detail_data,
    load_option_trading_data,
    parse_option_sizing_request,
)
from golden_vector.app.model_state import load_current_model_state_manifest
from golden_vector.serve.option_refresh import (
    read_option_refresh_status,
    start_options_refresh,
)
from golden_vector.serve.candidate_finder_data import load_candidate_finder_data
from golden_vector.serve.candidate_finder_page import render_candidate_finder_page
from golden_vector.serve.overview_option_trading import _render_option_trading_overview_page
from golden_vector.serve.overview_combined import _render_overview_page
from golden_vector.serve.overview_tool_a import _render_tool_a_overview_page
from golden_vector.serve.overview_tool_b import _render_tool_b_overview_page
from golden_vector.serve.format_helpers import (
    _coerce_form_numeric,
    _coerce_form_text,
    _frame_index_by_ticker,
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

            if method == "GET" and path == "/favicon.ico":
                return _no_content_response(start_response)

            if method == "GET" and path == "/hedge-readiness":
                return _redirect_response(start_response, "/option-trading")

            if method == "GET" and path == "/hedge-readiness/latest.md":
                return _download_file_response(
                    start_response,
                    paths.output_hedge_readiness_dir / "latest.md",
                    content_type="text/markdown; charset=utf-8",
                    download_name="golden-vector-hedge-readiness-latest.md",
                )

            if method == "POST" and path == "/option-trading/refresh":
                form_data = _read_form_data(environ)
                start_options_refresh(paths)
                return _redirect_response(
                    start_response,
                    _safe_return_to(form_data.get("return_to", ["/option-trading"])[0]),
                )

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

            if method == "GET" and path == "/option-trading":
                option_trading_data = load_option_trading_data(
                    paths,
                    app_config=app_config,
                )
                refresh_status = read_option_refresh_status(paths)
                return _html_response(
                    start_response,
                    _render_option_trading_overview_page(
                        option_trading_data.overview,
                        refresh_status=refresh_status,
                        model_state_manifest=load_current_model_state_manifest(paths),
                    ),
                )

            if method == "GET" and path == "/candidate-finder":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                candidate_data = load_candidate_finder_data(
                    paths,
                    app_config=app_config,
                )
                return _html_response(
                    start_response,
                    render_candidate_finder_page(candidate_data, query=query),
                )

            if path.startswith("/ticker/"):
                ticker, action = _parse_ticker_route(path)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                detail_lens = (
                    resolve_detail_lens(query.get("lens", [""])[0])
                    if method == "GET" and action is None
                    else DEFAULT_LENS_ID
                )
                option_vehicle_detail = False
                prefetched_option_trading_data = None
                if ticker not in allowed_tickers:
                    if method == "GET" and action is None and detail_lens == DETAIL_OPTION_TRADING_LENS_ID:
                        prefetched_option_trading_data = load_option_trading_data(
                            paths,
                            app_config=app_config,
                        )
                        option_vehicle_row = next(
                            (
                                row
                                for row in prefetched_option_trading_data.overview.rows
                                if row.ticker == ticker
                                and row.option_vehicle_type == "benchmark_etf"
                            ),
                            None,
                        )
                        option_vehicle_detail = option_vehicle_row is not None
                    if not option_vehicle_detail:
                        return _html_response(
                            start_response,
                            _render_error_page(f"{ticker} is not an active Tool B ticker."),
                            status="404 Not Found",
                        )

                if method == "GET" and action is None:
                    state = _load_workspace_state(paths, normalized_tickers)
                    tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker)
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
                    option_trading_detail = None
                    option_refresh_status = None
                    if detail_lens == DETAIL_OPTION_TRADING_LENS_ID:
                        option_trading_data = (
                            prefetched_option_trading_data
                            or load_option_trading_data(
                                paths,
                                app_config=app_config,
                            )
                        )
                        option_refresh_status = read_option_refresh_status(paths)
                        option_trading_detail = build_option_trading_detail_data(
                            option_trading_data,
                            ticker=ticker,
                            app_config=app_config,
                            sizing_request=parse_option_sizing_request(
                                query,
                                app_config=app_config,
                            ),
                        )
                    return _html_response(
                        start_response,
                        render_detail_page(
                            state,
                            ticker=ticker,
                            tool_a_detail=tool_a_detail,
                            flash=flash,
                            active_window=active_window,
                            canonical_anchor=canonical_anchor,
                            visible_windows=visible_windows,
                            lens=detail_lens,
                            app_config=app_config,
                            option_trading_detail=option_trading_detail,
                            option_refresh_status=option_refresh_status,
                            show_workspace_panels=not option_vehicle_detail,
                            show_manual_sections=not option_vehicle_detail,
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
                                render_detail_page(
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
                                render_detail_page(
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
                                render_detail_page(
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
                                render_detail_page(
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


def _safe_return_to(raw_value: object) -> str:
    value = str(raw_value or "").strip()
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/option-trading"
    return value


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
