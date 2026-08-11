"""Ticker-page producer tests (plan §11 model-unit gates)."""

from datetime import date

import pandas as pd
import pytest

import golden_vector.model.ticker_page as ticker_page_module
from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.app.ticker_page_state import (
    STATUS_OK,
    load_gold_response,
    load_performance_series,
    load_research_series,
    load_score_percentiles,
)
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_COLUMNS,
    PERCENTILES_COLUMNS,
    PERFORMANCE_COLUMNS,
    RESEARCH_SERIES_COLUMNS,
)
from golden_vector.ingestion.persist_ticker_page import persist_ticker_page_artifacts
from golden_vector.model.gold_lines import GoldLine, evaluate
from golden_vector.model.ticker_page import (
    build_gold_response_pack,
    build_performance_series,
    build_research_series,
    build_score_percentiles,
)
from golden_vector.screening.manual_store import upsert_company_input
from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.pipeline import compute_tool_b_in_memory
from tests.helpers import build_test_paths

TICKERS = ["AEM", "AGI"]
INTERIOR_GOLD = 3000.0
SPOT_GOLD = 3500.0


# --------------------------------------------------------------------------
# fixtures / builders
# --------------------------------------------------------------------------


def _only_active_tickers(app_config, *tickers: str):
    targets = {ticker.upper() for ticker in tickers}
    new_tickers = [
        ticker.model_copy(update={"active": ticker.ticker in targets})
        for ticker in app_config.universe.tickers
    ]
    return app_config.model_copy(
        update={"universe": app_config.universe.model_copy(update={"tickers": new_tickers})}
    )


def _with_systemic_threshold(app_config, threshold: int):
    dial = app_config.ticker_page.dial.model_copy(update={"systemic_min_tickers": threshold})
    ticker_page = app_config.ticker_page.model_copy(update={"dial": dial})
    return app_config.model_copy(update={"ticker_page": ticker_page})


def _manual_payload(ticker: str, *, aisc: float = 1300.0) -> dict[str, object]:
    return {
        "ticker": ticker,
        "production_oz": 1_000_000,
        "aisc_usd_per_oz": aisc,
        "cash_cost_usd_per_oz": 900,
        "royalty_rate": 0.03,
        "sustaining_capex_musd": 150,
        "da_musd": 100,
        "interest_expense_musd": 40,
        "tax_rate": 0.30,
        "reserve_life_years": 12,
        "net_debt_musd": 500,
        "ebitda_ltm_musd": 900,
    }


def _market_snapshots() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "snapshot_date": date(2026, 6, 1),
                "share_price_usd": 60.0,
                "market_cap_usd": 6_000_000_000.0,
                "shares_outstanding": 100_000_000.0,
                "normalization_status": "OK",
            }
            for ticker in TICKERS
        ]
    )


def _gold_history() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-05-29"), "adj_close_usd": 3400.0},
            {"date": pd.Timestamp("2026-06-01"), "adj_close_usd": SPOT_GOLD},
        ]
    )


@pytest.fixture()
def pack_inputs(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _only_active_tickers(load_app_config(ProjectPaths.discover()).app, *TICKERS)
    bootstrap_manual_screening_data(paths, tickers=TICKERS)
    for index, ticker in enumerate(TICKERS):
        upsert_company_input(
            paths, ticker=ticker, values=_manual_payload(ticker, aisc=1300.0 + 100 * index)
        )
    manual_data = load_manual_screening_data(paths, tickers=TICKERS)
    return {
        "paths": paths,
        "app_config": app_config,
        "manual_data": manual_data,
        "normalized_market_snapshots": _market_snapshots(),
        "official_fundamentals": None,
        "gold_history": _gold_history(),
        "snapshot_refresh_run_id": "refresh-run",
        "snapshot_as_of_date": "2026-06-01",
        "source_run_id": "ticker-page-run",
    }


def _builder_kwargs(pack_inputs):
    return {
        key: value for key, value in pack_inputs.items() if key not in {"paths"}
    }


# --------------------------------------------------------------------------
# 1. gold response pack
# --------------------------------------------------------------------------


def test_pack_lines_reproduce_tool_b_at_an_untested_interior_gold(pack_inputs):
    pack, diagnostics = build_gold_response_pack(**_builder_kwargs(pack_inputs))

    assert list(pack.columns) == list(GOLD_RESPONSE_COLUMNS)
    assert set(pack["finance_source"]) == {"our", "yahoo"}
    our = pack[pack["finance_source"] == "our"].set_index("ticker")
    assert sorted(our.index) == sorted(TICKERS)
    assert set(our["gold_response_status"]) == {"OK"}
    assert not diagnostics.empty
    assert bool(diagnostics["passed"].all())

    interior = compute_tool_b_in_memory(
        app_config=pack_inputs["app_config"],
        manual_data=pack_inputs["manual_data"],
        normalized_market_snapshots=pack_inputs["normalized_market_snapshots"],
        gold_price_assumption=INTERIOR_GOLD,
        snapshot_refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-06-01",
        source_run_id="ticker-page-run",
        official_fundamentals=None,
        finance_source="our",
    ).set_index("ticker")

    for ticker in TICKERS:
        for metric in ("forward_revenue_musd", "forward_ebitda_musd", "forward_eps"):
            line = GoldLine(
                slope=float(our.loc[ticker, f"line_slope_{metric}"]),
                intercept=float(our.loc[ticker, f"line_intercept_{metric}"]),
            )
            assert evaluate(line, INTERIOR_GOLD) == pytest.approx(
                float(interior.loc[ticker, metric]), rel=1e-9, abs=1e-6
            )


def test_pack_spot_values_match_the_spot_run_and_use_true_spot(pack_inputs):
    pack, _ = build_gold_response_pack(**_builder_kwargs(pack_inputs))
    our = pack[pack["finance_source"] == "our"].set_index("ticker")

    # True spot, never Tool B's configured $4,000 default (plan §3.2).
    assert set(our["spot_gold_usd"]) == {SPOT_GOLD}
    assert SPOT_GOLD != pack_inputs["app_config"].screening_params.default_gold_price_assumption
    assert set(our["spot_gold_date"]) == {"2026-06-01"}

    spot_run = compute_tool_b_in_memory(
        app_config=pack_inputs["app_config"],
        manual_data=pack_inputs["manual_data"],
        normalized_market_snapshots=pack_inputs["normalized_market_snapshots"],
        gold_price_assumption=SPOT_GOLD,
        snapshot_refresh_run_id="refresh-run",
        snapshot_as_of_date="2026-06-01",
        source_run_id="ticker-page-run",
        official_fundamentals=None,
        finance_source="our",
    ).set_index("ticker")

    for ticker in TICKERS:
        assert our.loc[ticker, "spot_margin_usd_per_oz"] == pytest.approx(
            float(spot_run.loc[ticker, "cash_margin_usd_per_oz"])
        )
        assert our.loc[ticker, "spot_fcf_yield"] == pytest.approx(
            float(spot_run.loc[ticker, "fcf_yield"])
        )
        # Stressed forward leverage is derived (Tool B ships only trailing `leverage`).
        assert our.loc[ticker, "spot_leverage_stressed"] == pytest.approx(
            float(spot_run.loc[ticker, "net_debt_musd"])
            / float(spot_run.loc[ticker, "forward_ebitda_musd"])
        )
        assert our.loc[ticker, "aisc_usd_per_oz"] == pytest.approx(
            float(spot_run.loc[ticker, "aisc_usd_per_oz"])
        )


def _kinked_tool_b(kinked_tickers: set[str]):
    real = compute_tool_b_in_memory

    def wrapper(**kwargs):
        frame = real(**kwargs)
        gold = float(kwargs["gold_price_assumption"])
        if abs(gold - 4000.0) < 0.01:  # bend the interior probe only
            mask = frame["ticker"].isin(kinked_tickers)
            frame.loc[mask, "forward_ebitda_musd"] = (
                pd.to_numeric(frame.loc[mask, "forward_ebitda_musd"], errors="coerce") * 1.5
            )
        return frame

    return wrapper


def test_pack_degrades_only_the_kinked_ticker(pack_inputs, monkeypatch):
    monkeypatch.setattr(
        ticker_page_module, "compute_tool_b_in_memory", _kinked_tool_b({"AGI"})
    )
    pack, diagnostics = build_gold_response_pack(**_builder_kwargs(pack_inputs))
    our = pack[pack["finance_source"] == "our"].set_index("ticker")

    assert our.loc["AGI", "gold_response_status"] == "DEGRADED_NONLINEAR"
    assert "forward_ebitda_musd" in our.loc["AGI", "gold_response_reason"]
    assert "4000" in our.loc["AGI", "gold_response_reason"]
    # Healthy control row is untouched.
    assert our.loc["AEM", "gold_response_status"] == "OK"
    failed = diagnostics[~diagnostics["passed"]]
    assert set(failed["ticker"]) == {"AGI"}
    assert set(failed["metric"]) == {"forward_ebitda_musd"}


def test_pack_raises_on_systemic_nonlinearity(pack_inputs, monkeypatch):
    monkeypatch.setattr(
        ticker_page_module, "compute_tool_b_in_memory", _kinked_tool_b(set(TICKERS))
    )
    kwargs = _builder_kwargs(pack_inputs)
    kwargs["app_config"] = _with_systemic_threshold(kwargs["app_config"], 2)

    with pytest.raises(ValueError, match="systemic gold-response linearity failure"):
        build_gold_response_pack(**kwargs)


def test_pack_degrades_yahoo_source_only_when_it_raises(pack_inputs, monkeypatch):
    real = compute_tool_b_in_memory

    def wrapper(**kwargs):
        if kwargs.get("finance_source") == "yahoo":
            raise RuntimeError("yahoo fundamentals unavailable")
        return real(**kwargs)

    monkeypatch.setattr(ticker_page_module, "compute_tool_b_in_memory", wrapper)
    pack, _ = build_gold_response_pack(**_builder_kwargs(pack_inputs))

    yahoo = pack[pack["finance_source"] == "yahoo"]
    assert set(yahoo["gold_response_status"]) == {"DEGRADED_INPUTS"}
    assert yahoo["gold_response_reason"].str.contains("yahoo fundamentals unavailable").all()
    assert set(pack[pack["finance_source"] == "our"]["gold_response_status"]) == {"OK"}


# --------------------------------------------------------------------------
# 2. percentiles
# --------------------------------------------------------------------------


def _score_config(app_config, keys: list[str]):
    metrics = [m for m in app_config.ticker_page.score_builder.metrics if m.key in keys]
    builder = app_config.ticker_page.score_builder.model_copy(update={"metrics": metrics})
    ticker_page = app_config.ticker_page.model_copy(update={"score_builder": builder})
    return app_config.model_copy(update={"ticker_page": ticker_page})


@pytest.fixture()
def score_config():
    app_config = load_app_config(ProjectPaths.discover()).app
    return _score_config(
        app_config,
        [
            "down_beta_core",
            "asymmetry_ratio_core",
            "margin_pct",
            "survival_distance",
        ],
    )


def _tool_a_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            # deliberate tie on down_beta_core between AAA and BBB
            {
                "ticker": "AAA",
                "as_of_date": "2026-06-01",
                "score_eligible": True,
                "down_beta_core": 1.0,
                "up_beta_core": 1.5,
                "asymmetry_ratio_core": 1.5,
            },
            {
                "ticker": "BBB",
                "as_of_date": "2026-06-01",
                "score_eligible": True,
                "down_beta_core": 1.0,
                "up_beta_core": 2.0,
                "asymmetry_ratio_core": 2.0,
            },
            {  # maximally favourable regime: down <= 0 < up
                "ticker": "CCC",
                "as_of_date": "2026-06-01",
                "score_eligible": True,
                "down_beta_core": -0.2,
                "up_beta_core": 1.2,
                "asymmetry_ratio_core": -6.0,
            },
            {  # negative up beta -> ratio undefined
                "ticker": "DDD",
                "as_of_date": "2026-06-01",
                "score_eligible": True,
                "down_beta_core": 0.8,
                "up_beta_core": -0.4,
                "asymmetry_ratio_core": -0.5,
            },
            {  # ineligible subject
                "ticker": "EEE",
                "as_of_date": "2026-06-01",
                "score_eligible": False,
                "down_beta_core": 0.1,
                "up_beta_core": 1.1,
                "asymmetry_ratio_core": 11.0,
            },
            {  # NA metric
                "ticker": "FFF",
                "as_of_date": "2026-06-01",
                "score_eligible": True,
                "down_beta_core": None,
                "up_beta_core": 1.0,
                "asymmetry_ratio_core": 1.0,
            },
        ]
    )


def _tool_b_frame(margin: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ticker": ticker, "as_of_date": "2026-06-01", "margin_pct": value}
            for ticker, value in margin.items()
        ]
    )


def _tool_d_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "as_of_date": "2026-06-01",
                "resilience_data_status": "OK",
                "survival_distance_to_interest_cover_pct": 0.4,
            },
            {
                "ticker": "BBB",
                "as_of_date": "2026-06-01",
                "resilience_data_status": "DEGRADED",
                "survival_distance_to_interest_cover_pct": 0.9,
            },
        ]
    )


def _percentiles(score_config) -> pd.DataFrame:
    return build_score_percentiles(
        app_config=score_config,
        tool_a_latest=_tool_a_frame(),
        tool_b_latest_by_source={
            "our": _tool_b_frame({"AAA": 0.30, "BBB": 0.10, "CCC": 0.20}),
            "yahoo": _tool_b_frame({"AAA": 0.05, "BBB": 0.40, "CCC": 0.20}),
        },
        tool_c_latest=pd.DataFrame(),
        tool_d_latest=_tool_d_frame(),
        source_run_ids={},
    )


def test_percentiles_schema_and_source_coverage(score_config):
    frame = _percentiles(score_config)
    assert list(frame.columns) == list(PERCENTILES_COLUMNS)
    assert not frame.duplicated(subset=["ticker", "finance_source", "metric_key"]).any()

    # tool_b metric differs per source; tool_a metric is identical across sources.
    margin = frame[frame["metric_key"] == "margin_pct"].set_index(["ticker", "finance_source"])
    assert margin.loc[("AAA", "our"), "raw_value"] == pytest.approx(0.30)
    assert margin.loc[("AAA", "yahoo"), "raw_value"] == pytest.approx(0.05)

    down = frame[frame["metric_key"] == "down_beta_core"].set_index(["ticker", "finance_source"])
    assert down.loc[("AAA", "our"), "raw_value"] == down.loc[("AAA", "yahoo"), "raw_value"]
    assert down.loc[("AAA", "our"), "pct_low_good"] == pytest.approx(
        down.loc[("AAA", "yahoo"), "pct_low_good"]
    )


