import pandas as pd

from golden_vector.screening.manual_data import (
    bootstrap_manual_screening_data,
    determine_manual_confidence,
    load_manual_screening_data,
)
from golden_vector.screening.manual_store import (
    add_stock_note,
    export_store_to_csv,
    import_support_csvs_into_store,
    upsert_company_input,
    upsert_reporting_calendar,
    upsert_source_verification,
)
from tests.helpers import build_test_paths


def test_manual_loader_requires_existing_store_for_normal_reads(tmp_path):
    paths = build_test_paths(tmp_path)

    try:
        load_manual_screening_data(paths, tickers=["NEM", "GOLD"])
    except FileNotFoundError as exc:
        assert "manual-data init" in str(exc)
    else:
        raise AssertionError("Expected load_manual_screening_data to fail before the store is initialized.")


def test_bootstrap_manual_loader_initializes_store_and_seeds_active_tickers(tmp_path):
    paths = build_test_paths(tmp_path)

    loaded = bootstrap_manual_screening_data(paths, tickers=["NEM", "GOLD"])

    assert loaded.store_path == paths.manual_screening_store_path
    assert loaded.store_created is True
    assert set(loaded.seeded_tickers) == {"NEM", "GOLD"}
    assert set(loaded.company_inputs["ticker"]) == {"NEM", "GOLD"}
    assert set(loaded.reporting_calendar["ticker"]) == {"NEM", "GOLD"}
    assert loaded.source_verification.empty
    assert loaded.stock_notes.empty
    assert loaded.imported_csv_files == []


