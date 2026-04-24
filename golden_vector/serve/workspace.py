"""Thin local workspace UI for Tool B manual inputs and structural Tool A outputs."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Callable, ClassVar, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server

import pandas as pd

from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.features.horizons import build_core_horizons
from golden_vector.features.returns import RETURN_COLUMNS, compute_horizon_returns_for_ticker
from golden_vector.model.structural import (
    build_structural_weekly_series,
    build_trailing_window_rows,
)
from golden_vector.screening.manual_data import (
    REQUIRED_MANUAL_FIELDS,
    load_manual_screening_data,
)
from golden_vector.serve.lenses import (
    DEFAULT_LENS_ID,
    LENS_DEFINITIONS,
    compute_lens_score,
    resolve_lens,
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

RATE_FIELDS = {"royalty_rate", "tax_rate"}
TOOL_A_PERCENT_FIELDS = {
    "total_volatility_52w",
    "residual_volatility_52w",
    "downside_volatility_52w",
}
TOOL_A_NUMERIC_FIELDS = {
    "structural_delta_core",
    "structural_delta_6m",
    "structural_delta_12m",
    "structural_delta_3y",
    "structural_gamma_core",
    "gamma_6m",
    "gamma_12m",
    "gamma_3y",
    "up_beta_6m",
    "down_beta_6m",
    "up_beta_12m",
    "down_beta_12m",
    "up_beta_3y",
    "down_beta_3y",
    "asymmetry_ratio_6m",
    "asymmetry_ratio_12m",
    "asymmetry_ratio_3y",
    "asymmetry_ratio_core",
    "confidence_score",
    "tool_a_score",
}


@dataclass(frozen=True)
class WorkspaceState:
    tool_b_tickers: list[str]
    foundation_manifest: dict[str, Any] | None
    company_inputs: pd.DataFrame
    source_verification: pd.DataFrame
    reporting_calendar: pd.DataFrame
    stock_notes: pd.DataFrame
    latest_tool_a: pd.DataFrame
    latest_tool_b: pd.DataFrame
    tool_a_alias_present: bool
    tool_b_alias_present: bool


@dataclass(frozen=True)
class ToolADetailState:
    weekly_series: pd.DataFrame
    structural_window_metrics: pd.DataFrame
    structural_metrics_load: "StructuralHistoryLoad"
    exploratory_horizons: pd.DataFrame
    structural_history_load: "StructuralHistoryLoad"
    foundation_error: str | None = None


@dataclass(frozen=True)
class OverviewFilters:
    """Phase 1B.4: lightweight overview controls passed via querystring.

    Empty string means "no filter" / "default sort". Only a small allow-list
    of sort keys is honored so the URL surface stays predictable.
    """

    search: str = ""
    profile: str = ""
    verdict: str = ""
    confidence: str = ""
    sort: str = ""

    SORT_OPTIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("ticker", "Ticker (A→Z)"),
        ("tool_a_rank", "Tool A Rank (best first)"),
        ("tool_b_rank", "Tool B Rank (best first)"),
        ("tool_a_score", "Tool A Score (high→low)"),
        ("tool_b_score", "Tool B Score (high→low)"),
    )

    def normalized_search(self) -> str:
        return str(self.search or "").strip().upper()

    def normalized_profile(self) -> str:
        return str(self.profile or "").strip().upper()

    def normalized_verdict(self) -> str:
        return str(self.verdict or "").strip().upper()

    def normalized_confidence(self) -> str:
        return str(self.confidence or "").strip().upper()

    def normalized_sort(self) -> str:
        sort = str(self.sort or "").strip().lower()
        allowed = {key for key, _ in self.SORT_OPTIONS}
        return sort if sort in allowed else "ticker"


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
                return _html_response(
                    start_response,
                    _render_tool_b_overview_page(
                        state,
                        flash=flash,
                        search=query.get("search", [""])[0],
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
                    return _html_response(
                        start_response,
                        _render_ticker_page(
                            state,
                            ticker=ticker,
                            tool_a_detail=tool_a_detail,
                            flash=flash,
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


def _load_workspace_state(paths: ProjectPaths, tool_b_tickers: list[str]) -> WorkspaceState:
    loaded = load_manual_screening_data(paths, tickers=tool_b_tickers)
    foundation_manifest = _load_json_file(paths.latest_foundation_manifest_path)
    tool_a_alias_present = paths.latest_tool_a_snapshot_parquet_path.exists()
    tool_b_alias_present = paths.latest_tool_b_snapshot_parquet_path.exists()
    latest_tool_a = _read_optional_parquet(paths.latest_tool_a_snapshot_parquet_path)
    latest_tool_b = _read_optional_parquet(paths.latest_tool_b_snapshot_parquet_path)
    if not latest_tool_a.empty and "ticker" in latest_tool_a.columns:
        latest_tool_a["ticker"] = latest_tool_a["ticker"].astype(str).str.upper()
    if not latest_tool_b.empty and "ticker" in latest_tool_b.columns:
        latest_tool_b["ticker"] = latest_tool_b["ticker"].astype(str).str.upper()
    return WorkspaceState(
        tool_b_tickers=tool_b_tickers,
        foundation_manifest=foundation_manifest,
        company_inputs=loaded.company_inputs,
        source_verification=loaded.source_verification,
        reporting_calendar=loaded.reporting_calendar,
        stock_notes=loaded.stock_notes,
        latest_tool_a=latest_tool_a,
        latest_tool_b=latest_tool_b,
        tool_a_alias_present=tool_a_alias_present,
        tool_b_alias_present=tool_b_alias_present,
    )


def _load_tool_a_detail(
    paths: ProjectPaths,
    *,
    app_config: AppConfig,
    ticker: str,
) -> ToolADetailState:
    try:
        foundation_snapshot = load_latest_foundation_snapshot(
            paths=paths,
            app_config=app_config,
            include_gold_history=True,
            include_equity_histories=True,
            include_market_snapshots=False,
            requested_tickers=[ticker],
        )
    except Exception as exc:
        # Even when the foundation snapshot is unavailable, the structural-history
        # parquet might still be present and usable for the beta-history chart.
        return ToolADetailState(
            weekly_series=pd.DataFrame(),
            structural_window_metrics=pd.DataFrame(),
            structural_metrics_load=_load_published_structural_metrics(paths, ticker),
            exploratory_horizons=pd.DataFrame(),
            structural_history_load=_safe_load_structural_history(paths, ticker),
            foundation_error=str(exc),
        )

    # Performance fix (post-deep-review): the previous implementation called
    # build_structural_ticker_data which recomputed structural_window_metrics for
    # every weekly date in the ticker's full history (~1,300 weeks × 3 windows
    # × ~52 datapoint regressions) on every detail-page hit. For NEM that took
    # ~25 seconds. tool-a already computed and persisted the same metrics in
    # tool_a_structural_latest.parquet, so we read them from there instead and
    # only build the cheap weekly_series for the scatter panel sample.
    full_equity_history = foundation_snapshot.normalized_equity_histories.get(
        ticker,
        pd.DataFrame(columns=[]),
    )
    weekly_series, _ = build_structural_weekly_series(
        usd_equity_history=full_equity_history,
        gold_history=foundation_snapshot.gold_history,
    )
    structural_metrics_load = _load_published_structural_metrics(paths, ticker)
    structural_window_metrics = structural_metrics_load.history

    # Horizons: compute only the most recent slice. The longest core horizon is
    # 3 years ≈ 756 trading days; we keep ~3 years + buffer so the most recent
    # as_of_date can find its longest start. The workspace uses only the latest
    # as_of_date's horizons.
    equity_for_horizons = (
        full_equity_history.tail(900) if len(full_equity_history.index) > 900 else full_equity_history
    )
    exploratory_horizons = compute_horizon_returns_for_ticker(
        usd_equity_history=equity_for_horizons,
        gold_history=foundation_snapshot.gold_history,
        horizons=build_core_horizons(app_config.horizons),
        near_zero_gold_return_threshold=app_config.qa.near_zero_gold_return_threshold,
    )
    if not exploratory_horizons.empty:
        latest_as_of_date = exploratory_horizons["as_of_date"].max()
        exploratory_horizons = exploratory_horizons.loc[
            exploratory_horizons["as_of_date"] == latest_as_of_date
        ].copy()
    return ToolADetailState(
        weekly_series=weekly_series,
        structural_window_metrics=structural_window_metrics,
        structural_metrics_load=structural_metrics_load,
        exploratory_horizons=exploratory_horizons,
        structural_history_load=_safe_load_structural_history(paths, ticker),
        foundation_error=None,
    )


def _load_published_structural_metrics(
    paths: ProjectPaths,
    ticker: str,
) -> "StructuralHistoryLoad":
    """Read the full set of structural_window_metrics for one ticker from the
    published parquet, with no recomputation. Returns the same structured load
    result as the chart helper so the workspace can present one consistent
    artifact-health story across the detail page (codex follow-up to Fix #5).
    """
    parquet_path = paths.latest_tool_a_structural_metrics_path
    if not parquet_path.exists():
        return StructuralHistoryLoad(status="missing", history=pd.DataFrame())
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception as exc:
        return StructuralHistoryLoad(
            status="corrupt", history=pd.DataFrame(), error_message=str(exc)
        )
    if frame.empty or "ticker" not in frame.columns:
        return StructuralHistoryLoad(status="no_rows", history=frame)
    normalized = str(ticker).strip().upper()
    filtered = frame.loc[frame["ticker"].astype(str).str.upper() == normalized].copy()
    if filtered.empty:
        return StructuralHistoryLoad(status="no_rows", history=filtered)
    return StructuralHistoryLoad(status="ok", history=filtered)


def _safe_load_structural_history(paths: ProjectPaths, ticker: str) -> "StructuralHistoryLoad":
    """Load the 12M structural-delta history file with a structured result.

    Distinguishes ``missing`` / ``corrupt`` / ``no_rows`` / ``ok`` so the chart
    panel can render the right fallback (codex P2 fix).
    """

    parquet_path = paths.latest_tool_a_structural_metrics_path
    if not parquet_path.exists():
        return StructuralHistoryLoad(status="missing", history=pd.DataFrame())
    try:
        history = _load_structural_delta_history(paths, ticker=ticker, window_id="12M")
    except Exception as exc:  # parquet read error → corrupt
        return StructuralHistoryLoad(
            status="corrupt", history=pd.DataFrame(), error_message=str(exc)
        )
    if history.empty:
        return StructuralHistoryLoad(status="no_rows", history=history)
    return StructuralHistoryLoad(status="ok", history=history)


def _parse_ticker_route(path: str) -> tuple[str, str | None]:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2 or parts[0] != "ticker":
        return "", None
    ticker = parts[1].strip().upper()
    action = parts[2] if len(parts) > 2 else None
    return ticker, action


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
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            f"<td>{_fmt_number(company_row.get('production_oz'), decimals=0)}</td>"
            f"<td>{_fmt_number(company_row.get('aisc_usd_per_oz'), decimals=0)}</td>"
            f"<td>{_fmt_number(tool_a_row.get('structural_delta_core'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get('structural_gamma_core'), decimals=2)}</td>"
            f"<td>{_fmt_number(tool_a_row.get('asymmetry_ratio_core'), decimals=2)}</td>"
            f"<td>{_fmt_text(tool_a_row.get('confidence_label'))}</td>"
            f"<td>{_fmt_text(tool_a_row.get('volatility_context'))}</td>"
            f"<td>{_fmt_number(tool_a_row.get('tool_a_score'), decimals=1)}</td>"
            f"{lens_cell}"
            f"<td>{_fmt_text(tool_a_row.get('profile_label'))}</td>"
            f"<td>{_fmt_number(tool_b_row.get('tool_b_score'), decimals=1)}</td>"
            f"<td>{_fmt_text(tool_b_row.get('screening_verdict'))}</td>"
            f"<td>{row['note_count']}</td>"
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
        f"<th>Lens Score ({escape(lens.title)})</th>" if show_lens_column else ""
    )
    body.append(
        "<h2>Universe Overview</h2>"
        "<table>"
        "<thead><tr>"
        "<th>Ticker</th><th>Production</th><th>AISC</th>"
        "<th>Structural Delta</th><th>Gamma</th><th>Asymmetry</th><th>Confidence</th>"
        "<th>Volatility</th><th>Tool A Score</th>"
        f"{lens_score_header_cell}"
        "<th>Profile</th>"
        "<th>Tool B Score</th><th>Tool B Verdict</th><th>Notes</th>"
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
        "the table is automatically sorted by the lens's score.</p>"
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


def _render_tool_a_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
) -> str:
    """Tool A focused overview: ranked by gold-sensitivity score.

    Shows only Tool A-relevant columns (delta, gamma, asymmetry, confidence,
    volatility, score, rank, profile). No Tool B noise.
    """
    note_counts = (
        state.stock_notes.groupby("ticker").size().to_dict()
        if not state.stock_notes.empty and "ticker" in state.stock_notes.columns
        else {}
    )
    tool_a_index = _frame_index_by_ticker(state.latest_tool_a)
    search_term = str(search or "").strip().upper()

    derived: list[dict[str, Any]] = []
    for ticker in state.tool_b_tickers:
        if search_term and search_term not in ticker:
            continue
        tool_a_row = tool_a_index.get(ticker, {})
        derived.append({
            "ticker": ticker,
            "tool_a_row": tool_a_row,
            "tool_a_rank": _optional_float(tool_a_row.get("tool_a_rank")),
            "note_count": int(note_counts.get(ticker, 0)),
        })
    derived.sort(key=lambda r: (0 if r["tool_a_rank"] is not None else 1,
                                 r["tool_a_rank"] if r["tool_a_rank"] is not None else 0.0,
                                 r["ticker"]))

    rows_html: list[str] = []
    for row in derived:
        ta = row["tool_a_row"]
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            f"<td>{_fmt_text(ta.get('profile_label'))}</td>"
            f"<td>{_fmt_number(ta.get('structural_delta_core'), decimals=2)}</td>"
            f"<td>{_fmt_number(ta.get('structural_gamma_core'), decimals=2)}</td>"
            f"<td>{_fmt_number(ta.get('asymmetry_ratio_core'), decimals=2)}</td>"
            f"<td>{_fmt_text(ta.get('confidence_label'))}</td>"
            f"<td>{_fmt_text(ta.get('volatility_context'))}</td>"
            f"<td>{_fmt_number(ta.get('tool_a_score'), decimals=1)}</td>"
            f"<td>{_fmt_number(row['tool_a_rank'], decimals=0)}</td>"
            f"<td>{row['note_count']}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"10\" class=\"hint\">No tickers match.</td></tr>"
        )

    body = ["<h1>Tool A — Gold Sensitivity Ranking</h1>"]
    body.append(
        "<p>Ranks the universe by structural sensitivity to the gold price. "
        "Lower rank is better. Negative gamma is favorable (up-gold sensitivity exceeds down-gold sensitivity). "
        "Click a ticker for the full structural breakdown and beta-history chart.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-a\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(derived)} tickers shown.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/tool-a\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(
        "<table>"
        "<thead><tr>"
        "<th>Ticker</th><th>Profile</th>"
        "<th>Δ Core</th><th>Gamma</th><th>Asymmetry</th>"
        "<th>Confidence</th><th>Volatility</th>"
        "<th>Tool A Score</th><th>Rank</th><th>Notes</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell("Tool A — Gold Vector Workspace", "".join(body), active_nav="tool_a")


def _render_tool_b_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
) -> str:
    """Tool B focused overview: ranked by valuation-screening score.

    Shows verdict, target price, upside, FCF yield, leverage, etc. Tickers
    marked INCOMPLETE land at the bottom (missing manual data).
    """
    note_counts = (
        state.stock_notes.groupby("ticker").size().to_dict()
        if not state.stock_notes.empty and "ticker" in state.stock_notes.columns
        else {}
    )
    tool_b_index = _frame_index_by_ticker(state.latest_tool_b)
    search_term = str(search or "").strip().upper()

    derived: list[dict[str, Any]] = []
    for ticker in state.tool_b_tickers:
        if search_term and search_term not in ticker:
            continue
        tool_b_row = tool_b_index.get(ticker, {})
        derived.append({
            "ticker": ticker,
            "tool_b_row": tool_b_row,
            "tool_b_rank": _optional_float(tool_b_row.get("tool_b_rank")),
            "note_count": int(note_counts.get(ticker, 0)),
        })
    derived.sort(key=lambda r: (0 if r["tool_b_rank"] is not None else 1,
                                 r["tool_b_rank"] if r["tool_b_rank"] is not None else 0.0,
                                 r["ticker"]))

    rows_html: list[str] = []
    for row in derived:
        tb = row["tool_b_row"]
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            f"<td>{_fmt_text(tb.get('screening_verdict'))}</td>"
            f"<td>{_fmt_number(tb.get('tool_b_score'), decimals=1)}</td>"
            f"<td>{_fmt_number(row['tool_b_rank'], decimals=0)}</td>"
            # Four canonical target-price scenarios (matches Excel Top performers).
            f"<td>{_fmt_number(tb.get('target_price_peer_pe'), decimals=2)}</td>"
            f"<td>{_fmt_percent(tb.get('upside_peer_pe_pct'))}</td>"
            f"<td>{_fmt_number(tb.get('target_price_peak_pe'), decimals=2)}</td>"
            f"<td>{_fmt_percent(tb.get('upside_peak_pe_pct'))}</td>"
            f"<td>{_fmt_number(tb.get('target_price_peer_fcf'), decimals=2)}</td>"
            f"<td>{_fmt_percent(tb.get('upside_peer_fcf_pct'))}</td>"
            f"<td>{_fmt_number(tb.get('target_price_peak_fcf'), decimals=2)}</td>"
            f"<td>{_fmt_percent(tb.get('upside_peak_fcf_pct'))}</td>"
            f"<td>{_fmt_number(tb.get('forward_pe'), decimals=1)}</td>"
            f"<td>{_fmt_percent(tb.get('fcf_yield'))}</td>"
            f"<td>{_fmt_number(tb.get('leverage'), decimals=2)}</td>"
            f"<td>{_fmt_text(tb.get('layer1_status'))}</td>"
            f"<td>{row['note_count']}</td>"
            "</tr>"
        )
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"17\" class=\"hint\">No tickers match.</td></tr>"
        )

    body = ["<h1>Tool B — Valuation Screening</h1>"]
    body.append(
        "<p>Ranks the universe by valuation upside at the configured gold-price assumption. "
        "Lower rank is better. INCOMPLETE rows are missing manual mining inputs (production, AISC, "
        "FCF, etc.). Four target-price scenarios are shown side by side — read across and decide "
        "which scenario fits your view: Peer P/E is the most conservative, Peak FCF the most bullish. "
        "Click a ticker to fill in the manual data form.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-b\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(derived)} tickers shown.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/tool-b\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(
        "<table>"
        "<thead><tr>"
        "<th>Ticker</th><th>Verdict</th>"
        "<th>Score</th><th>Rank</th>"
        "<th>Peer P/E Target</th><th>Peer P/E Up %</th>"
        "<th>Peak P/E Target</th><th>Peak P/E Up %</th>"
        "<th>Peer FCF Target</th><th>Peer FCF Up %</th>"
        "<th>Peak FCF Target</th><th>Peak FCF Up %</th>"
        "<th>Fwd P/E</th><th>FCF Yield</th><th>Leverage</th>"
        "<th>Layer 1</th><th>Notes</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell("Tool B — Gold Vector Workspace", "".join(body), active_nav="tool_b")


def _render_ticker_page(
    state: WorkspaceState,
    *,
    ticker: str,
    tool_a_detail: ToolADetailState,
    flash: str | None,
    error: str | None = None,
) -> str:
    company_row = _frame_index_by_ticker(state.company_inputs).get(ticker, {})
    reporting_row = _frame_index_by_ticker(state.reporting_calendar).get(ticker, {})
    tool_a_row = _frame_index_by_ticker(state.latest_tool_a).get(ticker, {})
    tool_b_row = _frame_index_by_ticker(state.latest_tool_b).get(ticker, {})
    verification_rows = _ticker_rows(state.source_verification, ticker)
    note_rows = _ticker_rows(state.stock_notes, ticker)

    body = [f"<p><a href=\"/\">Back to workspace</a></p>", f"<h1>{escape(ticker)}</h1>"]
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


def _column_unique(frame: pd.DataFrame, column_name: str) -> set[str]:
    if frame.empty or column_name not in frame.columns:
        return set()
    series = frame[column_name].dropna().astype(str)
    return {value for value in series.unique() if value and value.lower() != "nan"}


# Tool A Detail Provenance Rule (plan v3 §1): foundation-backed panels on the
# detail page must match the displayed Tool A row's snapshot_refresh_run_id.
# When they don't, each panel is suppressed with a visible fallback card rather
# than rendered with stale numbers.
DETAIL_ALIGNMENT_ALIGNED = "ALIGNED"
DETAIL_ALIGNMENT_FOUNDATION_AHEAD = "FOUNDATION_AHEAD"
DETAIL_ALIGNMENT_FOUNDATION_MISSING = "FOUNDATION_MISSING"
DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH = "TOOL_A_MISSING_REFRESH"


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


def _render_latest_panels(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    tool_b_row: dict[str, Any],
    tool_a_detail: ToolADetailState,
    alignment: str,
) -> str:
    return (
        _render_tool_a_panel(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
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

    body = [
        "<section class=\"panel\">",
        "<h2>Structural Tool A</h2>",
        "<p class=\"hint\">Official Tool A now uses weekly structural delta, regime-split gamma, explicit asymmetry, "
        "confidence, and volatility diagnostics. The horizon-return ladder below is exploratory only.</p>",
        _render_signal_notice(tool_a_row),
        _render_detail_alignment_notice(alignment),
        _render_structural_metrics_load_notice(tool_a_detail.structural_metrics_load),
        "<div class=\"metric-grid\">",
        _metric_card("As Of", _fmt_text(tool_a_row.get("as_of_date"))),
        _metric_card("Anchor Window", _fmt_text(tool_a_row.get("anchor_window_id"))),
        _metric_card("Structural Delta", _fmt_number(tool_a_row.get("structural_delta_core"), decimals=2)),
        _metric_card("Gamma (Down-Up)", _fmt_number(tool_a_row.get("structural_gamma_core"), decimals=2)),
        _metric_card("Asymmetry", _fmt_number(tool_a_row.get("asymmetry_ratio_core"), decimals=2)),
        _metric_card("Confidence", _fmt_text(tool_a_row.get("confidence_label"))),
        _metric_card("Volatility", _fmt_text(tool_a_row.get("volatility_context"))),
        _metric_card("Tool A Score", _fmt_number(tool_a_row.get("tool_a_score"), decimals=1)),
        _metric_card("Profile", _fmt_text(tool_a_row.get("profile_label"))),
        "</div>",
        _render_explanation_cards(tool_a_row),
        _render_structural_window_table(tool_a_row),
        _render_visual_panels(
            ticker=ticker,
            tool_a_row=tool_a_row,
            tool_a_detail=tool_a_detail,
            alignment=alignment,
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


def _render_explanation_cards(tool_a_row: dict[str, Any]) -> str:
    cards = [
        ("Delta", tool_a_row.get("delta_explanation")),
        ("Gamma", tool_a_row.get("gamma_explanation")),
        ("Asymmetry", tool_a_row.get("asymmetry_explanation")),
        ("Volatility", tool_a_row.get("volatility_explanation")),
        ("Confidence", tool_a_row.get("confidence_explanation")),
        ("Interaction", tool_a_row.get("interaction_explanation")),
        ("Summary", tool_a_row.get("tool_a_summary_explanation")),
    ]
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


def _render_structural_window_table(tool_a_row: dict[str, Any]) -> str:
    window_rows = []
    anchor_window_id = str(tool_a_row.get("anchor_window_id") or "").upper()
    for window_id in ("6M", "12M", "3Y"):
        normalized = window_id.lower()
        anchor_marker = " (Anchor)" if window_id == anchor_window_id else ""
        window_rows.append(
            "<tr>"
            f"<td>{window_id}{anchor_marker}</td>"
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
) -> str:
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
            + _render_volatility_panel(tool_a_row)
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
    anchor_metric = _anchor_window_metric(tool_a_row, tool_a_detail)
    anchor_sample = _anchor_window_sample(tool_a_row, tool_a_detail)
    # Phase 2B: rolling 12M structural delta. Has its own provenance gate
    # (source_run_id), separate from the foundation-backed alignment used by
    # the panels above. Always rendered; the panel itself handles its empty
    # and out-of-sync states.
    beta_history_panel = _render_beta_history_panel(
        ticker=ticker,
        tool_a_row=tool_a_row,
        structural_history_load=tool_a_detail.structural_history_load,
    )
    # Chart placement (post-deep-review): the rolling-delta chart is the most
    # paper-aligned visual on the detail page, so it sits immediately under the
    # scatter / up-down-beta row, above the volatility and exploratory panels.
    return (
        "<div class=\"two-up\">"
        f"{_render_scatter_panel(ticker=ticker, tool_a_row=tool_a_row, anchor_metric=anchor_metric, anchor_sample=anchor_sample)}"
        f"{_render_up_down_beta_panel(tool_a_row, anchor_metric=anchor_metric)}"
        "</div>"
        f"{beta_history_panel}"
        "<div class=\"two-up\">"
        f"{_render_volatility_panel(tool_a_row)}"
        f"{_render_exploratory_horizon_panel(tool_a_detail.exploratory_horizons)}"
        "</div>"
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
) -> str:
    if anchor_sample.empty:
        return (
            "<section class=\"panel nested-panel\">"
            "<h3>Weekly Return Scatter</h3>"
            "<p>No weekly return detail is available yet.</p>"
            "</section>"
        )
    regression_beta = _optional_float(anchor_metric.get("structural_delta"))
    regression_alpha = _optional_float(anchor_metric.get("intercept_alpha"))
    anchor_window_id = _fmt_text(tool_a_row.get("anchor_window_id"))
    svg = _build_scatter_svg(
        x_values=anchor_sample["gold_weekly_log_return"].tolist(),
        y_values=anchor_sample["stock_weekly_log_return"].tolist(),
        regression_beta=regression_beta,
        regression_alpha=regression_alpha,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Weekly Return Scatter</h3><p class=\"hint\">{escape(ticker)} weekly log returns vs gold weekly log returns over the official {anchor_window_id} anchor sample.</p>"
        f"{svg}"
        "</section>"
    )


def _render_up_down_beta_panel(
    tool_a_row: dict[str, Any],
    *,
    anchor_metric: dict[str, Any],
) -> str:
    up_beta = _optional_float(anchor_metric.get("up_beta"))
    down_beta = _optional_float(anchor_metric.get("down_beta"))
    anchor_window_id = _fmt_text(tool_a_row.get("anchor_window_id"))
    if up_beta is None and down_beta is None:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Up vs Down Beta</h3><p>No {anchor_window_id} regime split is available yet.</p>"
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
        f"<p class=\"hint\">This shows the official {anchor_window_id} regime split. Positive gamma means down-gold sensitivity is stronger than up-gold sensitivity.</p>"
        f"{svg}"
        "</section>"
    )


def _render_volatility_panel(tool_a_row: dict[str, Any]) -> str:
    return (
        "<section class=\"panel nested-panel\">"
        "<h3>Volatility Diagnostics</h3>"
        "<div class=\"metric-grid\">"
        f"{_metric_card('Total Volatility (Annualized Log Vol)', _fmt_percent(tool_a_row.get('total_volatility_52w'), decimals=1))}"
        f"{_metric_card('Residual Volatility (Annualized Log Vol)', _fmt_percent(tool_a_row.get('residual_volatility_52w'), decimals=1))}"
        f"{_metric_card('Downside Volatility (Annualized Log Vol)', _fmt_percent(tool_a_row.get('downside_volatility_52w'), decimals=1))}"
        f"{_metric_card('Volatility Context', _fmt_text(tool_a_row.get('volatility_context')))}"
        "</div>"
        "</section>"
    )


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


def _fmt_note_tag(value: Any) -> str:
    text = _fmt_text(value)
    if text == "-":
        return text
    return f"<span class=\"badge note-tag\">{text}</span>"


def _render_small_table(title: str, row: dict[str, Any], columns: list[str]) -> str:
    if not row:
        return (
            "<section class=\"panel\">"
            f"<h2>{escape(title)}</h2>"
            "<p>No latest output is available yet.</p>"
            "</section>"
        )
    rows_html = "".join(
        "<tr>"
        f"<th>{escape(_humanize_column_name(column_name))}</th>"
        f"<td>{_fmt_value(row.get(column_name), column_name)}</td>"
        "</tr>"
        for column_name in columns
        if column_name in row
    )
    return (
        "<section class=\"panel\">"
        f"<h2>{escape(title)}</h2>"
        f"<table><tbody>{rows_html}</tbody></table>"
        "</section>"
    )


def _metric_card(title: str, value: str) -> str:
    return (
        "<article class=\"panel metric-card\">"
        f"<h3>{escape(title)}</h3><p>{value}</p>"
        "</article>"
    )


_NAV_LINKS: tuple[tuple[str, str, str], ...] = (
    ("combined", "/", "Combined"),
    ("tool_a", "/tool-a", "Tool A"),
    ("tool_b", "/tool-b", "Tool B"),
)


def _render_top_nav(active: str) -> str:
    items = []
    for nav_id, href, label in _NAV_LINKS:
        cls = "nav-tab active" if nav_id == active else "nav-tab"
        items.append(f"<a class=\"{cls}\" href=\"{escape(href)}\">{escape(label)}</a>")
    return f"<nav class=\"top-nav\">{''.join(items)}</nav>"


def _page_shell(title: str, body: str, *, active_nav: str = "") -> str:
    nav_html = _render_top_nav(active_nav) if active_nav else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #f5f1e7;
      --panel: #fffdf8;
      --ink: #1f1d1a;
      --muted: #6f685c;
      --line: #d8cfbf;
      --accent: #b26700;
      --accent-soft: #f8ead4;
      --positive: #2d6a4f;
      --negative: #8a2d3b;
      --neutral: #48566a;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: linear-gradient(180deg, #f1eadb 0%, var(--bg) 100%);
      color: var(--ink);
    }}
    main {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    h1, h2, h3 {{
      margin-top: 0;
    }}
    p, li {{
      line-height: 1.5;
    }}
    a {{
      color: #1d4b73;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 16px 18px;
      margin-bottom: 18px;
      box-shadow: 0 8px 24px rgba(98, 83, 57, 0.08);
    }}
    .nested-panel {{
      margin-bottom: 0;
    }}
    .two-up {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 18px;
      margin-bottom: 18px;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .metric-card {{
      margin-bottom: 0;
      min-height: 88px;
    }}
    .metric-card h3 {{
      font-size: 0.9rem;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .metric-card p {{
      font-size: 1.05rem;
      margin: 0;
    }}
    .explanation-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }}
    .explanation-card {{
      margin-bottom: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }}
    thead th {{
      background: #f7f0e2;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .form-grid label, .note-form label, .verification-form label {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 0.92rem;
    }}
    .badge {{
      display: inline-block;
      font-size: 0.7rem;
      font-style: normal;
      font-weight: 600;
      letter-spacing: 0.04em;
      padding: 2px 8px;
      border-radius: 999px;
      margin-left: 6px;
      vertical-align: middle;
      background: #efe6d3;
      color: #5b4d33;
    }}
    .badge-verified  {{ background: #d8eccf; color: #1f4c2a; }}
    .badge-estimated {{ background: #f4e3b6; color: #6c4a16; }}
    .badge-incomplete{{ background: #f1cdcd; color: #6e1d1d; }}
    .badge-needs     {{ background: #e6dcc4; color: #5b4d33; }}
    .badge-missing   {{ background: #f1cdcd; color: #6e1d1d; }}
    .note-badge      {{ margin-left: 0; }}
    .note-open       {{ background: #d8eccf; color: #1f4c2a; }}
    .note-watch      {{ background: #f4e3b6; color: #6c4a16; }}
    .note-done       {{ background: #d8d4cb; color: #4b463c; }}
    .note-tag        {{ background: #efe6d3; color: #5b4d33; margin-left: 0; }}
    .note-text       {{ white-space: pre-wrap; }}
    .clear-toggle    {{
      font-size: 0.78rem;
      color: var(--muted);
      display: inline-flex;
      gap: 4px;
      align-items: center;
      margin-top: 4px;
    }}
    .clear-toggle input {{
      width: auto;
      padding: 0;
      margin: 0;
    }}
    .tool-b-readiness {{
      background: var(--accent-soft);
      border: 1px solid #ebcd9f;
      border-radius: 10px;
      padding: 10px 12px;
      margin-bottom: 8px;
    }}
    .overview-filters-form {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      align-items: end;
    }}
    .overview-filters-form label {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      font-size: 0.88rem;
    }}
    .overview-filters-actions {{
      grid-column: 1 / -1;
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: flex-end;
    }}
    .verification-form {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      align-items: end;
    }}
    .verification-form .verification-cell {{
      font-size: 0.88rem;
    }}
    .verification-form .verification-actions {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    table.verification-table td, table.verification-table th {{
      vertical-align: top;
    }}
    .full-width {{
      grid-column: 1 / -1;
    }}
    input, textarea, select, button {{
      font: inherit;
    }}
    input, textarea, select {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 10px 12px;
      background: white;
    }}
    button {{
      border: 0;
      border-radius: 999px;
      padding: 10px 16px;
      background: var(--accent);
      color: white;
      cursor: pointer;
    }}
    .form-actions {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: flex-start;
      align-items: end;
    }}
    .flash {{
      margin-bottom: 16px;
      padding: 12px 14px;
      background: var(--accent-soft);
      border: 1px solid #ebcd9f;
      border-radius: 10px;
    }}
    .hint {{
      color: var(--muted);
    }}
    svg {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .top-nav {{
      max-width: 1240px;
      margin: 0 auto;
      padding: 18px 20px 0;
      display: flex;
      gap: 8px;
      border-bottom: 1px solid var(--line);
    }}
    .nav-tab {{
      padding: 10px 18px;
      border: 1px solid var(--line);
      border-bottom: none;
      border-radius: 8px 8px 0 0;
      background: var(--panel);
      color: var(--ink);
      text-decoration: none;
      font-weight: 600;
      font-size: 0.95rem;
    }}
    .nav-tab.active {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    .nav-tab:hover:not(.active) {{
      background: var(--accent-soft);
    }}
  </style>
</head>
<body>
  {nav_html}
  <main>{body}</main>
</body>
</html>"""


def _frame_index_by_ticker(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for record in frame.to_dict(orient="records"):
        ticker = str(record.get("ticker") or "").upper()
        if ticker:
            indexed[ticker] = record
    return indexed


def _ticker_rows(frame: pd.DataFrame, ticker: str) -> list[dict[str, Any]]:
    if frame.empty or "ticker" not in frame.columns:
        return []
    return frame[frame["ticker"].astype(str).str.upper() == ticker].to_dict(orient="records")


def _flash_message(saved_token: str) -> str | None:
    messages = {
        "company": "Company inputs saved.",
        "reporting": "Reporting calendar saved.",
        "note": "Stock note added.",
        "verification": "Source verification updated.",
    }
    return messages.get(saved_token)


def _render_error_page(message: str, *, detail: str | None = None) -> str:
    detail_html = f"<p class=\"hint\">{escape(detail)}</p>" if detail else ""
    return _page_shell(
        "Golden Vector Workspace Error",
        f"<h1>Workspace Error</h1><div class=\"panel\"><p>{escape(message)}</p>{detail_html}<p><a href=\"/\">Back to workspace</a></p></div>",
        active_nav="combined",
    )


def _humanize_column_name(value: str) -> str:
    return value.replace("_", " ").strip().title()


def _fmt_text(value: Any) -> str:
    if value is None:
        return "-"
    try:
        if pd.isna(value):
            return "-"
    except TypeError:
        pass
    text = str(value).strip()
    return escape(text) if text else "-"


def _fmt_number(value: Any, *, decimals: int) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt_text(value)
    if pd.isna(numeric):
        return "-"
    return escape(f"{numeric:,.{decimals}f}")


def _fmt_percent(value: Any, *, decimals: int = 1) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _fmt_text(value)
    if pd.isna(numeric):
        return "-"
    return escape(f"{numeric * 100:,.{decimals}f}%")


def _fmt_value(value: Any, column_name: str) -> str:
    if column_name in RATE_FIELDS.union({"best_upside_pct"}).union(TOOL_A_PERCENT_FIELDS):
        return _fmt_percent(value)
    if column_name.endswith("_rank"):
        return _fmt_number(value, decimals=0)
    if column_name in TOOL_A_NUMERIC_FIELDS:
        return _fmt_number(value, decimals=2)
    if isinstance(value, (int, float)):
        return _fmt_number(value, decimals=2)
    return _fmt_text(value)


def _format_form_value(field_name: str, value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    if field_name in RATE_FIELDS:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{numeric * 100:g}"
    return str(value)


def _coerce_form_numeric(value: str) -> float | None:
    text = str(value).strip()
    if not text:
        return None
    percent_suffix = text.endswith("%")
    if percent_suffix:
        text = text[:-1].strip()
    try:
        numeric = float(text)
    except ValueError as exc:
        raise ValueError("Numeric fields must be numeric.") from exc
    if percent_suffix:
        return numeric / 100.0
    return numeric


def _coerce_form_text(value: str) -> str | None:
    text = str(value).strip()
    return text or None


def _read_optional_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_form_data(environ: dict[str, Any]) -> dict[str, list[str]]:
    try:
        content_length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        content_length = 0
    body = environ.get("wsgi.input", io.BytesIO()).read(content_length)
    return parse_qs(body.decode("utf-8"), keep_blank_values=True)


def _html_response(
    start_response: Callable[..., Any],
    body: str,
    *,
    status: str = "200 OK",
) -> Iterable[bytes]:
    payload = body.encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(payload))),
        ],
    )
    return [payload]


def _redirect_response(start_response: Callable[..., Any], location: str) -> Iterable[bytes]:
    start_response(
        "303 See Other",
        [("Location", location), ("Content-Length", "0")],
    )
    return [b""]


def _build_scatter_svg(
    *,
    x_values: list[float],
    y_values: list[float],
    regression_beta: float | None,
    regression_alpha: float | None,
) -> str:
    if not x_values or not y_values:
        return "<p>No scatter data available.</p>"
    width = 360
    height = 260
    padding = 32
    max_abs = max([abs(value) for value in x_values + y_values] + [0.01])
    domain = max_abs * 1.1

    def sx(value: float) -> float:
        return padding + ((value + domain) / (2 * domain)) * (width - (2 * padding))

    def sy(value: float) -> float:
        return height - padding - ((value + domain) / (2 * domain)) * (height - (2 * padding))

    points = "".join(
        f"<circle cx=\"{sx(float(x)):.1f}\" cy=\"{sy(float(y)):.1f}\" r=\"3.2\" fill=\"#1d4b73\" opacity=\"0.72\" />"
        for x, y in zip(x_values, y_values, strict=False)
    )
    line = ""
    if regression_beta is not None and regression_alpha is not None:
        x1 = -domain
        y1 = regression_alpha + (regression_beta * x1)
        x2 = domain
        y2 = regression_alpha + (regression_beta * x2)
        line = (
            f"<line x1=\"{sx(x1):.1f}\" y1=\"{sy(y1):.1f}\" "
            f"x2=\"{sx(x2):.1f}\" y2=\"{sy(y2):.1f}\" stroke=\"#b26700\" stroke-width=\"2\" />"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Weekly return scatter\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"<line x1=\"{padding}\" y1=\"{sy(0):.1f}\" x2=\"{width - padding}\" y2=\"{sy(0):.1f}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />"
        f"<line x1=\"{sx(0):.1f}\" y1=\"{padding}\" x2=\"{sx(0):.1f}\" y2=\"{height - padding}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />"
        f"{line}{points}"
        f"<text x=\"{padding}\" y=\"20\" font-size=\"12\" fill=\"#6f685c\">Stock weekly return</text>"
        f"<text x=\"{width - 150}\" y=\"{height - 10}\" font-size=\"12\" fill=\"#6f685c\">Gold weekly return</text>"
        "</svg>"
    )


