"""Persist refresh-time option analytics artifacts."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.common.files import atomic_write_many
from golden_vector.common.parquet import write_parquet_into
from golden_vector.contracts.option_artifacts import (
    OPTION_ARTIFACT_NAMES,
    OPTION_ARTIFACT_PREFIXES,
    option_artifact_latest_path,
    option_artifact_run_stamped_path,
)
from golden_vector.hedge.option_signals import prepare_option_signal_history
from golden_vector.ingestion.persist import _write_parquet


def persist_option_artifact_frames(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    frames: dict[str, pd.DataFrame],
    publish_latest_aliases: bool = True,
) -> list[Path]:
    """Persist all option artifact frames under the current artifact run id."""

    missing = [name for name in OPTION_ARTIFACT_NAMES if name not in frames]
    if missing:
        raise ValueError(f"Missing option artifact frame(s): {', '.join(missing)}")

    written_paths: list[Path] = []
    for artifact_name in OPTION_ARTIFACT_NAMES:
        frame = frames[artifact_name]
        if "source_run_id" not in frame.columns:
            raise ValueError(f"Option artifact {artifact_name} is missing source_run_id.")
        prefix = OPTION_ARTIFACT_PREFIXES[artifact_name]
        written_paths.extend(
            [
                _write_parquet(
                    frame,
                    paths.output_options_dir / f"{prefix}_output_{run_context.run_id}.parquet",
                ),
                _write_parquet(
                    frame,
                    option_artifact_run_stamped_path(
                        paths,
                        artifact_name,
                        run_context.run_id,
                    ),
                ),
            ]
        )
        if publish_latest_aliases:
            written_paths.append(
                _write_parquet(
                    frame,
                    option_artifact_latest_path(paths, artifact_name),
                )
            )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def publish_option_artifact_latest_aliases(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    frames: dict[str, pd.DataFrame],
) -> list[Path]:
    """Flip the ``*_latest`` aliases for already-staged option artifact frames.

    Call this ONLY after every run-stamped artifact AND the signal history have been
    written successfully, so a mid-run failure (e.g. the signal-history shrink guard)
    can never leave latest aliases ahead of a failed option build. This keeps the
    option publish all-or-nothing: a failed run leaves the last good aliases intact.
    """

    missing = [name for name in OPTION_ARTIFACT_NAMES if name not in frames]
    if missing:
        raise ValueError(f"Missing option artifact frame(s): {', '.join(missing)}")

    written_paths: list[Path] = []
    for artifact_name in OPTION_ARTIFACT_NAMES:
        frame = frames[artifact_name]
        written_paths.append(
            _write_parquet(frame, option_artifact_latest_path(paths, artifact_name))
        )
    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def publish_option_artifacts_and_history_atomically(
    *,
    paths: ProjectPaths,
    run_context: RunContext,
    frames: dict[str, pd.DataFrame],
    history: pd.DataFrame,
) -> list[Path]:
    """Advance the option signal history AND flip the ``*_latest`` aliases as ONE
    all-or-nothing group.

    Run-stamped artifacts must already be persisted (``publish_latest_aliases=False``).
    The history shrink guard runs while STAGING, before any live file is touched;
    the history write plus every alias write are then staged and swapped together
    with rollback. So a mid-publish failure leaves the previous history AND the
    previous aliases fully intact -- no half-flipped alias set, and the accumulated
    IV-rank history is never advanced ahead of a failed alias flip. This closes the
    file-by-file / history-then-aliases tear the earlier H2 ordering still allowed
    (Codex options-UI review HIGH).
    """

    missing = [name for name in OPTION_ARTIFACT_NAMES if name not in frames]
    if missing:
        raise ValueError(f"Missing option artifact frame(s): {', '.join(missing)}")

    # Stage-time validation: run the shrink guard now (it reads the live history but
    # writes nothing), so a shrinking history aborts before any swap.
    history_path, normalized_history = prepare_option_signal_history(
        paths=paths, history=history
    )

    writes: list[tuple[Path, Callable[[Path], None]]] = []
    for artifact_name in OPTION_ARTIFACT_NAMES:
        frame = frames[artifact_name]
        latest_path = option_artifact_latest_path(paths, artifact_name)
        writes.append(
            (latest_path, lambda tmp, f=frame: write_parquet_into(f, tmp, index=False))
        )
    writes.append(
        (
            history_path,
            lambda tmp: write_parquet_into(normalized_history, tmp, index=False),
        )
    )

    written_paths = atomic_write_many(writes)
    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths
