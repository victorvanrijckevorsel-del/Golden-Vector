"""Lab drill-down: which weeks a miner beat/lagged the benchmark over time.

Render-only. Every number comes from the persisted episode + cell artifacts via
``lab_curve_data``; this module draws an SVG of the forward-alpha dots and formats
captions. No model aggregation, shrinkage, ratio, rebasing, or rank math here —
only display-only counts (e.g. how many scenario weeks beat) over already-resolved rows.

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

from golden_vector.common.numeric import is_missing
from golden_vector.lab.conditional_dial import BUCKET_SHORT_LABELS
from golden_vector.serve.column_help import help_term
from golden_vector.serve.lab_curve_data import LabCurveData
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import page_header
from golden_vector.serve.ui.status import notice

_CONTEXT_CLASS = "series-strip"
_BEAT_CLASS = "series-beat"
_LAG_CLASS = "series-lag"
_ZERO_CLASS = "series-zeroline"

_BENCHMARK_BLURB = {
    "GDX": "GDX — the broad gold-miner ETF (large, established producers).",
    "GDXJ": "GDXJ — the junior-miner ETF (smaller, more volatile names).",
}

# Friendly display text for the build-decided archetype codes (display constants — serve
# echoes the persisted `archetype` string; it never re-derives the box).
_ARCHETYPE_BLURB = {
    "CONVEX": "cushioned when gold falls, explosive when it rises (the dream)",
    "HEDGE": "holds up when gold falls; lags rallies",
    "TORQUE": "rips when gold rises; painful when it falls",
    "DEAD_WEIGHT": "lags both ways",
}


def _beh_x(value: Any) -> str:
    """Format a capture ratio as a multiple, e.g. 0.50× / 2.00×; '—' if missing."""
    return "—" if is_missing(value) else f"{float(value):.2f}×"


def _beh_pct(value: Any) -> str:
    """Format a fraction as a whole percent for display; '—' if missing."""
    return "—" if is_missing(value) else f"{float(value) * 100:.0f}%"


def _beh_int(value: Any) -> str:
    return "—" if is_missing(value) else f"{float(value):.0f}"


def _beh_signed(value: Any) -> str:
    """Signed plain number (convexity is a DIFFERENCE of two multiples, not a multiple)."""
    return "—" if is_missing(value) else f"{float(value):+.2f}"


def _beh_dec(value: Any) -> str:
    """Two-decimal number (e.g. an FDR q-value); '—' if missing."""
    return "—" if is_missing(value) else f"{float(value):.2f}"


def _present(value: Any) -> bool:
    """A persisted label is present only if it's not None and not NaN (a persisted None
    round-trips as truthy float nan) and not blank — so an unconfirmed/absent label is
    never rendered as a settled value. Uses the shared missing-value check (one copy)."""
    if is_missing(value):
        return False
    return str(value).strip() != "" and str(value).lower() != "nan"


def _beh_label(value: Any) -> str:
    """Render a persisted enum label safely: the label text, or an em dash when it is
    absent/NaN — never literal 'nan' (mirrors the archetype guard for trend labels)."""
    return escape(str(value)) if _present(value) else "—"


def _render_behaviour(curve: LabCurveData) -> str:
    """The symmetric Behaviour panel: capture/archetype (vs gold), peer rank (vs miners),
    and behaviour-change (trend) for the selected scenario. Pure render of build-computed,
    persisted fields — no arithmetic, no re-derivation. Absent/stale degrades the PANEL."""

    status = curve.behavior_status
    if status is not None:
        msg = {
            "MISSING": "Behaviour layer not built yet. Rebuild: "
            "<code>python -m golden_vector.lab.behavior_engine</code>.",
            "CORRUPT": "Behaviour artifacts are unreadable. Rebuild the behaviour layer.",
            "STALE": "Behaviour artifacts are stale (config or spine changed). Rebuild "
            "the behaviour layer.",
            "EMPTY": "Behaviour layer built but has no rows yet. Rebuild the behaviour layer.",
        }.get(str(status), "Behaviour layer unavailable.")
        # Name the failing artifact when serve isolated it, so an operator knows which
        # frame to look at (capture / peer / trend) rather than rebuilding blind.
        artifact = getattr(curve, "behavior_artifact", None)
        detail = f" (<code>{escape(str(artifact))}</code> frame)" if artifact else ""
        return (
            "<section class=\"panel\"><h2>Behaviour</h2>"
            f"<p class=\"hint\">{msg}{detail}</p></section>"
        )

    cards: list[str] = []

    # --- Capture / archetype (vs GOLD, at the default capture horizon) ---
    cap = curve.capture
    cap_h = int(curve.capture_horizon)
    if cap is not None:
        confirmed = cap.get("archetype")
        all_rows = cap.get("archetype_all_rows")
        if _present(confirmed):
            blurb = _ARCHETYPE_BLURB.get(str(confirmed), "")
            badge = f"<strong>{escape(str(confirmed))}</strong> — {escape(blurb)}"
        elif _present(all_rows):
            badge = (
                f"{escape(str(all_rows))} <span class=\"hint\">(not confirmed by the "
                "independent-episode cross-check)</span>"
            )
        else:
            badge = "<span class=\"hint\">not enough independent history to place a box</span>"
        cstatus = str(cap.get("capture_status") or "")
        thin_note = (
            f"<p class=\"hint\">⚠ a side is too thin or invalid to rely on ({escape(cstatus)}) "
            "— read the multiples with caution.</p>"
            if cstatus and cstatus != "OK"
            else ""
        )
        cards.append(
            "<div class=\"beh-card\">"
            f"<h3>Capture vs gold ({cap_h}-week)</h3>"
            f"<p class=\"beh-badge\">{badge}</p>"
            "<p>Takes <strong>" + _beh_x(cap.get("down_capture_mean")) + "</strong> of "
            "gold's <em>fall</em> · <strong>" + _beh_x(cap.get("up_capture_mean"))
            + "</strong> of its <em>rise</em> · convexity <strong>"
            + _beh_signed(cap.get("convexity")) + "</strong></p>"
            + "<p class=\"hint\">Evidence: ~" + _beh_int(cap.get("down_effective_n"))
            + " independent fall episodes · ~" + _beh_int(cap.get("up_effective_n"))
            + " rise episodes.</p>"
            + thin_note
            + "<p class=\"hint\">Lower fall-capture = better hedge; higher rise-capture = "
            "more torque; convexity &gt; 0 = the convex sweet spot. The box is grounded at "
            f"the {cap_h}-week horizon, independent of the look-ahead above.</p>"
            "</div>"
        )
    else:
        cards.append(
            "<div class=\"beh-card\"><h3>Capture vs gold</h3>"
            f"<p class=\"hint\">No capture history for {escape(curve.ticker)} at "
            f"{cap_h} weeks.</p></div>"
        )

    # --- Peer rank (vs OTHER miners), both directions ---
    def _peer_line(label: str, row: dict[str, Any] | None) -> str:
        if row is None:
            return f"<li>{escape(label)}: <span class=\"hint\">no usable peer pool</span></li>"
        if str(row.get("peer_status")) != "OK":
            return (
                f"<li>{escape(label)}: <span class=\"hint\">too few independent episodes "
                "to rank confidently</span></li>"
            )
        return (
            f"<li>{escape(label)}: typically better than "
            f"<strong>{_beh_int(row.get('peer_percentile_median'))}%</strong> of miners "
            f"(top-quartile {_beh_pct(row.get('top_quartile_rate'))} of the time, "
            f"~{_beh_int(row.get('peer_effective_n'))} independent episodes)</li>"
        )

    cards.append(
        "<div class=\"beh-card\">"
        f"<h3>Vs other miners ({int(curve.horizon)}-week)</h3>"
        "<ul class=\"beh-list\">"
        + _peer_line("When gold fell", curve.peer_down)
        + _peer_line("When gold rose", curve.peer_up)
        + "</ul>"
        "<p class=\"hint\">Was it historically one of the stronger miners in that move? "
        "Point-in-time, survivor-only — describes the past, not a recommendation.</p>"
        "</div>"
    )

    # --- Behaviour change (trend) for the SELECTED scenario ---
    tr = curve.behavior_trend
    scen = escape(curve.scenario_label or curve.scenario_bucket)
    if tr is not None and str(tr.get("trend_status")) == "OK":
        beat = _beh_label(tr.get("trend_label"))
        alpha = _beh_label(tr.get("alpha_trend_label"))
        trend_html = (
            f"<p>Beat-rate: <strong>{beat}</strong> "
            f"(recent {_beh_pct(tr.get('recent_p_beat_raw'))} of "
            f"{_beh_int(tr.get('recent_anchor_n'))} vs older "
            f"{_beh_pct(tr.get('older_p_beat_raw'))} of {_beh_int(tr.get('older_anchor_n'))} "
            f"independent episodes beat {escape(curve.benchmark)}; "
            f"could only catch a change &gt; {_beh_int(tr.get('mde_80pct_pp'))}pp)</p>"
            f"<p>Win-size: <strong>{alpha}</strong> "
            "<span class=\"hint\">(descriptive trend in past win size)</span></p>"
            f"<p class=\"hint\">FDR q={_beh_dec(tr.get('trend_q_value'))} within a family of "
            f"{_beh_int(tr.get('trend_fdr_family_size'))} miners tested in this scenario.</p>"
        )
    elif tr is not None:
        trend_html = (
            "<p class=\"hint\">Not enough independent recent vs older episodes in this "
            "scenario to judge a change (the honest default).</p>"
        )
    else:
        trend_html = (
            f"<p class=\"hint\">No behaviour-change record for this scenario at "
            f"{int(curve.trend_horizon)} weeks.</p>"
        )
    cards.append(
        "<div class=\"beh-card\">"
        f"<h3>Behaviour change — {scen} ({int(curve.trend_horizon)}-week)</h3>"
        + trend_html
        + "<p class=\"hint\">Recent vs older split on independent episodes; the bold label "
        "is decided on BOTH the raw and the peer-adjusted recent-vs-older rates and must "
        "survive a per-scenario false-discovery correction. NO_CHANGE_DETECTED means "
        f"undetected, not proven stable. Read at the {int(curve.trend_horizon)}-week horizon "
        "(the honest trend default), independent of the look-ahead above.</p>"
        "</div>"
    )

    return (
        "<section class=\"panel lab-behaviour\">"
        "<h2>Behaviour — both directions</h2>"
        "<div class=\"beh-grid\">" + "".join(cards) + "</div>"
        "<p class=\"hint\">Exploratory, survivor-only (failed miners absent) — describes "
        "the past, not a forecast.</p>"
        "</section>"
    )


def _render_lab_curve_page(curve: LabCurveData) -> str:
    title = f"{curve.ticker or 'Ticker'} relative performance - Golden Vector"
    body: list[str] = []
    body.append(
        "<p class=\"back-link\"><a href=\"/lab\">&larr; Back to the Lab scenario table</a></p>"
    )
    body.append(
        page_header(
            f"{curve.ticker or ''} — relative performance vs {curve.benchmark}"
        )
    )

    if not curve.available:
        status = str(curve.error_status)
        reason_map = {
            "CORRUPT": "Lab artifact is corrupt and could not be read.",
            "EMPTY": "Lab artifact built but contains no rows (empty universe).",
            "STALE": "Lab artifact was built by an older version (missing this "
            "horizon/benchmark). Rebuild it.",
            "META_MISSING": "Lab metadata file is missing — the artifact's health "
            "can't be verified. Rebuild it.",
            "META_CORRUPT": "Lab metadata file is unreadable. Rebuild it.",
            "CELLS_MISSING": "Lab scenario-cells artifact is missing (the profile, "
            "win-rate and headline numbers all come from it). Rebuild it.",
            "CELLS_CORRUPT": "Lab scenario-cells artifact is corrupt and could not "
            "be read. Rebuild it.",
            "CELLS_EMPTY": "Lab scenario-cells artifact is empty (no rows). Rebuild it.",
            "CELLS_STALE": "Lab scenario-cells artifact was built by an older "
            "version (missing columns). Rebuild it.",
            "UNKNOWN_SCENARIO": (
                f"Unknown gold scenario “{curve.scenario_bucket}”. Choose one "
                "of: gold_down_big, gold_down, gold_flat, gold_up, gold_up_big."
            ),
        }
        reason = reason_map.get(status, "No persisted episodes for this ticker yet.")
        # A mistyped scenario is a URL problem, not a build problem — don't tell the
        # operator to rebuild for it.
        rebuild = "" if status == "UNKNOWN_SCENARIO" else (
            " Rebuild: <code>python -m golden_vector.lab.conditional_dial</code>."
        )
        # Plan 10.5 mapping: corrupt/unreadable artifacts are danger; STALE /
        # CELLS_STALE are freshness states and stay warning, as do empty
        # builds, URL problems, and simply-absent episode data.
        # UNKNOWN_SCENARIO carries no rebuild action.
        danger_statuses = ("CORRUPT", "META_MISSING", "META_CORRUPT", "CELLS_MISSING", "CELLS_CORRUPT")
        tone = "danger" if status in danger_statuses else "warning"
        body.append(notice(tone, f"{escape(reason)}{rebuild}"))
        return _page_shell(title, "".join(body), active_nav="lab")

    body.append(_render_controls(curve))
    body.append(_render_profile(curve))  # hero: behaviour across all gold scenarios
    body.append(_render_behaviour(curve))  # symmetric capture / peer / behaviour-change
    body.append(_render_headline(curve))
    body.append(_render_winrate_bar(curve))  # clear within-scenario summary
    body.append(_render_distribution(curve))  # spread of outcomes (magnitude)
    body.append(_render_chart_a(curve))  # the week-by-week dots, collapsed
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


def _render_tilt_label(curve: LabCurveData) -> str:
    """The auto gold-tilt characterization (v2). Serve ONLY chooses display text
    from the persisted ``profile_label`` + ``profile_label_status`` — it never
    re-derives the tilt or re-decides the threshold (the literal category words
    live in the build, not here). Horizon-scoped wording, coverage basis shown."""

    status = curve.profile_label_status
    hz = int(curve.horizon)
    bench = escape(curve.benchmark)
    ticker = escape(curve.ticker)
    if status == "OK" and curve.profile_label:
        # Coverage basis = the TILT-PARTITION counts the build averaged over (read
        # from the persisted artifact), not the structural chart counts.
        down = curve.profile_basis_down
        up = curve.profile_basis_up
        dn, upm = curve.profile_down_mean, curve.profile_up_mean
        tilt, thr = curve.profile_tilt, curve.profile_tilt_threshold
        # Transparent derivation: the label sits directly above the numbers it comes
        # from (down-side vs up-side beat rate -> tilt, against the threshold). These
        # are persisted values formatted for display — no decision is made here.
        derivation = ""
        if None not in (dn, upm, tilt, thr):
            derivation = (
                f"down-side beat rate {float(dn) * 100:.0f}% vs up-side "
                f"{float(upm) * 100:.0f}% (tilt {float(tilt):+.2f}, threshold "
                f"{float(thr):.2f}); "
            )
        return (
            "<p class=\"profile-tilt\"><strong>"
            f"{hz}-week historical tilt: {escape(curve.profile_label)}</strong> "
            f"<span class=\"hint\">{derivation}based on {down} usable down scenario(s) and "
            f"{up} usable up scenario(s) at {hz}w vs {bench}. "
            f"{escape(curve.profile_caveat)}</span></p>"
        )
    if status == "INSUFFICIENT_CROSS_SCENARIO_HISTORY":
        return (
            "<p class=\"profile-tilt hint\">Not enough cross-scenario history to "
            f"characterize {ticker}'s {hz}-week tilt vs {bench} yet (needs countable "
            "down AND up scenarios).</p>"
        )
    if status == "MISSING_COMPONENTS":
        return (
            "<p class=\"profile-tilt hint\">No countable down/up scenario history to "
            f"characterize {ticker} at {hz}w vs {bench} yet.</p>"
        )
    # UNAVAILABLE: the profile artifact is absent/stale — degrade silently to the
    # chart (no fabricated label).
    return ""


def _render_profile(curve: LabCurveData) -> str:
    """Hero: how the miner behaves vs the benchmark across ALL gold scenarios at
    the selected horizon, with the auto tilt-label (v2) above it. The shape is the
    story; gaps where a scenario had too little history."""

    pts = curve.profile_points
    usable = [p for p in pts if p["usable"]]
    if not pts or not usable:
        return (
            "<section class=\"panel\"><h2>Gold profile</h2>"
            f"{_render_tilt_label(curve)}"
            f"<p class=\"hint\">No countable cross-scenario history for "
            f"{escape(curve.ticker)} at {int(curve.horizon)} weeks yet.</p></section>"
        )
    down = curve.profile_usable_down  # counted in the loader, not here
    up = curve.profile_usable_up
    # A "down-then-up slope" read requires BOTH a usable down AND a usable up
    # scenario (else there is no down-vs-up to compare) AND an adjacent usable pair
    # (a connecting line is actually drawn). A one-sided profile must NEVER imply
    # "held up better when gold fell" — there is no down bucket to support it.
    has_segment = any(pts[i]["usable"] and pts[i + 1]["usable"] for i in range(len(pts) - 1))
    two_sided = down >= 1 and up >= 1
    if two_sided and has_segment:
        shape = (
            "Above the 50% line = beat more often than not; a down-then-up slope means "
            "it held up better when gold fell."
        )
    elif two_sided:
        shape = (
            "Above the 50% line = beat more often than not; compare the down dot(s) to the "
            "up dot(s) (the scenarios between had too little history to connect)."
        )
    else:
        if down >= 1:
            side_msg = "Only down-side gold scenarios had countable history here"
        elif up >= 1:
            side_msg = "Only up-side gold scenarios had countable history here"
        else:
            side_msg = "Only the flat gold scenario had countable history here"
        shape = (
            "Above the 50% line = beat more often than not. " + side_msg + ", so there "
            "isn't enough to compare how it behaves when gold falls versus rises."
        )
    svg = _build_profile_svg(
        pts, ticker=curve.ticker, benchmark=curve.benchmark, horizon=int(curve.horizon)
    )
    return (
        "<section class=\"panel lab-profile\">"
        f"<h2>{escape(curve.ticker)} — how it behaved vs {escape(curve.benchmark)} as gold moved "
        f"({int(curve.horizon)}w)</h2>"
        f"{_render_tilt_label(curve)}"
        f"{svg}"
        f"<p class=\"hint\">Each point = how often {escape(curve.ticker)} actually beat "
        f"{escape(curve.benchmark)} over the next {int(curve.horizon)} weeks in that gold "
        "scenario — the counted (raw) rate; the ranked/smoothed version is on hover. Counted "
        f"history, surviving miners only, exploratory (not a forecast). {shape} "
        f"Based on {down} usable down scenario(s) and {up} usable up scenario(s) at "
        f"{int(curve.horizon)}w; empty slots had too few independent weeks to count.</p>"
        "</section>"
    )


def _build_profile_svg(
    points: list[dict[str, Any]], *, ticker: str, benchmark: str, horizon: int
) -> str:
    n = len(points)
    width, height = 700, 220
    left, right, top, bottom = 46, 18, 20, height - 38

    def x_at(i: int) -> float:
        return left if n <= 1 else left + i * (width - left - right) / (n - 1)

    def y_at(pct: float) -> float:
        return bottom - (pct / 100.0) * (bottom - top)

    parts: list[str] = []
    y50 = y_at(50.0)
    parts.append(
        f"<line x1=\"{left}\" y1=\"{y50:.1f}\" x2=\"{width - right}\" y2=\"{y50:.1f}\" "
        "class=\"series-strip\" stroke-dasharray=\"4 3\"/>"
        f"<text x=\"{left - 4}\" y=\"{y50 + 3:.1f}\" text-anchor=\"end\" font-size=\"9\" "
        "class=\"chart-strip-label\">50%</text>"
    )
    def _raw_pct(point: dict[str, Any]) -> float:
        return float(point["p_beat_raw"]) * 100

    for i in range(n - 1):
        a, b = points[i], points[i + 1]
        if a["usable"] and b["usable"]:
            parts.append(
                f"<line x1=\"{x_at(i):.1f}\" y1=\"{y_at(_raw_pct(a)):.1f}\" "
                f"x2=\"{x_at(i + 1):.1f}\" y2=\"{y_at(_raw_pct(b)):.1f}\" "
                "class=\"series-context\" stroke-width=\"2\"/>"
            )
    usable_n = 0
    for i, p in enumerate(points):
        x = x_at(i)
        if p["usable"]:
            usable_n += 1
            pct = _raw_pct(p)  # the counted (raw) rate — same basis as the win-rate bar
            y = y_at(pct)
            cls = "series-beat" if pct >= 50 else "series-warn"
            shr = f"{float(p['p_beat_shrunk']) * 100:.0f}%" if p["p_beat_shrunk"] is not None else "-"
            med = f"{float(p['median_alpha']) * 100:+.0f}%" if p["median_alpha"] is not None else "-"
            eff = p["effective_n"]
            eff_s = f"{float(eff):.1f}" if eff is not None and eff == eff else "-"
            parts.append(
                f"<circle cx=\"{x:.1f}\" cy=\"{y:.1f}\" r=\"5\" class=\"{cls}\">"
                f"<title>{escape(p['label'])}: beat {escape(benchmark)} {pct:.0f}% of weeks "
                f"(ranked/smoothed {shr}), median {med}, N={eff_s}</title></circle>"
                f"<text x=\"{x:.1f}\" y=\"{y - 9:.1f}\" text-anchor=\"middle\" font-size=\"9\" "
                f"class=\"chart-ink\">{pct:.0f}%</text>"
            )
        else:
            parts.append(
                f"<text x=\"{x:.1f}\" y=\"{bottom - 4:.1f}\" text-anchor=\"middle\" "
                "font-size=\"8\" class=\"series-zero\">no data</text>"
            )
        parts.append(
            f"<text x=\"{x:.1f}\" y=\"{bottom + 16:.1f}\" text-anchor=\"middle\" "
            f"font-size=\"9\" class=\"chart-strip-label\">{escape(BUCKET_SHORT_LABELS.get(p['bucket'], p['bucket']))}</text>"
        )
    parts.append(
        f"<text x=\"{left}\" y=\"{top - 6:.1f}\" font-size=\"10\" class=\"chart-strip-label\">"
        f"% of weeks {escape(ticker)} beat {escape(benchmark)}  ·  gold falling &rarr; rising</text>"
    )
    aria = (
        f"How often {escape(ticker)} beat {escape(benchmark)} over {int(horizon)} weeks "
        f"across gold scenarios; {usable_n} of {n} scenarios have countable history."
    )
    return (
        f"<svg class=\"option-chart-svg lab-profile-svg\" viewBox=\"0 0 {width} {height}\" "
        f"role=\"img\" aria-label=\"{aria}\">"
        f"{''.join(parts)}</svg>"
    )


def _render_winrate_bar(curve: LabCurveData) -> str:
    """Clear within-scenario summary: a filled bar = P(beat) for the selected
    scenario, replacing the dense dots as the headline read."""

    if _benchmark_insufficient(curve):
        return ""
    raw = _cell_field(curve, "p_beat")
    if raw is None or raw != raw:
        return ""
    pct = float(raw) * 100
    fill = min(100.0, max(0.0, pct))
    med = _cell_field(curve, "median_alpha")
    eff = _cell_field(curve, "effective_n")
    med_s = f"{float(med) * 100:+.0f}%" if med is not None and med == med else "-"
    eff_s = f"{float(eff):.1f}" if eff is not None and eff == eff else "-"
    return (
        "<section class=\"panel lab-winrate\">"
        f"<p><strong>In {escape(curve.scenario_label)} weeks, {escape(curve.ticker)} beat "
        f"{escape(curve.benchmark)} {pct:.0f}% of the time</strong> "
        f"(median {med_s} vs {escape(curve.benchmark)}, N={eff_s} independent weeks).</p>"
        f"<div class=\"winrate-bar\"><div class=\"winrate-fill\" style=\"width:{fill:.0f}%\"></div>"
        f"<span class=\"winrate-label\">{pct:.0f}%</span></div>"
        "</section>"
    )


def _render_headline(curve: LabCurveData) -> str:
    # Count over the SAME points Chart A plots (alpha present), so the headline's
    # "counted weeks / above zero" can't drift from the dots shown below.
    scenario_points = [
        p
        for p in curve.points
        if p["is_scenario"] and p["alpha"] is not None and p["alpha"] == p["alpha"]
    ]
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


def _render_distribution(curve: LabCurveData) -> str:
    """Distribution strip: each highlighted scenario week as a tick on a +/- axis, so
    the SPREAD of outcomes (how big the wins/losses were) is visible, not just the
    share that beat. Render-only — ticks are the raw persisted per-week alphas, the
    median marker is the persisted cell median; NO binning, counting, or averaging
    here (that would be serve-side analytics)."""

    if _benchmark_insufficient(curve):
        return ""
    # Plot in the SAME simple-return basis as the persisted median (alpha_simple),
    # so ticks and the median marker share one axis. Same scenario-week set the
    # headline counts (alpha_simple is non-null iff the log alpha is).
    scenario = [
        p
        for p in curve.points
        if p["is_scenario"]
        and p.get("alpha_simple") is not None
        and p["alpha_simple"] == p["alpha_simple"]  # not NaN
    ]
    if len(scenario) < 2:
        return ""
    median = _cell_field(curve, "median_alpha")  # persisted, simple-return basis
    svg = _build_distribution_svg(scenario, median=median, benchmark=curve.benchmark)
    return (
        "<section class=\"panel lab-dist\">"
        f"<h2>Spread of outcomes in {escape(curve.scenario_label)} weeks</h2>"
        f"{svg}"
        f"<p class=\"hint\">Each tick is one highlighted scenario week: how "
        f"{escape(curve.ticker)} did vs {escape(curve.benchmark)} over the next "
        f"{int(curve.horizon)} weeks (green = beat, red = lagged). The clustering shows "
        "where most outcomes landed; the marker is the median. Counted history, "
        "survivor-only, exploratory — not a forecast.</p>"
        "</section>"
    )


def _build_distribution_svg(
    scenario_points: list[dict[str, Any]], *, median: Any, benchmark: str
) -> str:
    """A 1-D strip: x = per-week SIMPLE-return alpha (alpha_simple), one tick per
    scenario week, zero baseline + the persisted (simple-return) median marked. Time
    is collapsed on purpose. Ticks and median share ONE basis so the marker sits with
    the ticks it summarizes."""

    alphas = [float(p["alpha_simple"]) for p in scenario_points]
    lo = min([*alphas, 0.0])  # always include zero so the baseline is on-axis
    hi = max([*alphas, 0.0])
    if lo == hi:
        hi = lo + 0.01
    width, height = 760, 92
    left, right, top = 42, 18, 16
    axis_y = 54
    plot_left, plot_right = left, width - right

    def x_at(alpha: float) -> float:
        return left + (alpha - lo) / (hi - lo) * (width - left - right)

    parts: list[str] = [
        f"<line x1=\"{left}\" y1=\"{axis_y}\" x2=\"{width - right}\" y2=\"{axis_y}\" "
        f"class=\"{_CONTEXT_CLASS}\"/>"
    ]
    zero_x = x_at(0.0)
    parts.append(
        f"<line x1=\"{zero_x:.1f}\" y1=\"{top}\" x2=\"{zero_x:.1f}\" y2=\"{axis_y + 7:.1f}\" "
        f"class=\"{_ZERO_CLASS}\" stroke-dasharray=\"4 3\"/>"
        f"<text x=\"{zero_x:.1f}\" y=\"{axis_y + 19:.1f}\" text-anchor=\"middle\" "
        "font-size=\"9\" class=\"chart-strip-label\">0</text>"
    )
    for point in scenario_points:
        alpha = float(point["alpha_simple"])
        x = x_at(alpha)
        cls = _BEAT_CLASS if point["beat"] else _LAG_CLASS  # persisted decision
        parts.append(
            f"<line x1=\"{x:.1f}\" y1=\"{top + 6:.1f}\" x2=\"{x:.1f}\" y2=\"{axis_y:.1f}\" "
            f"class=\"{cls}\" stroke-opacity=\"0.5\"><title>{escape(str(point['date']))}: "
            f"{alpha * 100:+.0f}% vs {escape(benchmark)}</title></line>"
        )
    median_label = ""
    if median is not None and median == median:
        # Clamp into the plot box: the cell median is over the cell's episode set,
        # which can differ slightly from the alpha-present scenario points shown, so
        # never let the marker draw off-canvas (and silently vanish). When it IS
        # outside the tick range, SAY so — a marker pinned to the edge must not be
        # read as the true position.
        raw_mx = x_at(float(median))
        mx = max(plot_left, min(plot_right, raw_mx))
        pinned = float(median) < lo or float(median) > hi
        median_label = f"median {float(median) * 100:+.0f}%" + (
            " (off scale)" if pinned else ""
        )
        parts.append(
            f"<path d=\"M {mx:.1f} {axis_y - 1:.1f} l -4 -7 l 8 0 z\" class=\"chart-ink\">"
            f"<title>{escape(median_label)}</title></path>"
            f"<text x=\"{mx:.1f}\" y=\"{top + 2:.1f}\" text-anchor=\"middle\" font-size=\"8\" "
            f"class=\"chart-ink\">{escape(median_label)}</text>"
        )
    # Axis end-labels (suppress the lo label when it coincides with the zero tick,
    # i.e. an all-positive spread, to avoid '0' and '+0%' colliding at the left edge).
    if lo < 0:
        parts.append(
            f"<text x=\"{left}\" y=\"{axis_y + 19:.1f}\" text-anchor=\"start\" font-size=\"8\" "
            f"class=\"chart-axis-label\">{lo * 100:+.0f}%</text>"
        )
    parts.append(
        f"<text x=\"{width - right}\" y=\"{axis_y + 19:.1f}\" text-anchor=\"end\" font-size=\"8\" "
        f"class=\"chart-axis-label\">{hi * 100:+.0f}%</text>"
    )
    aria = (
        f"Spread of {len(scenario_points)} scenario-week outcomes vs {escape(benchmark)} "
        f"from {lo * 100:+.0f}% to {hi * 100:+.0f}%"
        + (f"; {median_label}." if median_label else ".")
    )
    return (
        f"<svg class=\"option-chart-svg lab-dist-svg\" viewBox=\"0 0 {width} {height}\" "
        f"role=\"img\" aria-label=\"{aria}\">{''.join(parts)}</svg>"
    )


def _render_chart_a(curve: LabCurveData) -> str:
    svg = _build_dots_svg(curve.points, horizon=int(curve.horizon), benchmark=curve.benchmark)
    highlight_caption = (
        f"Highlighted = weeks where gold WENT ON to {escape(_scenario_phrase(curve))} "
        f"over the FOLLOWING {int(curve.horizon)} weeks (a hindsight grouping you chose, "
        "not a signal available on that date)."
    )
    # Collapsed by default: the dense week-by-week scatter is secondary to the
    # profile + win-rate + spread above; available on demand without cluttering.
    return (
        "<details class=\"panel lab-curve-chart\">"
        "<summary>When did it happen? — forward performance vs benchmark, week by week</summary>"
        f"{svg}"
        f"<p class=\"hint\">Each dot is one week: how {escape(curve.ticker)} did versus "
        f"{escape(curve.benchmark)} over the <strong>next {int(curve.horizon)} weeks</strong>. "
        "Above the line = beat the benchmark; below = lagged. Larger dots are the "
        "independent (non-overlapping) episodes.</p>"
        f"<p class=\"hint\">{highlight_caption}</p>"
        f"<p class=\"hint\">The most recent {int(curve.horizon)} weeks have no dot — their "
        "forward window has not completed yet.</p>"
        "</details>"
    )


def _scenario_phrase(curve: LabCurveData) -> str:
    label = curve.scenario_label.lower()
    return label if label else curve.scenario_bucket


def _build_dots_svg(points: list[dict[str, Any]], *, horizon: int, benchmark: str) -> str:
    # Plot the SIMPLE-return per-week outperformance (alpha_simple) — the SAME basis
    # as the distribution strip, win-rate bar, tilt label, and overview table, so the
    # whole drill-down speaks one return basis. Beat colour stays the persisted
    # decision (sign-invariant between log and simple, so the share above zero still
    # equals the table's raw P(beat)).
    usable = [
        p
        for p in points
        if p.get("alpha_simple") is not None and p["alpha_simple"] == p["alpha_simple"]
    ]
    if len(usable) < 2:
        return "<p class=\"hint\">Not enough episodes to plot yet.</p>"
    alphas = [float(p["alpha_simple"]) for p in usable]
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
        f"height=\"{bottom - top:.1f}\" class=\"chart-band\" fill-opacity=\"0.7\"/>"
        f"<line x1=\"{plot_right:.1f}\" y1=\"{top:.1f}\" x2=\"{plot_right:.1f}\" y2=\"{bottom:.1f}\" "
        f"class=\"{_CONTEXT_CLASS}\" stroke-dasharray=\"3 3\"/>"
        f"<text x=\"{plot_right + 4:.1f}\" y=\"{top + 10:.1f}\" font-size=\"8\" class=\"chart-axis-label\">"
        f"+{int(horizon)}w</text>"
        f"<text x=\"{plot_right + 4:.1f}\" y=\"{top + 20:.1f}\" font-size=\"8\" class=\"chart-axis-label\">"
        "pending</text>"
    )
    # zero baseline (across the data region only)
    if zero_y is not None:
        parts.append(
            f"<line x1=\"{left}\" y1=\"{zero_y:.1f}\" x2=\"{plot_right:.1f}\" "
            f"y2=\"{zero_y:.1f}\" class=\"{_ZERO_CLASS}\" stroke-dasharray=\"4 3\"/>"
            f"<text x=\"{left - 6}\" y=\"{zero_y + 3:.1f}\" text-anchor=\"end\" "
            "font-size=\"9\" class=\"chart-strip-label\">0</text>"
        )
    # context dots first (so highlighted draw on top)
    for index, point in enumerate(usable):
        if point["is_scenario"]:
            continue
        cx = x_at(index)
        cy = y_at(float(point["alpha_simple"]))
        parts.append(
            f"<circle cx=\"{cx:.1f}\" cy=\"{cy:.1f}\" r=\"1.4\" class=\"{_CONTEXT_CLASS}\"/>"
        )
    for index, point in enumerate(usable):
        if not point["is_scenario"]:
            continue
        cx = x_at(index)
        alpha = float(point["alpha_simple"])
        cy = y_at(alpha)
        cls = _BEAT_CLASS if point["beat"] else _LAG_CLASS  # persisted decision
        radius = 3.2 if point["is_anchor"] else 2.0
        parts.append(
            f"<circle cx=\"{cx:.1f}\" cy=\"{cy:.1f}\" r=\"{radius}\" class=\"{cls}\" "
            f"fill-opacity=\"0.85\"><title>{escape(str(point['date']))}: "
            f"{alpha * 100:+.1f}% vs {escape(benchmark)}</title></circle>"
        )
    # date ticks (first, middle, last episode start week)
    for index in (0, n // 2, n - 1):
        parts.append(
            f"<text x=\"{x_at(index):.1f}\" y=\"{bottom + 16}\" text-anchor=\"middle\" "
            f"font-size=\"9\" class=\"chart-strip-label\">{escape(str(usable[index]['date']))}</text>"
        )
    parts.append(
        f"<text x=\"{left}\" y=\"{top - 4}\" font-size=\"10\" class=\"chart-strip-label\">"
        f"outperformance vs {escape(benchmark)} (next {int(horizon)} wks)</text>"
    )
    return (
        f"<svg class=\"option-chart-svg lab-dots-svg\" viewBox=\"0 0 {width} {height}\" "
        "role=\"img\" aria-label=\"Forward outperformance vs benchmark by week; scenario weeks highlighted\">"
        f"{''.join(parts)}"
        "</svg>"
    )


def _render_chart_b(curve: LabCurveData) -> str:
    """Collapsed 'different measure' relative-strength line — context, not the
    counted number above."""

    points = curve.relstrength_points
    # EMPTY belongs with MISSING/CORRUPT: a relstrength artifact that exists but
    # holds no rows at all is a broken build, not a thin ticker, and silently
    # drawing a blank line hides it.
    if curve.relstrength_status in ("MISSING", "CORRUPT", "EMPTY"):
        line = (
            "<p class=\"hint\">Relative-strength artifact is "
            f"{escape(curve.relstrength_status.lower())} — rebuild the Lab artifacts "
            "(<code>python -m golden_vector.lab.conditional_dial</code>) to restore this "
            "context chart. The counted evidence above is unaffected.</p>"
        )
    else:
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
        f"class=\"{_ZERO_CLASS}\" stroke-dasharray=\"4 3\"/>"
        f"<text x=\"{left - 6}\" y=\"{base_y + 3:.1f}\" text-anchor=\"end\" font-size=\"9\" "
        "class=\"chart-strip-label\">100</text>"
        if base_y is not None
        else ""
    )
    ticks = "".join(
        f"<text x=\"{x_at(i):.1f}\" y=\"{bottom + 14}\" text-anchor=\"middle\" "
        f"font-size=\"9\" class=\"chart-strip-label\">{escape(values[i][0])}</text>"
        for i in (0, n // 2, n - 1)
    )
    return (
        f"<svg class=\"option-chart-svg lab-relstrength-svg\" viewBox=\"0 0 {width} {height}\" "
        f"role=\"img\" aria-label=\"Relative strength vs {escape(benchmark)} rebased to 100\">"
        f"{base_line}"
        f"<polyline points=\"{coords}\" fill=\"none\" class=\"series-context\" stroke-width=\"2\"/>"
        f"{ticks}"
        f"<text x=\"{left}\" y=\"{top - 2}\" font-size=\"10\" class=\"chart-strip-label\">"
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
