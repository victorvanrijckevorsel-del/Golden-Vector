"""Ticker-page producer tests (plan §11 model-unit gates)."""

import json
from datetime import date

import pandas as pd
import pytest

import golden_vector.model.ticker_page as ticker_page_module
from golden_vector.app.config import load_app_config
from golden_vector.app.model_state import write_current_model_state_manifest
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
    TICKER_PAGE_SCHEMA_VERSIONS,
    GOLD_RESPONSE_COLUMNS,
    PERCENTILES_COLUMNS,
    PERFORMANCE_COLUMNS,
    RESEARCH_SERIES_COLUMNS,
)
from golden_vector.contracts.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
)
from golden_vector.ingestion.persist_ticker_page import persist_ticker_page_artifacts
from golden_vector.model.gold_lines import GoldLine, evaluate
from golden_vector.model.ticker_page import (
    build_fx_attribution_series,
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
        assert our.loc[ticker, "spot_aisc_margin_yield"] == pytest.approx(
            float(spot_run.loc[ticker, "aisc_margin_yield"])
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
                "finance_source": "our",
                "as_of_date": "2026-06-01",
                "resilience_data_status": "OK",
                "survival_distance_to_interest_cover_pct": 0.4,
            },
            {
                "ticker": "AAA",
                "finance_source": "yahoo",
                "as_of_date": "2026-06-01",
                "resilience_data_status": "OK",
                "survival_distance_to_interest_cover_pct": 0.1,
            },
            {
                "ticker": "BBB",
                "finance_source": "our",
                "as_of_date": "2026-06-01",
                "resilience_data_status": "DEGRADED",
                "survival_distance_to_interest_cover_pct": 0.9,
            },
            {
                "ticker": "BBB",
                "finance_source": "yahoo",
                "as_of_date": "2026-06-01",
                "resilience_data_status": "OK",
                "survival_distance_to_interest_cover_pct": 0.8,
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
    # Phase 2: Yahoo uses its own persisted Tool D cohort, never Our View's row.
    yahoo = frame[
        (frame["metric_key"] == "survival_distance") & (frame["finance_source"] == "yahoo")
    ].set_index("ticker")
    assert not yahoo.empty
    assert yahoo.loc[["AAA", "BBB"], "metric_available"].all()
    assert yahoo.loc["AAA", "raw_value"] == pytest.approx(0.1)
    assert yahoo.loc["BBB", "raw_value"] == pytest.approx(0.8)
    assert set(yahoo["eligible_peer_count"]) == {2}
    # Our View's BBB row is degraded, but that never contaminates Yahoo.
    assert bool(yahoo.loc["BBB", "rank_eligible"])
    assert set(survival["eligible_peer_count"]) == {1}


def test_percentiles_tool_d_missing_source_never_borrows_the_other_source(score_config):
    tool_d = _tool_d_frame()
    tool_d = tool_d[
        ~(
            tool_d["ticker"].eq("AAA")
            & tool_d["finance_source"].eq("yahoo")
        )
    ]
    frame = build_score_percentiles(
        app_config=score_config,
        tool_a_latest=_tool_a_frame(),
        tool_b_latest_by_source={
            "our": _tool_b_frame({"AAA": 0.30, "BBB": 0.10}),
            "yahoo": _tool_b_frame({"AAA": 0.05, "BBB": 0.40}),
        },
        tool_c_latest=pd.DataFrame(),
        tool_d_latest=tool_d,
        configured_universe=["AAA", "BBB"],
    )
    survival = frame[frame["metric_key"].eq("survival_distance")].set_index(
        ["ticker", "finance_source"]
    )

    missing = survival.loc[("AAA", "yahoo")]
    assert not bool(missing["metric_available"])
    assert missing["metric_reason"] == "no_source_row"
    assert pd.isna(missing["raw_value"])
    assert pd.isna(missing["pct_high_good"])
    # The Our sentinel remains visible only on the Our key.
    assert survival.loc[("AAA", "our"), "raw_value"] == pytest.approx(0.4)


def test_percentiles_tool_d_rejects_duplicate_composite_keys(score_config):
    tool_d = _tool_d_frame()
    tool_d = pd.concat([tool_d, tool_d.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match=r"duplicate composite key \(AAA, our\)"):
        build_score_percentiles(
            app_config=score_config,
            tool_a_latest=_tool_a_frame(),
            tool_b_latest_by_source={
                "our": _tool_b_frame({"AAA": 0.30, "BBB": 0.10}),
                "yahoo": _tool_b_frame({"AAA": 0.05, "BBB": 0.40}),
            },
            tool_c_latest=pd.DataFrame(),
            tool_d_latest=tool_d,
        )


def test_percentiles_are_persisted_rounded_to_one_decimal(score_config):
    """Plan §12 rule 2: percentiles persist at 0.1, so the embedded compare
    payload carries a tenth rather than a full float64 expansion.

    ``margin_pct``/our is a THREE-peer pool (0.10 / 0.20 / 0.30), so the raw
    percentiles are the repeating 33.333... and 66.666... — this test fails on
    the unrounded producer and cannot pass by accident on a pool whose exact
    percentiles happen to be whole numbers.
    """

    frame = _percentiles(score_config)
    margin = frame[
        (frame["metric_key"] == "margin_pct") & (frame["finance_source"] == "our")
    ].set_index("ticker")
    assert int(margin.loc["AAA", "eligible_peer_count"]) == 3

    # Exact equality, not approx: the point of the change is the stored digits.
    assert margin.loc["BBB", "pct_high_good"] == 33.3
    assert margin.loc["CCC", "pct_high_good"] == 66.7
    assert margin.loc["AAA", "pct_high_good"] == 100.0
    # Both columns, both directions.
    assert margin.loc["BBB", "pct_low_good"] == 100.0
    assert margin.loc["CCC", "pct_low_good"] == 66.7
    assert margin.loc["AAA", "pct_low_good"] == 33.3

    # Every persisted percentile in the artifact is already at 0.1 — a leaked
    # long float anywhere would break this.
    for column in ("pct_high_good", "pct_low_good"):
        present = frame[column].dropna().astype(float)
        assert not present.empty
        assert (present == present.round(1)).all()

    # Nulls are preserved as nulls — rounding never invents a percentile.
    ineligible = frame[~frame["rank_eligible"].astype(bool)]
    assert not ineligible.empty
    assert ineligible["pct_high_good"].isna().all()
    assert ineligible["pct_low_good"].isna().all()


def test_percentile_rounding_keeps_ties_tied(score_config):
    """§7 average-tie policy survives the persist rounding.

    The pool is chosen so the tied percentile REPEATS: two of three peers share
    a margin, so the average-rank percentile is 83.333… and the stored value can
    only be 83.3 if the rounding actually ran. On a pool whose exact percentiles
    are already whole numbers the assertion would be a tautology — rounding is
    deterministic, so identical inputs can never be split by it.
    """

    frame = build_score_percentiles(
        app_config=score_config,
        tool_a_latest=_tool_a_frame(),
        tool_b_latest_by_source={
            # BBB/CCC are a deliberate tie; AAA is the healthy control.
            "our": _tool_b_frame({"AAA": 0.10, "BBB": 0.30, "CCC": 0.30}),
            "yahoo": _tool_b_frame({"AAA": 0.05, "BBB": 0.40, "CCC": 0.20}),
        },
        tool_c_latest=pd.DataFrame(),
        tool_d_latest=_tool_d_frame(),
        source_run_ids={},
    )
    margin = frame[
        (frame["metric_key"] == "margin_pct") & (frame["finance_source"] == "our")
    ].set_index("ticker")
    assert int(margin.loc["BBB", "eligible_peer_count"]) == 3

    # Exact stored tenth on BOTH tied tickers — not merely equal to each other.
    assert margin.loc["BBB", "pct_high_good"] == 83.3
    assert margin.loc["CCC", "pct_high_good"] == 83.3
    assert margin.loc["BBB", "pct_low_good"] == 50.0
    assert margin.loc["CCC", "pct_low_good"] == 50.0
    # A healthy control that is NOT part of the tie still sorts apart from it.
    assert margin.loc["AAA", "pct_high_good"] == 33.3
    assert margin.loc["AAA", "pct_low_good"] == 100.0


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
    # C4: an index-to-100 value is not a "USD price" - the views are labelled.
    assert set(frame.loc[frame["view"] == "price", "currency_basis"]) == {"USD"}
    assert set(frame.loc[frame["view"] == "rebased", "currency_basis"]) == {"INDEX_100"}
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


def test_performance_without_equity_emits_explicit_missing_stock_states(chart_config):
    """C4: a missing stock series is an explicit per-series state - an empty

    frame would read as a healthy build with nothing to show.
    """
    frame = build_performance_series(
        app_config=chart_config,
        equity_history=pd.DataFrame(),
        gold_history=_daily("2025-01-01", 30, column="adj_close_usd", base=2000.0),
        benchmark_histories={},
        ticker="AEM",
        equity_as_of_date=pd.Timestamp("2025-02-10"),
    )
    assert not frame.empty
    assert list(frame.columns) == list(PERFORMANCE_COLUMNS)
    stock = frame[frame["series"] == "stock"]
    assert set(stock["series_status"]) == {"MISSING"}
    assert stock["series_reason"].str.contains("unavailable").all()
    gold_rows = frame[frame["series"] == "gold"]
    assert set(gold_rows["series_status"]) == {"OMITTED_NO_STOCK"}
    assert frame["value"].isna().all()


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


def test_research_series_empty_inputs_make_explicit_missing_kind_rows():
    """C9 (v2): an absent kind is an explicit state, never a silent hole."""
    frame = build_research_series(
        ticker="AEM",
        weekly_series_frame=None,
        exploratory_horizons_frame=pd.DataFrame(),
        structural_window_metrics_frame=None,
    )
    assert list(frame.columns) == list(RESEARCH_SERIES_COLUMNS)
    assert len(frame) == 3  # one MISSING status row per kind
    assert set(frame["kind"]) == {"weekly", "horizon", "window_fit"}
    assert set(frame["kind_status"]) == {"MISSING"}
    assert frame["kind_reason"].str.contains("no .* rows are available").all()


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
    equity_fx = equity.assign(
        currency="AUD",
        return_basis_local=equity["return_basis_usd"] / 0.65,
        fx_rate_to_usd=0.65,
        fx_source_date=equity["date"],
        fx_source_symbol="AUDUSD=X",
        normalization_status="OK",
    )
    fx_attribution = build_fx_attribution_series(
        app_config=chart_config,
        equity_history=equity_fx,
        ticker="AEM",
        common_end=pd.Timestamp(equity["date"].max()),
    )

    written = persist_ticker_page_artifacts(
        paths,
        run_context,
        gold_response=gold_response,
        percentiles=percentiles,
        fx_attribution=fx_attribution,
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

    # The loaders are manifest-first: a refresh must publish model state naming
    # these artifacts before they read OK (see test_ticker_page_stage.py).
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "refresh-run",
                "foundation_status": "PASS",
                "snapshot_as_of_date": "2026-08-10",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash-1",
        parent_refresh_id="parent-refresh",
        stage_timings={},
    )

    for loader, artifact in (
        (load_gold_response, "gold_response"),
        (load_score_percentiles, "percentiles"),
        (load_performance_series, "performance"),
        (load_research_series, "research_series"),
    ):
        state = loader(paths)
        assert state.status == STATUS_OK, f"{loader.__name__}: {state.reason}"
        assert set(state.frame["source_run_id"]) == {run_context.run_id}
        assert set(state.frame["parent_refresh_id"]) == {"parent-refresh"}
        assert set(state.frame["config_hash"]) == {"config-hash-1"}
        assert set(state.frame["snapshot_refresh_run_id"]) == {"refresh-run"}
        assert (
            state.frame["schema_version"].eq(TICKER_PAGE_SCHEMA_VERSIONS[artifact]).all()
        )


# --------------------------------------------------------------------------
# 6. adversarial-review regression gates
# --------------------------------------------------------------------------


def _asymmetry_only_config(app_config):
    return _score_config(app_config, ["asymmetry_ratio_core"])


def test_percentiles_never_leak_a_rank_onto_an_ineligible_row(score_config):
    """A percentile IS a rank. No row may carry one while rank_eligible is False."""

    frame = _percentiles(score_config)
    eligible = frame["rank_eligible"].astype("boolean").fillna(False)
    available = frame["metric_available"].astype("boolean").fillna(False)
    has_pct = frame["pct_high_good"].notna() | frame["pct_low_good"].notna()

    leaked = frame[(~eligible) & has_pct]
    assert leaked.empty, leaked[["ticker", "metric_key", "pct_high_good"]].to_dict("records")
    assert frame[~available]["pct_high_good"].isna().all()
    assert frame[~available]["pct_low_good"].isna().all()


def test_percentiles_max_favourable_row_with_a_null_ratio_stays_ranked_at_the_ceiling():
    """down_beta == 0 with a positive up beta and NO finite ratio.

    The ratio is undefined (divide by zero) but the RANKING is defined and
    maximal, so the row stays available + rank-eligible and carries the forced
    100/0 percentile. It must not be silently downgraded by the generic
    "no raw value" rule, and its forced percentile must not exceed the pool's
    own maximum -- 100 is the rank(pct=True) ceiling, so it ties it.
    """

    app_config = _asymmetry_only_config(load_app_config(ProjectPaths.discover()).app)
    tool_a = pd.DataFrame(
        [
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
                "up_beta_core": 3.0,
                "asymmetry_ratio_core": 3.0,
            },
            {  # subject: down beta exactly 0, ratio genuinely undefined/None
                "ticker": "ZERO",
                "as_of_date": "2026-06-01",
                "score_eligible": True,
                "down_beta_core": 0.0,
                "up_beta_core": 1.2,
                "asymmetry_ratio_core": None,
            },
        ]
    )
    frame = build_score_percentiles(
        app_config=app_config,
        tool_a_latest=tool_a,
        tool_b_latest_by_source={"our": pd.DataFrame(), "yahoo": pd.DataFrame()},
        tool_c_latest=pd.DataFrame(),
        tool_d_latest=pd.DataFrame(),
    )
    ours = frame[frame["finance_source"] == "our"].set_index("ticker")

    assert bool(ours.loc["ZERO", "metric_available"])
    assert bool(ours.loc["ZERO", "rank_eligible"])
    assert ours.loc["ZERO", "metric_reason"] == "max_favourable_beta_regime"
    assert pd.isna(ours.loc["ZERO", "raw_value"])
    assert ours.loc["ZERO", "pct_high_good"] == pytest.approx(100.0)
    assert ours.loc["ZERO", "pct_low_good"] == pytest.approx(0.0)

    # The forced percentile is at/above every in-pool row's (it ties the ceiling).
    in_pool_max = ours.loc[["AAA", "BBB"], "pct_high_good"].max()
    assert ours.loc["ZERO", "pct_high_good"] >= in_pool_max
    assert in_pool_max == pytest.approx(100.0)


def test_usd_series_picks_one_basis_and_keeps_its_gaps():
    """Never splice two price bases together.

    ``return_basis_usd`` (dividend-adjusted) and ``adj_close_usd`` sit at
    different LEVELS here. Coalescing per row would fill the middle gap with
    adj_close values and invent a price step that never happened.
    """

    dates = pd.bdate_range("2025-01-01", periods=10)
    return_basis = [100.0 + index for index in range(10)]
    for index in (4, 5, 6):
        return_basis[index] = None
    frame = pd.DataFrame(
        {
            "date": dates,
            "return_basis_usd": return_basis,
            "adj_close_usd": [900.0 + index for index in range(10)],
        }
    )

    series, price_basis = ticker_page_module._usd_series(
        frame, ("return_basis_usd", "adj_close_usd")
    )
    assert price_basis == "return_basis_usd"

    # The chosen basis keeps its gap: the three null dates simply are not there,
    # and NO adj_close level (>= 900) leaked into the series.
    assert len(series.index) == 7
    assert series.max() < 900.0
    for index in (4, 5, 6):
        assert dates[index] not in series.index


def test_usd_series_falls_back_only_when_the_first_basis_is_entirely_null():
    dates = pd.bdate_range("2025-01-01", periods=5)
    frame = pd.DataFrame(
        {
            "date": dates,
            "return_basis_usd": [None] * 5,
            "adj_close_usd": [900.0 + index for index in range(5)],
        }
    )
    series, price_basis = ticker_page_module._usd_series(
        frame, ("return_basis_usd", "adj_close_usd")
    )
    assert price_basis == "adj_close_usd"
    assert len(series.index) == 5
    assert series.iloc[0] == pytest.approx(900.0)


def test_benchmark_staleness_is_measured_in_trading_days_across_a_weekend(chart_config):
    """A Friday close read on the following Monday is ONE trading day old.

    Calendar-day counting made every normal weekend look like a 3-day outage.
    Config stays benchmark_max_staleness_days: 5, now honestly trading days.
    """

    equity = _daily("2024-01-01", 300, column="return_basis_usd", base=100.0)
    equity = equity[equity["date"] <= pd.Timestamp("2025-01-13")]
    gold = _daily("2024-01-01", 300, column="adj_close_usd", base=2000.0)
    gdx_all = _daily("2024-01-01", 300, column="adj_close_local", base=30.0)
    assert pd.Timestamp("2025-01-10").dayofweek == 4  # Friday
    assert pd.Timestamp("2025-01-13").dayofweek == 0  # Monday

    fresh = gdx_all[gdx_all["date"] <= pd.Timestamp("2025-01-10")]
    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={"gdx": fresh},
        ticker="AEM",
        equity_as_of_date=pd.Timestamp("2025-01-13"),
    )
    assert set(frame[frame["series"] == "gdx"]["series_status"]) == {"OK"}

    # Healthy control: a genuine >5 trading-day gap is still omitted.
    old = gdx_all[gdx_all["date"] <= pd.Timestamp("2025-01-02")]
    stale_frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={"gdx": old},
        ticker="AEM",
        equity_as_of_date=pd.Timestamp("2025-01-13"),
    )
    gdx_rows = stale_frame[stale_frame["series"] == "gdx"]
    assert set(gdx_rows["series_status"]) == {"STALE_OMITTED"}
    assert gdx_rows["series_reason"].str.contains("trading day").all()