def test_percentiles_ties_na_and_ineligibility(score_config):
    frame = _percentiles(score_config)
    down = frame[
        (frame["metric_key"] == "down_beta_core") & (frame["finance_source"] == "our")
    ].set_index("ticker")

    # AAA/BBB tie -> identical average-rank percentile.
    assert down.loc["AAA", "pct_high_good"] == pytest.approx(down.loc["BBB", "pct_high_good"])
    # NA metric.
    assert not bool(down.loc["FFF", "metric_available"])
    assert down.loc["FFF", "metric_reason"] == "value_missing"
    assert down.loc["FFF", "pct_high_good"] is None or pd.isna(down.loc["FFF", "pct_high_good"])
    # Ineligible subject excluded from the pool with an explicit reason...
    assert not bool(down.loc["EEE", "rank_eligible"])
    assert down.loc["EEE", "rank_exclusion_reason"] == "score_ineligible"
    assert pd.isna(down.loc["EEE", "pct_high_good"])
    # ...while healthy controls still rank, and the cohort excludes both.
    assert bool(down.loc["AAA", "rank_eligible"])
    assert set(down["eligible_peer_count"]) == {4}


def test_percentiles_asymmetry_sign_rule(score_config):
    frame = _percentiles(score_config)
    ratio = frame[
        (frame["metric_key"] == "asymmetry_ratio_core") & (frame["finance_source"] == "our")
    ].set_index("ticker")

    # down <= 0 < up -> maximally favourable regime (mirrors model/scoring.py:59-60).
    assert ratio.loc["CCC", "pct_high_good"] == pytest.approx(100.0)
    assert ratio.loc["CCC", "pct_low_good"] == pytest.approx(0.0)
    assert ratio.loc["CCC", "metric_reason"] == "max_favourable_beta_regime"
    # Negative up beta -> undefined.
    assert not bool(ratio.loc["DDD", "metric_available"])
    assert ratio.loc["DDD", "metric_reason"] == "ratio_undefined_for_beta_signs"
    # Pool contains only both-positive-beta, eligible rows: AAA + BBB.
    # (CCC is the forced-100 regime, DDD/FFF have undefined beta signs, EEE is ineligible.)
    assert set(ratio["eligible_peer_count"]) == {2}
    assert not bool(ratio.loc["FFF", "metric_available"])


