from datetime import date

import pandas as pd
import pytest

import golden_vector.model.tool_d as tool_d_module
from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import ToolDConfig
from golden_vector.model.tool_d import (
    TOOL_D_OUTPUT_COLUMNS,
    ToolDExecutionInputs,
    build_tool_d_output_frame,
    compute_tool_d_outputs,
    latest_gold_price_from_history,
    tool_d_stress_scenario_presets,
)
from golden_vector.screening.manual_data import (
    LoadedManualScreeningData,
    bootstrap_manual_screening_data,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import upsert_company_input
from tests.helpers import build_test_paths


def test_compute_tool_d_outputs_uses_forward_ebitda_not_tool_b_leverage(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _only_active_tickers(load_app_config(ProjectPaths.discover()).app, "NEM")
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    upsert_company_input(paths, ticker="NEM", values=_manual_payload())
    manual_data = load_manual_screening_data(paths, tickers=["NEM"])
    tool_b_latest = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "source_run_id": "tool-b-run",
                # Deliberately bogus: Tool D must not read this trailing leverage column.
                "leverage": 999.0,
            }
        ]
    )

    output = compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=app_config,
            manual_data=manual_data,
            normalized_market_snapshots=_market_snapshot(),
            tool_b_latest=tool_b_latest,
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            snapshot_refresh_run_id="refresh-run",
            snapshot_as_of_date="2026-06-01",
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    expected_leverage = row["net_debt_musd"] / row["forward_ebitda_musd_at_g"]
    assert list(output.columns) == TOOL_D_OUTPUT_COLUMNS
    assert row["source_tool_b_run_id"] == "tool-b-run"
    assert row["leverage_stressed_at_g"] == pytest.approx(expected_leverage)
    assert row["leverage_stressed_at_g"] != 999.0
    assert row["forward_ebitda_musd_at_spot"] > row["forward_ebitda_musd_at_g"]
    assert row["tool_d_quality_rank"] == 100.0


def test_compute_tool_d_outputs_reuses_spot_tool_b_frame_for_spot_run(monkeypatch):
    calls: list[float] = []

    def fake_tool_b(**kwargs):
        gold = float(kwargs["gold_price_assumption"])
        calls.append(gold)
        return pd.DataFrame(
            [_tool_b_row("AAA", forward_ebitda=gold / 2.0, fcf_yield=0.01)]
        )

    monkeypatch.setattr(tool_d_module, "compute_tool_b_in_memory", fake_tool_b)
    manual_data = _manual_data([_manual_payload(ticker="AAA", aisc=1200, net_debt=500)])

    output = compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=object(),
            manual_data=manual_data,
            normalized_market_snapshots=pd.DataFrame(),
            tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            snapshot_refresh_run_id="refresh-run",
            snapshot_as_of_date="2026-06-01",
        ),
        config=ToolDConfig(),
        gold_price=4000.0,
        source_run_id="tool-d-run",
    )

    assert calls == [4000.0, 3600.0]
    assert output.iloc[0]["gold_price_used"] == 4000.0


def test_compute_tool_d_outputs_threads_official_fundamentals(monkeypatch):
    captured: list[pd.DataFrame | None] = []
    official = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "field_name": "net_debt_musd",
                "value": 123.0,
                "value_status": "OK",
            }
        ]
    )

    def fake_tool_b(**kwargs):
        captured.append(kwargs.get("official_fundamentals"))
        gold = float(kwargs["gold_price_assumption"])
        return pd.DataFrame(
            [_tool_b_row("AAA", forward_ebitda=gold / 2.0, fcf_yield=0.01)]
        )

    monkeypatch.setattr(tool_d_module, "compute_tool_b_in_memory", fake_tool_b)
    manual_data = _manual_data([_manual_payload(ticker="AAA", aisc=1200, net_debt=500)])

    compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=object(),
            manual_data=manual_data,
            normalized_market_snapshots=pd.DataFrame(),
            tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            snapshot_refresh_run_id="refresh-run",
            snapshot_as_of_date="2026-06-01",
            official_fundamentals=official,
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        source_run_id="tool-d-run",
    )

    assert len(captured) == 2
    for passed in captured:
        assert passed is official


def test_compute_tool_d_outputs_threads_finance_source_and_uses_source_values(
    monkeypatch,
):
    captured_sources: list[str] = []

    def fake_tool_b(**kwargs):
        captured_sources.append(kwargs["finance_source"])
        gold = float(kwargs["gold_price_assumption"])
        return pd.DataFrame(
            [
                _tool_b_row(
                    "AAA",
                    forward_ebitda=gold / 2.0,
                    fcf_yield=0.01,
                    net_debt=1000.0,
                    interest_expense=25.0,
                )
            ]
        )

    monkeypatch.setattr(tool_d_module, "compute_tool_b_in_memory", fake_tool_b)
    manual_data = _manual_data(
        [
            _manual_payload(
                ticker="AAA",
                aisc=1200,
                net_debt=500.0,
            )
        ]
    )

    output = compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=object(),
            manual_data=manual_data,
            normalized_market_snapshots=pd.DataFrame(),
            tool_b_latest=pd.DataFrame(
                [{"ticker": "AAA", "source_run_id": "tool-b-run"}]
            ),
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            snapshot_refresh_run_id="refresh-run",
            snapshot_as_of_date="2026-06-01",
            finance_source="yahoo",
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert captured_sources == ["yahoo", "yahoo"]
    assert row["finance_source"] == "yahoo"
    assert row["net_debt_musd"] == pytest.approx(1000.0)
    assert row["interest_expense_musd"] == pytest.approx(25.0)
    assert row["source_tool_b_run_id"] == "tool-d-run"


