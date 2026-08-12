"""Corporate finance section + gold dial control (ticker-page M3b).

Render-only, hard rule: **this module performs no arithmetic at all.** Every
number it prints is read 1:1 out of a persisted artifact column and passed to a
formatter. The dial's scenario values are produced by ``static/gold-dial.js``
from the persisted line coefficients — the sanctioned client-side exception
(plan §3.1, requirements addendum D-1) — never by this file and never by the
request path.

Two bases exist on this page and are never mixed silently:

``at spot``
    The gold-response artifact's own evaluated spot row
    (``spot_gold_usd`` / ``spot_gold_date`` + the six ``spot_*`` display
    columns). This is TRUE spot, not Tool B's configured $4,000 scenario
    (plan §3.2).
``at your scenario``
    Whatever the dial is set to. Written into ``[data-metric]`` cells by
    gold-dial.js, revealed only once the dial leaves spot (requirements Q43).

The failing-checks notice deliberately does NOT react to the dial (D-4).
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping

import pandas as pd

from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_CONSTANT_COLUMNS,
    GOLD_RESPONSE_LINE_METRICS,
)
from golden_vector.serve.column_help import help_icon
from golden_vector.serve.embed import embed_json_payload
from golden_vector.serve.ticker_page.data import TickerPageData
from golden_vector.serve.ui.components import disclosure, section_heading
from golden_vector.serve.ui.status import notice
from golden_vector.serve.ui.tables import table_region

#: The one payload id shared by the server (embed) and gold-dial.js (read).
GOLD_DIAL_PAYLOAD_ID = "gold-dial-payload"

#: Exact reason the resilience group carries in Yahoo mode (plan §3.2/P6). The
#: persisted Tool D artifact is Our-View; mixing sources would be a lie.
YAHOO_RESILIENCE_REASON = "resilience is computed on Our View inputs"

#: Client-assembled ratio keys. The guards mirror ``screening/layer1.py`` and
#: ``screening/layer2.py`` exactly and are implemented once, in gold-dial.js.
RATIO_METRICS: tuple[str, ...] = (
    "margin_usd_per_oz",
    "margin_pct",
    "aisc_margin_yield",
    "ev_ebitda",
    "forward_pe",
    "leverage_stressed",
)

#: ``spot_*`` display column -> dial metric key. The artifact is the ONLY source
#: of a spot value; this map never computes one.
SPOT_DISPLAY_BY_METRIC: dict[str, str] = {
    "margin_usd_per_oz": "spot_margin_usd_per_oz",
    "margin_pct": "spot_margin_pct",
    "aisc_margin_yield": "spot_aisc_margin_yield",
    "ev_ebitda": "spot_ev_ebitda",
    "forward_pe": "spot_forward_pe",
    "leverage_stressed": "spot_leverage_stressed",
}

#: Display format per metric key — shared with gold-dial.js through the payload
#: so the two formatters can never drift apart silently.
METRIC_FORMATS: dict[str, str] = {
    "forward_revenue_musd": "musd",
    "forward_ebitda_musd": "musd",
    "forward_net_income_musd": "musd",
    "forward_eps": "usd2",
    "aisc_margin_est_musd": "musd",
    "margin_usd_per_oz": "usd_per_oz",
    "margin_pct": "pct",
    "aisc_margin_yield": "pct",
    "ev_ebitda": "ratio",
    "forward_pe": "ratio",
    "leverage_stressed": "ratio",
}

_METRIC_LABELS: dict[str, str] = {
    "forward_revenue_musd": "Revenue",
    "forward_ebitda_musd": "EBITDA (forward)",
    "forward_net_income_musd": "Net income",
    "forward_eps": "Earnings per share",
    "aisc_margin_est_musd": "AISC margin",
    "margin_usd_per_oz": "Cash margin / oz",
    "margin_pct": "Margin %",
    "aisc_margin_yield": "AISC margin yield",
    "ev_ebitda": "EV / EBITDA (forward)",
    "forward_pe": "Forward P/E",
    "leverage_stressed": "Stressed forward leverage",
}

_METRIC_HELP_KEYS: dict[str, str] = {
    "forward_revenue_musd": "ticker_cf_forward_revenue",
    "forward_ebitda_musd": "ticker_cf_forward_ebitda",
    "forward_net_income_musd": "ticker_cf_forward_net_income",
    "forward_eps": "ticker_cf_forward_eps",
    "aisc_margin_est_musd": "ticker_cf_aisc_margin",
    "margin_usd_per_oz": "ticker_cf_margin_usd_per_oz",
    "margin_pct": "ticker_cf_margin_pct",
    "aisc_margin_yield": "ticker_cf_aisc_margin_yield",
    "ev_ebitda": "ticker_cf_ev_ebitda",
    "forward_pe": "ticker_cf_forward_pe",
    "leverage_stressed": "ticker_cf_leverage_stressed",
}

#: The six open headline cards (requirements §4 "open by default").
_HEADLINE_METRICS: tuple[str, ...] = (
    "margin_usd_per_oz",
    "margin_pct",
    "aisc_margin_yield",
    "ev_ebitda",
    "forward_pe",
    "leverage_stressed",
)

#: Persisted FAIL code -> (sentence template, measured Tool B column, measured
#: format, ``config_group.attribute`` threshold path, threshold format).
#: ``{value}`` and ``{threshold}`` are substituted with formatted strings.
#: ONE registry for every failing check, whichever persisted column carried the
#: code — the threshold path names its config group so the two groups
#: (layer-1 screening limits, verdict cut-offs) never need a second table.
_FAIL_SENTENCES: dict[str, tuple[str, str, str, str, str]] = {
    "AISC_FAIL": (
        "AISC {value} is above your {threshold} cap",
        "aisc_usd_per_oz",
        "usd_per_oz",
        "layer1_thresholds.aisc_max",
        "usd_per_oz",
    ),
    "MARGIN_FAIL": (
        "Cash margin {value} is below your {threshold} floor",
        "margin_pct",
        "pct",
        "layer1_thresholds.margin_min",
        "pct",
    ),
    "AISC_MARGIN_YIELD_FAIL": (
        "AISC margin yield {value} is below your {threshold} floor",
        "aisc_margin_yield",
        "pct",
        "layer1_thresholds.aisc_margin_yield_min",
        "pct",
    ),
    "RESERVE_LIFE_FAIL": (
        "Reserve life {value} is below your {threshold} floor",
        "reserve_life_years",
        "years",
        "layer1_thresholds.reserve_life_min",
        "years",
    ),
    "LEVERAGE_FAIL": (
        "Net debt / EBITDA (LTM) {value} is above your {threshold} cap",
        "leverage",
        "ratio",
        "layer1_thresholds.leverage_max",
        "ratio",
    ),
    # From the fundamental-check codes, not layer 1 (see
    # ``_FUNDAMENTAL_ONLY_CODES``). ``forward_pe`` is already materialized for
    # the active finance source before serve sees the row, so this is the same
    # forward P/E the Valuation table and the headline card print.
    "FORWARD_PE_FAIL": (
        "Forward P/E {value} is above your {threshold} cut-off",
        "forward_pe",
        "ratio",
        "verdict_thresholds.strong_candidate_forward_pe_max",
        "ratio",
    ),
}

#: Fundamental-check codes the layer-1 vocabulary does NOT already cover.
#:
#: The fundamental checks re-state most of layer 1 under identical code names
#: (``AISC_FAIL`` … ``LEVERAGE_FAIL``), and ``DATA_COMPLETE_FAIL`` is the same
#: "a required input is missing" concept that layer 1 already reports far more
#: precisely through its ``MISSING_*`` codes. Rendering either group twice
#: would print one failure as two, so only the genuinely NEW check is consumed
#: here. ``tests/test_ticker_page_corporate.py`` locks this against the
#: upstream vocabulary, so a new fundamental check cannot be added and then
#: silently never render.
_FUNDAMENTAL_ONLY_CODES: frozenset[str] = frozenset({"FORWARD_PE_FAIL"})

#: Fundamental-code column for the active finance source. The screening
#: pipeline deliberately leaves the plain column out of the Yahoo column map,
#: so in Yahoo mode it still holds Our-View codes and the ``_official`` column
#: is the only Yahoo-correct source. Either column may be absent entirely on an
#: artifact built before the codes existed — then there is simply no sentence.
_FUNDAMENTAL_CODE_COLUMN_BY_SOURCE: dict[str, str] = {
    "yahoo": "fundamental_check_fail_codes_official",
}
_DEFAULT_FUNDAMENTAL_CODE_COLUMN = "fundamental_check_fail_codes"

#: A ratio whose denominator is not positive is not a number that may be
#: compared to a cut-off. The code still fired, so the check still failed —
#: the line states the condition instead of inventing a multiple.
_NON_POSITIVE_VALUE_SENTENCES: dict[str, str] = {
    "FORWARD_PE_FAIL": (
        "Forward P/E is not meaningful here (forward earnings are not positive)"
    ),
}

#: Codes that state a condition rather than a threshold breach.
_FAIL_STATEMENTS: dict[str, str] = {
    "LEVERAGE_NON_POSITIVE_EBITDA": (
        "Trailing EBITDA is not positive, so net debt / EBITDA (LTM) cannot be measured"
    ),
    "MISSING_MARKET_CAP": "Market cap is missing, so the market-based checks could not run",
    "MISSING_PRODUCTION": "Production is missing, so the margin checks could not run",
    "MISSING_AISC": "AISC is missing, so the cost checks could not run",
    "MISSING_SUSTAINING_CAPEX": "Sustaining capex is missing",
    "MISSING_RESERVE_LIFE": "Reserve life is missing, so the reserve-life check could not run",
    "MISSING_NET_DEBT": "Net debt is missing, so the leverage check could not run",
    "MISSING_EBITDA": "Trailing EBITDA is missing, so the leverage check could not run",
}

_OUR_VIEW_BASIS = "Our View mining assumption"
_LTM_BASIS = "last twelve months (LTM)"


# ---------------------------------------------------------------------------
# formatting (display only — no arithmetic anywhere in this module)
# ---------------------------------------------------------------------------


def _value(row: Any, column: str) -> float | None:
    """Read one persisted column as a plain float, or ``None`` when absent."""

    if row is None:
        return None
    raw = row.get(column) if hasattr(row, "get") else None
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _text(row: Any, column: str) -> str:
    if row is None:
        return ""
    raw = row.get(column) if hasattr(row, "get") else None
    if raw is None:
        return ""
    try:
        if pd.isna(raw):
            return ""
    except (TypeError, ValueError):
        pass
    return str(raw).strip()


def _grouped(text: str) -> str:
    """Thousands separators for an already-formatted magnitude string.

    Mirrored character-for-character by ``groupDigits`` in gold-dial.js.
    """

    whole, _, fraction = text.partition(".")
    negative = whole.startswith("-")
    digits = whole[1:] if negative else whole
    chunks: list[str] = []
    while len(digits) > 3:
        chunks.insert(0, digits[-3:])
        digits = digits[:-3]
    chunks.insert(0, digits)
    out = ("-" if negative else "") + ",".join(chunks)
    return f"{out}.{fraction}" if fraction else out


def _currency(magnitude: str, suffix: str = "") -> str:
    """Place the minus sign OUTSIDE the currency symbol ("-$3,000m").

    Mirrored by ``currency`` in gold-dial.js. Pure string work — a negative
    magnitude already carries its sign from ``_grouped``.
    """

    if magnitude.startswith("-"):
        return "-$" + magnitude[1:] + suffix
    return "$" + magnitude + suffix


def format_metric(value: float | None, unit: str) -> str:
    """The ONE server-side metric formatter — mirrored by ``formatMetric`` in
    gold-dial.js so a spot cell and a scenario cell can never read differently.
    """

    if value is None:
        return "n/a"
    if unit == "musd":
        return _currency(_grouped(f"{value:.0f}"), "m")
    if unit == "usd2":
        return _currency(_grouped(f"{value:.2f}"))
    if unit == "usd_per_oz":
        return _currency(_grouped(f"{value:.0f}"), "/oz")
    if unit == "usd":
        return _currency(_grouped(f"{value:.0f}"))
    if unit == "pct":
        return f"{value:.1%}"
    if unit == "ratio":
        return f"{value:.2f}×"
    if unit == "years":
        return f"{value:.1f} years"
    if unit == "oz":
        return _grouped(f"{value:.0f}") + " oz"
    if unit == "days":
        return f"{value:.0f} days"
    if unit == "percentile":
        return _grouped(f"{value:.0f}")
    return _grouped(f"{value:.2f}")


def _cell(row: Any, column: str, unit: str) -> str:
    return escape(format_metric(_value(row, column), unit))


# ---------------------------------------------------------------------------
# gold dial control (global control bar) + payload
# ---------------------------------------------------------------------------


def _dial_state(
    gold_row: pd.Series | None, artifact_status: str, artifact_reason: str | None
) -> tuple[bool, str]:
    """(enabled, reason) — the ONE place the dial's availability is decided."""

    if artifact_status != "OK":
        return False, str(artifact_reason or f"gold-response artifact state {artifact_status}")
    if gold_row is None:
        return False, "no gold-response row was published for this ticker and source"
    status = _text(gold_row, "gold_response_status")
    if status != "OK":
        return False, _text(gold_row, "gold_response_reason") or f"gold response {status}"
    return True, ""


def build_gold_dial_payload(
    gold_row: pd.Series | None,
    *,
    ticker: str,
    finance_source: str,
    enabled: bool,
    disabled_reason: str,
) -> dict[str, Any]:
    """Backend-resolved inputs for gold-dial.js — artifact values, nothing else.

    Every number below is a column read. No ratio, no rounding, no derived
    field: the client evaluates, the artifact decides.
    """

    return {
        "ticker": str(ticker),
        "finance_source": str(finance_source),
        # The RAW persisted per-ticker state travels beside the resolved
        # availability flag: the flag is the decision serve already made, the
        # status/reason are the artifact's own words, unedited.
        "gold_response_status": _text(gold_row, "gold_response_status") or None,
        "gold_response_reason": _text(gold_row, "gold_response_reason") or None,
        "enabled": bool(enabled),
        "disabled_reason": disabled_reason or None,
        "spot_gold_usd": _value(gold_row, "spot_gold_usd"),
        "spot_gold_date": _text(gold_row, "spot_gold_date") or None,
        "margin_basis": _text(gold_row, "spot_margin_basis") or None,
        "lines": {
            metric: {
                "slope": _value(gold_row, f"line_slope_{metric}"),
                "intercept": _value(gold_row, f"line_intercept_{metric}"),
            }
            for metric in GOLD_RESPONSE_LINE_METRICS
        },
        "constants": {
            column: _value(gold_row, column) for column in GOLD_RESPONSE_CONSTANT_COLUMNS
        },
        "spot_display": {
            metric: _value(gold_row, column)
            for metric, column in SPOT_DISPLAY_BY_METRIC.items()
        },
        "formats": dict(METRIC_FORMATS),
    }


def render_gold_dial_control(
    data: TickerPageData,
    *,
    ticker: str,
    finance_source: str,
    app_config: AppConfig | None,
) -> str:
    """The global control-bar dial (requirements §3, D-6).

    Range and step come from ``config/ticker_page.yaml`` through the config
    object — never hardcoded. The default position is the artifact's own spot
    gold, never a configured scenario.
    """

    gold_row = data.gold_response_row(ticker, finance_source=finance_source)
    enabled, reason = _dial_state(
        gold_row, data.gold_response.status, data.gold_response.reason
    )
    spot = _value(gold_row, "spot_gold_usd")
    spot_date = _text(gold_row, "spot_gold_date")

    if app_config is None:
        return (
            '<div class="gold-dial" id="gold-dial">'
            '<p class="hint">Gold scenario dial unavailable: no configuration is loaded.</p>'
            "</div>"
        )
    dial_cfg = app_config.ticker_page.dial
    minimum = format_metric(float(dial_cfg.min_gold_usd), "usd")
    maximum = format_metric(float(dial_cfg.max_gold_usd), "usd")
    value_attr = "" if spot is None else f"{spot:g}"
    disabled_attr = "" if enabled and spot is not None else " disabled"
    explain = help_icon(
        "Gold price scenario", key="ticker_gold_dial", app_config=app_config
    )
    spot_label = (
        f"spot {format_metric(spot, 'usd')}"
        + (f" as of {spot_date}" if spot_date else "")
        if spot is not None
        else "spot gold unavailable"
    )
    reason_html = (
        f'<p class="hint gold-dial-disabled">Dial unavailable for {escape(str(ticker))}: '
        f"{escape(reason)}</p>"
        if not enabled or spot is None
        else ""
    )
    return (
        '<div class="gold-dial" id="gold-dial">'
        f'<label class="gold-dial-label" for="gold-dial-input">Gold price scenario{explain}</label>'
        '<input type="range" id="gold-dial-input" name="gold_dial"'
        f' min="{float(dial_cfg.min_gold_usd):g}" max="{float(dial_cfg.max_gold_usd):g}"'
        f' step="{float(dial_cfg.step_usd):g}" value="{escape(value_attr, quote=True)}"'
        f' aria-describedby="gold-dial-spot"{disabled_attr}>'
        '<output class="gold-dial-output" id="gold-dial-output" for="gold-dial-input">'
        f"{escape(format_metric(spot, 'usd'))}</output>"
        '<button type="button" class="button-like" id="gold-dial-reset"'
        f"{disabled_attr}>Reset to spot</button>"
        f'<span class="hint" id="gold-dial-spot">{escape(spot_label)} · range '
        f"{escape(minimum)}–{escape(maximum)}</span>"
        '<p class="hint" id="gold-dial-status" role="status" aria-live="polite"></p>'
        f"{reason_html}"
        "</div>"
    )


# ---------------------------------------------------------------------------
# failing-checks notice (persisted verdicts only — serve compares nothing)
# ---------------------------------------------------------------------------


def _threshold_text(app_config: AppConfig | None, path: str, unit: str) -> str:
    """Format one configured threshold addressed as ``config_group.attribute``.

    Thresholds live in two groups under ``screening_params`` (the layer-1
    screening limits and the verdict cut-offs). Addressing them by path keeps
    ONE sentence registry instead of one registry per config group.
    """

    if app_config is None:
        return "your configured threshold"
    group_name, _, attribute = path.partition(".")
    group = getattr(app_config.screening_params, group_name, None)
    raw = getattr(group, attribute, None) if group is not None else None
    if raw is None:
        return "your configured threshold"
    return format_metric(float(raw), unit)


def _persisted_codes(row: Mapping[str, Any], column: str) -> list[str]:
    """The semicolon-joined codes in one persisted column, in artifact order.

    An absent column, ``None``, an empty string and a NaN all mean the same
    thing: nothing failed that this column can speak for. None of them is an
    error, and none of them is a reason to guess.
    """

    raw = str(row.get(column) or "").strip()
    if not raw or raw.lower() == "nan":
        return []
    return [part.strip() for part in raw.split(";") if part.strip()]


def _fundamental_code_column(finance_source: str) -> str:
    return _FUNDAMENTAL_CODE_COLUMN_BY_SOURCE.get(
        str(finance_source).strip().lower(), _DEFAULT_FUNDAMENTAL_CODE_COLUMN
    )


def _failing_check_sentences(
    tool_b_row: Mapping[str, Any],
    *,
    finance_source: str,
    app_config: AppConfig | None,
) -> list[str]:
    """One sentence per PERSISTED failing check.

    Two persisted code columns feed the SAME registry: ``layer1_fail_reasons``
    (already materialized for the active finance source upstream) and the
    fundamental-check codes, which are NOT materialized and so are read from
    the per-source column. The fundamental column contributes only the checks
    layer 1 has no code for, so one failure is never printed as two.

    Serve NEVER compares a value to a threshold — it prints the measured column
    the persisted code names, beside the configured threshold that code was
    judged against.
    """

    codes = _persisted_codes(tool_b_row, "layer1_fail_reasons") + [
        code
        for code in _persisted_codes(
            tool_b_row, _fundamental_code_column(finance_source)
        )
        if code in _FUNDAMENTAL_ONLY_CODES
    ]

    sentences: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        seen.add(code)
        if code in _FAIL_SENTENCES:
            template, column, value_unit, path, threshold_unit = _FAIL_SENTENCES[code]
            measured = _value(tool_b_row, column)
            statement = _NON_POSITIVE_VALUE_SENTENCES.get(code)
            if statement is not None and (measured is None or measured <= 0):
                sentences.append(statement)
                continue
            sentences.append(
                template.format(
                    value=format_metric(measured, value_unit),
                    threshold=_threshold_text(app_config, path, threshold_unit),
                )
            )
        elif code in _FAIL_STATEMENTS:
            sentences.append(_FAIL_STATEMENTS[code])
    return sentences


