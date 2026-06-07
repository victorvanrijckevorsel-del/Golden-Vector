from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.screening.manual_store import (
    upsert_company_input,
    upsert_source_verification,
)
from golden_vector.screening.pipeline import execute_tool_b_pipeline
from tests.helpers import build_test_paths


def _activate_for_test(app_config, *fixture_tickers: str):
    """Force fixture tickers to be active in the loaded app_config so Tool B
    pipeline doesn't drop them when the live universe.yaml has them inactive.
    """
    targets = {t.upper() for t in fixture_tickers}
    new_tickers = [
        ticker.model_copy(update={"active": True}) if ticker.ticker in targets else ticker
        for ticker in app_config.universe.tickers
    ]
    new_universe = app_config.universe.model_copy(update={"tickers": new_tickers})
    return app_config.model_copy(update={"universe": new_universe})


def _populate_manual_store(paths: ProjectPaths, ticker_payloads: dict[str, dict[str, object]]) -> None:
    bootstrap_manual_screening_data(paths, tickers=list(ticker_payloads))
    for ticker, payload in ticker_payloads.items():
        upsert_company_input(paths, ticker=ticker, values=payload)
        for field_name in payload:
            upsert_source_verification(
                paths,
                ticker=ticker,
                field_name=field_name,
                verification_status="VERIFIED",
                values={},
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
    app_config = _activate_for_test(load_app_config(ProjectPaths.discover()).app, "GOLD")
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

    _populate_manual_store(
        paths,
        {
            "NEM": {
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
            "GOLD": {
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
        },
    )

    result = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=4000,
        snapshot_refresh_run_id="refresh-run-42",
        snapshot_as_of_date="2026-02-01",
    )

    assert result.overall_status == "WARN"
    assert set(result.tool_b_outputs["ticker"]) == expected_tickers
    output = result.tool_b_outputs.set_index("ticker")
    assert output.loc["NEM", "confidence"] == "VERIFIED"
    assert output.loc["NEM", "screening_verdict"] in {"STRONG_CANDIDATE", "WATCHLIST", "SCREEN_OUT"}
    assert output.loc["NEM", "layer1_status"] in {"PASS", "FAIL"}
    assert pd.notna(output.loc["NEM", "fundamental_check_score"])
    assert pd.notna(output.loc["NEM", "fundamental_check_rank"])
    assert "/7:" in output.loc["NEM", "fundamental_check_summary"]
    assert "AISC PASS" in output.loc["NEM", "fundamental_check_summary"]
    assert pd.isna(output.loc["NEM", "layer2_incomplete_reasons"])
    removed_target_columns = [
        "adjusted_peer_pe",
        "adjusted_peak_pe",
        "target_price_peer_pe",
        "target_price_peak_pe",
        "target_price_peer_fcf",
        "target_price_peak_fcf",
        "upside_peer_pe_pct",
        "upside_peak_pe_pct",
        "upside_peer_fcf_pct",
        "upside_peak_fcf_pct",
        "best_target_price_usd",
        "best_upside_pct",
        "tool_b_score",
        "tool_b_rank",
    ]
    assert not set(removed_target_columns).intersection(result.tool_b_outputs.columns)
    assert output.loc["GOLD", "confidence"] == "VERIFIED"
    uncovered_tickers = expected_tickers - {"NEM", "GOLD"}
    assert (output.loc[list(uncovered_tickers), "screening_verdict"] == "INCOMPLETE").all()
    assert result.summary["incomplete_row_count"] == len(uncovered_tickers)
    assert result.summary["manual_store_created"] is False
    # Provenance regression: every published Tool B row should carry the foundation
    # refresh run id and the snapshot as-of date, plus FX policy context.
    assert (result.tool_b_outputs["snapshot_refresh_run_id"] == "refresh-run-42").all()
    assert (result.tool_b_outputs["fx_policy_max_staleness_days"] == app_config.qa.max_fx_staleness_days).all()
    assert (result.tool_b_outputs["fx_policy_block_on_stale_fx"] == app_config.qa.block_on_stale_fx).all()


def test_tool_b_pipeline_marks_missing_manual_data_as_incomplete(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )

    bootstrap_manual_screening_data(paths, tickers=["NEM"])
    upsert_company_input(paths, ticker="NEM", values={"production_oz": 6_000_000})

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
    assert row["fundamental_check_score"] < 100
    assert "Data complete FAIL" in row["fundamental_check_summary"]


def test_tool_b_pipeline_fails_when_manual_store_has_not_been_initialized(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 3500},
        config_hash="hash",
    )

    try:
        execute_tool_b_pipeline(
            paths=paths,
            app_config=app_config,
            run_context=run_context,
            normalized_market_snapshots=_market_snapshots(),
            gold_price_assumption=3500,
        )
    except FileNotFoundError as exc:
        assert "manual-data init" in str(exc)
    else:
        raise AssertionError("Expected Tool B pipeline to fail when the manual store is missing.")


def test_tool_b_pipeline_uses_explicitly_imported_legacy_csvs(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    pd.DataFrame(
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
            }
        ]
    ).to_csv(paths.manual_screening_dir / "company_inputs.csv", index=False)
    pd.DataFrame(
        [
            {"ticker": "NEM", "field_name": "production_oz", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "aisc_usd_per_oz", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "cash_cost_usd_per_oz", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "royalty_rate", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "sustaining_capex_musd", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "da_musd", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "interest_expense_musd", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "tax_rate", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "reserve_life_years", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "net_debt_musd", "verification_status": "VERIFIED"},
            {"ticker": "NEM", "field_name": "ebitda_ltm_musd", "verification_status": "VERIFIED"},
        ]
    ).to_csv(paths.manual_screening_dir / "source_verification.csv", index=False)
    pd.DataFrame(columns=["ticker", "next_financial_report_date", "next_production_report_date", "notes"]).to_csv(
        paths.manual_screening_dir / "reporting_calendar.csv",
        index=False,
    )

    bootstrap_manual_screening_data(
        paths,
        tickers=["NEM"],
        import_csv_if_empty=True,
    )

    result = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=4000,
    )

    row = result.tool_b_outputs[result.tool_b_outputs["ticker"] == "NEM"].iloc[0]
    assert row["confidence"] == "VERIFIED"
    assert result.summary["manual_store_created"] is False


