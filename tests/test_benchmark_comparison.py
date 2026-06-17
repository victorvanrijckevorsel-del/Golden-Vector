"""Tier 2: window-aware stock-vs-GDX/GDXJ-vs-universe beta comparison.

Proves the comparison is genuinely re-based per window (the explicit requirement: the stock,
the ETFs, and the universe must share ONE window), that percentile/position math is correct
and tie-safe, that degraded inputs degrade per item, and that NONE of this math leaked into the
serve/chart layer.
"""

from pathlib import Path

import pandas as pd
import pytest

from golden_vector.model.benchmark_comparison import (
    _percentile,
    _position,
    resolve_beta_universe_comparison,
    resolve_beta_universe_comparisons_by_window,
)
from golden_vector.serve.charts import _build_beta_strip_svg
from golden_vector.serve.detail_panels import _render_beta_comparison_panel


def _universe() -> pd.DataFrame:
    # SUBJ's beta deliberately differs across windows so percentile must change with the window.
    return pd.DataFrame(
        {
            "ticker": ["AAA", "BBB", "CCC", "DDD", "SUBJ"],
            "down_beta_6m": [0.5, 1.0, 1.5, 2.0, 1.0],
            "up_beta_6m": [0.4, 0.9, 1.4, 1.9, 0.9],
            "down_beta_12m": [0.6, 1.1, 1.6, 2.1, 1.6],
            "up_beta_12m": [0.5, 1.0, 1.5, 2.0, 1.5],
            "down_beta_3y": [0.7, 1.2, 1.7, 2.2, 2.2],
            "up_beta_3y": [0.6, 1.1, 1.6, 2.1, 2.1],
        }
    )


def _benchmarks() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "benchmark_ticker": ["GDX", "GDXJ"],
            "benchmark_label": ["VanEck Gold Miners ETF", "VanEck Junior Gold Miners ETF"],
            "down_beta_6m": [1.3, 1.7],
            "up_beta_6m": [1.2, 1.6],
            "down_beta_12m": [1.4, 1.8],
            "up_beta_12m": [1.3, 1.7],
            "down_beta_3y": [1.35, 1.45],
            "up_beta_3y": [1.25, 1.35],
        }
    )


def test_comparison_is_window_aware_subject_and_percentile_change():
    """The same stock yields a different beta AND percentile under 6M vs 12M vs 3Y — proof the
    window switch re-bases the comparison rather than reusing one cached number."""
    uni, bench = _universe(), _benchmarks()
    c6 = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=bench)
    c12 = resolve_beta_universe_comparison(ticker="SUBJ", window_id="12M", universe_df=uni, benchmark_df=bench)
    c3y = resolve_beta_universe_comparison(ticker="SUBJ", window_id="3Y", universe_df=uni, benchmark_df=bench)

    assert c6.subject.down_beta == 1.0
    assert c12.subject.down_beta == 1.6
    assert c3y.subject.down_beta == 2.2
    # 6M: values <= 1.0 are {0.5, 1.0, 1.0} -> 3/5 = 60%
    assert c6.subject.down_percentile == 60.0
    # 12M: values <= 1.6 are {0.6, 1.1, 1.6, 1.6} -> 4/5 = 80%
    assert c12.subject.down_percentile == 80.0
    # 3Y: SUBJ is the max -> 100%
    assert c3y.subject.down_percentile == 100.0


def test_benchmarks_are_rebased_per_window():
    """GDX/GDXJ betas must come from the window's column, not a fixed core value."""
    uni, bench = _universe(), _benchmarks()
    c6 = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=bench)
    c12 = resolve_beta_universe_comparison(ticker="SUBJ", window_id="12M", universe_df=uni, benchmark_df=bench)
    gdx6 = next(m for m in c6.benchmarks if m.label == "GDX")
    gdx12 = next(m for m in c12.benchmarks if m.label == "GDX")
    assert gdx6.down_beta == 1.3
    assert gdx12.down_beta == 1.4
    assert {m.label for m in c6.benchmarks} == {"GDX", "GDXJ"}


def test_percentile_counts_ties_inclusively():
    values = sorted([0.5, 1.0, 1.0, 1.5, 2.0])
    # value equal to a tie cluster counts all at-or-below
    assert _percentile(values, 1.0) == 60.0
    assert _percentile(values, 0.4) == 0.0
    assert _percentile(values, 2.5) == 100.0
    assert _percentile([], 1.0) is None
    assert _percentile(values, None) is None


def test_position_clamps_and_handles_degenerate_domain():
    assert _position(1.5, (1.0, 2.0)) == 0.5
    assert _position(0.0, (1.0, 2.0)) == 0.0  # below domain -> clamped
    assert _position(3.0, (1.0, 2.0)) == 1.0  # above domain -> clamped
    assert _position(1.0, (1.0, 1.0)) == 0.5  # degenerate (all equal)
    assert _position(None, (1.0, 2.0)) is None
    assert _position(1.0, None) is None