def test_performance_emits_a_marker_when_an_ok_series_has_no_rows_in_a_window(
    chart_config,
):
    """An OK (fresh) series with zero in-window observations must never vanish."""

    equity = _daily("2019-01-01", 1900, column="return_basis_usd", base=100.0)
    gold = _daily("2019-01-01", 1900, column="adj_close_usd", base=2000.0)
    as_of = pd.Timestamp(equity["date"].max())
    # GDX is fresh (its last observation IS the as-of, so never STALE_OMITTED)
    # but has a single ancient block plus that one recent point, leaving the
    # shorter windows with (nearly) nothing.
    gdx_all = _daily("2019-01-01", 1900, column="adj_close_local", base=30.0)
    gdx = gdx_all[
        (gdx_all["date"] <= pd.Timestamp("2019-06-01")) | (gdx_all["date"] == as_of)
    ]

    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={"gdx": gdx},
        ticker="AEM",
        equity_as_of_date=as_of,
    )
    for horizon in chart_config.ticker_page.chart.horizons:
        rows = frame[(frame["series"] == "gdx") & (frame["horizon"] == horizon)]
        assert not rows.empty, f"gdx vanished from the {horizon} window"


def test_gold_response_degrades_when_an_interior_probe_has_no_value(
    pack_inputs, monkeypatch
):
    """Outer probes present but the interior/spot probe missing = UNTESTED.

    The line is fitted from the outer probes only, so a missing interior value
    means linearity was never checked where the page actually reads the line.
    """

    real = ticker_page_module.compute_tool_b_in_memory

    def patched(**kwargs):
        frame = real(**kwargs)
        gold = float(kwargs["gold_price_assumption"])
        if abs(gold - SPOT_GOLD) < 0.01:
            frame = frame.copy()
            mask = frame["ticker"].astype(str).str.upper() == "AEM"
            frame.loc[mask, "forward_ebitda_musd"] = None
        return frame

    monkeypatch.setattr(ticker_page_module, "compute_tool_b_in_memory", patched)
    pack, _ = build_gold_response_pack(**_builder_kwargs(pack_inputs))
    ours = pack[pack["finance_source"] == "our"].set_index("ticker")

    assert ours.loc["AEM", "gold_response_status"] == "DEGRADED_INPUTS"
    assert "forward_ebitda_musd" in ours.loc["AEM", "gold_response_reason"]
    assert ours.loc["AGI", "gold_response_status"] == "OK"  # healthy control


def test_gold_response_covers_yahoo_only_tickers(pack_inputs, monkeypatch):
    """A ticker only the yahoo source can price still gets BOTH rows."""

    real = ticker_page_module.compute_tool_b_in_memory

    def patched(**kwargs):
        frame = real(**kwargs)
        if str(kwargs.get("finance_source")) == "our":
            frame = frame[frame["ticker"].astype(str).str.upper() != "AGI"].copy()
        return frame

    monkeypatch.setattr(ticker_page_module, "compute_tool_b_in_memory", patched)
    pack, _ = build_gold_response_pack(**_builder_kwargs(pack_inputs))

    assert set(pack[pack["ticker"] == "AGI"]["finance_source"]) == {"our", "yahoo"}
    agi = pack[pack["ticker"] == "AGI"].set_index("finance_source")
    assert agi.loc["our", "gold_response_status"] == "DEGRADED_INPUTS"
    assert "no Tool B row for AGI" in agi.loc["our", "gold_response_reason"]
    # The yahoo row is REAL (it found its spot Tool B row and carries the
    # constants), not a "no Tool B row" placeholder. In this fixture yahoo has no
    # official forward fundamentals, so its own status is degraded for that
    # separate reason -- what matters is that the ticker was not erased.
    assert "no Tool B row" not in str(agi.loc["yahoo", "gold_response_reason"])
    assert pd.notna(agi.loc["yahoo", "market_cap_musd"])
    # Healthy control: the ticker present in BOTH runs still reads our=OK.
    aem = pack[pack["ticker"] == "AEM"].set_index("finance_source")
    assert aem.loc["our", "gold_response_status"] == "OK"


def test_gold_response_labels_the_margin_basis(pack_inputs):
    pack, _ = build_gold_response_pack(**_builder_kwargs(pack_inputs))
    assert set(pack["spot_margin_basis"]) == {"aisc"}


def test_research_weekly_frame_without_a_date_column_raises():
    weekly = pd.DataFrame(
        [{"stock_weekly_log_return": 0.01, "gold_weekly_log_return": 0.02}]
    )
    with pytest.raises(ValueError, match="as_of_date, date"):
        build_research_series(
            ticker="AEM",
            weekly_series_frame=weekly,
            exploratory_horizons_frame=None,
            structural_window_metrics_frame=None,
        )
    # An EMPTY frame is a legitimate zero-DATA contribution — it yields the
    # three explicit per-kind MISSING rows (C9), never a silent empty artifact.
    empty = build_research_series(
        ticker="AEM",
        weekly_series_frame=pd.DataFrame(),
        exploratory_horizons_frame=None,
        structural_window_metrics_frame=None,
    )
    assert len(empty) == 3
    assert set(empty["kind_status"]) == {"MISSING"}


def test_research_weeks_is_a_nullable_integer():
    frame = build_research_series(
        ticker="AEM",
        weekly_series_frame=None,
        exploratory_horizons_frame=None,
        structural_window_metrics_frame=_windows_frame(),
    )
    assert str(frame["weeks"].dtype) == "Int64"


