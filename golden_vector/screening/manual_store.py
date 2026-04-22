"""SQLite-backed store for Tool B manual inputs and stock notes."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths


TIMESTAMP_COLUMNS = [
    "created_at_utc",
    "updated_at_utc",
]

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
] + TIMESTAMP_COLUMNS

SOURCE_VERIFICATION_COLUMNS = [
    "ticker",
    "field_name",
    "verification_status",
    "source_date",
    "source_url",
    "notes",
] + TIMESTAMP_COLUMNS

REPORTING_CALENDAR_COLUMNS = [
    "ticker",
    "next_financial_report_date",
    "next_production_report_date",
    "notes",
] + TIMESTAMP_COLUMNS

STOCK_NOTE_COLUMNS = [
    "note_id",
    "ticker",
    "note_text",
    "note_tag",
    "note_status",
    "created_at_utc",
    "updated_at_utc",
]

NUMERIC_COMPANY_FIELDS = [
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


@dataclass(frozen=True)
class ManualStoreSyncResult:
    store_path: Path
    created_store: bool
    seeded_tickers: list[str]
    imported_csv_files: list[str]


@dataclass(frozen=True)
class ManualStoreExportResult:
    exported_files: list[str]
    backup_files: list[str]


def manual_store_exists(paths: ProjectPaths) -> bool:
    return paths.manual_screening_store_path.exists()


def ensure_manual_store(
    paths: ProjectPaths,
    *,
    tickers: list[str],
    import_csv_if_empty: bool = True,
) -> ManualStoreSyncResult:
    paths.ensure_runtime_dirs()
    store_path = paths.manual_screening_store_path
    created_store = not store_path.exists()
    normalized_tickers = sorted({_normalize_ticker(ticker) for ticker in tickers if _normalize_ticker(ticker)})

    with _connect(store_path) as connection:
        _create_schema(connection)
        seeded_tickers = _seed_ticker_rows(connection, normalized_tickers)
        imported_csv_files: list[str] = []
        if import_csv_if_empty and _store_has_no_manual_content(connection):
            imported_csv_files = _import_csv_support_files(connection, paths)
            if seeded_tickers:
                # Rerun seeding because imports may not contain the full active universe.
                _seed_ticker_rows(connection, normalized_tickers)
        connection.commit()

    return ManualStoreSyncResult(
        store_path=store_path,
        created_store=created_store,
        seeded_tickers=seeded_tickers,
        imported_csv_files=imported_csv_files,
    )


def load_store_tables(paths: ProjectPaths) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    store_path = paths.manual_screening_store_path
    if not store_path.exists():
        return (
            pd.DataFrame(columns=COMPANY_INPUT_COLUMNS),
            pd.DataFrame(columns=SOURCE_VERIFICATION_COLUMNS),
            pd.DataFrame(columns=REPORTING_CALENDAR_COLUMNS),
            pd.DataFrame(columns=STOCK_NOTE_COLUMNS),
        )

    with _connect(store_path) as connection:
        company_inputs = pd.read_sql_query(
            """
            SELECT ticker, production_oz, aisc_usd_per_oz, cash_cost_usd_per_oz,
                   royalty_rate, sustaining_capex_musd, da_musd, interest_expense_musd,
                   tax_rate, reserve_life_years, net_debt_musd, ebitda_ltm_musd,
                   created_at_utc, updated_at_utc
            FROM company_inputs
            ORDER BY ticker
            """,
            connection,
        )
        source_verification = pd.read_sql_query(
            """
            SELECT ticker, field_name, verification_status, source_date, source_url, notes,
                   created_at_utc, updated_at_utc
            FROM source_verification
            ORDER BY ticker, field_name
            """,
            connection,
        )
        reporting_calendar = pd.read_sql_query(
            """
            SELECT ticker, next_financial_report_date, next_production_report_date, notes,
                   created_at_utc, updated_at_utc
            FROM reporting_calendar
            ORDER BY ticker
            """,
            connection,
        )
        stock_notes = pd.read_sql_query(
            """
            SELECT note_id, ticker, note_text, note_tag, note_status, created_at_utc, updated_at_utc
            FROM stock_notes
            ORDER BY updated_at_utc DESC, note_id DESC
            """,
            connection,
        )

    return company_inputs, source_verification, reporting_calendar, stock_notes


def upsert_company_input(
    paths: ProjectPaths,
    *,
    ticker: str,
    values: dict[str, object],
) -> None:
    normalized_ticker = _normalize_ticker(ticker)
    filtered_values = {
        field_name: values[field_name]
        for field_name in NUMERIC_COMPANY_FIELDS
        if field_name in values
    }
    if not filtered_values:
        raise ValueError("At least one company-input field must be provided.")

    with _connect(paths.manual_screening_store_path) as connection:
        _create_schema(connection)
        _ensure_single_ticker_seeded(connection, normalized_ticker)
        updates = {
            field_name: _normalize_numeric_value(field_name, value)
            for field_name, value in filtered_values.items()
        }
        updates["updated_at_utc"] = _utc_timestamp()
        assignments = ", ".join(f"{field_name} = ?" for field_name in updates)
        parameters = list(updates.values())
        parameters.append(normalized_ticker)
        connection.execute(
            f"UPDATE company_inputs SET {assignments} WHERE ticker = ?",
            parameters,
        )
        connection.commit()


def upsert_reporting_calendar(
    paths: ProjectPaths,
    *,
    ticker: str,
    values: dict[str, object],
) -> None:
    normalized_ticker = _normalize_ticker(ticker)
    allowed_fields = {
        "next_financial_report_date",
        "next_production_report_date",
        "notes",
    }
    unexpected_fields = sorted(set(values) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            "Unsupported reporting-calendar fields: "
            + ", ".join(unexpected_fields)
        )

    updates: dict[str, object] = {}
    if "next_financial_report_date" in values:
        updates["next_financial_report_date"] = _normalize_date_value(
            values["next_financial_report_date"]
        )
    if "next_production_report_date" in values:
        updates["next_production_report_date"] = _normalize_date_value(
            values["next_production_report_date"]
        )
    if "notes" in values:
        updates["notes"] = _normalize_text_value(values["notes"])
    if not updates:
        raise ValueError("At least one reporting-calendar field must be provided.")

    with _connect(paths.manual_screening_store_path) as connection:
        _create_schema(connection)
        _ensure_single_ticker_seeded(connection, normalized_ticker)
        updates["updated_at_utc"] = _utc_timestamp()
        assignments = ", ".join(f"{field_name} = ?" for field_name in updates)
        parameters = list(updates.values())
        parameters.append(normalized_ticker)
        connection.execute(
            f"UPDATE reporting_calendar SET {assignments} WHERE ticker = ?",
            parameters,
        )
        connection.commit()


def upsert_source_verification(
    paths: ProjectPaths,
    *,
    ticker: str,
    field_name: str,
    verification_status: str,
    values: dict[str, object] | None = None,
) -> None:
    normalized_ticker = _normalize_ticker(ticker)
    normalized_field_name = str(field_name).strip()
    if not normalized_field_name:
        raise ValueError("field_name is required.")
    normalized_status = str(verification_status).strip().upper()
    if normalized_status not in {"VERIFIED", "ESTIMATED", "INCOMPLETE"}:
        raise ValueError("verification_status must be VERIFIED, ESTIMATED, or INCOMPLETE.")
    values = values or {}
    allowed_fields = {"source_date", "source_url", "notes"}
    unexpected_fields = sorted(set(values) - allowed_fields)
    if unexpected_fields:
        raise ValueError(
            "Unsupported source-verification fields: "
            + ", ".join(unexpected_fields)
        )
    normalized_values: dict[str, object] = {}
    if "source_date" in values:
        normalized_values["source_date"] = _normalize_date_value(values["source_date"])
    if "source_url" in values:
        normalized_values["source_url"] = _normalize_text_value(values["source_url"])
    if "notes" in values:
        normalized_values["notes"] = _normalize_text_value(values["notes"])

    with _connect(paths.manual_screening_store_path) as connection:
        _create_schema(connection)
        _ensure_single_ticker_seeded(connection, normalized_ticker)
        existing_row = connection.execute(
            """
            SELECT source_date, source_url, notes
            FROM source_verification
            WHERE ticker = ? AND field_name = ?
            """,
            (normalized_ticker, normalized_field_name),
        ).fetchone()

        if existing_row is None:
            connection.execute(
                """
                INSERT INTO source_verification (
                    ticker,
                    field_name,
                    verification_status,
                    source_date,
                    source_url,
                    notes,
                    created_at_utc,
                    updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_ticker,
                    normalized_field_name,
                    normalized_status,
                    normalized_values.get("source_date"),
                    normalized_values.get("source_url"),
                    normalized_values.get("notes"),
                    _utc_timestamp(),
                    _utc_timestamp(),
                ),
            )
        else:
            updates = {
                "verification_status": normalized_status,
                **normalized_values,
                "updated_at_utc": _utc_timestamp(),
            }
            assignments = ", ".join(f"{field_name} = ?" for field_name in updates)
            parameters = list(updates.values()) + [normalized_ticker, normalized_field_name]
            connection.execute(
                f"""
                UPDATE source_verification
                SET {assignments}
                WHERE ticker = ? AND field_name = ?
                """,
                parameters,
            )
        connection.commit()


