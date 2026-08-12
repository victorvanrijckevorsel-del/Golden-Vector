from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.contracts.ticker_page import FINANCE_SOURCES
from golden_vector.contracts.tool_d import (
    TOOL_D_KEY_COLUMNS,
    TOOL_D_OUTPUT_COLUMNS,
    TOOL_D_RANKING_OUTPUT_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
    YAHOO_TOOL_D_REBUILD_REQUIRED_REASON,
    YAHOO_TOOL_D_UNAVAILABLE_REASON,
    validate_tool_d_output_frame,
)


def _row(ticker: str, source: str, **overrides: object) -> dict[str, object]:
    row = {column: None for column in TOOL_D_OUTPUT_COLUMNS}
    row.update(
        {
            "ticker": ticker,
            "finance_source": source,
            "tool_d_schema_version": TOOL_D_SCHEMA_VERSION,
            "as_of_date": date(2026, 8, 12),
            "source_run_id": "tool-d-run",
            "resilience_data_status": "OK",
            "snapshot_refresh_run_id": "refresh-run",
            "gold_price_used": 4000.0,
            "spot_gold_usd": 4100.0,
            "spot_gold_date": "2026-08-12",
        }
    )
    row.update(overrides)
    return row


def _healthy_frame(*tickers: str) -> pd.DataFrame:
    return pd.DataFrame(
        [_row(ticker, source) for ticker in tickers for source in FINANCE_SOURCES],
        columns=TOOL_D_OUTPUT_COLUMNS,
    )


def test_tool_d_v4_contract_declares_composite_identity_and_migration_reasons():
    assert TOOL_D_SCHEMA_VERSION == 4
    assert TOOL_D_KEY_COLUMNS == ("ticker", "finance_source")
    assert YAHOO_TOOL_D_UNAVAILABLE_REASON == "resilience is computed on Our View inputs"
    # W10: this reason is rendered VERBATIM to the user during the v3->v4
    # window, so it must read as English, not as an internal schema token.
    assert "Corporate Resilience for Yahoo Fundamentals is not available yet" in (
        YAHOO_TOOL_D_REBUILD_REQUIRED_REASON
    )
    assert "one refresh in the new dual-source format" in YAHOO_TOOL_D_REBUILD_REQUIRED_REASON
    for internal_token in ("schema", "v4", "Tool D", "rebuild"):
        assert internal_token not in YAHOO_TOOL_D_REBUILD_REQUIRED_REASON, internal_token


def test_tool_d_contract_accepts_one_explicit_row_per_ticker_and_source():
    frame = _healthy_frame("NEM", "AEM")

    assert validate_tool_d_output_frame(
        frame, expected_tickers=("NEM", "AEM")
    ) == []


def test_tool_d_contract_rejects_duplicate_composite_keys_and_noncanonical_source():
    frame = pd.concat(
        [_healthy_frame("NEM"), pd.DataFrame([_row("NEM", "OUR")])],
        ignore_index=True,
    )
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)

    violations = validate_tool_d_output_frame(frame)

    assert any("duplicate keys on (ticker, finance_source)" in item for item in violations)
    assert any("non-canonical finance_source values: OUR" in item for item in violations)


def test_tool_d_contract_rejects_normalized_key_collisions_and_noncanonical_tickers():
    frame = pd.DataFrame(
        [
            _row(" nem ", "our"),
            _row("NEM", "OUR"),
            _row("NEM", "yahoo"),
        ],
        columns=TOOL_D_OUTPUT_COLUMNS,
    )

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    assert any("duplicate normalized keys" in item for item in violations)
    assert any("stored uppercase and stripped" in item for item in violations)
    assert any("non-canonical finance_source values: OUR" in item for item in violations)


def test_tool_d_contract_rejects_missing_source_and_wrong_schema_version():
    frame = pd.DataFrame(
        [_row("NEM", "our", tool_d_schema_version=3)],
        columns=TOOL_D_OUTPUT_COLUMNS,
    )

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    assert any("tool_d_schema_version must equal 4" in item for item in violations)
    assert any("missing expected (ticker, finance_source) keys: (NEM, yahoo)" in item for item in violations)


