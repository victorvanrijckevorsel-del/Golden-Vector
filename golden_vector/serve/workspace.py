"""Thin local workspace UI for Tool B manual inputs and structural Tool A outputs."""

from __future__ import annotations

from html import escape
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import pandas as pd



from golden_vector.serve.screening_overrides import (
    ScreeningOverrideError,
    ScreeningOverrides,
    parse_query_overrides,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.model.structural import build_trailing_window_rows
from golden_vector.screening.manual_data import (
    REQUIRED_MANUAL_FIELDS,
)
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD,
    DETAIL_ALIGNMENT_FOUNDATION_MISSING,
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH,
    OverviewFilters,
    StructuralHistoryLoad,
    ToolADetailState,
    WorkspaceState,
    _STRUCTURAL_WINDOWS,
    _WINDOW_WEEKS,
    _load_tool_a_detail,
    _load_workspace_state,
    _parse_ticker_route,
    _structural_history_matches_tool_a,
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
from golden_vector.serve.charts import (
    _build_beta_history_svg,
    _build_dual_bar_svg,
    _build_scatter_svg,
)
from golden_vector.serve.lenses import DEFAULT_LENS_ID
from golden_vector.serve.overview_combined import _render_overview_page
from golden_vector.serve.overview_tool_a import _render_tool_a_overview_page
from golden_vector.serve.overview_tool_b import _render_tool_b_overview_page
from golden_vector.serve.format_helpers import (
    _coerce_form_numeric,
    _coerce_form_text,
    _fmt_note_tag,
    _fmt_number,
    _fmt_numeric_td,
    _fmt_percent,
    _fmt_text,
    _fmt_value,
    _format_form_value,
    _frame_index_by_ticker,
    _humanize_column_name,
    _is_na,
    _metric_card,
    _optional_float,
    _render_small_table,
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


def _render_window_switcher(*, ticker: str, active: str, canonical: str) -> str:
    """Three-tab switcher at the top of the detail page: 6M / 12M / 3Y.

    Clicking a tab navigates to the same ticker with `?window=<id>`. The
    active tab is bold; the canonical anchor is marked with a tiny label
    so the user always knows which window the pipeline considers the
    official read.
    """
    tabs: list[str] = []
    base = f"/ticker/{escape(ticker)}"
    for window in _STRUCTURAL_WINDOWS:
        is_active = window == active
        is_canonical = window == canonical
        cls = "window-tab active" if is_active else "window-tab"
        href = base if window == canonical else f"{base}?window={window.lower()}"
        canonical_marker = (
            " <span class=\"window-canonical\">anchor</span>" if is_canonical else ""
        )
        tabs.append(
            f"<a class=\"{cls}\" href=\"{href}\">{escape(window)}{canonical_marker}</a>"
        )
    mismatch_note = ""
    if active != canonical:
        mismatch_note = (
            f"<p class=\"hint window-mismatch\">Viewing {escape(active)} — canonical anchor for "
            f"this ticker is {escape(canonical)}. Cross-window aggregates (Confidence, Tool A "
            "Score, Profile) are unchanged.</p>"
        )
    return (
        "<section class=\"panel window-switcher\">"
        "<div class=\"window-tabs\">"
        + "".join(tabs)
        + "</div>"
        + mismatch_note
        + "</section>"
    )







def _detail_alignment(
    tool_a_row: dict[str, Any],
    foundation_manifest: dict[str, Any] | None,
) -> str:
    """Decide whether the foundation-backed detail panels can render safely.

    Returns one of the DETAIL_ALIGNMENT_* constants. ALIGNED means the Tool A
    row and the current foundation manifest reference the same refresh run id.
    """

    if not foundation_manifest:
        return DETAIL_ALIGNMENT_FOUNDATION_MISSING
    foundation_refresh = str(foundation_manifest.get("refresh_run_id") or "").strip()
    if not foundation_refresh:
        return DETAIL_ALIGNMENT_FOUNDATION_MISSING
    tool_a_refresh = str(tool_a_row.get("snapshot_refresh_run_id") or "").strip()
    if not tool_a_refresh or tool_a_refresh.lower() == "nan":
        return DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH
    if tool_a_refresh != foundation_refresh:
        return DETAIL_ALIGNMENT_FOUNDATION_AHEAD
    return DETAIL_ALIGNMENT_ALIGNED


def _render_detail_alignment_notice(alignment: str) -> str:
    if alignment == DETAIL_ALIGNMENT_ALIGNED:
        return ""
    messages = {
        DETAIL_ALIGNMENT_FOUNDATION_AHEAD: (
            "The current foundation snapshot has moved ahead of the published Tool A row. "
            "Foundation-backed panels below are suppressed to avoid mixing data from different refreshes. "
            "Re-run <code>python main.py tool-a</code> to realign."
        ),
        DETAIL_ALIGNMENT_FOUNDATION_MISSING: (
            "No validated foundation snapshot is available for provenance alignment. "
            "Run <code>python main.py update-data</code>, then <code>python main.py tool-a</code>."
        ),
        DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: (
            "The published Tool A row does not carry a snapshot refresh identifier, "
            "so provenance cannot be confirmed. Re-run <code>python main.py tool-a</code>."
        ),
    }
    return f"<div class=\"flash\"><p>{messages[alignment]}</p></div>"


def _render_suppressed_panel(title: str, reason: str, command: str) -> str:
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Out of Sync</h3>"
        f"<p>{reason}</p>"
        f"<p class=\"hint\">Run <code>{escape(command)}</code> to realign.</p>"
        "</section>"
    )




def _render_latest_panels(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_b_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
    app_config: AppConfig | None = None,
) -> str:
    return (
        _render_tool_a_panel(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            visible_windows=visible_windows,
            app_config=app_config,
        )
        + "<div class=\"two-up\">"
        f"{_render_small_table('Latest Tool B Snapshot', tool_b_row, ['as_of_date', 'gold_price_assumption', 'tool_b_score', 'tool_b_rank', 'screening_verdict', 'confidence', 'best_upside_pct', 'snapshot_refresh_run_id', 'snapshot_as_of_date', 'snapshot_normalization_status', 'fx_staleness_days'])}"
        "</div>"
    )


def _render_tool_a_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
    app_config: AppConfig | None = None,
) -> str:
    if not tool_a_row:
        message = "No latest structural Tool A output is available yet."
        if tool_a_detail.foundation_error:
            message += f" {escape(tool_a_detail.foundation_error)}"
        return (
            "<section class=\"panel\">"
            "<h2>Structural Tool A</h2>"
            f"<p>{message}</p>"
            "</section>"
        )

    win = active_window.lower()
    scoring_config = app_config.scoring if app_config is not None else None
    volatility_diag = _compute_window_volatility(
        tool_a_row=tool_a_row,
        active_window=active_window,
        weekly_series=tool_a_detail.weekly_series,
        scoring_config=scoring_config,
    )
    vol_context_display = volatility_diag.get("volatility_context") or tool_a_row.get("volatility_context")

    body = [
        "<section class=\"panel\">",
        "<h2>Structural Tool A</h2>",
        "<p class=\"hint\">Official Tool A uses weekly structural delta, regime-split gamma, explicit asymmetry, "
        "confidence, and volatility diagnostics. The horizon-return ladder below is exploratory only.</p>",
        _render_signal_notice(tool_a_row),
        _render_detail_alignment_notice(alignment),
        _render_structural_metrics_load_notice(tool_a_detail.structural_metrics_load),
        # Window-specific metrics (recompute with switcher).
        f"<h3>Active window: {escape(active_window)}</h3>",
        "<div class=\"metric-grid\">",
        _metric_card("As Of", _fmt_text(tool_a_row.get("as_of_date"))),
        _metric_card(f"Structural Delta ({active_window})", _fmt_number(tool_a_row.get(f"structural_delta_{win}"), decimals=2)),
        _metric_card(f"Gamma Down-Up ({active_window})", _fmt_number(tool_a_row.get(f"gamma_{win}"), decimals=2)),
        _metric_card(f"Asymmetry ({active_window})", _fmt_number(tool_a_row.get(f"asymmetry_ratio_{win}"), decimals=2)),
        _metric_card(f"R² ({active_window})", _fmt_percent(tool_a_row.get(f"r_squared_{win}"), decimals=1)),
        _metric_card(f"Weeks ({active_window})", _fmt_number(tool_a_row.get(f"weeks_{win}"), decimals=0)),
        _metric_card(f"Volatility Context ({active_window})", _fmt_text(vol_context_display)),
        "</div>",
        # Aggregate (cross-window) metrics — stable regardless of switcher.
        "<h3>Aggregate across all windows</h3>",
        "<div class=\"metric-grid\">",
        _metric_card("Confidence", _fmt_text(tool_a_row.get("confidence_label"))),
        _metric_card("Tool A Score", _fmt_number(tool_a_row.get("tool_a_score"), decimals=1)),
        _metric_card("Profile", _fmt_text(tool_a_row.get("profile_label"))),
        _metric_card("Canonical Anchor", _fmt_text(tool_a_row.get("anchor_window_id"))),
        "</div>",
        _render_explanation_cards(
            tool_a_row,
            active_window=active_window,
            scoring_config=scoring_config,
            volatility_diag=volatility_diag,
        ),
        _render_structural_window_table(tool_a_row, active_window=active_window),
        _render_visual_panels(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
            active_window=active_window,
            visible_windows=visible_windows,
            scoring_config=scoring_config,
        ),
        "</section>",
    ]
    return "".join(body)


