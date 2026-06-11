from dataclasses import fields
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.contracts.data_models import ToolAOutput, ToolBOutput
from golden_vector.features.options import compute_options_features
from golden_vector.hedge.candidate_puts import OptionCandidate
from golden_vector.hedge.scenarios import CandidateScenarioBundle, ScenarioRow
from golden_vector.ingestion.fetch_options import (
    OPTIONS_STATUS_SUCCESS,
    OptionsChainResult,
)
from golden_vector.ingestion.options_phase import _compute_feature_row
from golden_vector.ingestion.persist_options import OptionsSnapshotRecord
from tests.helpers import build_test_paths


def test_hedge_reads_only_real_tool_a_columns():
    expected = {
        "ticker",
        "structural_delta_core",
        "down_beta_core",
        "up_beta_core",
        "confidence_score",
        "confidence_label",
        "score_eligible",
        "snapshot_refresh_run_id",
        "source_run_id",
    }

    assert expected <= set(ToolAOutput.model_fields)


def test_hedge_reads_only_real_tool_b_columns():
    expected = {
        "ticker",
        "share_price_usd",
        "screening_verdict",
        "snapshot_refresh_run_id",
        "source_run_id",
    }

    assert expected <= set(ToolBOutput.model_fields)


def test_options_features_contract_contains_core_feature_columns():
    features = compute_options_features(
        target_horizons_days=(30, 60, 90),
        chain=pd.DataFrame(),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
    )

    assert {
        "ticker",
        "optionability_tier",
        "iv_percentile_cross_sectional",
        "atm_iv_60d",
        "put_iv_25d_60d",
        "call_iv_25d_60d",
        "iv_skew_60d",
        "iv_rv_ratio_60d",
        "put_call_oi_ratio_total",
        "put_call_oi_ratio_otm",
    } <= set(features)


def test_options_phase_feature_row_contract_contains_hedge_provenance_columns(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    snapshot_path = (
        paths.runs_dir / "options-run" / "snapshots" / "options" / "AEM.parquet"
    )
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    chain = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "as_of_date": "2026-05-29",
                "expiration": "2026-07-31",
                "option_type": "P",
                "strike": 45.0,
                "bid": 1.15,
                "ask": 1.25,
                "mid": 1.20,
                "last_price": 1.20,
                "volume": 50,
                "open_interest": 500,
                "implied_volatility": 0.40,
                "underlying_price": 50.0,
                "moneyness": 0.90,
                "days_to_expiry": 60,
            }
        ]
    )
    chain.to_parquet(snapshot_path, index=False)
    snapshot_record = OptionsSnapshotRecord(
        ticker="AEM",
        options_available=True,
        row_count=1,
        snapshot_path=snapshot_path,
        sha256="fixture-sha",
    )
    options_result = OptionsChainResult(
        ticker="AEM",
        as_of_date=date(2026, 5, 29),
        status=OPTIONS_STATUS_SUCCESS,
        frame=chain,
    )

    row = _compute_feature_row(
        snapshot_record=snapshot_record,
        options_result=options_result,
        paths=paths,
        ticker="AEM",
        as_of_date=date(2026, 5, 29),
        risk_free_rate=0.04,
        run_id="options-run",
        app_config=app_config,
        price_history=pd.DataFrame({"return_basis_usd": [0.01, -0.02, 0.01] * 30}),
    )

    assert {
        "ticker",
        "run_id",
        "underlying_price",
        "options_snapshot_path",
        "options_fetch_status",
        "options_fetch_message",
    } <= set(row)
    assert row["run_id"] == "options-run"
    assert row["options_snapshot_path"].endswith("AEM.parquet")


def test_option_candidate_and_scenario_contract_contains_rendered_fields():
    option_candidate_fields = {field.name for field in fields(OptionCandidate)}
    assert {
        "ticker",
        "horizon_days",
        "expiration",
        "days_to_expiry",
        "strike",
        "bid",
        "ask",
        "mid",
        "open_interest",
        "volume",
        "implied_volatility",
        "delta",
        "delta_gap",
        "premium_pct_spot",
        "underlying_price",
        "option_type",
    } <= option_candidate_fields

    scenario_row_fields = {field.name for field in fields(ScenarioRow)}
    assert {
        "gold_pct_change",
        "implied_stock_price",
        "stock_clamped_at_zero",
        "expiry_value_per_contract",
        "current_value_per_contract",
        "pnl_per_contract_at_expiry",
        "pnl_per_contract_if_closed_today",
        "net_pnl_at_expiry",
        "net_pnl_if_closed_today",
    } <= scenario_row_fields

    bundle_fields = {field.name for field in fields(CandidateScenarioBundle)}
    assert {
        "ticker",
        "horizon",
        "candidate",
        "rows",
        "breakeven_gold_pct",
        "breakeven_annotation",
        "gold_beta_used",
        "confidence_label",
        "skipped_reason",
    } <= bundle_fields
