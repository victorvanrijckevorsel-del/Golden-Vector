from datetime import date

import pandas as pd
import pytest

import golden_vector.model.tool_d as tool_d_module
from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import ToolDConfig
from golden_vector.contracts.tool_d import TOOL_D_SCHEMA_VERSION
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
    assert row["tool_d_schema_version"] == TOOL_D_SCHEMA_VERSION == 4
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
            [_tool_b_row("AAA", forward_ebitda=gold / 2.0, aisc_margin_yield=0.01)]
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
            [_tool_b_row("AAA", forward_ebitda=gold / 2.0, aisc_margin_yield=0.01)]
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
                    aisc_margin_yield=0.01,
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
            aisc_margin_yield=0.01,
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
            _tool_b_row("AAA", forward_ebitda=2000, aisc_margin_yield=0.01),
            # BBB has much higher FCF yield, but worse survival/leverage components.
            _tool_b_row("BBB", forward_ebitda=1000, aisc_margin_yield=0.02),
        ]
    )
    spot = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=3000, aisc_margin_yield=0.05),
            _tool_b_row("BBB", forward_ebitda=1800, aisc_margin_yield=0.90),
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
    # The context yield carries the STRESSED run's value, with the spot pair
    # kept alongside — a stressed row must never quietly show spot economics.
    assert rows.loc["BBB", "aisc_margin_yield_at_g"] == 0.02
    assert rows.loc["BBB", "aisc_margin_yield_at_spot"] == 0.90
    assert rows.loc["AAA", "aisc_margin_yield_at_g"] == 0.01
    assert rows.loc["AAA", "aisc_margin_yield_at_spot"] == 0.05
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
            _tool_b_row("AAA", forward_ebitda=2000, aisc_margin_yield=0.01),
            _tool_b_row("BBB", forward_ebitda=2000, aisc_margin_yield=0.01),
        ]
    )
    spot = pd.DataFrame(
        [
            _tool_b_row("AAA", forward_ebitda=3000, aisc_margin_yield=0.01),
            _tool_b_row("BBB", forward_ebitda=3000, aisc_margin_yield=0.01),
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
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=2000, aisc_margin_yield=0.01)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=3000, aisc_margin_yield=0.01)])

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
    # C1: reported AISC already includes sustaining capital, so the cost
    # breakeven IS the reported AISC and no separate FCF-breakeven line exists.
    assert "fcf_breakeven_gold_usd" not in output.columns
    assert row["interest_cover_gold_usd"] == pytest.approx(1100.0)
    assert row["debt_stress_gold_usd"] == pytest.approx(1400.0)
    assert row["survival_order_ladder"] == (
        "Breakeven $1,200/oz -> Interest cover $1,100/oz"
    )


def test_tool_d_missing_interest_is_insufficient_not_silently_ranked():
    manual_data = _manual_data(
        [
            _manual_payload(ticker="AAA", aisc=1200, net_debt=500)
            | {"interest_expense_musd": None}
        ]
    )
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=1000, aisc_margin_yield=0.01)])
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
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=-100, aisc_margin_yield=-0.1)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=900, aisc_margin_yield=0.05)])

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
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=None, aisc_margin_yield=0.0)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=None, aisc_margin_yield=0.0)])

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
    stressed = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=1000, aisc_margin_yield=0.0)])
    spot = pd.DataFrame([_tool_b_row("AAA", forward_ebitda=900, aisc_margin_yield=0.0)])

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
        [_tool_b_row("AAA", forward_ebitda=1000, aisc_margin_yield=0.0) | {"leverage": 999.0}]
    )
    spot = pd.DataFrame(
        [_tool_b_row("AAA", forward_ebitda=900, aisc_margin_yield=0.0) | {"leverage": 777.0}]
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
    aisc_margin_yield: float,
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
        "aisc_margin_yield": aisc_margin_yield,
        "forward_ebitda_musd": forward_ebitda,
        "net_debt_musd": net_debt,
        "interest_expense_musd": interest_expense,
    }


def test_yahoo_scenario_error_names_requested_source_without_fallback():
    from golden_vector.serve.overview_tool_d import _yahoo_scenario_error

    message = _yahoo_scenario_error(RuntimeError("boom"))

    assert "Yahoo Fundamentals" in message
    assert "Our View" not in message
    assert "boom" in message


def test_tool_d_plain_yahoo_route_does_not_call_scenario_compute(tmp_path, monkeypatch):
    import golden_vector.serve.overview_tool_d as overview_tool_d
    from tests.helpers import call_wsgi_app
    from tests.test_redesign_routes import _full_app

    _paths, app = _full_app(tmp_path)

    def exploding_scenario(**kwargs):
        raise AssertionError("plain at-spot Yahoo must use persisted data")

    monkeypatch.setattr(overview_tool_d, "_compute_scenario_frame", exploding_scenario)

    response = call_wsgi_app(app, method="GET", path="/tool-d?fundamentals_source=yahoo")

    assert response["status"].startswith("200")
    body = response["body"]
    assert "yahoo-source-boom" not in body
    assert "Showing Our View data instead" not in body
    assert 'aria-current="true">Yahoo Fundamentals</a>' in body
    assert '<select name="fundamentals_source">' not in body


