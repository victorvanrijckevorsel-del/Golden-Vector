"""M3c: the ticker page's Market-behaviour section.

Everything here is fixture-driven — no test reads a real ``data/`` artifact.
The Lab loaders are monkeypatched with constructed ``LabCellsData`` /
``LabCurveData`` values so the disclosure's states (unavailable, empty bucket,
drawn charts) are exercised without a built Lab on disk.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.ticker_page_state import TickerPageArtifactState
from golden_vector.serve.lab_curve_data import LabCellsData, LabCurveData
from golden_vector.serve.ticker_page import TickerPageData
from golden_vector.serve.ticker_page import behaviour as B
from golden_vector.serve.workspace_state import (
    DETAIL_ALIGNMENT_ALIGNED,
    StructuralHistoryLoad,
    ToolADetailState,
)


def _app_config():
    return load_app_config(ProjectPaths.discover()).app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

_WINDOWS = ("6M", "12M", "2Y", "3Y", "5Y")


def _tool_a_row(**overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "as_of_date": "2026-08-08",
        "anchor_window_id": "12M",
        "volatility_anchor_window_id": "12M",
        "total_volatility_52w": 0.412,
        "residual_volatility_52w": 0.287,
        "downside_volatility_52w": 0.331,
        "volatility_context": "HIGH_NOISE",
        "structural_delta_core": 1.44,
        "structural_gamma_core": 0.22,
        "asymmetry_ratio_core": 0.91,
        "up_beta_core": 1.31,
        "down_beta_core": 1.53,
        "score_eligibility_reason": "",
        "normalization_issue_summary": None,
    }
    for window in _WINDOWS:
        win = window.lower()
        row[f"structural_delta_{win}"] = 1.4
        row[f"gamma_{win}"] = 0.2
        row[f"up_beta_{win}"] = 1.3
        row[f"down_beta_{win}"] = 1.5
        row[f"asymmetry_ratio_{win}"] = 0.9
        row[f"r_squared_{win}"] = 0.55
        row[f"weeks_{win}"] = 52
        row[f"window_status_{win}"] = "ELIGIBLE"
    row.update(overrides)
    return row


def _detail_state(**overrides) -> ToolADetailState:
    kwargs: dict[str, object] = {
        "weekly_series": pd.DataFrame(),
        "structural_window_metrics": pd.DataFrame(),
        "structural_metrics_load": StructuralHistoryLoad(
            status="ok", history=pd.DataFrame(), error_message=""
        ),
        "exploratory_horizons": pd.DataFrame(),
        "benchmark_comparison_by_window": {},
    }
    kwargs.update(overrides)
    return ToolADetailState(**kwargs)  # type: ignore[arg-type]


def _percentile_frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def _pct_row(metric_key: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "finance_source": "our",
        "metric_key": metric_key,
        "category": "trading",
        "raw_value": 0.32,
        "unit": "percent",
        "basis": "tool C window",
        "metric_available": True,
        "metric_reason": None,
        "pct_low_good": 61.0,
        "pct_high_good": 39.0,
        "eligible_observation_count": 44,
        "hit_count": 6,
        "source_period_start": pd.Timestamp("2019-01-04"),
        "source_period_end": pd.Timestamp("2026-08-07"),
        "source_verification_status": None,
        "source_verification_date": None,
    }
    row.update(overrides)
    return row


def _research_frame(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def _weekly_row(date: str, stock: float, gold: float, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "kind": "weekly",
        "date": pd.Timestamp(date),
        "stock_return": stock,
        "gold_return": gold,
        "kind_status": "OK",
        "kind_reason": None,
    }
    row.update(overrides)
    return row


def _window_fit_row(window: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "kind": "window_fit",
        "window": window,
        "up_beta": 1.21,
        "down_beta": 1.64,
        "r_squared": 0.51,
        "weeks": 52,
        "window_status": "ELIGIBLE",
        "kind_status": "OK",
        "kind_reason": None,
    }
    row.update(overrides)
    return row


def _horizon_row(label: str, **overrides) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": "NEM",
        "kind": "horizon",
        "horizon_label": label,
        "horizon_return": 0.18,
        "horizon_gold_return": 0.09,
        "horizon_gold_delta": 2.0,
        "horizon_coverage_flag": "PARTIAL",
        "horizon_coverage_reason": "only 34 of 52 weeks present",
        "horizon_start_date": pd.Timestamp("2025-08-08"),
        "horizon_end_date": pd.Timestamp("2026-08-07"),
        "kind_status": "OK",
        "kind_reason": None,
    }
    row.update(overrides)
    return row


def _data(
    *,
    percentiles: pd.DataFrame | None = None,
    research: pd.DataFrame | None = None,
    research_status: str = "OK",
    research_reason: str | None = None,
) -> TickerPageData:
    blank = TickerPageArtifactState(status="OK", reason=None, frame=pd.DataFrame())
    return TickerPageData(
        gold_response=blank,
        percentiles=TickerPageArtifactState(
            status="OK",
            reason=None,
            frame=percentiles if percentiles is not None else pd.DataFrame(),
        ),
        performance=blank,
        research_series=TickerPageArtifactState(
            status=research_status,
            reason=research_reason,
            frame=research if research is not None else pd.DataFrame(),
        ),
        fx_attribution=blank,
    )


def _full_percentiles() -> pd.DataFrame:
    return _percentile_frame(
        _pct_row("rel_strength_vs_gdx", raw_value=0.58),
        _pct_row("rel_weakness_vs_gdx", raw_value=0.42),
        _pct_row("upside_hit_rate", raw_value=0.21, hit_count=9, eligible_observation_count=43),
        _pct_row("downside_hit_rate", raw_value=0.14, hit_count=6, eligible_observation_count=44),
        _pct_row("tail_best10", raw_value=0.11),
        _pct_row("tail_worst10", raw_value=-0.13),
        _pct_row("aisc", raw_value=1480.0, unit="usd_per_oz", basis="Our View mining assumption"),
    )


def _full_research() -> pd.DataFrame:
    return _research_frame(
        *(_window_fit_row(window) for window in _WINDOWS),
        _weekly_row("2026-07-31", 0.021, 0.014),
        _weekly_row("2026-08-07", -0.018, -0.009),
        _weekly_row("2026-08-14", 0.004, 0.002),
        _horizon_row("12M"),
    )


def _render(**overrides) -> str:
    kwargs: dict[str, object] = {
        "ticker": "NEM",
        "tool_a_row": _tool_a_row(),
        "tool_a_detail": _detail_state(),
        "alignment": DETAIL_ALIGNMENT_ALIGNED,
        "active_window": "12M",
        "canonical_anchor": "12M",
        "data": _data(percentiles=_full_percentiles(), research=_full_research()),
        "finance_source": "our",
        "app_config": _app_config(),
    }
    kwargs.update(overrides)
    return B.render_market_behaviour_section(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# section composition + the removed verdicts
# ---------------------------------------------------------------------------


def test_section_mounts_at_market_behaviour_with_the_beta_window_switcher():
    html = _render()
    assert 'id="market-behaviour"' in html
    # the switcher MOVED here out of the global control bar
    assert 'class="window-switcher"' in html
    assert 'aria-label="Beta window"' in html
    assert "window=6m" in html  # the window param round-trips exactly as before


def _window_tab_hrefs(html: str) -> dict[str, str]:
    """Map each beta-window tab label -> its (unescaped) href."""
    hrefs: dict[str, str] = {}
    for match in re.finditer(
        r'<a class="window-tab[^"]*" href="([^"]+)"[^>]*>([^<]+)', html
    ):
        hrefs[match.group(2).strip()] = unescape(match.group(1))
    return hrefs


def test_window_tabs_round_trip_every_unrelated_view_param():
    """W1: a beta-window click must not drop chart / options / lab state.

    The switcher used to hand-roll an allow-list of four params, so every other
    query key on the page (chart_view, chart_h, tw, lab_*) was silently reset on
    each tab click. Tabs now build their href from the page's real query params.
    """

    query = {
        "chart_view": "price",
        "chart_h": "5Y",
        "tw": "45",
        "fundamentals_source": "yahoo",
        "lab_h": "12",
        "lab_b": "GDXJ",
        "window": "6m",
        "saved": "reporting",
    }
    html = _render(active_window="6M", finance_source="yahoo", query_params=query)

    hrefs = _window_tab_hrefs(html)
    assert set(hrefs) == {"6M", "1Y", "2Y", "3Y", "5Y"}
    for label, href in hrefs.items():
        params = parse_qs(urlsplit(href).query)
        for key in ("chart_view", "chart_h", "tw", "lab_h", "lab_b"):
            assert params.get(key) == [query[key]], f"{label} dropped {key}"
        assert params.get("fundamentals_source") == ["yahoo"], label
        # the one-shot flash marker is never re-carried
        assert "saved" not in params, label
        assert urlsplit(href).fragment == "market-behaviour"

    # every non-canonical tab sets its own window; the canonical-default tab
    # drops ONLY `window` (12M renders as "1Y").
    assert parse_qs(urlsplit(hrefs["6M"]).query)["window"] == ["6m"]
    assert parse_qs(urlsplit(hrefs["3Y"]).query)["window"] == ["3y"]
    canonical_params = parse_qs(urlsplit(hrefs["1Y"]).query)
    assert "window" not in canonical_params
    assert set(canonical_params) == set(parse_qs(urlsplit(hrefs["6M"]).query)) - {"window"}


def test_open_by_default_bars_and_rugs_render_from_the_published_window_fit():
    comparison = _StubComparison()
    html = _render(
        tool_a_detail=_detail_state(benchmark_comparison_by_window={"12M": comparison}),
    )
    assert "Up vs Down Beta" in html
    assert "Where its gold beta ranks vs the miner universe" in html
    # both are OUTSIDE any disclosure: everything before the first <details>
    open_part = html.split("<details", 1)[0]
    assert "Up vs Down Beta" in open_part
    assert "Where its gold beta ranks vs the miner universe" in open_part
    assert '<th scope="col">Ticker</th>' in html
    assert '<th scope="col" class="numeric">Beta</th>' in html
    assert '<td>AEM</td><td class="numeric">0.80</td>' in html


def test_relative_record_states_the_exact_counted_evidence():
    html = _render()
    assert "Relative record vs GDX" in html
    assert "Big down-week hit rate" in html
    assert "Big up-week hit rate" in html
    # the SAME evidence wording the cost/downside card uses (one helper)
    assert "6 large falls in 44 qualifying weak-gold weeks" in html
    assert "9 large rises in 43 qualifying strong-gold weeks" in html
    assert "Period 2019-01-04 to 2026-08-07" in html
    # thresholds come from config, never a hardcoded twin
    assert "A big down week is a weekly return of -10% or worse" in html


def test_relative_record_marks_only_the_value_column_as_numeric():
    html = _render()

    assert '<th class="numeric" scope="col">Value</th>' in html
    assert '<td class="numeric">58.0%</td>' in html
    assert '<th scope="col">Measure</th>' in html
    assert '<th scope="col">Evidence and basis</th>' in html
    assert '<td class="numeric">Period 2019-01-04 to 2026-08-07' not in html


def test_relative_record_reports_a_missing_metric_instead_of_inventing_one():
    frame = _percentile_frame(
        _pct_row("rel_strength_vs_gdx", raw_value=0.58),
        _pct_row(
            "downside_hit_rate",
            metric_available=False,
            raw_value=None,
            metric_reason="fewer than 8 qualifying weeks",
        ),
    )
    html = _render(data=_data(percentiles=frame, research=_full_research()))
    assert "fewer than 8 qualifying weeks" in html
    assert "no published row for this metric" in html  # the untouched metrics


def test_relative_record_accepts_nullable_metric_flag_and_reason():
    frame = _percentile_frame(
        _pct_row(
            "downside_hit_rate",
            metric_available=pd.NA,
            metric_reason=pd.NA,
            raw_value=pd.NA,
        )
    )

    html = _render(data=_data(percentiles=frame, research=_full_research()))

    assert "not available" in html


@pytest.mark.parametrize(
    "banned",
    [
        "Gold Sensitivity Score",
        "Confidence",
        "confidence score",
        "tool_a_rank",
        "screening verdict",
        "fundamental check",
        # M3f: the cross-sectional ranks are Finder/Tool-page language. This
        # section renders the beta standings, so it is where they would leak.
        "quality rank",
        "downside rank",
        "upside rank",
    ],
)
def test_no_compiled_verdict_survives_anywhere_in_the_section(banned):
    """Requirements §3: no compiled score/verdict is displayed on this page.

    Asserted over the WHOLE section string, so a value hidden inside a closed
    disclosure fails just as loudly as one in the open part.
    """
    assert banned not in _render()


def test_explanation_cards_describe_measured_betas_only():
    cards = B._build_measured_beta_explanations(
        tool_a_row=_tool_a_row(),
        active_window="12M",
        scoring_config=_app_config().scoring,
    )
    assert [title for title, _ in cards] == ["Delta", "Gamma", "Asymmetry", "Volatility"]


# ---------------------------------------------------------------------------
# the Lab disclosure
# ---------------------------------------------------------------------------


class _StubMark:
    """One resolved universe tick (position is a backend-computed 0..1 fraction)."""

    def __init__(self, ticker: str, beta: float, position: float) -> None:
        self.ticker = ticker
        self.beta = beta
        self.position = position


class _StubComparison:
    """Minimal resolved comparison object (the model layer builds the real one)."""

    available = True
    window_label = "1Y"
    down_domain = (0.0, 2.0)
    up_domain = (0.0, 2.0)
    down_universe_marks = (
        _StubMark("AEM", 0.8, 0.4),
        _StubMark("GOLD", 1.2, 0.6),
        _StubMark("NEM", 1.64, 0.8),
    )
    up_universe_marks = (
        _StubMark("AEM", 0.7, 0.35),
        _StubMark("GOLD", 1.1, 0.55),
        _StubMark("NEM", 1.21, 0.6),
    )
    universe_down_n = 61
    universe_up_n = 61
    benchmarks = ()

    class _Subject:
        label = "NEM"
        up_beta = 1.21
        down_beta = 1.64
        up_pos = 0.6
        down_pos = 0.8
        up_percentile = 62.0
        down_percentile = 77.0

    subject = _Subject()


def _lab_curve(**overrides) -> LabCurveData:
    points = [
        {
            "date": "2014-06-06",
            "alpha": 0.02,
            "alpha_simple": 0.02,
            "beat": True,
            "is_scenario": True,
            "is_anchor": True,
        },
        {
            "date": "2019-03-01",
            "alpha": 0.05,
            "alpha_simple": 0.05,
            "beat": True,
            "is_scenario": True,
            "is_anchor": True,
        },
        {
            "date": "2021-07-02",
            "alpha": -0.04,
            "alpha_simple": -0.04,
            "beat": False,
            "is_scenario": True,
            "is_anchor": False,
        },
        {
            "date": "2023-11-03",
            "alpha": 0.01,
            "alpha_simple": 0.01,
            "beat": True,
            "is_scenario": True,
            "is_anchor": True,
        },
    ]
    profile_points = [
        {
            "bucket": bucket,
            "label": label,
            "usable": True,
            "p_beat_raw": 0.55,
            "p_beat_shrunk": 0.53,
            "median_alpha": 0.02,
            "effective_n": 12.0,
            "wilson_low": 0.41,
            "wilson_high": 0.69,
        }
        for bucket, label in (
            ("gold_down_big", "Gold down more than 15%"),
            ("gold_down", "Gold down 5% to 15%"),
            ("gold_flat", "Gold flat (−5% to +5%)"),
            ("gold_up", "Gold up 5% to 15%"),
            ("gold_up_big", "Gold up more than 15%"),
        )
    ]
    kwargs: dict[str, object] = {
        "available": True,
        "ticker": "NEM",
        "benchmark": "GDX",
        "horizon": 8,
        "scenario_bucket": "gold_down",
        "scenario_label": "Gold down 5% to 15%",
        "points": points,
        "profile_points": profile_points,
        "profile_usable_down": 2,
        "profile_usable_up": 2,
        "profile_label_status": "UNAVAILABLE",
        "cell": {
            "p_beat_gdx": 0.55,
            "p_beat_gdx_shrunk": 0.53,
            "median_alpha_gdx": 0.02,
            "gdx_effective_n": 12.0,
            "gdx_insufficient_history": False,
        },
    }
    kwargs.update(overrides)
    return LabCurveData(**kwargs)  # type: ignore[arg-type]


def _lab_cells(**overrides) -> LabCellsData:
    kwargs: dict[str, object] = {
        "available": True,
        "horizon": 8,
        "horizons": [4, 8, 13, 26],
        "buckets": [("gold_down", "Gold down 5% to 15%")],
        "selected_bucket": "gold_down",
        "bucket_availability": {
            "8": {
                "gold_down_big": 0,
                "gold_down": 54,
                "gold_flat": 61,
                "gold_up": 58,
                "gold_up_big": 12,
            }
        },
        "rows": [],
    }
    kwargs.update(overrides)
    return LabCellsData(**kwargs)  # type: ignore[arg-type]


@pytest.fixture
def lab_paths(tmp_path) -> ProjectPaths:
    data_dir = tmp_path / "data"
    return ProjectPaths(
        repo_root=tmp_path,
        config_dir=tmp_path / "config",
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        intermediate_dir=data_dir / "intermediate",
        output_dir=data_dir / "output",
        manual_dir=data_dir / "manual",
        runs_dir=data_dir / "runs",
        reviews_dir=tmp_path / "reviews",
        tests_dir=tmp_path / "tests",
    )


@pytest.fixture(autouse=True)
def _drop_lab_cache():
    B.clear_lab_render_cache()
    yield
    B.clear_lab_render_cache()


def _stub_lab(monkeypatch, *, cells: LabCellsData, curve: LabCurveData) -> None:
    monkeypatch.setattr(B, "load_dial_cells", lambda *a, **k: cells)
    monkeypatch.setattr(B, "load_ticker_curve", lambda *a, **k: curve)


def test_lab_disclosure_is_closed_by_default(monkeypatch, lab_paths):
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    html = _render(paths=lab_paths)
    assert "How it behaved in past gold moves" in html
    marker = '<details class="disclosure lab-history"'
    assert marker in html
    assert marker + ">" in html  # no open attribute


def test_a_valid_lab_query_reopens_and_anchors_the_disclosure(monkeypatch, lab_paths):
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    request = B.parse_lab_request(
        {"lab_h": ["13"], "lab_b": ["GDXJ"], "lab_s": ["gold_up"]},
        app_config=_app_config(),
    )
    assert request.active is True
    assert (request.horizon, request.benchmark, request.bucket) == (13, "GDXJ", "gold_up")
    html = _render(paths=lab_paths, lab_request=request)
    assert '<details class="disclosure lab-history" open>' in html
    assert 'id="market-behaviour"' in html
    assert "#market-behaviour" in html  # the controls submit back to this section


def test_lab_defaults_are_config_driven_and_eight_weeks_is_marked_default(
    monkeypatch, lab_paths
):
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    config = _app_config()
    assert config.ticker_page.lab.default_horizon_weeks == 8
    request = B.parse_lab_request(None, app_config=config)
    assert (request.horizon, request.benchmark, request.bucket, request.active) == (
        8,
        "GDX",
        "gold_down",
        False,
    )
    html = _render(paths=lab_paths, app_config=config)
    for weeks in (4, 8, 13, 26):
        assert f"lab_h={weeks}" in html
        assert f">{weeks}w" in html
    assert '>8w <span class="hint">default</span></a>' in html
    for param in ("lab_b=GDX", "lab_s=gold_down"):
        assert param in html
    # the controls group carries its registered explainer (no orphan entry)
    assert html.count('data-help-title="Lab history controls"') == 1


def test_an_invalid_lab_param_defaults_with_a_visible_note(monkeypatch, lab_paths):
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    request = B.parse_lab_request({"lab_h": ["7"]}, app_config=_app_config())
    assert request.horizon == 8
    assert request.active is True  # the user asked for the Lab; keep it open and explain
    assert "look-ahead 7 is not one of 4w, 8w, 13w, 26w" in request.note
    html = _render(paths=lab_paths, lab_request=request)
    assert "look-ahead 7 is not one of 4w, 8w, 13w, 26w" in html


def test_lab_charts_carry_their_own_period_labels_and_the_survivor_caveat(
    monkeypatch, lab_paths
):
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    config = _app_config()
    html = _render(paths=lab_paths, app_config=config)
    year = config.ticker_page.lab.scatter_from_year
    assert f"Episodes since {year}" in html
    assert "Beat-rate: full published history" in html
    assert "published 95% interval" in html
    assert "Survivor-only history" in html


def test_lab_scatter_is_trimmed_to_the_configured_year(monkeypatch, lab_paths):
    """Q44: the episode charts start at the configured year, not at 2014."""
    curve = _lab_curve()
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=curve)
    html = _render(paths=lab_paths)
    assert "2014-06-06" not in html  # trimmed away
    assert "2019-03-01" in html  # kept


def test_an_empty_bucket_renders_its_reason_not_a_guessed_chart(monkeypatch, lab_paths):
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    request = B.parse_lab_request({"lab_s": ["gold_down_big"]}, app_config=_app_config())
    html = _render(paths=lab_paths, lab_request=request)
    assert "No countable history for “Gold down more than 15%” at 8 weeks" in html
    assert "0 miners with enough independent weeks" in html
    assert "Spread of outcomes" not in html


def test_an_unavailable_lab_artifact_states_the_reason_once(monkeypatch, lab_paths):
    _stub_lab(
        monkeypatch,
        cells=_lab_cells(available=False, error_status="CELLS_CORRUPT"),
        curve=_lab_curve(),
    )
    html = _render(paths=lab_paths)
    assert "Lab scenario-cells artifact is corrupt" in html
    assert "python -m golden_vector.lab.conditional_dial" in html


def test_the_lab_never_embeds_raw_episode_rows(monkeypatch, lab_paths):
    """Plan §12 rule 1: Lab charts are server-side SVG only."""
    _stub_lab(monkeypatch, cells=_lab_cells(), curve=_lab_curve())
    html = _render(paths=lab_paths)
    assert "application/json" not in html
    assert "<script" not in html


def test_the_lab_render_cache_is_bounded_and_invalidates_on_a_rebuild(
    monkeypatch, lab_paths
):
    calls: list[int] = []

    def _counting_cells(*_args, **_kwargs):
        calls.append(1)
        return _lab_cells()

    monkeypatch.setattr(B, "load_dial_cells", _counting_cells)
    monkeypatch.setattr(B, "load_ticker_curve", lambda *a, **k: _lab_curve())
    monkeypatch.setattr(B, "lab_artifact_pointer", lambda _paths: (111, 222))
    request = B.parse_lab_request(None, app_config=_app_config())
    for _ in range(3):
        B.render_lab_history(lab_paths, ticker="NEM", request=request, app_config=_app_config())
    assert len(calls) == 1  # memoized

    # A Lab REBUILD moves the artifact pointer, which must invalidate.
    monkeypatch.setattr(B, "lab_artifact_pointer", lambda _paths: (999, 222))
    B.render_lab_history(lab_paths, ticker="NEM", request=request, app_config=_app_config())
    assert len(calls) == 2

    # Bounded: 40 combinations cannot grow the cache past its cap.
    for horizon in (4, 8, 13, 26):
        for benchmark in ("GDX", "GDXJ"):
            for bucket in (
                "gold_down_big",
                "gold_down",
                "gold_flat",
                "gold_up",
                "gold_up_big",
            ):
                B.render_lab_history(
                    lab_paths,
                    ticker="NEM",
                    request=B.LabRequest(
                        horizon=horizon, benchmark=benchmark, bucket=bucket
                    ),
                    app_config=_app_config(),
                )
    assert len(B._LAB_CACHE) <= B._LAB_CACHE_MAX == 32


# ---------------------------------------------------------------------------
# Full research detail — research-series consumption
# ---------------------------------------------------------------------------


def test_weekly_scatter_and_ladder_render_from_the_research_series():
    html = _render()
    assert "Weekly return scatter" in html
    assert "3 weekly observations · 2026-07-31 to 2026-08-14" in html
    assert "Exploratory horizon ladder" in html
    assert "only 34 of 52 weeks present" in html  # the ladder's coverage reason
    assert "PARTIAL" in html


# --- M3f: the window sample + the published fit line ------------------------


def _five_weeks_research() -> pd.DataFrame:
    """Five published weeks, deliberately OUT of date order.

    A real artifact is not guaranteed to arrive sorted, and the trailing sample
    must be the latest WEEKS, never the last ROWS: emitting the newest week
    first means a dropped ``sort_values("date")`` changes which dots are drawn.
    """
    return _research_frame(
        *(_window_fit_row(window) for window in _WINDOWS),
        _weekly_row("2026-08-14", 0.004, 0.002),
        _weekly_row("2026-07-17", 0.011, 0.006),
        _weekly_row("2026-07-24", -0.007, -0.004),
        _weekly_row("2026-07-31", 0.021, 0.014),
        _weekly_row("2026-08-07", -0.018, -0.009),
        _horizon_row("12M"),
    )


def _structural_metrics(**overrides) -> pd.DataFrame:
    rows = []
    for window in _WINDOWS:
        row: dict[str, object] = {
            "ticker": "NEM",
            "window_id": window,
            "as_of_date": pd.Timestamp("2026-08-14"),
            "structural_delta": 1.4,
            "intercept_alpha": 0.0021,
        }
        row.update(overrides)
        rows.append(row)
    return pd.DataFrame(rows)


def test_scatter_draws_the_published_fit_line_and_the_window_sample():
    """The line comes from the window's PUBLISHED slope + intercept, and the
    dots are the trailing ``weeks_{window}`` rows the artifact published."""
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=2),
        tool_a_detail=_detail_state(structural_window_metrics=_structural_metrics()),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert 'class="chart-fit-line"' in html
    assert "The line is the published 1Y fit (slope 1.40, intercept 0.0021)" in html
    assert "nothing is fitted in the page" in html

    # sample = the LAST 2 of 5 published weeks, sized by the persisted count
    assert "2 weekly observations · 2026-08-07 to 2026-08-14" in html
    assert "Trailing 2 weeks" in html
    # ...and the trimmed-away weeks are genuinely gone from the period
    assert "2026-07-17" not in html
    assert "No published fit line" not in html


@pytest.mark.parametrize(
    "missing", [{"intercept_alpha": None}, {"structural_delta": None}]
)
def test_scatter_draws_no_line_when_either_coefficient_is_not_published(missing):
    """A slope alone cannot place a line, and neither can an intercept alone.
    Serve must not back-solve the other half — the control is the identical
    fixture with BOTH coefficients, which does draw."""
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=2),
        tool_a_detail=_detail_state(
            structural_window_metrics=_structural_metrics(**missing)
        ),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert 'class="chart-fit-line"' not in html
    assert "No published fit line for this window." in html
    # ...and no half-formatted claim leaks into the caption
    assert "slope n/a" not in html
    assert "intercept n/a" not in html
    # the dots and the window sample are unaffected by the missing coefficient
    assert "2 weekly observations · 2026-08-07 to 2026-08-14" in html


def test_scatter_falls_back_to_the_full_series_without_a_published_weeks_count():
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=None),
        tool_a_detail=_detail_state(structural_window_metrics=_structural_metrics()),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert "5 weekly observations · 2026-07-17 to 2026-08-14" in html
    assert "no weeks count is published for this window" in html
    assert "Trailing" not in html
    # the published line still draws — the two facts are independent
    assert 'class="chart-fit-line"' in html


def test_scatter_reads_the_fit_for_the_ACTIVE_window_not_the_first_one():
    """Selection is by ``window_id``, so switching the window switches the
    line. A 6M-only metrics frame must leave the 1Y view with no line."""
    six_month_only = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "window_id": "6M",
                "as_of_date": pd.Timestamp("2026-08-14"),
                "structural_delta": 2.5,
                "intercept_alpha": 0.009,
            }
        ]
    )
    data = _data(percentiles=_full_percentiles(), research=_five_weeks_research())
    on_1y = _render(
        tool_a_detail=_detail_state(structural_window_metrics=six_month_only),
        data=data,
    )
    assert "No published fit line for this window." in on_1y
    assert "slope 2.50" not in on_1y

    on_6m = _render(
        active_window="6M",
        tool_a_detail=_detail_state(structural_window_metrics=six_month_only),
        data=data,
    )
    assert "The line is the published 6M fit (slope 2.50, intercept 0.0090)" in on_6m


def test_scatter_uses_the_NEWEST_published_row_for_the_window():
    """``_published_window_fit`` promises the newest published row wins. Real
    artifacts carry one row per week, so a stale row must never draw the line —
    the rows are fed newest-first so dropping the sort picks the stale one."""
    two_dated = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "window_id": "12M",
                "as_of_date": pd.Timestamp("2026-08-14"),
                "structural_delta": 1.4,
                "intercept_alpha": 0.0021,
            },
            {
                "ticker": "NEM",
                "window_id": "12M",
                "as_of_date": pd.Timestamp("2025-08-14"),
                "structural_delta": 9.99,
                "intercept_alpha": 0.5,
            },
        ]
    )
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=2),
        tool_a_detail=_detail_state(structural_window_metrics=two_dated),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert "The line is the published 1Y fit (slope 1.40, intercept 0.0021)" in html
    assert "slope 9.99" not in html
    assert "intercept 0.5000" not in html


def test_scatter_suppresses_the_line_when_the_window_is_not_eligible():
    """The producer publishes real coefficients for degraded windows too (a 1Y
    fit on too few weeks is still a regression). Degraded evidence is EXCLUDED,
    not decorated: no line, and a caption naming the persisted status. The
    control is the identical fixture on an ELIGIBLE window, which does draw."""
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=2, window_status_12m="LOW_OBSERVATION"),
        tool_a_detail=_detail_state(structural_window_metrics=_structural_metrics()),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert 'class="chart-fit-line"' not in html
    assert (
        "No fit line: the 1Y window is not eligible for this ticker "
        "(status: LOW_OBSERVATION), so its published fit is not drawn." in html
    )
    assert "slope 1.40" not in html
    # the dots themselves are published observations and still draw
    assert "2 weekly observations · 2026-08-07 to 2026-08-14" in html

    eligible = _render(
        tool_a_row=_tool_a_row(weeks_12m=2),
        tool_a_detail=_detail_state(structural_window_metrics=_structural_metrics()),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert 'class="chart-fit-line"' in eligible
    assert "The line is the published 1Y fit (slope 1.40, intercept 0.0021)" in eligible


def test_scatter_draws_the_full_series_when_the_published_weeks_count_is_zero():
    """``weeks_12m = 0`` is not a sample size. It takes the same honest path as
    a missing count rather than trimming the series to nothing."""
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=0),
        tool_a_detail=_detail_state(structural_window_metrics=_structural_metrics()),
        data=_data(percentiles=_full_percentiles(), research=_five_weeks_research()),
    )
    assert "5 weekly observations · 2026-07-17 to 2026-08-14" in html
    assert "no weeks count is published for this window" in html
    assert "Trailing" not in html


def test_scatter_renders_without_a_period_when_the_series_has_no_date_column():
    """A weekly series with no ``date`` is neither trimmed nor given a period
    suffix — but it still draws, and it must not raise."""
    undated = _five_weeks_research().drop(columns=["date"])
    html = _render(
        tool_a_row=_tool_a_row(weeks_12m=2),
        tool_a_detail=_detail_state(structural_window_metrics=_structural_metrics()),
        data=_data(percentiles=_full_percentiles(), research=undated),
    )
    assert "5 weekly observations." in html
    assert "weekly observations ·" not in html
    assert "no weeks count is published for this window" in html


def test_a_degraded_research_kind_renders_its_persisted_reason():
    frame = _research_frame(
        {
            "ticker": "NEM",
            "kind": "weekly",
            "kind_status": "MISSING",
            "kind_reason": "fewer than 12 clean weekly observations",
        },
        *(_window_fit_row(window) for window in _WINDOWS),
    )
    html = _render(data=_data(percentiles=_full_percentiles(), research=frame))
    assert "fewer than 12 clean weekly observations" in html
    assert "The published weekly return series is MISSING" in html
    # the marker row is never drawn as an observation
    assert "weekly observations ·" not in html


def test_research_kind_state_accepts_nullable_parquet_strings():
    data = _data(
        research=_research_frame(
            _window_fit_row("12M", kind_reason=pd.NA),
        )
    )

    assert data.research_kind_state("NEM", kind="window_fit") == ("OK", "")

    missing_status = _data(
        research=_research_frame(
            _window_fit_row("12M", kind_status=pd.NA, kind_reason=pd.NA),
        )
    )
    assert missing_status.research_kind_state("NEM", kind="window_fit") == (
        "MISSING",
        "window_fit series unavailable",
    )


def test_horizon_ladder_accepts_nullable_persisted_text():
    html = B.render_horizon_ladder(
        _research_frame(
            _horizon_row(
                pd.NA,
                horizon_coverage_flag=pd.NA,
                horizon_coverage_reason=pd.NA,
            )
        )
    )

    assert "Exploratory horizon ladder" in html
    assert "&lt;NA&gt;" not in html


def test_structural_window_table_shows_betas_and_drops_the_score_inputs():
    html = B.render_structural_window_table(
        _research_frame(*(_window_fit_row(window) for window in _WINDOWS)),
        active_window="12M",
        canonical_anchor="12M",
    )
    assert "Fitted betas by window" in html
    for header in ("Up beta", "Down beta", "R^2", "Weeks", "Status"):
        assert header in html
    for dropped in ("Delta", "Gamma", "Asymmetry", "Score", "Confidence"):
        assert f">{dropped}<" not in html
    assert "1.21" in html and "1.64" in html and "ELIGIBLE" in html
    assert "(Anchor, Active)" in html


def test_structural_and_horizon_tables_mark_only_quantitative_columns_numeric():
    structural = B.render_structural_window_table(
        _research_frame(*(_window_fit_row(window) for window in _WINDOWS)),
        active_window="12M",
        canonical_anchor="12M",
    )
    for header in ("Up beta", "Down beta", "R^2", "Weeks"):
        assert f'<th scope="col" data-sort-numeric>{header}' in structural
    for value in ("1.21", "1.64", "51.0%", "52"):
        assert f'<td class="numeric">{value}</td>' in structural
    assert '<th scope="col">Window' in structural
    assert '<th scope="col">Status' in structural
    assert '<td>ELIGIBLE</td>' in structural

    horizon = B.render_horizon_ladder(_research_frame(_horizon_row("12M")))
    for header in ("Equity return", "Gold return", "Single-period ratio"):
        assert f'<th scope="col" data-sort-numeric>{header}' in horizon
    for value in ("18.0%", "9.0%", "2.00"):
        assert f'<td class="numeric">{value}</td>' in horizon
    assert '<th scope="col">Horizon' in horizon
    assert '<th scope="col">Status' in horizon
    assert '<th scope="col">Window' in horizon
    assert '<td>PARTIAL <span class="hint">only 34 of 52 weeks present</span></td>' in horizon
    assert '<td>2025-08-08 to 2026-08-07</td>' in horizon


# ---------------------------------------------------------------------------
# volatility: published only, never recomputed
# ---------------------------------------------------------------------------


def test_volatility_renders_the_published_fields_on_the_canonical_window():
    html = B.render_volatility_panel(_tool_a_row(), active_window="12M")
    assert "41.2%" in html and "28.7%" in html and "33.1%" in html
    assert "HIGH_NOISE" in html
    assert "Published 52-week values for the canonical window." in html


def test_volatility_cards_each_carry_their_explainer_icon():
    """``_metric_card(help_key=...)`` must actually render the icon: proving the
    key exists in the registry proves nothing about the button reaching the
    page."""
    html = B.render_volatility_panel(
        _tool_a_row(), active_window="12M", app_config=_app_config()
    )
    for title in (
        "Total volatility (annualized log vol)",
        "Residual volatility (annualized log vol)",
        "Downside volatility (annualized log vol)",
        "Volatility context",
    ):
        assert html.count(f'data-help-title="{title}"') == 1, title


def test_volatility_is_never_estimated_for_a_non_canonical_window():
    html = B.render_volatility_panel(_tool_a_row(), active_window="3Y")
    assert "Volatility diagnostics are published for the canonical window only." in html
    assert "41.2%" not in html  # the canonical number is not shown under another name


def test_volatility_is_suppressed_when_the_window_is_not_eligible():
    row = _tool_a_row(window_status_3y="LOW_OBSERVATION")
    html = B.render_volatility_panel(row, active_window="3Y")
    assert "is not eligible for this ticker" in html
    assert "LOW_OBSERVATION" in html


def test_no_serve_module_fits_a_regression_in_the_request_path():
    """The sanctioned ``np.polyfit`` exception was DELETED with the recompute."""
    for module in sorted(Path("golden_vector/serve").rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        assert "polyfit" not in source, module