def _render_failing_checks(
    tool_b_row: Mapping[str, Any],
    *,
    finance_source: str,
    app_config: AppConfig | None,
    spot_gold_usd: float | None,
    spot_gold_date: str,
) -> str:
    sentences = _failing_check_sentences(
        tool_b_row, finance_source=finance_source, app_config=app_config
    )
    if not sentences:
        return ""
    screening_gold = _value(tool_b_row, "gold_price_assumption")
    basis_bits = ["at spot gold"]
    if spot_gold_usd is not None:
        basis_bits.append(
            format_metric(spot_gold_usd, "usd")
            + (f"/oz as of {spot_gold_date}" if spot_gold_date else "/oz")
        )
    if screening_gold is not None:
        basis_bits.append(
            "screening basis " + format_metric(screening_gold, "usd") + "/oz"
        )
    explain = help_icon(
        "Failing screening checks", key="ticker_cf_failing_checks", app_config=app_config
    )
    body = (
        "<p><strong>These screening checks fail "
        f"{escape(' · '.join(basis_bits))}:</strong>{explain}</p><ul>"
        + "".join(f"<li>{escape(sentence)}.</li>" for sentence in sentences)
        + "</ul><p class=\"hint\">These sentences are fixed at spot gold and do not "
        "move with the dial.</p>"
    )
    return (
        '<div id="corporate-failing-checks">'
        + notice("warning", body)
        + "</div>"
    )


# ---------------------------------------------------------------------------
# rows + cards
# ---------------------------------------------------------------------------


def _scenario_cell(metric: str, *, tag: str = "td") -> str:
    """The initially-hidden scenario cell gold-dial.js writes into."""

    return (
        f'<{tag} class="scenario-cell" data-metric="{escape(metric)}" '
        f'data-basis="scenario" hidden></{tag}>'
    )


def _spot_dial_cell(metric: str) -> str:
    """Spot cell for a LINE metric.

    The gold-response contract persists spot display values for the six ratio
    metrics only, so a line metric's spot value is evaluated from its persisted
    line by gold-dial.js at ``g = spot`` — the same sanctioned client formula,
    at a different price. Recomputing it here would be backend maths in serve.
    """

    return (
        f'<td class="spot-cell" data-metric="{escape(metric)}" data-basis="spot">'
        '<span class="dial-pending">needs the gold dial (JavaScript)</span></td>'
    )


def _line_metric_row(metric: str, *, app_config: AppConfig | None) -> str:
    label = _METRIC_LABELS[metric]
    return (
        '<tr class="moves-with-gold">'
        f'<th scope="row">{escape(label)}'
        f"{help_icon(label, key=_METRIC_HELP_KEYS[metric], app_config=app_config)}</th>"
        + _spot_dial_cell(metric)
        + _scenario_cell(metric)
        + '<td class="basis">moves with gold · evaluated from the persisted line</td>'
        "</tr>"
    )


def _ratio_metric_row(
    metric: str, gold_row: pd.Series | None, *, app_config: AppConfig | None, basis: str
) -> str:
    label = _METRIC_LABELS[metric]
    column = SPOT_DISPLAY_BY_METRIC[metric]
    return (
        '<tr class="moves-with-gold">'
        f'<th scope="row">{escape(label)}'
        f"{help_icon(label, key=_METRIC_HELP_KEYS[metric], app_config=app_config)}</th>"
        f'<td class="spot-cell">{_cell(gold_row, column, METRIC_FORMATS[metric])}</td>'
        + _scenario_cell(metric)
        + f'<td class="basis">{escape(basis)}</td>'
        "</tr>"
    )


def _fixed_row(
    label: str,
    value_html: str,
    basis: str,
    *,
    help_key: str | None = None,
    app_config: AppConfig | None = None,
) -> str:
    explain = (
        help_icon(label, key=help_key, app_config=app_config) if help_key else ""
    )
    return (
        f'<tr><th scope="row">{escape(label)}{explain}</th>'
        f'<td class="spot-cell">{value_html}</td>'
        f'<td class="basis">{escape(basis)}</td></tr>'
    )


def _moving_table(
    rows_html: str,
    *,
    region_id: str,
    label: str,
    spot_header: str,
    app_config: AppConfig | None = None,
) -> str:
    scenario_help = help_icon(
        "At your scenario", key="ticker_cf_scenario_column", app_config=app_config
    )
    table_html = (
        '<table class="compact-table"><thead><tr>'
        '<th scope="col">Metric</th>'
        f'<th scope="col">{escape(spot_header)}</th>'
        '<th scope="col" class="scenario-head" data-scenario-head="1" hidden>'
        f"At your scenario{scenario_help}</th>"
        '<th scope="col">Basis</th></tr></thead>'
        f"<tbody>{rows_html}</tbody></table>"
    )
    return table_region(table_html, region_id=region_id, label=label)


