"""SVG chart builders for the local workspace UI."""

from __future__ import annotations

import json
import math
from html import escape

import pandas as pd

from golden_vector.model.benchmark_comparison import BetaUniverseMark
from golden_vector.serve.ui.tables import table_region


def _build_scatter_svg(
    *,
    x_values: list[float],
    y_values: list[float],
    regression_beta: float | None,
    regression_alpha: float | None,
) -> str:
    if not x_values or not y_values:
        return "<p>No scatter data available.</p>"
    width = 360
    height = 260
    padding = 32
    max_abs = max([abs(value) for value in x_values + y_values] + [0.01])
    domain = max_abs * 1.1

    def sx(value: float) -> float:
        return padding + ((value + domain) / (2 * domain)) * (width - (2 * padding))

    def sy(value: float) -> float:
        return height - padding - ((value + domain) / (2 * domain)) * (height - (2 * padding))

    points = "".join(
        f"<circle cx=\"{sx(float(x)):.1f}\" cy=\"{sy(float(y)):.1f}\" r=\"3.2\" class=\"chart-point\" opacity=\"0.72\" />"
        for x, y in zip(x_values, y_values, strict=False)
    )
    line = ""
    if regression_beta is not None and regression_alpha is not None:
        x1 = -domain
        y1 = regression_alpha + (regression_beta * x1)
        x2 = domain
        y2 = regression_alpha + (regression_beta * x2)
        line = (
            f"<line x1=\"{sx(x1):.1f}\" y1=\"{sy(y1):.1f}\" "
            f"x2=\"{sx(x2):.1f}\" y2=\"{sy(y2):.1f}\" class=\"chart-fit-line\" stroke-width=\"2\" />"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Weekly return scatter\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" class=\"chart-bg\" rx=\"12\" ry=\"12\" />"
        f"<line x1=\"{padding}\" y1=\"{sy(0):.1f}\" x2=\"{width - padding}\" y2=\"{sy(0):.1f}\" class=\"chart-axis-line\" stroke-width=\"1\" />"
        f"<line x1=\"{sx(0):.1f}\" y1=\"{padding}\" x2=\"{sx(0):.1f}\" y2=\"{height - padding}\" class=\"chart-axis-line\" stroke-width=\"1\" />"
        f"{line}{points}"
        f"<text x=\"{padding}\" y=\"20\" font-size=\"12\" class=\"chart-label\">Stock weekly return</text>"
        f"<text x=\"{width - 150}\" y=\"{height - 10}\" font-size=\"12\" class=\"chart-label\">Gold weekly return</text>"
        "</svg>"
    )


def _build_dual_bar_svg(
    *,
    left_label: str,
    left_value: float,
    right_label: str,
    right_value: float,
) -> str:
    width = 360
    height = 220
    padding = 28
    max_value = max(abs(left_value), abs(right_value), 0.25)
    plot_height = height - (2 * padding) - 30
    baseline = padding + (plot_height / 2)

    def bar_height(value: float) -> float:
        return (abs(value) / max_value) * (plot_height / 2)

    def bar_y(value: float) -> float:
        return baseline - bar_height(value) if value >= 0 else baseline

    def bar_class(value: float) -> str:
        return "series-positive" if value >= 0 else "series-negative"

    bars = []
    for x_pos, label, value in ((95, left_label, left_value), (235, right_label, right_value)):
        height_value = bar_height(value)
        bars.append(
            f"<rect x=\"{x_pos}\" y=\"{bar_y(value):.1f}\" width=\"40\" height=\"{height_value:.1f}\" class=\"{bar_class(value)}\" opacity=\"0.85\" rx=\"6\" ry=\"6\" />"
        )
        bars.append(
            f"<text x=\"{x_pos + 20}\" y=\"{height - 18}\" text-anchor=\"middle\" font-size=\"12\" class=\"chart-label\">{escape(label)}</text>"
        )
        bars.append(
            f"<text x=\"{x_pos + 20}\" y=\"{bar_y(value) - 8 if value >= 0 else bar_y(value) + height_value + 16:.1f}\" text-anchor=\"middle\" font-size=\"12\" class=\"chart-value\">{value:,.2f}</text>"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Up beta versus down beta\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" class=\"chart-bg\" rx=\"12\" ry=\"12\" />"
        f"<line x1=\"{padding}\" y1=\"{baseline:.1f}\" x2=\"{width - padding}\" y2=\"{baseline:.1f}\" class=\"chart-axis-line\" stroke-width=\"1\" />"
        f"{''.join(bars)}"
        "</svg>"
    )


