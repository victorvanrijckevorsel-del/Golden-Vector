"""Shared portfolio artifact writing helpers."""

from __future__ import annotations

import pandas as pd

from golden_vector.common.files import atomic_write_file
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.parquet import write_parquet_atomic


def write_portfolio_artifact_pair(
    *,
    paths: ProjectPaths,
    frame: pd.DataFrame,
    prefix: str,
    source_run_id: str,
) -> None:
    output_dir = paths.output_portfolio_dir
    run_path = output_dir / f"{prefix}_latest_{source_run_id}.parquet"
    latest_path = output_dir / f"{prefix}_latest.parquet"
    write_parquet_atomic(frame, run_path, index=False)
    write_parquet_atomic(frame, latest_path, index=False)


def write_portfolio_csv_pair(
    *,
    paths: ProjectPaths,
    frame: pd.DataFrame,
    prefix: str,
    source_run_id: str,
) -> None:
    output_dir = paths.output_portfolio_dir
    run_path = output_dir / f"{prefix}_latest_{source_run_id}.csv"
    latest_path = output_dir / f"{prefix}_latest.csv"
    atomic_write_file(run_path, lambda temporary_path: frame.to_csv(temporary_path, index=False))
    atomic_write_file(latest_path, lambda temporary_path: frame.to_csv(temporary_path, index=False))
