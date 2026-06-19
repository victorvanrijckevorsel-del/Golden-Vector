from datetime import date

import numpy as np
import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import _latest_snapshot
from golden_vector.model.pipeline import _build_tool_a_outputs, execute_tool_a_profile_pipeline
from golden_vector.model.scoring import rank_tool_a_outputs
from tests.helpers import build_test_paths


class _SyntheticRunContext:
    run_id = "synthetic-run"


def _activate_for_test(app_config, *fixture_tickers: str):
    """Force a set of fixture tickers to be active in the loaded app_config.

    Pipeline functions filter histories to active tickers only; if a fixture
    ticker is inactive in the live universe.yaml the test row vanishes from
    the output and the assertion KeyErrors. This helper decouples tests from
    the live active/inactive state so universe edits don't break fixtures.
    """
    targets = {t.upper() for t in fixture_tickers}
    new_tickers = [
        ticker.model_copy(update={"active": True}) if ticker.ticker in targets else ticker
        for ticker in app_config.universe.tickers
    ]
    new_universe = app_config.universe.model_copy(update={"tickers": new_tickers})
    return app_config.model_copy(update={"universe": new_universe})


def _gold_history(weeks: int = 180) -> pd.DataFrame:
    dates = pd.date_range("2022-01-07", periods=weeks, freq="W-FRI")
    gold_log_returns = np.array(
        [
            0.012 if index % 4 in (0, 1) else -0.008
            for index in range(weeks)
        ],
        dtype=float,
    )
    gold_basis = 1800.0 * np.exp(np.cumsum(gold_log_returns))
    return pd.DataFrame(
        {
            "date": dates.date,
            "close_usd": gold_basis,
            "adj_close_usd": gold_basis,
        }
    )


def _equity_history(
    *,
    ticker: str,
    gold_history: pd.DataFrame,
    positive_beta: float,
    negative_beta: float,
    alpha: float = 0.001,
) -> pd.DataFrame:
    gold_basis = pd.to_numeric(gold_history["adj_close_usd"], errors="coerce").to_numpy(dtype=float)
    gold_log_returns = np.log(gold_basis[1:] / gold_basis[:-1])
    stock_log_returns = np.where(
        gold_log_returns > 0,
        (positive_beta * gold_log_returns) + alpha,
        (negative_beta * gold_log_returns) + alpha,
    )
    stock_basis = np.empty(len(gold_basis), dtype=float)
    stock_basis[0] = 10.0
    stock_basis[1:] = stock_basis[0] * np.exp(np.cumsum(stock_log_returns))
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": pd.to_datetime(gold_history["date"]).dt.date,
            "return_basis_usd": stock_basis,
            "normalization_status": "OK",
        }
    )


def test_tool_a_pipeline_ranks_structural_names_and_skips_inverse(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _activate_for_test(load_app_config(ProjectPaths.discover()).app, "GOLD")
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    gold_history = _gold_history()
    normalized_equity_histories = {
        "NEM": _equity_history(
            ticker="NEM",
            gold_history=gold_history,
            positive_beta=2.0,
            negative_beta=1.2,
        ),
        "GOLD": _equity_history(
            ticker="GOLD",
            gold_history=gold_history,
            positive_beta=0.7,
            negative_beta=0.7,
        ),
    }

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        snapshot_refresh_run_id="refresh-run",
    )

    assert result.overall_status == "PASS"
    latest_as_of_date = result.tool_a_outputs["as_of_date"].max()
    latest_rows = result.tool_a_outputs[
        result.tool_a_outputs["as_of_date"] == latest_as_of_date
    ].set_index("ticker")

    assert bool(latest_rows.loc["NEM", "score_eligible"]) is True
    assert int(latest_rows.loc["NEM", "tool_a_rank"]) == 1
    assert latest_rows.loc["NEM", "profile_label"] == "CONVEX"
    assert latest_rows.loc["NEM", "structural_gamma_core"] < 0
    assert pd.notna(latest_rows.loc["NEM", "total_volatility_52w"])
    assert pd.notna(latest_rows.loc["NEM", "residual_volatility_52w"])
    assert pd.notna(latest_rows.loc["NEM", "downside_volatility_52w"])
    assert bool(latest_rows.loc["GOLD", "score_eligible"]) is False
    assert latest_rows.loc["GOLD", "score_eligibility_reason"] == "LOW_LINKAGE_STRUCTURAL_SIGNAL"
    assert pd.isna(latest_rows.loc["GOLD", "tool_a_rank"])
    assert pd.notna(latest_rows.loc["GOLD", "total_volatility_52w"])
    assert result.summary["tool_a_output_row_count"] == result.summary["latest_snapshot_row_count"]
    assert result.summary["tool_a_output_candidate_date_count"] == 1
    assert result.summary["tool_a_output_built_group_count"] == 2
    assert result.summary["tool_a_output_unrestricted_group_count"] > result.summary[
        "tool_a_output_built_group_count"
    ]
    assert "output_assembly" in result.summary["tool_a_stage_timings"]


def test_tool_a_pipeline_marks_short_history_as_ineligible(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    gold_history = _gold_history(weeks=36)
    normalized_equity_histories = {
        "NEM": _equity_history(
            ticker="NEM",
            gold_history=gold_history,
            positive_beta=1.4,
            negative_beta=1.1,
        )
    }

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        snapshot_refresh_run_id="refresh-run",
    )

    latest_row = result.tool_a_outputs.sort_values("as_of_date").iloc[-1]
    assert bool(latest_row["score_eligible"]) is False
    assert latest_row["score_eligibility_reason"] in {
        "INSUFFICIENT_ELIGIBLE_STRUCTURAL_WINDOWS",
        "LOW_CONFIDENCE_STRUCTURAL_SIGNAL",
    }


def test_tool_a_pipeline_withholds_rows_when_normalization_is_blocked(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _activate_for_test(load_app_config(ProjectPaths.discover()).app, "FRES.L")
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )
    gold_history = _gold_history()
    blocked_history = _equity_history(
        ticker="FRES.L",
        gold_history=gold_history,
        positive_beta=1.8,
        negative_beta=1.1,
    )
    blocked_history.loc[blocked_history.index[-30::5], "normalization_status"] = "STALE_FX"
    normalized_equity_histories = {"FRES.L": blocked_history}

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        snapshot_refresh_run_id="refresh-run",
    )

    latest_row = result.tool_a_outputs.sort_values("as_of_date").iloc[-1]
    assert bool(latest_row["score_eligible"]) is False
    assert latest_row["score_eligibility_reason"] == "UNACCEPTABLE_NORMALIZATION_STATUS"
    assert latest_row["confidence_label"] == "WITHHELD"
    assert latest_row["profile_label"] == "SCORE_WITHHELD"
    assert latest_row["normalization_issue_summary"] == "STALE_FX"
    assert "withheld" in str(latest_row["tool_a_summary_explanation"]).lower()


def test_tool_a_pipeline_fails_cleanly_on_empty_inputs(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="test-hash",
    )

    result = execute_tool_a_profile_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        gold_history=pd.DataFrame(),
        normalized_equity_histories={},
        snapshot_refresh_run_id="refresh-run",
    )

    assert result.overall_status == "FAIL"
    assert result.tool_a_outputs.empty


def test_tool_a_output_build_restricts_to_latest_snapshot_candidate_dates():
    app_config = load_app_config(ProjectPaths.discover()).app
    metrics = _synthetic_structural_metrics(
        {
            "AEM": [date(2026, 1, 2), date(2026, 1, 9), date(2026, 1, 16)],
            "NEM": [date(2026, 1, 2), date(2026, 1, 9), date(2026, 1, 16), date(2026, 1, 23)],
            "VAU.AX": [date(2026, 1, 2), date(2026, 1, 9)],
        }
    )
    volatility = _synthetic_volatility_diagnostics(metrics)

    reference = _rank_tool_a_outputs(
        _build_tool_a_outputs(
            structural_window_metrics=metrics,
            volatility_diagnostics=volatility,
            app_config=app_config,
            run_context=_SyntheticRunContext(),
            snapshot_refresh_run_id="foundation-run",
            restrict_to_latest_snapshot_dates=False,
        )
    )
    optimized = _rank_tool_a_outputs(
        _build_tool_a_outputs(
            structural_window_metrics=metrics,
            volatility_diagnostics=volatility,
            app_config=app_config,
            run_context=_SyntheticRunContext(),
            snapshot_refresh_run_id="foundation-run",
        )
    )

    assert len(optimized.index) < len(reference.index)
    assert set(optimized["as_of_date"].dropna().tolist()) == {
        date(2026, 1, 9),
        date(2026, 1, 16),
        date(2026, 1, 23),
    }
    assert optimized.attrs["output_build_stats"]["candidate_date_count"] == 3
    pd.testing.assert_frame_equal(
        _latest_by_ticker(reference),
        _latest_by_ticker(optimized),
        check_dtype=False,
        check_exact=False,
        atol=1e-9,
        rtol=1e-9,
    )


def test_display_windows_never_change_rank_or_scoring():
    """Codex Phase-2 P0 guard: appending 2Y/5Y display rows — even ELIGIBLE with extreme
    betas that WOULD move confidence/counts/core if they leaked — must leave every scoring/
    rank field byte-identical. Display rows only populate the new *_2y/*_5y columns."""
    app_config = load_app_config(ProjectPaths.discover()).app
    dates = {
        "AEM": [date(2026, 1, 9), date(2026, 1, 16)],
        "NEM": [date(2026, 1, 9), date(2026, 1, 16)],
        "VAU.AX": [date(2026, 1, 9), date(2026, 1, 16)],
    }
    base = _synthetic_structural_metrics(dates)
    # Add decision-boundary + deliberate-tie subjects so the DISCRETE protected fields
    # (eligible_structural_window_count, score_eligible, tool_a_rank) are load-bearing —
    # not just the continuous score/count fields. CLAUDE.md: exclusion tests use a
    # borderline subject + healthy control; determinism tests include ties and NA.
    edge_dates = [date(2026, 1, 9), date(2026, 1, 16)]
    edge_rows: list[dict[str, object]] = []
    for as_of in edge_dates:
        # BRD: only 2 ELIGIBLE scoring windows (3Y is LOW_OBSERVATION — the degraded/NA
        # window). Its eligible count sits at 2; if the 2 ELIGIBLE 2Y/5Y display rows
        # leaked into scoring, the count would jump 2 -> 4 and could flip score_eligible.
        for window_id, status, weeks in (
            ("6M", "ELIGIBLE", 26), ("12M", "ELIGIBLE", 52), ("3Y", "LOW_OBSERVATION", 60),
        ):
            edge_rows.append({
                "ticker": "BRD", "as_of_date": as_of, "window_id": window_id,
                "window_status": status, "structural_delta": 1.30, "gamma_value": -0.2,
                "asymmetry_ratio": 1.1, "up_beta": 1.2, "down_beta": 1.4, "r_squared": 0.9,
                "week_count": weeks, "normalization_issue_summary": None,
            })
        # TIA / TIB: identical scoring inputs -> a deliberate score tie (rank tiebreak).
        for tie_ticker in ("TIA", "TIB"):
            for window_id, weeks in (("6M", 26), ("12M", 52), ("3Y", 156)):
                edge_rows.append({
                    "ticker": tie_ticker, "as_of_date": as_of, "window_id": window_id,
                    "window_status": "ELIGIBLE", "structural_delta": 1.50, "gamma_value": -0.2,
                    "asymmetry_ratio": 1.1, "up_beta": 1.35, "down_beta": 1.65, "r_squared": 0.9,
                    "week_count": weeks, "normalization_issue_summary": None,
                })
    base = pd.concat([base, pd.DataFrame(edge_rows)], ignore_index=True)
    volatility = _synthetic_volatility_diagnostics(base)
    # Give the tie pair identical volatility so their scores tie EXACTLY (determinism).
    tie_mask = volatility["ticker"].isin(["TIA", "TIB"])
    for col in ("total_volatility_52w", "residual_volatility_52w", "downside_volatility_52w"):
        volatility.loc[tie_mask, col] = float(volatility.loc[tie_mask, col].iloc[0])

    extra_rows: list[dict[str, object]] = []
    for r in base[["ticker", "as_of_date"]].drop_duplicates().itertuples(index=False):
        for window_id, weeks in (("2Y", 104), ("5Y", 260)):
            # One ticker's display rows carry a normalization issue: if it were read from
            # the full frame instead of scoring_frame it would leak into eligibility.
            issue = "STALE_FX" if r.ticker == "NEM" else None
            extra_rows.append({
                "ticker": r.ticker, "as_of_date": r.as_of_date, "window_id": window_id,
                "window_status": "ELIGIBLE", "structural_delta": 99.0, "gamma_value": 5.0,
                "asymmetry_ratio": 9.0, "up_beta": 50.0, "down_beta": 50.0,
                "r_squared": 0.99, "week_count": weeks, "normalization_issue_summary": issue,
            })
    candidate = pd.concat([base, pd.DataFrame(extra_rows)], ignore_index=True)

    def _build(metrics: pd.DataFrame) -> pd.DataFrame:
        return _rank_tool_a_outputs(_build_tool_a_outputs(
            structural_window_metrics=metrics, volatility_diagnostics=volatility,
            app_config=app_config, run_context=_SyntheticRunContext(),
            snapshot_refresh_run_id="foundation-run",
        ))

    baseline = _build(base)
    with_display = _build(candidate)
    protected = [
        "ticker", "as_of_date", "tool_a_score", "tool_a_rank", "confidence_score",
        "confidence_label", "profile_label", "score_eligible", "score_eligibility_reason",
        "eligible_structural_window_count", "positive_delta_window_count",
        "structural_delta_core", "structural_gamma_core", "up_beta_core", "down_beta_core",
        "asymmetry_ratio_core", "anchor_window_id", "volatility_anchor_window_id",
        # explicit invariant fields with their own leak paths (normalization issue is read
        # from scoring_frame; stability derives from the eligible scoring frame)
        "normalization_issue_summary", "delta_stability_score",
    ]
    pd.testing.assert_frame_equal(
        baseline[protected].reset_index(drop=True),
        with_display[protected].reset_index(drop=True),
        check_dtype=False, check_exact=False, atol=1e-9, rtol=1e-9,
    )
    wd = with_display
    # eligibility counts the SCORING windows only: 3 for full names, 2 for the boundary BRD
    # (never the 5 a leak would produce). This is the load-bearing discrete assertion.
    assert (wd.loc[wd["ticker"] != "BRD", "eligible_structural_window_count"] == 3).all()
    assert (wd.loc[wd["ticker"] == "BRD", "eligible_structural_window_count"] == 2).all()
    # the normalization issue on NEM's DISPLAY rows must not reach the scoring output
    assert wd.loc[wd["ticker"] == "NEM", "normalization_issue_summary"].isna().all()
    # the new display columns ARE populated from the (extreme) display rows
    assert (wd["up_beta_2y"] == 50.0).all()
    assert (wd["window_status_5y"] == "ELIGIBLE").all()
    # the deliberate tie resolves deterministically: identical inputs -> identical score
    latest = wd[wd["as_of_date"] == max(edge_dates)].set_index("ticker")
    assert abs(float(latest.loc["TIA", "tool_a_score"]) - float(latest.loc["TIB", "tool_a_score"])) < 1e-9
    assert pd.notna(latest.loc["TIA", "tool_a_rank"]) and pd.notna(latest.loc["TIB", "tool_a_rank"])