def test_compute_tool_d_yahoo_source_does_not_fallback_to_manual_debt_or_interest(
    monkeypatch,
):
    def fake_tool_b(**kwargs):
        gold = float(kwargs["gold_price_assumption"])
        row = _tool_b_row(
            "AAA",
            forward_ebitda=gold / 2.0,
            fcf_yield=0.01,
            net_debt=None,
            interest_expense=None,
        )
        row["source_run_id"] = kwargs["source_run_id"]
        return pd.DataFrame([row])

    monkeypatch.setattr(tool_d_module, "compute_tool_b_in_memory", fake_tool_b)
    manual_data = _manual_data(
        [
            _manual_payload(
                ticker="AAA",
                aisc=1200,
                net_debt=500.0,
            )
        ]
    )

    output = compute_tool_d_outputs(
        inputs=ToolDExecutionInputs(
            app_config=object(),
            manual_data=manual_data,
            normalized_market_snapshots=pd.DataFrame(),
            tool_b_latest=pd.DataFrame(
                [{"ticker": "AAA", "source_run_id": "persisted-tool-b-run"}]
            ),
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            snapshot_refresh_run_id="refresh-run",
            snapshot_as_of_date="2026-06-01",
            finance_source="yahoo",
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        source_run_id="workspace-tool-d-scenario",
    )
    row = output.iloc[0]

    assert row["finance_source"] == "yahoo"
    assert pd.isna(row["net_debt_musd"])
    assert pd.isna(row["interest_expense_musd"])
    assert "net_debt_musd" in row["missing_inputs"]
    assert "interest_expense_musd" in row["missing_inputs"]
    assert row["source_tool_b_run_id"] == "workspace-tool-d-scenario"


def test_tool_d_stress_scenario_presets_are_backend_owned():
    assert tool_d_stress_scenario_presets(4000.0) == [
        ("Spot", 4000.0),
        ("-15%", 3400.0),
        ("-25%", 3000.0),
        ("-35%", 2600.0),
        ("~$1,830", 1830.0),
        ("~$1,050", 1050.0),
    ]
    with pytest.raises(ValueError, match="finite positive"):
        tool_d_stress_scenario_presets(float("nan"))


def test_latest_gold_price_from_history_uses_price_precedence_and_validates_input():
    gold_history = pd.DataFrame(
        [
            {"date": "2026-06-01", "adj_close_usd": 4300.0, "close_usd": 4200.0, "close": 4100.0},
            {"date": "2026-06-02", "adj_close_usd": None, "close_usd": 4210.0, "close": 4110.0},
            {"date": "2026-06-03", "adj_close_usd": None, "close_usd": None, "close": 4120.0},
        ]
    )

    assert latest_gold_price_from_history(gold_history) == (4120.0, "2026-06-03")
    assert latest_gold_price_from_history(gold_history.iloc[[0]]) == (4300.0, "2026-06-01")
    assert latest_gold_price_from_history(gold_history.iloc[[1]]) == (4210.0, "2026-06-02")
    with pytest.raises(ValueError, match="empty"):
        latest_gold_price_from_history(pd.DataFrame())
    with pytest.raises(ValueError, match="missing date"):
        latest_gold_price_from_history(pd.DataFrame([{"close_usd": 4000.0}]))
    with pytest.raises(ValueError, match="no positive"):
        latest_gold_price_from_history(pd.DataFrame([{"date": "2026-06-01", "close_usd": -1.0}]))


def test_compute_tool_d_outputs_rejects_nonfinite_gold_price(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _only_active_tickers(load_app_config(ProjectPaths.discover()).app, "NEM")
    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    upsert_company_input(paths, ticker="NEM", values=_manual_payload())
    manual_data = load_manual_screening_data(paths, tickers=["NEM"])

    with pytest.raises(ValueError, match="gold_price must be a finite positive number"):
        compute_tool_d_outputs(
            inputs=ToolDExecutionInputs(
                app_config=app_config,
                manual_data=manual_data,
                normalized_market_snapshots=_market_snapshot(),
                tool_b_latest=pd.DataFrame([{"ticker": "NEM", "source_run_id": "tool-b-run"}]),
                spot_gold_usd=4000.0,
                spot_gold_date="2026-06-01",
                snapshot_refresh_run_id="refresh-run",
                snapshot_as_of_date="2026-06-01",
            ),
            config=ToolDConfig(),
            gold_price=float("inf"),
            source_run_id="tool-d-run",
        )


def test_tool_d_resilience_rank_uses_survival_components_fcf_context_only():
    manual_data = _manual_data(
        [
            _manual_payload(ticker="AAA", aisc=1500, net_debt=1000),
            _manual_payload(ticker="BBB", aisc=2000, net_debt=1000),
        ]
    )
    stressed = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=2000, fcf_yield=0.01),
            # BBB has much higher FCF yield, but worse survival/leverage components.
            _tool_b_row("BBB", forward_ebitda=1000, fcf_yield=0.02),
        ]
    )
    spot = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=3000, fcf_yield=0.05),
            _tool_b_row("BBB", forward_ebitda=1800, fcf_yield=0.90),
        ]
    )

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame(
            [
                {"ticker": "AAA", "source_run_id": "tool-b-run"},
                {"ticker": "BBB", "source_run_id": "tool-b-run"},
            ]
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    rows = output.set_index("ticker")

    assert rows.loc["AAA", "tool_d_quality_rank"] == 100.0
    assert rows.loc["BBB", "tool_d_quality_rank"] == 50.0
    assert rows.loc["BBB", "fcf_yield"] > rows.loc["AAA", "fcf_yield"]
    assert rows.loc["BBB", "fcf_yield"] == 0.90
    component_cols = [
        "survival_distance_component",
        "cost_curve_resilience_component",
        "fragility_resilience_component",
        "balance_sheet_resilience_component",
    ]
    assert rows.loc["AAA", "tool_d_quality_score"] == pytest.approx(
        rows.loc["AAA", component_cols].mean()
    )


def test_tool_d_quality_component_directions_come_from_config():
    manual_data = _manual_data(
        [
            _manual_payload(ticker="AAA", aisc=1200, net_debt=1000),
            _manual_payload(ticker="BBB", aisc=2400, net_debt=1000),
        ]
    )
    stressed = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=2000, fcf_yield=0.01),
            _tool_b_row("BBB", forward_ebitda=2000, fcf_yield=0.01),
        ]
    )
    spot = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=3000, fcf_yield=0.01),
            _tool_b_row("BBB", forward_ebitda=3000, fcf_yield=0.01),
        ]
    )

    default_output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame(
            [
                {"ticker": "AAA", "source_run_id": "tool-b-run"},
                {"ticker": "BBB", "source_run_id": "tool-b-run"},
            ]
        ),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    flipped_output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame(
            [
                {"ticker": "AAA", "source_run_id": "tool-b-run"},
                {"ticker": "BBB", "source_run_id": "tool-b-run"},
            ]
        ),
        config=ToolDConfig(
            quality_components={
                "survival_distance_to_interest_cover_pct": "high_good",
                "cost_curve_aisc_percentile": "high_good",
                "fragility_ebitda_pct_per_10pct_gold": "low_good",
                "leverage_stressed_at_g": "low_good",
            }
        ),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )

    assert default_output.iloc[0]["ticker"] == "AAA"
    assert flipped_output.iloc[0]["ticker"] == "BBB"