def test_axis_domain_spans_universe_and_all_markers():
    uni, bench = _universe(), _benchmarks()
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=bench)
    low, high = c.down_domain
    # universe down_6m min 0.5, max 2.0; benchmarks 1.3/1.7 fall within -> domain is the universe span
    assert low == 0.5
    assert high == 2.0
    # every marker position is within [0, 1]
    for marker in [c.subject, *c.benchmarks]:
        assert 0.0 <= marker.down_pos <= 1.0


def test_missing_benchmark_columns_degrade_to_empty_but_universe_survives():
    """A core-only benchmark frame (no per-window cols) must yield no benchmark markers for 6M,
    yet still expose the universe distribution + subject — degrade per item, never crash."""
    uni = _universe()
    core_only = pd.DataFrame(
        {"benchmark_ticker": ["GDX"], "benchmark_label": ["VanEck"], "down_beta_core": [1.4], "up_beta_core": [1.3]}
    )
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=core_only)
    assert c.available is True
    assert c.benchmarks == ()
    assert c.subject.down_beta == 1.0


def test_degraded_universe_rows_excluded_from_distribution():
    """A ticker with NA beta for the window must drop out of the ranked distribution (canon:
    degraded data is excluded from rankings, not just flagged)."""
    uni = _universe()
    uni.loc[uni["ticker"] == "DDD", "down_beta_6m"] = pd.NA  # the would-be max
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=_benchmarks())
    assert c.universe_down_n == 4  # 5 miners minus the NA one
    assert c.down_domain[1] == 1.7  # max is now GDXJ (1.7), not the dropped 2.0


def test_subject_not_in_universe_still_shows_benchmarks_and_range():
    c = resolve_beta_universe_comparison(ticker="ZZZ", window_id="6M", universe_df=_universe(), benchmark_df=_benchmarks())
    assert c.available is True
    assert c.subject is None
    assert {m.label for m in c.benchmarks} == {"GDX", "GDXJ"}


def test_unsupported_window_is_unavailable():
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="9Q", universe_df=_universe(), benchmark_df=_benchmarks())
    assert c.available is False
    assert c.subject is None


def test_empty_inputs_degrade_cleanly():
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=None, benchmark_df=None)
    assert c.available is False
    assert c.benchmarks == ()


def test_by_window_resolves_every_selectable_window():
    out = resolve_beta_universe_comparisons_by_window(
        ticker="SUBJ", window_ids=("6M", "12M", "3Y"), universe_df=_universe(), benchmark_df=_benchmarks()
    )
    assert set(out) == {"6M", "12M", "3Y"}
    assert all(out[w].available for w in out)


def test_strip_chart_renders_subject_and_benchmark_markers():
    markers = [
        {"label": "SUBJ", "pos": 0.6, "value": 1.0, "is_subject": True},
        {"label": "GDX", "pos": 0.8, "value": 1.3, "is_subject": False},
    ]
    svg = _build_beta_strip_svg(axis_label="Down beta (6-month)", domain=(0.5, 2.0), markers=markers)
    assert "<svg" in svg
    assert "SUBJ" in svg and "GDX" in svg
    assert "stroke-dasharray" in svg  # benchmark tick is dashed
    assert "circle" in svg  # subject dot


def test_strip_chart_degrades_without_domain_or_markers():
    assert "No comparison data" in _build_beta_strip_svg(axis_label="x", domain=None, markers=[])
    assert "No comparison data" in _build_beta_strip_svg(
        axis_label="x", domain=(0.0, 1.0), markers=[]
    )


def test_by_window_keys_carry_correct_window_id_and_distinct_percentiles():
    """Stronger than checking dict keys: each resolved object must self-identify its window AND
    the subject's percentile must actually differ across windows (proof of re-basing)."""
    out = resolve_beta_universe_comparisons_by_window(
        ticker="SUBJ", window_ids=("6M", "12M", "3Y"), universe_df=_universe(), benchmark_df=_benchmarks()
    )
    assert out["6M"].window_id == "6M" and out["6M"].window_label == "6-month"
    assert out["12M"].window_id == "12M" and out["12M"].window_label == "12-month"
    assert out["3Y"].window_id == "3Y" and out["3Y"].window_label == "3-year"
    pcts = {out[w].subject.down_percentile for w in ("6M", "12M", "3Y")}
    assert len(pcts) == 3  # 60 / 80 / 100 — genuinely re-based, not one cached number


def test_subject_at_minimum_is_low_percentile():
    uni = pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "SUBJ"],
            "down_beta_6m": [2.0, 1.5, 1.0, 0.5],  # SUBJ is the strict minimum
            "up_beta_6m": [2.0, 1.5, 1.0, 0.5],
        }
    )
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=None)
    assert c.subject.down_percentile == 25.0  # only itself at-or-below -> 1/4
    assert c.subject.down_pos == 0.0  # at the domain minimum