def _render_structural_metrics_load_notice(
    metrics_load: "StructuralHistoryLoad",
) -> str:
    """Surface a corrupt or missing structural-metrics file at the page level.

    Codex follow-up to Fix #5: previously, `_load_published_structural_metrics` swallowed
    parquet read errors silently, so a corrupted file would show "Could not read" inside
    the chart panel but silently degrade the scatter / up-down panels. Now every consumer
    sees one consistent file-health story.
    """
    if metrics_load.status == "ok":
        return ""
    if metrics_load.status == "missing":
        message = (
            "Structural metrics file is missing. The scatter, up/down beta, and "
            "structural windows panels below cannot draw their anchor metrics. "
            "Run <code>python main.py tool-a</code> to generate it."
        )
    elif metrics_load.status == "corrupt":
        detail = (
            f" Underlying error: {escape(metrics_load.error_message)}"
            if metrics_load.error_message
            else ""
        )
        message = (
            "Could not read the structural metrics file." + detail
            + " Re-run <code>python main.py tool-a</code> to regenerate it."
        )
    elif metrics_load.status == "no_rows":
        message = (
            "Structural metrics file exists but has no rows for this ticker. "
            "Re-run <code>python main.py tool-a</code> after a fresh data refresh."
        )
    else:
        return ""
    return f"<div class=\"flash\"><p>{message}</p></div>"


def _render_signal_notice(tool_a_row: dict[str, Any]) -> str:
    score_eligible = bool(tool_a_row.get("score_eligible"))
    score_reason = str(tool_a_row.get("score_eligibility_reason") or "").strip()
    normalization_issue_summary = _fmt_text(tool_a_row.get("normalization_issue_summary"))
    notices: list[str] = []
    if not score_eligible:
        if score_reason == "UNACCEPTABLE_NORMALIZATION_STATUS":
            notices.append(
                "Official Tool A score is withheld because trailing FX or return-basis issues block a trustworthy structural read."
            )
        elif score_reason:
            notices.append(
                f"Official Tool A score is currently withheld: {escape(score_reason.replace('_', ' ').title())}."
            )
    if normalization_issue_summary != "-":
        notices.append(f"Observed normalization issues in the trailing sample: {normalization_issue_summary}.")
    if not notices:
        return ""
    return (
        "<div class=\"flash\">"
        + "".join(f"<p>{notice}</p>" for notice in notices)
        + "</div>"
    )


def _render_explanation_cards(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
    scoring_config: Any = None,
    volatility_diag: dict[str, Any] | None = None,
) -> str:
    """Render the 7 narrative cards for the active window.

    Reuses `golden_vector/model/explanations.py` so we have ONE source of
    truth for narrative semantics across the pipeline and the workspace
    (per Codex's horizon-plan review). The pipeline bakes explanations
    for the ticker's canonical anchor; the workspace regenerates them
    live using the active window's numbers.
    """
    cards = _build_active_window_explanations(
        tool_a_row=tool_a_row,
        active_window=active_window,
        scoring_config=scoring_config,
        volatility_diag=volatility_diag or {},
    )
    return (
        "<div class=\"explanation-grid\">"
        + "".join(
            "<article class=\"panel explanation-card\">"
            f"<h3>{escape(title)}</h3><p>{_fmt_text(text)}</p>"
            "</article>"
            for title, text in cards
        )
        + "</div>"
    )


def _build_active_window_explanations(
    *,
    tool_a_row: dict[str, Any],
    active_window: str,
    scoring_config: Any,
    volatility_diag: dict[str, Any],
) -> list[tuple[str, str]]:
    """Call each model/explanations.py builder with the active window's
    numeric inputs. Returns ordered (title, text) tuples.
    """
    from golden_vector.model.explanations import (
        build_asymmetry_explanation,
        build_confidence_explanation,
        build_delta_explanation,
        build_gamma_explanation,
        build_interaction_explanation,
        build_summary_explanation,
        build_volatility_explanation,
    )
    win = active_window.lower()
    anchor_delta = _optional_float(tool_a_row.get(f"structural_delta_{win}"))
    anchor_gamma = _optional_float(tool_a_row.get(f"gamma_{win}"))
    anchor_up_beta = _optional_float(tool_a_row.get(f"up_beta_{win}"))
    anchor_down_beta = _optional_float(tool_a_row.get(f"down_beta_{win}"))
    anchor_asym = _optional_float(tool_a_row.get(f"asymmetry_ratio_{win}"))

    # Aggregate (cross-window) values used by some builders.
    structural_delta_core = _optional_float(tool_a_row.get("structural_delta_core"))
    asymmetry_core = _optional_float(tool_a_row.get("asymmetry_ratio_core"))
    structural_gamma_core = _optional_float(tool_a_row.get("structural_gamma_core"))
    score_eligible = bool(tool_a_row.get("score_eligible"))
    score_eligibility_reason = str(tool_a_row.get("score_eligibility_reason") or "").strip()
    profile_label = str(tool_a_row.get("profile_label") or "").strip().upper()
    confidence_label = str(tool_a_row.get("confidence_label") or "").strip().upper()
    confidence_score = _optional_float(tool_a_row.get("confidence_score"))
    # Volatility fields: prefer the active-window values from the
    # workspace recompute; fall back to pipeline-published 52w fields.
    vol_context = (
        volatility_diag.get("volatility_context")
        or str(tool_a_row.get("volatility_context") or "").strip().upper()
    )
    residual_vol = volatility_diag.get("residual_volatility") or tool_a_row.get(
        "residual_volatility_52w"
    )
    downside_vol = volatility_diag.get("downside_volatility") or tool_a_row.get(
        "downside_volatility_52w"
    )

    delta_text = build_delta_explanation(
        anchor_delta=anchor_delta,
        anchor_window_id=active_window,
        structural_delta_core=structural_delta_core,
        score_eligible=score_eligible,
        score_eligibility_reason=score_eligibility_reason,
        scoring_config=scoring_config,
    )
    gamma_text = build_gamma_explanation(
        gamma_core=anchor_gamma,
        up_beta_anchor=anchor_up_beta,
        down_beta_anchor=anchor_down_beta,
        anchor_window_id=active_window,
        score_eligible=score_eligible,
        score_eligibility_reason=score_eligibility_reason,
        scoring_config=scoring_config,
    )
    asymmetry_text = build_asymmetry_explanation(
        asymmetry_ratio_anchor=anchor_asym,
        up_beta_anchor=anchor_up_beta,
        down_beta_anchor=anchor_down_beta,
        score_eligibility_reason=score_eligibility_reason,
        scoring_config=scoring_config,
    )
    volatility_text = build_volatility_explanation(
        volatility_context=vol_context,
        residual_volatility_52w=residual_vol,
        downside_volatility_52w=downside_vol,
    )
    confidence_text = build_confidence_explanation(
        confidence_label=confidence_label,
        confidence_score=confidence_score,
        score_eligibility_reason=score_eligibility_reason,
    )
    interaction_text = build_interaction_explanation(
        score_eligible=score_eligible,
        score_eligibility_reason=score_eligibility_reason,
        profile_label=profile_label,
        structural_delta_core=structural_delta_core,
        structural_gamma_core=structural_gamma_core,
        asymmetry_ratio_core=asymmetry_core,
        volatility_context=vol_context,
        confidence_label=confidence_label,
        scoring_config=scoring_config,
    )
    summary_text = build_summary_explanation(
        profile_label=profile_label,
        confidence_label=confidence_label,
        score_eligibility_reason=score_eligibility_reason,
        interaction_explanation=interaction_text,
    )
    return [
        ("Delta", delta_text),
        ("Gamma", gamma_text),
        ("Asymmetry", asymmetry_text),
        ("Volatility", volatility_text),
        ("Confidence", confidence_text),
        ("Interaction", interaction_text),
        ("Summary", summary_text),
    ]


def _render_structural_window_table(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
) -> str:
    window_rows = []
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    for window_id in ("6M", "12M", "3Y"):
        normalized = window_id.lower()
        markers = []
        if window_id == anchor_window_id:
            markers.append("Anchor")
        if window_id == active_window:
            markers.append("Active")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        row_class = " class=\"active-row\"" if window_id == active_window else ""
        window_rows.append(
            f"<tr{row_class}>"
            f"<td>{window_id}{marker_text}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'structural_delta_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'gamma_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'up_beta_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'down_beta_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'asymmetry_ratio_{normalized}'), decimals=2)}</td>"
            f"<td>{_fmt_percent(tool_a_row.get(f'r_squared_{normalized}'), decimals=1)}</td>"
            f"<td>{_fmt_number(tool_a_row.get(f'weeks_{normalized}'), decimals=0)}</td>"
            f"<td>{_fmt_text(tool_a_row.get(f'window_status_{normalized}'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Official Structural Windows</h3>"
        "<table>"
        "<thead><tr><th>Window</th><th>Delta</th><th>Gamma</th><th>Up Beta</th><th>Down Beta</th>"
        "<th>Asymmetry</th><th>R^2</th><th>Weeks</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(window_rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _render_visual_panels(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
    scoring_config: Any = None,
) -> str:
    if visible_windows is None:
        visible_windows = [active_window]
    # Alignment check fires first so every documented non-aligned state — including
    # FOUNDATION_MISSING, where load_latest_foundation_snapshot raises and sets
    # tool_a_detail.foundation_error — gets the per-panel suppressed-card treatment
    # promised by plan v3 §1, instead of falling through to a single generic error.
    if alignment != DETAIL_ALIGNMENT_ALIGNED:
        suppression_reasons = {
            DETAIL_ALIGNMENT_FOUNDATION_AHEAD: (
                "The foundation snapshot on disk differs from the published Tool A row, so this panel is "
                "suppressed to avoid mixing data from different refreshes."
            ),
            DETAIL_ALIGNMENT_FOUNDATION_MISSING: (
                "No validated foundation snapshot is available, so this panel cannot be rebuilt safely "
                "from the published Tool A row's refresh context."
            ),
            DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: (
                "The published Tool A row does not carry a snapshot refresh identifier, so this panel "
                "cannot be matched to a foundation snapshot and is suppressed for safety."
            ),
        }
        suppression_commands = {
            DETAIL_ALIGNMENT_FOUNDATION_AHEAD: "python main.py tool-a",
            DETAIL_ALIGNMENT_FOUNDATION_MISSING: "python main.py update-data",
            DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: "python main.py tool-a",
        }
        reason = suppression_reasons.get(alignment, suppression_reasons[DETAIL_ALIGNMENT_FOUNDATION_AHEAD])
        command = suppression_commands.get(alignment, "python main.py tool-a")
        # The beta-history chart has its own provenance check (source_run_id).
        # It still renders when its own provenance is OK even if foundation is
        # misaligned. The rebased gold overlay was removed in the post-deep-review
        # fix pass, so there's nothing extra to suppress here.
        beta_history_panel = _render_beta_history_panel(
            ticker=ticker,
            tool_a_row=tool_a_row,
            structural_history_load=tool_a_detail.structural_history_load,
            active_window=active_window,
            visible_windows=visible_windows,
        )
        # Mirror the aligned branch's ordering (Fix #10 follow-up): chart sits
        # between the scatter row and the volatility row in BOTH branches so the
        # detail page has consistent visual rhythm regardless of alignment state.
        return (
            "<div class=\"two-up\">"
            + _render_suppressed_panel("Weekly Return Scatter", reason, command)
            + _render_suppressed_panel("Up vs Down Beta", reason, command)
            + "</div>"
            + beta_history_panel
            + "<div class=\"two-up\">"
            + _render_volatility_panel(
                tool_a_row,
                active_window=active_window,
                weekly_series=tool_a_detail.weekly_series,
                scoring_config=scoring_config,
            )
            + _render_suppressed_panel("Exploratory Horizon Ladder", reason, command)
            + "</div>"
        )
    if tool_a_detail.foundation_error:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Tool A Detail</h3>"
            f"<p>{escape(tool_a_detail.foundation_error)}</p>"
            "</section>"
        )
    # Use the active window's metrics + sample (not the ticker's canonical anchor).
    active_metric = _active_window_metric(tool_a_detail, active_window)
    active_sample = _active_window_sample(tool_a_row, tool_a_detail, active_window)
    # Rolling chart now shows all three windows as separate lines;
    # structural_history_load provides the full per-window history.
    beta_history_panel = _render_beta_history_panel(
        ticker=ticker,
        tool_a_row=tool_a_row,
        structural_history_load=tool_a_detail.structural_history_load,
        active_window=active_window,
        visible_windows=visible_windows,
    )
    # Chart placement (post-deep-review): the rolling-delta chart is the most
    # paper-aligned visual on the detail page, so it sits immediately under the
    # scatter / up-down-beta row, above the volatility and exploratory panels.
    return (
        "<div class=\"two-up\">"
        f"{_render_scatter_panel(ticker=ticker, tool_a_row=tool_a_row, anchor_metric=active_metric, anchor_sample=active_sample, active_window=active_window)}"
        f"{_render_up_down_beta_panel(tool_a_row, anchor_metric=active_metric, active_window=active_window)}"
        "</div>"
        f"{beta_history_panel}"
        "<div class=\"two-up\">"
        f"{_render_volatility_panel(tool_a_row, active_window=active_window, weekly_series=tool_a_detail.weekly_series, scoring_config=scoring_config)}"
        f"{_render_exploratory_horizon_panel(tool_a_detail.exploratory_horizons)}"
        "</div>"
    )


def _active_window_metric(
    tool_a_detail: ToolADetailState,
    active_window: str,
) -> dict[str, Any]:
    """Return the structural_window_metrics row for the active window.

    Replaces _anchor_window_metric which keyed on the ticker's canonical
    anchor. Looking up by active_window lets the scatter + beta-bar
    panels follow the switcher.
    """
    metrics = tool_a_detail.structural_window_metrics
    if metrics.empty or not active_window:
        return {}
    matches = metrics.loc[
        metrics["window_id"].astype(str).str.upper().eq(active_window.upper())
    ]
    if matches.empty:
        return {}
    return matches.sort_values("as_of_date").iloc[-1].to_dict()


def _active_window_sample(
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    active_window: str,
) -> pd.DataFrame:
    """Trailing weekly-returns sample for the active window."""
    if not active_window or tool_a_detail.weekly_series.empty:
        return pd.DataFrame()
    as_of_date = pd.to_datetime(tool_a_row.get("as_of_date"), errors="coerce")
    if pd.isna(as_of_date):
        return pd.DataFrame()
    return build_trailing_window_rows(
        weekly_series=tool_a_detail.weekly_series,
        as_of_date=pd.Timestamp(as_of_date),
        window_id=active_window,
    )


def _anchor_window_metric(
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
) -> dict[str, Any]:
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    metrics = tool_a_detail.structural_window_metrics
    if not anchor_window_id or metrics.empty:
        return {}
    window_rows = metrics.loc[
        metrics["window_id"].astype(str).str.upper().eq(anchor_window_id)
    ].copy()
    if window_rows.empty:
        return {}
    return window_rows.sort_values("as_of_date").iloc[-1].to_dict()


def _anchor_window_sample(
    tool_a_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
) -> pd.DataFrame:
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    if not anchor_window_id or tool_a_detail.weekly_series.empty:
        return pd.DataFrame()
    as_of_date = pd.to_datetime(tool_a_row.get("as_of_date"), errors="coerce")
    if pd.isna(as_of_date):
        return pd.DataFrame()
    return build_trailing_window_rows(
        weekly_series=tool_a_detail.weekly_series,
        as_of_date=pd.Timestamp(as_of_date),
        window_id=anchor_window_id,
    )


def _render_scatter_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    anchor_metric: dict[str, Any],
    anchor_sample: pd.DataFrame,
    active_window: str = "12M",
) -> str:
    if anchor_sample.empty:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Weekly Return Scatter</h3>"
            f"<p>No weekly return detail is available yet for the {escape(active_window)} window.</p>"
            "</section>"
        )
    regression_beta = _optional_float(anchor_metric.get("structural_delta"))
    regression_alpha = _optional_float(anchor_metric.get("intercept_alpha"))
    svg = _build_scatter_svg(
        x_values=anchor_sample["gold_weekly_log_return"].tolist(),
        y_values=anchor_sample["stock_weekly_log_return"].tolist(),
        regression_beta=regression_beta,
        regression_alpha=regression_alpha,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Weekly Return Scatter</h3><p class=\"hint\">{escape(ticker)} weekly log returns vs gold weekly log returns over the {escape(active_window)} trailing sample.</p>"
        f"{svg}"
        "</section>"
    )