# --------------------------------------------------------------------------
# C6: per-metric eligibility, Yahoo isolation, spot Tool D authority
# --------------------------------------------------------------------------


def _ev_config():
    app_config = load_app_config(ProjectPaths.discover()).app
    return _score_config(app_config, ["ev_ebitda", "aisc", "reserve_life"])


def _ev_tool_b_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": row["ticker"],
                "as_of_date": "2026-06-01",
                "ev_ebitda": row.get("ev_ebitda"),
                "aisc_usd_per_oz": row.get("aisc", 1400.0),
                "reserve_life_years": row.get("reserve_life", 10.0),
                "snapshot_normalization_status": row.get("snapshot_status", "OK"),
                "financial_data_status": row.get("financial_status", "OK"),
            }
            for row in rows
        ]
    )


def _ev_percentiles(config, *, yahoo_rows: list[dict]) -> pd.DataFrame:
    healthy = [
        {"ticker": "AAA", "ev_ebitda": 5.0},
        {"ticker": "BBB", "ev_ebitda": 8.0},
        {"ticker": "CCC", "ev_ebitda": 11.0},
    ]
    return build_score_percentiles(
        app_config=config,
        tool_a_latest=pd.DataFrame(),
        tool_b_latest_by_source={
            "our": _ev_tool_b_frame(healthy),
            "yahoo": _ev_tool_b_frame(healthy + yahoo_rows),
        },
        tool_c_latest=pd.DataFrame(),
        tool_d_latest=pd.DataFrame(),
        source_run_ids={},
    )


