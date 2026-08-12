"""Tool D overview rendering for the workspace UI."""

from __future__ import annotations

import math
from html import escape
from time import perf_counter
from urllib.parse import quote, urlencode

import pandas as pd

from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import (
    read_current_model_parquet,
    resolve_current_foundation_manifest_path,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.fundamentals.artifacts import load_official_fundamentals
from golden_vector.model.tool_d import (
    ToolDExecutionInputs,
    compute_tool_d_outputs,
    latest_gold_price_from_history,
    tool_d_stress_scenario_presets,
)
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.pipeline import normalize_finance_source
from golden_vector.screening.schema import ToolBStaleSchemaError, validate_tool_b_output_schema
from golden_vector.serve.format_helpers import (
    _first_frame_number,
    _fmt_numeric_td,
    _fmt_text,
)
from golden_vector.serve.fundamentals_provenance import (
    load_fundamentals_provenance_lookup,
    ticker_provenance_icon,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.overview_helpers import (
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.column_help import help_th
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import page_header
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.serve.workspace_state import WorkspaceState, select_tool_d_source_rows


def _yahoo_scenario_error(
    exc: Exception,
    *,
    requested_gold: float | None = None,
    spot_gold: float | None = None,
) -> str:
    """Truthful Yahoo custom-scenario failure with no alternate-source fallback."""

    message = f"Could not compute Yahoo Fundamentals stress scenario: {exc}"
    if requested_gold is not None:
        message += (
            f" Your requested gold price of ${requested_gold:,.0f} was NOT applied; "
            "the table below remains the persisted selected-source spot run"
        )
        message += (
            f" (spot ${spot_gold:,.0f})." if spot_gold is not None else "."
        )
    return message


def _render_tool_d_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    app_config: AppConfig,
    paths: ProjectPaths,
    query: dict[str, list[str]] | None = None,
    search: str = "",
) -> str:
    """Render the Tool D corporate-resilience stress lens."""

    query = query or {}
    requested_gold, gold_price_error = _requested_gold_price(query)
    # Accumulate notices: a gold-price validation error and a later Yahoo-scenario
    # error are independent facts and must both reach the user.
    scenario_errors: list[str] = [gold_price_error] if gold_price_error else []
    finance_source = normalize_finance_source(
        (query.get("fundamentals_source", ["our"])[0] or "our")
    )
    persisted_selection = select_tool_d_source_rows(
        state.latest_tool_d,
        finance_source=finance_source,
        label="the Corporate Resilience overview",
    )
    frame = persisted_selection.frame
    scenario_seconds: float | None = None
    scenario_message: str | None = None
    # Both at-spot sources are persisted. Only a non-spot gold request keeps
    # the sanctioned scenario recompute path (plan D15).
    if requested_gold is not None:
        try:
            start = perf_counter()
            frame = _compute_scenario_frame(
                paths=paths,
                app_config=app_config,
                gold_price=requested_gold,
                finance_source=finance_source,
            )
            scenario_seconds = perf_counter() - start
            scenario_message = (
                f"Scenario recomputed in {scenario_seconds:.2f}s. "
                "Persisted spot output was not changed."
            )
        except ToolBStaleSchemaError:
            raise
        except Exception as exc:
            if finance_source == "yahoo":
                scenario_errors.append(
                    _yahoo_scenario_error(
                        exc,
                        requested_gold=requested_gold,
                        spot_gold=_first_number(frame, "spot_gold_usd"),
                    )
                )
            else:
                scenario_errors.append(f"Could not compute stress scenario: {exc}")

    if frame.empty and persisted_selection.reason and requested_gold is None:
        scenario_errors.append(persisted_selection.reason)

    search_term = str(search or "").strip().upper()
    if not frame.empty and search_term and "ticker" in frame.columns:
        frame = frame.loc[
            frame["ticker"].astype(str).str.upper().str.contains(search_term, na=False)
        ].copy()
    # Row order is owned by the writer: golden_vector/model/tool_d.py sorts its
    # output by (tool_d_quality_rank desc, ticker asc) before persisting, and the
    # scenario recompute goes through the same writer. Serve never re-sorts.

    spot_gold = _first_number(frame, "spot_gold_usd") or _first_number(
        persisted_selection.frame,
        "spot_gold_usd",
    )
    active_gold = _first_number(frame, "gold_price_used") or requested_gold or spot_gold
    # Canon: degraded rows are EXCLUDED from confident headlines, not just flagged.
    # The writer already nulls tool_d_quality_rank when resilience_data_status is
    # not OK, so the flip panel must apply the same gate.
    if (
        not frame.empty
        and {"resilience_flip_flags", "resilience_data_status"}.issubset(frame.columns)
    ):
        flip_rows = frame.loc[
            frame["resilience_flip_flags"].notna()
            & frame["resilience_data_status"].astype(str).eq("OK")
        ].copy()
    else:
        flip_rows = frame.iloc[0:0].copy()
    fundamentals_provenance = (
        load_fundamentals_provenance_lookup(paths)
        if finance_source == "yahoo"
        else {}
    )

    body = [page_header(
        "Corporate Resilience",
        lead_html=(
            "<p>Stress-test view: how far gold can fall before a miner reaches "
            "its survival lines, and how quickly balance-sheet risk deteriorates.</p>"
            "<p class=\"hint\">Simple transparent model. It does not model "
            "cash-runway duration, debt maturity walls, or gold hedging because "
            "those inputs are not in the local data.</p>"
        ),
    )]
    if flash:
        body.append(notice("success", escape(flash)))
    for scenario_error in scenario_errors:
        body.append(notice("danger", escape(scenario_error)))
    if scenario_message:
        body.append(notice("info", escape(scenario_message)))
    if not state.tool_d_alias_present:
        body.append(notice(
            "warning",
            "Corporate Resilience output is missing. "
            "Run <code>python main.py tool-d</code> after Corporate Finance.",
        ))
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        _render_scenario_form(
            search=search,
            spot_gold=spot_gold,
            active_gold=active_gold,
            requested_gold=requested_gold,
            finance_source=finance_source,
        )
    )
    body.append(
        _render_flip_section(
            flip_rows,
            app_config=app_config,
            finance_source=finance_source,
            fundamentals_provenance=fundamentals_provenance,
        )
    )
    # Truthful legacy state: a pre-v2 Tool D artifact has only the old `aisc_margin_yield`
    # column, so the FCF Yield @ G cells would silently render the missing-value
    # placeholder. Say so instead. Presence check only — no arithmetic in serve.
    legacy_fcf_schema = not frame.empty and "aisc_margin_yield_at_g" not in frame.columns
    if legacy_fcf_schema:
        body.append(notice(
            "warning",
            "This table was built before the FCF-yield fix (Tool D schema v1). "
            "FCF Yield @ G shows 'pending rebuild' until the next data refresh.",
        ))
    body.append(
        _render_table(
            frame,
            app_config=app_config,
            finance_source=finance_source,
            fundamentals_provenance=fundamentals_provenance,
            legacy_fcf_schema=legacy_fcf_schema,
        )
    )
    return _page_shell(
        "Corporate Resilience - Golden Vector Workspace",
        "".join(body),
        active_nav="tool_d",
    )


def _compute_scenario_frame(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    gold_price: float | None,
    finance_source: str = "our",
) -> pd.DataFrame:
    foundation_snapshot = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=True,
        include_equity_histories=False,
        include_market_snapshots=True,
        manifest_path=resolve_current_foundation_manifest_path(
            paths,
            require_current_manifest=True,
        ),
    )
    spot_gold_usd, spot_gold_date = latest_gold_price_from_history(
        foundation_snapshot.gold_history
    )
    resolved_gold_price = float(gold_price) if gold_price is not None else spot_gold_usd
    tool_b_latest = validate_tool_b_output_schema(
        read_current_model_parquet(
            paths,
            "tool_b",
            fallback_path=paths.latest_tool_b_snapshot_parquet_path,
        ),
        label="Tool D workspace stress input",
    )
    if tool_b_latest.empty:
        raise FileNotFoundError("No current Corporate Finance output exists. Run python main.py refresh.")
    manual_data = load_manual_screening_data(
        paths,
        tickers=sorted(
            ticker.ticker
            for ticker in app_config.universe.tickers
            if ticker.active and ticker.tool_b_enabled
        ),
    )
    official_fundamentals = load_official_fundamentals(paths)
    return compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=app_config,
            manual_data=manual_data,
            normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
            tool_b_latest=tool_b_latest,
            spot_gold_usd=spot_gold_usd,
            spot_gold_date=spot_gold_date,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
            snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
            official_fundamentals=official_fundamentals,
            finance_source=finance_source,
        ),
        config=app_config.tool_d,
        gold_price=resolved_gold_price,
        source_run_id="workspace-tool-d-scenario",
    )


