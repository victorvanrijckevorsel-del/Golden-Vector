"""Distribution strips for the ticker page's percentile metrics (plan D3/D4).

Render-only, and arithmetic-free: every position is the persisted ``strip_pos``
and every axis end is the persisted ``universe_min`` / ``universe_max``. Serve
maps fraction to pixel (inside ``build_distribution_strip_svg``) and formats
numbers; it never derives one.

The eligibility rule is the artifact's, obeyed by name: a tick exists only for a
row that is BOTH ``metric_available`` and ``rank_eligible`` and carries a
``strip_pos`` — a degraded miner is off the rug entirely, not drawn faintly.
The domain is carried on every row of a metric, so a subject with no usable
value still gets the cohort's strip, just without its own marker.

Both callers (Compare's 19 metric rows, Corporate's handful of table rows) go
through ``build_metric_strips``, which does ONE frame scan per section render
regardless of how many metrics it is asked for.
"""

from __future__ import annotations

from typing import Any, Sequence

from golden_vector.common.numeric import bool_or_false, is_missing, optional_finite_float
from golden_vector.common.strings import ordinal_percentile
from golden_vector.contracts.config_models import ScoreMetricSpec
from golden_vector.serve.charts import build_distribution_strip_svg
from golden_vector.serve.format_helpers import format_metric, id_token
from golden_vector.serve.ticker_page.data import TickerPageData

#: Catalog unit token -> the shared ``format_metric`` unit. The catalog speaks the
#: score-builder's vocabulary (contracts.TICKER_PAGE_METRIC_UNITS) and the page's
#: one formatter speaks the gold-dial vocabulary; only "percent" differs by name.
#: A unit with no entry falls through to ``format_metric``'s own default rather
#: than growing a second formatter table here.
_UNIT_FORMATS: dict[str, str] = {"percent": "pct"}


def _text(value: object) -> str:
    if is_missing(value):
        return ""
    return str(value).strip()


def _value_text(value: object, unit: str) -> str:
    """One persisted raw value in the metric's own units (display only)."""

    return format_metric(
        optional_finite_float(value), _UNIT_FORMATS.get(str(unit), str(unit))
    )


def _subject_label(ticker: str, value_text: str, percentile: float | None) -> str:
    """The one labelled marker: "TICKER value · Nth percentile".

    Same shape as the behaviour section's beta strip, with the ordinal rule read
    from its one home in ``common.strings``. A row with no percentile is labelled
    with its value alone — never with a guessed standing.
    """

    if percentile is None:
        return f"{ticker} {value_text}"
    return f"{ticker} {value_text} · {ordinal_percentile(percentile)}"


def build_metric_strips(
    data: TickerPageData,
    *,
    ticker: str,
    finance_source: str,
    metrics: Sequence[ScoreMetricSpec],
    section: str,
    compact: bool = True,
) -> dict[str, str]:
    """metric_key -> strip SVG, for every requested metric that HAS a strip.

    A metric is absent from the result (the caller renders nothing extra) when
    the cohort has no drawable domain — fewer than two eligible values or no
    spread leaves ``universe_min``/``universe_max`` null, and an axis invented
    over a single point would be a lie about the universe.

    Every strip carries its own collapsed "Chart data (table)" disclosure
    (GV-RD-FINAL-002): the rug ticks are pointer-only — ``rug-tooltip.js`` even
    strips their ``<title>`` nodes — so the peer ticker+value pairs must also
    exist as plain text. ``section`` namespaces the element ids because the same
    metric key (``ev_ebitda`` and friends) is drawn in BOTH the Compare and
    Corporate sections and duplicate ids are invalid HTML.
    """

    frame = data.percentiles.frame
    if frame is None or frame.empty:
        return {}
    if not {"ticker", "finance_source", "metric_key"}.issubset(frame.columns):
        return {}
    wanted = {str(spec.key): spec for spec in metrics}
    if not wanted:
        return {}
    subject = _text(ticker).upper()

    marks: dict[str, list[tuple[str, str, float]]] = {}
    domains: dict[str, tuple[float, float]] = {}
    subject_rows: dict[str, dict[str, Any]] = {}
    # ONE scan: the section renders many metrics and a per-metric frame filter
    # would repeat this pass once per row.
    for record in frame.loc[frame["finance_source"].eq(finance_source)].to_dict(
        "records"
    ):
        key = _text(record.get("metric_key"))
        spec = wanted.get(key)
        if spec is None:
            continue
        peer = _text(record.get("ticker")).upper()
        if not peer:
            continue
        if peer == subject and key not in subject_rows:
            subject_rows[key] = record
        if key not in domains:
            low = optional_finite_float(record.get("universe_min"))
            high = optional_finite_float(record.get("universe_max"))
            if low is not None and high is not None:
                domains[key] = (low, high)
        if not (
            bool_or_false(record.get("metric_available"))
            and bool_or_false(record.get("rank_eligible"))
        ):
            continue
        position = optional_finite_float(record.get("strip_pos"))
        if position is None:
            continue
        marks.setdefault(key, []).append(
            (peer, _value_text(record.get("raw_value"), spec.unit), position)
        )

    strips: dict[str, str] = {}
    for key, spec in wanted.items():
        domain = domains.get(key)
        if domain is None:
            continue
        row = subject_rows.get(key)
        subject_pos = (
            optional_finite_float(row.get("strip_pos")) if row is not None else None
        )
        subject_label = ""
        if row is not None and subject_pos is not None:
            percentile = optional_finite_float(
                row.get("pct_high_good" if spec.default_high_good else "pct_low_good")
            )
            subject_label = _subject_label(
                subject, _value_text(row.get("raw_value"), spec.unit), percentile
            )
        low, high = domain
        strips[key] = build_distribution_strip_svg(
            # No drawn axis text: the metric is already named by the row this
            # strip sits in. The SVG's aria name falls back to the subject label.
            axis_label="",
            domain_labels=(
                _value_text(low, spec.unit),
                _value_text(high, spec.unit),
            ),
            marks=sorted(marks.get(key, [])),
            subject_pos=subject_pos,
            subject_label=subject_label,
            # Names the strip for assistive tech when there is no subject marker
            # to name it (the builder's aria fallback chain).
            value_column_label=str(spec.label),
            # Unique + stable per rendered strip: section, metric, subject, source.
            data_table_id=(
                f"chart-data-strip-{id_token(section)}-{id_token(key)}"
                f"-{id_token(subject)}-{id_token(finance_source)}"
            ),
            compact=compact,
        )
    return strips