def _build_dual_bar_svg(
    *,
    left_label: str,
    left_value: float,
    right_label: str,
    right_value: float,
) -> str:
    width = 360
    height = 220
    padding = 28
    max_value = max(abs(left_value), abs(right_value), 0.25)
    plot_height = height - (2 * padding) - 30
    baseline = padding + (plot_height / 2)

    def bar_height(value: float) -> float:
        return (abs(value) / max_value) * (plot_height / 2)

    def bar_y(value: float) -> float:
        return baseline - bar_height(value) if value >= 0 else baseline

    def bar_color(value: float) -> str:
        return "#2d6a4f" if value >= 0 else "#8a2d3b"

    bars = []
    for x_pos, label, value in ((95, left_label, left_value), (235, right_label, right_value)):
        height_value = bar_height(value)
        bars.append(
            f"<rect x=\"{x_pos}\" y=\"{bar_y(value):.1f}\" width=\"40\" height=\"{height_value:.1f}\" fill=\"{bar_color(value)}\" opacity=\"0.85\" rx=\"6\" ry=\"6\" />"
        )
        bars.append(
            f"<text x=\"{x_pos + 20}\" y=\"{height - 18}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#6f685c\">{escape(label)}</text>"
        )
        bars.append(
            f"<text x=\"{x_pos + 20}\" y=\"{bar_y(value) - 8 if value >= 0 else bar_y(value) + height_value + 16:.1f}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#1f1d1a\">{value:,.2f}</text>"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Up beta versus down beta\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"<line x1=\"{padding}\" y1=\"{baseline:.1f}\" x2=\"{width - padding}\" y2=\"{baseline:.1f}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />"
        f"{''.join(bars)}"
        "</svg>"
    )


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return numeric


