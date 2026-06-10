"""Contracts for official fundamental data artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from golden_vector.common.files import safe_file_fragment

FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME = "fundamentals_official"
FETCHED_FUNDAMENTALS_PREFIX = "fetched_fundamentals"
FETCHED_FUNDAMENTALS_SCHEMA_VERSION = 1

FundamentalValueStatus = Literal[
    "OK",
    "MISSING",
    "STALE",
    "CONTAMINATED",
    "CURRENCY_UNCONVERTIBLE",
    "CURRENCY_BASIS_MISMATCH",
]

FUNDAMENTAL_VALUE_STATUSES: tuple[FundamentalValueStatus, ...] = (
    "OK",
    "MISSING",
    "STALE",
    "CONTAMINATED",
    "CURRENCY_UNCONVERTIBLE",
    "CURRENCY_BASIS_MISMATCH",
)

FETCHED_FUNDAMENTALS_COLUMNS: tuple[str, ...] = (
    "schema_version",
    "ticker",
    "field_name",
    "value",
    "source",
    "source_run_id",
    "fetched_at_utc",
    "statement_period",
    "period_end",
    "period_type",
    "statement_currency",
    "statement_scale",
    "value_status",
)


class _FundamentalsArtifactPaths(Protocol):
    output_fundamentals_dir: Path


def fetched_fundamentals_latest_path(paths: _FundamentalsArtifactPaths) -> Path:
    """Return the convenience latest alias path for official fundamentals."""

    return paths.output_fundamentals_dir / f"{FETCHED_FUNDAMENTALS_PREFIX}_latest.parquet"


def fetched_fundamentals_run_stamped_path(
    paths: _FundamentalsArtifactPaths,
    source_run_id: str,
) -> Path:
    """Return the immutable run-stamped path for official fundamentals."""

    return (
        paths.output_fundamentals_dir
        / f"{FETCHED_FUNDAMENTALS_PREFIX}_latest_{safe_file_fragment(source_run_id)}.parquet"
    )
