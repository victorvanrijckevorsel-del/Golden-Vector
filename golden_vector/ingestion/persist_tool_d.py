"""Persist Tool D outputs and provenance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_tool_d_sources
from golden_vector.app.run_context import RunContext
from golden_vector.ingestion.persist import _latest_snapshot, _write_csv, _write_parquet


def persist_tool_d_outputs(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    tool_d_outputs: pd.DataFrame,
    source_paths: dict[str, Path] | None = None,
    provenance_metadata: dict[str, object] | None = None,
    publish_latest_aliases: bool = True,
    publish_spot_latest_aliases: bool = False,
) -> list[Path]:
    """Persist Tool D full/latest outputs and replay source snapshots."""

    latest_snapshot = _latest_snapshot(tool_d_outputs)
    written_paths = [
        _write_parquet(
            tool_d_outputs,
            paths.intermediate_tool_d_dir / f"tool_d_output_{run_context.run_id}.parquet",
        ),
        _write_parquet(
            tool_d_outputs,
            paths.output_tool_d_dir / f"tool_d_output_{run_context.run_id}.parquet",
        ),
        _write_csv(
            tool_d_outputs,
            paths.output_tool_d_dir / f"tool_d_output_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.output_tool_d_dir / f"tool_d_latest_{run_context.run_id}.parquet",
        ),
        _write_csv(
            latest_snapshot,
            paths.output_tool_d_dir / f"tool_d_latest_{run_context.run_id}.csv",
        ),
    ]
    if publish_latest_aliases:
        written_paths.extend(
            [
                _write_parquet(
                    latest_snapshot,
                    paths.latest_tool_d_snapshot_parquet_path,
                ),
                _write_csv(
                    latest_snapshot,
                    paths.latest_tool_d_snapshot_csv_path,
                ),
            ]
        )
    if publish_spot_latest_aliases:
        written_paths.extend(
            [
                _write_parquet(
                    latest_snapshot,
                    paths.latest_tool_d_spot_snapshot_parquet_path,
                ),
                _write_csv(
                    latest_snapshot,
                    paths.latest_tool_d_spot_snapshot_csv_path,
                ),
            ]
        )

    if source_paths:
        written_paths.extend(
            update_manifest_with_tool_d_sources(
                run_context.run_dir,
                source_paths=source_paths,
                metadata=provenance_metadata,
            )
        )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths
