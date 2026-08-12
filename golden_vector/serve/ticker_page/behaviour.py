"""M3c: the Market behaviour section of the redesigned ticker page.

What lives here (requirements §2 position 3, §3 "Charts" + "Lab", §4):

* the beta-window switcher — a *behaviour* control, so it moved out of the
  global control bar into this section's header (the ``window`` query param
  round-trips exactly as before);
* open by default: the up/down beta bars and the universe percentile rugs
  (Victor asked for both as-is, so they moved unchanged), the Tool C relative
  record, and the cost-position/downside card;
* closed: "How it behaved in past gold moves" (the Lab) and "Full research
  detail".

Render-only, like the rest of ``serve/ticker_page``: every number is read from
a persisted artifact (the five ticker-page artifacts, the published Tool A row,
or the Lab artifacts through their loaders). Nothing is computed in the request
path — the old non-canonical-window volatility recompute (a serve-side
least-squares fit) is deleted, not moved (plan §9.3 / P2).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from html import escape
from typing import Any, Mapping
from urllib.parse import quote

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.strings import ordinal_percentile as _ordinal_percentile
from golden_vector.common.windows import window_label
from golden_vector.contracts.config_models import (
    TICKER_PAGE_LAB_HORIZON_WEEKS,
    AppConfig,
)
from golden_vector.lab.conditional_dial import BUCKET_LABELS, DEFAULT_DIAL_BUCKET
from golden_vector.serve.charts import (
    _STOCK_SERIES,
    _benchmark_series,
    _build_beta_strip_svg,
    _build_dual_bar_svg,
    _build_grouped_beta_bar_svg,
    _build_scatter_svg,
)
from golden_vector.serve.column_help import help_icon, help_th
from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _metric_card,
    _optional_float,
    id_token as _id_token,
)
from golden_vector.serve.lab_curve_data import (
    lab_artifact_pointer,
    load_dial_cells,
    load_ticker_curve,
)
from golden_vector.serve.lab_curve_page import (
    _render_chart_a,
    _render_distribution,
    _render_profile,
    lab_unavailable_reason,
)
from golden_vector.serve.ticker_page.data import TickerPageData
from golden_vector.serve.ticker_page.sections import (
    _fmt_date,
    _fmt_pct,
    format_evidence_period,
    format_hit_evidence,
    render_cost_downside_card,
)
from golden_vector.serve.ui.components import disclosure, section_heading
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.windows import SCORING_WINDOWS, WINDOW_LABELS
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD,
    DETAIL_ALIGNMENT_FOUNDATION_MISSING,
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH,
    _STRUCTURAL_WINDOWS,
    _structural_history_matches_tool_a,
)

SECTION_ID = "market-behaviour"
LAB_ANCHOR = f"#{SECTION_ID}"
LAB_HORIZON_WEEKS: tuple[int, ...] = tuple(sorted(TICKER_PAGE_LAB_HORIZON_WEEKS))
LAB_BENCHMARKS: tuple[str, ...] = ("GDX", "GDXJ")
SURVIVOR_CAVEAT = (
    "Survivor-only history: only miners still trading today are in this sample, "
    "so delisted losers are missing and the real beat-rates were probably lower. "
    "This is counted history, not a forecast — it sits behind this disclosure so "
    "it never reads as an equal of the measured betas above."
)
VOLATILITY_CANONICAL_NOTE = (
    "Volatility diagnostics are published for the canonical window only. They are "
    "not recomputed here for other windows — an estimate made in the page would "
    "not be the published number."
)


# ---------------------------------------------------------------------------
# beta-window switcher (moved here from the global control bar)
# ---------------------------------------------------------------------------


def _sizing_query_parts(sizing_request: object | None) -> list[str]:
    """Serialize the option sizing request into URL query parts so window-tab
    navigation preserves the user's calculator state (audit L3). Only meaningful,
    non-default values are emitted to keep URLs clean."""

    if sizing_request is None:
        return []
    parts: list[str] = []
    side = str(getattr(sizing_request, "side", "") or "").strip()
    if side and side != "put":  # "put" is the default landing side; omit it
        parts.append(f"side={quote(side, safe='')}")
    if getattr(sizing_request, "horizon_explicit", False):
        parts.append(f"horizon={int(getattr(sizing_request, 'horizon_days', 0))}")
    bucket = getattr(sizing_request, "bucket", None)
    if bucket:
        parts.append(f"bucket={quote(str(bucket), safe='')}")
    if getattr(sizing_request, "size_explicit", False):
        size_mode = str(getattr(sizing_request, "size_mode", "") or "").strip()
        if size_mode == "budget":
            parts.append("size_mode=budget")
            budget = getattr(sizing_request, "budget", None)
            if budget is not None:
                parts.append(f"budget={quote(f'{float(budget):g}', safe='')}")
        elif size_mode == "contracts":
            quantity = getattr(sizing_request, "quantity", None)
            if quantity is not None:
                parts.append(f"quantity={int(quantity)}")
    return parts


def render_window_switcher(
    *,
    ticker: str,
    active: str,
    canonical: str,
    lens: str | None = None,
    anchor: str | None = None,
    sizing_request: object | None = None,
    financials_source: str = "our",
    app_config: AppConfig | None = None,
) -> str:
    """Beta-window tabs (6M / 1Y / 2Y / 3Y / 5Y; 12M renders as "1Y").

    Moved out of the page control bar into the Market-behaviour header: the beta
    window is a behaviour concept and is independent of the performance chart's
    horizon (requirements §3). The ``window=`` query param semantics, the lens /
    anchor / sizing-state preservation and the fundamentals-source carry are
    unchanged from the control-bar version.
    """

    tabs: list[str] = []
    base = f"/ticker/{quote(str(ticker), safe='')}"
    lens_value = str(lens or "").strip()
    anchor_value = str(anchor or "").strip()
    source_value = str(financials_source or "our").strip().lower()
    sizing_parts = _sizing_query_parts(sizing_request)
    for window in _STRUCTURAL_WINDOWS:
        is_active = window == active
        is_canonical = window == canonical
        cls = "window-tab active" if is_active else "window-tab"
        query_parts = []
        if window != canonical:
            query_parts.append(f"window={window.lower()}")
        if lens_value:
            query_parts.append(f"lens={quote(lens_value, safe='')}")
        if source_value == "yahoo":
            query_parts.append("fundamentals_source=yahoo")
        query_parts.extend(sizing_parts)
        query = f"?{'&'.join(query_parts)}" if query_parts else ""
        fragment = f"#{quote(anchor_value, safe='')}" if anchor_value else LAB_ANCHOR
        href = f"{base}{query}{fragment}"
        canonical_marker = (
            " <span class=\"window-canonical\">anchor</span>" if is_canonical else ""
        )
        tabs.append(
            f"<a class=\"{cls}\" href=\"{escape(href, quote=True)}\""
            + (" aria-current=\"true\"" if is_active else "")
            + f">{escape(WINDOW_LABELS.get(window, window))}{canonical_marker}</a>"
        )
    mismatch_note = ""
    if active != canonical:
        mismatch_note = (
            f"<p class=\"hint window-mismatch\">Viewing {escape(WINDOW_LABELS.get(active, active))} — "
            f"the canonical anchor window for this ticker is "
            f"{escape(WINDOW_LABELS.get(canonical, canonical))}.</p>"
        )
    return (
        "<div class=\"window-switcher\" role=\"group\" aria-label=\"Beta window\">"
        + help_icon(
            "Beta window", key="ticker_beta_window_switcher", app_config=app_config
        )
        + "<div class=\"window-tabs\">"
        + "".join(tabs)
        + "</div>"
        + mismatch_note
        + "</div>"
    )


# ---------------------------------------------------------------------------
# notices (moved; score prose removed)
# ---------------------------------------------------------------------------


def _render_alignment_notice(alignment: str) -> str:
    messages = {
        DETAIL_ALIGNMENT_FOUNDATION_AHEAD: (
            "The current foundation snapshot has moved ahead of the published beta row. "
            "Foundation-backed panels below are suppressed to avoid mixing data from different "
            "refreshes. Re-run <code>python main.py tool-a</code> to realign."
        ),
        DETAIL_ALIGNMENT_FOUNDATION_MISSING: (
            "No validated foundation snapshot is available for provenance alignment. "
            "Run <code>python main.py update-data</code>, then <code>python main.py tool-a</code>."
        ),
        DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: (
            "The published beta row does not carry a snapshot refresh identifier, "
            "so provenance cannot be confirmed. Re-run <code>python main.py tool-a</code>."
        ),
    }
    if alignment not in messages:
        return ""
    return notice("warning", f"<p>{messages[alignment]}</p>")


def _render_metrics_load_notice(metrics_load: Any, *, tool_a_row: Mapping[str, Any]) -> str:
    """One consistent file-health story for the beta panels below."""

    status = getattr(metrics_load, "status", "ok")
    if status == "ok":
        if tool_a_row and not _structural_history_matches_tool_a(
            metrics_load.history, dict(tool_a_row)
        ):
            return notice(
                "warning",
                "<p>The structural metrics file was produced by a different tool-a run than the "
                "published row, so the beta panels below may not match it. Re-run "
                "<code>python main.py tool-a</code> to realign.</p>",
            )
        return ""
    messages = {
        "missing": (
            "Structural metrics file is missing, so the beta panels below cannot draw their "
            "anchor metrics. Run <code>python main.py tool-a</code> to generate it."
        ),
        "corrupt": (
            "Could not read the structural metrics file. Re-run "
            "<code>python main.py tool-a</code> to regenerate it."
        ),
        "no_rows": (
            "Structural metrics file exists but has no rows for this ticker. Re-run "
            "<code>python main.py tool-a</code> after a fresh data refresh."
        ),
    }
    message = messages.get(str(status))
    if not message:
        return ""
    detail = getattr(metrics_load, "error_message", "") or ""
    if status == "corrupt" and detail:
        message += f" Underlying error: {escape(str(detail))}"
    return notice("warning", f"<p>{message}</p>")


def _render_normalization_notice(tool_a_row: Mapping[str, Any]) -> str:
    """Data-quality status only.

    The old "score is withheld" sentences went with the score (requirements §3:
    no compiled score is displayed on this page). Observed normalization issues
    are a *data* status, not an opinion, so they stay.
    """

    summary = _fmt_text(tool_a_row.get("normalization_issue_summary"))
    if summary == "-":
        return ""
    return notice(
        "warning",
        f"<p>Observed normalization issues in the trailing sample: {summary}.</p>",
    )


def _render_suppressed_panel(title: str, reason: str, command: str) -> str:
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)} &mdash; Out of Sync</h3>"
        f"<p>{escape(reason)}</p>"
        f"<p class=\"hint\">Run <code>{escape(command)}</code> to realign.</p>"
        "</section>"
    )


_SUPPRESSION_REASONS = {
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD: (
        "The foundation snapshot on disk differs from the published beta row, so this panel is "
        "suppressed to avoid mixing data from different refreshes."
    ),
    DETAIL_ALIGNMENT_FOUNDATION_MISSING: (
        "No validated foundation snapshot is available, so this panel cannot be rebuilt safely "
        "from the published row's refresh context."
    ),
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: (
        "The published beta row does not carry a snapshot refresh identifier, so this panel "
        "cannot be matched to a foundation snapshot and is suppressed for safety."
    ),
}
_SUPPRESSION_COMMANDS = {
    DETAIL_ALIGNMENT_FOUNDATION_AHEAD: "python main.py tool-a",
    DETAIL_ALIGNMENT_FOUNDATION_MISSING: "python main.py update-data",
    DETAIL_ALIGNMENT_TOOL_A_MISSING_REFRESH: "python main.py tool-a",
}


# ---------------------------------------------------------------------------
# up/down beta bars + universe rugs (moved essentially unchanged)
# ---------------------------------------------------------------------------


def _grouped_beta_bars(comparison: Any, side: str) -> list[dict[str, Any]]:
    """One grouped-bar entry (stock + each benchmark) for the up/down side, from resolved values."""

    bars: list[dict[str, Any]] = []
    if comparison.subject is not None:
        bars.append(
            {
                "label": comparison.subject.label,
                "value": getattr(comparison.subject, f"{side}_beta"),
                "series": _STOCK_SERIES,
            }
        )
    for index, marker in enumerate(comparison.benchmarks):
        bars.append(
            {
                "label": marker.label,
                "value": getattr(marker, f"{side}_beta"),
                "series": _benchmark_series(marker.label, index),
            }
        )
    return bars


def render_up_down_beta_panel(
    *,
    anchor_metric: Mapping[str, Any],
    active_window: str = "12M",
    comparison: Any = None,
    app_config: AppConfig | None = None,
) -> str:
    up_beta = _optional_float(anchor_metric.get("up_beta"))
    down_beta = _optional_float(anchor_metric.get("down_beta"))
    explain = help_icon("Up vs down beta", key="ticker_up_down_beta", app_config=app_config)
    if up_beta is None and down_beta is None:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>Up vs Down Beta{explain}</h3><p>No "
            f"{escape(WINDOW_LABELS.get(active_window, active_window))} regime split is "
            "available yet.</p></section>"
        )
    has_benchmarks = (
        comparison is not None
        and getattr(comparison, "subject", None) is not None
        and comparison.benchmarks
    )
    if has_benchmarks:
        svg = _build_grouped_beta_bar_svg(
            groups=[
                {"label": "Up-Gold (weeks gold rose)", "bars": _grouped_beta_bars(comparison, "up")},
                {"label": "Down-Gold (weeks gold fell)", "bars": _grouped_beta_bars(comparison, "down")},
            ],
        )
        # Swatch classes come from the SAME semantic series keys the bars use, so the legend
        # can never drift from the bars it labels, and it enumerates only the benchmarks that
        # were actually resolved into the chart.
        legend_items = [f"<span class=\"legend-swatch-{_STOCK_SERIES}\">■ this stock</span>"]
        for index, marker in enumerate(comparison.benchmarks):
            legend_items.append(
                f"<span class=\"legend-swatch-{_benchmark_series(marker.label, index)}\">"
                f"■ {escape(str(marker.label))}</span>"
            )
        legend = (
            "<p class=\"hint\">Bars: "
            + ", ".join(legend_items)
            + " — all on the "
            + f"{escape(WINDOW_LABELS.get(active_window, active_window))} window, so they are "
            "directly comparable.</p>"
        )
    else:
        # Pass None through for a missing side: the builder draws an explicit n/a marker
        # rather than a real-looking 0.00 bar.
        svg = _build_dual_bar_svg(
            left_label="Up-Gold",
            left_value=up_beta,
            right_label="Down-Gold",
            right_value=down_beta,
        )
        legend = ""
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>Up vs Down Beta{explain}</h3>"
        "<p class=\"hint\">Gold beta measured separately on weeks gold rose (up beta) vs weeks "
        f"gold fell (down beta), over the {escape(WINDOW_LABELS.get(active_window, active_window))} "
        "sample. A taller down bar than up bar means it falls more with gold than it rises — a "
        "fragile, asymmetric profile. Either beta can be negative (moves opposite to gold).</p>"
        f"{legend}"
        f"{svg}"
        "</section>"
    )


def _subject_strip_label(ticker: str, beta: float | None, percentile: float | None) -> str:
    """Pre-format the one labelled marker on the universe strip (display only, no math)."""

    if beta is None:
        return ticker
    if percentile is None:
        return f"{ticker} {_fmt_number(beta, decimals=2)}"
    return f"{ticker} {_fmt_number(beta, decimals=2)} · {_ordinal_percentile(percentile)}"


def render_beta_comparison_panel(
    comparison: Any,
    *,
    ticker: str,
    active_window: str = "12M",
    app_config: AppConfig | None = None,
) -> str:
    """Where this stock ranks within the miner universe, on the SAME selected window.

    The strip shows the whole universe as a faint rug, the stock as the one labelled marker, and
    GDX/GDXJ as small context ticks. Every position is resolved in the model layer; this renderer
    only formats text and places backend positions.
    """

    title = "Where its gold beta ranks vs the miner universe"
    explain = help_icon(title, key="ticker_beta_percentile_rug", app_config=app_config)
    if comparison is None or not getattr(comparison, "available", False):
        note = getattr(comparison, "note", None) if comparison is not None else None
        message = note or (
            f"No universe comparison is available for the "
            f"{WINDOW_LABELS.get(active_window, active_window)} window yet."
        )
        return (
            "<section class=\"panel nested-panel\">"
            f"<h3>{escape(title)}{explain}</h3><p class=\"hint\">{escape(message)}</p>"
            "</section>"
        )

    window_label_text = escape(str(comparison.window_label))
    window_label_raw = str(comparison.window_label)
    subject = comparison.subject
    down_svg = _build_beta_strip_svg(
        axis_label=f"Down beta — weeks gold fell ({window_label_raw})",
        domain=comparison.down_domain,
        universe_marks=list(comparison.down_universe_marks),
        subject_pos=subject.down_pos if subject is not None else None,
        subject_label=_subject_strip_label(
            ticker,
            subject.down_beta if subject else None,
            subject.down_percentile if subject else None,
        ),
        benchmark_positions=[m.down_pos for m in comparison.benchmarks if m.down_pos is not None],
        data_table_id=f"chart-data-downbeta-{_id_token(ticker)}-{_id_token(window_label_raw)}",
    )
    up_svg = _build_beta_strip_svg(
        axis_label=f"Up beta — weeks gold rose ({window_label_raw})",
        domain=comparison.up_domain,
        universe_marks=list(comparison.up_universe_marks),
        subject_pos=subject.up_pos if subject is not None else None,
        subject_label=_subject_strip_label(
            ticker,
            subject.up_beta if subject else None,
            subject.up_percentile if subject else None,
        ),
        benchmark_positions=[m.up_pos for m in comparison.benchmarks if m.up_pos is not None],
        data_table_id=f"chart-data-upbeta-{_id_token(ticker)}-{_id_token(window_label_raw)}",
    )

    # Build the lead per side, so a stock with only one side available is described correctly.
    if subject is None:
        lead = (
            f"{escape(ticker)} is not in the scored miner universe, so only the universe spread "
            f"and the GDX/GDXJ ticks are shown for the {window_label_text} window. "
        )
    else:
        side_phrases = []
        if subject.down_percentile is not None:
            side_phrases.append(
                f"its down beta sits at the {_ordinal_percentile(subject.down_percentile)} of the "
                f"{comparison.universe_down_n} scored miners (higher = falls more with gold)"
            )
        if subject.up_percentile is not None:
            side_phrases.append(
                f"its up beta at the {_ordinal_percentile(subject.up_percentile)} of "
                f"{comparison.universe_up_n}"
            )
        if side_phrases:
            lead = (
                f"Over the {window_label_text} window, {escape(ticker)}'s "
                + ", and ".join(side_phrases)
                + ". "
            )
        else:
            lead = (
                f"{escape(ticker)}'s gold beta is not available for the {window_label_text} "
                "window; the universe spread and GDX/GDXJ ticks are shown for context. "
            )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h3>{escape(title)}{explain}</h3>"
        f"<p class=\"hint\">{lead}Each light tick is one of the miners; the "
        f"<span class=\"legend-swatch-{_STOCK_SERIES}\">orange marker</span> is {escape(ticker)}; "
        "the dashed blue ticks are GDX/GDXJ (values on the chart above). Switch the beta window "
        "above to re-base all of them to the same period.</p>"
        f"{down_svg}{up_svg}"
        "</section>"
    )


# ---------------------------------------------------------------------------
# Tool C relative record (persisted percentile rows — raw values + evidence)
# ---------------------------------------------------------------------------

# (metric_key, label, help key, evidence nouns) — evidence nouns are None for
# metrics that publish no counted-hit evidence.
_RECORD_METRICS: tuple[tuple[str, str, str, tuple[str, str] | None], ...] = (
    (
        "rel_strength_vs_gdx",
        "Strength vs GDX",
        "ticker_rel_strength_vs_gdx",
        None,
    ),
    (
        "rel_weakness_vs_gdx",
        "Weakness vs GDX",
        "ticker_rel_weakness_vs_gdx",
        None,
    ),
    (
        "upside_hit_rate",
        "Big up-week hit rate",
        "ticker_upside_hit_rate",
        ("large rises", "qualifying strong-gold weeks"),
    ),
    (
        "downside_hit_rate",
        "Big down-week hit rate",
        "ticker_downside_hit_rate",
        ("large falls", "qualifying weak-gold weeks"),
    ),
    (
        "tail_best10",
        "Best 10% weeks (average)",
        "ticker_tail_best10",
        None,
    ),
    (
        "tail_worst10",
        "Worst 10% weeks (average)",
        "ticker_tail_worst10",
        None,
    ),
)


def _threshold_sentence(app_config: AppConfig | None) -> str:
    """The counted-hit thresholds, read from config — never a hardcoded twin."""

    if app_config is None:
        return ""
    tool_c = app_config.tool_c
    return (
        f"A big down week is a weekly return of {tool_c.downside_hit_rate_threshold_pct:.0f}% "
        f"or worse and a big up week is {tool_c.upside_hit_rate_threshold_pct:+.0f}% or better, "
        f"each counted inside gold's rolling {tool_c.regime_rolling_weeks}-week regime windows."
    )


def _record_row(
    row: pd.Series | None,
    *,
    label: str,
    help_key: str,
    evidence_nouns: tuple[str, str] | None,
    app_config: AppConfig | None,
) -> str:
    header = (
        f"<th scope=\"row\">{escape(label)}"
        f"{help_icon(label, key=help_key, app_config=app_config)}</th>"
    )
    if row is None:
        return (
            f"<tr>{header}<td>n/a</td>"
            "<td class=\"hint\">no published row for this metric</td></tr>"
        )
    if not bool(row.get("metric_available")):
        reason = str(row.get("metric_reason") or "not available")
        return f"<tr>{header}<td>n/a</td><td class=\"hint\">{escape(reason)}</td></tr>"
    value = _fmt_pct(row.get("raw_value"))
    evidence_bits: list[str] = []
    if evidence_nouns is not None:
        evidence_bits.append(
            format_hit_evidence(
                row, hit_noun=evidence_nouns[0], window_noun=evidence_nouns[1]
            )
        )
    basis = str(row.get("basis") or "").strip()
    if basis:
        evidence_bits.append(basis)
    period_start = row.get("source_period_start")
    if period_start is not None and not pd.isna(period_start):
        evidence_bits.append(format_evidence_period(row))
    evidence = " · ".join(bit for bit in evidence_bits if bit) or "no evidence published"
    return f"<tr>{header}<td>{escape(value)}</td><td class=\"hint\">{escape(evidence)}</td></tr>"


def render_relative_record(
    data: TickerPageData | None,
    *,
    ticker: str,
    finance_source: str,
    app_config: AppConfig | None = None,
) -> str:
    """The Tool C relative record: how this miner actually behaved against GDX.

    Raw values plus their counted evidence — no ranks, no percentile ordering,
    no composite. Everything is one persisted percentile row per metric.
    """

    explain = help_icon(
        "Relative record vs GDX", key="ticker_relative_record", app_config=app_config
    )
    if data is None:
        return (
            "<section class=\"panel nested-panel\" id=\"relative-record\">"
            f"<h3>Relative record vs GDX{explain}</h3>"
            "<p class=\"hint\">The ticker-page artifacts are not loaded in this view.</p>"
            "</section>"
        )
    if data.percentiles.status != "OK":
        return (
            "<section class=\"panel nested-panel\" id=\"relative-record\">"
            f"<h3>Relative record vs GDX{explain}</h3>"
            + notice(
                "degraded",
                f"<p>Metric artifact state <strong>{escape(data.percentiles.status)}</strong>: "
                f"{escape(data.percentiles.reason or 'no reason recorded')}. Nothing is "
                "estimated to fill the gap.</p>",
            )
            + "</section>"
        )
    rows_html = "".join(
        _record_row(
            data.metric_row(ticker, metric_key=key, finance_source=finance_source),
            label=label,
            help_key=help_key,
            evidence_nouns=nouns,
            app_config=app_config,
        )
        for key, label, help_key, nouns in _RECORD_METRICS
    )
    table_html = (
        "<table class=\"compact-table\"><thead><tr>"
        "<th scope=\"col\">Measure</th><th scope=\"col\">Value</th>"
        "<th scope=\"col\">Evidence and basis</th>"
        "</tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
    )
    threshold = _threshold_sentence(app_config)
    return (
        "<section class=\"panel nested-panel\" id=\"relative-record\">"
        f"<h3>Relative record vs GDX{explain}</h3>"
        "<p class=\"hint\">Counted history against the gold-miner ETF — share of weeks it was "
        "stronger or weaker, how often the big moves landed, and what the tails averaged.</p>"
        + table_region(
            table_html,
            region_id="behaviour-relative-record",
            label="Relative record vs GDX",
        )
        + (f"<p class=\"hint\">{escape(threshold)}</p>" if threshold else "")
        + "</section>"
    )


# ---------------------------------------------------------------------------
# the Lab disclosure — "How it behaved in past gold moves"
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabRequest:
    """Resolved ``lab_h`` / ``lab_b`` / ``lab_s`` state for one render."""

    horizon: int
    benchmark: str
    bucket: str
    active: bool = False
    note: str = ""


def parse_lab_request(
    query: Mapping[str, Any] | None,
    *,
    app_config: AppConfig | None = None,
) -> LabRequest:
    """Validate the three Lab params. Invalid values fall back WITH a note.

    ``active`` is True when at least one valid Lab param was supplied — that is
    what reopens and anchors the disclosure after a control click.
    """

    default_horizon = (
        int(app_config.ticker_page.lab.default_horizon_weeks)
        if app_config is not None
        else 8
    )
    raw = {key: _first_value(query, key) for key in ("lab_h", "lab_b", "lab_s")}
    notes: list[str] = []
    active = False

    horizon = default_horizon
    if raw["lab_h"]:
        try:
            candidate = int(str(raw["lab_h"]).strip())
        except (TypeError, ValueError):
            candidate = None
        if candidate in LAB_HORIZON_WEEKS:
            horizon = int(candidate)
            active = True
        else:
            notes.append(
                f"look-ahead {raw['lab_h']!s} is not one of "
                f"{', '.join(f'{weeks}w' for weeks in LAB_HORIZON_WEEKS)}"
            )

    benchmark = LAB_BENCHMARKS[0]
    if raw["lab_b"]:
        candidate_b = str(raw["lab_b"]).strip().upper()
        if candidate_b in LAB_BENCHMARKS:
            benchmark = candidate_b
            active = True
        else:
            notes.append(f"benchmark {raw['lab_b']!s} is not GDX or GDXJ")

    bucket = DEFAULT_DIAL_BUCKET
    if raw["lab_s"]:
        candidate_s = str(raw["lab_s"]).strip()
        if candidate_s in BUCKET_LABELS:
            bucket = candidate_s
            active = True
        else:
            notes.append(f"gold scenario {raw['lab_s']!s} is not a configured bucket")

    note = ""
    if notes:
        note = (
            "Showing the default view because " + "; ".join(notes) + "."
        )
        active = True  # the user asked for the Lab, so keep it open and explain
    return LabRequest(
        horizon=horizon, benchmark=benchmark, bucket=bucket, active=active, note=note
    )


def _first_value(query: Mapping[str, Any] | None, key: str) -> str:
    if not query:
        return ""
    value = query.get(key)
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return "" if value is None else str(value)


# Bounded side-cache for the Lab render (plan §9.4): 40 control combinations must
# not be able to evict the much smaller detail-state cache, and a Lab REBUILD must
# invalidate — hence the artifact pointer stat in the key.
_LAB_CACHE: OrderedDict[tuple, str] = OrderedDict()
_LAB_CACHE_MAX = 32


def clear_lab_render_cache() -> None:
    _LAB_CACHE.clear()


def _lab_config_key(app_config: AppConfig | None) -> tuple:
    if app_config is None:
        return ("default",)
    lab = app_config.ticker_page.lab
    return (int(lab.default_horizon_weeks), int(lab.scatter_from_year))


def _lab_controls(
    *,
    ticker: str,
    request: LabRequest,
    availability: Mapping[str, int],
    query_params: Mapping[str, str] | None,
    default_horizon: int,
) -> str:
    """GET links for look-ahead / benchmark / scenario.

    Every link carries the page's existing query params, sets its own lab_*
    value, and anchors back at the section so the disclosure reopens where the
    user was standing.
    """

    base = f"/ticker/{quote(str(ticker), safe='')}"
    carried = {
        key: value
        for key, value in dict(query_params or {}).items()
        if key not in {"lab_h", "lab_b", "lab_s", "saved"} and value
    }

    def href(**overrides: str) -> str:
        params = dict(carried)
        params.update(
            {
                "lab_h": str(request.horizon),
                "lab_b": request.benchmark,
                "lab_s": request.bucket,
            }
        )
        params.update(overrides)
        query = "&".join(
            f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
            for key, value in sorted(params.items())
        )
        return f"{base}?{query}{LAB_ANCHOR}"

    horizon_links = "".join(
        (
            f"<a class=\"lab-control{' active' if weeks == request.horizon else ''}\" "
            f"href=\"{escape(href(lab_h=str(weeks)), quote=True)}\""
            + (" aria-current=\"true\"" if weeks == request.horizon else "")
            + f">{weeks}w"
            + (" <span class=\"hint\">default</span>" if weeks == default_horizon else "")
            + "</a>"
        )
        for weeks in LAB_HORIZON_WEEKS
    )
    benchmark_links = "".join(
        (
            f"<a class=\"lab-control{' active' if name == request.benchmark else ''}\" "
            f"href=\"{escape(href(lab_b=name), quote=True)}\""
            + (" aria-current=\"true\"" if name == request.benchmark else "")
            + f">{escape(name)}</a>"
        )
        for name in LAB_BENCHMARKS
    )
    scenario_links = "".join(
        (
            f"<a class=\"lab-control{' active' if bucket == request.bucket else ''}\" "
            f"href=\"{escape(href(lab_s=bucket), quote=True)}\""
            + (" aria-current=\"true\"" if bucket == request.bucket else "")
            + f">{escape(label)}"
            + (
                f" <span class=\"hint\">({int(availability.get(bucket, 0))} miners)</span>"
                if availability
                else ""
            )
            + "</a>"
        )
        for bucket, label in BUCKET_LABELS.items()
    )
    return (
        "<div class=\"lab-controls\" role=\"group\" aria-label=\"Lab history controls\">"
        f"<p><strong>Look-ahead:</strong> {horizon_links}</p>"
        f"<p><strong>Benchmark:</strong> {benchmark_links}</p>"
        f"<p><strong>Gold scenario:</strong> {scenario_links}</p>"
        "</div>"
    )


def _build_lab_body(
    paths: ProjectPaths,
    *,
    ticker: str,
    request: LabRequest,
    app_config: AppConfig | None,
) -> tuple[dict[str, int], str]:
    """``(bucket availability, charts html)`` — the expensive, cacheable half.

    The controls are deliberately NOT built here: they carry the page's other
    query params, which would otherwise leak into the cache key and stop the
    Lab cache from ever hitting across a window or chart switch.
    """

    scatter_from_year = (
        int(app_config.ticker_page.lab.scatter_from_year) if app_config is not None else 2016
    )
    cells = load_dial_cells(paths, horizon=request.horizon, bucket=request.bucket)
    availability: dict[str, int] = {}
    if cells.available:
        availability = {
            str(bucket): int(count)
            for bucket, count in (
                cells.bucket_availability.get(str(cells.horizon), {}) or {}
            ).items()
        }
    caveat = (
        "<p class=\"hint\">"
        + escape(SURVIVOR_CAVEAT)
        + help_icon(
            "Survivor-only history",
            key="ticker_survivor_caveat",
            app_config=app_config,
        )
        + "</p>"
    )

    if not cells.available:
        reason, tone, rebuild = lab_unavailable_reason(cells.error_status)
        return availability, notice(tone, f"<p>{escape(reason)}{rebuild}</p>") + caveat

    horizon_note = ""
    if int(cells.horizon) != int(request.horizon):
        # The Lab was built without this look-ahead. Say which one is actually
        # on screen rather than labelling another horizon's numbers.
        horizon_note = notice(
            "warning",
            f"<p>The Lab has no {int(request.horizon)}-week look-ahead built; "
            f"showing {int(cells.horizon)} weeks instead.</p>",
        )

    bucket_label = BUCKET_LABELS.get(request.bucket, request.bucket)
    usable_cells = availability.get(request.bucket)
    if usable_cells is not None and usable_cells <= 0:
        # Counted in the BUILD, read here: the bucket is empty for a reason, and
        # the reason is shown instead of a guessed chart.
        return availability, (
            horizon_note
            + notice(
                "warning",
                f"<p>No countable history for “{escape(bucket_label)}” at "
                f"{int(cells.horizon)} weeks: the build found 0 miners with enough "
                "independent weeks in this scenario, so nothing is drawn.</p>",
            )
            + caveat
        )

    curve = load_ticker_curve(
        paths,
        ticker=ticker,
        scenario_bucket=request.bucket,
        horizon=request.horizon,
        benchmark=request.benchmark,
    )
    if not curve.available:
        reason, tone, rebuild = lab_unavailable_reason(curve.error_status)
        return availability, (
            horizon_note + notice(tone, f"<p>{escape(reason)}{rebuild}</p>") + caveat
        )

    episodes_period = f"Episodes since {scatter_from_year}"
    charts = horizon_note + (
        _render_profile(
            curve,
            uncertainty=True,
            heading_level=4,
            period_label="Beat-rate: full published history · bars are the published 95% interval",
        )
        + _render_distribution(
            curve,
            since_year=scatter_from_year,
            heading_level=4,
            period_label=episodes_period,
        )
        + _render_chart_a(
            curve,
            since_year=scatter_from_year,
            period_label=episodes_period,
        )
    )
    return availability, charts + caveat


def render_lab_history(
    paths: ProjectPaths | None,
    *,
    ticker: str,
    request: LabRequest,
    app_config: AppConfig | None = None,
    query_params: Mapping[str, str] | None = None,
) -> str:
    """The closed "How it behaved in past gold moves" disclosure.

    Server-side SVG only — no episode rows are ever embedded in the page (plan
    §12 rule 1). The rendered body is memoized on (ticker, h, b, s, the Lab
    artifact pointer stat, the live Lab config), so a rebuild invalidates it.
    """

    summary = escape("How it behaved in past gold moves") + help_icon(
        "How it behaved in past gold moves", key="ticker_lab_history", app_config=app_config
    )
    if paths is None:
        return disclosure(
            summary,
            "<p class=\"hint\">Lab history is not available in this view.</p>",
            class_name="lab-history",
        )
    key = (
        str(ticker).upper(),
        int(request.horizon),
        request.benchmark,
        request.bucket,
        lab_artifact_pointer(paths),
        _lab_config_key(app_config),
    )
    cached = _LAB_CACHE.get(key)
    if cached is not None:
        _LAB_CACHE.move_to_end(key)
        availability, body = cached
    else:
        availability, body = _build_lab_body(
            paths, ticker=ticker, request=request, app_config=app_config
        )
        _LAB_CACHE[key] = (availability, body)
        while len(_LAB_CACHE) > _LAB_CACHE_MAX:
            _LAB_CACHE.popitem(last=False)
    controls = _lab_controls(
        ticker=ticker,
        request=request,
        availability=availability,
        query_params=query_params,
        default_horizon=(
            int(app_config.ticker_page.lab.default_horizon_weeks)
            if app_config is not None
            else 8
        ),
    )
    note = (
        f"<p class=\"hint lab-note\">{escape(request.note)}</p>" if request.note else ""
    )
    return disclosure(
        summary,
        note + controls + body,
        expanded=request.active,
        class_name="lab-history",
    )


# ---------------------------------------------------------------------------
# Full research detail
# ---------------------------------------------------------------------------


def _kind_notice(state: tuple[str, str], *, kind_label: str) -> str:
    status, reason = state
    if status == "OK":
        return ""
    return (
        f"<p class=\"hint\">The published {escape(kind_label)} series is "
        f"{escape(status)}: {escape(reason)}</p>"
    )


def _window_status(tool_a_row: Mapping[str, Any], window: str) -> str:
    """Extract the ELIGIBLE / INELIGIBLE_* status for a window (persisted)."""

    raw = tool_a_row.get(f"window_status_{window.lower()}")
    if raw is None:
        return "UNKNOWN"
    try:
        if pd.isna(raw):
            return "UNKNOWN"
    except TypeError:
        pass
    return str(raw).strip().upper() or "UNKNOWN"


def _window_fit_row(rows: pd.DataFrame, window: str) -> dict[str, Any]:
    if rows is None or rows.empty or "window" not in rows.columns:
        return {}
    match = rows.loc[rows["window"].astype(str).str.upper().eq(str(window).upper())]
    if match.empty:
        return {}
    return match.iloc[0].to_dict()


def render_structural_window_table(
    window_fit_rows: pd.DataFrame,
    *,
    active_window: str,
    canonical_anchor: str,
    app_config: AppConfig | None = None,
) -> str:
    """Published per-window fits: beta, R², weeks, status.

    Reads the ``window_fit`` kind of the research-series artifact — the same rows
    the up/down bars use, so the chart and the table can never disagree. Score
    columns are gone with the score (requirements §3).
    """

    rows: list[str] = []
    for window_id in _STRUCTURAL_WINDOWS:
        fit = _window_fit_row(window_fit_rows, window_id)
        markers = []
        if window_id == str(canonical_anchor).upper():
            markers.append("Anchor")
        if window_id == active_window:
            markers.append("Active")
        if window_id not in SCORING_WINDOWS:
            markers.append("display-only")
        marker_text = f" ({', '.join(markers)})" if markers else ""
        row_class = " class=\"active-row\"" if window_id == active_window else ""
        rows.append(
            f"<tr{row_class}>"
            f"<td>{escape(WINDOW_LABELS.get(window_id, window_id))}{marker_text}</td>"
            f"<td>{_fmt_number(fit.get('up_beta'), decimals=2)}</td>"
            f"<td>{_fmt_number(fit.get('down_beta'), decimals=2)}</td>"
            f"<td>{_fmt_percent(fit.get('r_squared'), decimals=1)}</td>"
            f"<td>{_fmt_number(fit.get('weeks'), decimals=0)}</td>"
            f"<td>{_fmt_text(fit.get('window_status'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        "<h4>Fitted betas by window"
        + help_icon(
            "Fitted betas by window",
            key="ticker_fitted_betas_panel",
            app_config=app_config,
        )
        + "</h4>"
        "<p class=\"hint\">Published fits for every selectable lookback: 6M / 1Y / 3Y are the "
        "scoring windows used elsewhere in the product; 2Y / 5Y are display-only longer "
        "lookbacks.</p>"
        + table_region(
            "<table><thead><tr>"
            + help_th("Window", key="tool_a_structural_window", app_config=app_config)
            + help_th("Up beta", key="tool_c_up_beta", app_config=app_config)
            + help_th("Down beta", key="tool_c_down_beta", app_config=app_config)
            + help_th("R^2", key="tool_a_r_squared", app_config=app_config)
            + help_th("Weeks", key="tool_a_window_weeks", app_config=app_config)
            + help_th("Status", key="tool_a_window_status", app_config=app_config)
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="behaviour-windows-table-region",
            label="Fitted betas by window",
        )
        + "</section>"
    )


def _window_weekly_sample(
    weekly_rows: pd.DataFrame,
    *,
    tool_a_row: Mapping[str, Any] | None,
    active_window: str,
) -> tuple[pd.DataFrame, int | None]:
    """The active window's trailing weekly rows — pure SELECTION, no maths.

    ``N`` is the persisted ``weeks_{window}`` count on the Tool A row: the
    artifact's own statement of how many weeks its fit for that window used, so
    the dots on the chart are the sample the published line was fitted to.
    Serve re-derives no window boundary and drops no observation of its own.

    Returns ``(rows, weeks)``. ``weeks is None`` means no usable count is
    published — the full series is drawn and the caption says exactly that.
    """

    if weekly_rows is None or weekly_rows.empty or not active_window:
        return weekly_rows, None
    source = tool_a_row if tool_a_row is not None else {}
    weeks = _optional_float(source.get(f"weeks_{str(active_window).lower()}"))
    if weeks is None or weeks <= 0 or "date" not in weekly_rows.columns:
        return weekly_rows, None
    ordered = weekly_rows.sort_values("date")
    return ordered.tail(int(weeks)), int(weeks)


def _published_window_fit(
    structural_window_metrics: pd.DataFrame | None, window: str
) -> tuple[float | None, float | None]:
    """``(slope, intercept)`` as PUBLISHED for one window, else ``(None, None)``.

    Both coefficients come from the published ``structural_window_metrics``
    history — the only artifact carrying a per-window intercept (the Tool A row
    publishes ``structural_delta_{window}`` but no alpha at any suffix).
    Nothing is fitted, averaged or back-solved here: the newest published row
    for the window wins, and a missing coefficient means no line at all rather
    than a half-drawn one.
    """

    frame = structural_window_metrics
    if frame is None or frame.empty or not window or "window_id" not in frame.columns:
        return None, None
    match = frame.loc[frame["window_id"].astype(str).str.upper().eq(str(window).upper())]
    if match.empty:
        return None, None
    if "as_of_date" in match.columns:
        match = match.sort_values("as_of_date")
    newest = match.iloc[-1]
    return (
        _optional_float(newest.get("structural_delta")),
        _optional_float(newest.get("intercept_alpha")),
    )


def render_weekly_scatter(
    weekly_rows: pd.DataFrame,
    *,
    ticker: str,
    tool_a_row: Mapping[str, Any] | None = None,
    active_window: str = "",
    structural_window_metrics: pd.DataFrame | None = None,
    app_config: AppConfig | None = None,
) -> str:
    """Weekly-return scatter for the ACTIVE window, with its published fit line.

    Two published facts shape it and nothing else: the window's ``weeks_*``
    count selects the trailing sample, and the window's published slope +
    intercept draw the line. Serve fits nothing in the request path — when
    either coefficient is absent the dots are drawn alone and the caption says
    there is no published fit line for the window.
    """

    explain = help_icon(
        "Weekly return scatter", key="ticker_weekly_scatter", app_config=app_config
    )
    if weekly_rows is None or weekly_rows.empty:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h4>Weekly return scatter{explain}</h4>"
            "<p class=\"hint\">No weekly research series is published for this ticker.</p>"
            "</section>"
        )
    sample, weeks = _window_weekly_sample(
        weekly_rows, tool_a_row=tool_a_row, active_window=active_window
    )
    pairs = [
        (float(row["gold_return"]), float(row["stock_return"]))
        for _, row in sample.iterrows()
        if _is_drawable(row.get("gold_return")) and _is_drawable(row.get("stock_return"))
    ]
    if not pairs:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h4>Weekly return scatter{explain}</h4>"
            "<p class=\"hint\">No drawable weekly observations in the published series.</p>"
            "</section>"
        )
    slope, intercept = _published_window_fit(structural_window_metrics, active_window)
    has_line = slope is not None and intercept is not None
    svg = _build_scatter_svg(
        x_values=[x for x, _ in pairs],
        y_values=[y for _, y in pairs],
        regression_beta=slope if has_line else None,
        regression_alpha=intercept if has_line else None,
    )
    # Guarded to match ``_window_weekly_sample``: a series with no ``date`` is
    # neither trimmed to the window nor given a period suffix, but it still draws.
    dates = (
        pd.to_datetime(sample["date"], errors="coerce").dropna()
        if "date" in sample.columns
        else pd.Series(dtype="datetime64[ns]")
    )
    period = (
        f" · {_fmt_date(dates.min())} to {_fmt_date(dates.max())}" if not dates.empty else ""
    )
    win_label = WINDOW_LABELS.get(active_window, active_window) if active_window else ""
    sample_clause = (
        f" Trailing {weeks} weeks — the published sample size for the {win_label} window."
        if weeks is not None
        else " The full published series: no weeks count is published for this window."
    )
    line_clause = (
        f" The line is the published {win_label} fit (slope "
        f"{_fmt_number(slope, decimals=2)}, intercept {_fmt_number(intercept, decimals=4)}); "
        "nothing is fitted in the page."
        if has_line
        else " No published fit line for this window."
    )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h4>Weekly return scatter{explain}</h4>"
        f"<p class=\"hint\">Each dot is one published week: x = gold's weekly return, "
        f"y = {escape(ticker)}'s. Top-right = both rose, bottom-left = both fell. "
        f"{len(pairs)} weekly observations{escape(period)}."
        f"{escape(sample_clause)}{escape(line_clause)}</p>"
        f"{svg}"
        "</section>"
    )


def _is_drawable(value: Any) -> bool:
    """A value that can be placed on an axis: present, numeric, finite."""

    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    # NaN and infinities are equally unplottable; both are excluded without any
    # arithmetic on the value itself.
    return number == number and number not in (float("inf"), float("-inf"))


def render_volatility_panel(
    tool_a_row: Mapping[str, Any],
    *,
    active_window: str,
    app_config: AppConfig | None = None,
) -> str:
    """Published volatility diagnostics only — never a request-path estimate.

    The pipeline publishes volatility for ONE canonical window per ticker. For
    any other window this says so instead of estimating (the old serve-side
    least-squares recompute is deleted, plan P2).
    """

    win_label = WINDOW_LABELS.get(active_window, active_window)
    explain = help_icon(
        "Volatility diagnostics", key="ticker_volatility_diagnostics", app_config=app_config
    )
    window_status = _window_status(tool_a_row, active_window)
    if window_status != "ELIGIBLE":
        return (
            "<section class=\"panel nested-panel\">"
            f"<h4>Volatility diagnostics ({escape(win_label)}){explain}</h4>"
            f"<p class=\"hint\">The {escape(win_label)} window is not eligible for this ticker "
            f"(status: {escape(window_status)}). Volatility is not shown.</p>"
            "</section>"
        )
    anchor_raw = tool_a_row.get("volatility_anchor_window_id")
    anchor = "" if anchor_raw is None else str(anchor_raw).strip().upper()
    if anchor != str(active_window).upper():
        anchor_label = WINDOW_LABELS.get(anchor, anchor) if anchor else "n/a"
        return (
            "<section class=\"panel nested-panel\">"
            f"<h4>Volatility diagnostics ({escape(win_label)}){explain}</h4>"
            f"<p class=\"hint\">{escape(VOLATILITY_CANONICAL_NOTE)} For this ticker that window "
            f"is {escape(str(anchor_label))} — switch the beta window above to see them.</p>"
            "</section>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h4>Volatility diagnostics ({escape(win_label)}){explain}</h4>"
        "<p class=\"hint\">Published 52-week values for the canonical window.</p>"
        "<div class=\"metric-grid\">"
        + _metric_card(
            "Total volatility (annualized log vol)",
            _fmt_percent(tool_a_row.get("total_volatility_52w"), decimals=1),
            help_key="tool_a_volatility",
            app_config=app_config,
        )
        + _metric_card(
            "Residual volatility (annualized log vol)",
            _fmt_percent(tool_a_row.get("residual_volatility_52w"), decimals=1),
            help_key="tool_a_residual_volatility",
            app_config=app_config,
        )
        + _metric_card(
            "Downside volatility (annualized log vol)",
            _fmt_percent(tool_a_row.get("downside_volatility_52w"), decimals=1),
            help_key="tool_a_downside_volatility",
            app_config=app_config,
        )
        + _metric_card(
            "Volatility context",
            _fmt_text(tool_a_row.get("volatility_context")),
            help_key="tool_a_volatility_context",
            app_config=app_config,
        )
        + "</div></section>"
    )


def render_horizon_ladder(
    horizon_rows: pd.DataFrame,
    *,
    app_config: AppConfig | None = None,
) -> str:
    """The exploratory horizon ladder, read 1:1 from the research series."""

    explain = help_icon(
        "Exploratory horizon ladder", key="exploratory_horizon", app_config=app_config
    )
    if horizon_rows is None or horizon_rows.empty:
        return (
            "<section class=\"panel nested-panel\">"
            f"<h4>Exploratory horizon ladder{explain}</h4>"
            "<p class=\"hint\">No exploratory horizon rows are published for this ticker.</p>"
            "</section>"
        )
    rows: list[str] = []
    for _, row in horizon_rows.iterrows():
        coverage = str(row.get("horizon_coverage_flag") or "")
        reason = str(row.get("horizon_coverage_reason") or "")
        status_cell = escape(coverage) if coverage else "-"
        if reason:
            status_cell += f" <span class=\"hint\">{escape(reason)}</span>"
        rows.append(
            "<tr>"
            f"<td>{escape(window_label(str(row.get('horizon_label') or '')))}</td>"
            f"<td>{_fmt_percent(row.get('horizon_return'), decimals=1)}</td>"
            f"<td>{_fmt_percent(row.get('horizon_gold_return'), decimals=1)}</td>"
            f"<td>{_fmt_number(row.get('horizon_gold_delta'), decimals=2)}</td>"
            f"<td>{status_cell}</td>"
            f"<td>{_fmt_date(row.get('horizon_start_date'))} to "
            f"{_fmt_date(row.get('horizon_end_date'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"panel nested-panel\">"
        f"<h4>Exploratory horizon ladder{explain}</h4>"
        "<p class=\"hint\">The older horizon-return lens, kept for tactical context. The ratio "
        "is a single-period return ratio, not a structural beta.</p>"
        + table_region(
            "<table><thead><tr>"
            + help_th("Horizon", key="exploratory_horizon", app_config=app_config)
            + help_th("Equity return", key="exploratory_equity_return", app_config=app_config)
            + help_th("Gold return", key="exploratory_gold_return", app_config=app_config)
            + help_th(
                "Single-period ratio",
                key="exploratory_single_period_ratio",
                app_config=app_config,
            )
            + help_th(
                "Status", key="exploratory_coverage_status", app_config=app_config
            )
            + help_th("Window", key="tool_a_structural_window", app_config=app_config)
            + "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="behaviour-horizon-ladder-region",
            label="Exploratory horizon ladder",
        )
        + "</section>"
    )


_MEASURED_EXPLANATION_TITLES = ("Delta", "Gamma", "Asymmetry", "Volatility")


def _build_measured_beta_explanations(
    *,
    tool_a_row: Mapping[str, Any],
    active_window: str,
    scoring_config: Any,
) -> list[tuple[str, str]]:
    """Narrative cards for the MEASURED betas only.

    The Confidence, Interaction and Summary cards went with the score prose
    (plan §9.2): they described a compiled verdict this page no longer shows.
    Volatility reads the published 52-week fields — there is no live estimate to
    describe any more.
    """

    from golden_vector.model.explanations import (
        build_asymmetry_explanation,
        build_delta_explanation,
        build_gamma_explanation,
        build_volatility_explanation,
    )

    win = active_window.lower()
    anchor_delta = _optional_float(tool_a_row.get(f"structural_delta_{win}"))
    anchor_gamma = _optional_float(tool_a_row.get(f"gamma_{win}"))
    anchor_up_beta = _optional_float(tool_a_row.get(f"up_beta_{win}"))
    anchor_down_beta = _optional_float(tool_a_row.get(f"down_beta_{win}"))
    anchor_asym = _optional_float(tool_a_row.get(f"asymmetry_ratio_{win}"))
    structural_delta_core = _optional_float(tool_a_row.get("structural_delta_core"))
    # Eligibility is a DATA status (it gates whether the measured read is
    # trustworthy), so the builders still receive it; none of the four surviving
    # cards renders a score or a confidence label.
    reason = str(tool_a_row.get("score_eligibility_reason") or "").strip()
    eligible = reason == ""

    return [
        (
            "Delta",
            build_delta_explanation(
                anchor_delta=anchor_delta,
                anchor_window_id=active_window,
                structural_delta_core=structural_delta_core,
                score_eligible=eligible,
                score_eligibility_reason=reason,
                scoring_config=scoring_config,
            ),
        ),
        (
            "Gamma",
            build_gamma_explanation(
                gamma_core=anchor_gamma,
                up_beta_anchor=anchor_up_beta,
                down_beta_anchor=anchor_down_beta,
                anchor_window_id=active_window,
                score_eligible=eligible,
                score_eligibility_reason=reason,
                scoring_config=scoring_config,
            ),
        ),
        (
            "Asymmetry",
            build_asymmetry_explanation(
                asymmetry_ratio_anchor=anchor_asym,
                up_beta_anchor=anchor_up_beta,
                down_beta_anchor=anchor_down_beta,
                score_eligibility_reason=reason,
                scoring_config=scoring_config,
            ),
        ),
        (
            "Volatility",
            build_volatility_explanation(
                volatility_context=str(tool_a_row.get("volatility_context") or "").strip().upper(),
                residual_volatility_52w=tool_a_row.get("residual_volatility_52w"),
                downside_volatility_52w=tool_a_row.get("downside_volatility_52w"),
            ),
        ),
    ]


def _render_explanation_grid(cards: list[tuple[str, str]]) -> str:
    """Render (title, text) narrative cards as one explanation grid.

    Text comes from ``golden_vector/model/explanations.py`` so narrative
    semantics have ONE source of truth across the pipeline and the workspace.
    """

    if not cards:
        return ""
    return (
        "<div class=\"explanation-grid\">"
        + "".join(
            "<article class=\"panel explanation-card\">"
            f"<h4>{escape(title)}</h4><p>{_fmt_text(text)}</p>"
            "</article>"
            for title, text in cards
        )
        + "</div>"
    )


def _render_research_detail(
    *,
    ticker: str,
    tool_a_row: Mapping[str, Any],
    data: TickerPageData | None,
    active_window: str,
    canonical_anchor: str,
    structural_window_metrics: pd.DataFrame | None = None,
    app_config: AppConfig | None,
) -> str:
    """The closed "Full research detail" disclosure (plan §9.2, exhaustively)."""

    win = active_window.lower()
    win_label = WINDOW_LABELS.get(active_window, active_window)
    scoring_config = app_config.scoring if app_config is not None else None
    weekly_state = ("MISSING", "no ticker-page artifacts loaded")
    horizon_state = weekly_state
    window_state = weekly_state
    weekly_rows = pd.DataFrame()
    horizon_rows = pd.DataFrame()
    window_rows = pd.DataFrame()
    if data is not None:
        weekly_state = data.research_kind_state(ticker, kind="weekly")
        horizon_state = data.research_kind_state(ticker, kind="horizon")
        window_state = data.research_kind_state(ticker, kind="window_fit")
        weekly_rows = data.research_rows(ticker, kind="weekly")
        horizon_rows = data.research_rows(ticker, kind="horizon")
        window_rows = data.research_rows(ticker, kind="window_fit")

    active_grid = (
        f"<h4>Active window: {escape(win_label)}</h4>"
        "<div class=\"metric-grid\">"
        + _metric_card("As of", _fmt_text(tool_a_row.get("as_of_date")))
        + _metric_card(
            f"Gold beta ({win_label})",
            _fmt_number(tool_a_row.get(f"structural_delta_{win}"), decimals=2),
            help_key="tool_a_delta",
            app_config=app_config,
        )
        + _metric_card(
            f"Down-minus-up beta ({win_label})",
            _fmt_number(tool_a_row.get(f"gamma_{win}"), decimals=2),
            help_key="tool_a_gamma",
            app_config=app_config,
        )
        + _metric_card(
            f"Asymmetry ({win_label})",
            _fmt_number(tool_a_row.get(f"asymmetry_ratio_{win}"), decimals=2),
            help_key="tool_a_asymmetry",
            app_config=app_config,
        )
        + _metric_card(
            f"R² ({win_label})",
            _fmt_percent(tool_a_row.get(f"r_squared_{win}"), decimals=1),
            help_key="tool_a_r_squared",
            app_config=app_config,
        )
        + _metric_card(
            f"Weeks ({win_label})",
            _fmt_number(tool_a_row.get(f"weeks_{win}"), decimals=0),
            help_key="tool_a_window_weeks",
            app_config=app_config,
        )
        + "</div>"
        f"<p class=\"hint\">These read-outs describe the active beta window ({escape(win_label)}) "
        "and follow the switcher at the top of this section.</p>"
    )
    cross_window_grid = (
        f"<h4>Across the scoring windows ({' / '.join(WINDOW_LABELS[w] for w in SCORING_WINDOWS)})</h4>"
        "<p class=\"hint\">Blends of the measured betas across the scoring windows — the same "
        "cross-window values the Candidate Finder and Portfolio tools show. They do not change "
        "with the beta-window switcher.</p>"
        "<div class=\"metric-grid\">"
        + _metric_card(
            "Gold beta (cross-window)",
            _fmt_number(tool_a_row.get("structural_delta_core"), decimals=2),
            help_key="tool_a_delta_blend",
            app_config=app_config,
        )
        + _metric_card(
            "Up beta (cross-window)",
            _fmt_number(tool_a_row.get("up_beta_core"), decimals=2),
            help_key="tool_c_up_beta_blend",
            app_config=app_config,
        )
        + _metric_card(
            "Down beta (cross-window)",
            _fmt_number(tool_a_row.get("down_beta_core"), decimals=2),
            help_key="tool_c_down_beta_blend",
            app_config=app_config,
        )
        + _metric_card(
            "Down-minus-up beta (cross-window)",
            _fmt_number(tool_a_row.get("structural_gamma_core"), decimals=2),
            help_key="tool_a_gamma",
            app_config=app_config,
        )
        + _metric_card(
            "Asymmetry (cross-window)",
            _fmt_number(tool_a_row.get("asymmetry_ratio_core"), decimals=2),
            help_key="tool_a_asymmetry",
            app_config=app_config,
        )
        + "</div>"
    )
    body = (
        active_grid
        + _render_explanation_grid(
            _build_measured_beta_explanations(
                tool_a_row=tool_a_row,
                active_window=active_window,
                scoring_config=scoring_config,
            )
        )
        + cross_window_grid
        + _kind_notice(window_state, kind_label="per-window fit")
        + render_structural_window_table(
            window_rows,
            active_window=active_window,
            canonical_anchor=canonical_anchor,
            app_config=app_config,
        )
        + _kind_notice(weekly_state, kind_label="weekly return")
        + render_weekly_scatter(
            weekly_rows,
            ticker=ticker,
            tool_a_row=tool_a_row,
            active_window=active_window,
            structural_window_metrics=structural_window_metrics,
            app_config=app_config,
        )
        + render_volatility_panel(
            tool_a_row, active_window=active_window, app_config=app_config
        )
        + _kind_notice(horizon_state, kind_label="horizon ladder")
        + render_horizon_ladder(horizon_rows, app_config=app_config)
    )
    summary = escape("Full research detail") + help_icon(
        "Full research detail", key="ticker_research_detail", app_config=app_config
    )
    return disclosure(summary, body, class_name="research-detail")


# ---------------------------------------------------------------------------
# section
# ---------------------------------------------------------------------------


def render_market_behaviour_section(
    *,
    ticker: str,
    tool_a_row: Mapping[str, Any],
    tool_a_detail: Any,
    alignment: str,
    active_window: str = "12M",
    canonical_anchor: str = "12M",
    data: TickerPageData | None = None,
    finance_source: str = "our",
    app_config: AppConfig | None = None,
    paths: ProjectPaths | None = None,
    lab_request: LabRequest | None = None,
    query_params: Mapping[str, str] | None = None,
    option_lens_active: bool = False,
    sizing_request: object | None = None,
) -> str:
    """The ``#market-behaviour`` section (requirements §2 position 3)."""

    explain = help_icon(
        "Market behaviour", key="ticker_behaviour_section", app_config=app_config
    )
    switcher = render_window_switcher(
        ticker=ticker,
        active=active_window,
        canonical=canonical_anchor,
        lens="option-trading" if option_lens_active else None,
        anchor="option-trading" if option_lens_active else None,
        sizing_request=sizing_request,
        financials_source=finance_source,
        app_config=app_config,
    )
    pieces: list[str] = [
        f'<section class="panel" id="{SECTION_ID}">',
        section_heading("Market behaviour", help_html=explain, actions_html=switcher),
    ]
    if not tool_a_row:
        message = "No published gold/share behaviour row is available yet."
        foundation_error = getattr(tool_a_detail, "foundation_error", "")
        if foundation_error:
            message += f" {foundation_error}"
        pieces.append(f"<p class=\"hint\">{escape(message)}</p>")
        pieces.append("</section>")
        return "".join(pieces)

    pieces.append(
        "<p class=\"hint\">How this share has actually moved with gold: betas measured on "
        "weekly returns, its counted record against the gold-miner ETFs, and the history "
        "behind the disclosures below.</p>"
    )
    pieces.append(_render_normalization_notice(tool_a_row))
    pieces.append(_render_alignment_notice(alignment))
    pieces.append(
        _render_metrics_load_notice(
            tool_a_detail.structural_metrics_load, tool_a_row=tool_a_row
        )
    )

    # -- open: beta bars + percentile rugs ------------------------------------
    # The bars read the PUBLISHED per-window fit. When that kind is degraded the
    # reason is shown here, beside the open chart — not only inside the closed
    # research disclosure, where nobody would look for it.
    window_fit_rows = pd.DataFrame()
    if data is not None:
        window_fit_rows = data.research_rows(ticker, kind="window_fit")
        pieces.append(
            _kind_notice(
                data.research_kind_state(ticker, kind="window_fit"),
                kind_label="per-window fit",
            )
        )
    anchor_metric = _window_fit_row(window_fit_rows, active_window)
    comparison = tool_a_detail.benchmark_comparison_by_window.get(active_window)
    if alignment != DETAIL_ALIGNMENT_ALIGNED:
        reason = _SUPPRESSION_REASONS.get(
            alignment, _SUPPRESSION_REASONS[DETAIL_ALIGNMENT_FOUNDATION_AHEAD]
        )
        command = _SUPPRESSION_COMMANDS.get(alignment, "python main.py tool-a")
        pieces.append(
            "<div class=\"two-up\">"
            + _render_suppressed_panel("Up vs Down Beta", reason, command)
            + _render_suppressed_panel(
                "Where its gold beta ranks vs the miner universe", reason, command
            )
            + "</div>"
        )
    else:
        pieces.append(
            "<div class=\"two-up\">"
            + render_up_down_beta_panel(
                anchor_metric=anchor_metric,
                active_window=active_window,
                comparison=comparison,
                app_config=app_config,
            )
            + render_beta_comparison_panel(
                comparison,
                ticker=ticker,
                active_window=active_window,
                app_config=app_config,
            )
            + "</div>"
        )

    # -- open: Tool C relative record + cost/downside card --------------------
    pieces.append(
        render_relative_record(
            data, ticker=ticker, finance_source=finance_source, app_config=app_config
        )
    )
    if data is not None:
        pieces.append(
            render_cost_downside_card(
                ticker=ticker,
                aisc_row=data.metric_row(
                    ticker, metric_key="aisc", finance_source=finance_source
                ),
                downside_row=data.metric_row(
                    ticker, metric_key="downside_hit_rate", finance_source=finance_source
                ),
                aisc_peers=data.metric_peers(
                    metric_key="aisc", finance_source=finance_source
                ),
                downside_peers=data.metric_peers(
                    metric_key="downside_hit_rate", finance_source=finance_source
                ),
            )
        )

    # -- closed: the Lab, then the raw research -------------------------------
    pieces.append(
        render_lab_history(
            paths,
            ticker=ticker,
            request=lab_request or parse_lab_request(None, app_config=app_config),
            app_config=app_config,
            query_params=query_params,
        )
    )
    pieces.append(
        _render_research_detail(
            ticker=ticker,
            tool_a_row=tool_a_row,
            data=data,
            active_window=active_window,
            canonical_anchor=canonical_anchor,
            structural_window_metrics=getattr(
                tool_a_detail, "structural_window_metrics", None
            ),
            app_config=app_config,
        )
    )
    pieces.append("</section>")
    return "".join(pieces)
