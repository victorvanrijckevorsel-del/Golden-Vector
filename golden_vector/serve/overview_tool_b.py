"""Tool B overview rendering and scenario override helpers."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from time import perf_counter
from typing import Any
from urllib.parse import quote, urlencode

import pandas as pd

from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import resolve_current_foundation_manifest_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.fundamentals.artifacts import load_official_fundamentals
from golden_vector.model.tool_d import latest_gold_price_from_history
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.pipeline import (
    compute_tool_b_in_memory,
    materialize_tool_b_finance_source,
    normalize_finance_source,
)
from golden_vector.screening.schema import ToolBStaleSchemaError
from golden_vector.serve.format_helpers import (
    _MISSING_SORT_SENTINEL,
    _first_frame_number,
    _first_frame_text,
    _fmt_form_number,
    _fmt_numeric_td,
    _fmt_text,
    _frame_index_by_ticker,
    _optional_float,
    resolve_dual_source,
    source_alternate_span,
)
from golden_vector.serve.fundamentals_provenance import (
    METRIC_FIELD_DEPENDENCIES,
    load_fundamentals_provenance_lookup,
    provenance_icon_for_metric,
    provenance_text_for_fields,
    ticker_provenance_icon,
)
from golden_vector.serve.metric_formula import metric_formula_icon
from golden_vector.serve.overview_helpers import (
    _collect_filter_options,
    _render_filter_bar,
    _render_provenance_warnings,
    _render_refresh_summary,
    note_counts_by_ticker,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.column_help import help_th
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.screening_overrides import ScreeningOverrides, apply_overrides
from golden_vector.serve.url_helpers import build_page_url
from golden_vector.serve.workspace_state import WorkspaceState


def _checks_detail_cell(tb: dict[str, Any]) -> str:
    """Compact, click-to-expand checks cell so the table stays readable.

    Shows only the "N/M" count by default; clicking it reveals the full
    per-check breakdown (Data complete PASS; AISC PASS; ...).
    """
    summary = str(tb.get("fundamental_check_summary") or "").strip()
    if not summary:
        return "<td>-</td>"
    label, _, detail = summary.partition(":")
    label = label.strip() or "checks"
    detail = detail.strip() or summary
    return (
        "<td class=\"checks-summary-cell\">"
        f"<details><summary>{escape(label)}</summary>"
        f"<span class=\"checks-detail\">{escape(detail)}</span>"
        "</details></td>"
    )


def _overview_metric_icon(
    metric_name: str,
    tb: dict[str, Any],
    *,
    rank_by: str,
    provenance_lookup: dict[tuple[str, str], str] | None,
) -> str:
    """Formula + live-numbers info button for an overview ratio cell. In Yahoo (official) mode
    the underlying line items' source provenance is appended below the formula; if the ratio
    value is unavailable (degraded row) we still surface the source-provenance icon so it is
    not lost (same affordance the plain provenance icon gave before this feature)."""
    extra = ""
    if rank_by == "official" and provenance_lookup:
        extra = provenance_text_for_fields(
            tb.get("ticker"),
            METRIC_FIELD_DEPENDENCIES.get(metric_name, ()),
            provenance_lookup,
        )
    icon = metric_formula_icon(metric_name, tb, extra=extra)
    if icon:
        return icon
    if rank_by == "official" and provenance_lookup:
        return provenance_icon_for_metric(tb.get("ticker"), metric_name, provenance_lookup)
    return ""


def _comparison_numeric_td(
    tb: dict[str, Any],
    metric_name: str,
    *,
    decimals: int,
    rank_by: str,
    provenance_lookup: dict[tuple[str, str], str] | None = None,
) -> str:
    # Resolve active/alternate via the shared helper (finite-aware, matching the formula popover):
    # a non-finite ratio renders "-" on the cell AND suppresses the popover, so the two never
    # disagree. The ticker-detail snapshot uses the SAME resolver, so both surfaces agree.
    active, alternate, alternate_label, differs = resolve_dual_source(
        tb, metric_name, prefer_official=(rank_by == "official")
    )
    order_value = _MISSING_SORT_SENTINEL if active is None else f"{active}"
    show_alternate = alternate is not None and (
        (active is not None and differs)
        or (active is None and rank_by == "official")
    )
    if show_alternate:
        # Compact one-line divergence: the active value reads inline like every other row
        # (so the column stays scannable), and the differing alternate is a short accent
        # parenthetical. The active source is not relabelled here — the page's source toggle
        # already says which source is active. Keeps the row from ballooning to 3 lines.
        display = (
            f"{_number_text(active, decimals=decimals)} "
            f"{source_alternate_span(alternate_label, _number_text(alternate, decimals=decimals))}"
        )
    else:
        display = _number_text(active, decimals=decimals)
    icon = _overview_metric_icon(
        metric_name, tb, rank_by=rank_by, provenance_lookup=provenance_lookup
    )
    return f"<td data-order=\"{escape(order_value)}\">{display}{icon}</td>"


def _number_text(value: float | None, *, decimals: int) -> str:
    if value is None:
        return "-"
    return escape(f"{value:,.{decimals}f}")


def _render_tool_b_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
    app_config: AppConfig | None = None,
    paths: ProjectPaths | None = None,
    overrides: ScreeningOverrides | None = None,
    override_error: str | None = None,
    rank_by: str = "our_view",
    differences_only: bool = False,
) -> str:
    """Tool B focused overview: simple fundamentals and gold-price economics.

    Shows visible checks, standard ratios, and estimates at the selected
    gold-price assumption. Tickers marked INCOMPLETE usually have missing
    manual mining inputs.

    When `overrides.has_any()`, the table is recomputed in memory from
    the current snapshot + manual store with the overlaid screening
    parameters (gold price, thresholds, tier discounts). The persisted
    parquet is left untouched; overrides are scenario tools.
    """
    overrides = overrides or ScreeningOverrides()
    note_counts = note_counts_by_ticker(state.stock_notes)

    # Either use the latest persisted parquet, or recompute in memory if
    # the user passed any URL-param overrides.
    resolution = _resolve_tool_b_frame(
        state=state,
        overrides=overrides,
        app_config=app_config,
        paths=paths,
    )
    rank_by = _normalize_rank_by(rank_by)
    tool_b_frame = materialize_tool_b_finance_source(
        resolution.frame,
        finance_source="yahoo" if rank_by == "official" else "our",
    )
    provenance_lookup = (
        load_fundamentals_provenance_lookup(paths)
        if rank_by == "official"
        else {}
    )
    override_runtime_error = resolution.runtime_error
    # The FRAME is the source of truth for what gold price is on screen.
    # On a failed recompute this self-corrects: the persisted fallback
    # carries spot, so the dial snaps back instead of showing a price the
    # table does not reflect.
    active_gold = _first_frame_number(tool_b_frame, "gold_price_used")
    spot_gold = _first_frame_number(tool_b_frame, "spot_gold_usd")
    spot_gold_date = _first_frame_text(tool_b_frame, "spot_gold_date")
    gold_price_basis = _first_frame_text(tool_b_frame, "gold_price_basis")
    tool_b_index = _frame_index_by_ticker(tool_b_frame)
    search_term = str(search or "").strip().upper()

    derived: list[dict[str, Any]] = []
    for ticker in state.tool_b_tickers:
        if search_term and search_term not in ticker:
            continue
        tool_b_row = tool_b_index.get(ticker, {})
        if differences_only and _optional_float(
            tool_b_row.get("divergent_field_count")
        ) in (None, 0.0):
            continue
        rank_column = (
            "fundamental_check_rank_official"
            if rank_by == "official"
            else "fundamental_check_rank"
        )
        derived.append({
            "ticker": ticker,
            "tool_b_row": tool_b_row,
            "rank_value": _optional_float(tool_b_row.get(rank_column)),
            "max_divergence_pct": _optional_float(tool_b_row.get("max_divergence_pct")),
            "divergent_field_count": _optional_float(
                tool_b_row.get("divergent_field_count")
            ),
            "note_count": int(note_counts.get(ticker, 0)),
        })
    if differences_only:
        derived.sort(
            key=lambda r: (
                0 if r["max_divergence_pct"] is not None else 1,
                -(r["max_divergence_pct"] or 0.0),
                r["ticker"],
            )
        )
    else:
        derived.sort(
            key=lambda r: (
                0 if r["rank_value"] is not None else 1,
                r["rank_value"] if r["rank_value"] is not None else 0.0,
                r["ticker"],
            )
        )

    rows_html: list[str] = []
    for row in derived:
        tb = row["tool_b_row"]
        ticker_icon = (
            ticker_provenance_icon(row["ticker"], provenance_lookup)
            if rank_by == "official"
            else ""
        )
        rows_html.append(
            "<tr>"
            f"<td><a href=\"{escape(_ticker_href(row['ticker'], rank_by=rank_by))}\">{escape(row['ticker'])}</a>{ticker_icon}</td>"
            f"<td>{_fmt_text(tb.get('screening_verdict'))}</td>"
            f"{_fmt_numeric_td(tb.get('fundamental_check_score'), decimals=1)}"
            f"{_fmt_numeric_td(row['rank_value'], decimals=0)}"
            f"{_fmt_numeric_td(tb.get('share_price_usd'), decimals=2)}"
            f"{_fmt_numeric_td(tb.get('market_cap_musd'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('enterprise_value_musd'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('aisc_usd_per_oz'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('cash_margin_usd_per_oz'), decimals=0, extra=_overview_metric_icon('cash_margin_usd_per_oz', tb, rank_by=rank_by, provenance_lookup=provenance_lookup))}"
            f"{_fmt_numeric_td(tb.get('margin_pct'), decimals=1, as_percent=True, extra=_overview_metric_icon('margin_pct', tb, rank_by=rank_by, provenance_lookup=provenance_lookup))}"
            f"{_fmt_numeric_td(tb.get('forward_ebitda_musd'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('forward_pe'), decimals=2, extra=_overview_metric_icon('forward_pe', tb, rank_by=rank_by, provenance_lookup=provenance_lookup))}"
            f"{_comparison_numeric_td(tb, 'ev_ebitda', decimals=1, rank_by=rank_by, provenance_lookup=provenance_lookup)}"
            f"{_fmt_numeric_td(tb.get('fcf_yield'), decimals=1, as_percent=True, extra=_overview_metric_icon('fcf_yield', tb, rank_by=rank_by, provenance_lookup=provenance_lookup))}"
            f"{_comparison_numeric_td(tb, 'leverage', decimals=2, rank_by=rank_by, provenance_lookup=provenance_lookup)}"
            f"{_fmt_numeric_td(tb.get('reserve_life_years'), decimals=1)}"
            f"<td>{_fmt_text(tb.get('financial_data_status'))}</td>"
            f"{_fmt_numeric_td(tb.get('divergent_field_count'), decimals=0)}"
            f"<td>{_fmt_text(tb.get('layer1_status'))}</td>"
            f"{_fmt_numeric_td(row['note_count'], decimals=0)}"
            f"{_checks_detail_cell(tb)}"
            "</tr>"
        )
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"21\" class=\"hint\">No tickers match.</td></tr>"
        )

    # Filter-bar options derived from the rendered rows.
    filter_options = _collect_filter_options(
        [r["tool_b_row"] for r in derived],
        [
            ("verdict", "screening_verdict"),
            ("layer1", "layer1_status"),
        ],
    )

    body = ["<h1>Corporate Finance</h1>"]
    gold_basis = _gold_basis_sentence(
        active_gold=active_gold,
        spot_gold=spot_gold,
        spot_gold_date=spot_gold_date,
        gold_price_basis=gold_price_basis,
    )
    body.append(
        "<p>Industry-standard corporate finance checks. "
        f"{gold_basis} "
        "The score is the number of visible checks passed, not a model target price. "
        "Click a ticker to edit the manual mining inputs.</p>"
    )
    if flash:
        body.append(f"<div class=\"flash\">{escape(flash)}</div>")
    if override_error:
        body.append(
            f"<div class=\"flash flash-error\">Invalid override: {escape(override_error)}</div>"
        )
    if override_runtime_error:
        body.append(
            "<div class=\"flash flash-error\">"
            f"Could not recompute with overrides: {escape(override_runtime_error)}. "
            "Showing the last persisted Corporate Finance snapshot at its own gold price."
            "</div>"
        )
    if resolution.recompute_active:
        timing = (
            f"Scenario recomputed in {resolution.compute_seconds:.2f}s "
            f"(inputs loaded in {resolution.load_seconds:.2f}s). "
            if resolution.compute_seconds is not None and resolution.load_seconds is not None
            else ""
        )
        body.append(
            "<div class=\"flash\"><strong>Scenario active:</strong> "
            f"{timing}"
            "Recomputed live from manual data + latest snapshot; the persisted "
            "spot output was not changed. <a href=\"/tool-b\">Reset to spot</a>.</div>"
        )
    if rank_by == "official":
        body.append(
            "<div class=\"flash\"><strong>Yahoo Fundamentals view:</strong> "
            "dual-source financial fields and derived finance checks are "
            "materialized from Yahoo Fundamentals for this page. Mining "
            "assumptions still come from Our View. The persisted decision "
            "artifact remains Our View.</div>"
        )
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    if app_config is not None:
        body.append(_render_gold_dial(
            app_config=app_config,
            overrides=overrides,
            search=search,
            rank_by=rank_by,
            differences_only=differences_only,
            active_gold=active_gold,
            spot_gold=spot_gold,
            spot_gold_date=spot_gold_date,
        ))
        body.append(_render_screening_params_form(
            app_config=app_config,
            overrides=overrides,
            search=search,
            rank_by=rank_by,
            differences_only=differences_only,
        ))
    # Filter form carries hidden override fields so submitting it doesn't
    # silently clear the active scenario. The "Reset" link still drops
    # everything by linking to bare /tool-b.
    hidden_overrides = _render_overrides_as_hidden_inputs(
        overrides,
        rank_by=rank_by,
        differences_only=differences_only,
    )
    search_input = _text_input_label(
        "Search ticker",
        name="search",
        value=search,
        placeholder="NEM",
    )
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-b\" class=\"overview-filters-form\">"
        f"{hidden_overrides}"
        f"{search_input}"
        f"{_render_rank_controls(rank_by=rank_by, differences_only=differences_only)}"
        "<div class=\"overview-filters-actions\">"
        f"<span class=\"hint\">{len(derived)} tickers shown.</span>"
        "<button type=\"submit\">Apply</button>"
        "<a class=\"hint\" href=\"/tool-b\">Reset</a>"
        "</div>"
        "</form>"
        "</section>"
    )
    body.append(_render_filter_bar(
        target_table_id="tool-b-table",
        options=filter_options,
        column_labels={"verdict": "Verdict", "layer1": "Layer 1"},
    ))
    body.append(
        "<table id=\"tool-b-table\" class=\"js-datatable\">"
        "<thead><tr>"
        + help_th("Ticker", key="ticker_symbol", app_config=app_config, col_name="ticker")
        + help_th("Verdict", key="tool_b_verdict", app_config=app_config, col_name="verdict")
        + help_th("Checks Passed %", key="tool_b_score", app_config=app_config, col_name="score", sort_numeric=True)
        + help_th("Rank", key="tool_b_rank", app_config=app_config, col_name="rank", sort_numeric=True)
        + help_th("Share Price", key="tool_b_share_price", app_config=app_config, col_name="share_price", sort_numeric=True)
        + help_th("Market Cap", key="tool_b_market_cap", app_config=app_config, col_name="market_cap", sort_numeric=True)
        + help_th("Enterprise Value", key="tool_b_enterprise_value", app_config=app_config, col_name="enterprise_value", sort_numeric=True)
        + help_th("AISC", key="tool_b_aisc", app_config=app_config, col_name="aisc", sort_numeric=True)
        + help_th("Cash Margin/oz", key="tool_b_cash_margin", app_config=app_config, col_name="cash_margin", sort_numeric=True)
        + help_th("Margin %", key="tool_b_margin_pct", app_config=app_config, col_name="margin_pct", sort_numeric=True)
        + help_th("Forward EBITDA est.", key="tool_b_forward_ebitda", app_config=app_config, col_name="forward_ebitda", sort_numeric=True)
        + help_th("Forward P/E est.", key="tool_b_forward_pe", app_config=app_config, col_name="forward_pe", sort_numeric=True)
        + help_th("EV/EBITDA est.", key="tool_b_ev_ebitda", app_config=app_config, col_name="ev_ebitda", sort_numeric=True)
        + help_th("FCF Yield est.", key="tool_b_fcf_yield", app_config=app_config, col_name="fcf_yield", sort_numeric=True)
        + help_th("Net Debt/EBITDA", key="tool_b_leverage", app_config=app_config, col_name="leverage", sort_numeric=True)
        + help_th("Reserve Life", key="tool_b_reserve_life", app_config=app_config, col_name="reserve_life", sort_numeric=True)
        + help_th("Financial Data", key="tool_b_financial_data_status", app_config=app_config, col_name="financial_data")
        + help_th("Differences", key="tool_b_divergent_field_count", app_config=app_config, col_name="differences", sort_numeric=True)
        + help_th("Layer 1", key="tool_b_layer1_status", app_config=app_config, col_name="layer1")
        + help_th("Notes", key="user_notes_count", app_config=app_config, col_name="notes", sort_numeric=True)
        + help_th("Checks", key="tool_b_check_summary", app_config=app_config, col_name="check_summary")
        + "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell("Corporate Finance - Golden Vector Workspace", "".join(body), active_nav="tool_b")


@dataclass(frozen=True)
class _ToolBFrameResolution:
    """What the page renders, plus the honest story of how it got it."""

    frame: pd.DataFrame
    runtime_error: str | None = None
    recompute_active: bool = False
    load_seconds: float | None = None
    compute_seconds: float | None = None


def _resolve_tool_b_frame(
    *,
    state: WorkspaceState,
    overrides: ScreeningOverrides,
    app_config: AppConfig | None,
    paths: ProjectPaths | None,
) -> _ToolBFrameResolution:
    """Resolve the frame for the Tool B view.

    No overrides -> the persisted parquet (the canonical spot run).
    Overrides -> recompute in memory at the dialed gold price, defaulting
    to spot from the fresh foundation when only thresholds were changed.
    On recompute failure the page falls back to the persisted parquet,
    but `recompute_active` stays False so the UI never claims a live
    scenario it didn't compute; the dial snaps back to what is shown.
    """
    if not overrides.has_any() or app_config is None or paths is None:
        return _ToolBFrameResolution(frame=state.latest_tool_b)

    try:
        load_start = perf_counter()
        overridden_config = apply_overrides(app_config, overrides)
        foundation_manifest_path = resolve_current_foundation_manifest_path(
            paths,
            require_current_manifest=True,
        )
        foundation_snapshot = load_latest_foundation_snapshot(
            paths=paths,
            app_config=overridden_config,
            include_gold_history=True,
            include_equity_histories=False,
            include_market_snapshots=True,
            manifest_path=foundation_manifest_path,
        )
        spot_gold_usd, spot_gold_date = latest_gold_price_from_history(
            foundation_snapshot.gold_history
        )
        manual_data = load_manual_screening_data(
            paths,
            tickers=state.tool_b_tickers,
        )
        official_fundamentals = load_official_fundamentals(paths)
        load_seconds = perf_counter() - load_start
        gold_price = (
            float(overrides.gold_price)
            if overrides.gold_price is not None
            else float(spot_gold_usd)
        )
        gold_price_basis = (
            "latest_daily_gold_close"
            if abs(gold_price - float(spot_gold_usd)) <= 0.01
            else "custom_scenario"
        )
        compute_start = perf_counter()
        recomputed = compute_tool_b_in_memory(
            app_config=overridden_config,
            manual_data=manual_data,
            normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
            gold_price_assumption=gold_price,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
            snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
            source_run_id="workspace-in-memory",
            spot_gold_usd=float(spot_gold_usd),
            spot_gold_date=spot_gold_date,
            gold_price_basis=gold_price_basis,
            official_fundamentals=official_fundamentals,
        )
        compute_seconds = perf_counter() - compute_start
        if not recomputed.empty and "ticker" in recomputed.columns:
            recomputed["ticker"] = recomputed["ticker"].astype(str).str.upper()
        return _ToolBFrameResolution(
            frame=recomputed,
            recompute_active=True,
            load_seconds=load_seconds,
            compute_seconds=compute_seconds,
        )
    except ToolBStaleSchemaError:
        # Nothing in this path reads a Tool B parquet today, but mirror
        # the Tool D rule: a stale-schema signal must surface the calm
        # refresh page, never be swallowed into a silent fallback.
        raise
    except Exception as exc:  # broad catch: fall back to persisted parquet, honestly labeled
        return _ToolBFrameResolution(frame=state.latest_tool_b, runtime_error=str(exc))


def _gold_basis_sentence(
    *,
    active_gold: float | None,
    spot_gold: float | None,
    spot_gold_date: str | None,
    gold_price_basis: str | None,
) -> str:
    """One plain sentence stating which gold price the table is showing."""
    if active_gold is None:
        return "Gold-dependent estimates use the gold price recorded in the last run."
    dated = f" (close {escape(spot_gold_date)})" if spot_gold_date else ""
    if gold_price_basis == "latest_daily_gold_close":
        return (
            f"All gold-dependent estimates are at spot gold "
            f"${active_gold:,.0f}/oz{dated}."
        )
    spot_part = (
        f"; spot is ${spot_gold:,.0f}/oz{dated}" if spot_gold is not None else ""
    )
    return (
        f"All gold-dependent estimates are at scenario gold "
        f"${active_gold:,.0f}/oz{spot_part}."
    )


def _render_gold_dial(
    *,
    app_config: AppConfig,
    overrides: ScreeningOverrides,
    search: str,
    rank_by: str,
    differences_only: bool,
    active_gold: float | None,
    spot_gold: float | None,
    spot_gold_date: str | None,
) -> str:
    """The page's primary control: one gold price for the whole table.

    Presets = Spot (dated) + the configured scenario ladder. Preset links
    carry the active search and any advanced-assumption overrides so
    moving the dial never silently resets them.
    """
    carried = _override_query_params(overrides, include_gold=False)
    if search:
        carried["search"] = search
    _add_view_params(carried, rank_by=rank_by, differences_only=differences_only)

    def _href(gold_value: float | None) -> str:
        params = dict(carried)
        if gold_value is not None:
            params["gold_price"] = f"{gold_value:g}"
        return "/tool-b" + (f"?{urlencode(params)}" if params else "")

    links: list[str] = []
    if spot_gold is not None:
        dated = f" (close {spot_gold_date})" if spot_gold_date else ""
        spot_active = (
            " active"
            if active_gold is not None and abs(active_gold - spot_gold) <= 0.01
            else ""
        )
        links.append(
            f"<a class=\"button-like{spot_active}\" href=\"{escape(_href(None))}\">"
            f"Spot ${spot_gold:,.0f}{escape(dated)}</a>"
        )
    for scenario in app_config.screening_params.gold_price_scenarios:
        preset_active = (
            " active"
            if active_gold is not None and abs(active_gold - float(scenario)) <= 0.01
            else ""
        )
        links.append(
            f"<a class=\"button-like{preset_active}\" href=\"{escape(_href(float(scenario)))}\">"
            f"${scenario:,.0f}</a>"
        )

    custom_value = "" if active_gold is None else f"{active_gold:.0f}"
    carried_hidden = "".join(
        f"<input type=\"hidden\" name=\"{escape(name)}\" value=\"{escape(value)}\">"
        for name, value in carried.items()
    )
    return (
        "<section class=\"panel gold-dial\">"
        "<h2>Gold price</h2>"
        "<form method=\"get\" action=\"/tool-b\" class=\"gold-dial-form\">"
        f"{carried_hidden}"
        f"<label><span>Custom gold price ($/oz)</span>"
        f"<input name=\"gold_price\" type=\"number\" min=\"1\" step=\"1\" value=\"{escape(custom_value)}\"></label>"
        "<div class=\"overview-filters-actions\">"
        f"{''.join(links)}"
        "<button type=\"submit\">Apply</button>"
        f"<a class=\"hint\" href=\"{escape(_href(None))}\">Reset to spot</a>"
        "</div>"
        "</form>"
        "<p class=\"hint\">Moving the dial recomputes and re-ranks the whole table live. "
        "Nothing is saved; the nightly run always prices at spot.</p>"
        "</section>"
    )


def _render_screening_params_form(
    *,
    app_config: AppConfig,
    overrides: ScreeningOverrides,
    search: str,
    rank_by: str,
    differences_only: bool,
) -> str:
    """Render the "Advanced screening assumptions" panel for the Tool B view.

    Mirrors the yellow-highlighted cells of the friend's Excel
    `Summary & Parameters` sheet: six Layer 1 thresholds and the three
    jurisdiction tier discounts. The gold price moved to the primary
    dial panel; this panel stays collapsed unless a threshold override
    is active. Values pre-fill from either the active overrides (if
    any) or the YAML defaults.
    """
    sp = app_config.screening_params

    pe_target = overrides.verdict.get("strong_candidate_forward_pe_max",
                                       sp.verdict_thresholds.strong_candidate_forward_pe_max)
    fcf_yield_target = overrides.layer1.get("fcf_yield_min", sp.layer1_thresholds.fcf_yield_min)
    aisc_target = overrides.layer1.get("aisc_max", sp.layer1_thresholds.aisc_max)
    margin_target = overrides.layer1.get("margin_min", sp.layer1_thresholds.margin_min)
    reserve_life_target = overrides.layer1.get("reserve_life_min", sp.layer1_thresholds.reserve_life_min)
    leverage_target = overrides.layer1.get("leverage_max", sp.layer1_thresholds.leverage_max)
    tier1 = overrides.jurisdiction.get("tier_1", sp.jurisdiction_discounts.tier_1)
    tier2 = overrides.jurisdiction.get("tier_2", sp.jurisdiction_discounts.tier_2)
    tier3 = overrides.jurisdiction.get("tier_3", sp.jurisdiction_discounts.tier_3)

    # Percent-valued fields display the typed percent (15 for 15%) rather
    # than the fraction (0.15). The override parser accepts either.
    def _as_percent_display(fraction: float) -> str:
        return f"{fraction * 100:g}"

    # Carry the search term and the active dial price through the form so
    # applying a threshold doesn't silently reset either.
    search_hidden = (
        f"<input type=\"hidden\" name=\"search\" value=\"{escape(search)}\">"
        if search else ""
    )
    gold_hidden = (
        f"<input type=\"hidden\" name=\"gold_price\" value=\"{_fmt_form_number(overrides.gold_price)}\">"
        if overrides.gold_price is not None else ""
    )
    view_hidden = _render_view_hidden_inputs(
        rank_by=rank_by,
        differences_only=differences_only,
    )
    open_attr = " open" if overrides.has_non_gold() else ""
    pe_input = _number_input_label(
        "Strong P/E cutoff (<)",
        name="pe_target",
        value=_fmt_form_number(pe_target),
        step="0.1",
        minimum="0.1",
    )
    fcf_input = _number_input_label(
        "Minimum FCF yield (%)",
        name="fcf_yield_target",
        value=_as_percent_display(fcf_yield_target),
        step="0.5",
        minimum="0",
    )
    aisc_input = _number_input_label(
        "AISC cutoff ($/oz)",
        name="aisc_target",
        value=_fmt_form_number(aisc_target),
        step="10",
        minimum="1",
    )
    margin_input = _number_input_label(
        "Minimum margin (%)",
        name="margin_target",
        value=_as_percent_display(margin_target),
        step="1",
        minimum="0",
    )
    reserve_input = _number_input_label(
        "Minimum reserve life (yrs)",
        name="reserve_life_target",
        value=_fmt_form_number(reserve_life_target),
        step="0.5",
        minimum="0",
    )
    leverage_input = _number_input_label(
        "Net Debt/EBITDA cutoff",
        name="leverage_target",
        value=_fmt_form_number(leverage_target),
        step="0.1",
        minimum="0",
    )
    tier1_input = _number_input_label(
        "Tier 1 Discount (%)",
        name="tier1_discount",
        value=_as_percent_display(tier1),
        step="1",
        minimum="0",
        maximum="100",
    )
    tier2_input = _number_input_label(
        "Tier 2 Discount (%)",
        name="tier2_discount",
        value=_as_percent_display(tier2),
        step="1",
        minimum="0",
        maximum="100",
    )
    tier3_input = _number_input_label(
        "Tier 3 Discount (%)",
        name="tier3_discount",
        value=_as_percent_display(tier3),
        step="1",
        minimum="0",
        maximum="100",
    )

    return (
        f"<details class=\"panel screening-params advanced-assumptions\"{open_attr}>"
        "<summary><h2>Advanced screening assumptions</h2></summary>"
        "<form method=\"get\" action=\"/tool-b\" class=\"screening-params-form\">"
        f"{search_hidden}"
        f"{gold_hidden}"
        f"{view_hidden}"
        "<div class=\"screening-params-grid\">"
        f"{pe_input}"
        f"{fcf_input}"
        f"{aisc_input}"
        f"{margin_input}"
        f"{reserve_input}"
        f"{leverage_input}"
        f"{tier1_input}"
        f"{tier2_input}"
        f"{tier3_input}"
        "</div>"
        "<div class=\"screening-params-actions\">"
        "<button type=\"submit\">Apply assumptions</button>"
        "<a class=\"hint\" href=\"/tool-b\">Reset all</a>"
        "</div>"
        "</form>"
        "</details>"
    )


# Mapping from override field -> (URL-param name, percent-style?). Mirrors
# `_FIELD_SPECS` in screening_overrides.py so any param the parser accepts
# is also reflected back into hidden inputs.
_OVERRIDE_PARAM_NAMES: tuple[tuple[str, str, str, bool], ...] = (
    # (overrides-attr, dict-key, url-param, is_percent)
    ("layer1", "aisc_max", "aisc_target", False),
    ("layer1", "margin_min", "margin_target", True),
    ("layer1", "fcf_yield_min", "fcf_yield_target", True),
    ("layer1", "reserve_life_min", "reserve_life_target", False),
    ("layer1", "leverage_max", "leverage_target", False),
    ("verdict", "strong_candidate_forward_pe_max", "pe_target", False),
    ("jurisdiction", "tier_1", "tier1_discount", True),
    ("jurisdiction", "tier_2", "tier2_discount", True),
    ("jurisdiction", "tier_3", "tier3_discount", True),
)


def _override_query_params(
    overrides: ScreeningOverrides,
    *,
    include_gold: bool = True,
) -> dict[str, str]:
    """Active overrides as URL-param name -> display value.

    The single source for both hidden form inputs and dial preset links,
    so neither surface can silently drop the other's state. Percent-style
    fields are emitted in typed-percent form (15 not 0.15) to match how
    the form inputs render them; the override parser accepts either.
    """
    params: dict[str, str] = {}
    if include_gold and overrides.gold_price is not None:
        params["gold_price"] = _fmt_form_number(overrides.gold_price)
    for attr_name, dict_key, param_name, is_percent in _OVERRIDE_PARAM_NAMES:
        bucket = getattr(overrides, attr_name)
        if dict_key not in bucket:
            continue
        value = bucket[dict_key]
        params[param_name] = f"{value * 100:g}" if is_percent else _fmt_form_number(value)
    return params


def _render_overrides_as_hidden_inputs(
    overrides: ScreeningOverrides,
    *,
    rank_by: str,
    differences_only: bool,
) -> str:
    """Hidden form fields for every active override.

    Used by the search/filter form so submitting it doesn't silently
    clear the screening scenario.
    """
    params = _override_query_params(overrides)
    _add_view_params(params, rank_by=rank_by, differences_only=differences_only)
    return "".join(
        f"<input type=\"hidden\" name=\"{escape(name)}\" value=\"{escape(value)}\">"
        for name, value in params.items()
    )


def _render_view_hidden_inputs(*, rank_by: str, differences_only: bool) -> str:
    params: dict[str, str] = {}
    _add_view_params(params, rank_by=rank_by, differences_only=differences_only)
    return "".join(
        f"<input type=\"hidden\" name=\"{escape(name)}\" value=\"{escape(value)}\">"
        for name, value in params.items()
    )


def _add_view_params(
    params: dict[str, str],
    *,
    rank_by: str,
    differences_only: bool,
) -> None:
    if rank_by == "official":
        params["fundamentals_source"] = "yahoo"
    if differences_only:
        params["differences_only"] = "1"


def _text_input_label(
    label: str,
    *,
    name: str,
    value: str,
    placeholder: str = "",
) -> str:
    placeholder_attr = (
        f" placeholder=\"{escape(placeholder)}\"" if placeholder else ""
    )
    return (
        f"<label><span>{escape(label)}</span>"
        f"<input name=\"{escape(name)}\" type=\"text\" "
        f"value=\"{escape(value)}\"{placeholder_attr}></label>"
    )


def _number_input_label(
    label: str,
    *,
    name: str,
    value: str,
    step: str,
    minimum: str,
    maximum: str | None = None,
) -> str:
    max_attr = f" max=\"{escape(maximum)}\"" if maximum is not None else ""
    return (
        f"<label><span>{escape(label)}</span>"
        f"<input name=\"{escape(name)}\" type=\"number\" "
        f"step=\"{escape(step)}\" min=\"{escape(minimum)}\"{max_attr} "
        f"value=\"{escape(value)}\"></label>"
    )


def _render_rank_controls(*, rank_by: str, differences_only: bool) -> str:
    official_selected = " selected" if rank_by == "official" else ""
    our_selected = " selected" if rank_by != "official" else ""
    checked = " checked" if differences_only else ""
    return (
        "<label><span>Financials source</span>"
        "<select name=\"fundamentals_source\">"
        f"<option value=\"our\"{our_selected}>Our View</option>"
        f"<option value=\"yahoo\"{official_selected}>Yahoo Fundamentals</option>"
        "</select></label>"
        "<label class=\"checkbox-label\">"
        f"<input type=\"checkbox\" name=\"differences_only\" value=\"1\"{checked}>"
        "<span>Differences only</span>"
        "</label>"
    )


def _normalize_rank_by(value: object) -> str:
    return "official" if normalize_finance_source(value) == "yahoo" else "our_view"


def _ticker_href(ticker: object, *, rank_by: str) -> str:
    ticker_text = str(ticker or "").upper().strip()
    return build_page_url(
        f"/ticker/{quote(ticker_text, safe='')}",
        {},
        set_params=(
            {"fundamentals_source": "yahoo"}
            if rank_by == "official"
            else {}
        ),
    )
