"""Compare on your own terms — the opt-in score builder (ticker-page M3e).

Render-only, and stricter than that: **this module performs no arithmetic at
all.** Every number it hands to the browser is one persisted percentiles column
read 1:1; the ONE combine rule (a weighted average of backend percentiles) lives
once, in the frozen, parity-locked ``static/score-builder.js`` — the sanctioned
client-side exception (plan §3.1, requirements D-2). Nothing here ranks,
coalesces, or decides eligibility: ``rank_eligible`` / ``metric_available`` are
persisted verdicts and are obeyed, never recomputed.

What this file actually does:

payload
    Selects the catalog (config order), joins each entry with the subject's
    percentiles row for ``(metric_key, finance_source)``, and lists one peer per
    ticker present in the artifact for that source (ticker ascending). A peer's
    cell exists only when its row is BOTH ``metric_available`` and
    ``rank_eligible`` — a degraded row is absent, not down-weighted (canon:
    degraded data is excluded, not merely flagged).
markup
    Emits exactly the DOM contract frozen in the header of ``score-builder.js``.
    The controls are open by default (requirements §4) and the result region is
    server-rendered in its opt-in state, so the page is honest and complete with
    JavaScript switched off.

The section is labelled "at spot" (H2): these ranks are computed at spot gold
and the gold dial deliberately does not move them.
"""

from __future__ import annotations

from html import escape
from typing import Any, Sequence
from urllib.parse import quote

from golden_vector.common.numeric import bool_or_false, is_missing, optional_finite_float
from golden_vector.contracts.config_models import AppConfig, ScoreMetricSpec
from golden_vector.serve.column_help import help_icon, help_term
from golden_vector.serve.embed import embed_json_payload
from golden_vector.serve.ticker_page.data import TickerPageData
from golden_vector.serve.ui.components import section_heading
from golden_vector.serve.ui.status import notice
from golden_vector.serve.url_helpers import build_page_url

#: Ids/roles shared by the server (emit) and score-builder.js (read). FROZEN —
#: the JS is parity-locked against ``tests/fixtures/score_builder_parity.json``
#: and cannot be changed to follow a rename here.
SCORE_BUILDER_PAYLOAD_ID = "score-builder-payload"
SCORE_BUILDER_ROOT_ID = "score-builder"
SCORE_BUILDER_RESULT_ID = "score-builder-result"
SCORE_BUILDER_SCRIPT_SRC = "/static/score-builder.js"
#: The comparison definition lives in the URL under this key. It is written and
#: read ONLY by the client module; the server just never strips it.
SCORE_BUILDER_STATE_PARAM = "sb"

COMPARE_SECTION_ID = "compare"
COMPARE_SECTION_TITLE = "Compare on your own terms"

#: Requirements Q24 — nothing is scored until the user builds it.
OPT_IN_PROMPT = "Nothing is scored until you build it — pick a metric to start."

#: H2: the whole section is at spot, and the dial does not reach it.
_DIAL_CLAUSE = "the gold dial does not move these ranks"

#: A catalog metric with no persisted row at all for this ticker/source.
MISSING_ROW_REASON = "not published for this ticker"

#: Requirements Q23 — exactly two categories, in this order.
CATEGORY_LABELS: tuple[tuple[str, str], ...] = (
    ("trading", "Trading behaviour"),
    ("corporate", "Corporate finance"),
)

#: Display-only unit wording. The unit token itself is the config's.
_UNIT_LABELS: dict[str, str] = {
    "ratio": "ratio",
    "percent": "%",
    "usd": "USD",
    "usd_per_oz": "$/oz",
    "years": "years",
    "count": "count",
}

#: Each catalog metric reuses the registry entry that already explains it
#: elsewhere in the product — one wording per concept, never a second copy.
#: ``*_core`` betas are the cross-window blend, so they point at the blend
#: entries rather than the per-window ones.
METRIC_HELP_KEYS: dict[str, str] = {
    "down_beta_core": "tool_c_down_beta_blend",
    "up_beta_core": "tool_c_up_beta_blend",
    "asymmetry_ratio_core": "tool_a_asymmetry",
    "downside_volatility_52w": "tool_a_volatility",
    "rel_strength_vs_gdx": "ticker_rel_strength_vs_gdx",
    "rel_weakness_vs_gdx": "ticker_rel_weakness_vs_gdx",
    "downside_hit_rate": "ticker_downside_hit_rate",
    "upside_hit_rate": "ticker_upside_hit_rate",
    "tail_worst10": "ticker_tail_worst10",
    "tail_best10": "ticker_tail_best10",
    "margin_pct": "ticker_cf_margin_pct",
    "aisc_margin_yield": "ticker_cf_aisc_margin_yield",
    "ev_ebitda": "ticker_cf_ev_ebitda",
    "forward_pe": "ticker_cf_forward_pe",
    "leverage_trailing": "ticker_cf_leverage_trailing",
    "aisc": "tool_b_aisc",
    "reserve_life": "tool_b_reserve_life",
    "survival_distance": "tool_d_survival_distance",
    "fragility": "tool_d_fragility",
}


# ---------------------------------------------------------------------------
# cell readers (thin adapters over the shared scalar primitives)
# ---------------------------------------------------------------------------


def _text(value: object) -> str:
    """One persisted cell as plain text; ``""`` for any missing form."""

    if is_missing(value):
        return ""
    return str(value).strip()


def _flag(value: object) -> bool:
    """One persisted boolean column. A missing verdict is never a ``True``."""

    return bool_or_false(value)


def _normalized(value: object) -> str:
    return _text(value).upper()


# ---------------------------------------------------------------------------
# payload (frozen contract — score-builder.js header)
# ---------------------------------------------------------------------------


def _detail_url(ticker: str, *, finance_source: str) -> str:
    """The peer's ticker page, carrying the page's own source when it is set.

    Uses the shared query builder so this can never drift from the rest of the
    product's ``fundamentals_source=`` links.
    """

    base = f"/ticker/{quote(str(ticker), safe='')}"
    if str(finance_source or "our").strip().lower() == "yahoo":
        return build_page_url(base, {}, set_params={"fundamentals_source": "yahoo"})
    return base


def _subject_rows_by_metric(
    data: TickerPageData, *, ticker: str, finance_source: str
) -> dict[str, dict[str, Any]]:
    """The subject's percentiles rows, indexed by metric key — ONE frame scan.

    Same selection as calling ``metric_row`` per metric (first row wins on a
    duplicate key, matching its ``.iloc[0]``), but the detail page renders 19
    metrics and 19 full-frame scans is 19 times the work for one answer.
    """

    rows = data.percentile_rows(ticker, finance_source=finance_source)
    if rows.empty or "metric_key" not in rows.columns:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for record in rows.to_dict("records"):
        key = _text(record.get("metric_key"))
        if key and key not in index:
            index[key] = record
    return index


def _metric_entry(spec: ScoreMetricSpec, row: Any) -> dict[str, Any]:
    """One catalog entry joined with the subject's persisted row."""

    if row is None:
        return {
            "key": spec.key,
            "label": spec.label,
            "category": spec.category,
            "unit": spec.unit,
            "basis": spec.basis,
            "default_high_good": bool(spec.default_high_good),
            "available": False,
            "reason": MISSING_ROW_REASON,
            "pct_high_good": None,
            "pct_low_good": None,
        }
    available = _flag(row.get("metric_available"))
    reason = _text(row.get("metric_reason"))
    return {
        "key": spec.key,
        "label": spec.label,
        "category": spec.category,
        "unit": spec.unit,
        "basis": spec.basis,
        "default_high_good": bool(spec.default_high_good),
        "available": available,
        "reason": reason or None,
        "pct_high_good": (
            optional_finite_float(row.get("pct_high_good")) if available else None
        ),
        "pct_low_good": (
            optional_finite_float(row.get("pct_low_good")) if available else None
        ),
    }


def _peer_entries(
    data: TickerPageData,
    *,
    catalog: Sequence[ScoreMetricSpec],
    finance_source: str,
) -> list[dict[str, Any]]:
    """Every ticker in the artifact for this source, ticker ascending.

    A cell is emitted only for a row that is available AND rank-eligible; every
    other case is ``null``, which the client reads as "this miner has no usable
    value for that metric" rather than as a bad one.
    """

    frame = data.percentiles.frame
    if frame is None or frame.empty:
        return []
    columns = set(frame.columns)
    if not {"ticker", "finance_source", "metric_key"}.issubset(columns):
        return []
    keys = [spec.key for spec in catalog]
    wanted = set(keys)
    rows = frame.loc[frame["finance_source"].eq(finance_source)]
    cells: dict[str, dict[str, dict[str, float | None]]] = {}
    for record in rows.to_dict("records"):
        ticker = _normalized(record.get("ticker"))
        if not ticker:
            continue
        # A ticker present in the artifact is a peer even when none of its rows
        # are usable — it belongs in the list as explicitly unranked.
        bucket = cells.setdefault(ticker, {})
        metric_key = _text(record.get("metric_key"))
        if metric_key not in wanted:
            continue
        if not (
            _flag(record.get("metric_available")) and _flag(record.get("rank_eligible"))
        ):
            continue
        bucket[metric_key] = {
            "pct_high_good": optional_finite_float(record.get("pct_high_good")),
            "pct_low_good": optional_finite_float(record.get("pct_low_good")),
        }
    return [
        {
            "ticker": ticker,
            "detail_url": _detail_url(ticker, finance_source=finance_source),
            "values": {key: cells[ticker].get(key) for key in keys},
        }
        for ticker in sorted(cells)
    ]


def build_score_builder_payload(
    data: TickerPageData,
    *,
    ticker: str,
    finance_source: str,
    app_config: AppConfig,
) -> dict[str, Any]:
    """The frozen score-builder.js payload, built from persisted columns only."""

    config = app_config.ticker_page.score_builder
    catalog = list(config.metrics)
    subject = _normalized(ticker)
    subject_rows = _subject_rows_by_metric(
        data, ticker=subject, finance_source=finance_source
    )
    metrics = [_metric_entry(spec, subject_rows.get(spec.key)) for spec in catalog]
    return {
        "subject": subject,
        "budget_points": int(config.budget_points),
        "min_eligible_peers": int(config.min_eligible_peers),
        "min_active_metric_coverage": float(config.min_active_metric_coverage),
        "rank_stability_shift_points": int(config.rank_stability_shift_points),
        "rank_stability_alert_positions": int(config.rank_stability_alert_positions),
        "metrics": metrics,
        "peers": _peer_entries(data, catalog=catalog, finance_source=finance_source),
    }


# ---------------------------------------------------------------------------
# markup
# ---------------------------------------------------------------------------


def _as_of_label(
    subject_rows: dict[str, dict[str, Any]], *, catalog: Sequence[ScoreMetricSpec]
) -> str:
    """The H2 sentence: the latest as-of date carried by the subject's rows.

    Selection, not computation: ``max`` picks one persisted ``source_as_of_date``
    string (ISO, so lexicographic order IS date order). No date is derived, and
    when the column carries nothing the clause is simply omitted rather than
    guessed. Only the rows this section renders count — a metric outside the
    catalog cannot date the page.
    """

    published = [
        date
        for date in (
            _text((subject_rows.get(spec.key) or {}).get("source_as_of_date"))
            for spec in catalog
        )
        if date
    ]
    if not published:
        return f"at spot — {_DIAL_CLAUSE}"
    return f"at spot, as of {max(published)} — {_DIAL_CLAUSE}"


