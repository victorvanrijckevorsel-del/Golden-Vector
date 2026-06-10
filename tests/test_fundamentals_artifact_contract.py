from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    write_current_model_state_manifest,
)
from golden_vector.common.files import sha256_file
from golden_vector.contracts.fundamentals import (
    FETCHED_FUNDAMENTALS_COLUMNS,
    FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
)
from golden_vector.fundamentals.artifacts import (
    empty_fetched_fundamentals_frame,
    load_official_fundamentals,
    write_fetched_fundamentals_artifact_pair,
)
from golden_vector.fundamentals.resolution import resolve_fundamental_layers
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.screening.manual_store import (
    FINANCIAL_DUAL_SOURCE_FIELDS,
    NUMERIC_COMPANY_FIELDS,
    OPERATIONAL_SINGLE_SOURCE_FIELDS,
    upsert_company_input,
)
from tests.helpers import build_test_paths


def test_fundamental_field_catalog_partitions_manual_numeric_fields():
    assert OPERATIONAL_SINGLE_SOURCE_FIELDS.isdisjoint(FINANCIAL_DUAL_SOURCE_FIELDS)
    assert OPERATIONAL_SINGLE_SOURCE_FIELDS | FINANCIAL_DUAL_SOURCE_FIELDS == set(
        NUMERIC_COMPANY_FIELDS
    )


def test_fetched_fundamentals_rejects_operational_fields(tmp_path):
    paths = build_test_paths(tmp_path)
    frame = pd.DataFrame(
        [
            _official_row(
                ticker="AEM",
                field_name="production_oz",
                value=3_500_000,
            )
        ]
    )

    with pytest.raises(ValueError, match="financial dual-source fields"):
        write_fetched_fundamentals_artifact_pair(
            paths=paths,
            frame=frame,
            source_run_id="20260610T120000Z-fetch-fundamentals",
        )


def test_fetched_fundamentals_artifact_is_manifest_resolved_as_optional_immutable(tmp_path):
    paths = build_test_paths(tmp_path)
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [
                _official_row(
                    ticker="AEM",
                    field_name="net_debt_musd",
                    value=250.0,
                    source_run_id=source_run_id,
                )
            ]
        ),
        source_run_id=source_run_id,
    )

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    artifact = payload["artifacts"][FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME]
    assert artifact["required_for_complete"] is False
    assert artifact["immutable"] is True
    assert artifact["schema_version"] == str(FETCHED_FUNDAMENTALS_SCHEMA_VERSION)
    assert artifact["source_alias_path"] == "data/output/fundamentals/fetched_fundamentals_latest.parquet"
    assert artifact["path"].startswith(
        "data/output/fundamentals/fetched_fundamentals_latest_"
    )
    assert artifact["path"] != "data/output/fundamentals/fetched_fundamentals_latest.parquet"
    assert artifact["row_count"] == 1


def test_missing_official_fundamentals_are_optional_and_load_empty(tmp_path):
    paths = build_test_paths(tmp_path)
    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    artifact = payload["artifacts"][FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME]
    assert artifact["present"] is False
    assert artifact["required_for_complete"] is False
    loaded = load_official_fundamentals(paths)
    assert list(loaded.columns) == list(FETCHED_FUNDAMENTALS_COLUMNS)
    assert loaded.empty


def test_official_fundamentals_loader_reads_through_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    source_run_id = "20260610T120000Z-fetch-fundamentals"
    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [
                _official_row(
                    ticker="AEM",
                    field_name="ebitda_ltm_musd",
                    value=900.0,
                    source_run_id=source_run_id,
                )
            ]
        ),
        source_run_id=source_run_id,
    )
    write_current_model_state_manifest(paths=paths, config_hash="config-hash")
    paths.latest_fetched_fundamentals_path.unlink()

    loaded = load_official_fundamentals(paths)

    assert loaded[["ticker", "field_name", "value"]].to_dict("records") == [
        {"ticker": "AEM", "field_name": "ebitda_ltm_musd", "value": 900.0}
    ]