def _fixed_table(rows_html: str, *, region_id: str, label: str) -> str:
    table_html = (
        '<table class="compact-table"><thead><tr>'
        '<th scope="col">Metric</th><th scope="col">Value</th>'
        '<th scope="col">Basis</th></tr></thead>'
        f"<tbody>{rows_html}</tbody></table>"
    )
    return table_region(table_html, region_id=region_id, label=label)


def _headline_cards(
    gold_row: pd.Series | None, *, app_config: AppConfig | None, spot_label: str
) -> str:
    cards: list[str] = []
    for metric in _HEADLINE_METRICS:
        label = _METRIC_LABELS[metric]
        column = SPOT_DISPLAY_BY_METRIC[metric]
        cards.append(
            f'<div class="metric-card" data-metric-card="{escape(metric)}">'
            f'<p class="metric-card-label">{escape(label)}'
            f"{help_icon(label, key=_METRIC_HELP_KEYS[metric], app_config=app_config)}</p>"
            f'<p class="metric-card-value spot-cell">'
            f"{_cell(gold_row, column, METRIC_FORMATS[metric])}</p>"
            + _scenario_cell(metric, tag="p")
            + f'<p class="hint metric-card-basis">{escape(spot_label)}</p>'
            "</div>"
        )
    return '<div class="metric-card-grid" id="corporate-headline">' + "".join(cards) + "</div>"


# ---------------------------------------------------------------------------
# disclosure groups
# ---------------------------------------------------------------------------


def _earnings_group(gold_row: pd.Series | None, *, app_config: AppConfig | None, spot_header: str) -> str:
    rows = "".join(
        _line_metric_row(metric, app_config=app_config)
        for metric in GOLD_RESPONSE_LINE_METRICS
    )
    rows += _ratio_metric_row(
        "margin_usd_per_oz", gold_row, app_config=app_config, basis="moves with gold"
    )
    rows += _ratio_metric_row(
        "margin_pct", gold_row, app_config=app_config, basis="moves with gold"
    )
    rows += _ratio_metric_row(
        "aisc_margin_yield", gold_row, app_config=app_config, basis="moves with gold"
    )
    return disclosure(
        escape("Earnings and cash at this gold price")
        + help_icon(
            "Earnings and cash at this gold price",
            key="ticker_cf_earnings_group",
            app_config=app_config,
        ),
        _moving_table(
            rows,
            region_id="corporate-earnings",
            label="Earnings and cash at this gold price",
            spot_header=spot_header,
            app_config=app_config,
        ),
    )


def _valuation_group(gold_row: pd.Series | None, *, app_config: AppConfig | None, spot_header: str) -> str:
    fixed = (
        _fixed_row(
            "Market cap",
            _cell(gold_row, "market_cap_musd", "musd"),
            "market snapshot",
            help_key="tool_b_market_cap",
            app_config=app_config,
        )
        + _fixed_row(
            "Enterprise value",
            _cell(gold_row, "enterprise_value_musd", "musd"),
            "market snapshot",
            help_key="tool_b_enterprise_value",
            app_config=app_config,
        )
        + _fixed_row(
            "Share price",
            _cell(gold_row, "share_price_usd", "usd2"),
            "market snapshot",
            help_key="tool_b_share_price",
            app_config=app_config,
        )
    )
    moving = _ratio_metric_row(
        "ev_ebitda", gold_row, app_config=app_config, basis="moves with gold"
    ) + _ratio_metric_row(
        "forward_pe", gold_row, app_config=app_config, basis="moves with gold"
    ) + _ratio_metric_row(
        "leverage_stressed", gold_row, app_config=app_config, basis="moves with gold"
    )
    body = _fixed_table(
        fixed, region_id="corporate-valuation-fixed", label="Valuation inputs"
    ) + _moving_table(
        moving,
        region_id="corporate-valuation-moving",
        label="Valuation multiples",
        spot_header=spot_header,
        app_config=app_config,
    )
    return disclosure(
        escape("Valuation")
        + help_icon("Valuation", key="ticker_cf_valuation_group", app_config=app_config),
        body,
    )