# ----------------------- Phase 2B: 12M rolling structural delta chart ----------------------


def _load_structural_delta_history(
    paths: ProjectPaths,
    *,
    ticker: str,
    window_id: str = "12M",
) -> pd.DataFrame:
    """Read the published structural-metrics parquet for one ticker / window.

    Returns rows where ``window_status == 'ELIGIBLE'`` and ``structural_delta`` is
    finite, sorted by ``as_of_date``. Carries ``source_run_id`` for the Phase 1A
    provenance check. Empty DataFrame if the file is missing or no eligible rows
    exist for the ticker.
    """

    parquet_path = paths.latest_tool_a_structural_metrics_path
    if not parquet_path.exists():
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    frame = pd.read_parquet(parquet_path)
    if frame.empty or "ticker" not in frame.columns:
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    normalized_ticker = str(ticker).strip().upper()
    normalized_window = str(window_id).strip().upper()
    mask = (
        (frame["ticker"].astype(str).str.upper() == normalized_ticker)
        & (frame["window_id"].astype(str).str.upper() == normalized_window)
        & (frame.get("window_status", pd.Series(dtype=str)).astype(str).str.upper() == "ELIGIBLE")
    )
    history = frame.loc[mask].copy()
    if history.empty:
        return pd.DataFrame(
            columns=["ticker", "as_of_date", "window_id", "structural_delta", "source_run_id"]
        )
    history["structural_delta"] = pd.to_numeric(history["structural_delta"], errors="coerce")
    history = history.loc[history["structural_delta"].notna()].copy()
    history["as_of_date"] = pd.to_datetime(history["as_of_date"], errors="coerce")
    history = history.loc[history["as_of_date"].notna()].copy()
    history = history.sort_values("as_of_date").reset_index(drop=True)
    return history


def _structural_history_matches_tool_a(
    structural_history: pd.DataFrame,
    tool_a_row: dict[str, Any],
) -> bool:
    """Phase 2B provenance gate.

    The history rows carry ``source_run_id`` (added in Phase 1A). The Tool A row
    also carries ``source_run_id``. They must match for the chart to render —
    otherwise the structural file was produced by a different ``tool-a`` run and
    might not reflect the published row.
    """

    if structural_history.empty or "source_run_id" not in structural_history.columns:
        return False
    tool_a_run_id = str(tool_a_row.get("source_run_id") or "").strip()
    if not tool_a_run_id or tool_a_run_id.lower() == "nan":
        return False
    history_ids = {
        str(value).strip()
        for value in structural_history["source_run_id"].dropna().unique()
    }
    return history_ids == {tool_a_run_id}


def _build_beta_history_svg(
    *,
    dates: list[pd.Timestamp],
    deltas: list[float],
    current_delta_core: float | None,
) -> str:
    """SVG line chart of structural_delta over time.

    The rebased gold overlay was removed in the post-deep-review fix pass: it was
    ambiguous (rebased onto the beta y-axis it didn't communicate gold prices, only
    co-movement). If gold context is wanted later, ship a separate sparkline beneath
    the chart.
    """

    width = 720
    height = 240
    padding_left = 44
    padding_right = 24
    padding_top = 20
    padding_bottom = 28
    inner_w = width - padding_left - padding_right
    inner_h = height - padding_top - padding_bottom

    if not dates or not deltas or len(dates) != len(deltas):
        return "<p>No beta history data available.</p>"

    # X scale: index → x position (treat dates as evenly spaced for a clean v1 line)
    n = len(deltas)
    def x_at(i: int) -> float:
        if n <= 1:
            return padding_left + inner_w / 2
        return padding_left + (i / (n - 1)) * inner_w

    # Y scale: deltas → y position (anchor at 0 on the visible band)
    delta_lo = min(deltas + [0.0])
    delta_hi = max(deltas + [0.0])
    if current_delta_core is not None:
        delta_lo = min(delta_lo, current_delta_core)
        delta_hi = max(delta_hi, current_delta_core)
    if delta_hi == delta_lo:
        delta_hi = delta_lo + 1.0
    pad = (delta_hi - delta_lo) * 0.1
    delta_lo -= pad
    delta_hi += pad

    def y_at(value: float) -> float:
        return padding_top + (1.0 - (value - delta_lo) / (delta_hi - delta_lo)) * inner_h

    beta_points = " ".join(f"{x_at(i):.1f},{y_at(d):.1f}" for i, d in enumerate(deltas))
    grid_zero = ""
    if delta_lo <= 0.0 <= delta_hi:
        grid_zero = (
            f"<line x1=\"{padding_left}\" y1=\"{y_at(0.0):.1f}\" "
            f"x2=\"{width - padding_right}\" y2=\"{y_at(0.0):.1f}\" "
            f"stroke=\"#bfb5a2\" stroke-width=\"1\" stroke-dasharray=\"3 3\" />"
        )
    grid_core = ""
    if current_delta_core is not None:
        grid_core = (
            f"<line x1=\"{padding_left}\" y1=\"{y_at(current_delta_core):.1f}\" "
            f"x2=\"{width - padding_right}\" y2=\"{y_at(current_delta_core):.1f}\" "
            f"stroke=\"#b26700\" stroke-width=\"1\" stroke-dasharray=\"4 2\" opacity=\"0.65\" />"
        )

    # Y-axis labels (lo / hi)
    y_labels = (
        f"<text x=\"{padding_left - 6}\" y=\"{y_at(delta_hi) + 4:.1f}\" "
        f"text-anchor=\"end\" font-size=\"11\" fill=\"#6f685c\">{delta_hi:.1f}</text>"
        f"<text x=\"{padding_left - 6}\" y=\"{y_at(delta_lo) + 4:.1f}\" "
        f"text-anchor=\"end\" font-size=\"11\" fill=\"#6f685c\">{delta_lo:.1f}</text>"
    )

    # Date range labels (first / last only)
    first_date = dates[0]
    last_date = dates[-1]
    date_labels = (
        f"<text x=\"{padding_left}\" y=\"{height - 8}\" font-size=\"11\" fill=\"#6f685c\">"
        f"{first_date.strftime('%Y-%m-%d')}</text>"
        f"<text x=\"{width - padding_right}\" y=\"{height - 8}\" text-anchor=\"end\" "
        f"font-size=\"11\" fill=\"#6f685c\">{last_date.strftime('%Y-%m-%d')}</text>"
    )

    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"12M rolling structural delta\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"{grid_zero}{grid_core}"
        f"<polyline points=\"{beta_points}\" fill=\"none\" stroke=\"#1d4b73\" stroke-width=\"1.8\" />"
        f"{y_labels}{date_labels}"
        "</svg>"
    )


