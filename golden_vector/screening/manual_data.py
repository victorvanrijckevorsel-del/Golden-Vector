"""Manual screening data loading and confidence helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.screening.manual_store import (
    COMPANY_INPUT_COLUMNS,
    FINANCIAL_DUAL_SOURCE_FIELDS,
    NUMERIC_COMPANY_FIELDS,
    OPERATIONAL_SINGLE_SOURCE_FIELDS,
    REPORTING_CALENDAR_COLUMNS,
    SOURCE_VERIFICATION_COLUMNS,
    STOCK_NOTE_COLUMNS,
    ManualStoreSyncResult,
    ensure_manual_store,
    load_store_tables,
    manual_store_exists,
)


REQUIRED_MANUAL_FIELDS = [
    field_name
    for field_name in NUMERIC_COMPANY_FIELDS
    if field_name in OPERATIONAL_SINGLE_SOURCE_FIELDS | FINANCIAL_DUAL_SOURCE_FIELDS
]


@dataclass(frozen=True)
class LoadedManualScreeningData:
    company_inputs: pd.DataFrame
    source_verification: pd.DataFrame
    reporting_calendar: pd.DataFrame
    stock_notes: pd.DataFrame
    store_path: Path
    store_created: bool
    seeded_tickers: list[str]
    imported_csv_files: list[str]


def load_manual_screening_data(
    paths: ProjectPaths,
    *,
    tickers: list[str],
) -> LoadedManualScreeningData:
    if not manual_store_exists(paths):
        raise FileNotFoundError(
            "No local Tool B manual-data store exists yet. "
            "Run `python main.py manual-data init` first."
        )
    sync_result = ManualStoreSyncResult(
        store_path=paths.manual_screening_store_path,
        created_store=False,
        seeded_tickers=[],
        imported_csv_files=[],
    )
    return _load_manual_screening_data(paths, sync_result=sync_result)


def bootstrap_manual_screening_data(
    paths: ProjectPaths,
    *,
    tickers: list[str],
    import_csv_if_empty: bool = False,
) -> LoadedManualScreeningData:
    sync_result = ensure_manual_store(
        paths,
        tickers=tickers,
        import_csv_if_empty=import_csv_if_empty,
    )
    return _load_manual_screening_data(paths, sync_result=sync_result)


def _load_manual_screening_data(
    paths: ProjectPaths,
    *,
    sync_result: ManualStoreSyncResult,
) -> LoadedManualScreeningData:
    company_inputs, source_verification, reporting_calendar, stock_notes = load_store_tables(paths)

    company_inputs = _normalize_company_inputs(company_inputs)
    source_verification = _normalize_source_verification(source_verification)
    reporting_calendar = _normalize_reporting_calendar(reporting_calendar)
    stock_notes = _normalize_stock_notes(stock_notes)

    return LoadedManualScreeningData(
        company_inputs=company_inputs,
        source_verification=source_verification,
        reporting_calendar=reporting_calendar,
        stock_notes=stock_notes,
        store_path=sync_result.store_path,
        store_created=sync_result.created_store,
        seeded_tickers=sync_result.seeded_tickers,
        imported_csv_files=sync_result.imported_csv_files,
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
        source_verification["ticker"] == str(ticker).upper()
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


def summarize_manual_store_sync(loaded: LoadedManualScreeningData) -> ManualStoreSyncResult:
    return ManualStoreSyncResult(
        store_path=loaded.store_path,
        created_store=loaded.store_created,
        seeded_tickers=loaded.seeded_tickers,
        imported_csv_files=loaded.imported_csv_files,
    )


def _normalize_company_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in COMPANY_INPUT_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized.drop_duplicates(subset=["ticker"], keep="last")
    for column in NUMERIC_COMPANY_FIELDS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    if "royalty_rate" in normalized.columns:
        normalized["royalty_rate"] = normalized["royalty_rate"].apply(_normalize_rate)
    if "tax_rate" in normalized.columns:
        normalized["tax_rate"] = normalized["tax_rate"].apply(_normalize_rate)
    for column in ("created_at_utc", "updated_at_utc"):
        if column in normalized.columns:
            normalized[column] = normalized[column].apply(_normalize_text)
    return normalized[COMPANY_INPUT_COLUMNS].reset_index(drop=True)


def _normalize_source_verification(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in SOURCE_VERIFICATION_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
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
    normalized["source_url"] = normalized["source_url"].apply(_normalize_text)
    normalized["notes"] = normalized["notes"].apply(_normalize_text)
    for column in ("created_at_utc", "updated_at_utc"):
        if column in normalized.columns:
            normalized[column] = normalized[column].apply(_normalize_text)
    normalized = normalized[
        (normalized["ticker"] != "") & (normalized["field_name"] != "")
    ].copy()
    normalized = normalized.drop_duplicates(subset=["ticker", "field_name"], keep="last")
    return normalized[SOURCE_VERIFICATION_COLUMNS].reset_index(drop=True)


def _normalize_reporting_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in REPORTING_CALENDAR_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    for column in ("next_financial_report_date", "next_production_report_date"):
        normalized[column] = pd.to_datetime(normalized[column], errors="coerce").dt.date
    normalized["notes"] = normalized["notes"].apply(_normalize_text)
    for column in ("created_at_utc", "updated_at_utc"):
        if column in normalized.columns:
            normalized[column] = normalized[column].apply(_normalize_text)
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized.drop_duplicates(subset=["ticker"], keep="last")
    return normalized[REPORTING_CALENDAR_COLUMNS].reset_index(drop=True)


def _normalize_stock_notes(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in STOCK_NOTE_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["note_id"] = pd.to_numeric(normalized["note_id"], errors="coerce").astype("Int64")
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    normalized["note_text"] = normalized["note_text"].apply(_normalize_text)
    normalized["note_tag"] = normalized["note_tag"].apply(_normalize_text)
    normalized["note_status"] = (
        normalized["note_status"]
        .fillna("OPEN")
        .astype(str)
        .str.upper()
        .str.strip()
    )
    normalized["created_at_utc"] = normalized["created_at_utc"].apply(_normalize_text)
    normalized["updated_at_utc"] = normalized["updated_at_utc"].apply(_normalize_text)
    normalized = normalized[(normalized["ticker"] != "") & (normalized["note_text"].notna())].copy()
    return normalized[STOCK_NOTE_COLUMNS].reset_index(drop=True)


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


def _normalize_text(value: object) -> str | None:
    if _is_missing(value):
        return None
    text = str(value).strip()
    return text or None


def _is_missing(value: object) -> bool:
    return value is None or pd.isna(value)
