"""Persist Tool D outputs and provenance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_tool_d_sources
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.tool_d import (
    TOOL_D_KEY_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
    validate_tool_d_output_frame,
)
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
    expected_tickers: tuple[str, ...] | list[str] | None = None,
) -> list[Path]:
    """Persist Tool D full/latest outputs and replay source snapshots."""

    violations = validate_tool_d_output_frame(
        tool_d_outputs,
        expected_tickers=expected_tickers,
        require_complete_sources=True,
    )
    if violations:
        raise ValueError(
            "Tool D output does not satisfy schema v4: " + "; ".join(violations)
        )

    persisted_outputs = tool_d_outputs.copy()
    persisted_outputs.attrs.update(tool_d_outputs.attrs)
    persisted_outputs.attrs["schema_version"] = TOOL_D_SCHEMA_VERSION
    latest_snapshot = _latest_snapshot(
        persisted_outputs,
        key_columns=TOOL_D_KEY_COLUMNS,
    )
    latest_snapshot.attrs["schema_version"] = TOOL_D_SCHEMA_VERSION
    written_paths = [
        _write_parquet(
            persisted_outputs,
            paths.intermediate_tool_d_dir / f"tool_d_output_{run_context.run_id}.parquet",
        ),
        _write_parquet(
            persisted_outputs,
            paths.output_tool_d_dir / f"tool_d_output_{run_context.run_id}.parquet",
        ),
        _write_csv(
            persisted_outputs,
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