def _render_beta_history_panel(
    *,
    ticker: str,
    tool_a_row: dict[str, Any],
    structural_history_load: "StructuralHistoryLoad",
) -> str:
    """Render the 12M rolling structural-delta panel.

    Per plan v3 §5 and the post-deep-review fix pass:
    - The chart uses only ``source_run_id`` for its provenance gate. The rebased
      gold overlay was removed because it wasn't numerically interpretable.
    - The four empty states are now distinguished by the structured load result
      (missing / corrupt / no_rows / ok), not by checking ``DataFrame.empty`` alone.
    """

    title = "12M Rolling Structural Delta"

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
            "This ticker does not have enough clean 12M structural history to plot yet. "
            "Run <code>python main.py tool-a</code> after a fresh data refresh.",
        )

    if not _structural_history_matches_tool_a(structural_history, tool_a_row):
        return _render_chart_fallback_panel(
            title,
            "Structural history file is out of sync with the published Tool A row.",
            "python main.py tool-a",
        )

    deltas = structural_history["structural_delta"].astype(float).tolist()
    dates = list(structural_history["as_of_date"])

    current_delta_core = _optional_float(tool_a_row.get("structural_delta_core"))
    score_eligible = bool(tool_a_row.get("score_eligible"))
    watermark = ""
    if not score_eligible:
        watermark = (
            "<p class=\"hint\"><em>Current snapshot score for this stock is withheld; "
            "historical series shown for context only.</em></p>"
        )

    svg = _build_beta_history_svg(
        dates=dates,
        deltas=deltas,
        current_delta_core=current_delta_core,
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)}</h3>"
        "<p class=\"hint\">How this stock's weekly structural beta to gold has moved over time. "
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


@dataclass(frozen=True)
class StructuralHistoryLoad:
    """Structured load result for the beta-history parquet, per codex P2 fix.

    Distinguishes the file states the workspace must communicate differently:
    - ``ok`` — file loaded; ``history`` is the filtered DataFrame
    - ``missing`` — file does not exist on disk
    - ``no_rows`` — file exists but no eligible rows for the ticker / window
    - ``corrupt`` — file exists but pandas couldn't read it (or wrong shape)
    """

    status: str
    history: pd.DataFrame
    error_message: str | None = None