def _render_scenario_form(
    *,
    search: str,
    spot_gold: float | None,
    active_gold: float | None,
    requested_gold: float | None,
    finance_source: str,
) -> str:
    links = []
    if spot_gold is not None:
        for label, value in tool_d_stress_scenario_presets(spot_gold):
            href = _scenario_href(
                search=search,
                gold_price=value,
                finance_source=finance_source,
            )
            active_class = (
                " active"
                if active_gold is not None and abs(float(active_gold) - value) < 0.01
                else ""
            )
            links.append(
                f"<a class=\"button-like{active_class}\" href=\"{escape(href)}\">{escape(label)}</a>"
            )
    custom_value = "" if requested_gold is None else f"{requested_gold:.0f}"
    reset_params = {}
    if search:
        reset_params["search"] = search
    if finance_source == "yahoo":
        reset_params["fundamentals_source"] = "yahoo"
    reset_link = "/tool-d" + (f"?{urlencode(reset_params)}" if reset_params else "")
    yahoo_selected = " selected" if finance_source == "yahoo" else ""
    our_selected = " selected" if finance_source != "yahoo" else ""
    return (
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-d\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        f"<label><span>Custom gold price</span><input name=\"gold_price\" type=\"number\" min=\"1\" step=\"1\" value=\"{escape(custom_value)}\"></label>"
        "<label><span>Financials source</span><select name=\"fundamentals_source\">"
        f"<option value=\"our\"{our_selected}>Our View</option>"
        f"<option value=\"yahoo\"{yahoo_selected}>Yahoo Fundamentals</option>"
        "</select></label>"
        "<div class=\"overview-filters-actions\">"
        f"{''.join(links)}"
        "<button type=\"submit\" class=\"btn btn-primary\">Apply</button>"
        f"<a class=\"hint\" href=\"{escape(reset_link)}\">Reset gold price to spot</a>"
        "</div>"
        "</form>"
        "<p class=\"hint\">Formulas: breakeven = AISC (reported AISC already includes sustaining capital); "
        "interest-cover line is the gold price where modeled EBITDA equals interest expense; "
        "debt-stress line is where Net Debt/EBITDA crosses the configured danger band.</p>"
        "</section>"
    )


