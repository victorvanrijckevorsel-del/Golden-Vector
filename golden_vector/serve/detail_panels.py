"""Detail-panel rendering helpers for the workspace ticker page."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

import pandas as pd

from golden_vector.contracts.config_models import AppConfig
from golden_vector.hedge.option_trading import OptionTradingDetailData
from golden_vector.hedge.scenarios import CandidateScenarioBundle
from golden_vector.model.structural import build_trailing_window_rows
from golden_vector.serve.charts import (
    _build_beta_history_svg,
    _build_dual_bar_svg,
    _build_scatter_svg,
)
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _is_na,
    _metric_card,
    _optional_float,
    _render_small_table,
)
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD,
    DETAIL_ALIGNMENT_FOUNDATION_MISSING,
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH,
    StructuralHistoryLoad,
    ToolADetailState,
    _STRUCTURAL_WINDOWS,
    _WINDOW_WEEKS,
    _structural_history_matches_tool_a,
)


def _render_window_switcher(
    *,
    ticker: str,
    active: str,
    canonical: str,
    lens: str | None = None,
    anchor: str | None = None,
) -> str:
    """Three-tab switcher at the top of the detail page: 6M / 12M / 3Y.

    Clicking a tab navigates to the same ticker with `?window=<id>`. Optional
    lens/anchor values keep tool-specific detail views stable while the user
    switches structural windows.
    """
    tabs: list[str] = []
    base = f"/ticker/{quote(str(ticker), safe='')}"
    lens_value = str(lens or "").strip()
    anchor_value = str(anchor or "").strip()
    for window in _STRUCTURAL_WINDOWS:
        is_active = window == active
        is_canonical = window == canonical
        cls = "window-tab active" if is_active else "window-tab"
        query_parts = []
        if window != canonical:
            query_parts.append(f"window={window.lower()}")
        if lens_value:
            query_parts.append(f"lens={quote(lens_value, safe='')}")
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        fragment = f"#{quote(anchor_value, safe='')}" if anchor_value else ""
        href = f"{base}{query}{fragment}"
        canonical_marker = (
            " <span class=\"window-canonical\">anchor</span>" if is_canonical else ""
        )
        tabs.append(
            f"<a class=\"{cls}\" href=\"{escape(href, quote=True)}\">{escape(window)}{canonical_marker}</a>"
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


def _render_option_trading_panel(detail: OptionTradingDetailData | None) -> str:
    body = [
        "<section id=\"option-trading\" class=\"panel\">",
        "<h2>Option Trading</h2>",
        "<p class=\"hint\">Downside put candidates are modeled server-side from the "
        "same cached candidate grid used by the Option Trading tab.</p>",
    ]
    if detail is None:
        body.append(
            "<p>No option-trading data is available yet. Run "
            "<code>python main.py update-data</code> to refresh options data.</p>"
        )
        body.append("</section>")
        return "".join(body)
    if detail.row is None:
        reason = detail.reason or "This ticker is not optionable in the latest snapshot."
        body.append(f"<p>{escape(reason)}</p>")
        body.append("</section>")
        return "".join(body)

    row = detail.row
    if detail.risk_free_rate_is_fallback:
        body.append(
            "<p class=\"hint\">Risk-free rate was missing from the options manifest; "
            "scenario values use a 0% rate fallback.</p>"
        )
    body.extend(
        [
            "<table><tbody>",
            "<tr><th>Down Beta</th>"
            f"<td>{_fmt_number(row.down_beta_core, decimals=2)}</td></tr>",
            f"<tr><th>Put Status</th><td>{_fmt_text(row.put_status)}</td></tr>",
            f"<tr><th>Optionability</th><td>{_fmt_text(row.optionability_tier)}</td></tr>",
            "<tr><th>Put P&amp;L/share @ Gold -10% (60d)</th>"
            f"<td>{_fmt_number(row.pnl_put_at_minus10_60d, decimals=2)}</td></tr>",
            "</tbody></table>",
        ]
    )
    body.append(_render_option_candidate_table(detail))
    body.append(_render_option_scenario_tables(detail.put_bundles))
    if row.notes:
        notes = "".join(f"<li>{escape(note)}</li>" for note in row.notes)
        body.append(f"<ul class=\"hint\">{notes}</ul>")
    body.append("</section>")
    return "".join(body)


def _render_option_candidate_table(detail: OptionTradingDetailData) -> str:
    if not detail.put_candidates:
        return (
            "<section class=\"nested-panel\">"
            "<h3>Downside Put Candidates</h3>"
            "<p>No usable listed put candidate was found for this ticker.</p>"
            "</section>"
        )
    rows = []
    for candidate in detail.put_candidates:
        rows.append(
            "<tr>"
            f"<td>{_fmt_number(candidate.horizon_days, decimals=0)}d</td>"
            f"<td>{_fmt_number(candidate.strike, decimals=2)}</td>"
            f"<td>{escape(candidate.expiration)}</td>"
            f"<td>{_fmt_number(candidate.mid, decimals=2)}</td>"
            f"<td>{_fmt_number(candidate.bid, decimals=2)} / {_fmt_number(candidate.ask, decimals=2)}</td>"
            f"<td>{_fmt_number(candidate.open_interest, decimals=0)}</td>"
            f"<td>{_fmt_number(candidate.volume, decimals=0)}</td>"
            f"<td>{_fmt_percent(candidate.implied_volatility, decimals=1)}</td>"
            f"<td>{_fmt_number(candidate.delta, decimals=2)}</td>"
            "</tr>"
        )
    return (
        "<section class=\"nested-panel\">"
        "<h3>Downside Put Candidates</h3>"
        "<table>"
        "<thead><tr><th>Horizon</th><th>Strike</th><th>Expiry</th><th>Mid</th>"
        "<th>Bid / Ask</th><th>Open Interest</th><th>Volume</th><th>IV</th><th>Delta</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _render_option_scenario_tables(
    bundles: tuple[CandidateScenarioBundle, ...],
) -> str:
    if not bundles:
        return (
            "<section class=\"nested-panel\">"
            "<h3>Downside Put Scenarios</h3>"
            "<p>No put scenarios are available for this ticker.</p>"
            "</section>"
        )
    sections: list[str] = [
        "<section class=\"nested-panel\">",
        "<h3>Downside Put Scenarios</h3>",
        "<p class=\"hint\">P&amp;L/share uses listed per-share option quotes. Net P&amp;L "
        "uses one standard 100-share contract until the sizing calculator lands.</p>",
    ]
    for bundle in bundles:
        sections.append(
            f"<h4>{escape(bundle.horizon)} put, strike {_fmt_number(bundle.candidate.strike, decimals=2)}</h4>"
        )
        if bundle.skipped_reason:
            sections.append(f"<p>{escape(bundle.skipped_reason)}</p>")
            continue
        if bundle.breakeven_annotation:
            sections.append(f"<p class=\"hint\">{escape(bundle.breakeven_annotation)}</p>")
        elif bundle.breakeven_gold_pct is not None:
            sections.append(
                f"<p class=\"hint\">Breakeven gold move: {_fmt_percent(bundle.breakeven_gold_pct, decimals=1)}.</p>"
            )
        rows = []
        for row in bundle.rows:
            rows.append(
                "<tr>"
                f"<td>{_fmt_percent(row.gold_pct_change, decimals=1)}</td>"
                f"<td>{_fmt_number(row.implied_stock_price, decimals=2)}</td>"
                f"<td>{_fmt_number(row.current_value_per_contract, decimals=2)}</td>"
                f"<td>{_fmt_number(row.expiry_value_per_contract, decimals=2)}</td>"
                f"<td>{_fmt_number(row.pnl_per_contract_if_closed_today, decimals=2)}</td>"
                f"<td>{_fmt_number(row.pnl_per_contract_at_expiry, decimals=2)}</td>"
                f"<td>{_fmt_number(row.net_pnl_at_expiry, decimals=0)}</td>"
                "</tr>"
            )
        sections.append(
            "<table>"
            "<thead><tr><th>Gold Move</th><th>Modeled Stock</th><th>Value Now</th>"
            "<th>Value At Expiry</th><th>P&amp;L/share Now</th><th>P&amp;L/share Expiry</th>"
            "<th>Net Expiry P&amp;L</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody>"
            "</table>"
        )
    sections.append("</section>")
    return "".join(sections)


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