def _rank_tool_a_outputs(outputs: pd.DataFrame) -> pd.DataFrame:
    ranked = rank_tool_a_outputs(outputs)
    return ranked.sort_values(
        ["as_of_date", "tool_a_rank", "ticker"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)


def _latest_by_ticker(outputs: pd.DataFrame) -> pd.DataFrame:
    latest = _latest_snapshot(outputs).sort_values("ticker").reset_index(drop=True)
    return latest[sorted(latest.columns)]


def _synthetic_structural_metrics(dates_by_ticker: dict[str, list[date]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for ticker_index, (ticker, dates) in enumerate(dates_by_ticker.items()):
        for date_index, as_of_date in enumerate(dates):
            base_delta = 1.15 + (0.12 * ticker_index) + (0.03 * date_index)
            for window_id, weeks, adjustment in (
                ("6M", 26, 0.02),
                ("12M", 52, 0.0),
                ("3Y", 156, -0.03),
            ):
                structural_delta = base_delta + adjustment
                rows.append(
                    {
                        "ticker": ticker,
                        "as_of_date": as_of_date,
                        "window_id": window_id,
                        "window_status": "ELIGIBLE",
                        "structural_delta": structural_delta,
                        "gamma_value": -0.18 - (0.01 * ticker_index),
                        "asymmetry_ratio": 1.15 + (0.02 * ticker_index),
                        "up_beta": structural_delta * 0.9,
                        "down_beta": structural_delta * 1.1,
                        "r_squared": 0.92,
                        "week_count": weeks,
                        "normalization_issue_summary": None,
                    }
                )
    return pd.DataFrame(rows)


def _synthetic_volatility_diagnostics(structural_metrics: pd.DataFrame) -> pd.DataFrame:
    groups = structural_metrics[["ticker", "as_of_date"]].drop_duplicates()
    rows = []
    for index, row in enumerate(groups.itertuples(index=False)):
        rows.append(
            {
                "ticker": row.ticker,
                "as_of_date": row.as_of_date,
                "total_volatility_52w": 0.25 + (index * 0.001),
                "residual_volatility_52w": 0.18 + (index * 0.001),
                "downside_volatility_52w": 0.2 + (index * 0.001),
                "volatility_anchor_window_id": "12M",
            }
        )
    return pd.DataFrame(rows)