def test_tool_d_survival_lines_and_failure_order_are_backend_outputs():
    manual_data = _manual_data(
        [
            _manual_payload(
                ticker="AAA",
                aisc=1200,
                net_debt=1200,
            )
        ]
    )
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=2000, fcf_yield=0.01)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=3000, fcf_yield=0.01)])

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert row["breaks_even_at_gold_usd"] == 1200
    assert row["fcf_breakeven_gold_usd"] == pytest.approx(1350.0)
    assert row["interest_cover_gold_usd"] == pytest.approx(1100.0)
    assert row["debt_stress_gold_usd"] == pytest.approx(1400.0)
    assert row["survival_order_ladder"] == (
        "FCF breakeven $1,350/oz -> Breakeven $1,200/oz -> Interest cover $1,100/oz"
    )


def test_tool_d_missing_interest_is_insufficient_not_silently_ranked():
    manual_data = _manual_data(
        [
            _manual_payload(ticker="AAA", aisc=1200, net_debt=500)
            | {"interest_expense_musd": None}
        ]
    )
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=1000, fcf_yield=0.01)])
    spot = stressed.copy()

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert row["resilience_data_status"] == "INSUFFICIENT_INTEREST_DATA"
    assert pd.isna(row["interest_cover_gold_usd"])
    assert pd.isna(row["tool_d_quality_rank"])
    assert "missing_interest" in row["tool_d_tags"]


def test_tool_d_ebitda_nonpositive_makes_leverage_and_ev_ebitda_null():
    manual_data = _manual_data([_manual_payload(ticker="AAA", aisc=3500, net_debt=1000)])
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=-100, fcf_yield=-0.1)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=900, fcf_yield=0.05)])

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert pd.isna(row["leverage_stressed_at_g"])
    assert pd.isna(row["ev_ebitda_at_g"])
    assert "leverage_undefined_at_G" in row["tool_d_tags"]


def test_tool_d_all_missing_quality_components_leave_score_and_rank_null():
    manual_data = _manual_data(
        [_manual_payload(ticker="AAA", aisc=None, net_debt=None)]
    )
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=None, fcf_yield=0.0)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=None, fcf_yield=0.0)])

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert pd.isna(row["tool_d_quality_score"])
    assert pd.isna(row["tool_d_quality_rank"])


def test_tool_d_net_cash_flows_through_stressed_leverage_and_ev():
    manual_data = _manual_data(
        [_manual_payload(ticker="AAA", aisc=1400, net_debt=-500)]
    )
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=1000, fcf_yield=0.0)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=900, fcf_yield=0.0)])

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=pd.DataFrame([{"ticker": "AAA", "source_run_id": "tool-b-run"}]),
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert row["leverage_stressed_at_g"] == pytest.approx(-0.5)
    assert row["ev_ebitda_at_g"] == pytest.approx(2.5)
    assert "missing_debt" not in str(row["tool_d_tags"] or "")


