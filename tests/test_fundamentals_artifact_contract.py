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
    FUNDAMENTAL_STATUS_PRECEDENCE,
    FUNDAMENTAL_VALUE_STATUSES,
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
    fetched_fundamentals_latest_path,
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


def test_fundamental_status_precedence_covers_every_non_ok_status():
    assert set(FUNDAMENTAL_STATUS_PRECEDENCE) == (
        set(FUNDAMENTAL_VALUE_STATUSES) - {"OK"}
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
    assert artifact["fetched_at_utc"] == "2026-06-10T12:00:00Z"
    assert artifact["value_statuses"] == ["OK"]
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


def test_model_state_warns_when_official_fundamentals_have_stale_fields(tmp_path):
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
                    value_status="STALE",
                )
            ]
        ),
        source_run_id=source_run_id,
    )

    payload = write_current_model_state_manifest(paths=paths, config_hash="config-hash")

    assert "Official fundamentals include stale statement fields." in payload["warnings"]


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
    fetched_fundamentals_latest_path(paths).unlink()

    loaded = load_official_fundamentals(paths)

    assert loaded[["ticker", "field_name", "value"]].to_dict("records") == [
        {"ticker": "AEM", "field_name": "ebitda_ltm_musd", "value": 900.0}
    ]


def test_official_fundamentals_loader_prefer_latest_alias_reads_fresh_fetch(tmp_path):
    """prefer_latest_alias=True reads the freshly-written latest alias even when the manifest
    still points at the previous fetch — the bypass refresh's Tool B uses so it reflects this
    run's fundamentals fetch before the end-of-run promote."""
    paths = build_test_paths(tmp_path)
    old_run = "20260610T120000Z-fetch-fundamentals"
    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [_official_row(ticker="AEM", field_name="ebitda_ltm_musd", value=900.0, source_run_id=old_run)]
        ),
        source_run_id=old_run,
    )
    write_current_model_state_manifest(paths=paths, config_hash="config-hash")  # manifest -> old

    new_run = "20260620T120000Z-fetch-fundamentals"
    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [_official_row(ticker="AEM", field_name="ebitda_ltm_musd", value=950.0, source_run_id=new_run)]
        ),
        source_run_id=new_run,
    )  # alias -> new, manifest NOT re-promoted

    via_manifest = load_official_fundamentals(paths)
    via_alias = load_official_fundamentals(paths, prefer_latest_alias=True)
    assert via_manifest.set_index("field_name").loc["ebitda_ltm_musd", "value"] == 900.0
    assert via_alias.set_index("field_name").loc["ebitda_ltm_musd", "value"] == 950.0


def test_official_fundamentals_loader_prefer_latest_alias_falls_back_when_alias_unreadable(
    tmp_path,
):
    """Refresh should prefer the fresh alias only if it is usable. If the stale guard was
    triggered by an unreadable latest alias and the optional fetch cannot replace it, Tool B
    must fall back to the last published manifest artifact instead of aborting the refresh."""
    paths = build_test_paths(tmp_path)
    old_run = "20260610T120000Z-fetch-fundamentals"
    write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=pd.DataFrame(
            [
                _official_row(
                    ticker="AEM",
                    field_name="ebitda_ltm_musd",
                    value=900.0,
                    source_run_id=old_run,
                )
            ]
        ),
        source_run_id=old_run,
    )
    write_current_model_state_manifest(paths=paths, config_hash="config-hash")
    fetched_fundamentals_latest_path(paths).write_text("not parquet", encoding="utf-8")

    loaded = load_official_fundamentals(paths, prefer_latest_alias=True)

    assert loaded[["ticker", "field_name", "value"]].to_dict("records") == [
        {"ticker": "AEM", "field_name": "ebitda_ltm_musd", "value": 900.0}
    ]


def test_writer_enforces_one_source_run_id_for_manifest_resolution(tmp_path):
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
                    source_run_id="20260609T120000Z-old-fetch",
                )
            ]
        ),
        source_run_id=source_run_id,
    )

    payload = write_current_model_state_manifest(paths=paths, config_hash="config-hash")

    artifact = payload["artifacts"][FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME]
    assert artifact["source_run_ids"] == [source_run_id]
    assert artifact["immutable"] is True


def test_writer_rejects_blank_source_run_id(tmp_path):
    paths = build_test_paths(tmp_path)

    with pytest.raises(ValueError, match="source_run_id is required"):
        write_fetched_fundamentals_artifact_pair(
            paths=paths,
            frame=pd.DataFrame(
                [_official_row(ticker="AEM", field_name="net_debt_musd", value=250.0)]
            ),
            source_run_id="",
        )


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


def test_resolution_treats_nullable_official_status_as_missing(tmp_path):
    paths = build_test_paths(tmp_path)
    manual = bootstrap_manual_screening_data(paths, tickers=["AEM"])
    official = pd.DataFrame(
        [
            _official_row(
                ticker="AEM",
                field_name="net_debt_musd",
                value=250.0,
                value_status=pd.NA,
            )
        ]
    )

    resolved = resolve_fundamental_layers(
        company_inputs=manual.company_inputs,
        official_fundamentals=official,
    )

    row = resolved[
        resolved["ticker"].eq("AEM") & resolved["field_name"].eq("net_debt_musd")
    ].iloc[0]
    assert row["official_status"] == "MISSING"
    assert row["our_view_value"] == 250.0
    assert row["our_view_status"] == "MISSING"
    assert row["our_view_source"] == "official"


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