def _render_flip_section(
    frame,
    *,
    app_config: AppConfig | None = None,
    finance_source: str,
    fundamentals_provenance: dict[tuple[str, str], str],
) -> str:
    if frame.empty:
        return (
            "<section class=\"panel\"><h2>Who Flips Under This Stress</h2>"
            "<p class=\"hint\">No names flip from fine at spot into margin-negative, thin-margin, "
            "or over-levered status under the selected gold price.</p></section>"
        )
    rows: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        href = _ticker_href(ticker, finance_source=finance_source)
        icon = (
            ticker_provenance_icon(ticker, fundamentals_provenance)
            if finance_source == "yahoo"
            else ""
        )
        rows.append(
            "<tr>"
            f"<td><a href=\"{escape(href, quote=True)}\">{escape(ticker)}</a>{icon}</td>"
            f"<td>{_fmt_text(row.get('resilience_flip_flags'))}</td>"
            f"{_fmt_numeric_td(row.get('interest_cover_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('leverage_stressed_at_g'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('headroom_to_breakeven_pct_at_g'), decimals=1, as_percent=True)}"
            "</tr>"
        )
    return (
        "<section class=\"panel\"><h2>Who Flips Under This Stress</h2>"
        + table_region(
        "<table class=\"compact-table\"><thead><tr>"
        + help_th("Ticker", key="ticker_symbol", app_config=app_config)
        + help_th("Flip", key="tool_d_resilience_flip", app_config=app_config)
        + help_th("Interest-Cover Line", key="tool_d_interest_cover", app_config=app_config)
        + help_th("Leverage @ G", key="tool_d_leverage", app_config=app_config)
        + help_th("Headroom @ G", key="tool_d_headroom", app_config=app_config)
        + "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>",
        region_id="tool-d-flip-table-region",
        label="Who flips under this stress",
        )
        + "</section>"
    )