def _render_up_down_beta_panel(
    tool_a_row: dict[str, Any],
    *,
    anchor_metric: dict[str, Any],
    active_window: str = "12M",
) -> str:
    up_beta = _optional_float(anchor_metric.get("up_beta"))
    down_beta = _optional_float(anchor_metric.get("down_beta"))
    if up_beta is None and down_beta is None:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Up vs Down Beta</h3><p>No {escape(active_window)} regime split is available yet.</p>"
            "</section>"
        )
    svg = _build_dual_bar_svg(
        left_label="Up-Gold",
        left_value=up_beta or 0.0,
        right_label="Down-Gold",
        right_value=down_beta or 0.0,
    )
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Up vs Down Beta</h3>"
        f"<p class=\"hint\">This shows the {escape(active_window)} regime split. Positive gamma means down-gold sensitivity is stronger than up-gold sensitivity.</p>"
        f"{svg}"
        "</section>"
    )


def _render_volatility_panel(
    tool_a_row: dict[str, Any],
    *,
    active_window: str = "12M",
    weekly_series: pd.DataFrame | None = None,
    scoring_config: Any = None,
) -> str:
    """Render the volatility card group for the active window.

    When active_window is the ticker's canonical 52w basis (derived from
    the anchor-window selection baked into the pipeline), we show the
    pre-computed `*_52w` fields. When the user selects a non-canonical
    window, we recompute from the weekly_series slice. If the window
    isn't ELIGIBLE for that ticker, we show "not eligible" instead of
    rendering numbers built on thin observations.
    """
    window_status = _window_status(tool_a_row, active_window)
    # If the active window isn't ELIGIBLE, suppress numbers entirely.
    # Codex flagged in review: a structural page showing low-obs vol
    # with just a sample-size asterisk implies more trust than it should.
    if window_status != "ELIGIBLE":
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Volatility Diagnostics ({escape(active_window)})</h3>"
            f"<p class=\"hint\">The {escape(active_window)} window is not eligible for this ticker "
            f"(status: {escape(str(window_status))}). Volatility is not shown.</p>"
            "</section>"
        )

    diag = _compute_window_volatility(
        tool_a_row=tool_a_row,
        active_window=active_window,
        weekly_series=weekly_series,
        scoring_config=scoring_config,
    )
    context_label = diag.get("volatility_context") or "UNKNOWN"
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Volatility Diagnostics ({escape(active_window)})</h3>"
        "<div class=\"metric-grid\">"
        f"{_metric_card('Total Volatility (Annualized Log Vol)', _fmt_percent(diag.get('total_volatility'), decimals=1))}"
        f"{_metric_card('Residual Volatility (Annualized Log Vol)', _fmt_percent(diag.get('residual_volatility'), decimals=1))}"
        f"{_metric_card('Downside Volatility (Annualized Log Vol)', _fmt_percent(diag.get('downside_volatility'), decimals=1))}"
        f"{_metric_card('Volatility Context', _fmt_text(context_label))}"
        "</div>"
        "</section>"
    )


def _window_status(tool_a_row: dict[str, Any], window: str) -> str:
    """Extract the ELIGIBLE / INELIGIBLE_* status for a window."""
    key = f"window_status_{window.lower()}"
    raw = tool_a_row.get(key)
    if raw is None:
        return "UNKNOWN"
    try:
        if pd.isna(raw):
            return "UNKNOWN"
    except TypeError:
        pass
    return str(raw).strip().upper() or "UNKNOWN"


