"""Render persisted option-signal chart frames for the ticker detail page."""

from __future__ import annotations

from html import escape
from typing import Mapping, Sequence

from golden_vector.serve.format_helpers import (
    _fmt_number,
    _fmt_percent,
    _fmt_text,
    _optional_float,
    format_dte_suffix,
)
from golden_vector.serve.ui.tables import table_region
from golden_vector.serve.option_signal_render import format_vol_points


OptionSignalPoint = Mapping[str, object]


def render_option_signal_charts(
    skew_curve_points: Sequence[OptionSignalPoint],
    oi_strike_points: Sequence[OptionSignalPoint],
    signal_history_points: Sequence[OptionSignalPoint],
    *,
    signal_horizon_days: int | None = None,
    underlying_price: float | None = None,
) -> str:
    """Render persisted option-signal frames; no chain scans or analytics here."""

    if not skew_curve_points and not oi_strike_points and not signal_history_points:
        return (
            "<section class=\"nested-panel option-signal-charts\">"
            "<h3>Option Signal Charts</h3>"
            "<p class=\"hint\">No persisted option-signal chart data is available yet. "
            "Run <code>python main.py refresh</code> after the signal migration.</p>"
            "</section>"
        )
    return (
        "<section class=\"nested-panel option-signal-charts\">"
        "<h3>Option Signal Charts</h3>"
        f"{_render_skew_curve_chart(skew_curve_points)}"
        f"{_render_oi_strike_chart(oi_strike_points, underlying_price=underlying_price)}"
        f"{_render_signal_history_chart(signal_history_points, signal_horizon_days=signal_horizon_days)}"
        "<p class=\"hint\">IV rank is not available yet; the history store needs "
        "more market-hours snapshots before that label is useful.</p>"
        "</section>"
    )


def _render_skew_curve_chart(points: Sequence[OptionSignalPoint]) -> str:
    if not points:
        return (
            "<section class=\"option-chart-block\">"
            "<h4>Skew Curve</h4>"
            "<p class=\"hint\">No persisted skew-curve points are available for this ticker.</p>"
            "</section>"
        )
    rows = []
    for point in sorted(
        points,
        key=lambda item: (
            _sort_number(item.get("horizon_days")),
            str(item.get("side") or ""),
            _sort_number(item.get("delta_bucket")),
        ),
    ):
        rows.append(
            "<tr>"
            f"<td>{_fmt_number(point.get('horizon_days'), decimals=0)}d</td>"
            f"<td>{_fmt_text(point.get('side'))}</td>"
            f"<td>{_fmt_number(point.get('delta_bucket'), decimals=2)}</td>"
            f"<td>{_fmt_percent(point.get('iv'), decimals=1)}</td>"
            f"<td>{_fmt_text(point.get('liquidity_flag'))}</td>"
            f"<td>{_format_flag_list(point.get('quote_flags'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"option-chart-block\">"
        "<h4>Skew Curve</h4>"
        f"{_render_skew_curve_svg(points)}"
        + table_region(
            "<table><thead><tr>"
            "<th scope=\"col\">Horizon</th><th scope=\"col\">Side</th><th scope=\"col\">Abs Delta</th>"
            "<th scope=\"col\">IV</th><th scope=\"col\">Liquidity</th><th scope=\"col\">Flags</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="option-skew-curve-table-region",
            label="Skew curve points",
        )
        + "</section>"
    )


