"""Persist the four ticker-page artifacts (plan §5, §5.6).

Follows the Tool C persistence pattern: one immutable run-stamped file per
artifact, one run-stamped ``_latest`` file, and one mutable ``_latest`` alias,
each recorded on the run context. Provenance is stamped here (never guessed by
the builders) so every persisted row carries its generation identity.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.ticker_page import TICKER_PAGE_SCHEMA_VERSIONS

#: Artifact file prefixes, in publish order.
TICKER_PAGE_ARTIFACT_PREFIXES: tuple[str, ...] = (
    "gold_response",
    "percentiles",
    "performance",
    "research_series",
)

LINEARITY_DIAGNOSTICS_FILE_NAME = "ticker_page_linearity_diagnostics.parquet"


def stamp_ticker_page_provenance(
    frame: pd.DataFrame,
    *,
    artifact: str,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    parent_refresh_id: str,
    config_hash: str,
) -> pd.DataFrame:
    """Return ``frame`` with the five §5.6 provenance columns filled in."""

    if artifact not in TICKER_PAGE_SCHEMA_VERSIONS:
        raise ValueError(f"unknown ticker-page artifact: {artifact}")
    stamped = frame.copy()
    stamped["schema_version"] = int(TICKER_PAGE_SCHEMA_VERSIONS[artifact])
    stamped["source_run_id"] = str(source_run_id)
    stamped["snapshot_refresh_run_id"] = str(snapshot_refresh_run_id)
    stamped["parent_refresh_id"] = str(parent_refresh_id)
    stamped["config_hash"] = str(config_hash)
    return stamped


def persist_ticker_page_artifacts(
    paths: ProjectPaths,
    run_context: RunContext,
    *,
    gold_response: pd.DataFrame,
    percentiles: pd.DataFrame,
    performance: pd.DataFrame,
    research_series: pd.DataFrame,
    diagnostics: pd.DataFrame | None = None,
    source_run_id: str,
    snapshot_refresh_run_id: str,
    parent_refresh_id: str,
    config_hash: str,
) -> list[Path]:
    """Write the four artifacts (+ the run-directory linearity diagnostics)."""

    frames: dict[str, pd.DataFrame] = {
        "gold_response": gold_response,
        "percentiles": percentiles,
        "performance": performance,
        "research_series": research_series,
    }
    output_dir = paths.output_ticker_page_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    for prefix in TICKER_PAGE_ARTIFACT_PREFIXES:
        stamped = stamp_ticker_page_provenance(
            frames[prefix],
            artifact=prefix,
            source_run_id=source_run_id,
            snapshot_refresh_run_id=snapshot_refresh_run_id,
            parent_refresh_id=parent_refresh_id,
            config_hash=config_hash,
        )
        written_paths.extend(
            [
                write_parquet_atomic(
                    stamped,
                    output_dir / f"{prefix}_output_{run_context.run_id}.parquet",
                ),
                write_parquet_atomic(
                    stamped,
                    output_dir / f"{prefix}_latest_{run_context.run_id}.parquet",
                ),
                write_parquet_atomic(stamped, output_dir / f"{prefix}_latest.parquet"),
            ]
        )

    if diagnostics is not None:
        written_paths.append(
            write_parquet_atomic(
                diagnostics,
                run_context.run_dir / LINEARITY_DIAGNOSTICS_FILE_NAME,
            )
        )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths
