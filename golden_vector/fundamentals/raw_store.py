"""Durable storage for raw Yahoo fundamentals statements."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import to_jsonable
from golden_vector.common.files import atomic_write_text, repo_relative, sha256_file
from golden_vector.common.parquet import read_required_parquet, write_parquet_atomic
from golden_vector.contracts.fundamentals import (
    FUNDAMENTALS_FETCH_MANIFEST_VERSION,
    RAW_FUNDAMENTALS_STATEMENTS_COLUMNS,
    RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION,
    fundamentals_fetch_manifest_run_stamped_path,
    raw_fundamentals_statements_latest_path,
    raw_fundamentals_statements_run_stamped_path,
)

STATEMENT_TYPES: tuple[str, ...] = ("income_stmt", "balance_sheet", "cashflow")
RAW_FETCH_STATUS_PASS = "PASS"
RAW_FETCH_STATUS_FAIL = "FAIL"
RAW_FETCH_STATUS_EMPTY = "EMPTY"


@dataclass(frozen=True)
class RawFundamentalsArtifactWrite:
    run_path: str
    latest_path: str | None
    row_count: int


def raw_statement_payload_to_frame(
    *,
    ticker: str,
    yahoo_symbol: str,
    payload: dict[str, object],
    fetched_at_utc: str,
    source_run_id: str,
    error_message: str | None = None,
) -> pd.DataFrame:
    """Flatten one Yahoo statement payload into the canonical raw long table."""

    ticker = _clean_code(ticker)
    yahoo_symbol = _clean_code(yahoo_symbol)
    source_run_id = _require_source_run_id(source_run_id)
    financial_currency = _clean_currency(payload.get("financialCurrency"))
    rows: list[dict[str, object]] = []
    if not payload:
        return _status_frame(
            ticker=ticker,
            yahoo_symbol=yahoo_symbol,
            fetched_at_utc=fetched_at_utc,
            source_run_id=source_run_id,
            financial_currency=financial_currency,
            fetch_status=RAW_FETCH_STATUS_FAIL,
            error_message=error_message or "Yahoo returned no financial statements.",
        )
    for statement_type in STATEMENT_TYPES:
        frame = payload.get(statement_type)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        rows.extend(
            _flatten_statement_frame(
                ticker=ticker,
                yahoo_symbol=yahoo_symbol,
                statement_type=statement_type,
                frame=frame,
                financial_currency=financial_currency,
                fetched_at_utc=fetched_at_utc,
                source_run_id=source_run_id,
            )
        )
    if not rows:
        return _status_frame(
            ticker=ticker,
            yahoo_symbol=yahoo_symbol,
            fetched_at_utc=fetched_at_utc,
            source_run_id=source_run_id,
            financial_currency=financial_currency,
            fetch_status=RAW_FETCH_STATUS_EMPTY,
            error_message=error_message or "Yahoo returned empty financial statement frames.",
        )
    return normalize_raw_fundamentals_frame(pd.DataFrame(rows), source_run_id=source_run_id)


def write_raw_fundamentals_artifact_pair(
    *,
    paths: ProjectPaths,
    frame: pd.DataFrame,
    source_run_id: str,
    publish_latest_alias: bool = True,
) -> RawFundamentalsArtifactWrite:
    """Write immutable + latest raw Yahoo fundamentals artifacts."""

    normalized = normalize_raw_fundamentals_frame(frame, source_run_id=source_run_id)
    run_path = raw_fundamentals_statements_run_stamped_path(paths, source_run_id)
    latest_path = raw_fundamentals_statements_latest_path(paths)
    write_parquet_atomic(normalized, run_path, index=False)
    if publish_latest_alias:
        write_parquet_atomic(normalized, latest_path, index=False)
    return RawFundamentalsArtifactWrite(
        run_path=run_path.as_posix(),
        latest_path=latest_path.as_posix() if publish_latest_alias else None,
        row_count=int(len(normalized.index)),
    )


def load_raw_fundamentals_statements(
    paths: ProjectPaths,
    *,
    source_run_id: str | None = None,
    ticker: str | None = None,
    statement_type: str | None = None,
) -> pd.DataFrame:
    """Load raw fundamentals statements from the latest alias or a run id."""

    path = (
        raw_fundamentals_statements_run_stamped_path(paths, source_run_id)
        if source_run_id
        else raw_fundamentals_statements_latest_path(paths)
    )
    frame = read_required_parquet(
        path,
        label="raw fundamentals statements",
        required_columns=RAW_FUNDAMENTALS_STATEMENTS_COLUMNS,
        schema_version=RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION,
    )
    frame = validate_raw_fundamentals_frame(frame)
    if ticker:
        frame = frame[frame["ticker"].eq(_clean_code(ticker))].copy()
    if statement_type:
        frame = frame[frame["statement_type"].eq(str(statement_type).strip())].copy()
    return frame.reset_index(drop=True)


def write_fundamentals_fetch_manifest(
    *,
    paths: ProjectPaths,
    source_run_id: str,
    fetched_at_utc: str,
    raw_run_path: str,
    raw_latest_path: str | None,
    ticker_statuses: list[dict[str, object]],
    timings: dict[str, object],
    official_artifact: dict[str, object] | None = None,
    publish_latest_alias: bool = True,
) -> dict[str, object]:
    """Write latest + run-stamped fetch manifests for the raw fundamentals stage."""

    source_run_id = _require_source_run_id(source_run_id)
    raw_path = paths.resolve_repo_relative(raw_run_path)
    latest_path = paths.resolve_repo_relative(raw_latest_path) if raw_latest_path else None
    payload: dict[str, object] = {
        "manifest_version": FUNDAMENTALS_FETCH_MANIFEST_VERSION,
        "source_run_id": source_run_id,
        "fetched_at_utc": fetched_at_utc,
        "raw_statements": {
            "path": repo_relative(paths, raw_path),
            "latest_alias_path": (
                repo_relative(paths, latest_path) if latest_path is not None else None
            ),
            "sha256": sha256_file(raw_path) if raw_path.exists() else None,
            "latest_alias_sha256": (
                sha256_file(latest_path)
                if latest_path is not None and latest_path.exists()
                else None
            ),
        },
        "official_artifact": official_artifact or {},
        "ticker_statuses": ticker_statuses,
        "stage_timings": timings,
        "summary": _status_summary(ticker_statuses),
    }
    serialized = json.dumps(to_jsonable(payload), indent=2, sort_keys=True)
    run_manifest_path = fundamentals_fetch_manifest_run_stamped_path(paths, source_run_id)
    latest_manifest_path = paths.latest_fundamentals_fetch_manifest_path
    atomic_write_text(run_manifest_path, serialized)
    if publish_latest_alias:
        atomic_write_text(latest_manifest_path, serialized)
    return payload


def load_latest_fundamentals_fetch_manifest(paths: ProjectPaths) -> dict[str, object] | None:
    """Load the latest raw fundamentals fetch manifest if present."""

    path = paths.latest_fundamentals_fetch_manifest_path
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def normalize_raw_fundamentals_frame(
    frame: pd.DataFrame,
    *,
    source_run_id: str,
) -> pd.DataFrame:
    """Normalize raw Yahoo statement rows without mapping or financial judgment."""

    source_run_id = _require_source_run_id(source_run_id)
    normalized = frame.copy()
    for column in RAW_FUNDAMENTALS_STATEMENTS_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["schema_version"] = RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION
    normalized["source_run_id"] = source_run_id
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    normalized["yahoo_symbol"] = (
        normalized["yahoo_symbol"].fillna("").astype(str).str.upper().str.strip()
    )
    normalized["statement_type"] = (
        normalized["statement_type"].fillna("").astype(str).str.strip()
    )
    normalized["line_item_original"] = normalized["line_item_original"].astype("object").where(
        normalized["line_item_original"].notna(),
        None,
    )
    normalized["period_end"] = pd.to_datetime(normalized["period_end"], errors="coerce").dt.date
    normalized["value_raw"] = pd.to_numeric(normalized["value_raw"], errors="coerce")
    normalized["financial_currency"] = (
        normalized["financial_currency"].fillna("").astype(str).str.upper().str.strip()
    )
    normalized["fetched_at_utc"] = (
        normalized["fetched_at_utc"].fillna("").astype(str).str.strip()
    )
    normalized["fetch_status"] = normalized["fetch_status"].fillna(
        RAW_FETCH_STATUS_PASS
    ).astype(str).str.upper().str.strip()
    normalized["error_message"] = normalized["error_message"].astype("object").where(
        normalized["error_message"].notna(),
        None,
    )
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized[list(RAW_FUNDAMENTALS_STATEMENTS_COLUMNS)].reset_index(drop=True)
    normalized.attrs["schema_version"] = RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION
    normalized.attrs["source_run_id"] = source_run_id
    return validate_raw_fundamentals_frame(normalized)


def validate_raw_fundamentals_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate the raw fundamentals storage contract."""

    missing = [
        column for column in RAW_FUNDAMENTALS_STATEMENTS_COLUMNS if column not in frame.columns
    ]
    if missing:
        raise ValueError(
            "raw fundamentals statements artifact is missing columns: "
            + ", ".join(missing)
        )
    invalid_statement_types = sorted(
        set(frame["statement_type"].dropna().astype(str)) - set(STATEMENT_TYPES) - {""}
    )
    if invalid_statement_types:
        raise ValueError(
            "raw fundamentals statements contain unsupported statement_type values: "
            + ", ".join(invalid_statement_types)
        )
    invalid_statuses = sorted(
        set(frame["fetch_status"].dropna().astype(str))
        - {RAW_FETCH_STATUS_PASS, RAW_FETCH_STATUS_FAIL, RAW_FETCH_STATUS_EMPTY}
    )
    if invalid_statuses:
        raise ValueError(
            "raw fundamentals statements contain unsupported fetch_status values: "
            + ", ".join(invalid_statuses)
        )
    return frame.copy()


def _flatten_statement_frame(
    *,
    ticker: str,
    yahoo_symbol: str,
    statement_type: str,
    frame: pd.DataFrame,
    financial_currency: str,
    fetched_at_utc: str,
    source_run_id: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    prepared = frame.copy()
    for line_item, row in prepared.iterrows():
        for period_end, value in row.items():
            rows.append(
                {
                    "schema_version": RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION,
                    "ticker": ticker,
                    "yahoo_symbol": yahoo_symbol,
                    "statement_type": statement_type,
                    "line_item_original": str(line_item),
                    "period_end": period_end,
                    "value_raw": value,
                    "financial_currency": financial_currency,
                    "fetched_at_utc": fetched_at_utc,
                    "source_run_id": source_run_id,
                    "fetch_status": RAW_FETCH_STATUS_PASS,
                    "error_message": None,
                }
            )
    return rows


def _status_frame(
    *,
    ticker: str,
    yahoo_symbol: str,
    fetched_at_utc: str,
    source_run_id: str,
    financial_currency: str,
    fetch_status: str,
    error_message: str,
) -> pd.DataFrame:
    return normalize_raw_fundamentals_frame(
        pd.DataFrame(
            [
                {
                    "schema_version": RAW_FUNDAMENTALS_STATEMENTS_SCHEMA_VERSION,
                    "ticker": ticker,
                    "yahoo_symbol": yahoo_symbol,
                    "statement_type": "",
                    "line_item_original": None,
                    "period_end": None,
                    "value_raw": None,
                    "financial_currency": financial_currency,
                    "fetched_at_utc": fetched_at_utc,
                    "source_run_id": source_run_id,
                    "fetch_status": fetch_status,
                    "error_message": error_message,
                }
            ]
        ),
        source_run_id=source_run_id,
    )


def _status_summary(ticker_statuses: list[dict[str, object]]) -> dict[str, object]:
    total = len(ticker_statuses)
    pass_count = sum(1 for row in ticker_statuses if str(row.get("status")).upper() == "PASS")
    fail_count = sum(1 for row in ticker_statuses if str(row.get("status")).upper() == "FAIL")
    empty_count = sum(1 for row in ticker_statuses if str(row.get("status")).upper() == "EMPTY")
    return {
        "ticker_count": total,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "empty_count": empty_count,
    }


def _clean_code(value: object) -> str:
    return str(value or "").strip().upper()


def _clean_currency(value: object) -> str:
    return str(value or "").strip().upper()


def _require_source_run_id(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError("raw fundamentals source_run_id is required")
    return cleaned