def _render_oi_strike_chart(
    points: Sequence[OptionSignalPoint],
    *,
    underlying_price: float | None = None,
) -> str:
    if not points:
        return (
            "<section class=\"option-chart-block\">"
            "<h4>Open Interest by Strike</h4>"
            "<p class=\"hint\">No persisted open-interest strike points are available "
            "for this ticker.</p>"
            "</section>"
        )
    shown, omitted = _select_oi_strikes(points, underlying_price=underlying_price)
    trim_note = ""
    if omitted:
        trim_note = (
            "<p class=\"hint\">Showing strikes near the money plus the highest "
            f"open-interest strikes; {omitted} further strike rows are omitted.</p>"
        )
    rows = []
    for point in sorted(
        shown,
        key=lambda item: (
            str(item.get("side") or ""),
            _sort_number(item.get("strike")),
            _sort_number(item.get("days_to_expiry")),
        ),
    ):
        days = _record_int(point.get("days_to_expiry"))
        rows.append(
            "<tr>"
            f"<td>{_fmt_text(point.get('side'))}</td>"
            f"<td>{_fmt_number(point.get('strike'), decimals=2)}</td>"
            f"<td>{_fmt_number(point.get('open_interest'), decimals=0)}</td>"
            f"<td>{_fmt_number(point.get('volume'), decimals=0)}</td>"
            f"<td>{_fmt_text(point.get('expiration'))}{format_dte_suffix(days)}</td>"
            f"<td>{_fmt_text(point.get('liquidity_flag'))}</td>"
            f"<td>{_format_flag_list(point.get('quote_flags'))}</td>"
            "</tr>"
        )
    return (
        "<section class=\"option-chart-block\">"
        "<h4>Open Interest by Strike</h4>"
        f"{_render_oi_strike_svg(shown)}"
        + table_region(
            "<table><thead><tr>"
            "<th scope=\"col\">Side</th><th scope=\"col\">Strike</th><th scope=\"col\">Open Interest</th>"
            "<th scope=\"col\">Volume</th><th scope=\"col\">Expiry / DTE</th>"
            "<th scope=\"col\">Liquidity</th><th scope=\"col\">Flags</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="option-oi-strike-table-region",
            label="Open interest by strike",
        )
        + f"{trim_note}"
        + "</section>"
    )


