"""Shared Parquet read helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.common.files import atomic_write_file


def read_optional_parquet(path: Path | None) -> pd.DataFrame:
    """Best-effort Parquet reader for optional local artifacts."""

    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def read_required_parquet(path: Path, *, label: str) -> pd.DataFrame:
    """Read a required Parquet artifact, raising with context on absence/corruption."""

    if not path.exists():
        raise FileNotFoundError(f"{label} is missing: {path}")
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        raise ValueError(f"{label} could not be read: {exc}") from exc


def write_parquet_atomic(frame: pd.DataFrame, path: Path, *, index: bool = False) -> Path:
    """Write a Parquet file through a unique temp file and atomic replace."""

    return atomic_write_file(
        path,
        lambda temporary_path: frame.to_parquet(temporary_path, index=index),
    )