def test_c6_contaminated_yahoo_rows_cannot_move_healthy_cohorts():
    """C6: stale/contaminated/missing-status Yahoo financial rows are excluded

    from the cohort BEFORE percentiles, so healthy percentiles are invariant,
    and every ineligible row carries null percentiles with its reason.
    """
    config = _ev_config()
    baseline = _ev_percentiles(config, yahoo_rows=[])
    contested = _ev_percentiles(
        config,
        yahoo_rows=[
            # extreme values that WOULD reshuffle the pool if admitted
            {"ticker": "BAD1", "ev_ebitda": 0.1, "financial_status": "INCOMPLETE"},
            {"ticker": "BAD2", "ev_ebitda": 99.0, "financial_status": "STALE"},
            {"ticker": "BAD3", "ev_ebitda": 1.0, "financial_status": ""},  # unknown -> fail closed
            {"ticker": "BAD4", "ev_ebitda": 2.0, "snapshot_status": "STALE_FX"},
        ],
    )

    def ev_yahoo(frame):
        rows = frame[(frame["metric_key"] == "ev_ebitda") & (frame["finance_source"] == "yahoo")]
        return rows.set_index("ticker")

    base = ev_yahoo(baseline)
    cont = ev_yahoo(contested)
    for ticker in ("AAA", "BBB", "CCC"):
        assert cont.loc[ticker, "pct_low_good"] == base.loc[ticker, "pct_low_good"]
        assert cont.loc[ticker, "pct_high_good"] == base.loc[ticker, "pct_high_good"]
    assert set(base["eligible_peer_count"]) == {3}
    assert set(cont.loc[["AAA", "BBB", "CCC"], "eligible_peer_count"]) == {3}

    assert not cont.loc["BAD1", "metric_available"]
    assert cont.loc["BAD1", "metric_reason"] == "yahoo_financials_not_ok:INCOMPLETE"
    assert cont.loc["BAD3", "metric_reason"] == "financial_status_unknown"
    assert cont.loc["BAD4", "metric_reason"] == "snapshot_not_ok:STALE_FX"
    for ticker in ("BAD1", "BAD2", "BAD3", "BAD4"):
        assert pd.isna(cont.loc[ticker, "pct_high_good"])
        assert pd.isna(cont.loc[ticker, "pct_low_good"])


def test_c6_manual_mining_metrics_never_inherit_yahoo_financial_failure():
    """C6: AISC / reserve life are Our-View mining assumptions in either mode -

    a broken Yahoo financial status must not take them away, and their basis
    label says so explicitly.
    """
    config = _ev_config()
    frame = _ev_percentiles(
        config,
        yahoo_rows=[{"ticker": "DDD", "ev_ebitda": 7.0, "financial_status": "INCOMPLETE"}],
    )
    aisc = frame[(frame["metric_key"] == "aisc") & (frame["finance_source"] == "yahoo")]
    aisc = aisc.set_index("ticker")

    assert bool(aisc.loc["DDD", "metric_available"])  # yahoo failure is irrelevant
    assert aisc.loc["DDD", "basis"] == "Our View mining assumption"
    ev = frame[(frame["metric_key"] == "ev_ebitda") & (frame["finance_source"] == "yahoo")]
    assert not bool(ev.set_index("ticker").loc["DDD", "metric_available"])


