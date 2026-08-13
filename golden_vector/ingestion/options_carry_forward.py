"""Resolve verified per-ticker option snapshots for partial-refresh recovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.model_state import read_current_model_json
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import sha256_file
from golden_vector.common.options_schema import OPTIONS_FEATURE_REQUIRED_COLUMNS
from golden_vector.common.parquet import read_required_parquet
from golden_vector.common.strings import normalize_ticker


@dataclass(frozen=True)
class PreviousOptionsTickerBundle:
    """One previously published ticker snapshot and its exact feature row."""

    ticker: str
    snapshot: pd.DataFrame
    feature: pd.DataFrame
    feature_row: dict[str, Any]
    manifest_entry: dict[str, Any]
    source_refresh_run_id: str
    source_as_of_date: str
    captured_at_utc: str | None


def load_previous_options_ticker_bundles(
    paths: ProjectPaths,
) -> dict[str, PreviousOptionsTickerBundle]:
    """Load only prior ticker bundles whose chain and feature both verify.

    Invalid prior rows are deliberately omitted. The caller can then publish an
    honest unavailable result instead of reviving an unverified partial bundle.
    """

    manifest = read_current_model_json(
        paths,
        "options",
        fallback_path=paths.latest_options_manifest_path,
    )
    if not isinstance(manifest, dict):
        return {}
    # Per-ticker carry requires both parts of the bundle to be immutable and
    # checksum-addressed. A v1 mutable feature-history file cannot prove that.
    if int(manifest.get("manifest_version") or 1) < 2:
        return {}
    bundles: dict[str, PreviousOptionsTickerBundle] = {}
    for raw_entry in manifest.get("snapshots") or []:
        if not isinstance(raw_entry, dict):
            continue
        ticker = normalize_ticker(raw_entry.get("ticker"))
        if not ticker or _upper(raw_entry.get("feature_status") or "OK") == "ERROR":
            continue
        try:
            bundle = _load_bundle(
                paths=paths,
                manifest=manifest,
                entry=raw_entry,
                ticker=ticker,
            )
        except (FileNotFoundError, OSError, ValueError):
            continue
        bundles[ticker] = bundle
    return bundles


def _load_bundle(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
    entry: dict[str, Any],
    ticker: str,
) -> PreviousOptionsTickerBundle:
    source_run_id = _text(entry.get("source_refresh_run_id")) or _text(
        manifest.get("refresh_run_id")
    )
    source_date = _text(entry.get("source_as_of_date")) or _text(manifest.get("as_of_date"))
    relative_snapshot = _text(entry.get("snapshot_path"))
    expected_sha = _text(entry.get("sha256"))
    if not source_run_id or not source_date or not relative_snapshot or not expected_sha:
        raise ValueError("Prior ticker bundle has incomplete source provenance.")

    snapshot_path = paths.resolve_repo_relative(relative_snapshot)
    if sha256_file(snapshot_path) != expected_sha:
        raise ValueError(f"Prior options snapshot checksum mismatch for {ticker}.")
    snapshot = read_required_parquet(
        snapshot_path,
        label=f"Prior options chain snapshot for {ticker}",
        required_columns=("ticker",),
    )
    normalized = snapshot["ticker"].map(normalize_ticker)
    if snapshot.empty or normalized.isna().any() or set(normalized) != {ticker}:
        raise ValueError(f"Prior options snapshot ticker identity is invalid for {ticker}.")
    if int(manifest.get("manifest_version") or 1) >= 2:
        _require_single_value(snapshot, "source_refresh_run_id", source_run_id)
        _require_single_value(snapshot, "source_as_of_date", source_date)

    feature_relative = _text(entry.get("feature_path"))
    feature_sha = _text(entry.get("feature_sha256"))
    if not feature_relative or not feature_sha:
        raise ValueError("Prior ticker bundle has no immutable feature snapshot.")
    feature_path = paths.resolve_repo_relative(feature_relative)
    if sha256_file(feature_path) != feature_sha:
        raise ValueError(f"Prior options feature checksum mismatch for {ticker}.")
    features = read_required_parquet(
        feature_path,
        label=f"Prior options feature snapshot for {ticker}",
        required_columns=(*OPTIONS_FEATURE_REQUIRED_COLUMNS, "run_id"),
    )
    if len(features.index) != 1:
        raise ValueError(
            f"Prior immutable options feature snapshot for {ticker} must have one row."
        )
    matching = features[
        (features["run_id"].astype(str) == source_run_id)
        & (features["ticker"].map(normalize_ticker) == ticker)
    ]
    if matching.empty:
        raise ValueError(
            f"Prior options feature snapshot for {ticker} has no row for {source_run_id}."
        )
    feature_row = matching.iloc[-1].to_dict()
    captured_at = _text(entry.get("captured_at_utc")) or _first_text(
        snapshot, "captured_at_utc"
    )
    if captured_at is None:
        captured_at = _file_timestamp(snapshot_path)
    return PreviousOptionsTickerBundle(
        ticker=ticker,
        snapshot=snapshot,
        feature=matching.iloc[[-1]].copy().reset_index(drop=True),
        feature_row=feature_row,
        manifest_entry=dict(entry),
        source_refresh_run_id=source_run_id,
        source_as_of_date=source_date,
        captured_at_utc=captured_at,
    )


def _require_single_value(frame: pd.DataFrame, column: str, expected: str) -> None:
    if column not in frame.columns:
        raise ValueError(f"Prior options snapshot is missing {column}.")
    values = {str(value).strip() for value in frame[column].dropna() if str(value).strip()}
    if values != {expected}:
        raise ValueError(f"Prior options snapshot has inconsistent {column}.")


def _first_text(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame.columns:
        return None
    values = frame[column].dropna()
    return _text(values.iloc[0]) if not values.empty else None


def _file_timestamp(path: Path) -> str:
    return pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat()


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text.lower() != "nan" else None


def _upper(value: object) -> str:
    return (_text(value) or "").upper()
