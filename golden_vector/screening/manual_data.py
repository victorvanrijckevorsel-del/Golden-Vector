"""Manual screening input loaders and confidence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths


COMPANY_INPUT_COLUMNS = [
    "ticker",
    "production_oz",
    "aisc_usd_per_oz",
    "cash_cost_usd_per_oz",
    "royalty_rate",
    "sustaining_capex_musd",
    "da_musd",
    "interest_expense_musd",
    "tax_rate",
    "reserve_life_years",
    "net_debt_musd",
    "ebitda_ltm_musd",
]

SOURCE_VERIFICATION_COLUMNS = [
    "ticker",
    "field_name",
    "verification_status",
    "source_date",
    "source_url",
    "notes",
]

REPORTING_CALENDAR_COLUMNS = [
    "ticker",
    "next_financial_report_date",
    "next_production_report_date",
    "notes",
]

REQUIRED_MANUAL_FIELDS = [
    "production_oz",
    "aisc_usd_per_oz",
    "cash_cost_usd_per_oz",
    "royalty_rate",
    "sustaining_capex_musd",
    "da_musd",
    "interest_expense_musd",
    "tax_rate",
    "reserve_life_years",
    "net_debt_musd",
    "ebitda_ltm_musd",
]

NUMERIC_MANUAL_FIELDS = [
    column for column in COMPANY_INPUT_COLUMNS if column != "ticker"
]


@dataclass(frozen=True)
class LoadedManualScreeningData:
    company_inputs: pd.DataFrame
    source_verification: pd.DataFrame
    reporting_calendar: pd.DataFrame
    missing_files: list[str]


@dataclass(frozen=True)
class ManualTemplateSyncResult:
    created_files: list[str]
    updated_files: list[str]


def ensure_manual_screening_templates(
    paths: ProjectPaths,
    tickers: list[str],
) -> ManualTemplateSyncResult:
    manual_dir = paths.manual_screening_dir
    manual_dir.mkdir(parents=True, exist_ok=True)

    created_files: list[str] = []
    updated_files: list[str] = []
    company_path = manual_dir / "company_inputs.csv"
    verification_path = manual_dir / "source_verification.csv"
    reporting_path = manual_dir / "reporting_calendar.csv"

    if not company_path.exists():
        company_template = pd.DataFrame({"ticker": sorted(set(tickers))})
        for column in COMPANY_INPUT_COLUMNS:
            if column != "ticker":
                company_template[column] = pd.NA
        company_template.to_csv(company_path, index=False)
        created_files.append(company_path.name)
    elif _append_missing_ticker_rows(
        company_path,
        COMPANY_INPUT_COLUMNS,
        sorted(set(tickers)),
    ):
        updated_files.append(company_path.name)

    if not verification_path.exists():
        pd.DataFrame(columns=SOURCE_VERIFICATION_COLUMNS).to_csv(
            verification_path,
            index=False,
        )
        created_files.append(verification_path.name)

    if not reporting_path.exists():
        reporting_template = pd.DataFrame({"ticker": sorted(set(tickers))})
        for column in REPORTING_CALENDAR_COLUMNS:
            if column != "ticker":
                reporting_template[column] = pd.NA
        reporting_template.to_csv(reporting_path, index=False)
        created_files.append(reporting_path.name)
    elif _append_missing_ticker_rows(
        reporting_path,
        REPORTING_CALENDAR_COLUMNS,
        sorted(set(tickers)),
    ):
        updated_files.append(reporting_path.name)

    return ManualTemplateSyncResult(
        created_files=created_files,
        updated_files=updated_files,
    )


def load_manual_screening_data(paths: ProjectPaths) -> LoadedManualScreeningData:
    manual_dir = paths.manual_screening_dir
    company_path = manual_dir / "company_inputs.csv"
    verification_path = manual_dir / "source_verification.csv"
    reporting_path = manual_dir / "reporting_calendar.csv"

    missing_files: list[str] = []
    company_inputs = _read_csv_or_empty(company_path, COMPANY_INPUT_COLUMNS, missing_files)
    source_verification = _read_csv_or_empty(
        verification_path,
        SOURCE_VERIFICATION_COLUMNS,
        missing_files,
    )
    reporting_calendar = _read_csv_or_empty(
        reporting_path,
        REPORTING_CALENDAR_COLUMNS,
        missing_files,
    )

    company_inputs = _normalize_company_inputs(company_inputs)
    source_verification = _normalize_source_verification(source_verification)
    reporting_calendar = _normalize_reporting_calendar(reporting_calendar)

    return LoadedManualScreeningData(
        company_inputs=company_inputs,
        source_verification=source_verification,
        reporting_calendar=reporting_calendar,
        missing_files=missing_files,
    )


def determine_manual_confidence(
    *,
    ticker: str,
    company_row: pd.Series,
    source_verification: pd.DataFrame,
) -> str:
    missing_required_fields = [
        field_name
        for field_name in REQUIRED_MANUAL_FIELDS
        if _is_missing(company_row.get(field_name))
    ]
    if missing_required_fields:
        return "INCOMPLETE"

    verification_rows = source_verification[
        source_verification["ticker"] == ticker
    ].copy()
    if verification_rows.empty:
        return "ESTIMATED"

    verification_rows["field_name"] = verification_rows["field_name"].astype(str)
    status_by_field = {
        field_name: set(
            verification_rows.loc[
                verification_rows["field_name"] == field_name,
                "verification_status",
            ].astype(str)
        )
        for field_name in REQUIRED_MANUAL_FIELDS
    }
    if all(status_by_field.get(field_name) == {"VERIFIED"} for field_name in REQUIRED_MANUAL_FIELDS):
        return "VERIFIED"
    return "ESTIMATED"


def missing_required_manual_fields(company_row: pd.Series) -> list[str]:
    return [
        field_name
        for field_name in REQUIRED_MANUAL_FIELDS
        if _is_missing(company_row.get(field_name))
    ]


def _read_csv_or_empty(
    path: Path,
    required_columns: list[str],
    missing_files: list[str],
) -> pd.DataFrame:
    if not path.exists():
        missing_files.append(path.name)
        return pd.DataFrame(columns=required_columns)

    frame = pd.read_csv(path)
    for column in required_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame[required_columns].copy()


def _append_missing_ticker_rows(
    path: Path,
    required_columns: list[str],
    tickers: list[str],
) -> bool:
    frame = pd.read_csv(path)
    for column in required_columns:
        if column not in frame.columns:
            frame[column] = pd.NA
    working = frame[required_columns].copy()
    working["ticker"] = working["ticker"].fillna("").astype(str).str.upper().str.strip()

    existing = set(working.loc[working["ticker"] != "", "ticker"])
    missing = [ticker for ticker in tickers if ticker not in existing]
    if not missing:
        return False

    additions = pd.DataFrame({"ticker": missing})
    for column in required_columns:
        if column != "ticker":
            additions[column] = pd.NA

    updated = pd.concat([working, additions[required_columns]], ignore_index=True)
    updated.to_csv(path, index=False)
    return True


def _normalize_company_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    if "ticker" in normalized.columns:
        normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
        normalized = normalized[normalized["ticker"] != ""].copy()
        normalized = normalized.drop_duplicates(subset=["ticker"], keep="last")

    for column in NUMERIC_MANUAL_FIELDS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    if "royalty_rate" in normalized.columns:
        normalized["royalty_rate"] = normalized["royalty_rate"].apply(_normalize_rate)
    if "tax_rate" in normalized.columns:
        normalized["tax_rate"] = normalized["tax_rate"].apply(_normalize_rate)

    return normalized.reset_index(drop=True)


def _normalize_source_verification(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    normalized["field_name"] = normalized["field_name"].fillna("").astype(str).str.strip()
    normalized["verification_status"] = (
        normalized["verification_status"]
        .fillna("ESTIMATED")
        .astype(str)
        .str.upper()
        .str.strip()
        .replace({"UNVERIFIED": "ESTIMATED"})
    )
    normalized["source_date"] = pd.to_datetime(
        normalized["source_date"],
        errors="coerce",
    ).dt.date
    normalized = normalized[
        (normalized["ticker"] != "") & (normalized["field_name"] != "")
    ].copy()
    return normalized.reset_index(drop=True)


def _normalize_reporting_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    for column in ("next_financial_report_date", "next_production_report_date"):
        normalized[column] = pd.to_datetime(normalized[column], errors="coerce").dt.date
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized.drop_duplicates(subset=["ticker"], keep="last")
    return normalized.reset_index(drop=True)


def _normalize_rate(value: object) -> float | None:
    if _is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1.0:
        return numeric / 100.0
    return numeric


def _is_missing(value: object) -> bool:
    return value is None or pd.isna(value)