def test_tool_b_pipeline_emits_incomplete_row_when_snapshot_is_missing(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _activate_for_test(load_app_config(ProjectPaths.discover()).app, "GOLD")
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

    _populate_manual_store(
        paths,
        {
            "NEM": {
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
            "GOLD": {
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
        },
    )

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


def test_compute_tool_b_in_memory_matches_execute_tool_b_pipeline(tmp_path):
    """Equivalence lock: the in-memory helper must produce an identical
    DataFrame to the persistent pipeline when given the same inputs.

    This is the seam the workspace relies on for live URL-param
    overrides. If it drifts, the "scenario active" table would no
    longer reflect the same math as a real `python main.py tool-b` run.
    """
    from golden_vector.screening.manual_data import load_manual_screening_data
    from golden_vector.screening.pipeline import compute_tool_b_in_memory

    paths = build_test_paths(tmp_path)
    app_config = _activate_for_test(load_app_config(ProjectPaths.discover()).app, "GOLD")
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={"gold_price": 4000},
        config_hash="hash",
    )
    _populate_manual_store(
        paths,
        {
            "NEM": {
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
            "GOLD": {
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
        },
    )

    snapshots = _market_snapshots()

    # Persistent path — writes parquet but returns the DataFrame.
    persistent = execute_tool_b_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
        normalized_market_snapshots=snapshots,
        gold_price_assumption=4000,
        snapshot_refresh_run_id="refresh-run-42",
        snapshot_as_of_date="2026-02-01",
    ).tool_b_outputs

    # In-memory path — no persistence. Must receive identical inputs
    # and use the same source_run_id so the compared DataFrames match
    # on every cell.
    manual_data = load_manual_screening_data(
        paths,
        tickers=sorted(
            t.ticker for t in app_config.universe.tickers
            if t.active and t.tool_b_enabled
        ),
    )
    in_memory = compute_tool_b_in_memory(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=snapshots,
        gold_price_assumption=4000,
        snapshot_refresh_run_id="refresh-run-42",
        snapshot_as_of_date="2026-02-01",
        source_run_id=run_context.run_id,
    )

    # Sort both the same way so index alignment doesn't confuse equality.
    sort_keys = ["as_of_date", "gold_price_assumption", "fundamental_check_rank", "ticker"]
    persistent_sorted = persistent.sort_values(sort_keys, na_position="last").reset_index(drop=True)
    in_memory_sorted = in_memory.sort_values(sort_keys, na_position="last").reset_index(drop=True)

    pd.testing.assert_frame_equal(persistent_sorted, in_memory_sorted, check_like=True)


def test_compute_tool_b_in_memory_accepts_arbitrary_gold_price_without_persistence(tmp_path):
    """Tool D depends on this seam: Tool B math must be callable at any
    gold price using already-loaded inputs, without writing Tool B outputs.
    """
    from golden_vector.screening.manual_data import load_manual_screening_data
    from golden_vector.screening.pipeline import compute_tool_b_in_memory

    paths = build_test_paths(tmp_path)
    app_config = _activate_for_test(load_app_config(ProjectPaths.discover()).app, "GOLD")
    _populate_manual_store(
        paths,
        {
            "NEM": {
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
            }
        },
    )
    manual_data = load_manual_screening_data(
        paths,
        tickers=sorted(
            ticker.ticker
            for ticker in app_config.universe.tickers
            if ticker.active and ticker.tool_b_enabled
        ),
    )

    low_gold = compute_tool_b_in_memory(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=3000,
    )
    high_gold = compute_tool_b_in_memory(
        app_config=app_config,
        manual_data=manual_data,
        normalized_market_snapshots=_market_snapshots(),
        gold_price_assumption=4000,
    )

    low_nem = low_gold.set_index("ticker").loc["NEM"]
    high_nem = high_gold.set_index("ticker").loc["NEM"]
    assert low_nem["gold_price_assumption"] == 3000
    assert high_nem["gold_price_assumption"] == 4000
    assert high_nem["forward_ebitda_musd"] > low_nem["forward_ebitda_musd"]
    assert not paths.latest_tool_b_snapshot_parquet_path.exists()