def test_negative_betas_rank_and_position_correctly():
    """Betas can be negative (a stock that moves opposite gold). Percentile, domain, and position
    must all handle a negative domain."""
    uni = pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D", "SUBJ"],
            "down_beta_6m": [-0.5, 0.0, 0.5, 1.0, -0.3],
            "up_beta_6m": [-0.5, 0.0, 0.5, 1.0, -0.3],
        }
    )
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=None)
    assert c.down_domain == (-0.5, 1.0)
    # SUBJ is itself in the universe; values <= -0.3 are {-0.5, -0.3} -> 2/5 = 40%
    assert c.subject.down_percentile == 40.0
    # position: (-0.3 - (-0.5)) / (1.0 - (-0.5)) = 0.2 / 1.5
    assert c.subject.down_pos == pytest.approx(0.2 / 1.5)


def test_infinite_beta_is_excluded_from_universe():
    uni = _universe()
    uni.loc[uni["ticker"] == "DDD", "down_beta_6m"] = float("inf")
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="6M", universe_df=uni, benchmark_df=None)
    assert c.universe_down_n == 4  # inf row dropped, not poisoning the domain
    assert c.down_domain[1] != float("inf")


def test_degraded_row_excluded_but_healthy_control_retained_and_changes_percentile():
    """Exclusion must be SELECTIVE: degrading the universe max must drop ONLY that row and shift
    the subject's percentile accordingly — proving healthy rows are kept (canon: control row)."""
    healthy = resolve_beta_universe_comparison(
        ticker="SUBJ", window_id="6M", universe_df=_universe(), benchmark_df=None
    )
    assert healthy.subject.down_percentile == 60.0  # SUBJ=1.0; {0.5,1.0,1.0} of 5

    degraded_uni = _universe()
    degraded_uni.loc[degraded_uni["ticker"] == "DDD", "down_beta_6m"] = pd.NA  # drop the 2.0 max
    degraded = resolve_beta_universe_comparison(
        ticker="SUBJ", window_id="6M", universe_df=degraded_uni, benchmark_df=None
    )
    assert degraded.universe_down_n == 4  # exactly one row removed
    # SUBJ=1.0 vs surviving {0.5,1.0,1.0,1.5} -> 3/4 = 75% (healthy rows still counted)
    assert degraded.subject.down_percentile == 75.0


def test_render_panel_shows_window_label_percentile_and_benchmark_numbers():
    c = resolve_beta_universe_comparison(ticker="SUBJ", window_id="3Y", universe_df=_universe(), benchmark_df=_benchmarks())
    html = _render_beta_comparison_panel(c, ticker="SUBJ", active_window="3Y")
    assert "How its gold beta compares" in html
    assert "3-year" in html  # window label rendered
    assert "percentile" in html  # subject percentile text rendered
    assert "GDX down" in html and "GDXJ down" in html  # benchmark reference numbers
    assert "orange marker" in html  # legend
    assert "<svg" in html  # both strips present


def test_render_panel_unavailable_and_subject_absent_paths():
    # Fully unavailable (no data resolved yet)
    assert "No GDX/GDXJ" in _render_beta_comparison_panel(None, ticker="SUBJ", active_window="6M")
    # Subject not in the universe -> still renders, with the explanatory message
    c = resolve_beta_universe_comparison(ticker="ZZZ", window_id="6M", universe_df=_universe(), benchmark_df=_benchmarks())
    html = _render_beta_comparison_panel(c, ticker="ZZZ", active_window="6M")
    assert "not in the scored miner universe" in html
    assert "GDX down" in html  # benchmarks still shown


def test_comparison_math_is_not_duplicated_in_the_serve_layer():
    """Canon per-surface guardrail: percentile / rank / axis-domain math for the comparison lives
    ONLY in the model module. The serve panel and chart builder must read resolved fields, never
    recompute them (Emanuel: 'all the calculation in the backend, no UI logic')."""
    charts = Path("golden_vector/serve/charts.py").read_text(encoding="utf-8")
    panels = Path("golden_vector/serve/detail_panels.py").read_text(encoding="utf-8")
    # Genuine rank / percentile / sort COMPUTATION tokens (a formatter like _ordinal_percentile
    # that only renders a resolved number is fine — these catch recomputation, not formatting).
    for forbidden in ("np.percentile", ".rank(", ".quantile(", "np.sort", "def _percentile"):
        assert forbidden not in charts, f"charts.py recomputes comparison math: {forbidden}"
        assert forbidden not in panels, f"detail_panels.py recomputes comparison math: {forbidden}"
    # The strip builder must not sort or min/max the universe (that is the model's job).
    assert "sorted(" not in charts
