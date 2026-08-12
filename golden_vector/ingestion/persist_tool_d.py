"""Persist Tool D outputs and provenance."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.replay_manifest import update_manifest_with_tool_d_sources
from golden_vector.app.run_context import RunContext
from golden_vector.common.files import atomic_write_many
from golden_vector.common.parquet import write_parquet_into
from golden_vector.contracts.tool_d import (
    TOOL_D_KEY_COLUMNS,
    TOOL_D_SCHEMA_VERSION,
    canonicalize_tool_d_tickers,
    validate_tool_d_output_frame,
)
from golden_vector.ingestion.persist import _latest_snapshot


def persist_tool_d_outputs(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    tool_d_outputs: pd.DataFrame,
    source_paths: dict[str, Path] | None = None,
    provenance_metadata: dict[str, object] | None = None,
    publish_latest_aliases: bool = True,
    publish_spot_latest_aliases: bool = False,
    expected_tickers: tuple[str, ...] | list[str],
) -> list[Path]:
    """Persist one complete Tool D generation as a rollback-safe group."""

    persisted_outputs = canonicalize_tool_d_tickers(tool_d_outputs)
    violations = validate_tool_d_output_frame(
        persisted_outputs,
        expected_tickers=expected_tickers,
        require_complete_sources=True,
        expected_source_run_id=run_context.run_id,
    )
    if violations:
        raise ValueError(
            "Tool D output does not satisfy schema v4: " + "; ".join(violations)
        )

    persisted_outputs.attrs["schema_version"] = TOOL_D_SCHEMA_VERSION
    persisted_outputs.attrs["source_run_id"] = run_context.run_id
    snapshot_ids = _unique_nonblank_values(
        persisted_outputs,
        "snapshot_refresh_run_id",
    )
    persisted_outputs.attrs["snapshot_refresh_run_id"] = snapshot_ids[0]
    latest_snapshot = _latest_snapshot(
        persisted_outputs,
        key_columns=TOOL_D_KEY_COLUMNS,
    )
    latest_snapshot.attrs.update(persisted_outputs.attrs)

    immutable_writes = [
        (
            paths.intermediate_tool_d_dir
            / f"tool_d_output_{run_context.run_id}.parquet",
            _parquet_writer(persisted_outputs),
        ),
        (
            paths.output_tool_d_dir / f"tool_d_output_{run_context.run_id}.parquet",
            _parquet_writer(persisted_outputs),
        ),
        (
            paths.output_tool_d_dir / f"tool_d_output_{run_context.run_id}.csv",
            _csv_writer(persisted_outputs),
        ),
        (
            paths.output_tool_d_dir / f"tool_d_latest_{run_context.run_id}.parquet",
            _parquet_writer(latest_snapshot),
        ),
        (
            paths.output_tool_d_dir / f"tool_d_latest_{run_context.run_id}.csv",
            _csv_writer(latest_snapshot),
        ),
    ]
    collisions = [path for path, _writer in immutable_writes if path.exists()]
    if collisions:
        raise FileExistsError(
            "refusing to overwrite immutable Tool D artifact(s): "
            + ", ".join(str(path) for path in collisions)
        )

    # Replay sources are run-local evidence rather than live aliases. Capture
    # them before the publish transaction so a provenance failure cannot advance
    # a convenience alias from a run that cannot be reproduced.
    replay_paths: list[Path] = []
    if source_paths:
        replay_paths = update_manifest_with_tool_d_sources(
            run_context.run_dir,
            source_paths=source_paths,
            metadata=provenance_metadata,
        )
        if len(replay_paths) != len(source_paths):
            raise RuntimeError(
                "Tool D replay-source capture failed; refusing to publish the generation"
            )

    writes = list(immutable_writes)
    if publish_latest_aliases:
        writes.extend(
            (
                (
                    paths.latest_tool_d_snapshot_csv_path,
                    _csv_writer(latest_snapshot),
                ),
                (
                    paths.latest_tool_d_snapshot_parquet_path,
                    _parquet_writer(latest_snapshot),
                ),
            )
        )
    if publish_spot_latest_aliases:
        # The in-refresh ticker-page stage consumes the spot Parquet alias, so
        # it is deliberately the final (most consequential) mutable swap.
        writes.extend(
            (
                (
                    paths.latest_tool_d_spot_snapshot_csv_path,
                    _csv_writer(latest_snapshot),
                ),
                (
                    paths.latest_tool_d_spot_snapshot_parquet_path,
                    _parquet_writer(latest_snapshot),
                ),
            )
        )

    written_paths = atomic_write_many(writes)
    written_paths.extend(replay_paths)

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def _parquet_writer(frame: pd.DataFrame):
    return lambda temporary_path: write_parquet_into(
        frame,
        temporary_path,
        index=False,
    )


def _csv_writer(frame: pd.DataFrame):
    return lambda temporary_path: frame.to_csv(temporary_path, index=False)


def _unique_nonblank_values(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame.columns:
        return []
    return sorted(
        {
            str(value).strip()
            for value in frame[column].dropna().tolist()
            if str(value).strip()
        }
    )
