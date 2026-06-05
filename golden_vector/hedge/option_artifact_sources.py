"""Load source inputs for option artifact building without importing serve code."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.app.model_state import (
    read_current_model_json,
    read_current_model_parquet,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import sha256_file
from golden_vector.common.parquet import read_optional_parquet, read_required_parquet
from golden_vector.common.strings import normalize_ticker
from golden_vector.hedge._helpers import as_float
from golden_vector.ingestion.persist_options import safe_options_file_name


@dataclass(frozen=True)
class OptionArtifactSourceInputs:
    manifest: dict[str, Any]
    features: pd.DataFrame
    chains: dict[str, pd.DataFrame]
    tool_a: pd.DataFrame
    tool_b: pd.DataFrame
    risk_free_rate: float
    risk_free_rate_is_fallback: bool


def load_option_artifact_source_inputs(
    paths: ProjectPaths,
    *,
    use_model_state: bool,
) -> OptionArtifactSourceInputs | None:
    """Load all inputs needed by the shared option artifact builder."""

    manifest = _read_options_manifest(paths, use_model_state=use_model_state)
    if manifest is None:
        return None
    tool_a = _read_tool_frame(
        paths,
        artifact_name="tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
        use_model_state=use_model_state,
    )
    tool_b = _read_tool_frame(
        paths,
        artifact_name="tool_b",
        fallback_path=paths.latest_tool_b_snapshot_parquet_path,
        use_model_state=use_model_state,
    )
    risk_free_rate = as_float(manifest.get("risk_free_rate"))
    return OptionArtifactSourceInputs(
        manifest=manifest,
        features=load_options_features(paths=paths, manifest=manifest),
        chains=load_options_chains(paths=paths, manifest=manifest),
        tool_a=tool_a,
        tool_b=tool_b,
        risk_free_rate=risk_free_rate if risk_free_rate is not None else 0.0,
        risk_free_rate_is_fallback=risk_free_rate is None,
    )


def load_options_chains(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> dict[str, pd.DataFrame]:
    chains: dict[str, pd.DataFrame] = {}
    for item in manifest.get("snapshots", []):
        ticker = normalize_ticker(item.get("ticker"))
        if not ticker:
            continue
        snapshot_path = paths.resolve_repo_relative(str(item.get("snapshot_path", "")))
        expected_sha256 = str(item.get("sha256") or "").strip()
        if expected_sha256:
            actual_sha256 = sha256_file(snapshot_path)
            if actual_sha256 != expected_sha256:
                raise ValueError(
                    f"Options chain snapshot for {ticker} has sha256 {actual_sha256}; "
                    f"expected {expected_sha256}."
                )
        chains[ticker] = read_required_parquet(
            snapshot_path,
            label=f"Options chain snapshot for {ticker}",
        )
    return chains


def load_options_features(
    *,
    paths: ProjectPaths,
    manifest: dict[str, Any],
) -> pd.DataFrame:
    rows: list[pd.Series] = []
    refresh_run_id = str(manifest.get("refresh_run_id") or "")
    for item in manifest.get("snapshots", []):
        ticker = normalize_ticker(item.get("ticker"))
        if not ticker:
            continue
        feature_path = paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet"
        frame = read_required_parquet(
            feature_path,
            label=f"Options feature snapshot for {ticker}",
        )
        if "run_id" in frame.columns and refresh_run_id:
            matching = frame[frame["run_id"].astype(str) == refresh_run_id]
            if not matching.empty:
                rows.append(matching.iloc[-1])
            continue
        rows.append(frame.iloc[-1])
    if not rows:
        return pd.DataFrame()
    result = pd.DataFrame(rows).reset_index(drop=True)
    if "ticker" in result.columns:
        result["ticker"] = result["ticker"].map(normalize_ticker)
    return result


def _read_options_manifest(
    paths: ProjectPaths,
    *,
    use_model_state: bool,
) -> dict[str, Any] | None:
    if use_model_state:
        return read_current_model_json(
            paths,
            "options",
            fallback_path=paths.latest_options_manifest_path,
        )
    try:
        payload = json.loads(paths.latest_options_manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _read_tool_frame(
    paths: ProjectPaths,
    *,
    artifact_name: str,
    fallback_path: Path,
    use_model_state: bool,
) -> pd.DataFrame:
    if use_model_state:
        return read_current_model_parquet(
            paths,
            artifact_name,
            fallback_path=fallback_path,
        )
    return read_optional_parquet(fallback_path)