def _balance_sheet_group(
    gold_row: pd.Series | None,
    tool_b_row: Mapping[str, Any],
    *,
    app_config: AppConfig | None,
) -> str:
    rows = (
        _fixed_row(
            "Net debt",
            _cell(gold_row, "net_debt_musd", "musd"),
            "balance sheet",
            help_key="ticker_cf_net_debt",
            app_config=app_config,
        )
        + _fixed_row(
            "Interest expense",
            _cell(gold_row, "interest_expense_musd", "musd"),
            "per year",
            help_key="ticker_cf_interest_expense",
            app_config=app_config,
        )
        + _fixed_row(
            "Trailing EBITDA",
            _cell(gold_row, "ebitda_ltm_musd", "musd"),
            _LTM_BASIS,
            help_key="ticker_cf_ebitda_ltm",
            app_config=app_config,
        )
        + _fixed_row(
            "Net debt / EBITDA (LTM)",
            _cell(tool_b_row, "leverage", "ratio"),
            _LTM_BASIS,
            help_key="ticker_cf_leverage_trailing",
            app_config=app_config,
        )
        + _fixed_row(
            "AISC",
            _cell(gold_row, "aisc_usd_per_oz", "usd_per_oz"),
            _OUR_VIEW_BASIS,
            help_key="tool_b_aisc",
            app_config=app_config,
        )
        + _fixed_row(
            "Cash cost",
            _cell(gold_row, "cash_cost_usd_per_oz", "usd_per_oz"),
            _OUR_VIEW_BASIS,
            help_key="ticker_cf_cash_cost",
            app_config=app_config,
        )
        + _fixed_row(
            "Production",
            _cell(gold_row, "production_oz", "oz"),
            _OUR_VIEW_BASIS,
            help_key="ticker_cf_production",
            app_config=app_config,
        )
        + _fixed_row(
            "Reserve life",
            _cell(tool_b_row, "reserve_life_years", "years"),
            _OUR_VIEW_BASIS,
            help_key="tool_b_reserve_life",
            app_config=app_config,
        )
    )
    return disclosure(
        escape("Balance sheet, cost and scale")
        + help_icon(
            "Balance sheet, cost and scale",
            key="ticker_cf_balance_group",
            app_config=app_config,
        ),
        _fixed_table(
            rows, region_id="corporate-balance-sheet", label="Balance sheet, cost and scale"
        ),
    )


def _resilience_group(
    tool_d_row: Mapping[str, Any],
    *,
    finance_source: str,
    app_config: AppConfig | None,
) -> str:
    title = "Resilience — at what gold price does this break?"
    if str(finance_source).strip().lower() == "yahoo":
        return disclosure(
            escape(title),
            f'<p class="hint">Resilience is disabled in Yahoo Fundamentals mode: '
            f"{escape(YAHOO_RESILIENCE_REASON)}.</p>",
        )
    if not tool_d_row:
        return disclosure(
            escape(title),
            '<p class="hint">No resilience row has been published for this ticker.</p>',
        )
    status = _text(tool_d_row, "resilience_data_status")
    rows = (
        _fixed_row(
            "Operating breakeven gold",
            _cell(tool_d_row, "breaks_even_at_gold_usd", "usd_per_oz"),
            "below this each ounce loses money",
            help_key="tool_d_breakeven",
            app_config=app_config,
        )
        + _fixed_row(
            "Interest-cover gold",
            _cell(tool_d_row, "interest_cover_gold_usd", "usd_per_oz"),
            "below this earnings cannot cover interest",
            help_key="tool_d_interest_cover",
            app_config=app_config,
        )
        + _fixed_row(
            "Debt-stress gold",
            _cell(tool_d_row, "debt_stress_gold_usd", "usd_per_oz"),
            "below this leverage becomes distressed",
            help_key="tool_d_debt_stress",
            app_config=app_config,
        )
        + _fixed_row(
            "Survival distance",
            _cell(tool_d_row, "survival_distance_to_interest_cover_pct", "pct"),
            "how far gold can fall before interest cover breaks",
            help_key="tool_d_survival_distance",
            app_config=app_config,
        )
        + _fixed_row(
            "EBITDA fragility",
            _cell(tool_d_row, "fragility_ebitda_pct_per_10pct_gold", "pct"),
            "EBITDA move per 10% gold move",
            help_key="tool_d_fragility",
            app_config=app_config,
        )
        + _fixed_row(
            "Cost-curve position (percentile of your universe)",
            _cell(tool_d_row, "cost_curve_aisc_percentile", "percentile"),
            _OUR_VIEW_BASIS,
            help_key="tool_d_cost_curve",
            app_config=app_config,
        )
        + _fixed_row(
            "Resilience data status",
            escape(status or "n/a"),
            "Tool D as of " + (_text(tool_d_row, "as_of_date") or "n/a"),
            help_key="tool_d_data_status",
            app_config=app_config,
        )
    )
    explain = help_icon("Resilience", key="ticker_cf_resilience", app_config=app_config)
    return disclosure(
        escape(title) + explain,
        _fixed_table(rows, region_id="corporate-resilience", label="Resilience thresholds"),
    )


