"""Cumulative raw fundamentals history store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import pandas as pd

from golden_vector.app.run_context import to_jsonable
from golden_vector.common.parquet import read_required_parquet, write_parquet_atomic
from golden_vector.contracts.fundamentals import (
    RAW_FUNDAMENTALS_HISTORY_COLUMNS,
    RAW_FUNDAMENTALS_HISTORY_SCHEMA_VERSION,
    RAW_FUNDAMENTALS_STATEMENTS_COLUMNS,
    raw_fundamentals_history_latest_path,
    raw_fundamentals_history_run_stamped_path,
)
from golden_vector.fundamentals.raw_store import normalize_raw_fundamentals_frame

HISTORY_KEY_COLUMNS = (
    "ticker",
    "yahoo_symbol",
    "statement_type",
    "line_item_original",
    "period_end",
    "period_type",
)


@dataclass(frozen=True)
class RawFundamentalsHistoryWrite:
    run_path: str
    latest_path: str | None
    row_count: int


def write_raw_fundamentals_history_artifact_pair(
    *,
    paths,
    incoming: pd.DataFrame,
    source_run_id: str,
    publish_latest_alias: bool = True,
) -> RawFundamentalsHistoryWrite:
    """Merge this fetch's raw statements into the cumulative history artifact."""

    existing = _read_existing_history(paths)
    merged = merge_raw_fundamentals_history(
        existing=existing,
        incoming=incoming,
        source_run_id=source_run_id,
    )
    run_path = raw_fundamentals_history_run_stamped_path(paths, source_run_id)
    latest_path = raw_fundamentals_history_latest_path(paths)
    write_parquet_atomic(merged, run_path, index=False)
    if publish_latest_alias:
        write_parquet_atomic(merged, latest_path, index=False)
    return RawFundamentalsHistoryWrite(
        run_path=run_path.as_posix(),
        latest_path=latest_path.as_posix() if publish_latest_alias else None,
        row_count=int(len(merged.index)),
    )


def merge_raw_fundamentals_history(
    *,
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame,
    source_run_id: str,
) -> pd.DataFrame:
    normalized_incoming = normalize_raw_fundamentals_frame(
        incoming,
        source_run_id=source_run_id,
    )
    normalized_incoming = normalized_incoming[
        normalized_incoming["statement_type"].astype(str).str.strip() != ""
    ].copy()
    prepared_existing = _normalize_history_frame(existing)
    prepared_incoming = _incoming_history_frame(normalized_incoming, source_run_id)

    by_key = {
        _history_key(row): row
        for row in prepared_existing.to_dict(orient="records")
    }
    for row in prepared_incoming.to_dict(orient="records"):
        key = _history_key(row)
        prior = by_key.get(key)
        if prior is not None:
            row["first_seen_source_run_id"] = prior.get("first_seen_source_run_id")
            row["first_seen_at_utc"] = prior.get("first_seen_at_utc")
        by_key[key] = row

    if not by_key:
        return _empty_history_frame()
    merged = pd.DataFrame(by_key.values())
    for column in RAW_FUNDAMENTALS_HISTORY_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA
    merged = merged[list(RAW_FUNDAMENTALS_HISTORY_COLUMNS)]
    merged = merged.sort_values(list(HISTORY_KEY_COLUMNS)).reset_index(drop=True)
    merged.attrs["schema_version"] = RAW_FUNDAMENTALS_HISTORY_SCHEMA_VERSION
    return merged


def _incoming_history_frame(frame: pd.DataFrame, source_run_id: str) -> pd.DataFrame:
    if frame.empty:
        return _empty_history_frame()
    history = frame.copy()
    history["schema_version"] = RAW_FUNDAMENTALS_HISTORY_SCHEMA_VERSION
    history["row_hash"] = history.apply(_row_hash, axis=1)
    history["first_seen_source_run_id"] = source_run_id
    history["last_seen_source_run_id"] = source_run_id
    history["first_seen_at_utc"] = history["fetched_at_utc"]
    history["last_seen_at_utc"] = history["fetched_at_utc"]
    return history[list(RAW_FUNDAMENTALS_HISTORY_COLUMNS)]


def _normalize_history_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return _empty_history_frame()
    normalized = frame.copy()
    for column in RAW_FUNDAMENTALS_HISTORY_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    return normalized[list(RAW_FUNDAMENTALS_HISTORY_COLUMNS)].reset_index(drop=True)


def _read_existing_history(paths) -> pd.DataFrame:
    path = raw_fundamentals_history_latest_path(paths)
    if not path.exists():
        return _empty_history_frame()
    return read_required_parquet(
        path,
        label="raw fundamentals history",
        required_columns=RAW_FUNDAMENTALS_HISTORY_COLUMNS,
        schema_version=RAW_FUNDAMENTALS_HISTORY_SCHEMA_VERSION,
    )


def _empty_history_frame() -> pd.DataFrame:
    frame = pd.DataFrame(columns=RAW_FUNDAMENTALS_HISTORY_COLUMNS)
    frame.attrs["schema_version"] = RAW_FUNDAMENTALS_HISTORY_SCHEMA_VERSION
    return frame


def _history_key(row: dict[str, object]) -> tuple[str, ...]:
    return tuple(str(row.get(column) or "") for column in HISTORY_KEY_COLUMNS)


def _row_hash(row: pd.Series) -> str:
    payload = {
        column: row.get(column)
        for column in RAW_FUNDAMENTALS_STATEMENTS_COLUMNS
        if column not in {"schema_version", "source_run_id", "fetched_at_utc"}
    }
    encoded = json.dumps(to_jsonable(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