_BENCHMARK_SERIES = {"GDX": "gdx", "GDXJ": "gdxj"}
_STOCK_SERIES = "stock"


def _benchmark_series(label: str, index: int) -> str:
    """Semantic series key for a label; paint lives in css/charts.css."""
    return _BENCHMARK_SERIES.get(label.upper(), "gdxj" if index % 2 else "gdx")


def _chart_data_disclosure(
    *,
    table_html: str,
    region_id: str,
    label: str,
) -> str:
    """Collapsed, keyboard-operable text equivalent for a pointer-only chart interaction.

    Accessibility remedy for GV-RD-FINAL-002: the crosshair / rug tooltips are pointer-driven, so
    every value they reveal is ALSO rendered as a plain table right after the chart. The table is
    built from the exact payload the SVG was built from — no recomputation, no truncation."""

    return (
        "<details class=\"disclosure chart-data-details\">"
        f"<summary>Chart data (table)</summary>"
        f"{table_region(table_html, region_id=region_id, label=label)}"
        "</details>"
    )


def _build_beta_strip_svg(
    *,
    axis_label: str,
    domain: tuple[float, float] | None,
    universe_marks: list[BetaUniverseMark],
    subject_pos: float | None,
    subject_label: str,
    benchmark_positions: list[float],
    data_table_id: str | None = None,
) -> str:
    """Render a slim "where does this stock rank" strip from BACKEND-resolved positions.

    The full miner universe is drawn as a faint "rug" of ticks (so the distribution is visible);
    each tick is identifiable on hover (ticker + beta) via an invisible wide hit-area. The stock
    is the one labelled orange marker, and GDX/GDXJ are small dashed ticks (their exact values
    live on the grouped Up-vs-Down bar). Every position is a pre-computed 0..1 fraction; this
    builder only maps it to a pixel.
    """

    if domain is None:
        return "<p>No comparison data available.</p>"
    width = 420
    height = 92
    padding = 40
    track_y = 50
    span = width - (2 * padding)

    # Positions are a trusted backend contract (the model's _position already clamps to 0..1); serve
    # only maps fraction -> pixel. We do NOT re-clamp here, so an out-of-range backend bug is visible
    # rather than silently hidden.
    def px(pos: float) -> float:
        return padding + (pos * span)

    low, high = domain
    parts = [
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" class=\"chart-bg\" rx=\"12\" ry=\"12\" />",
        f"<text x=\"{padding}\" y=\"18\" font-size=\"12\" class=\"chart-label\">{escape(axis_label)}</text>",
        f"<line x1=\"{padding}\" y1=\"{track_y}\" x2=\"{width - padding}\" y2=\"{track_y}\" class=\"chart-track-line\" stroke-width=\"3\" stroke-linecap=\"round\" />",
        f"<text x=\"{padding}\" y=\"{track_y + 26}\" font-size=\"11\" class=\"chart-label-minor\">{low:,.2f}</text>",
        f"<text x=\"{width - padding}\" y=\"{track_y + 26}\" text-anchor=\"end\" font-size=\"11\" class=\"chart-label-minor\">{high:,.2f}</text>",
    ]
    # Universe rug: one faint tick per scored miner (shows the distribution). Each tick gets an
    # invisible wide hit-area carrying a <title>, so hovering identifies the miner (ticker + beta)
    # — a bare 1px tick is far too thin to hover precisely.
    for mark in universe_marks:
        x = px(float(mark.position))
        label = f"{mark.ticker} · {mark.beta:,.2f}"
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{track_y - 7}\" x2=\"{x:.1f}\" y2=\"{track_y + 7}\" class=\"chart-tick-line\" stroke-width=\"1\" opacity=\"0.7\" />"
            f"<line class=\"rug-tick\" data-rug=\"{escape(label)}\" x1=\"{x:.1f}\" y1=\"{track_y - 9}\" x2=\"{x:.1f}\" y2=\"{track_y + 9}\" stroke=\"transparent\" stroke-width=\"7\" pointer-events=\"all\">"
            f"<title>{escape(label)}</title></line>"
        )
    # GDX/GDXJ context ticks (dashed, unlabelled — values are on the grouped bar).
    for pos in benchmark_positions:
        x = px(float(pos))
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{track_y - 11}\" x2=\"{x:.1f}\" y2=\"{track_y + 11}\" class=\"chart-marker\" stroke-width=\"2\" stroke-dasharray=\"3 2\" />"
        )
    # The stock: the one labelled marker.
    if subject_pos is not None:
        x = px(float(subject_pos))
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{track_y - 15}\" x2=\"{x:.1f}\" y2=\"{track_y + 15}\" class=\"series-{_STOCK_SERIES}\" stroke-width=\"2\" />"
        )
        parts.append(f"<circle cx=\"{x:.1f}\" cy=\"{track_y:.1f}\" r=\"5\" class=\"series-{_STOCK_SERIES}\" />")
        # Keep the label inside the canvas at the extremes.
        anchor = "middle"
        if x < padding + 40:
            anchor = "start"
        elif x > width - padding - 40:
            anchor = "end"
        parts.append(
            f"<text x=\"{x:.1f}\" y=\"{track_y - 21}\" text-anchor=\"{anchor}\" font-size=\"11.5\" class=\"chart-value\">{escape(subject_label)}</text>"
        )
    svg = (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{escape(axis_label)} distribution\">"
        f"{''.join(parts)}"
        "</svg>"
    )
    if not data_table_id:
        return svg
    # Text equivalent of the rug tooltips: one row per tick, exactly the ticker + beta the
    # hover <title> / rug-tooltip.js shows (same f-string as the tick label above).
    rows = "".join(
        f"<tr><td>{escape(mark.ticker)}</td><td>{escape(f'{mark.beta:,.2f}')}</td></tr>"
        for mark in universe_marks
    )
    table_html = (
        "<table>"
        f"<caption>{escape(axis_label)} — every miner in the universe</caption>"
        "<thead><tr><th scope=\"col\">Ticker</th><th scope=\"col\">Beta</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
    return svg + _chart_data_disclosure(
        table_html=table_html,
        region_id=data_table_id,
        label=f"{axis_label} — chart data table",
    )


def _build_grouped_beta_bar_svg(
    *,
    groups: list[dict[str, object]],
    title: str | None = None,
) -> str:
    """Grouped bar chart: each group (e.g. Up-Gold / Down-Gold) holds the stock + GDX + GDXJ bars,
    side by side, so the stock's beta reads directly against the ETFs on the SAME window.

    ``groups`` is a list of ``{"label": str, "bars": [{"label","value","color"}, ...]}``. Bars carry
    backend-resolved beta values; this builder only scales them to pixel heights.
    """

    if not groups:
        return "<p>No beta data available.</p>"
    width = 460
    height = 250
    padding = 26
    plot_top = 44
    plot_bottom = height - 46
    all_values = [
        float(bar["value"])
        for group in groups
        for bar in group["bars"]
        if bar.get("value") is not None
    ]
    if not all_values:
        return "<p>No beta data available.</p>"
    max_abs = max([abs(v) for v in all_values] + [0.25])
    has_negative = any(v < 0 for v in all_values)
    baseline = plot_bottom if not has_negative else (plot_top + plot_bottom) / 2
    bar_w = 30
    gap = 8
    group_centers = [width * (i + 1) / (len(groups) + 1) for i in range(len(groups))]

    def bar_height(value: float) -> float:
        return (abs(value) / max_abs) * (baseline - plot_top if value >= 0 else plot_bottom - baseline)

    parts = [
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" class=\"chart-bg\" rx=\"12\" ry=\"12\" />",
        f"<line x1=\"{padding}\" y1=\"{baseline:.1f}\" x2=\"{width - padding}\" y2=\"{baseline:.1f}\" class=\"chart-axis-line\" stroke-width=\"1\" />",
    ]
    if title:
        parts.append(
            f"<text x=\"{width / 2:.0f}\" y=\"20\" text-anchor=\"middle\" font-size=\"12\" class=\"chart-label\">{escape(title)}</text>"
        )
    for center, group in zip(group_centers, groups, strict=False):
        bars = group["bars"]
        total_w = len(bars) * bar_w + (len(bars) - 1) * gap
        start = center - total_w / 2
        for i, bar in enumerate(bars):
            value = bar.get("value")
            x = start + i * (bar_w + gap)
            label = escape(str(bar.get("label", "")))
            series_key = str(bar.get("series", "gdx"))
            if value is None:
                parts.append(
                    f"<text x=\"{x + bar_w / 2:.1f}\" y=\"{baseline - 6:.1f}\" text-anchor=\"middle\" font-size=\"10\" class=\"chart-label-minor\">n/a</text>"
                )
                continue
            value = float(value)
            bh = bar_height(value)
            y = baseline - bh if value >= 0 else baseline
            parts.append(
                f"<rect x=\"{x:.1f}\" y=\"{y:.1f}\" width=\"{bar_w}\" height=\"{bh:.1f}\" class=\"series-{escape(series_key)}\" opacity=\"0.9\" rx=\"5\" ry=\"5\" />"
            )
            value_y = (y - 6) if value >= 0 else (y + bh + 14)
            parts.append(
                f"<text x=\"{x + bar_w / 2:.1f}\" y=\"{value_y:.1f}\" text-anchor=\"middle\" font-size=\"11\" class=\"chart-value\">{value:,.2f}</text>"
            )
            parts.append(
                f"<text x=\"{x + bar_w / 2:.1f}\" y=\"{height - 26:.1f}\" text-anchor=\"middle\" font-size=\"9.5\" class=\"chart-label-soft\">{label}</text>"
            )
        parts.append(
            f"<text x=\"{center:.1f}\" y=\"{height - 10:.1f}\" text-anchor=\"middle\" font-size=\"12\" class=\"chart-label-strong\">{escape(str(group['label']))}</text>"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Up versus down beta vs benchmarks\">"
        f"{''.join(parts)}"
        "</svg>"
    )


def _pct_label(delta: float) -> str:
    """Signed percent label for the rebased overlay (value - base). Used for BOTH the
    y-axis gridline labels and the per-point hover values so the two can never diverge (one copy
    of the index-to-% display rule). Exact zero shows as ``0%`` without a sign."""
    if math.isclose(delta, 0.0, abs_tol=1e-9):
        return "0%"
    if abs(delta) < 1.0:
        compact = f"{delta:+.2f}".rstrip("0").rstrip(".")
        return f"{compact}%"
    if math.isclose(delta, round(delta), abs_tol=0.05):
        return f"{delta:+.0f}%"
    return f"{delta:+.1f}%"


def _nice_overlay_grid_step(span: float, *, max_intervals: int = 6) -> float:
    """Return a bounded 1/2/5-style grid step for rebased overlay display ticks."""

    if not math.isfinite(span) or span <= 0:
        return 1.0
    rough_step = span / max(max_intervals, 1)
    magnitude = 10 ** math.floor(math.log10(rough_step))
    for multiplier in (1, 2, 5, 10):
        step = multiplier * magnitude
        if span / step <= max_intervals:
            return step
    return 10 * magnitude


def _build_multiline_overlay_svg(
    *,
    series_by_label: dict[str, tuple[list[pd.Timestamp], list[float | None]]],
    series_keys: dict[str, str] | None = None,
    base: float = 100.0,
    data_table_id: str | None = None,
) -> str:
    """SVG line chart of several already-rebased series sharing one indexed y-axis.

    ``series_by_label`` maps a label → (dates, values) where values are pre-rebased upstream
    (``model.structural.build_rebased_comparison_series``). All series are drawn; a dashed
    baseline at ``base`` (100) anchors the comparison. ``None`` values (gaps / pre-anchor points)
    are skipped within each line. The x-axis spans the union of dates so different-length series
    align. Serve-render only: it maps pre-computed values to pixels, no business arithmetic."""

    series_keys = series_keys or {}
    width = 720
    height = 240
    padding_left = 48
    padding_right = 24
    padding_top = 20
    padding_bottom = 28
    inner_w = width - padding_left - padding_right
    inner_h = height - padding_top - padding_bottom

    cleaned: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    all_values: list[float] = []
    all_dates: list[pd.Timestamp] = []
    for label, series in series_by_label.items():
        dates, values = series
        if not dates or not values or len(dates) != len(values):
            continue
        # Skip points with a missing value OR a missing/NaT date — a NaT date would
        # otherwise propagate into min()/max() below and crash strftime on corrupt input.
        points = [
            (d, float(v)) for d, v in zip(dates, values) if v is not None and pd.notna(d)
        ]
        if not points:
            continue
        cleaned[label] = points
        all_dates.extend(d for d, _ in points)
        all_values.extend(v for _, v in points)

    if not cleaned:
        return "<p>No comparison data available.</p>"

    min_date = min(all_dates)
    max_date = max(all_dates)
    date_span_days = max((max_date - min_date).days, 1)

    def x_at(date_value: pd.Timestamp) -> float:
        return padding_left + ((date_value - min_date).days / date_span_days) * inner_w

    value_lo = min(all_values + [base])
    value_hi = max(all_values + [base])
    if value_hi == value_lo:
        value_hi = value_lo + 1.0
    pad = (value_hi - value_lo) * 0.1
    value_lo -= pad
    value_hi += pad

    def y_at(value: float) -> float:
        return padding_top + (1.0 - (value - value_lo) / (value_hi - value_lo)) * inner_h

    baseline = ""
    if value_lo <= base <= value_hi:
        baseline = (
            f"<line x1=\"{padding_left}\" y1=\"{y_at(base):.1f}\" "
            f"x2=\"{width - padding_right}\" y2=\"{y_at(base):.1f}\" "
            f"class=\"chart-axis-line\" stroke-width=\"1\" stroke-dasharray=\"3 3\" />"
        )

    resolved_series = {
        label: series_keys.get(label, _benchmark_series(label, index))
        for index, label in enumerate(cleaned)
    }

    lines_html = ""
    legend_parts: list[str] = []
    for label, points in cleaned.items():
        series_key = escape(resolved_series[label])
        coords = " ".join(f"{x_at(d):.1f},{y_at(v):.1f}" for d, v in points)
        lines_html += (
            f"<polyline points=\"{coords}\" class=\"series-{series_key}\" "
            f"stroke-width=\"1.8\" opacity=\"0.9\" />"
        )
        legend_parts.append(
            f"<span class=\"chart-legend-item legend-swatch-{series_key}\">"
            f"&#9632; {escape(label)}</span>"
        )
    legend_html = "<p class=\"chart-legend\">" + " ".join(legend_parts) + "</p>"

    # Horizontal gridlines at nice levels, labelled as % change from the rebase start (base=100)
    # so the lines are actually readable ("AEM +120%, gold +60%"). Display-only axis math.
    step = _nice_overlay_grid_step(value_hi - value_lo)
    grid_lines = ""
    grid_labels = ""
    tick = base + math.floor((value_lo - base) / step) * step
    max_tick_count = 12
    tick_count = 0
    while tick <= value_hi + 1e-9 and tick_count < max_tick_count:
        if tick >= value_lo - 1e-9:
            gy = y_at(tick)
            is_base = abs(tick - base) < 1e-9
            if not is_base:  # the dashed baseline already marks 0%
                grid_lines += (
                    f"<line x1=\"{padding_left}\" y1=\"{gy:.1f}\" x2=\"{width - padding_right}\" "
                    f"y2=\"{gy:.1f}\" class=\"chart-grid-line\" stroke-width=\"1\" />"
                )
            label_text = _pct_label(tick - base)
            grid_labels += (
                f"<text x=\"{padding_left - 6}\" y=\"{gy + 4:.1f}\" text-anchor=\"end\" "
                f"font-size=\"11\" class=\"chart-label\">{label_text}</text>"
            )
        tick += step
        tick_count += 1

    date_labels = (
        f"<text x=\"{padding_left}\" y=\"{height - 8}\" font-size=\"11\" class=\"chart-label\">"
        f"{min_date.strftime('%Y-%m-%d')}</text>"
        f"<text x=\"{width - padding_right}\" y=\"{height - 8}\" text-anchor=\"end\" "
        f"font-size=\"11\" class=\"chart-label\">{max_date.strftime('%Y-%m-%d')}</text>"
    )

    # Embed the data so the hover crosshair (overlay-crosshair.js) can show each line's value +
    # date at the cursor: ticks = union dates with x-px (for snapping); each series carries
    # byDate -> [y-px, value, pct-label]. The pct label is produced HERE by _pct_label (the same
    # formatter as the y-axis gridlines), so the JS only renders pre-formatted strings — no
    # percent arithmetic in the browser. Serve mirrors already-rebased values; no business math.
    # Ticks are keyed by the SAME date string as byDate (one entry per calendar day) so a tick and
    # its point can never desync, even if two timestamps happen to share a day.
    tick_x_by_date = {d.strftime("%Y-%m-%d"): round(x_at(d), 1) for d in all_dates}
    overlay_data = {
        "top": round(padding_top, 1),
        "bottom": round(height - padding_bottom, 1),
        "base": base,
        "ticks": sorted(tick_x_by_date.items()),
        "series": [
            {
                "label": label,
                "series": resolved_series[label],
                "byDate": {
                    d.strftime("%Y-%m-%d"): [round(y_at(v), 1), round(v, 2), _pct_label(v - base)]
                    for d, v in points
                },
            }
            for label, points in cleaned.items()
        ],
    }
    data_attr = escape(json.dumps(overlay_data, separators=(",", ":")))

    svg = (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Rebased price comparison\" "
        f"class=\"overlay-chart\" data-overlay=\"{data_attr}\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" class=\"chart-bg\" rx=\"12\" ry=\"12\" />"
        f"{grid_lines}{baseline}{lines_html}{grid_labels}{date_labels}"
        "</svg>"
    )
    if not data_table_id:
        return legend_html + svg
    # Text equivalent of the crosshair: one row per snapped date, one column per series, each cell
    # rendered from the SAME overlay_data payload the JS reads ("100.0 (+0.0%)" — value to one
    # decimal, then the pre-formatted percent label). No new arithmetic; every date is listed.
    series_entries = overlay_data["series"]
    header_cells = "".join(
        f"<th scope=\"col\">{escape(str(entry['label']))}</th>" for entry in series_entries
    )
    body_rows = ""
    for date_key, _x in overlay_data["ticks"]:
        cells = ""
        for entry in series_entries:
            point = entry["byDate"].get(date_key)
            cells += (
                f"<td>{escape(f'{point[1]:.1f}')} ({escape(str(point[2]))})</td>"
                if point
                else "<td>—</td>"
            )
        body_rows += f"<tr><th scope=\"row\">{escape(date_key)}</th>{cells}</tr>"
    table_html = (
        "<table>"
        "<caption>Rebased price comparison — indexed value (change vs the rebase start)</caption>"
        f"<thead><tr><th scope=\"col\">Date</th>{header_cells}</tr></thead>"
        f"<tbody>{body_rows}</tbody></table>"
    )
    return (
        legend_html
        + svg
        + _chart_data_disclosure(
            table_html=table_html,
            region_id=data_table_id,
            label="Rebased price comparison — chart data table",
        )
    )
