from __future__ import annotations

from datetime import date

import pandas as pd

from golden_vector.contracts.ticker_page import FINANCE_SOURCES
from golden_vector.contracts.tool_d import (
    TOOL_D_KEY_COLUMNS,
    TOOL_D_OUTPUT_COLUMNS,
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
            "resilience_data_status": "OK",
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
    assert "schema v4 rebuild" in YAHOO_TOOL_D_REBUILD_REQUIRED_REASON


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


def test_tool_d_contract_rejects_missing_columns_dates_and_unexpected_ticker():
    frame = _healthy_frame("NEM", "EXTRA").drop(columns=["source_run_id"])
    frame.loc[frame["ticker"].eq("NEM"), "as_of_date"] = None

    violations = validate_tool_d_output_frame(frame, expected_tickers=("NEM",))

    assert any("missing columns: source_run_id" in item for item in violations)
    assert any("null as_of_date values: 2 row(s)" in item for item in violations)
    assert any("unexpected tickers: EXTRA" in item for item in violations)