def test_percentiles_tool_d_requires_ok_status(score_config):
    frame = _percentiles(score_config)
    survival = frame[
        (frame["metric_key"] == "survival_distance") & (frame["finance_source"] == "our")
    ].set_index("ticker")

    assert bool(survival.loc["AAA", "metric_available"])
    assert not bool(survival.loc["BBB", "metric_available"])
    assert survival.loc["BBB", "rank_exclusion_reason"] == "resilience_data_not_ok"
    # Emitted for both sources with identical values (source-independent tool).
    yahoo = frame[
        (frame["metric_key"] == "survival_distance") & (frame["finance_source"] == "yahoo")
    ].set_index("ticker")
    assert yahoo.loc["AAA", "raw_value"] == survival.loc["AAA", "raw_value"]


# --------------------------------------------------------------------------
# 3. performance series
# --------------------------------------------------------------------------


def _daily(start: str, days: int, *, column: str, base: float, skip: set[str] | None = None):
    dates = pd.bdate_range(start=start, periods=days)
    rows = []
    for index, day in enumerate(dates):
        if skip and str(day.date()) in skip:
            continue
        rows.append({"date": day, column: base + index})
    return pd.DataFrame(rows)


@pytest.fixture()
def chart_config():
    return load_app_config(ProjectPaths.discover()).app


def test_performance_shared_rebase_gap_and_late_start(chart_config):
    equity = _daily("2024-01-01", 420, column="return_basis_usd", base=100.0)
    gold = _daily("2024-01-01", 420, column="adj_close_usd", base=2000.0)
    # GDX starts late and misses one date entirely (a visible gap, never bridged).
    gdx = _daily("2024-03-01", 380, column="adj_close_local", base=30.0, skip={"2025-01-02"})
    gdxj = _daily("2024-01-01", 420, column="adj_close_local", base=40.0)
    as_of = pd.Timestamp(equity["date"].max())

    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={"gdx": gdx, "gdxj": gdxj},
        ticker="aem",
        equity_as_of_date=as_of,
        series_source_run_ids={"stock": "foundation-run", "gdx": "bench-run"},
    )

    assert list(frame.columns) == list(PERFORMANCE_COLUMNS)
    assert set(frame["ticker"]) == {"AEM"}
    assert set(frame["currency_basis"]) == {"USD"}
    assert set(frame["view"]) == {"price", "rebased"}

    one_year = frame[frame["horizon"] == "1Y"]
    # One shared rebase date across every series in the horizon.
    assert one_year["rebase_date"].nunique() == 1
    rebase_date = one_year["rebase_date"].iloc[0]
    # Every series is 100 at the rebase date in the rebased view.
    at_rebase = one_year[(one_year["view"] == "rebased") & (one_year["date"] == rebase_date)]
    assert set(at_rebase["series"]) == {"stock", "gold", "gdx", "gdxj"}
    assert at_rebase["value"].round(6).eq(100.0).all()

    # GDX's missing date is a null row, not a bridged value.
    gap = one_year[
        (one_year["series"] == "gdx")
        & (one_year["view"] == "price")
        & (one_year["date"] == pd.Timestamp("2025-01-02"))
    ]
    assert len(gap) == 1
    assert pd.isna(gap["value"].iloc[0])
    stock_same_day = one_year[
        (one_year["series"] == "stock")
        & (one_year["view"] == "price")
        & (one_year["date"] == pd.Timestamp("2025-01-02"))
    ]
    assert stock_same_day["value"].notna().all()

    # gdx starts after the 3Y window start -> late_start.
    three_year = frame[frame["horizon"] == "3Y"]
    assert bool(three_year[three_year["series"] == "gdx"]["late_start"].all())
    assert not bool(three_year[three_year["series"] == "stock"]["late_start"].any())
    # 3Y is weekly (W-FRI), 1Y is daily.
    weekly_dates = sorted(set(three_year[three_year["series"] == "stock"]["date"]))
    assert all(day.dayofweek == 4 for day in weekly_dates)
    assert len(weekly_dates) < one_year[one_year["series"] == "stock"]["date"].nunique()