def test_c6_custom_tool_d_scenario_cannot_enter_spot_ticker_build():
    """C6: the stage's spot assertion rejects a custom-gold Tool D artifact."""
    import pytest as _pytest

    from golden_vector.app.ticker_page_stage import _assert_tool_d_is_spot

    def v4_frame() -> pd.DataFrame:
        rows = []
        for ticker in ("AAA", "BBB"):
            for source in ("our", "yahoo"):
                row = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
                row.update(
                    {
                        "ticker": ticker,
                        "finance_source": source,
                        "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                        "as_of_date": "2026-06-01",
                        "gold_price_used": 4000.0,
                        "spot_gold_usd": 4000.0,
                        "resilience_data_status": "OK",
                    }
                )
                rows.append(row)
        return pd.DataFrame(rows, columns=TOOL_D_OUTPUT_COLUMNS)

    spot_frame = v4_frame()
    assert _assert_tool_d_is_spot(
        spot_frame, active_tickers=["AAA", "BBB"]
    ) is spot_frame

    scenario_frame = v4_frame()
    scenario_frame.loc[0, "gold_price_used"] = 3000.0
    with _pytest.raises(ValueError, match="at-spot"):
        _assert_tool_d_is_spot(scenario_frame, active_tickers=["AAA", "BBB"])

    missing_column_frame = v4_frame().drop(columns=["spot_gold_usd"])
    with _pytest.raises(ValueError, match="spot_gold_usd"):
        _assert_tool_d_is_spot(missing_column_frame, active_tickers=["AAA", "BBB"])


def test_tool_d_spot_v4_requires_both_sources_for_active_tool_b_universe():
    from golden_vector.app.ticker_page_stage import _assert_tool_d_is_spot

    rows = []
    for source in ("our", "yahoo"):
        row = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
        row.update(
            {
                "ticker": "AAA",
                "finance_source": source,
                "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
                "as_of_date": "2026-06-01",
                "gold_price_used": 4000.0,
                "spot_gold_usd": 4000.0,
                "resilience_data_status": "OK",
            }
        )
        rows.append(row)
    frame = pd.DataFrame(rows, columns=TOOL_D_OUTPUT_COLUMNS)

    with pytest.raises(ValueError, match=r"missing expected .*\(BBB, our\)"):
        _assert_tool_d_is_spot(frame, active_tickers=["AAA", "BBB"])


def test_tool_d_spot_v3_migration_is_explicit_our_only_and_rejects_mixed_versions():
    from golden_vector.app.ticker_page_stage import _assert_tool_d_is_spot

    legacy = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "finance_source": "our",
                "tool_d_schema_version": 3,
                "gold_price_used": 4000.0,
                "spot_gold_usd": 4000.0,
            },
            {
                "ticker": "BBB",
                "finance_source": "our",
                "tool_d_schema_version": 3,
                "gold_price_used": 4000.0,
                "spot_gold_usd": 4000.0,
            },
        ]
    )
    assert _assert_tool_d_is_spot(
        legacy, active_tickers=["AAA", "BBB"]
    ) is legacy

    yahoo = legacy.copy()
    yahoo.loc[0, "finance_source"] = "yahoo"
    with pytest.raises(ValueError, match="Our View rows only"):
        _assert_tool_d_is_spot(yahoo, active_tickers=["AAA", "BBB"])

    mixed = legacy.copy()
    mixed.loc[0, "tool_d_schema_version"] = TOOL_D_SCHEMA_VERSION
    with pytest.raises(ValueError, match="mixes unsupported schema versions"):
        _assert_tool_d_is_spot(mixed, active_tickers=["AAA", "BBB"])

    malformed = legacy.copy()
    malformed.loc[0, "tool_d_schema_version"] = None
    with pytest.raises(ValueError, match="missing or malformed"):
        _assert_tool_d_is_spot(malformed, active_tickers=["AAA", "BBB"])

    fractional = legacy.copy()
    fractional["tool_d_schema_version"] = 3.9
    with pytest.raises(ValueError, match="unsupported or fractional"):
        _assert_tool_d_is_spot(fractional, active_tickers=["AAA", "BBB"])


