"""Scorecard page: does each tool actually work?

Render-only. Every verdict, statistic, and caveat comes from the persisted
artifact; this page formats and escapes. No arithmetic, no verdict logic.
"""

from __future__ import annotations

import json
import math
from html import escape
from typing import Any

from golden_vector.serve.column_help import help_term
from golden_vector.serve.page_shell import _page_shell
from golden_vector.serve.ui.components import (
    empty_state,
    page_header,
    section_heading,
    terminal_density,
)
from golden_vector.serve.ui.status import notice


def _verdict_class(verdict: Any) -> str:
    # A non-string / NaN verdict is a missing value, not a category: route it to
    # the neutral presentation instead of letting "nan" render as a verdict.
    if not isinstance(verdict, str):
        return "verdict-partial"
    v = verdict.strip().upper()
    if v in ("", "NAN", "NONE", "NA"):
        return "verdict-partial"
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
        numeric = float(value)
    except (TypeError, ValueError):
        return escape(str(value))
    if not math.isfinite(numeric):
        return "-"
    return f"{numeric:,.{decimals}f}"


def _render_scorecard_page(data) -> str:
    body = [page_header(
        "Evidence Scorecard",
        lead_html=(
            "<p>Each ranking the product shows is tested out of sample, walk-forward, "
            "against pass/fail bars locked before any number was computed. "
            "<strong>SUPPORTED</strong> means the ranking passed that historical test "
            "in the surviving-name universe; it is evidence, not proof. "
            "<strong>NOT SUPPORTED</strong> ships just as plainly.</p>"
        ),
    )]

    if not data.available:
        if data.error_status == "CORRUPT":
            msg = "Scorecard artifact is corrupt; rebuild it."
        elif data.error_status == "STALE":
            msg = "Scorecard artifact is from an older schema; rebuild it."
        else:
            msg = "Scorecard is not built yet."
        # Plan 10.5 mapping (same rule as the Lab pages): corrupt artifacts are
        # danger; stale and not-built are freshness/absence warnings.
        tone = "danger" if data.error_status == "CORRUPT" else "warning"
        body.append(notice(
            tone,
            f"{escape(msg)} "
            "Run <code>python -m golden_vector.lab.scorecard</code>.",
        ))
        return _page_shell(
            "Evidence Scorecard - Golden Vector Workspace",
            terminal_density("".join(body)),
            active_nav="scorecard",
        )

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
        body.append(notice("info", " ".join(banner_bits)))
    if meta.get("legacy_schema_assumed"):
        body.append(notice(
            "warning",
            "This scorecard artifact predates "
            "schema metadata. Its columns match the current reader, but rebuild it "
            "when convenient with <code>python -m golden_vector.lab.scorecard</code>.",
        ))
    for caveat in meta.get("caveats", []):
        body.append(notice("warning", escape(str(caveat))))

    body.append(section_heading("Tested today (backtest)"))
    if data.backtest_rows:
        for row in data.backtest_rows:
            body.append(_render_backtest_card(row))
    else:
        body.append(empty_state("No backtest claims are published."))

    body.append(section_heading("Accruing (forward-only - first verdicts ~2031)"))
    body.append(
        "<p class=\"hint\">Options and fundamentals can only be tested on data "
        "captured going forward; the recorder is accumulating it now.</p>"
    )
    if data.accruing_rows:
        for row in data.accruing_rows:
            body.append(_render_accruing_card(row))
    else:
        body.append(empty_state("No forward-only claims are accruing."))

    return _page_shell(
        "Evidence Scorecard - Golden Vector Workspace",
        terminal_density("".join(body)),
        active_nav="scorecard",
    )


def _share_percent(value: Any) -> float | None:
    """Scale a 0-1 share to percent; ``None`` when the writer emitted no value."""

    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric * 100


def _verdict_text(value: Any) -> str:
    """Verdict as displayable text; missing/NaN verdicts render blank, not 'nan'."""

    if not isinstance(value, str):
        return ""
    return "" if value.strip().upper() in ("NAN", "NONE", "NA") else value


def _render_backtest_card(row: dict[str, Any]) -> str:
    raw_verdict = row.get("verdict")
    verdict = _verdict_text(raw_verdict)
    cls = _verdict_class(raw_verdict)
    # A missing share stays missing ("-"); it is not 0% of periods.
    share = _share_percent(row.get("share_folds_directional"))
    share_part = "- of periods" if share is None else f"{_fmt(share, 0)}% of periods"
    stats = (
        f"{int(row.get('n_folds') or 0)} test periods · "
        f"IC {_fmt(row.get('mean_ic'))} · t {_fmt(row.get('nw_t'), 1)} · "
        f"{share_part} · "
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
        "<article class=\"panel scorecard-card\">"
        f"<div class=\"scorecard-verdict {cls}\">{escape(verdict)}</div>"
        f"<div class=\"scorecard-claim\">{escape(str(row.get('claim') or ''))}</div>"
        f"<div class=\"hint\">{stats} · {diag}</div>"
        f"{baseline_html}"
        "</article>"
    )


def _render_accruing_card(row: dict[str, Any]) -> str:
    return (
        "<article class=\"panel scorecard-card\">"
        f"<div class=\"scorecard-verdict verdict-accruing\">{escape(_verdict_text(row.get('verdict')))}</div>"
        f"<div class=\"scorecard-claim\">{escape(str(row.get('claim') or ''))}</div>"
        f"<div class=\"hint\">{escape(str(row.get('caveat') or ''))}</div>"
        "</article>"
    )