def _compute_window_volatility(
    *,
    tool_a_row: dict[str, Any],
    active_window: str,
    weekly_series: pd.DataFrame | None,
    scoring_config: Any,
) -> dict[str, Any]:
    """Compute total/residual/downside volatility for the active window.

    If the active window matches the pipeline's canonical 52w basis
    (volatility_anchor_window_id), we reuse the pre-computed values to
    avoid tiny floating-point drift. Otherwise we recompute from the
    weekly_series slice.
    """
    anchor_win_raw = tool_a_row.get("volatility_anchor_window_id")
    anchor_basis = (
        str(anchor_win_raw).strip().upper()
        if anchor_win_raw is not None and not _is_na(anchor_win_raw)
        else None
    )
    if anchor_basis == active_window and tool_a_row.get("total_volatility_52w") is not None:
        # Reuse pipeline-published numbers for the canonical window.
        return {
            "total_volatility": tool_a_row.get("total_volatility_52w"),
            "residual_volatility": tool_a_row.get("residual_volatility_52w"),
            "downside_volatility": tool_a_row.get("downside_volatility_52w"),
            "volatility_context": tool_a_row.get("volatility_context"),
        }

    # Non-canonical window: recompute from the window's weekly slice.
    if weekly_series is None or weekly_series.empty:
        return {}
    from golden_vector.model.structural import (
        annualize_weekly_volatility,
        annualize_downside_volatility,
    )
    weeks = _WINDOW_WEEKS.get(active_window, 52)
    ordered = weekly_series.sort_values("as_of_date").reset_index(drop=True)
    trailing = ordered.tail(weeks)
    stock_returns = pd.to_numeric(
        trailing.get("stock_weekly_log_return"), errors="coerce"
    )
    gold_returns = pd.to_numeric(
        trailing.get("gold_weekly_log_return"), errors="coerce"
    )
    total_vol = annualize_weekly_volatility(stock_returns)
    downside_vol = annualize_downside_volatility(stock_returns)
    # Residual vol needs the window's alpha + beta. The _latest row has
    # delta per window but not alpha per window — alpha lives in the
    # structural_window_metrics history. Approximate via OLS over the
    # trailing slice to keep things simple; drift vs the pipeline is tiny.
    residual_vol = None
    import numpy as np
    x = gold_returns.to_numpy(dtype=float)
    y = stock_returns.to_numpy(dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x = x[mask]
    y = y[mask]
    if len(x) >= 2 and x.std() > 0:
        beta_fit, alpha_fit = np.polyfit(x, y, 1)
        residual_vol = annualize_weekly_volatility(y - (alpha_fit + beta_fit * x))

    # Categorical context label from residual vol thresholds.
    context = _classify_volatility_context(residual_vol, downside_vol, total_vol, scoring_config)
    return {
        "total_volatility": total_vol,
        "residual_volatility": residual_vol,
        "downside_volatility": downside_vol,
        "volatility_context": context,
    }


def _classify_volatility_context(
    residual_vol: float | None,
    downside_vol: float | None,
    total_vol: float | None,
    scoring_config: Any,
) -> str:
    """Bucket a residual-vol into LOW_NOISE / MODERATE_NOISE / HIGH_NOISE.

    Uses the same thresholds the structural pipeline applies in its
    compute_volatility_diagnostics function. If the scoring_config or
    a threshold block is missing, returns UNKNOWN rather than crashing.
    """
    if residual_vol is None or _is_na(residual_vol):
        return "UNKNOWN"
    try:
        bands = scoring_config.volatility_diagnostic_bands
    except AttributeError:
        return "UNKNOWN"
    # Match pipeline logic: residual-first, then downside/total escalations.
    if downside_vol is not None and downside_vol >= bands.high_downside_volatility_min:
        return "HIGH_DOWNSIDE_RISK"
    if total_vol is not None and total_vol >= bands.high_total_volatility_min:
        return "HIGH_NOISE"
    if residual_vol >= bands.high_residual_volatility_min:
        return "HIGH_NOISE"
    if residual_vol <= bands.low_residual_volatility_max:
        return "LOW_NOISE"
    return "MODERATE_NOISE"




def _render_exploratory_horizon_panel(exploratory_horizons: pd.DataFrame) -> str:
    if exploratory_horizons.empty:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Exploratory Horizon Ladder</h3>"
            "<p>No exploratory horizon data is available yet.</p>"
            "</section>"
        )
    rows = []
    for row in exploratory_horizons.sort_values(["horizon_value", "horizon_unit"]).itertuples(index=False):
        rows.append(
            "<tr>"
            f"<td>{escape(str(row.horizon_id))}</td>"
            f"<td>{_fmt_percent(getattr(row, 'equity_return', None), decimals=1)}</td>"
            f"<td>{_fmt_percent(getattr(row, 'gold_return', None), decimals=1)}</td>"
            f"<td>{_fmt_number(getattr(row, 'gold_delta', None), decimals=2)}</td>"
            f"<td>{_fmt_text(getattr(row, 'coverage_flag', None))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Exploratory Horizon Ladder</h3>"
        "<p class=\"hint\">This preserves the older horizon-return lens for tactical context only. The ratio below is a single-period return ratio, not a structural beta, and it does not drive the official Tool A score.</p>"
        "<table>"
        "<thead><tr><th>Horizon</th><th>Equity Return</th><th>Gold Return</th><th>Single-Period Ratio</th><th>Status</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
    )


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




def _canonical_anchor_window(tool_a_row: dict[str, Any]) -> str:
    """Return the ticker's canonical anchor window id (always 6M / 12M / 3Y).

    Falls back to 12M when the field is missing or malformed so the
    detail page keeps working even on incomplete fixtures.
    """
    raw = tool_a_row.get("anchor_window_id") if tool_a_row else None
    if raw is None:
        return "12M"
    try:
        if pd.isna(raw):
            return "12M"
    except TypeError:
        pass
    normalized = str(raw).strip().upper()
    return normalized if normalized in _STRUCTURAL_WINDOWS else "12M"


def _resolve_active_window(raw_param: str, canonical_anchor: str) -> str:
    """Map a URL `window=` value to a valid structural window id.

    Invalid / missing params fall back to the ticker's canonical anchor.
    Case-insensitive.
    """
    normalized = str(raw_param or "").strip().upper()
    if normalized in _STRUCTURAL_WINDOWS:
        return normalized
    return canonical_anchor if canonical_anchor in _STRUCTURAL_WINDOWS else "12M"


