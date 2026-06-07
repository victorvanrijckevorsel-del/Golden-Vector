"""Tool B overview rendering and scenario override helpers."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd

from golden_vector.app.latest_data import load_latest_foundation_snapshot
from golden_vector.app.model_state import resolve_current_foundation_manifest_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import AppConfig
from golden_vector.screening.manual_data import load_manual_screening_data
from golden_vector.screening.pipeline import compute_tool_b_in_memory
from golden_vector.serve.format_helpers import (
    _fmt_form_number,
    _fmt_numeric_td,
    _fmt_text,
    _frame_index_by_ticker,
    _optional_float,
)
from golden_vector.serve.overview_helpers import (
    _collect_filter_options,
    _render_filter_bar,
    _render_provenance_warnings,
    _render_refresh_summary,
)
from golden_vector.serve.model_state_banner import render_model_state_banner
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.screening_overrides import ScreeningOverrides, apply_overrides
from golden_vector.serve.workspace_state import WorkspaceState


def _render_tool_b_overview_page(
    state: WorkspaceState,
    *,
    flash: str | None,
    search: str = "",
    app_config: AppConfig | None = None,
    paths: ProjectPaths | None = None,
    overrides: ScreeningOverrides | None = None,
    override_error: str | None = None,
) -> str:
    """Tool B focused overview: simple fundamentals and gold-price economics.

    Shows visible checks, standard ratios, and estimates at the selected
    gold-price assumption. Tickers marked INCOMPLETE usually have missing
    manual mining inputs.

    When `overrides.has_any()`, the table is recomputed in memory from
    the current snapshot + manual store with the overlaid screening
    parameters (gold price, thresholds, tier discounts). The persisted
    parquet is left untouched — overrides are scenario tools.
    """
    overrides = overrides or ScreeningOverrides()
    note_counts = (
        state.stock_notes.groupby("ticker").size().to_dict()
        if not state.stock_notes.empty and "ticker" in state.stock_notes.columns
        else {}
    )

    # Either use the latest persisted parquet, or recompute in memory if
    # the user passed any URL-param overrides.
    tool_b_frame, override_runtime_error = _resolve_tool_b_frame(
        state=state,
        overrides=overrides,
        app_config=app_config,
        paths=paths,
    )
    tool_b_index = _frame_index_by_ticker(tool_b_frame)
    search_term = str(search or "").strip().upper()

    derived: list[dict[str, Any]] = []
    for ticker in state.tool_b_tickers:
        if search_term and search_term not in ticker:
            continue
        tool_b_row = tool_b_index.get(ticker, {})
        derived.append({
            "ticker": ticker,
            "tool_b_row": tool_b_row,
            "fundamental_check_rank": _optional_float(
                tool_b_row.get("fundamental_check_rank")
            ),
            "note_count": int(note_counts.get(ticker, 0)),
        })
    derived.sort(
        key=lambda r: (
            0 if r["fundamental_check_rank"] is not None else 1,
            r["fundamental_check_rank"] if r["fundamental_check_rank"] is not None else 0.0,
            r["ticker"],
        )
    )

    rows_html: list[str] = []
    for row in derived:
        tb = row["tool_b_row"]
        rows_html.append(
            "<tr>"
            f"<td><a href=\"/ticker/{escape(row['ticker'])}\">{escape(row['ticker'])}</a></td>"
            f"<td>{_fmt_text(tb.get('screening_verdict'))}</td>"
            f"<td>{_fmt_text(tb.get('fundamental_check_summary'))}</td>"
            f"{_fmt_numeric_td(tb.get('fundamental_check_score'), decimals=1)}"
            f"{_fmt_numeric_td(row['fundamental_check_rank'], decimals=0)}"
            f"{_fmt_numeric_td(tb.get('share_price_usd'), decimals=2)}"
            f"{_fmt_numeric_td(tb.get('market_cap_musd'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('enterprise_value_musd'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('aisc_usd_per_oz'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('cash_margin_usd_per_oz'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('margin_pct'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(tb.get('forward_ebitda_musd'), decimals=0)}"
            f"{_fmt_numeric_td(tb.get('forward_pe'), decimals=1)}"
            f"{_fmt_numeric_td(tb.get('ev_ebitda'), decimals=1)}"
            f"{_fmt_numeric_td(tb.get('fcf_yield'), decimals=1, as_percent=True)}"
            f"{_fmt_numeric_td(tb.get('leverage'), decimals=2)}"
            f"{_fmt_numeric_td(tb.get('reserve_life_years'), decimals=1)}"
            f"<td>{_fmt_text(tb.get('layer1_status'))}</td>"
            f"{_fmt_numeric_td(row['note_count'], decimals=0)}"
            "</tr>"
        )
    if not rows_html:
        rows_html.append(
            "<tr><td colspan=\"19\" class=\"hint\">No tickers match.</td></tr>"
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
    body.append(
        "<p>Shows industry-standard corporate finance checks at the configured gold-price "
        "assumption. The score is the number of visible checks passed, not a model target price. "
        "Forward EBITDA, P/E, and FCF are transparent estimates at that gold price. "
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
            "Showing the last persisted Corporate Finance snapshot."
            "</div>"
        )
    body.append(render_model_state_banner(state.model_state_manifest))
    body.append(_render_provenance_warnings(state))
    body.append(_render_refresh_summary(state.foundation_manifest))
    if app_config is not None:
        body.append(_render_screening_params_form(
            app_config=app_config,
            overrides=overrides,
            search=search,
        ))
    # Filter form carries hidden override fields so submitting it doesn't
    # silently clear the active scenario. The "Reset" link still drops
    # everything by linking to bare /tool-b.
    body.append(
        "<section class=\"panel\">"
        "<form method=\"get\" action=\"/tool-b\" class=\"overview-filters-form\">"
        f"{_render_overrides_as_hidden_inputs(overrides)}"
        f"<label><span>Search ticker</span><input name=\"search\" type=\"text\" value=\"{escape(search)}\" placeholder=\"NEM\"></label>"
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
        "<th data-col-name=\"ticker\">Ticker</th>"
        "<th data-col-name=\"verdict\">Verdict</th>"
        "<th data-col-name=\"check_summary\">Checks</th>"
        "<th data-col-name=\"score\" data-sort-numeric>Checks Passed %</th>"
        "<th data-col-name=\"rank\" data-sort-numeric>Rank</th>"
        "<th data-col-name=\"share_price\" data-sort-numeric>Share Price</th>"
        "<th data-col-name=\"market_cap\" data-sort-numeric>Market Cap</th>"
        "<th data-col-name=\"enterprise_value\" data-sort-numeric>Enterprise Value</th>"
        "<th data-col-name=\"aisc\" data-sort-numeric>AISC</th>"
        "<th data-col-name=\"cash_margin\" data-sort-numeric>Cash Margin/oz</th>"
        "<th data-col-name=\"margin_pct\" data-sort-numeric>Margin %</th>"
        "<th data-col-name=\"forward_ebitda\" data-sort-numeric>Forward EBITDA est.</th>"
        "<th data-col-name=\"forward_pe\" data-sort-numeric>Forward P/E est.</th>"
        "<th data-col-name=\"ev_ebitda\" data-sort-numeric>EV/EBITDA est.</th>"
        "<th data-col-name=\"fcf_yield\" data-sort-numeric>FCF Yield est.</th>"
        "<th data-col-name=\"leverage\" data-sort-numeric>Net Debt/EBITDA</th>"
        "<th data-col-name=\"reserve_life\" data-sort-numeric>Reserve Life</th>"
        "<th data-col-name=\"layer1\">Layer 1</th>"
        "<th data-col-name=\"notes\" data-sort-numeric>Notes</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table>"
    )
    return _page_shell("Corporate Finance - Golden Vector Workspace", "".join(body), active_nav="tool_b")


def _resolve_tool_b_frame(
    *,
    state: WorkspaceState,
    overrides: ScreeningOverrides,
    app_config: AppConfig | None,
    paths: ProjectPaths | None,
) -> tuple[pd.DataFrame, str | None]:
    """Return (frame, runtime_error_message).

    If no overrides are active, use `state.latest_tool_b` (the persisted
    parquet). Otherwise, recompute in memory with the overlaid config.
    On unexpected recompute failure, fall back to the persisted parquet
    and surface the error message so the user sees what went wrong.
    """
    if not overrides.has_any() or app_config is None or paths is None:
        return state.latest_tool_b, None

    try:
        overridden_config = apply_overrides(app_config, overrides)
        foundation_manifest_path = resolve_current_foundation_manifest_path(
            paths,
            require_current_manifest=True,
        )
        foundation_snapshot = load_latest_foundation_snapshot(
            paths=paths,
            app_config=overridden_config,
            include_gold_history=False,
            include_equity_histories=False,
            include_market_snapshots=True,
            manifest_path=foundation_manifest_path,
        )
        manual_data = load_manual_screening_data(
            paths,
            tickers=state.tool_b_tickers,
        )
        gold_price = overridden_config.screening_params.resolve_gold_price(overrides.gold_price)
        recomputed = compute_tool_b_in_memory(
            app_config=overridden_config,
            manual_data=manual_data,
            normalized_market_snapshots=foundation_snapshot.normalized_market_snapshots,
            gold_price_assumption=gold_price,
            snapshot_refresh_run_id=foundation_snapshot.refresh_run_id,
            snapshot_as_of_date=foundation_snapshot.snapshot_as_of_date,
            source_run_id="workspace-in-memory",
        )
        if not recomputed.empty and "ticker" in recomputed.columns:
            recomputed["ticker"] = recomputed["ticker"].astype(str).str.upper()
        return recomputed, None
    except Exception as exc:  # broad catch: fall back to persisted parquet
        return state.latest_tool_b, str(exc)


def _render_screening_params_form(
    *,
    app_config: AppConfig,
    overrides: ScreeningOverrides,
    search: str,
) -> str:
    """Render the "Screening Parameters" form panel for the Tool B view.

    Mirrors the yellow-highlighted cells of the friend's Excel
    `Summary & Parameters` sheet: gold price, six Layer 1 thresholds and
    the three jurisdiction tier discounts. Values pre-fill from either
    the active overrides (if any) or the YAML defaults.
    """
    sp = app_config.screening_params
    current_gold = sp.resolve_gold_price(None)

    gold_price_value = overrides.gold_price if overrides.gold_price is not None else current_gold
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

    active_banner = ""
    if overrides.has_any():
        active_banner = (
            "<p class=\"hint\"><strong>Scenario active:</strong> recomputing live from manual "
            "data + latest snapshot. YAML defaults and persisted parquet are unchanged. "
            "<a href=\"/tool-b\">Clear overrides</a>.</p>"
        )

    # Percent-valued fields display the typed percent (15 for 15%) rather
    # than the fraction (0.15). The override parser accepts either.
    def _as_percent_display(fraction: float) -> str:
        return f"{fraction * 100:g}"

    # Carry the search term through the form so the user doesn't lose it.
    search_hidden = (
        f"<input type=\"hidden\" name=\"search\" value=\"{escape(search)}\">"
        if search else ""
    )

    return (
        "<section class=\"panel screening-params\">"
        "<h2>Screening Parameters</h2>"
        f"{active_banner}"
        "<form method=\"get\" action=\"/tool-b\" class=\"screening-params-form\">"
        f"{search_hidden}"
        "<div class=\"screening-params-grid\">"
        f"<label><span>Gold Price ($/oz)</span>"
        f"<input name=\"gold_price\" type=\"number\" step=\"1\" min=\"1\" value=\"{_fmt_form_number(gold_price_value)}\"></label>"
        f"<label><span>Strong P/E cutoff (&lt;)</span>"
        f"<input name=\"pe_target\" type=\"number\" step=\"0.1\" min=\"0.1\" value=\"{_fmt_form_number(pe_target)}\"></label>"
        f"<label><span>Minimum FCF yield (%)</span>"
        f"<input name=\"fcf_yield_target\" type=\"number\" step=\"0.5\" min=\"0\" value=\"{_as_percent_display(fcf_yield_target)}\"></label>"
        f"<label><span>AISC cutoff ($/oz)</span>"
        f"<input name=\"aisc_target\" type=\"number\" step=\"10\" min=\"1\" value=\"{_fmt_form_number(aisc_target)}\"></label>"
        f"<label><span>Minimum margin (%)</span>"
        f"<input name=\"margin_target\" type=\"number\" step=\"1\" min=\"0\" value=\"{_as_percent_display(margin_target)}\"></label>"
        f"<label><span>Minimum reserve life (yrs)</span>"
        f"<input name=\"reserve_life_target\" type=\"number\" step=\"0.5\" min=\"0\" value=\"{_fmt_form_number(reserve_life_target)}\"></label>"
        f"<label><span>Net Debt/EBITDA cutoff</span>"
        f"<input name=\"leverage_target\" type=\"number\" step=\"0.1\" min=\"0\" value=\"{_fmt_form_number(leverage_target)}\"></label>"
        f"<label><span>Tier 1 Discount (%)</span>"
        f"<input name=\"tier1_discount\" type=\"number\" step=\"1\" min=\"0\" max=\"100\" value=\"{_as_percent_display(tier1)}\"></label>"
        f"<label><span>Tier 2 Discount (%)</span>"
        f"<input name=\"tier2_discount\" type=\"number\" step=\"1\" min=\"0\" max=\"100\" value=\"{_as_percent_display(tier2)}\"></label>"
        f"<label><span>Tier 3 Discount (%)</span>"
        f"<input name=\"tier3_discount\" type=\"number\" step=\"1\" min=\"0\" max=\"100\" value=\"{_as_percent_display(tier3)}\"></label>"
        "</div>"
        "<div class=\"screening-params-actions\">"
        "<button type=\"submit\">Apply scenario</button>"
        "<a class=\"hint\" href=\"/tool-b\">Reset all</a>"
        "</div>"
        "</form>"
        "</section>"
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


def _render_overrides_as_hidden_inputs(overrides: ScreeningOverrides) -> str:
    """Hidden form fields for every active override.

    Used by the search/filter form so submitting it doesn't silently
    clear the screening scenario. Percent-style fields are emitted in
    typed-percent form (15 not 0.15) to match how the form input renders
    them — the override parser accepts either, but keeping the form
    round-trip consistent makes the URL state visible to the user.
    """
    parts: list[str] = []
    if overrides.gold_price is not None:
        parts.append(
            f"<input type=\"hidden\" name=\"gold_price\" value=\"{_fmt_form_number(overrides.gold_price)}\">"
        )
    for attr_name, dict_key, param_name, is_percent in _OVERRIDE_PARAM_NAMES:
        bucket = getattr(overrides, attr_name)
        if dict_key not in bucket:
            continue
        value = bucket[dict_key]
        display = f"{value * 100:g}" if is_percent else _fmt_form_number(value)
        parts.append(
            f"<input type=\"hidden\" name=\"{escape(param_name)}\" value=\"{escape(display)}\">"
        )
    return "".join(parts)
