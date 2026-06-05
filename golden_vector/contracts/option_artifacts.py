"""Shared contracts for persisted option analytics artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from golden_vector.common.files import safe_file_fragment

OPTION_ARTIFACT_SCHEMA_VERSION = 1

OPTION_ARTIFACT_NAMES: tuple[str, ...] = (
    "option_contract_metrics",
    "option_liquidity_measurements",
    "option_candidate_slots",
    "option_selected_candidates",
    "option_trading_overview",
    "candidate_finder_inputs",
)

REQUIRED_OPTION_ARTIFACT_NAMES: tuple[str, ...] = (
    "option_candidate_slots",
    "option_trading_overview",
    "candidate_finder_inputs",
)

OPTION_ARTIFACT_PREFIXES: dict[str, str] = {
    name: name for name in OPTION_ARTIFACT_NAMES
}


class _OptionArtifactPaths(Protocol):
    output_options_dir: Path


def option_artifact_latest_path(paths: _OptionArtifactPaths, artifact_name: str) -> Path:
    """Return the convenience latest alias path for an option artifact."""

    return paths.output_options_dir / f"{_prefix(artifact_name)}_latest.parquet"


def option_artifact_run_stamped_path(
    paths: _OptionArtifactPaths,
    artifact_name: str,
    source_run_id: str,
) -> Path:
    """Return the immutable run-stamped latest path for an option artifact."""

    return (
        paths.output_options_dir
        / f"{_prefix(artifact_name)}_latest_{safe_file_fragment(source_run_id)}.parquet"
    )


def _prefix(artifact_name: str) -> str:
    try:
        return OPTION_ARTIFACT_PREFIXES[artifact_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported option artifact: {artifact_name}") from exc
