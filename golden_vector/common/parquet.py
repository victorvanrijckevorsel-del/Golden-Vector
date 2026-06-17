"""Shared Parquet read helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from golden_vector.common.files import atomic_write_file

PARQUET_METADATA_PREFIX = "golden_vector."
PARQUET_CONTEXT_METADATA_KEYS = (
    "schema_version",
    "snapshot_refresh_run_id",
    "source_run_id",
    "parent_refresh_id",
    "config_hash",
    "risk_free_rate",
    "risk_free_rate_is_fallback",
)


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
    metadata = parquet_context_metadata(path)
    for key, value in metadata.items():
        frame.attrs.setdefault(key, value)
    validate_parquet_schema(
        frame,
        label=label,
        required_columns=required_columns,
        schema_version=schema_version,
        column_dtypes=column_dtypes,
        metadata=metadata,
    )
    return frame


def validate_parquet_schema(
    frame: pd.DataFrame,
    *,
    label: str,
    required_columns: Iterable[str] | None = None,
    schema_version: int | str | None = None,
    column_dtypes: Mapping[str, str | Iterable[str]] | None = None,
    metadata: Mapping[str, str] | None = None,
) -> None:
    """Validate a loaded Parquet frame using the shared checked-read contract."""

    errors: list[str] = []
    required = tuple(required_columns or ())
    missing = [column for column in required if column not in frame.columns]
    if missing:
        errors.append(f"missing columns: {', '.join(missing)}")

    if schema_version is not None:
        actual_schema_versions = _schema_versions(frame, metadata=metadata)
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
        lambda temporary_path: _write_parquet_with_metadata(
            frame,
            temporary_path,
            index=index,
        ),
    )


def write_run_stamped_set(
    target_dir: Path,
    frames: Mapping[str, pd.DataFrame],
    specs: Mapping[str, tuple[str, str]],
    *,
    stamp: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Publish a SET of run-stamped artifacts all-or-nothing.

    ``specs`` maps each key to ``(run_stamped_prefix, latest_filename)``. Fails LOUD if
    ``frames`` keys != ``specs`` keys, so a build can never silently stop emitting an
    artifact (half-wired publish). Writes EVERY immutable run-stamped file first, then
    flips EVERY ``latest`` alias — the caller writes the published meta last, so a crash
    mid-publish leaves the previous meta (and the files it points to) intact. Returns
    ``({key: stamped_filename}, {key: latest_filename})`` for that meta.
    """

    missing = set(specs) - set(frames)
    extra = set(frames) - set(specs)
    if missing or extra:
        raise ValueError(
            f"artifact set requires exactly {sorted(specs)}; "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    stamped: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for key, (prefix, latest_name) in specs.items():
        stamped_name = f"{prefix}_{stamp}.parquet"
        write_parquet_atomic(frames[key], target_dir / stamped_name)
        stamped[key] = stamped_name
        aliases[key] = latest_name
    for key, (_prefix, latest_name) in specs.items():
        write_parquet_atomic(frames[key], target_dir / latest_name)
    return stamped, aliases


def write_parquet_into(frame: pd.DataFrame, path: Path, *, index: bool = False) -> None:
    """Write a Parquet file directly to ``path`` (no temp/replace).

    Use only when an outer transaction owns the atomic swap -- e.g. as the staging
    writer inside ``atomic_write_many`` -- so a group of files can be staged and
    swapped together. Prefer ``write_parquet_atomic`` for standalone writes.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_parquet_with_metadata(frame, path, index=index)


def _write_parquet_with_metadata(
    frame: pd.DataFrame,
    path: Path,
    *,
    index: bool,
) -> None:
    metadata = _golden_vector_metadata_from_attrs(frame)
    if not metadata:
        frame.to_parquet(path, index=index)
        return
    table = pa.Table.from_pandas(frame, preserve_index=index)
    existing = dict(table.schema.metadata or {})
    table = table.replace_schema_metadata({**existing, **metadata})
    pq.write_table(table, path)


def _golden_vector_metadata_from_attrs(frame: pd.DataFrame) -> dict[bytes, bytes]:
    metadata: dict[bytes, bytes] = {}
    for key in PARQUET_CONTEXT_METADATA_KEYS:
        value = frame.attrs.get(key)
        if _is_missing(value):
            continue
        metadata[f"{PARQUET_METADATA_PREFIX}{key}".encode("utf-8")] = str(value).encode(
            "utf-8"
        )
    return metadata


def parquet_context_metadata(path: Path) -> dict[str, str]:
    """Return Golden Vector Parquet context metadata."""

    try:
        raw_metadata = pq.read_metadata(path).metadata or {}
    except Exception:
        return {}
    parsed: dict[str, str] = {}
    prefix = PARQUET_METADATA_PREFIX.encode("utf-8")
    for raw_key, raw_value in raw_metadata.items():
        if not raw_key.startswith(prefix):
            continue
        key = raw_key.decode("utf-8")[len(PARQUET_METADATA_PREFIX):]
        parsed[key] = raw_value.decode("utf-8")
    return parsed


def _schema_versions(
    frame: pd.DataFrame,
    *,
    metadata: Mapping[str, str] | None = None,
) -> list[str]:
    if "schema_version" in frame.columns:
        values = [
            str(value)
            for value in frame["schema_version"].dropna().unique().tolist()
        ]
        if values:
            return sorted(values)
    if metadata:
        value = metadata.get("schema_version")
        if not _is_missing(value):
            return [str(value)]
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
