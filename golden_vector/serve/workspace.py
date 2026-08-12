"""Thin local workspace UI for Tool B manual inputs and structural Tool A outputs."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import replace
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urlsplit, urlunsplit
from wsgiref.simple_server import make_server

from golden_vector.serve.screening_overrides import (
    ScreeningOverrideError,
    ScreeningOverrides,
    parse_query_overrides,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.common.strings import normalize_ticker
from golden_vector.screening.manual_data import (
    REQUIRED_MANUAL_FIELDS,
)
from golden_vector.screening.pipeline import (
    materialize_tool_b_finance_source,
    normalize_finance_source,
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
)
from golden_vector.serve.detail_forms import COMPANY_FORM_FIELDS, REPORTING_FORM_FIELDS
from golden_vector.serve.ticker_page import load_ticker_page_data, parse_lab_request
from golden_vector.serve.detail_page import (
    DETAIL_DEFAULT_LENS_ID,
    DETAIL_OPTION_TRADING_LENS_ID,
    render_detail_page,
    resolve_detail_lens,
)
from golden_vector.serve.option_trading_data import (
    OPTION_PAGE_UNREADABLE,
    OptionArtifactIntegrityError,
    OptionArtifactStaleSchemaError,
    OptionPageArtifacts,
    build_option_trading_detail_data,
    load_option_page_artifacts,
    load_option_trading_data,
    parse_option_sizing_request,
)
from golden_vector.serve.ticker_page import TARGET_WINDOW_PARAM, resolve_target_window
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
from golden_vector.serve.url_helpers import build_page_url
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
from golden_vector.serve.fundamentals_provenance import (
    FundamentalsProvenance,
    load_fundamentals_provenance,
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


LOGGER = logging.getLogger(__name__)


def _first_query_values(query: dict[str, list[str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, values in query.items():
        if not values or values[0] is None:
            continue
        value = str(values[0])
        if str(key) == "lens" and value.strip().lower() != DETAIL_OPTION_TRADING_LENS_ID:
            continue
        result[str(key)] = value
    return result


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
        fundamentals_source = query.get("fundamentals_source", ["our"])[0]
        beta_window = query.get("beta_window", [""])[0]
        return load_candidate_finder_data(
            paths,
            app_config=app_config,
            scenario=scenario,
            fundamentals_source=fundamentals_source,
            beta_window=beta_window,
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
                start_result = start_options_refresh(paths)
                default_return_to = "/" if path == "/refresh" else "/option-trading"
                target = _safe_return_to(
                    form_data.get("return_to", [default_return_to])[0],
                    fallback=default_return_to,
                )
                if start_result.already_running:
                    # D9: signal the no-op; the landing page renders the notice.
                    parts = urlsplit(target)
                    params = dict(parse_qsl(parts.query, keep_blank_values=True))
                    params["refresh"] = "already-running"
                    target = urlunsplit(
                        (parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment)
                    )
                return _redirect_response(start_response, target)

            def _candidate_finder_response(
                query: dict[str, list[str]],
                base_path: str,
            ) -> list[bytes]:
                try:
                    candidate_data = _candidate_finder_data_for_query(query)
                except CandidateFinderScenarioError as exc:
                    # D6: parse failure re-renders the persisted screen at 400.
                    safe_query = {k: v for k, v in query.items() if k != "gold_price"}
                    candidate_data = _candidate_finder_data_for_query(safe_query)
                    return _html_response(
                        start_response,
                        render_candidate_finder_page(
                            candidate_data,
                            query=query,
                            base_path=base_path,
                            refresh_status=read_option_refresh_status(paths),
                            app_config=app_config,
                            error_message=str(exc),
                        ),
                        status="400 Bad Request",
                    )
                return _html_response(
                    start_response,
                    render_candidate_finder_page(
                        candidate_data,
                        query=query,
                        base_path=base_path,
                        refresh_status=read_option_refresh_status(paths),
                        app_config=app_config,
                    ),
                )

            if method == "GET" and path == "/":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                return _candidate_finder_response(query, "/")

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
                rank_by = query.get(
                    "fundamentals_source",
                    query.get("rank_by", ["our_view"]),
                )[0]
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
                        window=query.get("window", [""])[0],
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
                ticker = path[len("/lab/dial/") :].strip().upper()
                # Deep-review L3: mirror the /ticker/ gate — an unknown ticker
                # is a clean 404, not a real-looking "no data" dial page for
                # any arbitrary string.
                if ticker not in allowed_tickers:
                    return _html_response(
                        start_response,
                        _render_error_page("Page not found."),
                        status="404 Not Found",
                    )
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
                        refresh_already_running=(
                            (option_query.get("refresh", [""]) or [""])[0] == "already-running"
                        ),
                    ),
                )

            if method == "GET" and path == "/candidate-finder":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                return _candidate_finder_response(query, "/candidate-finder")

            if method == "GET" and path == "/ticker":
                query = parse_qs(str(environ.get("QUERY_STRING", "")))
                requested = normalize_ticker((query.get("ticker") or [""])[0])
                source = normalize_finance_source(
                    (query.get("fundamentals_source") or ["our"])[0]
                )
                if requested is None or requested not in allowed_tickers:
                    shown = requested or "That ticker"
                    # W7: honest 404, user language, and a way back to the page
                    # the jump form was submitted from (its hidden `from` field)
                    # with the active financials source preserved.
                    origin = normalize_ticker((query.get("from") or [""])[0])
                    origin_links: list[tuple[str, str]] = []
                    if origin is not None and origin in allowed_tickers:
                        origin_links.append(
                            (
                                build_page_url(
                                    f"/ticker/{quote(origin, safe='')}",
                                    {},
                                    set_params=(
                                        {"fundamentals_source": "yahoo"}
                                        if source == "yahoo"
                                        else {}
                                    ),
                                ),
                                f"Back to {origin}",
                            )
                        )
                    return _html_response(
                        start_response,
                        _render_error_page(
                            f"{shown} is not one of your tracked tickers.",
                            links=origin_links,
                        ),
                        status="404 Not Found",
                    )
                destination = f"/ticker/{quote(requested, safe='')}"
                if source == "yahoo":
                    destination += "?fundamentals_source=yahoo"
                return _redirect_response(start_response, destination)

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
                    configured_benchmarks = {
                        str(symbol).strip().upper()
                        for symbol in app_config.hedge_readiness.benchmark_tickers
                    }
                    if (
                        method == "GET"
                        and action is None
                        and detail_lens == DETAIL_OPTION_TRADING_LENS_ID
                        and ticker in configured_benchmarks
                    ):
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
                            # Same user language as the jump 404 (W7); a direct
                            # URL has no originating ticker page to return to.
                            _render_error_page(f"{ticker} is not one of your tracked tickers."),
                            status="404 Not Found",
                        )

                if method == "GET" and action is None:
                    state = _load_workspace_state(paths, normalized_tickers)
                    financials_source = normalize_finance_source(
                        query.get("fundamentals_source", ["our"])[0]
                    )
                    if financials_source == "yahoo":
                        state = replace(
                            state,
                            latest_tool_b=materialize_tool_b_finance_source(
                                state.latest_tool_b,
                                finance_source=financials_source,
                            ),
                        )
                    # ONE artifact read serving both consumers: the source
                    # tooltip's explanations and the data-quality table's
                    # statement period.
                    provenance = (
                        load_fundamentals_provenance(paths)
                        if financials_source == "yahoo"
                        else FundamentalsProvenance()
                    )
                    fundamentals_provenance = provenance.lookup
                    tool_a_detail = _load_tool_a_detail(paths, app_config=app_config, ticker=ticker, universe_tool_a=state.latest_tool_a)
                    flash = _flash_message(query.get("saved", [""])[0])
                    # Resolve the active structural window for this page
                    # render. Defaults to the ticker's canonical anchor.
                    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
                    canonical_anchor = _canonical_anchor_window(tool_a_row)
                    active_window = _resolve_active_window(
                        query.get("window", [""])[0], canonical_anchor,
                    )
                    # The Options section is part of the canonical page now, so
                    # option data loads for EVERY detail GET, not only under
                    # ?lens=option-trading. Both loaders are cached on the
                    # publish pointer, so this is one read per refresh.
                    (
                        option_trading_data,
                        option_trading_detail,
                        option_page_artifacts,
                    ) = _detail_option_state(
                        paths,
                        app_config=app_config,
                        ticker=ticker,
                        query=query,
                        prefetched=prefetched_option_trading_data,
                    )
                    ticker_page_data = load_ticker_page_data(paths)
                    return _html_response(
                        start_response,
                        render_detail_page(
                            state,
                            ticker=ticker,
                            tool_a_detail=tool_a_detail,
                            flash=flash,
                            active_window=active_window,
                            canonical_anchor=canonical_anchor,
                            lens=detail_lens,
                            ticker_page_data=ticker_page_data,
                            paths=paths,
                            lab_request=parse_lab_request(query, app_config=app_config),
                            chart_horizon=_resolve_chart_horizon(
                                query.get("chart_h", [""])[0], app_config
                            ),
                            chart_view=_resolve_chart_view(query.get("chart_view", [""])[0]),
                            app_config=app_config,
                            option_trading_detail=option_trading_detail,
                            option_page_artifacts=option_page_artifacts,
                            option_candidate_slots_frame=(
                                option_trading_data.candidate_slots_frame
                                if option_trading_data is not None
                                else None
                            ),
                            target_window=_resolve_target_window(
                                query.get(TARGET_WINDOW_PARAM, [""])[0],
                                app_config,
                            ),
                            show_workspace_panels=not option_vehicle_detail,
                            show_manual_sections=not option_vehicle_detail,
                            financials_source=financials_source,
                            query_params=_first_query_values(query),
                            fundamentals_provenance=fundamentals_provenance,
                            fundamentals_statement_periods=provenance.statement_periods,
                        ),
                    )

                if method == "POST":
                    form_data = _read_form_data(environ)

                    def _validation_error_response(
                        exc: ValueError,
                        *,
                        submitted: dict[str, list[str]],
                        section: str,
                    ):
                        """Re-render the detail page for a rejected form POST.

                        One copy of the error re-render for all four manual
                        sections: it resolves the SAME view state the GET
                        detail branch resolves (window / anchor / lens /
                        financials source / query params / provenance) so the
                        user lands back on the page they were actually on,
                        and echoes what they submitted instead of the stored
                        row. Option-lens prefetch work is deliberately skipped
                        — an error re-render never needs the option detail.
                        """
                        # Real browsers POST to the bare action URL, so the
                        # view state travels in the submitted hidden
                        # `return_to` field, not the POST query string. Merge
                        # both, with any explicit POST-URL query winning per
                        # key. Every merged value still passes through the
                        # normal validators below.
                        return_to_value = _safe_return_to(
                            (submitted.get("return_to") or [""])[0],
                            fallback=f"/ticker/{ticker}",
                        )
                        merged_query = dict(parse_qs(urlsplit(return_to_value).query))
                        merged_query.update(query)
                        error_state = _load_workspace_state(paths, normalized_tickers)
                        error_source = normalize_finance_source(
                            merged_query.get("fundamentals_source", ["our"])[0]
                        )
                        if error_source == "yahoo":
                            error_state = replace(
                                error_state,
                                latest_tool_b=materialize_tool_b_finance_source(
                                    error_state.latest_tool_b,
                                    finance_source=error_source,
                                ),
                            )
                        error_provenance = (
                            load_fundamentals_provenance(paths)
                            if error_source == "yahoo"
                            else FundamentalsProvenance()
                        )
                        error_lens = resolve_detail_lens(merged_query.get("lens", [""])[0])
                        (
                            error_option_data,
                            error_option_detail,
                            error_option_artifacts,
                        ) = _detail_option_state(
                            paths,
                            app_config=app_config,
                            ticker=ticker,
                            query=merged_query,
                        )
                        error_tool_a_row = _frame_index_by_ticker(
                            error_state.latest_tool_a
                        ).get(ticker, {})
                        error_anchor = _canonical_anchor_window(error_tool_a_row)
                        error_window = _resolve_active_window(
                            merged_query.get("window", [""])[0], error_anchor,
                        )
                        return _html_response(
                            start_response,
                            render_detail_page(
                                error_state,
                                ticker=ticker,
                                tool_a_detail=_load_tool_a_detail(
                                    paths,
                                    app_config=app_config,
                                    ticker=ticker,
                                    universe_tool_a=error_state.latest_tool_a,
                                ),
                                flash=None,
                                error=str(exc),
                                active_window=error_window,
                                canonical_anchor=error_anchor,
                                lens=error_lens,
                                app_config=app_config,
                                # A rejected POST must re-render the SAME page
                                # the user was on. Without these the redesigned
                                # Performance / Corporate finance sections (and
                                # their nav entries) silently vanished behind
                                # the error, which reads as data loss.
                                ticker_page_data=load_ticker_page_data(paths),
                                paths=paths,
                                lab_request=parse_lab_request(
                                    merged_query, app_config=app_config
                                ),
                                chart_horizon=_resolve_chart_horizon(
                                    (merged_query.get("chart_h") or [""])[0], app_config
                                ),
                                chart_view=_resolve_chart_view(
                                    (merged_query.get("chart_view") or [""])[0]
                                ),
                                financials_source=error_source,
                                query_params=_first_query_values(merged_query),
                                fundamentals_provenance=error_provenance.lookup,
                                fundamentals_statement_periods=(
                                    error_provenance.statement_periods
                                ),
                                # A rejected POST re-renders the SAME page, so
                                # the Options section must come back too — its
                                # absence would read as data loss.
                                option_trading_detail=error_option_detail,
                                option_page_artifacts=error_option_artifacts,
                                option_candidate_slots_frame=(
                                    error_option_data.candidate_slots_frame
                                    if error_option_data is not None
                                    else None
                                ),
                                target_window=_resolve_target_window(
                                    (merged_query.get(TARGET_WINDOW_PARAM) or [""])[0],
                                    app_config,
                                ),
                                form_overrides={
                                    section: {
                                        key: str(values[0])
                                        for key, values in submitted.items()
                                        if values
                                    }
                                },
                            ),
                            status="400 Bad Request",
                        )

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
                                # D2: nothing was written — return WITHOUT the
                                # saved marker so the page never claims a save.
                                no_op_fallback = f"/ticker/{ticker}"
                                return _redirect_response(
                                    start_response,
                                    _safe_return_to(
                                        form_data.get("return_to", [no_op_fallback])[0],
                                        fallback=no_op_fallback,
                                    ),
                                )
                            upsert_company_input(paths, ticker=ticker, values=company_values)
                        except ValueError as exc:
                            return _validation_error_response(
                                exc, submitted=form_data, section="company",
                            )
                        return _redirect_response(
                            start_response,
                            _saved_ticker_return_to(form_data, ticker, "company"),
                        )

                    if action == "reporting":
                        try:
                            # W11: identical blank-means-unchanged contract to the
                            # company and verification forms. This branch used to
                            # build all three keys unconditionally, so a partial
                            # POST (one date typed, the rest absent) NULLED the
                            # fields the user never touched — silent data loss.
                            # `upsert_reporting_calendar` writes only the keys it
                            # is given, so omitting a field leaves it alone.
                            reporting_values: dict[str, object] = {}
                            for field_name, _label in REPORTING_FORM_FIELDS:
                                if str(
                                    form_data.get(f"clear_{field_name}", [""])[0]
                                ).strip():
                                    reporting_values[field_name] = None
                                    continue
                                typed = _coerce_form_text(
                                    form_data.get(field_name, [""])[0]
                                )
                                if typed is None:
                                    continue
                                reporting_values[field_name] = typed
                            if not reporting_values:
                                # Nothing was written — return WITHOUT the saved
                                # marker so the page never claims a save (D2).
                                no_op_fallback = f"/ticker/{ticker}"
                                return _redirect_response(
                                    start_response,
                                    _safe_return_to(
                                        form_data.get("return_to", [no_op_fallback])[0],
                                        fallback=no_op_fallback,
                                    ),
                                )
                            upsert_reporting_calendar(
                                paths,
                                ticker=ticker,
                                values=reporting_values,
                            )
                        except ValueError as exc:
                            return _validation_error_response(
                                exc, submitted=form_data, section="reporting",
                            )
                        return _redirect_response(
                            start_response,
                            _saved_ticker_return_to(form_data, ticker, "reporting"),
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
                            # something; the same blank-means-unchanged guard the
                            # company and reporting forms use (W11: the reporting
                            # branch really did null omitted fields until then, so
                            # this comment described a guard that did not exist).
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
                            return _validation_error_response(
                                exc, submitted=form_data, section="verification",
                            )
                        return _redirect_response(
                            start_response,
                            _saved_ticker_return_to(form_data, ticker, "verification"),
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
                            return _validation_error_response(
                                exc, submitted=form_data, section="note",
                            )
                        return _redirect_response(
                            start_response,
                            _saved_ticker_return_to(form_data, ticker, "note"),
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
        except OptionArtifactIntegrityError as exc:
            return _html_response(
                start_response,
                _render_error_page(
                    "Your local Option Trading data failed its integrity check.",
                    detail=(
                        "A persisted option artifact does not match the sha256 recorded "
                        "in the model-state manifest, so the file has been corrupted or "
                        "modified after publish. Run python main.py refresh to rebuild "
                        f"the option artifacts. Details: {exc}"
                    ),
                ),
                status="503 Service Unavailable",
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
    if (
        not value
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        # D4: no control characters may reach the Location header. Deep-review
        # M5: nothing above ASCII either — wsgiref latin-1-encodes headers
        # AFTER the app returns, so a non-ASCII char (e.g. /ticker/Café) blows
        # up past our error handler and yields a broken response.
        or any(ord(ch) < 0x20 or ord(ch) > 0x7E for ch in value)
    ):
        return fallback
    return value


def _saved_ticker_return_to(form_data: dict[str, list[str]], ticker: str, saved: str) -> str:
    fallback = f"/ticker/{ticker}"
    return_to = _safe_return_to(
        form_data.get("return_to", [fallback])[0],
        fallback=fallback,
    )
    parts = urlsplit(return_to)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["saved"] = saved
    return urlunsplit(("", "", parts.path or fallback, urlencode(params), parts.fragment))


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


def _detail_option_state(paths, *, app_config, ticker, query, prefetched=None):
    """Option inputs for a ticker DETAIL render, degrading instead of aborting.

    The Options section is one section of a five-section page now, so a stale or
    corrupt option artifact must not take Performance, Corporate finance, Market
    behaviour and the user's own inputs down with it. The two loud errors are
    caught HERE (the /option-trading overview page still raises them, because
    there the option data IS the page) and turned into the same degraded state
    the missing-artifact path already renders, with the real reason attached.
    """

    try:
        data = prefetched or load_option_trading_data(paths, app_config=app_config)
        detail = build_option_trading_detail_data(
            data,
            ticker=ticker,
            app_config=app_config,
            sizing_request=parse_option_sizing_request(query, app_config=app_config),
        )
        return data, detail, load_option_page_artifacts(paths)
    except (OptionArtifactStaleSchemaError, OptionArtifactIntegrityError) as exc:
        LOGGER.warning("option artifacts unusable for %s detail page: %s", ticker, exc)
        return (
            None,
            None,
            OptionPageArtifacts(state=OPTION_PAGE_UNREADABLE, reason=str(exc)),
        )


def _resolve_chart_horizon(raw: str | None, app_config) -> str:
    """Resolve the chart horizon query param against the configured list."""
    horizons = list(app_config.ticker_page.chart.horizons)
    value = str(raw or "").strip().upper()
    return value if value in horizons else horizons[0]


def _resolve_chart_view(raw: str | None) -> str:
    value = str(raw or "").strip().lower()
    return value if value in {"rebased", "price"} else "rebased"


def _resolve_target_window(raw: str | None, app_config) -> int | None:
    """Parse the Options "Target window" (`tw`) param.

    Parsing only — the FALLBACK RULE itself lives once, in the section that
    renders the control (`ticker_page.options.resolve_target_window`), so the
    route and the chips can never disagree about which window is selected.
    """

    try:
        requested: int | None = int(str(raw or "").strip())
    except (TypeError, ValueError):
        requested = None
    return resolve_target_window(requested, app_config)
