"""Read and write official fundamentals artifacts."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.app.model_state import resolve_current_model_artifact_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.parquet import read_required_parquet, write_parquet_atomic
from golden_vector.contracts.fundamentals import (
    FETCHED_FUNDAMENTALS_COLUMNS,
    FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
    FUNDAMENTAL_VALUE_STATUSES,
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
    fetched_fundamentals_latest_path,
    fetched_fundamentals_run_stamped_path,
)
from golden_vector.screening.manual_store import FINANCIAL_DUAL_SOURCE_FIELDS


@dataclass(frozen=True)
class FetchedFundamentalsArtifactWrite:
    run_path: str
    latest_path: str | None
    row_count: int


def write_fetched_fundamentals_artifact_pair(
    *,
    paths: ProjectPaths,
    frame: pd.DataFrame,
    source_run_id: str,
    publish_latest_alias: bool = True,
) -> FetchedFundamentalsArtifactWrite:
    """Write immutable + latest official fundamentals artifacts."""

    normalized = normalize_fetched_fundamentals_frame(
        frame,
        source_run_id=source_run_id,
    )
    run_path = fetched_fundamentals_run_stamped_path(paths, source_run_id)
    latest_path = fetched_fundamentals_latest_path(paths)
    write_parquet_atomic(normalized, run_path, index=False)
    if publish_latest_alias:
        write_parquet_atomic(normalized, latest_path, index=False)
    return FetchedFundamentalsArtifactWrite(
        run_path=run_path.as_posix(),
        latest_path=latest_path.as_posix() if publish_latest_alias else None,
        row_count=int(len(normalized.index)),
    )


def load_official_fundamentals(paths: ProjectPaths) -> pd.DataFrame:
    """Load the manifest-resolved official fundamentals artifact, if present."""

    path = resolve_current_model_artifact_path(
        paths,
        FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
        fallback_path=fetched_fundamentals_latest_path(paths),
    )
    if path is None:
        return empty_fetched_fundamentals_frame()
    frame = read_required_parquet(
        path,
        label="official fundamentals",
        required_columns=FETCHED_FUNDAMENTALS_COLUMNS,
        schema_version=FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
    )
    return validate_fetched_fundamentals_frame(frame)


def normalize_fetched_fundamentals_frame(
    frame: pd.DataFrame,
    *,
    source_run_id: str,
) -> pd.DataFrame:
    """Normalize and validate the canonical official fundamentals frame."""

    source_run_id = str(source_run_id or "").strip()
    if not source_run_id:
        raise ValueError("official fundamentals source_run_id is required")
    normalized = frame.copy()
    for column in FETCHED_FUNDAMENTALS_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["schema_version"] = FETCHED_FUNDAMENTALS_SCHEMA_VERSION
    normalized["source_run_id"] = source_run_id
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    normalized["field_name"] = normalized["field_name"].fillna("").astype(str).str.strip()
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    normalized["value_status"] = (
        normalized["value_status"].fillna("MISSING").astype(str).str.upper().str.strip()
    )
    normalized["source"] = normalized["source"].fillna("YAHOO").astype(str).str.upper().str.strip()
    for column in (
        "fetched_at_utc",
        "statement_period",
        "period_end",
        "period_type",
        "statement_currency",
        "statement_scale",
    ):
        normalized[column] = normalized[column].astype("object").where(
            normalized[column].notna(),
            None,
        )
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized[normalized["field_name"] != ""].copy()
    normalized = normalized.drop_duplicates(
        subset=["ticker", "field_name"],
        keep="last",
    )
    normalized = normalized[list(FETCHED_FUNDAMENTALS_COLUMNS)].reset_index(drop=True)
    normalized.attrs["schema_version"] = FETCHED_FUNDAMENTALS_SCHEMA_VERSION
    normalized.attrs["source_run_id"] = source_run_id
    return validate_fetched_fundamentals_frame(normalized)


def validate_fetched_fundamentals_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate official fundamentals values against the shared contract."""

    missing_columns = [
        column for column in FETCHED_FUNDAMENTALS_COLUMNS if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            "official fundamentals artifact is missing columns: "
            + ", ".join(missing_columns)
        )
    invalid_fields = sorted(set(frame["field_name"].dropna()) - FINANCIAL_DUAL_SOURCE_FIELDS)
    if invalid_fields:
        raise ValueError(
            "official fundamentals may only contain financial dual-source fields; "
            f"invalid fields: {', '.join(invalid_fields)}"
        )
    invalid_statuses = sorted(
        set(frame["value_status"].dropna().astype(str)) - set(FUNDAMENTAL_VALUE_STATUSES)
    )
    if invalid_statuses:
        raise ValueError(
            "official fundamentals artifact contains unsupported value_status values: "
            + ", ".join(invalid_statuses)
        )
    return frame.copy()


def empty_fetched_fundamentals_frame() -> pd.DataFrame:
    """Return an empty official fundamentals frame with the canonical columns."""

    frame = pd.DataFrame(columns=FETCHED_FUNDAMENTALS_COLUMNS)
    frame.attrs["schema_version"] = FETCHED_FUNDAMENTALS_SCHEMA_VERSION
    return frame