def _metric_row_html(
    spec: ScoreMetricSpec,
    entry: dict[str, Any],
    *,
    budget_points: int,
    app_config: AppConfig | None,
) -> str:
    key = str(spec.key)
    key_attr = escape(key, quote=True)
    activate_id = escape(f"sb-activate-{key}", quote=True)
    weight_id = escape(f"sb-weight-{key}", quote=True)
    label = str(spec.label)
    available = bool(entry["available"])
    disabled = "" if available else " disabled"
    high_good = bool(spec.default_high_good)
    direction_text = "Higher is better" if high_good else "Lower is better"
    unit_label = _UNIT_LABELS.get(str(spec.unit), str(spec.unit))
    explain = help_icon(
        label, key=METRIC_HELP_KEYS.get(key), app_config=app_config
    )
    direction_help = help_icon(
        f"Which way is good for {label}",
        key="ticker_compare_direction",
        app_config=app_config,
    )
    reason_html = ""
    if not available:
        reason_html = (
            '<span class="hint sb-unavailable">'
            f"{escape(str(entry['reason'] or 'no reason recorded'))}</span>"
        )
    return (
        f'<li class="sb-metric" data-metric-key="{key_attr}" data-active="false">'
        f'<span class="sb-metric-name"><label for="{activate_id}">{escape(label)}</label>'
        f"{explain}</span>"
        f'<span class="sb-metric-basis">{escape(unit_label)} · {escape(str(spec.basis))}</span>'
        f'<input type="checkbox" id="{activate_id}" data-role="activate"{disabled}>'
        '<button type="button" class="control" data-role="direction" '
        f'aria-pressed="{"true" if high_good else "false"}"{disabled}>'
        f"{escape(direction_text)}</button>{direction_help}"
        f'<input type="range" id="{weight_id}" data-role="weight" min="0" '
        f'max="{int(budget_points)}" step="1" value="0" disabled '
        f'aria-label="Weight for {escape(label, quote=True)}">'
        f'<output class="sb-weight-points" data-role="weight-points" '
        f'for="{weight_id}">0</output>'
        f"{reason_html}"
        "</li>"
    )


def _category_group_html(
    category: str,
    title: str,
    *,
    catalog: Sequence[ScoreMetricSpec],
    entries: dict[str, dict[str, Any]],
    budget_points: int,
    app_config: AppConfig | None,
) -> str:
    rows = "".join(
        _metric_row_html(
            spec,
            entries[spec.key],
            budget_points=budget_points,
            app_config=app_config,
        )
        for spec in catalog
        if str(spec.category) == category
    )
    if not rows:
        return ""
    return (
        f'<fieldset class="sb-group" data-category="{escape(category, quote=True)}">'
        f"<legend>{escape(title)}</legend>"
        f'<ul class="sb-metrics">{rows}</ul>'
        "</fieldset>"
    )


def _result_region_html(*, app_config: AppConfig | None = None) -> str:
    """Server-rendered opt-in state carrying every target the client fills.

    Only the elements the client explicitly ``show()``s are hidden here — the
    score, rank, contributions and ranked list are written by ``setText`` /
    ``appendChild`` and would stay invisible forever if this markup hid them.
    """

    score_help = help_icon(
        "Your score", key="ticker_compare_score", app_config=app_config
    )
    rank_help = help_icon("Your rank", key="ticker_compare_rank", app_config=app_config)
    return (
        f'<div id="{SCORE_BUILDER_RESULT_ID}" class="score-builder-result" '
        'role="group" aria-label="Your comparison">'
        f'<p class="hint" data-role="opt-in">{escape(OPT_IN_PROMPT)}</p>'
        '<p class="hint" data-role="message" hidden></p>'
        '<p class="sb-subject">'
        '<span class="visually-hidden">Your score: </span>'
        f'<span class="sb-score" data-role="subject-score"></span>{score_help}'
        '<span class="visually-hidden">Rank: </span>'
        f'<span class="sb-rank" data-role="subject-rank"></span>{rank_help}'
        "</p>"
        '<p class="hint" data-role="subject-note" hidden></p>'
        '<ul class="sb-contributions" data-role="contributions" '
        'aria-label="What carries the score"></ul>'
        '<ul class="sb-ranked" data-role="ranked-list" '
        'aria-label="Every miner, ranked"></ul>'
        '<p class="hint sb-stability" data-role="stability-warning" hidden></p>'
        '<p class="visually-hidden" data-role="live" role="status" '
        'aria-live="polite"></p>'
        "</div>"
    )