def _data_quality_group(
    gold_row: pd.Series | None,
    tool_b_row: Mapping[str, Any],
    *,
    data: TickerPageData,
    finance_source: str,
    app_config: AppConfig | None,
) -> str:
    rows = (
        _fixed_row(
            "Financials source",
            escape("Yahoo Fundamentals" if finance_source == "yahoo" else "Our View"),
            "active source toggle",
        )
        + _fixed_row(
            "Financial data status",
            escape(_text(tool_b_row, "financial_data_status") or "n/a"),
            "Tool B",
            help_key="ticker_cf_financial_data_status",
            app_config=app_config,
        )
        + _fixed_row(
            "Tool B as of",
            escape(_text(tool_b_row, "as_of_date") or "n/a"),
            "screening run",
        )
        + _fixed_row(
            "Screening gold basis",
            _cell(tool_b_row, "gold_price_assumption", "usd_per_oz"),
            "the gold price the checks were judged at",
        )
        + _fixed_row(
            "Market snapshot as of",
            escape(_text(tool_b_row, "snapshot_as_of_date") or "n/a"),
            "market snapshot",
        )
        + _fixed_row(
            "Snapshot normalization",
            escape(_text(tool_b_row, "snapshot_normalization_status") or "n/a"),
            "currency normalization boundary",
            help_key="ticker_cf_snapshot_normalization",
            app_config=app_config,
        )
        + _fixed_row(
            "FX staleness",
            _cell(tool_b_row, "fx_staleness_days", "days"),
            "market snapshot",
            help_key="ticker_cf_fx_staleness",
            app_config=app_config,
        )
        + _fixed_row(
            "Spot gold used",
            _cell(gold_row, "spot_gold_usd", "usd_per_oz"),
            "gold-response artifact as of " + (_text(gold_row, "spot_gold_date") or "n/a"),
        )
        + _fixed_row(
            "Margin cost basis",
            escape(_text(gold_row, "spot_margin_basis") or "n/a"),
            "which cost the margin is measured against",
        )
        + _fixed_row(
            "Gold response status",
            escape(_text(gold_row, "gold_response_status") or "n/a"),
            _text(gold_row, "gold_response_reason") or "no reason recorded",
        )
        + _fixed_row(
            "Gold response artifact",
            escape(data.gold_response.status),
            data.gold_response.reason or "current generation",
        )
    )
    explain = help_icon(
        "Data quality and sources", key="ticker_cf_data_quality", app_config=app_config
    )
    return disclosure(
        escape("Data quality and sources") + explain,
        _fixed_table(rows, region_id="corporate-data-quality", label="Data quality and sources"),
    )


# ---------------------------------------------------------------------------
# section
# ---------------------------------------------------------------------------


def render_corporate_finance_section(
    data: TickerPageData,
    *,
    ticker: str,
    finance_source: str,
    tool_b_row: Mapping[str, Any],
    tool_d_row: Mapping[str, Any],
    app_config: AppConfig | None = None,
) -> str:
    """The ``#corporate-finance`` section (requirements §2 position 2).

    ``tool_b_row`` and ``tool_d_row`` are the rows the detail route already
    holds (workspace state, LRU-cached) — this function opens no files.
    """

    gold_row = data.gold_response_row(ticker, finance_source=finance_source)
    enabled, reason = _dial_state(
        gold_row, data.gold_response.status, data.gold_response.reason
    )
    spot = _value(gold_row, "spot_gold_usd")
    spot_date = _text(gold_row, "spot_gold_date")
    spot_label = (
        "fwd @ spot " + format_metric(spot, "usd") + "/oz"
        if spot is not None
        else "spot gold unavailable"
    ) + (f" as of {spot_date}" if spot_date else "")
    spot_header = (
        "Reported (spot " + format_metric(spot, "usd") + ")"
        if spot is not None
        else "Reported (at spot)"
    )

    pieces: list[str] = [
        '<section class="panel" id="corporate-finance">',
        section_heading(
            "Corporate finance",
            help_html=help_icon(
                "Corporate finance", key="ticker_cf_section", app_config=app_config
            ),
        ),
        f'<p class="hint">{escape(spot_label)} · rows marked "moves with gold" follow '
        "the dial; everything else is fixed.</p>",
    ]

    if data.gold_response.status != "OK":
        pieces.append(
            notice(
                "degraded",
                "<p>Gold-response artifact state <strong>"
                f"{escape(data.gold_response.status)}</strong>: "
                f"{escape(data.gold_response.reason or 'no reason recorded')}. "
                "The values below are limited to what has been published; nothing is "
                "estimated to fill the gap.</p>",
            )
        )
    elif not enabled:
        pieces.append(
            notice(
                "warning",
                f"<p>The gold dial is disabled for {escape(str(ticker))}: "
                f"{escape(reason)}. Spot values below are the published ones.</p>",
            )
        )

    pieces.append(_headline_cards(gold_row, app_config=app_config, spot_label=spot_label))
    pieces.append(
        _render_failing_checks(
            tool_b_row,
            finance_source=finance_source,
            app_config=app_config,
            spot_gold_usd=spot,
            spot_gold_date=spot_date,
        )
    )
    pieces.append(_earnings_group(gold_row, app_config=app_config, spot_header=spot_header))
    pieces.append(_valuation_group(gold_row, app_config=app_config, spot_header=spot_header))
    pieces.append(_balance_sheet_group(gold_row, tool_b_row, app_config=app_config))
    pieces.append(
        _resilience_group(tool_d_row, finance_source=finance_source, app_config=app_config)
    )
    pieces.append(
        _data_quality_group(
            gold_row,
            tool_b_row,
            data=data,
            finance_source=finance_source,
            app_config=app_config,
        )
    )
    pieces.append(
        embed_json_payload(
            GOLD_DIAL_PAYLOAD_ID,
            build_gold_dial_payload(
                gold_row,
                ticker=ticker,
                finance_source=finance_source,
                enabled=enabled,
                disabled_reason=reason,
            ),
        )
    )
    pieces.append("</section>")
    return "".join(pieces)