def add_stock_note(
    paths: ProjectPaths,
    *,
    ticker: str,
    note_text: str,
    note_tag: str | None = None,
    note_status: str = "OPEN",
) -> int:
    normalized_ticker = _normalize_ticker(ticker)
    normalized_note_text = str(note_text).strip()
    if not normalized_note_text:
        raise ValueError("note_text is required.")

    normalized_status = str(note_status).strip().upper()
    if normalized_status not in {"OPEN", "DONE", "WATCH"}:
        raise ValueError("note_status must be OPEN, DONE, or WATCH.")

    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    with _connect(paths.manual_screening_store_path) as connection:
        _create_schema(connection)
        _ensure_single_ticker_seeded(connection, normalized_ticker)
        cursor = connection.execute(
            """
            INSERT INTO stock_notes (
                ticker,
                note_text,
                note_tag,
                note_status,
                created_at_utc,
                updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                normalized_ticker,
                normalized_note_text,
                _normalize_text_value(note_tag),
                normalized_status,
                now_utc,
                now_utc,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_stock_notes(
    paths: ProjectPaths,
    *,
    ticker: str | None = None,
    limit: int = 50,
) -> pd.DataFrame:
    store_path = paths.manual_screening_store_path
    if not store_path.exists():
        return pd.DataFrame(columns=STOCK_NOTE_COLUMNS)

    normalized_ticker = _normalize_ticker(ticker) if ticker is not None else None
    query = """
        SELECT note_id, ticker, note_text, note_tag, note_status, created_at_utc, updated_at_utc
        FROM stock_notes
    """
    parameters: list[object] = []
    if normalized_ticker is not None:
        query += " WHERE ticker = ?"
        parameters.append(normalized_ticker)
    query += " ORDER BY updated_at_utc DESC, note_id DESC LIMIT ?"
    parameters.append(int(limit))

    with _connect(store_path) as connection:
        return pd.read_sql_query(query, connection, params=parameters)


def import_support_csvs_into_store(
    paths: ProjectPaths,
    *,
    tickers: list[str],
) -> ManualStoreSyncResult:
    sync_result = ensure_manual_store(
        paths,
        tickers=tickers,
        import_csv_if_empty=False,
    )
    with _connect(paths.manual_screening_store_path) as connection:
        imported_csv_files = _import_csv_support_files(connection, paths)
        _seed_ticker_rows(connection, sorted({_normalize_ticker(ticker) for ticker in tickers if _normalize_ticker(ticker)}))
        connection.commit()
    return ManualStoreSyncResult(
        store_path=sync_result.store_path,
        created_store=sync_result.created_store,
        seeded_tickers=sync_result.seeded_tickers,
        imported_csv_files=imported_csv_files,
    )


def export_store_to_csv(paths: ProjectPaths) -> ManualStoreExportResult:
    paths.ensure_runtime_dirs()
    company_inputs, source_verification, reporting_calendar, _ = load_store_tables(paths)
    exported_files: list[str] = []
    backup_files: list[str] = []

    company_path = paths.manual_screening_dir / "company_inputs.csv"
    company_backup = _backup_existing_file(company_path)
    if company_backup is not None:
        backup_files.append(company_backup.name)
    company_inputs.to_csv(company_path, index=False)
    exported_files.append(company_path.name)

    verification_path = paths.manual_screening_dir / "source_verification.csv"
    verification_backup = _backup_existing_file(verification_path)
    if verification_backup is not None:
        backup_files.append(verification_backup.name)
    source_verification.to_csv(verification_path, index=False)
    exported_files.append(verification_path.name)

    reporting_path = paths.manual_screening_dir / "reporting_calendar.csv"
    reporting_backup = _backup_existing_file(reporting_path)
    if reporting_backup is not None:
        backup_files.append(reporting_backup.name)
    reporting_calendar.to_csv(reporting_path, index=False)
    exported_files.append(reporting_path.name)

    return ManualStoreExportResult(
        exported_files=exported_files,
        backup_files=backup_files,
    )


def _connect(store_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(store_path)
    connection.row_factory = sqlite3.Row
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS company_inputs (
            ticker TEXT PRIMARY KEY,
            production_oz REAL,
            aisc_usd_per_oz REAL,
            cash_cost_usd_per_oz REAL,
            royalty_rate REAL,
            sustaining_capex_musd REAL,
            da_musd REAL,
            interest_expense_musd REAL,
            tax_rate REAL,
            reserve_life_years REAL,
            net_debt_musd REAL,
            ebitda_ltm_musd REAL,
            created_at_utc TEXT,
            updated_at_utc TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_verification (
            ticker TEXT NOT NULL,
            field_name TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            source_date TEXT,
            source_url TEXT,
            notes TEXT,
            created_at_utc TEXT,
            updated_at_utc TEXT,
            PRIMARY KEY (ticker, field_name)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reporting_calendar (
            ticker TEXT PRIMARY KEY,
            next_financial_report_date TEXT,
            next_production_report_date TEXT,
            notes TEXT,
            created_at_utc TEXT,
            updated_at_utc TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_notes (
            note_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            note_text TEXT NOT NULL,
            note_tag TEXT,
            note_status TEXT NOT NULL,
            created_at_utc TEXT NOT NULL,
            updated_at_utc TEXT NOT NULL
        )
        """
    )
    _ensure_column(connection, "company_inputs", "created_at_utc", "TEXT")
    _ensure_column(connection, "company_inputs", "updated_at_utc", "TEXT")
    _ensure_column(connection, "source_verification", "created_at_utc", "TEXT")
    _ensure_column(connection, "source_verification", "updated_at_utc", "TEXT")
    _ensure_column(connection, "reporting_calendar", "created_at_utc", "TEXT")
    _ensure_column(connection, "reporting_calendar", "updated_at_utc", "TEXT")
    now_utc = _utc_timestamp()
    connection.execute(
        "UPDATE company_inputs SET created_at_utc = COALESCE(created_at_utc, ?), updated_at_utc = COALESCE(updated_at_utc, created_at_utc, ?)",
        (now_utc, now_utc),
    )
    connection.execute(
        "UPDATE source_verification SET created_at_utc = COALESCE(created_at_utc, ?), updated_at_utc = COALESCE(updated_at_utc, created_at_utc, ?)",
        (now_utc, now_utc),
    )
    connection.execute(
        "UPDATE reporting_calendar SET created_at_utc = COALESCE(created_at_utc, ?), updated_at_utc = COALESCE(updated_at_utc, created_at_utc, ?)",
        (now_utc, now_utc),
    )


def _seed_ticker_rows(connection: sqlite3.Connection, tickers: list[str]) -> list[str]:
    seeded_tickers: list[str] = []
    now_utc = _utc_timestamp()
    for ticker in tickers:
        company_insert = connection.execute(
            """
            INSERT OR IGNORE INTO company_inputs (ticker, created_at_utc, updated_at_utc)
            VALUES (?, ?, ?)
            """,
            (ticker, now_utc, now_utc),
        )
        calendar_insert = connection.execute(
            """
            INSERT OR IGNORE INTO reporting_calendar (ticker, created_at_utc, updated_at_utc)
            VALUES (?, ?, ?)
            """,
            (ticker, now_utc, now_utc),
        )
        if company_insert.rowcount or calendar_insert.rowcount:
            seeded_tickers.append(ticker)
    return seeded_tickers


def _ensure_single_ticker_seeded(connection: sqlite3.Connection, ticker: str) -> None:
    _seed_ticker_rows(connection, [ticker])


def _store_has_no_manual_content(connection: sqlite3.Connection) -> bool:
    company_count = connection.execute(
        "SELECT COUNT(*) FROM company_inputs WHERE " + " OR ".join(f"{field_name} IS NOT NULL" for field_name in NUMERIC_COMPANY_FIELDS)
    ).fetchone()[0]
    verification_count = connection.execute("SELECT COUNT(*) FROM source_verification").fetchone()[0]
    reporting_count = connection.execute(
        """
        SELECT COUNT(*) FROM reporting_calendar
        WHERE next_financial_report_date IS NOT NULL
           OR next_production_report_date IS NOT NULL
           OR notes IS NOT NULL
        """
    ).fetchone()[0]
    note_count = connection.execute("SELECT COUNT(*) FROM stock_notes").fetchone()[0]
    return int(company_count) == 0 and int(verification_count) == 0 and int(reporting_count) == 0 and int(note_count) == 0