def test_c4_weekly_points_keep_actual_trading_dates_never_invented_fridays(chart_config):
    """C4: a source ending mid-week keeps its real last date - the artifact

    must never claim a date after the source data ends (the AEM 2026-08-14
    case: resample('W-FRI') relabelled an earlier observation as Friday).
    """
    # equity ends on a Tuesday
    equity = _daily("2022-01-03", 1000, column="return_basis_usd", base=100.0)
    last_real_date = pd.Timestamp(equity["date"].max())
    gold = _daily("2022-01-03", 1000, column="adj_close_usd", base=2000.0)

    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={},
        ticker="AEM",
        equity_as_of_date=last_real_date,
    )

    ok_rows = frame[frame["series_status"] == "OK"]
    assert not ok_rows.empty
    # No artifact date may exceed the true source end.
    assert pd.to_datetime(ok_rows["date"]).max() <= last_real_date
    # And source_last_date discloses the real end.
    stock_rows = ok_rows[ok_rows["series"] == "stock"]
    assert set(stock_rows["source_last_date"]) == {last_real_date}


def test_c4_stale_fx_rows_are_excluded_from_performance(chart_config):
    """C4: a non-OK normalized endpoint can never become a chart point."""
    equity = _daily("2025-01-01", 200, column="return_basis_usd", base=100.0)
    equity["normalization_status"] = "OK"
    # last five rows carry stale FX - they must vanish from the series
    equity.loc[equity.index[-5:], "normalization_status"] = "STALE_FX"
    clean_last = pd.Timestamp(equity.loc[equity.index[-6], "date"])
    gold = _daily("2025-01-01", 200, column="adj_close_usd", base=2000.0)

    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={},
        ticker="AEM",
        equity_as_of_date=pd.Timestamp(equity["date"].max()),
    )

    stock_rows = frame[(frame["series"] == "stock") & (frame["series_status"] == "OK")]
    assert not stock_rows.empty
    assert pd.to_datetime(stock_rows["date"]).max() <= clean_last
    assert set(stock_rows["source_last_date"]) == {clean_last}


def test_c4_no_rebased_value_exists_before_the_shared_anchor(chart_config):
    """C4: the rebased view starts AT the anchor; price view still shows the

    full window. A pre-anchor point divided by a future base is fabricated.
    """
    equity = _daily("2024-01-01", 420, column="return_basis_usd", base=100.0)
    gold = _daily("2024-01-01", 420, column="adj_close_usd", base=2000.0)
    # GDX starts three months late -> the shared anchor is its first date.
    gdx = _daily("2024-04-01", 355, column="adj_close_local", base=30.0)
    as_of = pd.Timestamp(equity["date"].max())

    frame = build_performance_series(
        app_config=chart_config,
        equity_history=equity,
        gold_history=gold,
        benchmark_histories={"gdx": gdx},
        ticker="AEM",
        equity_as_of_date=as_of,
    )

    three_year = frame[(frame["horizon"] == "3Y") & (frame["series_status"] == "OK")]
    anchor = three_year["rebase_date"].dropna().iloc[0]
    rebased = three_year[three_year["view"] == "rebased"]
    assert not rebased.empty
    assert pd.to_datetime(rebased["date"]).min() >= anchor
    # exactly 100 for EVERY series at the anchor
    at_anchor = rebased[rebased["date"] == anchor]
    assert set(at_anchor["series"]) == {"stock", "gold", "gdx"}
    assert (at_anchor["value"] == 100.0).all()
    # price view still covers dates before the anchor
    price = three_year[(three_year["view"] == "price") & (three_year["series"] == "stock")]
    assert pd.to_datetime(price["date"]).min() < anchor


def test_c9_horizon_rows_persist_the_full_retained_ladder():
    """C9 (v2): the UI reads gold return/delta, coverage, and exact period

    from persisted fields 1:1 — nothing is recomputed in a request handler.
    """
    horizons = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "horizon_id": "1Y",
                "horizon_mode": "trading_days",
                "equity_return": 0.31,
                "gold_return": 0.22,
                "gold_delta": 0.09,
                "coverage_flag": "FULL",
                "coverage_reason": None,
                "start_date": "2025-08-11",
                "end_date": "2026-08-10",
            }
        ]
    )

    frame = build_research_series(
        ticker="AEM",
        weekly_series_frame=None,
        exploratory_horizons_frame=horizons,
        structural_window_metrics_frame=None,
    )
    row = frame[frame["kind"] == "horizon"].iloc[0]

    assert row["horizon_return"] == pytest.approx(0.31)
    assert row["horizon_gold_return"] == pytest.approx(0.22)
    assert row["horizon_gold_delta"] == pytest.approx(0.09)
    assert row["horizon_coverage_flag"] == "FULL"
    assert row["horizon_start_date"] == pd.Timestamp("2025-08-11")
    assert row["horizon_end_date"] == pd.Timestamp("2026-08-10")
    assert row["kind_status"] == "OK"
    # absent kinds still carry explicit MISSING rows alongside
    assert set(frame.loc[frame["kind_status"] == "MISSING", "kind"]) == {
        "weekly",
        "window_fit",
    }