def _select_oi_strikes(
    points: Sequence[OptionSignalPoint],
    *,
    underlying_price: float | None = None,
    near: int = 11,
    top_oi: int = 5,
) -> tuple[list[OptionSignalPoint], int]:
    """Trim the strike dump to the strikes that matter.

    Keeps the strikes nearest the money (``near`` distinct strikes, ~±5 around
    the underlying) plus the ``top_oi`` strikes carrying the most open interest,
    then returns the matching rows and the count of strike rows omitted.
    """

    strikes = sorted(
        {value for point in points if (value := _optional_float(point.get("strike"))) is not None}
    )
    if not strikes:
        return list(points), 0
    reference = underlying_price if underlying_price and underlying_price > 0 else None
    if reference is None:
        reference = strikes[len(strikes) // 2]
    nearest = sorted(strikes, key=lambda strike: abs(strike - reference))[:near]
    oi_by_strike: dict[float, float] = {}
    for point in points:
        strike = _optional_float(point.get("strike"))
        if strike is None:
            continue
        oi_by_strike[strike] = oi_by_strike.get(strike, 0.0) + (
            _optional_float(point.get("open_interest")) or 0.0
        )
    busiest = sorted(oi_by_strike, key=lambda strike: oi_by_strike[strike], reverse=True)[:top_oi]
    kept = set(nearest) | set(busiest)
    shown = [
        point
        for point in points
        if _optional_float(point.get("strike")) in kept
    ]
    return shown, len(points) - len(shown)


def _signal_history_horizon(points: Sequence[OptionSignalPoint]) -> int | None:
    """The signal horizon to chart, taken from the persisted long-form points."""

    horizons = sorted(
        {
            int(value)
            for point in points
            for value in (_optional_float(point.get("signal_horizon_days")),)
            if value is not None
        }
    )
    return horizons[0] if horizons else None


def _render_signal_history_chart(
    points: Sequence[OptionSignalPoint],
    *,
    signal_horizon_days: int | None = None,
) -> str:
    if not points:
        return (
            "<section class=\"option-chart-block\">"
            "<h4>Signal History</h4>"
            "<p class=\"hint\">No persisted signal history exists for this ticker yet.</p>"
            "</section>"
        )
    # Follow the row's actual signal horizon; min-of-points is only a
    # fallback for points predating the horizon column.
    horizon = signal_horizon_days or _signal_history_horizon(points)
    if horizon is not None:
        filtered = [
            point
            for point in points
            if _optional_float(point.get("signal_horizon_days")) == horizon
        ]
        if filtered:
            points = filtered
        else:
            # The row's horizon matched nothing — every persisted point predates the
            # signal_horizon_days column. Showing an empty chart there reads as "no
            # history exists"; fall back to the unfiltered points and label them with
            # the horizon the points themselves carry (None -> the generic label).
            horizon = _signal_history_horizon(points)
    label = f"{horizon}d" if horizon is not None else "Signal"
    rows = []
    for point in sorted(points, key=lambda item: str(item.get("as_of_date") or "")):
        rows.append(
            "<tr>"
            f"<td>{_fmt_text(point.get('as_of_date'))}</td>"
            f"<td>{format_vol_points(point.get('skew_residual'))}</td>"
            f"<td>{format_vol_points(point.get('atm_iv'))}</td>"
            f"<td>{_fmt_number(point.get('iv_rv_ratio'), decimals=2)}</td>"
            "</tr>"
        )
    return (
        "<section class=\"option-chart-block\">"
        "<h4>Signal History</h4>"
        f"{_render_signal_history_svg(points)}"
        + table_region(
            "<table><thead><tr>"
            f"<th scope=\"col\">Date</th><th scope=\"col\">{label} Skew Residual</th>"
            f"<th scope=\"col\">{label} ATM IV</th><th scope=\"col\">IV/RV Ratio</th>"
            "</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>",
            region_id="option-signal-history-table-region",
            label="Signal history",
        )
        + "</section>"
    )


def _render_skew_curve_svg(points: Sequence[OptionSignalPoint]) -> str:
    rows = [point for point in points if _optional_float(point.get("iv")) is not None]
    if not rows:
        return "<p class=\"hint\">No usable IV points to plot.</p>"
    ordered = sorted(
        rows,
        key=lambda item: (
            _sort_number(item.get("horizon_days")),
            str(item.get("side") or ""),
            _sort_number(item.get("delta_bucket")),
        ),
    )
    max_iv = max(_optional_float(row.get("iv")) or 0.0 for row in ordered)
    width = max(420, len(ordered) * 24 + 80)
    height = 170
    baseline = height - 36
    usable_height = 105
    bars = []
    labels = []
    for index, row in enumerate(ordered):
        iv = _optional_float(row.get("iv")) or 0.0
        bar_height = 0 if max_iv <= 0 else max(1, iv / max_iv * usable_height)
        x = 44 + index * 24
        y = baseline - bar_height
        cls = "series-put" if str(row.get("side") or "").upper() == "P" else "series-call"
        bars.append(
            f"<rect x=\"{x}\" y=\"{y:.1f}\" width=\"14\" height=\"{bar_height:.1f}\" "
            f"class=\"{cls}\"><title>{escape(str(row.get('horizon_days') or '-'))}d "
            f"{escape(str(row.get('side') or '-'))} delta "
            f"{escape(str(row.get('delta_bucket') or '-'))}: "
            f"{_fmt_percent(iv, decimals=1)}</title></rect>"
        )
        if index % 3 == 0:
            labels.append(
                f"<text x=\"{x + 7}\" y=\"{baseline + 16}\" text-anchor=\"middle\" "
                "font-size=\"10\" class=\"chart-strip-label\">"
                f"{escape(str(row.get('horizon_days') or '-'))}d</text>"
            )
    return (
        f"<svg class=\"option-chart-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Persisted option IV by side, delta, and horizon\">"
        f"<line x1=\"36\" y1=\"{baseline}\" x2=\"{width - 20}\" y2=\"{baseline}\" "
        "class=\"series-strip\"/>"
        f"{''.join(bars)}{''.join(labels)}"
        "<text x=\"36\" y=\"18\" font-size=\"11\" class=\"chart-strip-label\">IV</text>"
        "</svg>"
    )


def _render_oi_strike_svg(points: Sequence[OptionSignalPoint]) -> str:
    rows = [
        point
        for point in points
        if _optional_float(point.get("open_interest")) is not None
    ]
    if not rows:
        return "<p class=\"hint\">No open-interest points to plot.</p>"
    ordered = sorted(
        rows,
        key=lambda item: (
            str(item.get("side") or ""),
            _sort_number(item.get("strike")),
            _sort_number(item.get("days_to_expiry")),
        ),
    )
    max_oi = max(_optional_float(row.get("open_interest")) or 0.0 for row in ordered)
    width = 620
    row_height = 18
    height = max(80, len(ordered) * row_height + 34)
    bars = []
    for index, row in enumerate(ordered):
        oi = _optional_float(row.get("open_interest")) or 0.0
        bar_width = 0 if max_oi <= 0 else max(1, oi / max_oi * 360)
        y = 24 + index * row_height
        label = f"{str(row.get('side') or '-')} {_fmt_number(row.get('strike'), decimals=2)}"
        bars.append(
            f"<text x=\"8\" y=\"{y + 11}\" font-size=\"10\" class=\"chart-ink\">"
            f"{escape(label)}</text>"
            f"<rect x=\"115\" y=\"{y}\" width=\"{bar_width:.1f}\" height=\"12\" "
            "class=\"series-oi\"><title>"
            f"Open interest {_fmt_number(oi, decimals=0)}; "
            f"volume {_fmt_number(row.get('volume'), decimals=0)}</title></rect>"
        )
    return (
        f"<svg class=\"option-chart-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Persisted option open interest by strike\">"
        f"{''.join(bars)}"
        "</svg>"
    )


def _render_signal_history_svg(points: Sequence[OptionSignalPoint]) -> str:
    ordered = sorted(points, key=lambda item: str(item.get("as_of_date") or ""))
    horizon = _signal_history_horizon(ordered)
    label = f"{horizon}d" if horizon is not None else "signal"
    series = [
        (
            f"{label} skew residual",
            [_optional_float(point.get("skew_residual")) for point in ordered],
            "skew",
        ),
        (
            f"{label} ATM IV",
            [_optional_float(point.get("atm_iv")) for point in ordered],
            "atm",
        ),
        (
            "IV/RV ratio",
            [_optional_float(point.get("iv_rv_ratio")) for point in ordered],
            "ivrv",
        ),
    ]
    numeric_values = [
        value
        for _label, values, _series_key in series
        for value in values
        if value is not None
    ]
    if len(ordered) < 2 or not numeric_values:
        return "<p class=\"hint\">Not enough signal history to plot yet.</p>"
    min_value = min(numeric_values)
    max_value = max(numeric_values)
    if min_value == max_value:
        max_value = min_value + 1.0
    width = max(420, len(ordered) * 36 + 60)
    height = 170
    top = 18
    bottom = height - 34
    span = max_value - min_value
    lines = []
    for label, values, series_key in series:
        coords = []
        for index, value in enumerate(values):
            if value is None:
                continue
            x = 36 + index * ((width - 70) / max(1, len(ordered) - 1))
            y = bottom - ((value - min_value) / span) * (bottom - top)
            coords.append(f"{x:.1f},{y:.1f}")
        if len(coords) >= 2:
            lines.append(
                f"<polyline points=\"{' '.join(coords)}\" "
                f"class=\"series-{series_key}\" stroke-width=\"2\">"
                f"<title>{escape(label)}</title></polyline>"
            )
    if not lines:
        return "<p class=\"hint\">Not enough signal history to plot yet.</p>"
    return (
        f"<svg class=\"option-chart-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Persisted option signal history\">"
        f"<line x1=\"32\" y1=\"{bottom}\" x2=\"{width - 24}\" y2=\"{bottom}\" "
        "class=\"series-strip\"/>"
        f"{''.join(lines)}"
        "<text x=\"36\" y=\"18\" font-size=\"11\" class=\"chart-strip-label\">history</text>"
        "</svg>"
    )


def _sort_number(value: object) -> float:
    parsed = _optional_float(value)
    return float("inf") if parsed is None else parsed


def _record_int(value: object) -> int | None:
    parsed = _optional_float(value)
    return None if parsed is None else int(parsed)


def _format_flag_list(value: object) -> str:
    raw = str(value or "").replace("|", ", ").strip()
    return "-" if not raw else escape(raw)
