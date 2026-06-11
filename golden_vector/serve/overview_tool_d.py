"""Tool D overview rendering for the workspace UI."""

from __future__ import annotations

import math
from html import escape
from time import perf_counter
from urllib.parse import urlencode

import pandas as pd

from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import (
    read_current_model_parquet,
    resolve_current_foundation_manifest_path,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.model.tool_d import (
    ToolDExecutionInputs,
    compute_tool_d_outputs,
    latest_gold_price_from_history,
    tool_d_stress_scenario_presets,
)
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.schema import ToolBStaleSchemaError, validate_tool_b_output_schema
from golden_vector.serve.format_helpers import (
    _first_frame_number,
    _fmt_numeric_td,
    _fmt_text,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.overview_helpers import (
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.workspace_state import WorkspaceState


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
    requested_gold, scenario_error = _requested_gold_price(query)
    frame = state.latest_tool_d.copy()
    scenario_seconds: float | None = None
    scenario_message: str | None = None
    if requested_gold is not None:
        try:
            start = perf_counter()
            frame = _compute_scenario_frame(
                paths=paths,
                app_config=app_config,
                gold_price=requested_gold,
            )
            scenario_seconds = perf_counter() - start
            scenario_message = (
                f"Scenario recomputed in {scenario_seconds:.2f}s. "
                "Persisted spot output was not changed."
            )
        except ToolBStaleSchemaError:
            raise
        except Exception as exc:
            scenario_error = f"Could not compute stress scenario: {exc}"

    search_term = str(search or "").strip().upper()
    if not frame.empty and search_term and "ticker" in frame.columns:
        frame = frame.loc[
            frame["ticker"].astype(str).str.upper().str.contains(search_term, na=False)
        ].copy()
    if not frame.empty and {"tool_d_quality_rank", "ticker"}.issubset(frame.columns):
        frame = frame.sort_values(
            ["tool_d_quality_rank", "ticker"],
            ascending=[False, True],
            na_position="last",
        )

    spot_gold = _first_number(frame, "spot_gold_usd") or _first_number(
        state.latest_tool_d,
        "spot_gold_usd",
    )
    active_gold = _first_number(frame, "gold_price_used") or requested_gold or spot_gold
    flip_rows = (
        frame.loc[frame["resilience_flip_flags"].notna()].copy()
        if not frame.empty and "resilience_flip_flags" in frame.columns
        else frame.iloc[0:0].copy()
    )

    body = ["<h1>Corporate Resilience</h1>"]
    body.append(
        "<p>Stress-test view: how far gold can fall before a miner reaches its survival lines, "
        "and how quickly balance-sheet risk deteriorates.</p>"
    )
    body.append(
        "<p class=\"hint\">Simple transparent model. It does not model cash-runway duration, "
        "debt maturity walls, or gold hedging because those inputs are not in the local data.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if scenario_error:
        body.append(f"<div class=\"flash flash-warning\">{escape(scenario_error)}</div>")
    if scenario_message:
        body.append(f"<div class=\"flash\">{escape(scenario_message)}</div>")
    if not state.tool_d_alias_present:
        body.append(
            "<div class=\"flash flash-warning\">Corporate Resilience output is missing. "
            "Run <code>python main.py tool-d</code> after Corporate Finance.</div>"
        )
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    body.append(
        _render_scenario_form(
            search=search,
            spot_gold=spot_gold,
            active_gold=active_gold,
        )
    )
    body.append(_render_flip_section(flip_rows))
    body.append(_render_table(frame))
    return _page_shell(
        "Corporate Resilience - Golden Vector Workspace",
        "".join(body),
        active_nav="tool_d",
    )


def _compute_scenario_frame(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    gold_price: float,
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
        ),
        config=app_config.tool_d,
        gold_price=gold_price,
        source_run_id="workspace-tool-d-scenario",
    )


def _render_scenario_form(
    *,
    search: str,
    spot_gold: float | None,
    active_gold: float | None,
) -> str:
    links = []
    if spot_gold is not None:
        for label, value in tool_d_stress_scenario_presets(spot_gold):
            href = _scenario_href(search=search, gold_price=value)
            active_class = (
                " active"
                if active_gold is not None and abs(float(active_gold) - value) < 0.01
                else ""
            )
            links.append(
                f"<a class=\"button-like{active_class}\" href=\"{escape(href)}\">{escape(label)}</a>"
            )
    custom_value = "" if active_gold is None else f"{active_gold:.0f}"
    reset_link = "/tool-d" + (f"?{urlencode({'search': search})}" if search else "")
    return (
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-d\" class=\"overview-filters-form\">"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
        f"<label><span>Custom gold price</span><input name=\"gold_price\" type=\"number\" min=\"1\" step=\"1\" value=\"{escape(custom_value)}\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"{''.join(links)}"
        "<button type=\"submit\">Apply</button>"
        f"<a class=\"hint\" href=\"{escape(reset_link)}\">Reset to persisted spot</a>"
        "</div>"
        "</form>"
        "<p class=\"hint\">Formulas: breakeven = AISC; FCF breakeven = AISC plus sustaining capex per ounce; "
        "interest-cover line is the gold price where modeled EBITDA equals interest expense; "
        "debt-stress line is where Net Debt/EBITDA crosses the configured danger band.</p>"
        "</section>"
    )


def _render_flip_section(frame) -> str:
    if frame.empty:
        return (
            "<section class=\"panel\"><h2>Who Flips Under This Stress</h2>"
            "<p class=\"hint\">No names flip from fine at spot into margin-negative, thin-margin, "
            "or over-levered status under the selected gold price.</p></section>"
        )
    rows: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        rows.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"<td>{_fmt_text(row.get('resilience_flip_flags'))}</td>"
            f"{_fmt_numeric_td(row.get('interest_cover_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('leverage_stressed_at_g'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('headroom_to_breakeven_pct_at_g'), decimals=1, as_percent=True)}"
            "</tr>"
        )
    return (
        "<section class=\"panel\"><h2>Who Flips Under This Stress</h2>"
        "<table class=\"compact-table\"><thead><tr>"
        "<th>Ticker</th><th>Flip</th><th>Interest-Cover Line</th><th>Leverage @ G</th><th>Headroom @ G</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _render_table(frame) -> str:
    rows_html: list[str] = []
    for row in frame.to_dict(orient="records"):
        ticker = str(row.get("ticker") or "")
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(ticker)}\">{escape(ticker)}</a></td>"
            f"{_fmt_numeric_td(row.get('tool_d_quality_rank'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('gold_price_used'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('interest_cover_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('survival_distance_to_interest_cover_pct'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('breaks_even_at_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('fcf_breakeven_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('debt_stress_gold_usd'), decimals=0)}"
            f"{_fmt_numeric_td(row.get('cost_curve_aisc_percentile'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('fragility_ebitda_pct_per_10pct_gold'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(row.get('leverage_stressed_at_g'), decimals=2)}"
            f"<td>{_fmt_text(row.get('survival_order_ladder'))}</td>"
            f"<td>{_fmt_text(row.get('tool_d_tags'))}</td>"
            f"<td>{_fmt_text(row.get('resilience_data_status'))}</td>"
            f"{_fmt_numeric_td(row.get('survival_distance_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('cost_curve_resilience_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('fragility_resilience_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('balance_sheet_resilience_component'), decimals=1)}"
            f"{_fmt_numeric_td(row.get('ev_ebitda_at_g'), decimals=2)}"
            f"{_fmt_numeric_td(row.get('fcf_yield'), decimals=1, as_percent=True)}"
            "</tr>"
        )
    if not rows_html:
        rows_html.append("<tr><td colspan=\"20\" class=\"hint\">No Corporate Resilience rows found.</td></tr>")

    return (
        "<table id=\"tool-d-table\" class=\"js-datatable\">"
        "<thead><tr>"
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"quality_rank\" data-sort-numeric title=\"Percentile rank of the transparent resilience components\">Resilience Rank</th>"
        "<th data-col-name=\"gold_price\" data-sort-numeric title=\"Gold price used for every stress figure in this row\">Gold @ G</th>"
        "<th data-col-name=\"interest_cover\" data-sort-numeric title=\"Gold price where modeled EBITDA equals interest expense\">Interest-Cover Line</th>"
        "<th data-col-name=\"survival_distance\" data-sort-numeric title=\"(Gold @ G - interest-cover line) / Gold @ G\">Distance To Line</th>"
        "<th data-col-name=\"breakeven\" data-sort-numeric title=\"AISC: the gold price where mine margin reaches zero before sustaining capex\">Breakeven Gold</th>"
        "<th data-col-name=\"fcf_breakeven\" data-sort-numeric title=\"AISC plus sustaining capex per ounce\">FCF Breakeven</th>"
        "<th data-col-name=\"debt_stress\" data-sort-numeric title=\"Gold price where Net Debt / EBITDA reaches the configured danger band\">Debt-Stress Line</th>"
        "<th data-col-name=\"cost_curve\" data-sort-numeric title=\"AISC percentile across the universe; lower is more resilient\">Cost-Curve %ile</th>"
        "<th data-col-name=\"fragility\" data-sort-numeric title=\"Modeled EBITDA loss for a 10% gold fall, divided by EBITDA at the selected gold price\">Fragility Slope</th>"
        "<th data-col-name=\"leverage\" data-sort-numeric title=\"Net Debt / EBITDA at the selected gold price\">Leverage @ G</th>"
        "<th data-col-name=\"ladder\">Failure Ladder</th>"
        "<th data-col-name=\"tags\">Resilience Flags</th>"
        "<th data-col-name=\"status\">Data Status</th>"
        "<th data-col-name=\"survival_component\" data-sort-numeric>Survival Component</th>"
        "<th data-col-name=\"cost_component\" data-sort-numeric>Cost Component</th>"
        "<th data-col-name=\"fragility_component\" data-sort-numeric>Fragility Component</th>"
        "<th data-col-name=\"balance_sheet_component\" data-sort-numeric>Balance-Sheet Component</th>"
        "<th data-col-name=\"ev_ebitda\" data-sort-numeric title=\"Secondary context only; not used in the rank\">EV/EBITDA Context</th>"
        "<th data-col-name=\"fcf_yield\" data-sort-numeric title=\"Secondary context only; not used in the rank\">FCF Yield Context</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
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


def _scenario_href(*, search: str, gold_price: float) -> str:
    params: dict[str, str] = {"gold_price": f"{gold_price:.2f}"}
    if search:
        params["search"] = search
    return "/tool-d?" + urlencode(params)


def _first_number(frame, column: str) -> float | None:
    return _first_frame_number(frame, column)
