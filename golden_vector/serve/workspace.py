"""Thin local workspace UI for Tool B manual inputs and structural Tool A outputs."""

from __future__ import annotations

import ipaddress
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, unquote
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
from golden_vector.screening.schema import ToolBStaleSchemaError
from golden_vector.serve.workspace_state import (
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
    DETAIL_DEFAULT_LENS_ID,
    DETAIL_OPTION_TRADING_LENS_ID,
    render_detail_page,
    resolve_detail_lens,
)
from golden_vector.serve.option_trading_data import (
    OptionArtifactStaleSchemaError,
    build_option_trading_detail_data,
    load_option_trading_data,
    parse_option_sizing_request,
)
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    resolve_current_model_artifact_path,
)
from golden_vector.serve.option_refresh import (
    read_option_refresh_status,
    start_options_refresh,
)
from golden_vector.serve.candidate_finder_data import (
    CandidateFinderData,
    CandidateFinderScenarioError,
    CandidateFinderSourceError,
    load_candidate_finder_data,
    parse_candidate_finder_scenario,
)
from golden_vector.serve.candidate_finder_page import render_candidate_finder_page
from golden_vector.serve.lab_curve_data import (
    default_lab_horizon,
    load_dial_cells,
    load_ticker_curve,
)
from golden_vector.serve.lab_curve_page import _render_lab_curve_page
from golden_vector.serve.scorecard_data import load_scorecard_data
from golden_vector.serve.overview_lab import _render_lab_overview_page
from golden_vector.serve.overview_scorecard import _render_scorecard_page
from golden_vector.serve.overview_option_trading import _render_option_trading_overview_page
from golden_vector.serve.overview_tool_a import _render_tool_a_overview_page
from golden_vector.serve.overview_tool_b import _render_tool_b_overview_page
from golden_vector.serve.overview_tool_c import _render_tool_c_overview_page
from golden_vector.serve.overview_tool_d import _render_tool_d_overview_page
from golden_vector.serve.portfolio_page import (
    portfolio_form_payload,
    render_portfolio_page,
)
from golden_vector.serve.format_helpers import (
    _coerce_form_numeric,
    _coerce_form_text,
    _frame_index_by_ticker,
)
from golden_vector.portfolio.manual_store import add_lot, delete_lot, edit_lot
from golden_vector.portfolio.models import PortfolioError, PortfolioStaleSchemaError
from golden_vector.portfolio.pipeline import build_portfolio_artifacts, build_ticker_info
from golden_vector.portfolio.reader import load_portfolio_data
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

    def _candidate_finder_data_for_query(
        query: dict[str, list[str]],
    ) -> CandidateFinderData:
        scenario = parse_candidate_finder_scenario(query)
        if scenario is None:
            return load_candidate_finder_data(paths, app_config=app_config)
        return load_candidate_finder_data(
            paths,
            app_config=app_config,
            scenario=scenario,
        )

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
                if not app_config.portfolio.enabled:
                    return _html_response(
                        start_response,
                        _render_error_page(
                            "Portfolio downloads are disabled.",
                            detail="Enable portfolio.enabled locally before serving holdings-bearing reports.",
                        ),
                        status="403 Forbidden",
                    )
                return _download_file_response(
                    start_response,
                    paths.output_hedge_readiness_dir / "latest.md",
                    content_type="text/markdown; charset=utf-8",
                    download_name="golden-vector-hedge-readiness-latest.md",
                )

            if method == "GET" and path == "/portfolio":
                if not app_config.portfolio.enabled:
                    return _html_response(
                        start_response,
                        _render_error_page(
                            "Portfolio is disabled.",
                            detail="Enable portfolio.enabled locally before serving holdings-bearing pages.",
                        ),
                        status="403 Forbidden",
                    )
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                return _html_response(
                    start_response,
                    render_portfolio_page(
                        paths=paths,
                        app_config=app_config,
                        flash=flash,
                    ),
                )

            if method == "GET" and path == "/portfolio/reconciliation.csv":
                if not app_config.portfolio.enabled:
                    return _html_response(
                        start_response,
                        _render_error_page(
                            "Portfolio downloads are disabled.",
                            detail="Enable portfolio.enabled locally before serving holdings-bearing exports.",
                        ),
                        status="403 Forbidden",
                    )
                reconciliation_csv_path = _portfolio_reconciliation_csv_path(paths)
                return _download_file_response(
                    start_response,
                    reconciliation_csv_path,
                    content_type="text/csv; charset=utf-8",
                    download_name="golden-vector-portfolio-reconciliation.csv",
                )

            if path.startswith("/portfolio/lots"):
                if not app_config.portfolio.enabled:
                    return _html_response(
                        start_response,
                        _render_error_page(
                            "Portfolio is disabled.",
                            detail="Enable portfolio.enabled locally before editing positions.",
                        ),
                        status="403 Forbidden",
                    )
                if method != "POST":
                    return _html_response(
                        start_response,
                        _render_error_page("Unsupported portfolio route."),
                        status="404 Not Found",
                    )
                try:
                    form_data = _read_form_data(environ)
                    ticker_info = build_ticker_info(app_config)
                    if path == "/portfolio/lots":
                        add_lot(
                            paths,
                            portfolio_form_payload(form_data),
                            ticker_info=ticker_info,
                        )
                    elif path.endswith("/edit"):
                        lot_id = path.removeprefix("/portfolio/lots/").removesuffix("/edit")
                        edit_lot(
                            paths,
                            lot_id,
                            portfolio_form_payload(form_data),
                            ticker_info=ticker_info,
                        )
                    elif path.endswith("/delete"):
                        lot_id = path.removeprefix("/portfolio/lots/").removesuffix("/delete")
                        delete_lot(paths, lot_id)
                    else:
                        return _html_response(
                            start_response,
                            _render_error_page("Unsupported portfolio route."),
                            status="404 Not Found",
                        )
                    build_portfolio_artifacts(
                        paths=paths,
                        app_config=app_config,
                    )
                except (PortfolioError, FileNotFoundError, ValueError) as exc:
                    return _html_response(
                        start_response,
                        render_portfolio_page(
                            paths=paths,
                            app_config=app_config,
                            error=str(exc),
                        ),
                        status="400 Bad Request",
                    )
                return _redirect_response(start_response, "/portfolio?saved=portfolio")

            if method == "POST" and path in ("/refresh", "/option-trading/refresh"):
                form_data = _read_form_data(environ)
                start_options_refresh(paths)
                default_return_to = "/" if path == "/refresh" else "/option-trading"
                return _redirect_response(
                    start_response,
                    _safe_return_to(
                        form_data.get("return_to", [default_return_to])[0],
                        fallback=default_return_to,
                    ),
                )

            if method == "GET" and path == "/":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                try:
                    candidate_data = _candidate_finder_data_for_query(query)
                except CandidateFinderScenarioError as exc:
                    return _html_response(
                        start_response,
                        _render_error_page(str(exc)),
                        status="400 Bad Request",
                    )
                return _html_response(
                    start_response,
                    render_candidate_finder_page(
                        candidate_data,
                        query=query,
                        base_path="/",
                        refresh_status=read_option_refresh_status(paths),
                        app_config=app_config,
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
                        window=query.get("window", [""])[0],
                        app_config=app_config,
                    ),
                )

            if method == "GET" and path == "/tool-b":
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                rank_by = query.get("rank_by", ["our_view"])[0]
                differences_only = _query_flag(query, "differences_only")
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
                            rank_by=rank_by,
                            differences_only=differences_only,
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
                        rank_by=rank_by,
                        differences_only=differences_only,
                    ),
                )

            if method == "GET" and path == "/tool-c":
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                return _html_response(
                    start_response,
                    _render_tool_c_overview_page(
                        state,
                        flash=flash,
                        search=query.get("search", [""])[0],
                        app_config=app_config,
                    ),
                )

            if method == "GET" and path == "/lab":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                requested_bucket = query.get("bucket", [""])[0] or None
                default_horizon = default_lab_horizon()
                try:
                    requested_horizon = int(query.get("horizon", [str(default_horizon)])[0])
                except (TypeError, ValueError):
                    requested_horizon = default_horizon
                lab_data = load_dial_cells(
                    paths, horizon=requested_horizon, bucket=requested_bucket
                )
                # The loader resolves the bucket (requested -> default -> first);
                # the page renders whatever it actually loaded. One resolver, no fork.
                return _html_response(
                    start_response,
                    _render_lab_overview_page(
                        lab_data,
                        selected_bucket=lab_data.selected_bucket,
                    ),
                )

            if method == "GET" and path.startswith("/lab/dial/"):
                ticker = unquote(path[len("/lab/dial/") :]).strip().upper()
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                scenario = query.get("scenario", ["gold_down"])[0] or "gold_down"
                benchmark = (query.get("benchmark", ["GDX"])[0] or "GDX").upper()
                default_horizon = default_lab_horizon()
                try:
                    horizon = int(query.get("horizon", [str(default_horizon)])[0])
                except (TypeError, ValueError):
                    horizon = default_horizon
                curve = load_ticker_curve(
                    paths,
                    ticker=ticker,
                    scenario_bucket=scenario,
                    horizon=horizon,
                    benchmark=benchmark,
                )
                return _html_response(
                    start_response,
                    _render_lab_curve_page(curve),
                )

            if method == "GET" and path == "/scorecard":
                return _html_response(
                    start_response,
                    _render_scorecard_page(load_scorecard_data(paths)),
                )

            if method == "GET" and path == "/tool-d":
                state = _load_workspace_state(paths, normalized_tickers)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                flash = _flash_message(query.get("saved", [""])[0])
                return _html_response(
                    start_response,
                    _render_tool_d_overview_page(
                        state,
                        flash=flash,
                        app_config=app_config,
                        paths=paths,
                        query=query,
                        search=query.get("search", [""])[0],
                    ),
                )

            if method == "GET" and path == "/option-trading":
                option_trading_data = load_option_trading_data(
                    paths,
                    app_config=app_config,
                )
                option_query = parse_qs(str(environ.get("QUERY_STRING", "")))
                return _html_response(
                    start_response,
                    _render_option_trading_overview_page(
                        option_trading_data.overview,
                        option_signal_summary=option_trading_data.option_signal_summary,
                        model_state_manifest=load_current_model_state_manifest(paths),
                        app_config=app_config,
                        option_horizon=(option_query.get("option_horizon", [None]) or [None])[0],
                    ),
                )

            if method == "GET" and path == "/candidate-finder":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                try:
                    candidate_data = _candidate_finder_data_for_query(query)
                except CandidateFinderScenarioError as exc:
                    return _html_response(
                        start_response,
                        _render_error_page(str(exc)),
                        status="400 Bad Request",
                    )
                return _html_response(
                    start_response,
                    render_candidate_finder_page(
                        candidate_data,
                        query=query,
                        base_path="/candidate-finder",
                        refresh_status=read_option_refresh_status(paths),
                        app_config=app_config,
                    ),
                )

            if path.startswith("/ticker/"):
                ticker, action = _parse_ticker_route(path)
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                detail_lens = (
                    resolve_detail_lens(query.get("lens", [""])[0])
                    if method == "GET" and action is None
                    else DETAIL_DEFAULT_LENS_ID
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
                            _render_error_page(f"{ticker} is not an active Corporate Finance ticker."),
                            status="404 Not Found",
                        )

                if method == "GET" and action is None:
                    state = _load_workspace_state(paths, normalized_tickers)
                    tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker, universe_tool_a=state.latest_tool_a)
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
                    if detail_lens == DETAIL_OPTION_TRADING_LENS_ID:
                        option_trading_data = (
                            prefetched_option_trading_data
                            or load_option_trading_data(
                                paths,
                                app_config=app_config,
                            )
                        )
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
                            show_workspace_panels=not option_vehicle_detail,
                            show_manual_sections=not option_vehicle_detail,
                            model_state_manifest=(
                                load_current_model_state_manifest(paths)
                                if detail_lens == DETAIL_OPTION_TRADING_LENS_ID
                                else None
                            ),
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
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker, universe_tool_a=state.latest_tool_a)
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
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker, universe_tool_a=state.latest_tool_a)
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
                            # something; matches the null-on-blank guard used for the
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
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker, universe_tool_a=state.latest_tool_a)
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
                            tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker, universe_tool_a=state.latest_tool_a)
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
        except OptionArtifactStaleSchemaError as exc:
            return _html_response(
                start_response,
                _render_error_page(
                    "Your local Option Trading data is from the previous version.",
                    detail=(
                        "Run python main.py refresh to rebuild the option artifacts "
                        f"and the current model-state manifest. Details: {exc}"
                    ),
                ),
                status="503 Service Unavailable",
            )
        except ToolBStaleSchemaError as exc:
            return _html_response(
                start_response,
                _render_error_page(
                    "Your local Corporate Finance data is from the previous version.",
                    detail=(
                        "Run python main.py refresh to rebuild Tool B, the option artifacts, "
                        f"and the current model-state manifest. Details: {exc}"
                    ),
                ),
                status="503 Service Unavailable",
            )
        except PortfolioStaleSchemaError as exc:
            return _html_response(
                start_response,
                _render_error_page(
                    "Your local Portfolio data is from the previous version.",
                    detail=(
                        "Run python main.py refresh, or save a portfolio lot again, "
                        f"to rebuild the portfolio artifacts. Details: {exc}"
                    ),
                ),
                status="503 Service Unavailable",
            )
        except CandidateFinderSourceError as exc:
            return _html_response(
                start_response,
                _render_error_page(
                    "A Candidate Finder data source is corrupt or unreadable.",
                    detail=(
                        "Run python main.py refresh to rebuild the tool artifacts and the "
                        f"current model-state manifest. Details: {exc}"
                    ),
                ),
                status="503 Service Unavailable",
            )
        except Exception:
            return _html_response(
                start_response,
                _render_error_page(
                    "The workspace hit an unexpected error.",
                    detail="Run the command again from a terminal to see the full traceback.",
                ),
                status="500 Internal Server Error",
            )

    return app


def _portfolio_reconciliation_csv_path(paths: ProjectPaths):
    load_portfolio_data(paths)
    path = resolve_current_model_artifact_path(
        paths,
        "portfolio_reconciliation_export_csv",
    )
    if path is None:
        raise PortfolioStaleSchemaError(
            "Portfolio reconciliation CSV is missing from the current model-state manifest. "
            "Run python main.py refresh, or save a portfolio lot again."
        )
    return path


def _safe_return_to(raw_value: object, *, fallback: str = "/option-trading") -> str:
    value = str(raw_value or "").strip()
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    return value


def _query_flag(query: dict[str, list[str]], name: str) -> bool:
    values = query.get(name, [])
    if not values:
        return False
    return str(values[0]).strip().lower() in {"1", "true", "yes", "on"}


def run_workspace_server(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    tool_b_tickers: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
) -> int:
    if app_config.portfolio.enabled and not _is_loopback_host(host):
        raise ValueError(
            "Portfolio is enabled, so the workspace must bind to localhost or another loopback address."
        )
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


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False