def _render_table(
    frame,
    *,
    app_config=None,
    finance_source: str,
    fundamentals_provenance: dict[tuple[str, str], str],
    legacy_fcf_schema: bool = False,
) -> str:
    rows_html: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        href = _ticker_href(ticker, finance_source=finance_source)
        icon = (
            ticker_provenance_icon(ticker, fundamentals_provenance)
            if finance_source == "yahoo"
            else ""
        )
        rows_html.append(
            "<tr>"
            f"<td><a href=\"{escape(href, quote=True)}\">{escape(ticker)}</a>{icon}</td>"
            f"{_fmt_numeric_td(row.get('tool_d_quality_rank'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('gold_price_used'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('interest_cover_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('survival_distance_to_interest_cover_pct'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('breaks_even_at_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('debt_stress_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('cost_curve_aisc_percentile'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('fragility_ebitda_pct_per_10pct_gold'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('leverage_stressed_at_g'), decimals=2)}"
            f"<td class=\"tool-d-ladder\">{_fmt_text(row.get('survival_order_ladder'))}</td>"
            f"<td>{_fmt_text(row.get('tool_d_tags'))}</td>"
            f"<td>{_fmt_text(row.get('resilience_data_status'))}</td>"
            f"{_fmt_numeric_td(row.get('survival_distance_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('cost_curve_resilience_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('fragility_resilience_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('balance_sheet_resilience_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('ev_ebitda_at_g'), decimals=2)}"
            + (
                "<td class=\"hint\">pending rebuild</td>"
                if legacy_fcf_schema
                else _fmt_numeric_td(row.get("aisc_margin_yield_at_g"), decimals=1, as_percent=True)
            )
            + "</tr>"
        )
    # Empty state: the colspan row does not match the explicit column model that
    # workspace-tables.js hands DataTables, so drop js-datatable when there are no
    # data rows (same pattern as candidate_finder_page.py).
    table_class = "js-datatable" if rows_html else "empty-table"
    if not rows_html:
        rows_html.append("<tr><td colspan=\"19\" class=\"hint\">No Corporate Resilience rows found.</td></tr>")

    return table_region(
        f"<table id=\"tool-d-table\" class=\"{table_class}\">"
        "<thead><tr>"
        "<th scope=\"col\" data-col-name=\"ticker\">Ticker</th>"
        + help_th("Resilience Score", key="tool_d_quality_rank", app_config=app_config, col_name="quality_rank", sort_numeric=True, panel=True)
        + help_th("Gold @ G", key="tool_d_gold_used", app_config=app_config, col_name="gold_price", sort_numeric=True, panel=True)
        + help_th("Interest-Cover Line", key="tool_d_interest_cover", app_config=app_config, col_name="interest_cover", sort_numeric=True, panel=True)
        + help_th("Distance To Line", key="tool_d_survival_distance", app_config=app_config, col_name="survival_distance", sort_numeric=True, panel=True)
        + help_th("Breakeven Gold", key="tool_d_breakeven", app_config=app_config, col_name="breakeven", sort_numeric=True, panel=True)
        + help_th("Debt-Stress Line", key="tool_d_debt_stress", app_config=app_config, col_name="debt_stress", sort_numeric=True, panel=True)
        + help_th("Cost-Curve %ile", key="tool_d_cost_curve", app_config=app_config, col_name="cost_curve", sort_numeric=True, panel=True)
        + help_th("Fragility Slope", key="tool_d_fragility", app_config=app_config, col_name="fragility", sort_numeric=True, panel=True)
        + help_th("Leverage @ G", key="tool_d_leverage", app_config=app_config, col_name="leverage", sort_numeric=True, panel=True)
        + help_th("Failure Ladder", key="tool_d_failure_ladder", app_config=app_config, col_name="ladder", panel=True)
        + help_th("Resilience Flags", key="tool_d_resilience_flags", app_config=app_config, col_name="tags", panel=True)
        + help_th("Data Status", key="tool_d_data_status", app_config=app_config, col_name="status", panel=True)
        + help_th("Survival Component", key="tool_d_survival_component", app_config=app_config, col_name="survival_component", sort_numeric=True, panel=True)
        + help_th("Cost Component", key="tool_d_cost_component", app_config=app_config, col_name="cost_component", sort_numeric=True, panel=True)
        + help_th("Fragility Component", key="tool_d_fragility_component", app_config=app_config, col_name="fragility_component", sort_numeric=True, panel=True)
        + help_th("Balance-Sheet Component", key="tool_d_balance_sheet_component", app_config=app_config, col_name="balance_sheet_component", sort_numeric=True, panel=True)
        + help_th("EV/EBITDA Context", key="tool_d_ev_ebitda_context", app_config=app_config, col_name="ev_ebitda", sort_numeric=True, panel=True)
        + help_th("AISC Margin Yield @ G", key="tool_d_aisc_margin_yield_context", app_config=app_config, col_name="aisc_margin_yield_at_g", sort_numeric=True, panel=True)
        + "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>",
        region_id="tool-d-table-region",
        label="Corporate Resilience comparison",
    )


def _requested_gold_price(query: dict[str, list[str]]) -> tuple[float | None, str | None]:
    raw = (query.get("gold_price", [""])[0] or "").strip()
    if raw == "":
        return None, None
    try:
        value = float(raw)
    except ValueError:
        return None, f"Gold price must be numeric, got {raw!r}."
    if not math.isfinite(value) or value <= 0:
        return None, "Gold price must be a finite positive number."
    return value, None


def _scenario_href(*, search: str, gold_price: float, finance_source: str) -> str:
    params: dict[str, str] = {"gold_price": f"{gold_price:.2f}"}
    if search:
        params["search"] = search
    if finance_source == "yahoo":
        params["fundamentals_source"] = "yahoo"
    return "/tool-d?" + urlencode(params)


def _ticker_href(ticker: str, *, finance_source: str) -> str:
    return build_page_url(
        f"/ticker/{quote(str(ticker), safe='')}",
        {},
        set_params=(
            {"fundamentals_source": "yahoo"}
            if finance_source == "yahoo"
            else {}
        ),
    )


def _first_number(frame, column: str) -> float | None:
    return _first_frame_number(frame, column)
