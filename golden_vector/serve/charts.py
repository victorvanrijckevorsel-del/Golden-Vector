"""SVG chart builders for the local workspace UI."""

from __future__ import annotations

from html import escape

import pandas as pd

from golden_vector.serve.workspace_state import _STRUCTURAL_WINDOWS, _WINDOW_COLORS


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


def _build_beta_history_svg(
    *,
    series_by_window: dict[str, tuple[list[pd.Timestamp], list[float]]],
    active_window: str,
    visible_windows: list[str] | None = None,
    current_delta_core: float | None,
    ticker: str = "",
) -> str:
    """SVG line chart of structural_delta over time, one line per visible window.

    ``series_by_window`` maps ``window_id`` -> (dates, deltas). The active window
    is always drawn (thicker and fully opaque). Any other window whose id is in
    ``visible_windows`` is layered in thinner and muted. Hidden windows appear
    in the legend as muted toggle links so the user can click to reveal them.

    All lines share one y-axis (structural delta units), so a "stock drifts
    upward" signal is visible regardless of which window is active.
    """
    if visible_windows is None:
        visible_windows = [active_window]
    visible_upper = {w.upper() for w in visible_windows}

    width = 720
    height = 240
    padding_left = 44
    padding_right = 24
    padding_top = 20
    padding_bottom = 28
    inner_w = width - padding_left - padding_right
    inner_h = height - padding_top - padding_bottom

    # Collect every delta/date across VISIBLE windows so axis bounds rescale
    # when the user toggles a window off. A hidden 3Y line shouldn't stretch
    # the y-axis of a 6M-only view.
    all_deltas: list[float] = []
    all_dates: list[pd.Timestamp] = []
    for window_id, (dates, deltas) in series_by_window.items():
        if window_id.upper() not in visible_upper:
            continue
        if dates and deltas and len(dates) == len(deltas):
            all_deltas.extend(deltas)
            all_dates.extend(dates)

    if not all_deltas:
        return "<p>No beta history data available.</p>"

    # X scale uses the full date range across all windows so different-length
    # series align correctly. 6M has fewer points than 3Y; both must share x.
    min_date = min(all_dates)
    max_date = max(all_dates)
    date_span_days = max((max_date - min_date).days, 1)

    def x_at(date_value: pd.Timestamp) -> float:
        offset_days = (date_value - min_date).days
        return padding_left + (offset_days / date_span_days) * inner_w

    # Y scale: deltas -> y position (anchor at 0 on the visible band)
    delta_lo = min(all_deltas + [0.0])
    delta_hi = max(all_deltas + [0.0])
    if current_delta_core is not None:
        delta_lo = min(delta_lo, current_delta_core)
        delta_hi = max(delta_hi, current_delta_core)
    if delta_hi == delta_lo:
        delta_hi = delta_lo + 1.0
    pad = (delta_hi - delta_lo) * 0.1
    delta_lo -= pad
    delta_hi += pad

    def y_at(value: float) -> float:
        return padding_top + (1.0 - (value - delta_lo) / (delta_hi - delta_lo)) * inner_h

    grid_zero = ""
    if delta_lo <= 0.0 <= delta_hi:
        grid_zero = (
            f"<line x1=\"{padding_left}\" y1=\"{y_at(0.0):.1f}\" "
            f"x2=\"{width - padding_right}\" y2=\"{y_at(0.0):.1f}\" "
            f"stroke=\"#bfb5a2\" stroke-width=\"1\" stroke-dasharray=\"3 3\" />"
        )
    grid_core = ""
    if current_delta_core is not None:
        grid_core = (
            f"<line x1=\"{padding_left}\" y1=\"{y_at(current_delta_core):.1f}\" "
            f"x2=\"{width - padding_right}\" y2=\"{y_at(current_delta_core):.1f}\" "
            f"stroke=\"#b26700\" stroke-width=\"1\" stroke-dasharray=\"4 2\" opacity=\"0.65\" />"
        )

    # SVG later elements paint above earlier ones, so render inactive windows
    # first and the active window last so it always sits on top. Only visible
    # windows draw lines; hidden windows still appear in the legend as toggle
    # links so the user can opt them back in.
    active_upper = (active_window or "").strip().upper()
    ordered_windows = [w for w in _STRUCTURAL_WINDOWS if w in series_by_window]
    draw_order = [
        w for w in ordered_windows
        if w.upper() != active_upper and w.upper() in visible_upper
    ] + [w for w in ordered_windows if w.upper() == active_upper]
    lines_html = ""
    for window_id in draw_order:
        dates, deltas = series_by_window[window_id]
        if not dates or not deltas or len(dates) != len(deltas):
            continue
        is_active = window_id.upper() == active_upper
        color = _WINDOW_COLORS.get(window_id.upper(), "#555555")
        width_px = 2.4 if is_active else 1.2
        opacity = "1.0" if is_active else "0.55"
        points = " ".join(f"{x_at(d):.1f},{y_at(v):.1f}" for d, v in zip(dates, deltas))
        lines_html += (
            f"<polyline points=\"{points}\" fill=\"none\" stroke=\"{color}\" "
            f"stroke-width=\"{width_px}\" opacity=\"{opacity}\" />"
        )

    # Build clickable toggle links: clicking a visible non-active window
    # removes it from `show=`; clicking a hidden window adds it. The active
    # window has no href - it's always drawn, so there's nothing to toggle.
    ticker_base = f"/ticker/{escape(ticker)}" if ticker else ""
    window_param = f"window={active_window.lower()}"
    legend_parts: list[str] = []
    for window_id in ordered_windows:
        upper = window_id.upper()
        is_active = upper == active_upper
        is_visible = upper in visible_upper
        color = _WINDOW_COLORS.get(upper, "#555555")
        font_weight = "600" if is_active else "400"
        marker = "&#9632;" if is_visible else "&#9633;"  # filled vs hollow square
        if is_active:
            label = f"{escape(window_id)} (active)"
            legend_parts.append(
                f"<span class=\"chart-legend-item\" "
                f"style=\"color:{color};font-weight:{font_weight}\">"
                f"{marker} {label}</span>"
            )
            continue
        # Toggle target: visible windows that are NOT the active one come out of
        # `show=` on click; hidden windows go in.
        new_show = {
            w.upper() for w in visible_windows
            if w.upper() != active_upper and w.upper() != upper
        } if is_visible else (
            {w.upper() for w in visible_windows if w.upper() != active_upper} | {upper}
        )
        show_param = ",".join(
            w.lower() for w in _STRUCTURAL_WINDOWS if w.upper() in new_show
        )
        action = "hide" if is_visible else "show"
        query = f"?{window_param}"
        if show_param:
            query += f"&show={show_param}"
        href = f"{ticker_base}{query}" if ticker_base else query
        title_text = f"Click to {action} the {window_id} line"
        legend_parts.append(
            f"<a class=\"chart-legend-item chart-legend-link\" href=\"{href}\" "
            f"title=\"{title_text}\" "
            f"style=\"color:{color};font-weight:{font_weight};"
            f"opacity:{'1.0' if is_visible else '0.55'}\">"
            f"{marker} {escape(window_id)}</a>"
        )
    legend_html = (
        "<p class=\"chart-legend\">" + " ".join(legend_parts) + "</p>" if legend_parts else ""
    )

    # Y-axis labels (lo / hi)
    y_labels = (
        f"<text x=\"{padding_left - 6}\" y=\"{y_at(delta_hi) + 4:.1f}\" "
        f"text-anchor=\"end\" font-size=\"11\" fill=\"#6f685c\">{delta_hi:.1f}</text>"
        f"<text x=\"{padding_left - 6}\" y=\"{y_at(delta_lo) + 4:.1f}\" "
        f"text-anchor=\"end\" font-size=\"11\" fill=\"#6f685c\">{delta_lo:.1f}</text>"
    )
    # Date range labels (first / last only)
    date_labels = (
        f"<text x=\"{padding_left}\" y=\"{height - 8}\" font-size=\"11\" fill=\"#6f685c\">"
        f"{min_date.strftime('%Y-%m-%d')}</text>"
        f"<text x=\"{width - padding_right}\" y=\"{height - 8}\" text-anchor=\"end\" "
        f"font-size=\"11\" fill=\"#6f685c\">{max_date.strftime('%Y-%m-%d')}</text>"
    )

    svg = (
        f"<svg viewBox=\"0 0 {width} {height}\" role=\"img\" aria-label=\"Rolling structural delta by window\">"
        f"<rect x=\"0\" y=\"0\" width=\"{width}\" height=\"{height}\" fill=\"#fffdf8\" rx=\"12\" ry=\"12\" />"
        f"{grid_zero}{grid_core}"
        f"{lines_html}"
        f"{y_labels}{date_labels}"
        "</svg>"
    )
    return legend_html + svg