def test_tool_d_ignores_decoy_leverage_in_consumed_frames():
    manual_data = _manual_data(
        [_manual_payload(ticker="AAA", aisc=1400, net_debt=500)]
    )
    stressed = pd.DataFrame(
        [_tool_b_row("AAA", forward_ebitda=1000, fcf_yield=0.0) | {"leverage": 999.0}]
    )
    spot = pd.DataFrame(
        [_tool_b_row("AAA", forward_ebitda=900, fcf_yield=0.0) | {"leverage": 777.0}]
    )
    latest = pd.DataFrame(
        [{"ticker": "AAA", "source_run_id": "tool-b-run", "leverage": 555.0}]
    )

    output = build_tool_d_output_frame(
        stressed_tool_b=stressed,
        spot_tool_b=spot,
        manual_data=manual_data,
        tool_b_latest=latest,
        config=ToolDConfig(),
        gold_price=3000.0,
        spot_gold_usd=4000.0,
        spot_gold_date="2026-06-01",
        source_run_id="tool-d-run",
    )
    row = output.iloc[0]

    assert row["leverage_stressed_at_g"] == pytest.approx(0.5)
    assert row["leverage_stressed_at_g"] not in {999.0, 777.0, 555.0}


def _only_active_tickers(app_config, *tickers: str):
    targets = {ticker.upper() for ticker in tickers}
    new_tickers = [
        ticker.model_copy(update={"active": ticker.ticker in targets})
        for ticker in app_config.universe.tickers
    ]
    return app_config.model_copy(
        update={"universe": app_config.universe.model_copy(update={"tickers": new_tickers})}
    )


def _market_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "snapshot_date": date(2026, 6, 1),
                "share_price_usd": 60.0,
                "market_cap_usd": 48_000_000_000.0,
                "shares_outstanding": 800_000_000.0,
                "normalization_status": "OK",
            }
        ]
    )


def _manual_payload(
    *,
    ticker: str = "NEM",
    aisc: float | None = 1300,
    net_debt: float | None = 2000,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "production_oz": 6_000_000,
        "aisc_usd_per_oz": aisc,
        "cash_cost_usd_per_oz": 900,
        "royalty_rate": 0.03,
        "sustaining_capex_musd": 900,
        "da_musd": 500,
        "interest_expense_musd": 100,
        "tax_rate": 0.30,
        "reserve_life_years": 12,
        "net_debt_musd": net_debt,
        "ebitda_ltm_musd": 5000,
    }


def _manual_data(rows: list[dict[str, object]]) -> LoadedManualScreeningData:
    return LoadedManualScreeningData(
        company_inputs=pd.DataFrame(rows),
        source_verification=pd.DataFrame(),
        reporting_calendar=pd.DataFrame(),
        stock_notes=pd.DataFrame(),
        store_path=ProjectPaths.discover().manual_screening_store_path,
        store_created=False,
        seeded_tickers=[],
        imported_csv_files=[],
    )


def _tool_b_row(
    ticker: str,
    *,
    forward_ebitda: float,
    fcf_yield: float,
    net_debt: float | None = None,
    interest_expense: float | None = None,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "as_of_date": date(2026, 6, 1),
        "snapshot_refresh_run_id": "refresh-run",
        "market_cap_musd": 3000,
        "screening_verdict": "WATCHLIST",
        "confidence": "VERIFIED",
        "fcf_yield": fcf_yield,
        "forward_ebitda_musd": forward_ebitda,
        "net_debt_musd": net_debt,
        "interest_expense_musd": interest_expense,
    }


def test_yahoo_fallback_error_names_both_sources():
    from golden_vector.serve.overview_tool_d import _yahoo_fallback_error

    message = _yahoo_fallback_error(RuntimeError("boom"))

    assert "Yahoo Fundamentals" in message
    assert "Our View" in message
    assert "boom" in message
