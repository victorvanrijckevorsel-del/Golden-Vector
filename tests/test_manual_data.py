import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.manual_data import (
    determine_manual_confidence,
    ensure_manual_screening_templates,
    load_manual_screening_data,
)
from tests.helpers import build_test_paths


def test_manual_loader_uses_empty_templates_when_files_are_missing(tmp_path):
    paths = build_test_paths(tmp_path)

    loaded = load_manual_screening_data(paths)

    assert loaded.company_inputs.empty
    assert sorted(loaded.missing_files) == [
        "company_inputs.csv",
        "reporting_calendar.csv",
        "source_verification.csv",
    ]


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


def test_manual_template_creation_writes_company_and_calendar_starters(tmp_path):
    paths = build_test_paths(tmp_path)

    sync_result = ensure_manual_screening_templates(paths, ["NEM", "GOLD"])

    assert sorted(sync_result.created_files) == [
        "company_inputs.csv",
        "reporting_calendar.csv",
        "source_verification.csv",
    ]
    assert sync_result.updated_files == []

    company_inputs = pd.read_csv(paths.manual_screening_dir / "company_inputs.csv")
    reporting_calendar = pd.read_csv(paths.manual_screening_dir / "reporting_calendar.csv")

    assert list(company_inputs["ticker"]) == ["GOLD", "NEM"]
    assert list(reporting_calendar["ticker"]) == ["GOLD", "NEM"]


def test_manual_loader_keeps_last_duplicate_company_row(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    pd.DataFrame(
        [
            {"ticker": "NEM", "production_oz": 1_000_000},
            {"ticker": "NEM", "production_oz": 2_000_000},
        ]
    ).to_csv(paths.manual_screening_dir / "company_inputs.csv", index=False)
    pd.DataFrame(columns=["ticker", "field_name", "verification_status", "source_date", "source_url", "notes"]).to_csv(
        paths.manual_screening_dir / "source_verification.csv",
        index=False,
    )
    pd.DataFrame(columns=["ticker", "next_financial_report_date", "next_production_report_date", "notes"]).to_csv(
        paths.manual_screening_dir / "reporting_calendar.csv",
        index=False,
    )

    loaded = load_manual_screening_data(paths)

    assert len(loaded.company_inputs.index) == 1
    assert float(loaded.company_inputs.iloc[0]["production_oz"]) == 2_000_000.0


def test_manual_template_creation_appends_missing_universe_tickers_to_existing_files(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    pd.DataFrame([{"ticker": "NEM"}]).to_csv(
        paths.manual_screening_dir / "company_inputs.csv",
        index=False,
    )
    pd.DataFrame(columns=["ticker", "field_name", "verification_status", "source_date", "source_url", "notes"]).to_csv(
        paths.manual_screening_dir / "source_verification.csv",
        index=False,
    )
    pd.DataFrame([{"ticker": "NEM"}]).to_csv(
        paths.manual_screening_dir / "reporting_calendar.csv",
        index=False,
    )

    sync_result = ensure_manual_screening_templates(paths, ["NEM", "GOLD"])

    company_inputs = pd.read_csv(paths.manual_screening_dir / "company_inputs.csv")
    reporting_calendar = pd.read_csv(paths.manual_screening_dir / "reporting_calendar.csv")

    assert sync_result.created_files == []
    assert sorted(sync_result.updated_files) == ["company_inputs.csv", "reporting_calendar.csv"]
    assert set(company_inputs["ticker"]) == {"NEM", "GOLD"}
    assert set(reporting_calendar["ticker"]) == {"NEM", "GOLD"}