def render_compare_section(
    data: TickerPageData,
    *,
    ticker: str,
    finance_source: str,
    app_config: AppConfig | None = None,
) -> str:
    """The ``#compare`` section (requirements §2 position 5).

    Always renders when it is called: a degraded percentiles artifact produces
    one honest notice with the state's own reason and no payload/script, so the
    nav entry never points at a section that vanished. A cohort smaller than
    ``min_eligible_peers`` is NOT gated here — the client says "not enough
    comparable miners" with the count, which is the truthful message.
    """

    pieces: list[str] = [
        f'<section class="panel" id="{COMPARE_SECTION_ID}">',
        section_heading(
            COMPARE_SECTION_TITLE,
            help_html=help_icon(
                COMPARE_SECTION_TITLE,
                key="ticker_compare_section",
                app_config=app_config,
            ),
        ),
    ]

    if app_config is None:
        pieces.append(
            notice(
                "degraded",
                "<p>The comparison builder needs the ticker-page configuration, and "
                "none is loaded. Nothing is ranked here rather than ranked on "
                "assumptions.</p>",
            )
        )
        pieces.append("</section>")
        return "".join(pieces)

    if data.percentiles.status != "OK":
        pieces.append(
            notice(
                "degraded",
                "<p>Percentiles artifact state <strong>"
                f"{escape(str(data.percentiles.status))}</strong>: "
                f"{escape(data.percentiles.reason or 'no reason recorded')}. "
                "No comparison is offered until the next successful publish — a "
                "partial cohort would rank miners against a universe that is not "
                "there.</p>",
            )
        )
        pieces.append("</section>")
        return "".join(pieces)

    config = app_config.ticker_page.score_builder
    catalog = list(config.metrics)
    payload = build_score_builder_payload(
        data, ticker=ticker, finance_source=finance_source, app_config=app_config
    )
    entries = {str(entry["key"]): entry for entry in payload["metrics"]}

    subject_rows = _subject_rows_by_metric(
        data, ticker=str(payload["subject"]), finance_source=finance_source
    )
    pieces.append(
        '<p class="hint sb-basis">'
        f"{escape(_as_of_label(subject_rows, catalog=catalog))}"
        "</p>"
    )
    pieces.append(
        '<p class="hint sb-legend">'
        + help_term(
            "How the percentiles work",
            key="ticker_compare_percentiles",
            app_config=app_config,
        )
        + " · "
        + help_term(
            "How the weight budget works",
            key="ticker_compare_budget",
            app_config=app_config,
        )
        + " · "
        + help_term(
            "Metrics this company lacks",
            key="ticker_compare_missing",
            app_config=app_config,
        )
        + " · "
        + help_term(
            "What carries the score",
            key="ticker_compare_contributions",
            app_config=app_config,
        )
        + " · "
        + help_term(
            "The ranked list",
            key="ticker_compare_ranked_list",
            app_config=app_config,
        )
        + " · "
        + help_term(
            "When a ranking is fragile",
            key="ticker_compare_stability",
            app_config=app_config,
        )
        + " · "
        + help_term(
            "Which way is good",
            key="ticker_compare_direction",
            app_config=app_config,
        )
        + "</p>"
    )

    groups = "".join(
        _category_group_html(
            category,
            title,
            catalog=catalog,
            entries=entries,
            budget_points=int(config.budget_points),
            app_config=app_config,
        )
        for category, title in CATEGORY_LABELS
    )
    pieces.append(
        f'<div id="{SCORE_BUILDER_ROOT_ID}" class="score-builder">'
        f'<div class="score-builder-controls">{groups}</div>'
        '<p class="sb-actions"><button type="button" class="control" '
        'data-role="reset">Reset weights</button></p>'
        "</div>"
    )
    pieces.append(_result_region_html(app_config=app_config))
    pieces.append(embed_json_payload(SCORE_BUILDER_PAYLOAD_ID, payload))
    pieces.append(f'<script src="{SCORE_BUILDER_SCRIPT_SRC}" defer></script>')
    pieces.append("</section>")
    return "".join(pieces)
