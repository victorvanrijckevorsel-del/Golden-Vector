"""Scorecard page: does each tool actually work?

Render-only. Every verdict, statistic, and caveat comes from the persisted
artifact; this page formats and escapes. No arithmetic, no verdict logic.
"""

from __future__ import annotations

import json
from html import escape
from typing import Any

from golden_vector.serve.column_help import help_term
from golden_vector.serve.page_shell import _page_shell


def _verdict_class(verdict: str) -> str:
    v = verdict.upper()
    if v.startswith("SUPPORTED"):
        return "verdict-supported"
    if v.startswith("NOT SUPPORTED"):
        return "verdict-not-supported"
    if v.startswith("INCONCLUSIVE"):
        return "verdict-inconclusive"
    if v.startswith("ACCRUING"):
        return "verdict-accruing"
    return "verdict-partial"


def _fmt(value: Any, decimals: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return escape(str(value))


def _render_scorecard_page(data) -> str:
    body = ["<h1>Scorecard - Does each tool work?</h1>"]
    body.append(
        "<p>Each ranking the product shows is tested out of sample, walk-forward, "
        "against pass/fail bars locked before any number was computed. A "
        "<strong>SUPPORTED</strong> verdict means the ranking genuinely predicted "
        "what it claims; <strong>NOT SUPPORTED</strong> ships just as plainly.</p>"
    )

    if not data.available:
        msg = (
            "Scorecard artifact is corrupt; rebuild it."
            if data.error_status == "CORRUPT"
            else "Scorecard is not built yet."
        )
        body.append(
            f"<div class=\"flash flash-warning\">{escape(msg)} "
            "Run <code>python -m golden_vector.lab.scorecard</code>.</div>"
        )
        return _page_shell("Scorecard - Golden Vector Workspace", "".join(body), active_nav="scorecard")

    meta = data.meta
    built = str(meta.get("built_at_utc") or "")
    leak = meta.get("leak_canary") or {}
    banner_bits = []
    if built:
        banner_bits.append(f"Built {escape(built)}.")
    if leak:
        banner_bits.append(
            "Leak check passed (honest signal "
            f"{_fmt(leak.get('honest_mean_ic'))} vs future-peeking "
            f"{_fmt(leak.get('contaminated_mean_ic'))})."
        )
    if banner_bits:
        body.append(f"<div class=\"flash\">{' '.join(banner_bits)}</div>")
    for caveat in meta.get("caveats", []):
        body.append(f"<div class=\"flash flash-warning\">{escape(str(caveat))}</div>")

    body.append("<h2>Tested today (backtest)</h2>")
    for row in data.backtest_rows:
        body.append(_render_backtest_card(row))

    body.append("<h2>Accruing (forward-only - first verdicts ~2031)</h2>")
    body.append(
        "<p class=\"hint\">Options and fundamentals can only be tested on data "
        "captured going forward; the recorder is accumulating it now.</p>"
    )
    for row in data.accruing_rows:
        body.append(_render_accruing_card(row))

    return _page_shell("Scorecard - Golden Vector Workspace", "".join(body), active_nav="scorecard")


def _render_backtest_card(row: dict[str, Any]) -> str:
    verdict = str(row.get("verdict") or "")
    cls = _verdict_class(verdict)
    stats = (
        f"{int(row.get('n_folds') or 0)} test periods · "
        f"IC {_fmt(row.get('mean_ic'))} · t {_fmt(row.get('nw_t'), 1)} · "
        f"{_fmt((row.get('share_folds_directional') or 0) * 100, 0)}% of periods · "
        f"spread {_fmt(row.get('tercile_spread_mean'))} (t {_fmt(row.get('tercile_spread_t'), 1)})"
    )
    try:
        baseline_lines = json.loads(row.get("baseline_lines") or "[]")
    except json.JSONDecodeError:
        baseline_lines = []
    baseline_html = "".join(
        f"<p class=\"hint\">{escape(str(line))}</p>" for line in baseline_lines
    )
    # Diagnostics popover: why a low-ceiling outcome can still pass.
    diag = help_term(
        "method",
        text=(
            f"Fold-IC autocorrelation {_fmt(row.get('fold_ic_autocorr'))}; "
            f"outcome split-half consistency {_fmt(row.get('median_ceiling'))} "
            "(low = noisy per-name outcome). The verdict comes from consistent "
            "ordering across many independent periods, not a large per-name effect."
        ),
    )
    return (
        "<section class=\"panel scorecard-card\">"
        f"<div class=\"scorecard-verdict {cls}\">{escape(verdict)}</div>"
        f"<div class=\"scorecard-claim\">{escape(str(row.get('claim') or ''))}</div>"
        f"<div class=\"hint\">{stats} · {diag}</div>"
        f"{baseline_html}"
        "</section>"
    )


def _render_accruing_card(row: dict[str, Any]) -> str:
    return (
        "<section class=\"panel scorecard-card\">"
        f"<div class=\"scorecard-verdict verdict-accruing\">{escape(str(row.get('verdict') or ''))}</div>"
        f"<div class=\"scorecard-claim\">{escape(str(row.get('claim') or ''))}</div>"
        f"<div class=\"hint\">{escape(str(row.get('caveat') or ''))}</div>"
        "</section>"
    )