def test_bootstrap_manual_loader_can_import_existing_support_csvs_when_requested(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    pd.DataFrame(
        [
            {"ticker": "NEM", "production_oz": 1_000_000},
            {"ticker": "NEM", "production_oz": 2_000_000},
        ]
    ).to_csv(paths.manual_screening_dir / "company_inputs.csv", index=False)
    pd.DataFrame(
        [
            {"ticker": "NEM", "field_name": "production_oz", "verification_status": "VERIFIED"},
        ]
    ).to_csv(paths.manual_screening_dir / "source_verification.csv", index=False)
    pd.DataFrame(
        [
            {"ticker": "NEM", "next_financial_report_date": "2026-05-01", "notes": "watch call"},
        ]
    ).to_csv(paths.manual_screening_dir / "reporting_calendar.csv", index=False)

    loaded = bootstrap_manual_screening_data(
        paths,
        tickers=["NEM", "GOLD"],
        import_csv_if_empty=True,
    )

    assert set(loaded.imported_csv_files) == {
        "company_inputs.csv",
        "source_verification.csv",
        "reporting_calendar.csv",
    }
    assert float(loaded.company_inputs.loc[loaded.company_inputs["ticker"] == "NEM", "production_oz"].iloc[0]) == 2_000_000.0
    assert set(loaded.company_inputs["ticker"]) == {"NEM", "GOLD"}
    assert len(loaded.source_verification.index) == 1
    assert loaded.reporting_calendar.loc[loaded.reporting_calendar["ticker"] == "NEM", "notes"].iloc[0] == "watch call"


def test_manual_confidence_is_verified_only_when_all_required_fields_are_verified():
    company_row = pd.Series(
        {
            "production_oz": 1_000_000,
            "aisc_usd_per_oz": 1200,
            "cash_cost_usd_per_oz": 850,
            "royalty_rate": 0.03,
            "sustaining_capex_musd": 250,
            "da_musd": 100,
            "interest_expense_musd": 20,
            "tax_rate": 0.3,
            "reserve_life_years": 10,
            "net_debt_musd": 500,
            "ebitda_ltm_musd": 800,
        }
    )
    verification = pd.DataFrame(
        [
            {"ticker": "NEM", "field_name": field_name, "verification_status": "VERIFIED"}
            for field_name in company_row.index
        ]
    )

    confidence = determine_manual_confidence(
        ticker="NEM",
        company_row=company_row,
        source_verification=verification,
    )

    assert confidence == "VERIFIED"


def test_manual_confidence_is_incomplete_when_required_fields_are_missing():
    company_row = pd.Series(
        {
            "production_oz": 1_000_000,
            "aisc_usd_per_oz": None,
        }
    )

    confidence = determine_manual_confidence(
        ticker="NEM",
        company_row=company_row,
        source_verification=pd.DataFrame(),
    )

    assert confidence == "INCOMPLETE"


def test_manual_store_updates_company_reporting_and_note_records(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    upsert_company_input(
        paths,
        ticker="nem",
        values={
            "production_oz": 6_000_000,
            "tax_rate": 30.0,
        },
    )
    upsert_reporting_calendar(
        paths,
        ticker="NEM",
        values={
            "next_financial_report_date": "2026-05-01",
            "notes": "watch next earnings",
        },
    )
    upsert_source_verification(
        paths,
        ticker="NEM",
        field_name="production_oz",
        verification_status="VERIFIED",
        values={"source_date": "2026-04-22"},
    )
    note_id = add_stock_note(
        paths,
        ticker="NEM",
        note_text="Follow up after guidance call",
        note_tag="FOLLOW_UP",
    )

    loaded = load_manual_screening_data(paths, tickers=["NEM"])

    row = loaded.company_inputs[loaded.company_inputs["ticker"] == "NEM"].iloc[0]
    assert float(row["production_oz"]) == 6_000_000.0
    assert float(row["tax_rate"]) == 0.30
    assert row["created_at_utc"] is not None
    assert row["updated_at_utc"] is not None
    calendar_row = loaded.reporting_calendar[loaded.reporting_calendar["ticker"] == "NEM"].iloc[0]
    assert str(calendar_row["next_financial_report_date"]) == "2026-05-01"
    assert calendar_row["notes"] == "watch next earnings"
    assert calendar_row["created_at_utc"] is not None
    assert calendar_row["updated_at_utc"] is not None
    verification_row = loaded.source_verification.iloc[0]
    assert verification_row["verification_status"] == "VERIFIED"
    assert verification_row["created_at_utc"] is not None
    assert verification_row["updated_at_utc"] is not None
    note_row = loaded.stock_notes.iloc[0]
    assert int(note_row["note_id"]) == note_id
    assert note_row["note_tag"] == "FOLLOW_UP"


def test_source_verification_updates_preserve_unmentioned_metadata(tmp_path):
    paths = build_test_paths(tmp_path)
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    upsert_source_verification(
        paths,
        ticker="NEM",
        field_name="production_oz",
        verification_status="VERIFIED",
        values={
            "source_date": "2026-04-22",
            "source_url": "https://example.com/source",
            "notes": "initial verification",
        },
    )
    upsert_source_verification(
        paths,
        ticker="NEM",
        field_name="production_oz",
        verification_status="ESTIMATED",
        values={},
    )

    loaded = load_manual_screening_data(paths, tickers=["NEM"])
    row = loaded.source_verification.iloc[0]
    assert row["verification_status"] == "ESTIMATED"
    assert str(row["source_date"]) == "2026-04-22"
    assert row["source_url"] == "https://example.com/source"
    assert row["notes"] == "initial verification"


def test_manual_store_import_and_export_support_csvs(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    pd.DataFrame(
        [{"ticker": "NEM", "production_oz": 2_500_000, "aisc_usd_per_oz": 1250}],
    ).to_csv(paths.manual_screening_dir / "company_inputs.csv", index=False)
    pd.DataFrame(
        [{"ticker": "NEM", "field_name": "production_oz", "verification_status": "VERIFIED"}],
    ).to_csv(paths.manual_screening_dir / "source_verification.csv", index=False)
    pd.DataFrame(
        [{"ticker": "NEM", "next_production_report_date": "2026-05-15"}],
    ).to_csv(paths.manual_screening_dir / "reporting_calendar.csv", index=False)

    import_result = import_support_csvs_into_store(paths, tickers=["NEM"])
    exported = export_store_to_csv(paths)

    assert set(import_result.imported_csv_files) == {
        "company_inputs.csv",
        "source_verification.csv",
        "reporting_calendar.csv",
    }
    assert set(exported.exported_files) == {
        "company_inputs.csv",
        "source_verification.csv",
        "reporting_calendar.csv",
    }
    assert len(exported.backup_files) == 3
    exported_company_inputs = pd.read_csv(paths.manual_screening_dir / "company_inputs.csv")
    assert float(exported_company_inputs.iloc[0]["production_oz"]) == 2_500_000.0


def test_manual_loader_treats_blank_text_cells_as_missing_not_literal_nan(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    pd.DataFrame(
        [{"ticker": "NEM", "field_name": "production_oz", "verification_status": "VERIFIED", "source_url": None}],
    ).to_csv(paths.manual_screening_dir / "source_verification.csv", index=False)

    loaded = bootstrap_manual_screening_data(
        paths,
        tickers=["NEM"],
        import_csv_if_empty=True,
    )

    assert loaded.source_verification.iloc[0]["source_url"] is None


def test_manual_store_csv_round_trip_preserves_normalized_values(tmp_path):
    source_paths = build_test_paths(tmp_path / "source")
    source_paths.ensure_runtime_dirs()
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "production_oz": 2_500_000,
                "aisc_usd_per_oz": 1250,
                "tax_rate": 30,
                "royalty_rate": 2.5,
            }
        ],
    ).to_csv(source_paths.manual_screening_dir / "company_inputs.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "field_name": "production_oz",
                "verification_status": "VERIFIED",
                "source_date": "2026-04-20",
                "source_url": None,
            }
        ]
    ).to_csv(source_paths.manual_screening_dir / "source_verification.csv", index=False)
    pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "next_financial_report_date": "2026-05-15",
                "notes": "watch quarter",
            }
        ]
    ).to_csv(source_paths.manual_screening_dir / "reporting_calendar.csv", index=False)

    bootstrap_manual_screening_data(
        source_paths,
        tickers=["NEM"],
        import_csv_if_empty=True,
    )
    export_store_to_csv(source_paths)

    round_trip_paths = build_test_paths(tmp_path / "round_trip")
    round_trip_paths.ensure_runtime_dirs()
    for file_name in ("company_inputs.csv", "source_verification.csv", "reporting_calendar.csv"):
        (source_paths.manual_screening_dir / file_name).replace(
            round_trip_paths.manual_screening_dir / file_name
        )

    loaded = bootstrap_manual_screening_data(
        round_trip_paths,
        tickers=["NEM"],
        import_csv_if_empty=True,
    )

    company_row = loaded.company_inputs.iloc[0]
    assert float(company_row["production_oz"]) == 2_500_000.0
    assert float(company_row["tax_rate"]) == 0.30
    assert float(company_row["royalty_rate"]) == 0.025
    verification_row = loaded.source_verification.iloc[0]
    assert str(verification_row["source_date"]) == "2026-04-20"
    assert verification_row["source_url"] is None
    calendar_row = loaded.reporting_calendar.iloc[0]
    assert str(calendar_row["next_financial_report_date"]) == "2026-05-15"
    assert calendar_row["notes"] == "watch quarter"
