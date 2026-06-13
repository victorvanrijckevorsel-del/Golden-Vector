"""Lab drill-down: which weeks a miner beat/lagged the benchmark over time.

Render-only. Every number comes from the persisted episode + cell artifacts via
``lab_curve_data``; this module draws an SVG of the forward-alpha dots and formats
captions. No counting, rebasing, or rank math here.

Chart A (the hero) plots one dot per week = that week's forward H-week alpha vs
the chosen benchmark. The scenario weeks (the ones the table's % counts) are
highlighted; the share of highlighted dots above zero equals the table's raw
P(beat) by construction. Honesty is bound into the captions: forward-looking,
overlapping (effective N << dot count), conditional, survivor-only.
"""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from golden_vector.serve.column_help import help_term
from golden_vector.serve.lab_curve_data import LabCurveData
from golden_vector.serve.page_shell import _page_shell

_CONTEXT_COLOR = "#cfc6b8"
_BEAT_COLOR = "#1d6b32"
_LAG_COLOR = "#a11a1a"
_ZERO_COLOR = "#8a8170"

_BENCHMARK_BLURB = {
    "GDX": "GDX — the broad gold-miner ETF (large, established producers).",
    "GDXJ": "GDXJ — the junior-miner ETF (smaller, more volatile names).",
}


def _render_lab_curve_page(curve: LabCurveData) -> str:
    title = f"{curve.ticker or 'Ticker'} relative performance - Golden Vector"
    body: list[str] = []
    body.append("<p><a href=\"/lab\">&larr; Back to the Lab scenario table</a></p>")
    body.append(
        f"<h1>{escape(curve.ticker or '')} — relative performance vs "
        f"{escape(curve.benchmark)}</h1>"
    )

    if not curve.available:
        reason = {
            "CORRUPT": "Lab artifact is corrupt and could not be read.",
            "STALE": "Lab artifact was built by an older version (missing this "
            "horizon/benchmark). Rebuild it.",
        }.get(str(curve.error_status), "No persisted episodes for this ticker yet.")
        body.append(f"<div class=\"flash flash-warning\">{escape(reason)} "
                    "Rebuild: <code>python -m golden_vector.lab.conditional_dial</code>.</div>")
        return _page_shell(title, "".join(body), active_nav="lab")

    body.append(_render_controls(curve))
    body.append(_render_headline(curve))
    body.append(_render_chart_a(curve))
    body.append(_render_chart_b(curve))
    body.append(_render_glossary(curve))
    return _page_shell(title, "".join(body), active_nav="lab")


def _cell_field(curve: LabCurveData, name: str) -> Any:
    """Resolve a logical field to its actual wide-cell column for the benchmark.

    The persisted columns mix conventions on purpose — ``p_beat_{b}``,
    ``p_beat_{b}_shrunk``, ``median_alpha_{b}`` put the benchmark mid/suffix,
    while ``{b}_effective_n`` / ``{b}_wilson_low`` / ``{b}_insufficient_history``
    prefix it — so the mapping is explicit, never a single suffix rule.
    """

    b = curve.benchmark.lower()
    columns = {
        "p_beat": f"p_beat_{b}",
        "p_beat_shrunk": f"p_beat_{b}_shrunk",
        "median_alpha": f"median_alpha_{b}",
        "alpha_q10": f"alpha_q10_{b}",
        "alpha_q90": f"alpha_q90_{b}",
        "n_weeks": f"{b}_n_weeks",
        "effective_n": f"{b}_effective_n",
        "wilson_low": f"{b}_wilson_low",
        "wilson_high": f"{b}_wilson_high",
        "insufficient_history": f"{b}_insufficient_history",
    }
    cell = curve.cell or {}
    return cell.get(columns.get(name, name))


def _benchmark_insufficient(curve: LabCurveData) -> bool:
    flag = _cell_field(curve, "insufficient_history")
    # Missing flag (wholly-absent benchmark) -> treat as insufficient, never as
    # a usable cell with hidden numbers.
    return bool(flag) if flag is not None else True


def _render_controls(curve: LabCurveData) -> str:
    """Benchmark toggle (GDX | GDXJ) + horizon note; scenario stays fixed."""

    def href(benchmark: str) -> str:
        return (
            f"/lab/dial/{quote(curve.ticker, safe='')}"
            f"?scenario={quote(curve.scenario_bucket, safe='')}"
            f"&horizon={int(curve.horizon)}&benchmark={quote(benchmark, safe='')}"
        )

    toggle = []
    for benchmark in ("GDX", "GDXJ"):
        if benchmark == curve.benchmark:
            toggle.append(f"<span class=\"benchmark-toggle active\">{benchmark}</span>")
        else:
            toggle.append(
                f"<a class=\"benchmark-toggle\" href=\"{escape(href(benchmark), quote=True)}\">{benchmark}</a>"
            )
    blurb = _BENCHMARK_BLURB.get(curve.benchmark, "")
    return (
        "<section class=\"panel lab-curve-controls\">"
        f"<p><strong>Scenario:</strong> {escape(curve.scenario_label)} &nbsp;·&nbsp; "
        f"<strong>Look-ahead:</strong> {int(curve.horizon)} weeks</p>"
        f"<p><strong>Benchmark:</strong> {' '.join(toggle)} "
        f"<span class=\"hint\">{escape(blurb)}</span></p>"
        "</section>"
    )


def _render_headline(curve: LabCurveData) -> str:
    scenario_points = [p for p in curve.points if p["is_scenario"]]
    above = [p for p in scenario_points if p["beat"]]  # persisted decision, not re-derived
    if _benchmark_insufficient(curve) or len(scenario_points) == 0:
        return (
            "<section class=\"panel\">"
            f"<p>Not enough independent {escape(curve.benchmark)} history at "
            f"{int(curve.horizon)} weeks in this scenario to count a reliable rate — "
            "the dots below are shown for context only.</p>"
            "</section>"
        )
    raw = _cell_field(curve, "p_beat")
    shrunk = _cell_field(curve, "p_beat_shrunk")
    eff_n = _cell_field(curve, "effective_n")
    raw_pct = f"{float(raw) * 100:.1f}%" if raw is not None and raw == raw else "—"
    shrunk_pct = f"{float(shrunk) * 100:.1f}%" if shrunk is not None and shrunk == shrunk else "—"
    eff_text = f"{float(eff_n):.1f}" if eff_n is not None and eff_n == eff_n else "—"
    survivor = help_term(
        "surviving miners only",
        text="Only miners still trading today are included; delisted losers are "
        "missing, so real beat-rates were probably lower. Exploratory.",
    )
    overlap = help_term(
        f"Effective N = {eff_text}",
        text=f"Each dot looks forward {int(curve.horizon)} weeks, so neighbouring dots "
        "overlap and are not independent. The effective (independent) sample is far "
        "smaller than the number of dots — smaller N is less reliable.",
    )
    return (
        "<section class=\"panel lab-curve-headline\">"
        f"<p><strong>{raw_pct}</strong> of the highlighted scenario weeks beat "
        f"{escape(curve.benchmark)} over the next {int(curve.horizon)} weeks "
        f"— {survivor}, exploratory. {overlap} independent episodes.</p>"
        f"<p class=\"hint\">Ranked/smoothed estimate: {shrunk_pct}. "
        f"Counted weeks: {len(scenario_points)} ({len(above)} above zero).</p>"
        "</section>"
    )


def _render_chart_a(curve: LabCurveData) -> str:
    svg = _build_dots_svg(curve.points, horizon=int(curve.horizon), benchmark=curve.benchmark)
    highlight_caption = (
        f"Highlighted = weeks where gold WENT ON to {escape(_scenario_phrase(curve))} "
        f"over the FOLLOWING {int(curve.horizon)} weeks (a hindsight grouping you chose, "
        "not a signal available on that date)."
    )
    return (
        "<section class=\"panel lab-curve-chart\">"
        "<h2>Forward performance vs benchmark, week by week</h2>"
        f"{svg}"
        f"<p class=\"hint\">Each dot is one week: how {escape(curve.ticker)} did versus "
        f"{escape(curve.benchmark)} over the <strong>next {int(curve.horizon)} weeks</strong>. "
        "Above the line = beat the benchmark; below = lagged. Larger dots are the "
        "independent (non-overlapping) episodes.</p>"
        f"<p class=\"hint\">{highlight_caption}</p>"
        f"<p class=\"hint\">The most recent {int(curve.horizon)} weeks have no dot — their "
        "forward window has not completed yet.</p>"
        "</section>"
    )


def _scenario_phrase(curve: LabCurveData) -> str:
    label = curve.scenario_label.lower()
    return label if label else curve.scenario_bucket


def _build_dots_svg(points: list[dict[str, Any]], *, horizon: int, benchmark: str) -> str:
    usable = [p for p in points if p["alpha"] is not None and p["alpha"] == p["alpha"]]
    if len(usable) < 2:
        return "<p class=\"hint\">Not enough episodes to plot yet.</p>"
    alphas = [float(p["alpha"]) for p in usable]
    lo = min(alphas)
    hi = max(alphas)
    if lo == hi:
        hi = lo + 0.01
    width = 820
    height = 300
    left = 52
    right = 18
    top = 16
    bottom = height - 34
    gutter = 60  # reserved right band for the not-yet-complete forward window
    plot_right = width - right - gutter
    n = len(usable)

    def x_at(index: int) -> float:
        if n == 1:
            return left
        return left + index * (plot_right - left) / (n - 1)

    def y_at(alpha: float) -> float:
        return bottom - (alpha - lo) / (hi - lo) * (bottom - top)

    zero_y = y_at(0.0) if lo <= 0 <= hi else None
    parts: list[str] = []
    # Forward-window gutter: the last `horizon` weeks have no episode yet (their
    # forward window has not completed), so reserve + label that region rather
    # than letting the line run to the edge.
    parts.append(
        f"<rect x=\"{plot_right:.1f}\" y=\"{top:.1f}\" width=\"{width - right - plot_right:.1f}\" "
        f"height=\"{bottom - top:.1f}\" fill=\"#efe9dc\" fill-opacity=\"0.7\"/>"
        f"<line x1=\"{plot_right:.1f}\" y1=\"{top:.1f}\" x2=\"{plot_right:.1f}\" y2=\"{bottom:.1f}\" "
        f"stroke=\"{_CONTEXT_COLOR}\" stroke-dasharray=\"3 3\"/>"
        f"<text x=\"{plot_right + 4:.1f}\" y=\"{top + 10:.1f}\" font-size=\"8\" fill=\"#7a7263\">"
        f"+{int(horizon)}w</text>"
        f"<text x=\"{plot_right + 4:.1f}\" y=\"{top + 20:.1f}\" font-size=\"8\" fill=\"#7a7263\">"
        "pending</text>"
    )
    # zero baseline (across the data region only)
    if zero_y is not None:
        parts.append(
            f"<line x1=\"{left}\" y1=\"{zero_y:.1f}\" x2=\"{plot_right:.1f}\" "
            f"y2=\"{zero_y:.1f}\" stroke=\"{_ZERO_COLOR}\" stroke-dasharray=\"4 3\"/>"
            f"<text x=\"{left - 6}\" y=\"{zero_y + 3:.1f}\" text-anchor=\"end\" "
            "font-size=\"9\" fill=\"#5f584e\">0</text>"
        )
    # context dots first (so highlighted draw on top)
    for index, point in enumerate(usable):
        if point["is_scenario"]:
            continue
        cx = x_at(index)
        cy = y_at(float(point["alpha"]))
        parts.append(
            f"<circle cx=\"{cx:.1f}\" cy=\"{cy:.1f}\" r=\"1.4\" fill=\"{_CONTEXT_COLOR}\"/>"
        )
    for index, point in enumerate(usable):
        if not point["is_scenario"]:
            continue
        cx = x_at(index)
        alpha = float(point["alpha"])
        cy = y_at(alpha)
        color = _BEAT_COLOR if point["beat"] else _LAG_COLOR  # persisted decision
        radius = 3.2 if point["is_anchor"] else 2.0
        parts.append(
            f"<circle cx=\"{cx:.1f}\" cy=\"{cy:.1f}\" r=\"{radius}\" fill=\"{color}\" "
            f"fill-opacity=\"0.85\"><title>{escape(str(point['date']))}: "
            f"{alpha * 100:+.1f}% vs {escape(benchmark)}</title></circle>"
        )
    # date ticks (first, middle, last episode start week)
    for index in (0, n // 2, n - 1):
        parts.append(
            f"<text x=\"{x_at(index):.1f}\" y=\"{bottom + 16}\" text-anchor=\"middle\" "
            f"font-size=\"9\" fill=\"#5f584e\">{escape(str(usable[index]['date']))}</text>"
        )
    parts.append(
        f"<text x=\"{left}\" y=\"{top - 4}\" font-size=\"10\" fill=\"#5f584e\">"
        f"alpha vs {escape(benchmark)} (next {int(horizon)} wks)</text>"
    )
    return (
        f"<svg class=\"option-chart-svg lab-dots-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Forward alpha vs benchmark by week; scenario weeks highlighted\">"
        f"{''.join(parts)}"
        "</svg>"
    )


def _render_chart_b(curve: LabCurveData) -> str:
    """Collapsed 'different measure' relative-strength line — context, not the
    counted number above."""

    points = curve.relstrength_points
    line = _build_line_svg(points, benchmark=curve.benchmark)
    return (
        "<details class=\"method-disclosure lab-relstrength\">"
        "<summary>Different measure: overall relative strength (every week)</summary>"
        f"<p class=\"hint\">This line answers a DIFFERENT question than the chart above: "
        f"it tracks {escape(curve.ticker)} versus {escape(curve.benchmark)} across EVERY "
        "week (rebased to 100 at the start), not just your gold scenario. Rising = beating "
        "the benchmark lately. Trust the top chart for the counted scenario probability; "
        "this one is just for feel.</p>"
        f"{line}"
        "</details>"
    )


def _build_line_svg(points: list[dict[str, Any]], *, benchmark: str) -> str:
    values = [
        (str(p["date"]), float(p["relstrength"]))
        for p in points
        if p.get("relstrength") is not None and p["relstrength"] == p["relstrength"]
    ]
    if len(values) < 2:
        return "<p class=\"hint\">Not enough history to plot the relative-strength line.</p>"
    levels = [v for _d, v in values]
    lo = min(levels)
    hi = max(levels)
    if lo == hi:
        hi = lo + 1.0
    width = 820
    height = 200
    left = 48
    right = 18
    top = 14
    bottom = height - 30
    n = len(values)

    def x_at(index: int) -> float:
        return left + index * (width - left - right) / (n - 1)

    def y_at(level: float) -> float:
        return bottom - (level - lo) / (hi - lo) * (bottom - top)

    coords = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, (_d, v) in enumerate(values))
    base_y = y_at(100.0) if lo <= 100 <= hi else None
    base_line = (
        f"<line x1=\"{left}\" y1=\"{base_y:.1f}\" x2=\"{width - right}\" y2=\"{base_y:.1f}\" "
        f"stroke=\"{_ZERO_COLOR}\" stroke-dasharray=\"4 3\"/>"
        f"<text x=\"{left - 6}\" y=\"{base_y + 3:.1f}\" text-anchor=\"end\" font-size=\"9\" "
        "fill=\"#5f584e\">100</text>"
        if base_y is not None
        else ""
    )
    ticks = "".join(
        f"<text x=\"{x_at(i):.1f}\" y=\"{bottom + 14}\" text-anchor=\"middle\" "
        f"font-size=\"9\" fill=\"#5f584e\">{escape(values[i][0])}</text>"
        for i in (0, n // 2, n - 1)
    )
    return (
        f"<svg class=\"option-chart-svg lab-relstrength-svg\" viewBox=\"0 0 {width} {height}\" "
        f"role=\"img\" aria-label=\"Relative strength vs {escape(benchmark)} rebased to 100\">"
        f"{base_line}"
        f"<polyline points=\"{coords}\" fill=\"none\" stroke=\"#2f6f6d\" stroke-width=\"2\"/>"
        f"{ticks}"
        f"<text x=\"{left}\" y=\"{top - 2}\" font-size=\"10\" fill=\"#5f584e\">"
        f"{escape(benchmark)} = 100 at start</text>"
        "</svg>"
    )


def _render_glossary(curve: LabCurveData) -> str:
    return (
        "<details class=\"method-disclosure\"><summary>How to read this</summary>"
        "<p>This chart is the evidence behind the scenario table: the share of the "
        "highlighted (counted) dots above zero is exactly the table's raw P(beat) for "
        "this benchmark. It is counted history conditional on the gold scenario you "
        "chose — not a forecast.</p>"
        "<p>Because each dot looks forward several months, neighbouring dots share most "
        "of their window and move together; that smoothness is overlap, not extra proof. "
        "Only miners still trading today are included (survivor-only), so the real "
        "numbers were probably a little worse. The Lab is exploratory.</p>"
        "</details>"
    )
