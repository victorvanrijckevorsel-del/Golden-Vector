"""Shared contracts for persisted option analytics artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from golden_vector.common.files import safe_file_fragment

# v3 (Milestone C2): signal-horizon fields replace *_60d names
# (iv_skew_signal, pnl_*_at_context, signal_horizon_days), candidate_finder
# inputs gain benchmark-relative skew_residual_signal, and signal history
# moved to long form. Pre-v3 artifacts fail loud / refuse carry-forward.
OPTION_ARTIFACT_SCHEMA_VERSION = 3

# Versioned artifact-name sets (plan §6.4). A single global name set cannot
# express "v3 still valid while v4 adds artifacts", so validation resolves the
# name set by a generation's OWN stamped schema_version. ACTIVE_OPTION_SCHEMA_VERSION
# is the version the publisher writes today; flipping it to 4 is a LATER lane's
# job (together with per-generation validation in app/model_state.py). Until then
# every v4 entry below is dormant: nothing resolves it at runtime.
ACTIVE_OPTION_SCHEMA_VERSION = OPTION_ARTIFACT_SCHEMA_VERSION

_V3_OPTION_ARTIFACT_NAMES: tuple[str, ...] = (
    "option_contract_metrics",
    "option_liquidity_measurements",
    "option_candidate_slots",
    "option_selected_candidates",
    "option_trading_overview",
    "candidate_finder_inputs",
    "option_signal_summary",
    "option_skew_curve_points",
    "option_oi_strike_points",
    "option_signal_history_points",
)

_V4_OPTION_ARTIFACT_NAMES: tuple[str, ...] = (
    *_V3_OPTION_ARTIFACT_NAMES,
    "option_chain_history_daily",
    "option_availability",
)

OPTION_ARTIFACT_SETS: dict[int, tuple[str, ...]] = {
    3: _V3_OPTION_ARTIFACT_NAMES,
    4: _V4_OPTION_ARTIFACT_NAMES,
}

# The Option Trading overview loader's reads. The two v4 additions are page-side
# only (dedicated readers), so they are deliberately EXCLUDED — closing the
# loader-inventory gap in plan §6.4/P11.
OPTION_TRADING_READ_SET: tuple[str, ...] = _V3_OPTION_ARTIFACT_NAMES


def option_artifact_names_for_version(schema_version: int) -> tuple[str, ...]:
    """Return the artifact-name set a generation of ``schema_version`` must hold."""

    try:
        return OPTION_ARTIFACT_SETS[int(schema_version)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported option schema version: {schema_version!r}") from exc


# Bound to the ACTIVE version: at runtime this is exactly the v3 ten-name tuple
# it has always been.
OPTION_ARTIFACT_NAMES: tuple[str, ...] = option_artifact_names_for_version(
    ACTIVE_OPTION_SCHEMA_VERSION
)

REQUIRED_OPTION_ARTIFACT_NAMES: tuple[str, ...] = (
    "option_candidate_slots",
    "option_trading_overview",
    "candidate_finder_inputs",
    "option_signal_summary",
)

OPTION_ARTIFACT_PREFIXES: dict[str, str] = {
    name: name for name in OPTION_ARTIFACT_NAMES
}

# --- v4 (dormant) artifact schemas -----------------------------------------
# Own version column for the chain-history artifact, independent of the option
# artifact-set version above (plan §6.1/§6.2).
CHAIN_HISTORY_SCHEMA_VERSION = 1

CHAIN_HISTORY_COLUMNS: tuple[str, ...] = (
    "ticker",
    "as_of_date",
    # chain-level daily quantities (plan §6.1)
    "total_open_interest",
    "put_oi_total",
    "call_oi_total",
    "put_oi_otm",
    "call_oi_otm",
    "put_call_oi_ratio_total",
    "put_call_oi_ratio_otm",
    "total_volume",
    "put_volume",
    "call_volume",
    # capture diagnostics
    "n_contracts",
    "n_expirations",
    "capture_quality",
    "row_status",
    # provenance (plan §6.2)
    "oi_split_backfilled",
    "capture_run_id",
    "published_run_id",
    "schema_version",
)

OPTION_AVAILABILITY_SCHEMA_VERSION = 1

OPTION_AVAILABILITY_COLUMNS: tuple[str, ...] = (
    "ticker",
    "availability_status",
    "expirations_enumerated",
    "fetch_status",
    "fetch_message",
    "provider",
    "capture_date",
    "schema_version",
)


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