def test_tool_d_contract_accepts_explicit_degraded_row_but_requires_its_reason():
    frame = _healthy_frame("NEM")
    yahoo = frame["finance_source"].eq("yahoo")
    frame.loc[yahoo, "resilience_data_status"] = "INSUFFICIENT_INTEREST_DATA"
    frame.loc[yahoo, "missing_inputs"] = "interest_expense_musd"
    assert validate_tool_d_output_frame(frame, expected_tickers=("NEM",)) == []

    frame.loc[yahoo, "missing_inputs"] = None
    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))
    assert any("degraded rows without" in item for item in violations)


def test_tool_d_contract_requires_all_non_ok_ranking_outputs_to_be_null():
    frame = _healthy_frame("NEM")
    yahoo = frame["finance_source"].eq("yahoo")
    frame.loc[yahoo, "resilience_data_status"] = "INSUFFICIENT_INTEREST_DATA"
    frame.loc[yahoo, "missing_inputs"] = "interest_expense_musd"
    for column in TOOL_D_RANKING_OUTPUT_COLUMNS:
        frame.loc[yahoo, column] = 42.0

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    violation = next(
        item for item in violations if "ranking/score/percentile outputs null" in item
    )
    for column in TOOL_D_RANKING_OUTPUT_COLUMNS:
        assert f"{column}=1" in violation


def test_tool_d_contract_rejects_split_generation_identity():
    frame = _healthy_frame("NEM")
    yahoo = frame["finance_source"].eq("yahoo")
    frame.loc[yahoo, "source_run_id"] = "other-tool-d-run"
    frame.loc[yahoo, "snapshot_refresh_run_id"] = "other-refresh-run"

    violations = validate_tool_d_output_frame(
        frame,
        expected_tickers=("NEM",),
        expected_source_run_id="tool-d-run",
    )

    assert any("source_run_id must contain exactly one" in item for item in violations)
    assert any("source_run_id must match persistence run_context" in item for item in violations)
    assert any(
        "snapshot_refresh_run_id must contain exactly one" in item
        for item in violations
    )


def test_tool_d_contract_rejects_blank_generation_identity():
    frame = _healthy_frame("NEM")
    frame.loc[0, "source_run_id"] = " "
    frame.loc[1, "snapshot_refresh_run_id"] = None

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    assert any("blank source_run_id values: 1" in item for item in violations)
    assert any("blank snapshot_refresh_run_id values: 1" in item for item in violations)


def test_tool_d_contract_rejects_incoherent_source_pair_context():
    frame = _healthy_frame("NEM")
    yahoo = frame["finance_source"].eq("yahoo")
    frame.loc[yahoo, "as_of_date"] = date(2026, 8, 11)
    frame.loc[yahoo, "gold_price_used"] = 3999.0
    frame.loc[yahoo, "spot_gold_usd"] = 4099.0
    frame.loc[yahoo, "spot_gold_date"] = "2026-08-11"

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    for column in ("as_of_date", "gold_price_used", "spot_gold_usd", "spot_gold_date"):
        assert any(f"source-pair {column} values differ" in item for item in violations)


def test_tool_d_contract_requires_global_scenario_and_spot_anchors():
    frame = _healthy_frame("NEM", "AEM")
    aem = frame["ticker"].eq("AEM")
    frame.loc[aem, "as_of_date"] = date(2026, 8, 11)
    frame.loc[aem, "gold_price_used"] = 3900.0
    frame.loc[aem, "spot_gold_usd"] = 4050.0
    frame.loc[aem, "spot_gold_date"] = "2026-08-11"

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM", "AEM"))

    assert not any(
        "as_of_date must contain one coherent generation-wide value" in item
        for item in violations
    )
    for column in ("gold_price_used", "spot_gold_usd", "spot_gold_date"):
        assert any(
            f"{column} must contain one coherent generation-wide value" in item
            for item in violations
        )


def test_tool_d_contract_rejects_missing_columns_dates_and_unexpected_ticker():
    frame = _healthy_frame("NEM", "EXTRA").drop(columns=["source_run_id"])
    frame.loc[frame["ticker"].eq("NEM"), "as_of_date"] = None

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    assert any("missing columns: source_run_id" in item for item in violations)
    assert any("null as_of_date values: 2 row(s)" in item for item in violations)
    assert any("unexpected tickers: EXTRA" in item for item in violations)
