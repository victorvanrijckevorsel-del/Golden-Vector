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
from golden_vector.serve.option_signal_render import format_vol_points


OptionSignalPoint = Mapping[str, object]


def render_option_signal_charts(
    skew_curve_points: Sequence[OptionSignalPoint],
    oi_strike_points: Sequence[OptionSignalPoint],
    signal_history_points: Sequence[OptionSignalPoint],
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
        f"{_render_oi_strike_chart(oi_strike_points)}"
        f"{_render_signal_history_chart(signal_history_points)}"
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
        "<table><thead><tr>"
        "<th>Horizon</th><th>Side</th><th>Delta</th><th>IV</th><th>Liquidity</th><th>Flags</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_oi_strike_chart(points: Sequence[OptionSignalPoint]) -> str:
    if not points:
        return (
            "<section class=\"option-chart-block\">"
            "<h4>Open Interest by Strike</h4>"
            "<p class=\"hint\">No persisted open-interest strike points are available "
            "for this ticker.</p>"
            "</section>"
        )
    rows = []
    for point in sorted(
        points,
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
        f"{_render_oi_strike_svg(points)}"
        "<table><thead><tr>"
        "<th>Side</th><th>Strike</th><th>Open Interest</th><th>Volume</th>"
        "<th>Expiry / DTE</th><th>Liquidity</th><th>Flags</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
    )


def _render_signal_history_chart(points: Sequence[OptionSignalPoint]) -> str:
    if not points:
        return (
            "<section class=\"option-chart-block\">"
            "<h4>Signal History</h4>"
            "<p class=\"hint\">No persisted signal history exists for this ticker yet.</p>"
            "</section>"
        )
    rows = []
    for point in sorted(points, key=lambda item: str(item.get("as_of_date") or "")):
        rows.append(
            "<tr>"
            f"<td>{_fmt_text(point.get('as_of_date'))}</td>"
            f"<td>{format_vol_points(point.get('skew_residual_60d'))}</td>"
            f"<td>{format_vol_points(point.get('atm_iv_60d'))}</td>"
            f"<td>{_fmt_number(point.get('iv_rv_ratio'), decimals=2)}</td>"
            "</tr>"
        )
    return (
        "<section class=\"option-chart-block\">"
        "<h4>Signal History</h4>"
        f"{_render_signal_history_svg(points)}"
        "<table><thead><tr>"
        "<th>Date</th><th>60d Skew Residual</th><th>60d ATM IV</th><th>IV/RV Ratio</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</section>"
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
        color = "#a45100" if str(row.get("side") or "").upper() == "P" else "#2f6f6d"
        bars.append(
            f"<rect x=\"{x}\" y=\"{y:.1f}\" width=\"14\" height=\"{bar_height:.1f}\" "
            f"fill=\"{color}\"><title>{escape(str(row.get('horizon_days') or '-'))}d "
            f"{escape(str(row.get('side') or '-'))} delta "
            f"{escape(str(row.get('delta_bucket') or '-'))}: "
            f"{_fmt_percent(iv, decimals=1)}</title></rect>"
        )
        if index % 3 == 0:
            labels.append(
                f"<text x=\"{x + 7}\" y=\"{baseline + 16}\" text-anchor=\"middle\" "
                "font-size=\"10\" fill=\"#5f584e\">"
                f"{escape(str(row.get('horizon_days') or '-'))}d</text>"
            )
    return (
        f"<svg class=\"option-chart-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Persisted option IV by side, delta, and horizon\">"
        f"<line x1=\"36\" y1=\"{baseline}\" x2=\"{width - 20}\" y2=\"{baseline}\" "
        "stroke=\"#cfc6b8\"/>"
        f"{''.join(bars)}{''.join(labels)}"
        "<text x=\"36\" y=\"18\" font-size=\"11\" fill=\"#5f584e\">IV</text>"
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
            f"<text x=\"8\" y=\"{y + 11}\" font-size=\"10\" fill=\"#3d3529\">"
            f"{escape(label)}</text>"
            f"<rect x=\"115\" y=\"{y}\" width=\"{bar_width:.1f}\" height=\"12\" "
            "fill=\"#7b6f5e\"><title>"
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
    series = [
        (
            "60d skew residual",
            [_optional_float(point.get("skew_residual_60d")) for point in ordered],
            "#a45100",
        ),
        (
            "60d ATM IV",
            [_optional_float(point.get("atm_iv_60d")) for point in ordered],
            "#2f6f6d",
        ),
        (
            "IV/RV ratio",
            [_optional_float(point.get("iv_rv_ratio")) for point in ordered],
            "#5b4a91",
        ),
    ]
    numeric_values = [
        value
        for _label, values, _color in series
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
    for label, values, color in series:
        coords = []
        for index, value in enumerate(values):
            if value is None:
                continue
            x = 36 + index * ((width - 70) / max(1, len(ordered) - 1))
            y = bottom - ((value - min_value) / span) * (bottom - top)
            coords.append(f"{x:.1f},{y:.1f}")
        if len(coords) >= 2:
            lines.append(
                f"<polyline points=\"{' '.join(coords)}\" fill=\"none\" "
                f"stroke=\"{color}\" stroke-width=\"2\">"
                f"<title>{escape(label)}</title></polyline>"
            )
    if not lines:
        return "<p class=\"hint\">Not enough signal history to plot yet.</p>"
    return (
        f"<svg class=\"option-chart-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Persisted option signal history\">"
        f"<line x1=\"32\" y1=\"{bottom}\" x2=\"{width - 24}\" y2=\"{bottom}\" "
        "stroke=\"#cfc6b8\"/>"
        f"{''.join(lines)}"
        "<text x=\"36\" y=\"18\" font-size=\"11\" fill=\"#5f584e\">history</text>"
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
