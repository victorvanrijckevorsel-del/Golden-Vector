"""Shared Parquet read helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

from golden_vector.common.files import atomic_write_file


class ParquetSchemaError(ValueError):
    """Raised when a required Parquet artifact does not match its contract."""


def read_optional_parquet(path: Path | None) -> pd.DataFrame:
    """Best-effort Parquet reader for optional local artifacts."""

    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def read_required_parquet(
    path: Path,
    *,
    label: str,
    required_columns: Iterable[str] | None = None,
    schema_version: int | str | None = None,
    column_dtypes: Mapping[str, str | Iterable[str]] | None = None,
) -> pd.DataFrame:
    """Read and validate a required Parquet artifact with one error shape."""

    if not path.exists():
        raise FileNotFoundError(f"{label} is missing: {path}")
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise ValueError(f"{label} could not be read: {exc}") from exc
    validate_parquet_schema(
        frame,
        label=label,
        required_columns=required_columns,
        schema_version=schema_version,
        column_dtypes=column_dtypes,
    )
    return frame


def validate_parquet_schema(
    frame: pd.DataFrame,
    *,
    label: str,
    required_columns: Iterable[str] | None = None,
    schema_version: int | str | None = None,
    column_dtypes: Mapping[str, str | Iterable[str]] | None = None,
) -> None:
    """Validate a loaded Parquet frame using the shared checked-read contract."""

    errors: list[str] = []
    required = tuple(required_columns or ())
    missing = [column for column in required if column not in frame.columns]
    if missing:
        errors.append(f"missing columns: {', '.join(missing)}")

    if schema_version is not None:
        actual_schema_versions = _schema_versions(frame)
        if len(actual_schema_versions) > 1:
            errors.append(
                "schema_version expected "
                f"{schema_version}, got multiple values: "
                f"{', '.join(actual_schema_versions)}"
            )
        elif not actual_schema_versions or actual_schema_versions[0] != str(schema_version):
            actual_schema_version = (
                actual_schema_versions[0] if actual_schema_versions else "missing"
            )
            errors.append(
                f"schema_version expected {schema_version}, got "
                f"{actual_schema_version}"
            )

    for column, expected in (column_dtypes or {}).items():
        if column not in frame.columns:
            continue
        actual_dtype = str(frame[column].dtype)
        expected_values = (
            (expected,)
            if isinstance(expected, str)
            else tuple(str(value) for value in expected)
        )
        if actual_dtype not in expected_values:
            errors.append(
                f"{column} dtype expected one of "
                f"{', '.join(expected_values)}, got {actual_dtype}"
            )

    if errors:
        raise ParquetSchemaError(
            f"{label} schema validation failed: {'; '.join(errors)}"
        )


def write_parquet_atomic(frame: pd.DataFrame, path: Path, *, index: bool = False) -> Path:
    """Write a Parquet file through a unique temp file and atomic replace."""

    return atomic_write_file(
        path,
        lambda temporary_path: frame.to_parquet(temporary_path, index=index),
    )


def _schema_versions(frame: pd.DataFrame) -> list[str]:
    if "schema_version" in frame.columns:
        values = [
            str(value)
            for value in frame["schema_version"].dropna().unique().tolist()
        ]
        if values:
            return sorted(values)
    value = frame.attrs.get("schema_version")
    if _is_missing(value):
        return []
    return [str(value)]


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except Exception:
        return False
    if isinstance(missing, bool):
        return missing
    return False