def test_performance_marks_stale_and_missing_benchmarks(chart_config):
    equity = _daily("2025-01-01", 300, column="return_basis_usd", base=100.0)
    gold = _daily("2025-01-01", 300, column="adj_close_usd", base=2000.0)
    stale = _daily("2025-01-01", 200, column="adj_close_local", base=30.0)
    as_of = pd.Timestamp(equity["date"].max())

    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={"gdx": stale},
        ticker="AEM",
        equity_as_of_date=as_of,
        series_source_run_ids={},
    )

    gdx = frame[frame["series"] == "gdx"]
    assert set(gdx["series_status"]) == {"STALE_OMITTED"}
    assert gdx["value"].isna().all()
    assert set(gdx["date"]) == {as_of}
    assert gdx["series_reason"].str.contains("behind the equity as-of").all()

    gdxj = frame[frame["series"] == "gdxj"]
    assert set(gdxj["series_status"]) == {"MISSING"}
    assert gdxj["value"].isna().all()

    assert set(frame[frame["series"] == "stock"]["series_status"]) == {"OK"}


def test_performance_without_equity_returns_empty_contract_frame(chart_config):
    frame = build_performance_series(
        app_config=chart_config,
        equity_history=pd.DataFrame(),
        gold_history=_daily("2025-01-01", 30, column="adj_close_usd", base=2000.0),
        benchmark_histories={},
        ticker="AEM",
        equity_as_of_date=pd.Timestamp("2025-02-10"),
    )
    assert frame.empty
    assert list(frame.columns) == list(PERFORMANCE_COLUMNS)


# --------------------------------------------------------------------------
# 4. research series
# --------------------------------------------------------------------------


def _weekly_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "as_of_date": pd.Timestamp("2026-05-29"),
                "stock_weekly_log_return": 0.02,
                "gold_weekly_log_return": 0.01,
            },
            {
                "ticker": "AEM",
                "as_of_date": pd.Timestamp("2026-06-05"),
                "stock_weekly_log_return": -0.01,
                "gold_weekly_log_return": 0.00,
            },
        ]
    )


def _horizons_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "horizon_id": "1Y",
                "horizon_mode": "trading_days",
                "equity_return": 0.31,
            },
            {
                "ticker": "AEM",
                "horizon_id": "3Y",
                "horizon_mode": "trading_days",
                "equity_return": 0.75,
            },
        ]
    )


def _windows_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "as_of_date": pd.Timestamp("2026-05-29"),
                "window_id": "156w",
                "up_beta": 1.4,
                "down_beta": 0.9,
                "r_squared": 0.5,
                "week_count": 156,
                "window_status": "OK",
            },
            {  # newer as_of for the same window wins
                "ticker": "AEM",
                "as_of_date": pd.Timestamp("2026-06-05"),
                "window_id": "156w",
                "up_beta": 1.5,
                "down_beta": 0.8,
                "r_squared": 0.55,
                "week_count": 156,
                "window_status": "OK",
            },
            {
                "ticker": "AEM",
                "as_of_date": pd.Timestamp("2026-06-05"),
                "window_id": "52w",
                "up_beta": 1.1,
                "down_beta": 1.0,
                "r_squared": 0.4,
                "week_count": 52,
                "window_status": "SHORT",
            },
        ]
    )


