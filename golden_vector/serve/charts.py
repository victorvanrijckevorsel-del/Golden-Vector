"""SVG chart builders for the local workspace UI."""

from __future__ import annotations

from html import escape

import pandas as pd


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
        f"<circle cx=\"{sx(float(x)):.1f}\" cy=\"{sy(float(y)):.1f}\" r=\"3.2\" fill=\"#1d4b73\" opacity=\"0.72\" />"
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
            f"x2=\"{sx(x2):.1f}\" y2=\"{sy(y2):.1f}\" stroke=\"#b26700\" stroke-width=\"2\" />"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Weekly return scatter\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"<line x1=\"{padding}\" y1=\"{sy(0):.1f}\" x2=\"{width - padding}\" y2=\"{sy(0):.1f}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />"
        f"<line x1=\"{sx(0):.1f}\" y1=\"{padding}\" x2=\"{sx(0):.1f}\" y2=\"{height - padding}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />"
        f"{line}{points}"
        f"<text x=\"{padding}\" y=\"20\" font-size=\"12\" fill=\"#6f685c\">Stock weekly return</text>"
        f"<text x=\"{width - 150}\" y=\"{height - 10}\" font-size=\"12\" fill=\"#6f685c\">Gold weekly return</text>"
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

    def bar_color(value: float) -> str:
        return "#2d6a4f" if value >= 0 else "#8a2d3b"

    bars = []
    for x_pos, label, value in ((95, left_label, left_value), (235, right_label, right_value)):
        height_value = bar_height(value)
        bars.append(
            f"<rect x=\"{x_pos}\" y=\"{bar_y(value):.1f}\" width=\"40\" height=\"{height_value:.1f}\" fill=\"{bar_color(value)}\" opacity=\"0.85\" rx=\"6\" ry=\"6\" />"
        )
        bars.append(
            f"<text x=\"{x_pos + 20}\" y=\"{height - 18}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#6f685c\">{escape(label)}</text>"
        )
        bars.append(
            f"<text x=\"{x_pos + 20}\" y=\"{bar_y(value) - 8 if value >= 0 else bar_y(value) + height_value + 16:.1f}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#1f1d1a\">{value:,.2f}</text>"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Up beta versus down beta\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"<line x1=\"{padding}\" y1=\"{baseline:.1f}\" x2=\"{width - padding}\" y2=\"{baseline:.1f}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />"
        f"{''.join(bars)}"
        "</svg>"
    )


_BENCHMARK_COLORS = {"GDX": "#1d4b73", "GDXJ": "#3f7cae"}
_STOCK_COLOR = "#b26700"


def _benchmark_color(label: str, index: int) -> str:
    return _BENCHMARK_COLORS.get(label.upper(), "#3f7cae" if index % 2 else "#1d4b73")