def _import_csv_support_files(
    connection: sqlite3.Connection,
    paths: ProjectPaths,
) -> list[str]:
    imported_files: list[str] = []
    company_path = paths.manual_screening_dir / "company_inputs.csv"
    if company_path.exists():
        frame = pd.read_csv(company_path)
        frame = _normalize_company_inputs(frame)
        for _, row in frame.iterrows():
            connection.execute(
                """
                INSERT INTO company_inputs (
                    ticker,
                    production_oz,
                    aisc_usd_per_oz,
                    cash_cost_usd_per_oz,
                    royalty_rate,
                    sustaining_capex_musd,
                    da_musd,
                    interest_expense_musd,
                    tax_rate,
                    reserve_life_years,
                    net_debt_musd,
                    ebitda_ltm_musd,
                    created_at_utc,
                    updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    production_oz = excluded.production_oz,
                    aisc_usd_per_oz = excluded.aisc_usd_per_oz,
                    cash_cost_usd_per_oz = excluded.cash_cost_usd_per_oz,
                    royalty_rate = excluded.royalty_rate,
                    sustaining_capex_musd = excluded.sustaining_capex_musd,
                    da_musd = excluded.da_musd,
                    interest_expense_musd = excluded.interest_expense_musd,
                    tax_rate = excluded.tax_rate,
                    reserve_life_years = excluded.reserve_life_years,
                    net_debt_musd = excluded.net_debt_musd,
                    ebitda_ltm_musd = excluded.ebitda_ltm_musd,
                    updated_at_utc = excluded.updated_at_utc
                """,
                    (
                        tuple(
                            _sqlite_value(row.get(column))
                            for column in COMPANY_INPUT_COLUMNS
                            if column not in TIMESTAMP_COLUMNS
                        )
                        + (_utc_timestamp(), _utc_timestamp())
                    ),
                )
        imported_files.append(company_path.name)

    verification_path = paths.manual_screening_dir / "source_verification.csv"
    if verification_path.exists():
        frame = pd.read_csv(verification_path)
        frame = _normalize_source_verification(frame)
        for _, row in frame.iterrows():
            connection.execute(
                """
                INSERT INTO source_verification (
                    ticker,
                    field_name,
                    verification_status,
                    source_date,
                    source_url,
                    notes,
                    created_at_utc,
                    updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, field_name) DO UPDATE SET
                    verification_status = excluded.verification_status,
                    source_date = excluded.source_date,
                    source_url = excluded.source_url,
                    notes = excluded.notes,
                    updated_at_utc = excluded.updated_at_utc
                """,
                    (
                        tuple(
                            _sqlite_value(row.get(column))
                            for column in SOURCE_VERIFICATION_COLUMNS
                            if column not in TIMESTAMP_COLUMNS
                        )
                        + (_utc_timestamp(), _utc_timestamp())
                    ),
                )
        imported_files.append(verification_path.name)

    reporting_path = paths.manual_screening_dir / "reporting_calendar.csv"
    if reporting_path.exists():
        frame = pd.read_csv(reporting_path)
        frame = _normalize_reporting_calendar(frame)
        for _, row in frame.iterrows():
            connection.execute(
                """
                INSERT INTO reporting_calendar (
                    ticker,
                    next_financial_report_date,
                    next_production_report_date,
                    notes,
                    created_at_utc,
                    updated_at_utc
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    next_financial_report_date = excluded.next_financial_report_date,
                    next_production_report_date = excluded.next_production_report_date,
                    notes = excluded.notes,
                    updated_at_utc = excluded.updated_at_utc
                """,
                    (
                        tuple(
                            _sqlite_value(row.get(column))
                            for column in REPORTING_CALENDAR_COLUMNS
                            if column not in TIMESTAMP_COLUMNS
                        )
                        + (_utc_timestamp(), _utc_timestamp())
                    ),
                )
        imported_files.append(reporting_path.name)

    return imported_files


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
    for column in TIMESTAMP_COLUMNS:
        normalized[column] = normalized[column].apply(_normalize_text_value)
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
    normalized["source_date"] = pd.to_datetime(normalized["source_date"], errors="coerce").dt.date
    normalized["source_url"] = normalized["source_url"].apply(_normalize_text_value)
    normalized["notes"] = normalized["notes"].apply(_normalize_text_value)
    for column in TIMESTAMP_COLUMNS:
        normalized[column] = normalized[column].apply(_normalize_text_value)
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
    normalized["next_financial_report_date"] = pd.to_datetime(
        normalized["next_financial_report_date"],
        errors="coerce",
    ).dt.date
    normalized["next_production_report_date"] = pd.to_datetime(
        normalized["next_production_report_date"],
        errors="coerce",
    ).dt.date
    normalized["notes"] = normalized["notes"].apply(_normalize_text_value)
    for column in TIMESTAMP_COLUMNS:
        normalized[column] = normalized[column].apply(_normalize_text_value)
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized.drop_duplicates(subset=["ticker"], keep="last")
    return normalized[REPORTING_CALENDAR_COLUMNS].reset_index(drop=True)


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    existing_columns = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in existing_columns:
        return
    connection.execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _backup_existing_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = path.with_name(f"{path.stem}_{timestamp}.bak{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def _normalize_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def _normalize_numeric_value(field_name: str, value: object) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc
    if field_name in {"royalty_rate", "tax_rate"} and numeric > 1.0:
        return numeric / 100.0
    return numeric


def _normalize_date_value(value: object) -> str | None:
    normalized = _normalize_text_value(value)
    if normalized is None:
        return None
    return str(pd.to_datetime(normalized, errors="raise").date())


def _normalize_text_value(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _normalize_rate(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1.0:
        return numeric / 100.0
    return numeric


def _sqlite_value(value: object) -> object:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