def test_research_series_reshape():
    frame = build_research_series(
        ticker="aem",
        weekly_series_frame=_weekly_frame(),
        exploratory_horizons_frame=_horizons_frame(),
        structural_window_metrics_frame=_windows_frame(),
    )

    assert list(frame.columns) == list(RESEARCH_SERIES_COLUMNS)
    assert set(frame["ticker"]) == {"AEM"}
    assert set(frame["kind"]) == {"weekly", "horizon", "window_fit"}

    weekly = frame[frame["kind"] == "weekly"]
    assert len(weekly) == 2
    assert weekly["stock_return"].tolist() == [0.02, -0.01]
    assert weekly["gdx_return"].isna().all()

    horizon = frame[frame["kind"] == "horizon"].set_index("horizon_label")
    assert horizon.loc["1Y", "horizon_return"] == pytest.approx(0.31)
    assert horizon.loc["1Y", "basis"] == "trading_days"

    windows = frame[frame["kind"] == "window_fit"].set_index("window")
    assert len(windows) == 2
    assert windows.loc["156w", "up_beta"] == pytest.approx(1.5)  # latest as_of wins
    assert windows.loc["52w", "window_status"] == "SHORT"
    assert windows.loc["52w", "weeks"] == pytest.approx(52)


def test_research_series_empty_inputs_make_no_rows():
    frame = build_research_series(
        ticker="AEM",
        weekly_series_frame=None,
        exploratory_horizons_frame=pd.DataFrame(),
        structural_window_metrics_frame=None,
    )
    assert frame.empty
    assert list(frame.columns) == list(RESEARCH_SERIES_COLUMNS)


# --------------------------------------------------------------------------
# 5. persistence
# --------------------------------------------------------------------------


def test_persist_writes_run_stamped_and_latest_artifacts_readable_by_the_real_readers(
    tmp_path, pack_inputs, score_config, chart_config
):
    paths = pack_inputs["paths"]
    run_context = RunContext.start(paths, "ticker-page", {}, "config-hash-1")

    gold_response, diagnostics = build_gold_response_pack(**_builder_kwargs(pack_inputs))
    percentiles = _percentiles(score_config)
    equity = _daily("2025-01-01", 300, column="return_basis_usd", base=100.0)
    performance = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=_daily("2025-01-01", 300, column="adj_close_usd", base=2000.0),
        benchmark_histories={},
        ticker="AEM",
        equity_as_of_date=pd.Timestamp(equity["date"].max()),
    )
    research = build_research_series(
        ticker="AEM",
        weekly_series_frame=_weekly_frame(),
        exploratory_horizons_frame=_horizons_frame(),
        structural_window_metrics_frame=_windows_frame(),
    )

    written = persist_ticker_page_artifacts(
        paths,
        run_context,
        gold_response=gold_response,
        percentiles=percentiles,
        performance=performance,
        research_series=research,
        diagnostics=diagnostics,
        source_run_id=run_context.run_id,
        snapshot_refresh_run_id="refresh-run",
        parent_refresh_id="parent-refresh",
        config_hash="config-hash-1",
    )

    names = {path.name for path in written}
    for prefix in ("gold_response", "percentiles", "performance", "research_series"):
        assert f"{prefix}_output_{run_context.run_id}.parquet" in names
        assert f"{prefix}_latest_{run_context.run_id}.parquet" in names
        assert f"{prefix}_latest.parquet" in names
    assert "ticker_page_linearity_diagnostics.parquet" in names
    assert all(path.exists() for path in written)

    for loader in (
        load_gold_response,
        load_score_percentiles,
        load_performance_series,
        load_research_series,
    ):
        state = loader(paths)
        assert state.status == STATUS_OK, f"{loader.__name__}: {state.reason}"
        assert set(state.frame["source_run_id"]) == {run_context.run_id}
        assert set(state.frame["parent_refresh_id"]) == {"parent-refresh"}
        assert set(state.frame["config_hash"]) == {"config-hash-1"}
        assert set(state.frame["snapshot_refresh_run_id"]) == {"refresh-run"}
        assert state.frame["schema_version"].eq(1).all()