def _build_beta_strip_svg(
    *,
    axis_label: str,
    domain: tuple[float, float] | None,
    universe_positions: list[float],
    subject_pos: float | None,
    subject_label: str,
    benchmark_positions: list[float],
) -> str:
    """Render a slim "where does this stock rank" strip from BACKEND-resolved positions.

    The full miner universe is drawn as a faint "rug" of ticks (so the distribution is visible),
    the stock is the one labelled orange marker, and GDX/GDXJ are small dashed ticks (their exact
    values live on the grouped Up-vs-Down bar, so they are intentionally not labelled here to avoid
    clutter). Every position is a pre-computed 0..1 fraction; this builder only maps it to a pixel.
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
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />",
        f"<text x=\"{padding}\" y=\"18\" font-size=\"12\" fill=\"#6f685c\">{escape(axis_label)}</text>",
        f"<line x1=\"{padding}\" y1=\"{track_y}\" x2=\"{width - padding}\" y2=\"{track_y}\" stroke=\"#cdbfa6\" stroke-width=\"3\" stroke-linecap=\"round\" />",
        f"<text x=\"{padding}\" y=\"{track_y + 26}\" font-size=\"11\" fill=\"#9a917f\">{low:,.2f}</text>",
        f"<text x=\"{width - padding}\" y=\"{track_y + 26}\" text-anchor=\"end\" font-size=\"11\" fill=\"#9a917f\">{high:,.2f}</text>",
    ]
    # Universe rug: one faint tick per scored miner (shows the distribution).
    for pos in universe_positions:
        x = px(float(pos))
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{track_y - 7}\" x2=\"{x:.1f}\" y2=\"{track_y + 7}\" stroke=\"#d2c4a6\" stroke-width=\"1\" opacity=\"0.7\" />"
        )
    # GDX/GDXJ context ticks (dashed, unlabelled — values are on the grouped bar).
    for pos in benchmark_positions:
        x = px(float(pos))
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{track_y - 11}\" x2=\"{x:.1f}\" y2=\"{track_y + 11}\" stroke=\"#1d4b73\" stroke-width=\"2\" stroke-dasharray=\"3 2\" />"
        )
    # The stock: the one labelled marker.
    if subject_pos is not None:
        x = px(float(subject_pos))
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{track_y - 15}\" x2=\"{x:.1f}\" y2=\"{track_y + 15}\" stroke=\"{_STOCK_COLOR}\" stroke-width=\"2\" />"
        )
        parts.append(f"<circle cx=\"{x:.1f}\" cy=\"{track_y:.1f}\" r=\"5\" fill=\"{_STOCK_COLOR}\" />")
        # Keep the label inside the canvas at the extremes.
        anchor = "middle"
        if x < padding + 40:
            anchor = "start"
        elif x > width - padding - 40:
            anchor = "end"
        parts.append(
            f"<text x=\"{x:.1f}\" y=\"{track_y - 21}\" text-anchor=\"{anchor}\" font-size=\"11.5\" fill=\"#1f1d1a\">{escape(subject_label)}</text>"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"{escape(axis_label)} distribution\">"
        f"{''.join(parts)}"
        "</svg>"
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
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />",
        f"<line x1=\"{padding}\" y1=\"{baseline:.1f}\" x2=\"{width - padding}\" y2=\"{baseline:.1f}\" stroke=\"#bfb5a2\" stroke-width=\"1\" />",
    ]
    if title:
        parts.append(
            f"<text x=\"{width / 2:.0f}\" y=\"20\" text-anchor=\"middle\" font-size=\"12\" fill=\"#6f685c\">{escape(title)}</text>"
        )
    for center, group in zip(group_centers, groups, strict=False):
        bars = group["bars"]
        total_w = len(bars) * bar_w + (len(bars) - 1) * gap
        start = center - total_w / 2
        for i, bar in enumerate(bars):
            value = bar.get("value")
            x = start + i * (bar_w + gap)
            label = escape(str(bar.get("label", "")))
            color = str(bar.get("color", "#1d4b73"))
            if value is None:
                parts.append(
                    f"<text x=\"{x + bar_w / 2:.1f}\" y=\"{baseline - 6:.1f}\" text-anchor=\"middle\" font-size=\"10\" fill=\"#9a917f\">n/a</text>"
                )
                continue
            value = float(value)
            bh = bar_height(value)
            y = baseline - bh if value >= 0 else baseline
            parts.append(
                f"<rect x=\"{x:.1f}\" y=\"{y:.1f}\" width=\"{bar_w}\" height=\"{bh:.1f}\" fill=\"{color}\" opacity=\"0.9\" rx=\"5\" ry=\"5\" />"
            )
            value_y = (y - 6) if value >= 0 else (y + bh + 14)
            parts.append(
                f"<text x=\"{x + bar_w / 2:.1f}\" y=\"{value_y:.1f}\" text-anchor=\"middle\" font-size=\"11\" fill=\"#1f1d1a\">{value:,.2f}</text>"
            )
            parts.append(
                f"<text x=\"{x + bar_w / 2:.1f}\" y=\"{height - 26:.1f}\" text-anchor=\"middle\" font-size=\"9.5\" fill=\"#8a8170\">{label}</text>"
            )
        parts.append(
            f"<text x=\"{center:.1f}\" y=\"{height - 10:.1f}\" text-anchor=\"middle\" font-size=\"12\" fill=\"#5f594c\">{escape(str(group['label']))}</text>"
        )
    return (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Up versus down beta vs benchmarks\">"
        f"{''.join(parts)}"
        "</svg>"
    )


def _build_multiline_overlay_svg(
    *,
    series_by_label: dict[str, tuple[list[pd.Timestamp], list[float | None]]],
    colors: dict[str, str] | None = None,
    base: float = 100.0,
) -> str:
    """SVG line chart of several already-rebased series sharing one indexed y-axis.

    ``series_by_label`` maps a label → (dates, values) where values are pre-rebased upstream
    (``model.structural.build_rebased_comparison_series``). All series are drawn; a dashed
    baseline at ``base`` (100) anchors the comparison. ``None`` values (gaps / pre-anchor points)
    are skipped within each line. The x-axis spans the union of dates so different-length series
    align. Serve-render only: it maps pre-computed values to pixels, no business arithmetic."""

    colors = colors or {}
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
            f"stroke=\"#bfb5a2\" stroke-width=\"1\" stroke-dasharray=\"3 3\" />"
        )

    lines_html = ""
    legend_parts: list[str] = []
    for index, (label, points) in enumerate(cleaned.items()):
        color = colors.get(label, _benchmark_color(label, index))
        coords = " ".join(f"{x_at(d):.1f},{y_at(v):.1f}" for d, v in points)
        lines_html += (
            f"<polyline points=\"{coords}\" fill=\"none\" stroke=\"{color}\" "
            f"stroke-width=\"1.8\" opacity=\"0.9\" />"
        )
        legend_parts.append(
            f"<span class=\"chart-legend-item\" style=\"color:{color};font-weight:600\">"
            f"&#9632; {escape(label)}</span>"
        )
    legend_html = "<p class=\"chart-legend\">" + " ".join(legend_parts) + "</p>"

    y_labels = (
        f"<text x=\"{padding_left - 6}\" y=\"{y_at(value_hi) + 4:.1f}\" text-anchor=\"end\" "
        f"font-size=\"11\" fill=\"#6f685c\">{value_hi:.0f}</text>"
        f"<text x=\"{padding_left - 6}\" y=\"{y_at(value_lo) + 4:.1f}\" text-anchor=\"end\" "
        f"font-size=\"11\" fill=\"#6f685c\">{value_lo:.0f}</text>"
    )
    date_labels = (
        f"<text x=\"{padding_left}\" y=\"{height - 8}\" font-size=\"11\" fill=\"#6f685c\">"
        f"{min_date.strftime('%Y-%m-%d')}</text>"
        f"<text x=\"{width - padding_right}\" y=\"{height - 8}\" text-anchor=\"end\" "
        f"font-size=\"11\" fill=\"#6f685c\">{max_date.strftime('%Y-%m-%d')}</text>"
    )

    svg = (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Rebased price comparison\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"{baseline}{lines_html}{y_labels}{date_labels}"
        "</svg>"
    )
    return legend_html + svg
