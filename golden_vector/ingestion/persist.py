"""Persist pipeline outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.data_models import FetchStatusRecord, QaCheckResult


def persist_foundation_outputs(
    paths: ProjectPaths,
    run_context: RunContext,
    equity_histories: dict[str, pd.DataFrame],
    fx_histories: dict[str, pd.DataFrame],
    gold_history: pd.DataFrame,
    market_snapshots: pd.DataFrame,
    fetch_statuses: list[FetchStatusRecord],
    qa_results: list[QaCheckResult],
) -> list[Path]:
    written_paths: list[Path] = []

    for ticker, frame in equity_histories.items():
        written_paths.append(_write_parquet(frame, paths.raw_equities_dir / f"{_safe_name(ticker)}.parquet"))
    written_paths.append(
        _write_parquet(
            _concat_frames(equity_histories),
            run_context.run_dir / "snapshots" / "raw_equities.parquet",
        )
    )

    for currency, frame in fx_histories.items():
        written_paths.append(_write_parquet(frame, paths.raw_fx_dir / f"{_safe_name(currency)}USD.parquet"))
    written_paths.append(
        _write_parquet(
            _concat_frames(fx_histories),
            run_context.run_dir / "snapshots" / "raw_fx.parquet",
        )
    )

    if not gold_history.empty:
        gold_symbol = str(gold_history["gold_symbol"].iloc[0])
    else:
        gold_symbol = "gold"
    written_paths.append(_write_parquet(gold_history, paths.raw_gold_dir / f"{_safe_name(gold_symbol)}.parquet"))
    written_paths.append(
        _write_parquet(
            gold_history,
            run_context.run_dir / "snapshots" / "raw_gold.parquet",
        )
    )

    written_paths.append(
        _write_parquet(
            market_snapshots,
            paths.raw_market_snapshots_dir / f"market_snapshot_{run_context.run_id}.parquet",
        )
    )
    written_paths.append(
        _write_parquet(
            market_snapshots,
            paths.latest_raw_market_snapshots_path,
        )
    )

    fetch_status_frame = pd.DataFrame([record.model_dump() for record in fetch_statuses])
    written_paths.append(
        _write_parquet(
            fetch_status_frame,
            paths.raw_status_dir / f"fetch_status_{run_context.run_id}.parquet",
        )
    )
    written_paths.append(
        _write_parquet(
            fetch_status_frame,
            paths.latest_fetch_status_path,
        )
    )

    qa_results_frame = pd.DataFrame([result.model_dump() for result in qa_results])
    written_paths.append(
        _write_parquet(
            qa_results_frame,
            paths.raw_status_dir / f"qa_results_{run_context.run_id}.parquet",
        )
    )
    written_paths.append(
        _write_parquet(
            qa_results_frame,
            paths.latest_raw_qa_results_path,
        )
    )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def persist_normalization_outputs(
    paths: ProjectPaths,
    run_context: RunContext,
    usd_equity_histories: dict[str, pd.DataFrame],
    normalized_market_snapshots: pd.DataFrame,
    qa_results: list[QaCheckResult],
) -> list[Path]:
    written_paths: list[Path] = []

    for ticker, frame in usd_equity_histories.items():
        written_paths.append(
            _write_parquet(
                frame,
                paths.intermediate_usd_equities_dir / f"{_safe_name(ticker)}.parquet",
            )
        )
    written_paths.append(
        _write_parquet(
            _concat_frames(usd_equity_histories),
            run_context.run_dir / "snapshots" / "usd_equities.parquet",
        )
    )

    written_paths.append(
        _write_parquet(
            normalized_market_snapshots,
            paths.intermediate_market_snapshots_dir
            / f"market_snapshot_{run_context.run_id}.parquet",
        )
    )
    written_paths.append(
        _write_parquet(
            normalized_market_snapshots,
            run_context.run_dir / "snapshots" / "market_snapshots_usd.parquet",
        )
    )
    written_paths.append(
        _write_parquet(
            normalized_market_snapshots,
            paths.latest_normalized_market_snapshots_path,
        )
    )

    qa_results_frame = pd.DataFrame([result.model_dump() for result in qa_results])
    written_paths.append(
        _write_parquet(
            qa_results_frame,
            paths.intermediate_status_dir
            / f"normalization_qa_results_{run_context.run_id}.parquet",
        )
    )
    written_paths.append(
        _write_parquet(
            qa_results_frame,
            paths.latest_normalization_qa_results_path,
        )
    )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def persist_horizon_outputs(
    paths: ProjectPaths,
    run_context: RunContext,
    horizon_metrics: pd.DataFrame,
    qa_results: list[QaCheckResult],
) -> list[Path]:
    written_paths: list[Path] = []

    written_paths.append(
        _write_parquet(
            horizon_metrics,
            paths.intermediate_horizon_metrics_dir
            / f"horizon_metrics_{run_context.run_id}.parquet",
        )
    )

    qa_results_frame = pd.DataFrame([result.model_dump() for result in qa_results])
    written_paths.append(
        _write_parquet(
            qa_results_frame,
            paths.intermediate_status_dir / f"horizon_qa_results_{run_context.run_id}.parquet",
        )
    )

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def persist_tool_a_outputs(
    paths: ProjectPaths,
    run_context: RunContext,
    tool_a_outputs: pd.DataFrame,
) -> list[Path]:
    latest_snapshot = _latest_snapshot(tool_a_outputs)
    written_paths = [
        _write_parquet(
            tool_a_outputs,
            paths.intermediate_tool_a_profiles_dir / f"tool_a_profiles_{run_context.run_id}.parquet",
        ),
        _write_parquet(
            tool_a_outputs,
            paths.output_tool_a_dir / f"tool_a_output_{run_context.run_id}.parquet",
        ),
        _write_csv(
            tool_a_outputs,
            paths.output_tool_a_dir / f"tool_a_output_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.output_tool_a_dir / f"tool_a_latest_{run_context.run_id}.parquet",
        ),
        _write_csv(
            latest_snapshot,
            paths.output_tool_a_dir / f"tool_a_latest_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.latest_tool_a_snapshot_parquet_path,
        ),
        _write_csv(
            latest_snapshot,
            paths.latest_tool_a_snapshot_csv_path,
        ),
    ]

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def persist_tool_b_outputs(
    paths: ProjectPaths,
    run_context: RunContext,
    tool_b_outputs: pd.DataFrame,
) -> list[Path]:
    latest_snapshot = _latest_snapshot(tool_b_outputs)
    written_paths = [
        _write_parquet(
            tool_b_outputs,
            paths.intermediate_tool_b_dir / f"tool_b_output_{run_context.run_id}.parquet",
        ),
        _write_parquet(
            tool_b_outputs,
            paths.output_tool_b_dir / f"tool_b_output_{run_context.run_id}.parquet",
        ),
        _write_csv(
            tool_b_outputs,
            paths.output_tool_b_dir / f"tool_b_output_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.output_tool_b_dir / f"tool_b_latest_{run_context.run_id}.parquet",
        ),
        _write_csv(
            latest_snapshot,
            paths.output_tool_b_dir / f"tool_b_latest_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.latest_tool_b_snapshot_parquet_path,
        ),
        _write_csv(
            latest_snapshot,
            paths.latest_tool_b_snapshot_csv_path,
        ),
    ]

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def persist_combined_outputs(
    paths: ProjectPaths,
    run_context: RunContext,
    combined_outputs: pd.DataFrame,
) -> list[Path]:
    latest_snapshot = _latest_snapshot(combined_outputs)
    written_paths = [
        _write_parquet(
            combined_outputs,
            paths.output_combined_dir / f"combined_output_{run_context.run_id}.parquet",
        ),
        _write_csv(
            combined_outputs,
            paths.output_combined_dir / f"combined_output_{run_context.run_id}.csv",
        ),
        _write_parquet(
            latest_snapshot,
            paths.output_combined_dir / f"combined_latest_{run_context.run_id}.parquet",
        ),
        _write_csv(
            latest_snapshot,
            paths.output_combined_dir / f"combined_latest_{run_context.run_id}.csv",
        ),
    ]

    for path in written_paths:
        run_context.record_artifact(path)
    return written_paths


def _write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def _concat_frames(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    materialized = [frame for frame in frames.values() if not frame.empty]
    if not materialized:
        return pd.DataFrame()
    return pd.concat(materialized, ignore_index=True)


def _latest_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "as_of_date" not in frame.columns:
        return frame.copy()
    latest_as_of_date = frame["as_of_date"].max()
    latest = frame[frame["as_of_date"] == latest_as_of_date].copy()
    sort_columns = [
        column
        for column in ("combined_rank", "tool_a_rank", "tool_b_rank", "ticker")
        if column in latest.columns
    ]
    if sort_columns:
        latest = latest.sort_values(sort_columns, na_position="last")
    return latest.reset_index(drop=True)


def _safe_name(value: str) -> str:
    sanitized = value
    for old, new in (
        ("\\", "_"),
        ("/", "_"),
        (":", "_"),
        ("*", "_"),
        ("?", "_"),
        ('"', "_"),
        ("<", "_"),
        (">", "_"),
        ("|", "_"),
        ("=", "-"),
    ):
        sanitized = sanitized.replace(old, new)
    return sanitized