def _resolve_visible_windows(raw_param: str, active_window: str) -> list[str]:
    """Map a URL `show=` value to an ordered list of windows to draw.

    The active window is always included — the switcher tab is the "primary"
    line the user picked, so hiding it would make the chart meaningless.
    Additional windows can be layered in via `?show=6m` or `?show=6m,3y`.
    Tokens are case-insensitive; invalid tokens are silently dropped.

    Return order mirrors `_STRUCTURAL_WINDOWS` so the legend is always
    displayed 6M / 12M / 3Y regardless of what the user clicked first.
    """
    tokens = {
        token.strip().upper()
        for token in str(raw_param or "").split(",")
        if token.strip()
    }
    tokens.add(active_window.upper())
    return [window for window in _STRUCTURAL_WINDOWS if window.upper() in tokens]



















































# ----------------------- Phase 2B: 12M rolling structural delta chart ----------------------







def _render_beta_history_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    structural_history_load: "StructuralHistoryLoad",
    active_window: str = "12M",
    visible_windows: list[str] | None = None,
) -> str:
    """Render the rolling structural-delta panel with one line per window.

    Per plan v3 §5 and the post-deep-review fix pass:
    - The chart uses only ``source_run_id`` for its provenance gate. The rebased
      gold overlay was removed because it wasn't numerically interpretable.
    - The four empty states are now distinguished by the structured load result
      (missing / corrupt / no_rows / ok), not by checking ``DataFrame.empty`` alone.
    - The horizon-switcher version draws 6M / 12M / 3Y as three lines on one shared
      y-axis; the active window is thicker and fully opaque, the other two muted.
    """

    title = "Rolling Structural Delta"

    if structural_history_load.status == "missing":
        return _render_chart_unavailable_panel(
            title,
            "Structural history file has not been generated yet. "
            "Run <code>python main.py tool-a</code> to generate it.",
        )

    if structural_history_load.status == "corrupt":
        detail = (
            f" Underlying error: {escape(structural_history_load.error_message)}"
            if structural_history_load.error_message
            else ""
        )
        return _render_chart_unavailable_panel(
            title,
            "Could not read the structural history file."
            + detail
            + " Re-run <code>python main.py tool-a</code> to regenerate it.",
        )

    structural_history = structural_history_load.history

    if structural_history is None or structural_history.empty:
        return _render_chart_unavailable_panel(
            title,
            "This ticker does not have enough clean structural history to plot yet. "
            "Run <code>python main.py tool-a</code> after a fresh data refresh.",
        )

    if not _structural_history_matches_tool_a(structural_history, tool_a_row):
        return _render_chart_fallback_panel(
            title,
            "Structural history file is out of sync with the published Tool A row.",
            "python main.py tool-a",
        )

    # Split the combined history back into per-window (dates, deltas) tuples.
    series_by_window: dict[str, tuple[list[pd.Timestamp], list[float]]] = {}
    window_series = structural_history["window_id"].astype(str).str.upper()
    for window_id in _STRUCTURAL_WINDOWS:
        mask = window_series == window_id.upper()
        slice_df = structural_history.loc[mask].copy()
        if slice_df.empty:
            continue
        slice_df = slice_df.sort_values("as_of_date")
        series_by_window[window_id] = (
            list(slice_df["as_of_date"]),
            slice_df["structural_delta"].astype(float).tolist(),
        )

    if not series_by_window:
        return _render_chart_unavailable_panel(
            title,
            "This ticker does not have enough clean structural history in any window to plot yet. "
            "Run <code>python main.py tool-a</code> after a fresh data refresh.",
        )

    current_delta_core = _optional_float(tool_a_row.get("structural_delta_core"))
    score_eligible = bool(tool_a_row.get("score_eligible"))
    watermark = ""
    if not score_eligible:
        watermark = (
            "<p class=\"hint\"><em>Current snapshot score for this stock is withheld; "
            "historical series shown for context only.</em></p>"
        )

    # Default: only the active window's line is drawn. The user opts-in to
    # additional windows by clicking their legend items (which toggle via the
    # `?show=` URL param).
    if visible_windows is None:
        visible_windows = [active_window]
    visible_upper = {w.upper() for w in visible_windows}

    svg = _build_beta_history_svg(
        series_by_window=series_by_window,
        active_window=active_window,
        visible_windows=visible_windows,
        current_delta_core=current_delta_core,
        ticker=ticker,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)}</h3>"
        f"<p class=\"hint\">How {escape(ticker)}'s weekly structural beta to gold has moved over time, "
        f"with the {escape(active_window)} window highlighted. Click a window below to add or remove its line. "
        "Drawn from <code>tool_a_structural_latest.parquet</code>.</p>"
        f"{watermark}{svg}"
        "</section>"
    )


def _render_chart_fallback_panel(title: str, reason: str, command: str) -> str:
    """Out-of-sync (provenance mismatch) fallback panel. Reserved for the
    source_run_id mismatch case so the 'Out of Sync' wording is unambiguous.
    """
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Out of Sync</h3>"
        f"<p>{reason}</p>"
        f"<p class=\"hint\">Run <code>{escape(command)}</code> to realign.</p>"
        "</section>"
    )


def _render_chart_unavailable_panel(title: str, reason_html: str) -> str:
    """Generic "not available yet" panel used when the structural file is missing
    or has no eligible rows for this ticker. Distinct from the out-of-sync state.
    """
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Not Available Yet</h3>"
        f"<p>{reason_html}</p>"
        "</section>"
    )