def test_resolution_uses_manual_override_then_official_fallback(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["AEM", "NEM"])
    upsert_company_input(
        paths,
        ticker="AEM",
        values={"net_debt_musd": 200.0},
    )
    official = pd.DataFrame(
        [
            _official_row(ticker="AEM", field_name="net_debt_musd", value=250.0),
            _official_row(ticker="NEM", field_name="net_debt_musd", value=100.0),
        ]
    )

    manual = bootstrap_manual_screening_data(paths, tickers=["AEM", "NEM"])
    resolved = resolve_fundamental_layers(
        company_inputs=manual.company_inputs,
        official_fundamentals=official,
    )

    rows = resolved[resolved["field_name"].eq("net_debt_musd")].set_index("ticker")
    assert rows.loc["AEM", "official_value"] == 250.0
    assert rows.loc["AEM", "our_view_value"] == 200.0
    assert rows.loc["AEM", "our_view_source"] == "manual"
    assert rows.loc["NEM", "official_value"] == 100.0
    assert rows.loc["NEM", "our_view_value"] == 100.0
    assert rows.loc["NEM", "our_view_source"] == "official"


def test_resolution_keeps_official_only_tickers_visible(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    official = pd.DataFrame(
        [
            _official_row(ticker="NEM", field_name="net_debt_musd", value=100.0),
        ]
    )
    manual = bootstrap_manual_screening_data(paths, tickers=["AEM"])

    resolved = resolve_fundamental_layers(
        company_inputs=manual.company_inputs,
        official_fundamentals=official,
    )

    row = resolved[
        resolved["ticker"].eq("NEM") & resolved["field_name"].eq("net_debt_musd")
    ].iloc[0]
    assert row["official_value"] == 100.0
    assert row["our_view_value"] == 100.0
    assert row["our_view_source"] == "official"


def test_resolution_keeps_operational_fields_single_source(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    upsert_company_input(
        paths,
        ticker="AEM",
        values={"aisc_usd_per_oz": 1450.0},
    )
    manual = bootstrap_manual_screening_data(paths, tickers=["AEM"])

    resolved = resolve_fundamental_layers(
        company_inputs=manual.company_inputs,
        official_fundamentals=empty_fetched_fundamentals_frame(),
    )

    row = resolved[
        resolved["ticker"].eq("AEM") & resolved["field_name"].eq("aisc_usd_per_oz")
    ].iloc[0]
    assert row["official_value"] == 1450.0
    assert row["official_source"] == "manual_single_source"
    assert row["our_view_value"] == 1450.0
    assert row["our_view_source"] == "manual_single_source"


def test_official_artifact_write_does_not_touch_manual_store(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["AEM"])
    upsert_company_input(
        paths,
        ticker="AEM",
        values={"net_debt_musd": 200.0, "aisc_usd_per_oz": 1450.0},
    )
    before_hash = sha256_file(paths.manual_screening_store_path)

    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [
                _official_row(
                    ticker="AEM",
                    field_name="net_debt_musd",
                    value=250.0,
                )
            ]
        ),
        source_run_id="20260610T120000Z-fetch-fundamentals",
    )

    assert sha256_file(paths.manual_screening_store_path) == before_hash
    assert load_current_model_state_manifest(paths) is None


def _official_row(
    *,
    ticker: str,
    field_name: str,
    value: float,
    source_run_id: str = "20260610T120000Z-fetch-fundamentals",
    value_status: str = "OK",
) -> dict[str, object]:
    return {
        "schema_version": FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
        "ticker": ticker,
        "field_name": field_name,
        "value": value,
        "source": "YAHOO",
        "source_run_id": source_run_id,
        "fetched_at_utc": "2026-06-10T12:00:00Z",
        "statement_period": "FY2025",
        "period_end": "2025-12-31",
        "period_type": "ANNUAL",
        "statement_currency": "USD",
        "statement_scale": "millions",
        "value_status": value_status,
    }