def test_tool_d_missing_source_uses_contract_reason_and_shared_degraded_state(
    tmp_path,
    monkeypatch,
):
    import golden_vector.serve.overview_tool_d as overview_tool_d
    from golden_vector.contracts.tool_d import (
        ToolDSourceSelection,
        YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
    )
    from tests.helpers import call_wsgi_app
    from tests.test_redesign_routes import _full_app

    _paths, app = _full_app(tmp_path)
    monkeypatch.setattr(
        overview_tool_d,
        "select_tool_d_source_rows",
        lambda *_args, **_kwargs: ToolDSourceSelection(
            frame=pd.DataFrame(),
            reason=YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
        ),
    )

    response = call_wsgi_app(
        app,
        method="GET",
        path="/tool-d?fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert YAHOO_TOOL_D_REBUILD_REQUIRED_REASON in body
    assert "notice-degraded" in body
    assert 'class="empty-state"' in body
    assert "Flip analysis is unavailable." in body
    assert "No names flip under the selected stress." not in body
    assert "Showing Our View data instead" not in body


def test_yahoo_scenario_error_states_requested_gold_price_was_not_applied():
    """The form keeps showing the requested gold price, so the scenario notice
    must say plainly that the price was NOT applied and the table is the spot run."""
    from golden_vector.serve.overview_tool_d import _yahoo_scenario_error

    message = _yahoo_scenario_error(
        RuntimeError("boom"), requested_gold=1800.0, spot_gold=2400.0
    )

    assert "Yahoo Fundamentals" in message
    assert "$1,800" in message
    assert "NOT applied" in message
    assert "persisted selected-source spot run" in message
    assert "$2,400" in message


def test_tool_d_route_yahoo_scenario_failure_names_requested_gold_price(
    tmp_path, monkeypatch
):
    import golden_vector.serve.overview_tool_d as overview_tool_d
    from tests.helpers import call_wsgi_app
    from tests.test_redesign_routes import _full_app

    _paths, app = _full_app(tmp_path)

    def exploding_scenario(**kwargs):
        raise RuntimeError("yahoo-source-boom")

    monkeypatch.setattr(overview_tool_d, "_compute_scenario_frame", exploding_scenario)

    response = call_wsgi_app(
        app,
        method="GET",
        path="/tool-d?gold_price=1800&fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "NOT applied" in body
    assert "persisted selected-source spot run" in body
    assert "Showing Our View data instead" not in body
    assert 'aria-current="true">Yahoo Fundamentals</a>' in body


def test_tool_d_invalid_gold_does_not_trigger_yahoo_scenario_compute(
    tmp_path, monkeypatch
):
    import golden_vector.serve.overview_tool_d as overview_tool_d
    from tests.helpers import call_wsgi_app
    from tests.test_redesign_routes import _full_app

    _paths, app = _full_app(tmp_path)

    def exploding_scenario(**kwargs):
        raise AssertionError("invalid gold must not trigger scenario compute")

    monkeypatch.setattr(overview_tool_d, "_compute_scenario_frame", exploding_scenario)

    response = call_wsgi_app(
        app,
        method="GET",
        path="/tool-d?gold_price=abc&fundamentals_source=yahoo",
    )

    assert response["status"].startswith("200")
    body = response["body"]
    assert "Gold price must be numeric" in body
    assert "Could not compute Yahoo Fundamentals stress scenario" not in body


def test_tool_d_flip_panel_excludes_degraded_rows(tmp_path, monkeypatch):
    """Canon: degraded rows are EXCLUDED from confident headlines. A flip-flagged
    row whose resilience_data_status is not OK must not reach the flip panel,
    while a healthy control row with the same flag does."""
    import golden_vector.serve.overview_tool_d as overview_tool_d
    from tests.helpers import call_wsgi_app
    from tests.test_redesign_routes import _full_app

    _paths, app = _full_app(tmp_path)

    frame = pd.DataFrame(
        [
            {
                "ticker": "HEALTHYCTL",
                "resilience_flip_flags": "flips to thin margin",
                "resilience_data_status": "OK",
                "tool_d_quality_rank": 80.0,
                "spot_gold_usd": 2400.0,
                "gold_price_used": 1800.0,
            },
            {
                "ticker": "DEGRADEDCO",
                "resilience_flip_flags": "flips to margin negative",
                "resilience_data_status": "INSUFFICIENT",
                "tool_d_explanation": (
                    "Not scored because the survival inputs are incomplete."
                ),
                "missing_inputs": "interest_expense_musd;net_debt_musd",
                "tool_d_quality_rank": None,
                "spot_gold_usd": 2400.0,
                "gold_price_used": 1800.0,
            },
        ]
    )
    monkeypatch.setattr(
        overview_tool_d, "_compute_scenario_frame", lambda **kwargs: frame
    )

    response = call_wsgi_app(app, method="GET", path="/tool-d?gold_price=1800")

    assert response["status"].startswith("200")
    flip_panel = response["body"].split("Who Flips Under This Stress", 1)[1].split(
        "</section>", 1
    )[0]
    assert "HEALTHYCTL" in flip_panel
    assert "DEGRADEDCO" not in flip_panel
    # The degraded row still appears in the full table, just not the headline.
    assert "DEGRADEDCO" in response["body"]
    assert "Resilience is unavailable for the selected financial source" in response["body"]
    assert "Not scored because the survival inputs are incomplete." in response["body"]
    assert "interest_expense_musd;net_debt_musd" in response["body"]


def test_tool_d_degraded_rows_cannot_move_healthy_components_scores_or_ranks():
    """C5 invariance: appending ANY number/magnitude of degraded rows leaves

    every healthy company's component percentiles, score, and rank identical.
    Degraded rows are excluded from the peer pool BEFORE percentiles compute,
    not masked after — masking after still shifted every healthy percentile.
    """
    healthy_manual = [
        _manual_payload(ticker="AAA", aisc=1500, net_debt=1000),
        _manual_payload(ticker="BBB", aisc=2000, net_debt=1000),
        _manual_payload(ticker="CCC", aisc=1200, net_debt=200),
    ]
    healthy_stressed = [
        _tool_b_row("AAA", forward_ebitda=2000, aisc_margin_yield=0.01),
        _tool_b_row("BBB", forward_ebitda=1000, aisc_margin_yield=0.02),
        _tool_b_row("CCC", forward_ebitda=2500, aisc_margin_yield=0.03),
    ]
    healthy_spot = [
        _tool_b_row("AAA", forward_ebitda=3000, aisc_margin_yield=0.05),
        _tool_b_row("BBB", forward_ebitda=1800, aisc_margin_yield=0.06),
        _tool_b_row("CCC", forward_ebitda=3600, aisc_margin_yield=0.07),
    ]
    latest_rows = [
        {"ticker": "AAA", "source_run_id": "tool-b-run"},
        {"ticker": "BBB", "source_run_id": "tool-b-run"},
        {"ticker": "CCC", "source_run_id": "tool-b-run"},
    ]

    def build(with_degraded: bool):
        manual = list(healthy_manual)
        stressed = list(healthy_stressed)
        spot = list(healthy_spot)
        latest = list(latest_rows)
        if with_degraded:
            # extreme AISC values that WOULD reshuffle every cost percentile if
            # they ever entered the pool; missing interest makes them degraded
            for ticker, extreme_aisc in (("BAD1", 1.0), ("BAD2", 99_999.0)):
                manual.append(
                    _manual_payload(ticker=ticker, aisc=extreme_aisc, net_debt=500)
                    | {"interest_expense_musd": None}
                )
                stressed.append(
                    _tool_b_row(ticker, forward_ebitda=1500, aisc_margin_yield=0.04)
                )
                spot.append(
                    _tool_b_row(ticker, forward_ebitda=2000, aisc_margin_yield=0.05)
                )
                latest.append({"ticker": ticker, "source_run_id": "tool-b-run"})
        return build_tool_d_output_frame(
            stressed_tool_b=pd.DataFrame(stressed),
            spot_tool_b=pd.DataFrame(spot),
            manual_data=_manual_data(manual),
            tool_b_latest=pd.DataFrame(latest),
            config=ToolDConfig(),
            gold_price=3000.0,
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            source_run_id="tool-d-run",
        )

    baseline = build(with_degraded=False).set_index("ticker")
    contested = build(with_degraded=True).set_index("ticker")

    watched_columns = [
        "cost_curve_aisc_percentile",
        "survival_distance_component",
        "cost_curve_resilience_component",
        "fragility_resilience_component",
        "balance_sheet_resilience_component",
        "tool_d_quality_score",
        "tool_d_quality_rank",
    ]
    for ticker in ("AAA", "BBB", "CCC"):
        for column in watched_columns:
            base_value = baseline.loc[ticker, column]
            contested_value = contested.loc[ticker, column]
            if pd.isna(base_value):
                assert pd.isna(contested_value), (ticker, column)
            else:
                assert contested_value == base_value, (ticker, column)

    # and the degraded rows themselves are explicitly out of every pool
    for ticker in ("BAD1", "BAD2"):
        assert contested.loc[ticker, "resilience_data_status"] != "OK"
        assert pd.isna(contested.loc[ticker, "cost_curve_aisc_percentile"])
        assert pd.isna(contested.loc[ticker, "tool_d_quality_score"])
        assert pd.isna(contested.loc[ticker, "tool_d_quality_rank"])
