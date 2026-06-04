"""Persist Tool C outputs and provenance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_tool_c_sources
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import _latest_snapshot, _write_csv, _write_parquet


def persist_tool_c_outputs(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    tool_c_outputs: pd.DataFrame,
    source_paths: dict[str, Path] | None = None,
    publish_latest_aliases: bool = True,
) -> list[Path]:
    """Persist Tool C full/latest outputs and replay source snapshots."""

    latest_snapshot = _latest_snapshot(tool_c_outputs)
    written_paths = [
        _write_parquet(
            tool_c_outputs,
            paths.intermediate_tool_c_dir / f"tool_c_output_{run_context.run_id}.parquet",
        ),
        _write_parquet(
            tool_c_outputs,
            paths.output_tool_c_dir / f"tool_c_output_{run_context.run_id}.parquet",
        ),
        _write_csv(
            tool_c_outputs,
            paths.output_tool_c_dir / f"tool_c_output_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.output_tool_c_dir / f"tool_c_latest_{run_context.run_id}.parquet",
        ),
        _write_csv(
            latest_snapshot,
            paths.output_tool_c_dir / f"tool_c_latest_{run_context.run_id}.csv",
        ),
    ]
    if publish_latest_aliases:
        written_paths.extend(
            [
                _write_parquet(
                    latest_snapshot,
                    paths.latest_tool_c_snapshot_parquet_path,
                ),
                _write_csv(
                    latest_snapshot,
                    paths.latest_tool_c_snapshot_csv_path,
                ),
            ]
        )

    if source_paths:
        written_paths.extend(
            update_manifest_with_tool_c_sources(
                run_context.run_dir,
                source_paths=source_paths,
            )
        )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths
