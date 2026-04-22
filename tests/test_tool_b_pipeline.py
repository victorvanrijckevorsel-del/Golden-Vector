from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.screening.pipeline import execute_tool_b_pipeline
from tests.helpers import build_test_paths


def _write_manual_files(paths: ProjectPaths, company_inputs: pd.DataFrame, verification: pd.DataFrame) -> None:
    paths.ensure_runtime_dirs()
    company_inputs.to_csv(paths.manual_screening_dir / "company_inputs.csv", index=False)
    verification.to_csv(paths.manual_screening_dir / "source_verification.csv", index=False)
    pd.DataFrame(columns=["ticker", "next_financial_report_date", "next_production_report_date", "notes"]).to_csv(
        paths.manual_screening_dir / "reporting_calendar.csv",
        index=False,
    )


def _market_snapshots() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "snapshot_date": date(2026, 2, 1),
                "share_price_usd": 60.0,
                "market_cap_usd": 48_000_000_000.0,
                "shares_outstanding": 800_000_000.0,
            },
            {
                "ticker": "GOLD",
                "snapshot_date": date(2026, 2, 1),
                "share_price_usd": 18.0,
                "market_cap_usd": 23_400_000_000.0,
                "shares_outstanding": 1_300_000_000.0,
            },
        ]
    )


def test_tool_b_pipeline_builds_complete_row_when_manual_inputs_are_present(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    expected_tickers = {
        ticker.ticker
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_b_enabled
    }
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )

    company_inputs = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "production_oz": 6_000_000,
                "aisc_usd_per_oz": 1300,
                "cash_cost_usd_per_oz": 900,
                "royalty_rate": 0.03,
                "sustaining_capex_musd": 900,
                "da_musd": 500,
                "interest_expense_musd": 100,
                "tax_rate": 0.30,
                "reserve_life_years": 12,
                "net_debt_musd": 2000,
                "ebitda_ltm_musd": 5000,
            },
            {
                "ticker": "GOLD",
                "production_oz": 4_000_000,
                "aisc_usd_per_oz": 1500,
                "cash_cost_usd_per_oz": 1000,
                "royalty_rate": 0.02,
                "sustaining_capex_musd": 650,
                "da_musd": 350,
                "interest_expense_musd": 80,
                "tax_rate": 0.28,
                "reserve_life_years": 10,
                "net_debt_musd": 1500,
                "ebitda_ltm_musd": 4200,
            },
        ]
    )
    verification = pd.DataFrame(
        [
            {"ticker": ticker, "field_name": field_name, "verification_status": "VERIFIED"}
            for ticker in ("NEM", "GOLD")
            for field_name in company_inputs.columns
            if field_name != "ticker"
        ]
    )
    _write_manual_files(paths, company_inputs, verification)

    result = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=4000,
    )

    assert result.overall_status == "WARN"
    assert set(result.tool_b_outputs["ticker"]) == expected_tickers
    output = result.tool_b_outputs.set_index("ticker")
    assert output.loc["NEM", "confidence"] == "VERIFIED"
    assert output.loc["NEM", "screening_verdict"] in {"STRONG_CANDIDATE", "WATCHLIST", "SCREEN_OUT"}
    assert output.loc["NEM", "layer1_status"] in {"PASS", "FAIL"}
    assert pd.notna(output.loc["NEM", "tool_b_score"])
    assert pd.notna(output.loc["NEM", "tool_b_rank"])
    assert pd.isna(output.loc["NEM", "layer2_incomplete_reasons"])
    assert output.loc["GOLD", "confidence"] == "VERIFIED"
    uncovered_tickers = expected_tickers - {"NEM", "GOLD"}
    assert (output.loc[list(uncovered_tickers), "screening_verdict"] == "INCOMPLETE").all()
    assert result.summary["incomplete_row_count"] == len(uncovered_tickers)


def test_tool_b_pipeline_marks_missing_manual_data_as_incomplete(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )

    company_inputs = pd.DataFrame([{"ticker": "NEM", "production_oz": 6_000_000}])
    verification = pd.DataFrame(columns=["ticker", "field_name", "verification_status"])
    _write_manual_files(paths, company_inputs, verification)

    result = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=4000,
    )

    assert result.overall_status == "WARN"
    row = result.tool_b_outputs[result.tool_b_outputs["ticker"] == "NEM"].iloc[0]
    assert row["screening_verdict"] == "INCOMPLETE"
    assert row["confidence"] == "INCOMPLETE"
    assert "aisc_usd_per_oz" in row["missing_manual_fields"]
    assert pd.isna(row["tool_b_rank"])


def test_tool_b_pipeline_creates_missing_manual_templates_and_warns_cleanly(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 3500},
        config_hash="hash",
    )

    result = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=3500,
    )

    assert result.overall_status == "WARN"
    assert (paths.manual_screening_dir / "company_inputs.csv").exists()
    assert result.summary["manual_template_file_count"] == 3
    assert result.summary["incomplete_row_count"] == len(result.tool_b_outputs.index)


def test_tool_b_pipeline_emits_incomplete_row_when_snapshot_is_missing(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    expected_tickers = {
        ticker.ticker
        for ticker in app_config.universe.tickers
        if ticker.active and ticker.tool_b_enabled
    }
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )

    company_inputs = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "production_oz": 6_000_000,
                "aisc_usd_per_oz": 1300,
                "cash_cost_usd_per_oz": 900,
                "royalty_rate": 0.03,
                "sustaining_capex_musd": 900,
                "da_musd": 500,
                "interest_expense_musd": 100,
                "tax_rate": 0.30,
                "reserve_life_years": 12,
                "net_debt_musd": 2000,
                "ebitda_ltm_musd": 5000,
            },
            {
                "ticker": "GOLD",
                "production_oz": 4_000_000,
                "aisc_usd_per_oz": 1500,
                "cash_cost_usd_per_oz": 1000,
                "royalty_rate": 0.02,
                "sustaining_capex_musd": 650,
                "da_musd": 350,
                "interest_expense_musd": 80,
                "tax_rate": 0.28,
                "reserve_life_years": 10,
                "net_debt_musd": 1500,
                "ebitda_ltm_musd": 4200,
            },
        ]
    )
    verification = pd.DataFrame(
        [
            {"ticker": ticker, "field_name": field_name, "verification_status": "VERIFIED"}
            for ticker in ("NEM", "GOLD")
            for field_name in company_inputs.columns
            if field_name != "ticker"
        ]
    )
    _write_manual_files(paths, company_inputs, verification)

    result = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=_market_snapshots().iloc[[0]].copy(),
        gold_price_assumption=4000,
    )

    assert len(result.tool_b_outputs.index) == len(expected_tickers)
    missing_row = result.tool_b_outputs[result.tool_b_outputs["ticker"] == "GOLD"].iloc[0]
    assert missing_row["screening_verdict"] == "INCOMPLETE"
    assert missing_row["layer1_status"] == "INCOMPLETE"
    assert result.summary["missing_market_snapshot_row_count"] == len(expected_tickers) - 1
