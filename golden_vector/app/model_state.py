"""Current model-state manifest helpers.

The model-state manifest is intentionally shaped as the future single atomic
pointer for a coherent Golden Vector build. I1 still lets existing readers use
their legacy latest aliases, but this contract is the path readers will resolve
through in I2/I3.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from golden_vector.common.files import atomic_write_bytes as _atomic_write_bytes
from golden_vector.common.files import atomic_write_text as _atomic_write_text
from golden_vector.common.files import repo_relative as _repo_relative
from golden_vector.common.files import safe_file_fragment as _safe_file_fragment
from golden_vector.common.files import sha256_file as _sha256_file
from golden_vector.common.parquet import parquet_context_metadata
from golden_vector.common.strings import clean_string as _common_clean_string
from golden_vector.common.strings import unique_strings as _common_unique_strings
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import to_jsonable
from golden_vector.contracts.fundamentals import (
    FETCHED_FUNDAMENTALS_PREFIX,
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
    fetched_fundamentals_latest_path,
)
from golden_vector.contracts.ticker_page import (
    TICKER_PAGE_SCHEMA_VERSIONS as _TICKER_PAGE_SCHEMA_VERSIONS,
)
from golden_vector.contracts.option_artifacts import (
    ACTIVE_OPTION_SCHEMA_VERSION,
    OPTION_ARTIFACT_NAMES,
    OPTION_ARTIFACT_PREFIXES,
    OPTION_TRADING_READ_SET,
    REQUIRED_OPTION_ARTIFACT_NAMES,
    SUPPORTED_OPTION_SCHEMA_VERSIONS,
    normalized_option_schema_version,
    option_artifact_latest_path,
    option_artifact_names_for_version,
)

MODEL_STATE_MANIFEST_VERSION = 1
CURRENT_FOUNDATION_UNAVAILABLE_MESSAGE = (
    "Current model-state manifest does not expose a usable immutable foundation artifact."
)

# The ticker-page artifacts, keyed by manifest name -> file prefix in
# ``paths.output_ticker_page_dir`` (plan §5.4). Names carry the ``ticker_page_``
# prefix so the manifest namespace stays unambiguous; the on-disk prefix stays
# the short one the producer writes.
TICKER_PAGE_ARTIFACT_PREFIXES: dict[str, str] = {
    f"ticker_page_{name}": name for name in sorted(_TICKER_PAGE_SCHEMA_VERSIONS)
}
TICKER_PAGE_ARTIFACT_NAMES: tuple[str, ...] = tuple(TICKER_PAGE_ARTIFACT_PREFIXES)

REQUIRED_ARTIFACTS: tuple[str, ...] = (
    "foundation",
    "options",
    "tool_a",
    "tool_b",
    "tool_c",
    "tool_d",
    *REQUIRED_OPTION_ARTIFACT_NAMES,
    # Required from the same commit that ships the refresh stage, so the next
    # refresh produces them and a missing set is loudly incomplete (plan §5.4).
    *TICKER_PAGE_ARTIFACT_NAMES,
)

PLANNED_I3_ARTIFACTS: tuple[str, ...] = OPTION_ARTIFACT_NAMES
PORTFOLIO_ARTIFACTS: tuple[str, ...] = (
    "portfolio_lines",
    "portfolio_positions",
    "portfolio_summary",
    "benchmark_betas",
    "portfolio_reconciliation",
    "portfolio_hedge_sizing",
    "portfolio_correlations",
    "portfolio_value_history",
    "portfolio_reconciliation_export",
)
# Every artifact load_portfolio_data() requires must be alignment-checked, or the
# status banner can read OK while the page reads a stale M4/export artifact from a
# different foundation run. _refresh_alignment skips not-yet-present artifacts, so
# covering the full required set never produces a false warning before first build.
PORTFOLIO_ALIGNMENT_ARTIFACTS: tuple[str, ...] = PORTFOLIO_ARTIFACTS

OPTION_FRESHNESS_OK = "OK"
OPTION_FRESHNESS_CARRIED_FORWARD = "CARRIED_FORWARD"
OPTION_FRESHNESS_UNAVAILABLE = "UNAVAILABLE"
# Usable + current-schema option artifacts that the alignment layer flags as
# referencing a different refresh than the current foundation/options run. Not a
# blocker (data is usable) but not "OK" either -- surfaces the split-brain (audit M4).
OPTION_FRESHNESS_MISALIGNED = "MISALIGNED"
OPTION_FRESHNESS_STATUSES = (
    OPTION_FRESHNESS_OK,
    OPTION_FRESHNESS_CARRIED_FORWARD,
    OPTION_FRESHNESS_UNAVAILABLE,
    OPTION_FRESHNESS_MISALIGNED,
)


@dataclass(frozen=True)
class OptionPublishBlock:
    """Refresh-time signal that fresh option artifacts were not publishable.

    Built by the refresh orchestrator when the option-artifact step finished
    but its publish gates blocked (data-quality verdicts such as SPARSE or
    LOW_LIQUIDITY). Hard build failures never produce this object — they keep
    aborting the publish entirely.
    """

    blockers: tuple[str, ...] = ()
    market_session: str = "UNKNOWN"  # OPEN | CLOSED | UNKNOWN
    # Set by inheritance from a previous UNAVAILABLE domain so rebound
    # publishes keep the original informative reason instead of re-deriving
    # a generic one from stub entries (audit N3).
    inherited_reason: str | None = None


@dataclass(frozen=True)
class _OptionCarryForward:
    entries: dict[str, dict[str, Any]]
    source_run_id: str
    snapshot_refresh_run_id: str
    as_of_date: str | None
    carried_from_parent_refresh_id: str | None = None


def write_current_model_state_manifest(
    *,
    paths: ProjectPaths,
    config_hash: str | None,
    parent_refresh_id: str | None = None,
    full_refresh_completed_at_utc: str | None = None,
    stage_timings: dict[str, Any] | None = None,
    option_publish_block: OptionPublishBlock | None = None,
) -> dict[str, Any]:
    """Build and atomically publish the current model-state manifest.

    Only the refresh orchestrator supplies ``full_refresh_completed_at_utc``.
    Other publishers omit it and inherit the prior refresh timestamp/identity,
    so rebuilding one derived domain cannot masquerade as new market data.
    """

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash=config_hash,
        parent_refresh_id=parent_refresh_id,
        full_refresh_completed_at_utc=full_refresh_completed_at_utc,
        stage_timings=stage_timings,
        option_publish_block=option_publish_block,
    )
    snapshot_path = _model_state_snapshot_path(paths, payload)
    payload["publish"]["retention_snapshot_path"] = _repo_relative(paths, snapshot_path)
    serialized = json.dumps(to_jsonable(payload), indent=2, sort_keys=True)
    _atomic_write_text(snapshot_path, serialized)
    target = paths.latest_model_state_manifest_path
    _atomic_write_text(target, serialized)
    return payload


def resolve_current_model_artifact_path(
    paths: ProjectPaths,
    artifact_name: str,
    *,
    fallback_path: Path | None = None,
) -> Path | None:
    """Resolve a current artifact through the model-state manifest.

    The fallback exists only for the transition period before a manifest has
    been published, or for old tests/fixtures that carry a partial manifest.
    When a manifest explicitly contains an artifact entry, a missing/unusable
    entry returns None rather than silently reading a mutable alias.
    """

    payload = load_current_model_state_manifest(paths)
    if payload is None:
        return _existing_path_or_none(fallback_path)
    if payload.get("manifest_readable") is False:
        return None
    if not isinstance(payload.get("artifacts"), dict):
        return None
    artifact = _manifest_artifact(payload, artifact_name)
    if artifact is None:
        return None
    if not artifact.get("usable"):
        return None
    if artifact.get("immutable") is not True:
        return None
    raw_path = str(artifact.get("path") or "").strip()
    if not raw_path:
        return None
    path = paths.resolve_repo_relative(raw_path)
    return path if path.exists() else None


def resolve_current_foundation_manifest_path(
    paths: ProjectPaths,
    *,
    require_current_manifest: bool = False,
) -> Path | None:
    """Resolve the foundation manifest selected by current model state.

    When ``require_current_manifest`` is true, a present-but-unusable model-state
    manifest is treated as a hard failure instead of silently dropping to the
    mutable foundation alias. This is the safe behavior for I2 readers that
    rebuild panels or scenarios from foundation data.
    """

    manifest_path = resolve_current_model_artifact_path(
        paths,
        "foundation",
        fallback_path=paths.latest_foundation_manifest_path,
    )
    if (
        manifest_path is None
        and require_current_manifest
        and load_current_model_state_manifest(paths) is not None
    ):
        raise FileNotFoundError(CURRENT_FOUNDATION_UNAVAILABLE_MESSAGE)
    return manifest_path


def read_current_model_parquet(
    paths: ProjectPaths,
    artifact_name: str,
    *,
    fallback_path: Path | None = None,
) -> pd.DataFrame:
    """Read a current Parquet artifact through the model-state manifest."""

    path = resolve_current_model_artifact_path(
        paths,
        artifact_name,
        fallback_path=fallback_path,
    )
    if path is None:
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()


def read_current_model_json(
    paths: ProjectPaths,
    artifact_name: str,
    *,
    fallback_path: Path | None = None,
) -> dict[str, Any] | None:
    """Read a current JSON artifact through the model-state manifest."""

    path = resolve_current_model_artifact_path(
        paths,
        artifact_name,
        fallback_path=fallback_path,
    )
    if path is None:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def load_current_model_state_manifest(paths: ProjectPaths) -> dict[str, Any] | None:
    """Load the latest model-state manifest, returning None when absent."""

    path = paths.latest_model_state_manifest_path
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _unreadable_manifest_payload(
            paths=paths,
            path=path,
            error=f"Could not read model-state manifest: {exc}",
        )
    if not isinstance(payload, dict):
        return _unreadable_manifest_payload(
            paths=paths,
            path=path,
            error="Could not read model-state manifest: root JSON value is not an object.",
        )
    return payload


def build_current_model_state_manifest(
    *,
    paths: ProjectPaths,
    config_hash: str | None,
    parent_refresh_id: str | None = None,
    full_refresh_completed_at_utc: str | None = None,
    stage_timings: dict[str, Any] | None = None,
    option_publish_block: OptionPublishBlock | None = None,
) -> dict[str, Any]:
    """Inspect current published artifacts and return a coherent-state manifest.

    When ``option_publish_block`` is given, the refresh could not publish fresh
    option artifacts (data-quality blockers). The manifest then carries forward
    the previous manifest's verified option artifact set instead of trusting
    the on-disk aliases, or marks the option domain UNAVAILABLE when no prior
    set verifies.
    """

    previous_manifest = load_current_model_state_manifest(paths)
    generated_at = _utc_now_iso()
    resolved_parent_refresh_id = _clean_string(parent_refresh_id) or _clean_string(
        (previous_manifest or {}).get("parent_refresh_id")
    )
    if full_refresh_completed_at_utc is not None:
        resolved_full_refresh_at = _clean_string(full_refresh_completed_at_utc)
    elif previous_manifest is not None:
        # Older manifests predate the dedicated field, so their publication
        # time is the only truthful migration source for the prior refresh.
        resolved_full_refresh_at = _clean_string(
            previous_manifest.get("full_refresh_completed_at_utc")
        ) or _clean_string(previous_manifest.get("generated_at_utc"))
    else:
        resolved_full_refresh_at = None

    artifacts = _artifact_map(paths, artifact_stamp=resolved_parent_refresh_id)
    if option_publish_block is None:
        option_publish_block = _inherited_option_publish_block(
            previous_manifest=previous_manifest,
            artifacts=artifacts,
        )

    carry: _OptionCarryForward | None = None
    carry_failure: str | None = None
    if option_publish_block is not None:
        carry, carry_failure = _resolve_option_carry_forward(
            paths=paths,
            previous_manifest=previous_manifest,
        )
        if carry is not None:
            artifacts.update(carry.entries)
        else:
            for name in OPTION_ARTIFACT_NAMES:
                artifacts[name] = _unavailable_option_artifact_entry(
                    name=name,
                    reason=carry_failure
                    or "No verified prior option artifact set is available.",
                )

    alignment = _alignment(
        artifacts,
        carried_options_run_id=(carry.snapshot_refresh_run_id if carry else None),
        options_carried_forward=carry is not None,
    )
    warnings = list(alignment["warnings"])
    missing_required = [
        name
        for name in REQUIRED_ARTIFACTS
        if not artifacts[name].get("usable")
    ]
    for name in missing_required:
        if artifacts[name].get("present"):
            warnings.append(f"Required artifact is not usable: {name}.")
        else:
            warnings.append(f"Required artifact is missing: {name}.")
    warnings.extend(_artifact_health_warnings(artifacts))

    freshness_domains = _freshness_domains(
        paths=paths,
        artifacts=artifacts,
        option_publish_block=option_publish_block,
        carry=carry,
        carry_failure=carry_failure,
        option_warnings=list(alignment.get("option_artifact_warnings", [])),
    )
    option_domain = freshness_domains.get("option_artifacts", {})
    if option_domain.get("status") == OPTION_FRESHNESS_CARRIED_FORWARD:
        warnings.append(_carried_forward_info_warning(option_domain))
    elif (
        option_publish_block is not None
        and option_domain.get("status") == OPTION_FRESHNESS_UNAVAILABLE
    ):
        warnings.append(
            "Option artifacts are unavailable this refresh; option pages show "
            "an unavailable notice instead of stale data."
        )

    state = "complete"
    if missing_required or alignment["status"] != "OK":
        state = "incomplete"
    if any(_is_required_health_warning(warning) for warning in warnings):
        state = "incomplete"

    return {
        "manifest_version": MODEL_STATE_MANIFEST_VERSION,
        "manifest_readable": True,
        "generated_at_utc": generated_at,
        # Publication time and full-data-refresh time deliberately differ.
        # A portfolio-only rebuild republishes the atomic pointer but must keep
        # the timestamp of the full refresh whose market data it still uses.
        "full_refresh_completed_at_utc": resolved_full_refresh_at,
        "parent_refresh_id": resolved_parent_refresh_id,
        "build_kind": "full_model",
        "state": state,
        "publish": {
            "atomic_pointer": True,
            "path": _repo_relative(paths, paths.latest_model_state_manifest_path),
            "latest_aliases_authoritative": False,
        },
        "config": {
            "config_hash": config_hash,
        },
        "manual_data": _file_artifact(
            paths=paths,
            name="manual_screening_store",
            path=paths.manual_screening_store_path,
            kind="sqlite",
            required_for_complete=False,
        ),
        "artifacts": artifacts,
        "alignment": alignment,
        "freshness_domains": freshness_domains,
        "warnings": warnings,
        "stage_timings": stage_timings or {},
    }


def summarize_model_state_manifest(payload: dict[str, Any] | None) -> list[str]:
    """Return concise status lines for CLI/UI display."""

    if payload is None:
        return [
            "Model state manifest: NOT FOUND",
            "  Legacy latest files are being inspected directly.",
        ]
    state = str(payload.get("state") or "unknown").upper()
    parent = payload.get("parent_refresh_id")
    generated = payload.get("generated_at_utc") or "?"
    lines = [
        f"Model state manifest: {state}",
        f"  generated_at_utc: {generated}",
        f"  parent_refresh_id: {parent if parent else '(none)'}",
    ]
    alignment = payload.get("alignment") if isinstance(payload.get("alignment"), dict) else {}
    if alignment:
        lines.append(f"  alignment: {alignment.get('status', 'UNKNOWN')}")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    for warning in warnings:
        lines.append(f"  - {warning}")
    return lines


def summarize_model_state_alignment(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the authoritative refresh-alignment verdict from model state.

    ``None`` means either no model-state manifest exists yet, or the manifest is
    incomplete but does not carry an alignment warning. In those cases legacy
    callers may still fall back to their old local checks. Any readable manifest
    with an explicit alignment warning is treated as authoritative.
    """

    if payload is None:
        return None

    if payload.get("manifest_readable") is False:
        warnings = _manifest_warning_messages(payload)
        message = warnings[0] if warnings else "Model-state manifest could not be read."
        return {
            "status": "UNKNOWN",
            "message": message,
            "warnings": tuple(warnings or [message]),
        }

    alignment = payload.get("alignment")
    alignment = alignment if isinstance(alignment, dict) else {}
    raw_status = str(alignment.get("status") or "").strip().upper()
    status = raw_status if raw_status in {"OK", "WARN"} else "UNKNOWN"
    alignment_warnings = _message_list(alignment.get("warnings"))
    if status == "OK" and str(payload.get("state") or "").strip().lower() != "complete":
        return None
    messages = _dedupe_messages(alignment_warnings)
    if status != "OK" and not messages:
        messages = [f"Model-state manifest reports alignment status {status}."]
    return {
        "status": status,
        "message": messages[0] if messages else None,
        "warnings": tuple(messages),
    }


def summarize_option_freshness(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return the option-artifact freshness verdict recorded in the manifest.

    ``None`` means the manifest is absent or predates freshness domains; readers
    then keep their legacy behavior. The returned dict carries ``status``
    (OK | CARRIED_FORWARD | UNAVAILABLE), the snapshot date, and a ready-to-render
    plain-English ``message`` so every surface shows the same wording.
    Status is one of OK | CARRIED_FORWARD | UNAVAILABLE | MISALIGNED.
    """

    if not isinstance(payload, dict):
        return None
    domains = payload.get("freshness_domains")
    if not isinstance(domains, dict):
        return None
    domain = domains.get("option_artifacts")
    if not isinstance(domain, dict):
        return None
    status = str(domain.get("status") or "").strip().upper()
    if status not in OPTION_FRESHNESS_STATUSES:
        return None
    freshness: dict[str, Any] = {
        "status": status,
        "as_of_date": _clean_string(domain.get("as_of_date")),
        "source_run_id": _clean_string(domain.get("source_run_id")),
        "market_session": _clean_string(domain.get("market_session")) or "UNKNOWN",
        "reason": _clean_string(domain.get("reason")),
        "blockers": tuple(_message_list(domain.get("blockers"))),
    }
    freshness["message"] = format_option_freshness_message(freshness)
    return freshness


def format_option_freshness_message(freshness: dict[str, Any]) -> str:
    """One shared plain-English freshness message for all option surfaces."""

    status = str(freshness.get("status") or "").strip().upper()
    as_of = _clean_string(freshness.get("as_of_date"))
    if status == OPTION_FRESHNESS_OK:
        if as_of:
            return f"Option data is from the market snapshot of {as_of}."
        return "Option data is from the latest refresh snapshot."
    if status == OPTION_FRESHNESS_CARRIED_FORWARD:
        snapshot = (
            f"Option prices are from the latest stored snapshot: {as_of}."
            if as_of
            else "Option prices are from the latest stored snapshot."
        )
        reason = _clean_string(freshness.get("reason"))
        if not reason:
            reason = "The latest refresh could not publish fresh option quotes."
        return f"{snapshot} {reason}"
    if status == OPTION_FRESHNESS_MISALIGNED:
        reason = _clean_string(freshness.get("reason")) or (
            "Option artifacts reference a different refresh than the current model run; "
            "run python main.py refresh to realign."
        )
        if as_of:
            return f"Option data is from the snapshot of {as_of}, but it is misaligned: {reason}"
        return f"Option data is misaligned: {reason}"
    return (
        "Option data is not available yet. "
        "Run python main.py refresh during US options market hours."
    )


def _artifact_map(
    paths: ProjectPaths,
    *,
    artifact_stamp: str | None = None,
) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {
        "foundation": _foundation_artifact(paths, artifact_stamp=artifact_stamp),
        "options": _options_artifact(paths, artifact_stamp=artifact_stamp),
        "tool_a": _parquet_artifact(
            paths=paths,
            name="tool_a",
            path=paths.latest_tool_a_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_a_structural_metrics": _tool_a_structural_metrics_artifact(paths),
        "tool_b": _parquet_artifact(
            paths=paths,
            name="tool_b",
            path=paths.latest_tool_b_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_c": _parquet_artifact(
            paths=paths,
            name="tool_c",
            path=paths.latest_tool_c_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_d": _parquet_artifact(
            paths=paths,
            name="tool_d",
            path=paths.latest_tool_d_snapshot_parquet_path,
            required_for_complete=True,
        ),
        "tool_d_spot": _parquet_artifact(
            paths=paths,
            name="tool_d_spot",
            path=paths.latest_tool_d_spot_snapshot_parquet_path,
            required_for_complete=False,
        ),
        FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME: _parquet_artifact(
            paths=paths,
            name=FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
            path=fetched_fundamentals_latest_path(paths),
            required_for_complete=False,
        ),
        "portfolio_lines": _parquet_artifact(
            paths=paths,
            name="portfolio_lines",
            path=paths.latest_portfolio_lines_path,
            required_for_complete=False,
        ),
        "portfolio_positions": _parquet_artifact(
            paths=paths,
            name="portfolio_positions",
            path=paths.latest_portfolio_positions_path,
            required_for_complete=False,
        ),
        "portfolio_summary": _parquet_artifact(
            paths=paths,
            name="portfolio_summary",
            path=paths.latest_portfolio_summary_path,
            required_for_complete=False,
        ),
        "benchmark_betas": _parquet_artifact(
            paths=paths,
            name="benchmark_betas",
            path=paths.latest_benchmark_betas_path,
            required_for_complete=False,
        ),
        "portfolio_reconciliation": _parquet_artifact(
            paths=paths,
            name="portfolio_reconciliation",
            path=paths.latest_portfolio_reconciliation_path,
            required_for_complete=False,
        ),
        "portfolio_hedge_sizing": _parquet_artifact(
            paths=paths,
            name="portfolio_hedge_sizing",
            path=paths.latest_portfolio_hedge_sizing_path,
            required_for_complete=False,
        ),
        "portfolio_correlations": _parquet_artifact(
            paths=paths,
            name="portfolio_correlations",
            path=paths.latest_portfolio_correlations_path,
            required_for_complete=False,
        ),
        "portfolio_value_history": _parquet_artifact(
            paths=paths,
            name="portfolio_value_history",
            path=paths.latest_portfolio_value_history_path,
            required_for_complete=False,
        ),
        "portfolio_reconciliation_export": _parquet_artifact(
            paths=paths,
            name="portfolio_reconciliation_export",
            path=paths.latest_portfolio_reconciliation_export_path,
            required_for_complete=False,
        ),
        "portfolio_reconciliation_export_csv": _csv_artifact(
            paths=paths,
            name="portfolio_reconciliation_export_csv",
            path=paths.latest_portfolio_reconciliation_export_csv_path,
            required_for_complete=False,
        ),
    }
    for name in PLANNED_I3_ARTIFACTS:
        artifacts[name] = _optional_i3_parquet_artifact(paths=paths, name=name)
    for name in TICKER_PAGE_ARTIFACT_NAMES:
        artifacts[name] = _parquet_artifact(
            paths=paths,
            name=name,
            path=_ticker_page_latest_path(paths, name),
            required_for_complete=True,
        )
    return artifacts


def _ticker_page_latest_path(paths: ProjectPaths, name: str) -> Path:
    return {
        "ticker_page_gold_response": paths.latest_ticker_page_gold_response_path,
        "ticker_page_percentiles": paths.latest_ticker_page_percentiles_path,
        "ticker_page_performance": paths.latest_ticker_page_performance_path,
        "ticker_page_research_series": paths.latest_ticker_page_research_series_path,
        "ticker_page_fx_attribution": paths.latest_ticker_page_fx_attribution_path,
        "ticker_page_downside_context": paths.latest_ticker_page_downside_context_path,
    }[name]


def _optional_i3_parquet_artifact(
    *,
    paths: ProjectPaths,
    name: str,
) -> dict[str, Any]:
    artifact = _parquet_artifact(
        paths=paths,
        name=name,
        path=option_artifact_latest_path(paths, name),
        required_for_complete=name in REQUIRED_OPTION_ARTIFACT_NAMES,
    )
    if not artifact["present"]:
        artifact["planned_phase"] = "I3"
    return artifact


def _foundation_artifact(
    paths: ProjectPaths,
    *,
    artifact_stamp: str | None,
) -> dict[str, Any]:
    artifact = _json_artifact(
        paths=paths,
        name="foundation",
        path=paths.latest_foundation_manifest_path,
        required_for_complete=True,
    )
    payload = artifact.pop("_payload", None)
    if isinstance(payload, dict):
        _snapshot_json_artifact(
            paths=paths,
            artifact=artifact,
            source_path=paths.latest_foundation_manifest_path,
            file_prefix="foundation_manifest",
            stamp=artifact_stamp or _clean_string(payload.get("refresh_run_id")),
        )
        artifact.update(
            {
                "refresh_run_id": _clean_string(payload.get("refresh_run_id")),
                "snapshot_as_of_date": payload.get("snapshot_as_of_date"),
                "foundation_status": payload.get("foundation_status"),
                "raw_qa_status": _nested_status(payload.get("raw_qa_summary")),
                "normalization_qa_status": _nested_status(
                    payload.get("normalization_qa_summary")
                ),
            }
        )
    return artifact


def _options_artifact(
    paths: ProjectPaths,
    *,
    artifact_stamp: str | None,
) -> dict[str, Any]:
    artifact = _json_artifact(
        paths=paths,
        name="options",
        path=paths.latest_options_manifest_path,
        required_for_complete=True,
    )
    payload = artifact.pop("_payload", None)
    if isinstance(payload, dict):
        _snapshot_json_artifact(
            paths=paths,
            artifact=artifact,
            source_path=paths.latest_options_manifest_path,
            file_prefix="options_manifest",
            stamp=artifact_stamp or _clean_string(payload.get("refresh_run_id")),
        )
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        artifact.update(
            {
                "refresh_run_id": _clean_string(payload.get("refresh_run_id")),
                "as_of_date": payload.get("as_of_date"),
                "options_phase_status": summary.get("options_phase_status"),
                "options_success_count": summary.get("options_success_count"),
                "options_error_count": summary.get("options_error_count"),
                "options_feature_row_count": summary.get("options_feature_row_count"),
            }
        )
    return artifact


def _json_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    required_for_complete: bool,
) -> dict[str, Any]:
    artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="json",
        required_for_complete=required_for_complete,
    )
    if not artifact["present"]:
        return artifact
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        artifact["read_error"] = str(exc)
        artifact["readable"] = False
        artifact["usable"] = False
        return artifact
    artifact["_payload"] = payload
    return artifact


def _parquet_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    required_for_complete: bool,
) -> dict[str, Any]:
    alias_artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="parquet",
        required_for_complete=required_for_complete,
    )
    if not alias_artifact["present"]:
        return alias_artifact
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        alias_artifact["read_error"] = str(exc)
        alias_artifact["readable"] = False
        alias_artifact["usable"] = False
        return alias_artifact
    alias_metadata = parquet_context_metadata(path)

    source_ids = _unique_strings(frame, "source_run_id")
    if not source_ids:
        source_ids = _frame_attr_strings(frame, "source_run_id")
    if not source_ids:
        source_ids = _metadata_strings(alias_metadata, "source_run_id")
    immutable_path = _resolve_run_stamped_parquet(
        paths=paths,
        name=name,
        source_run_ids=source_ids,
    )
    artifact = alias_artifact
    if immutable_path is not None:
        artifact = _file_artifact(
            paths=paths,
            name=name,
            path=immutable_path,
            kind="parquet",
            required_for_complete=required_for_complete,
        )
        artifact["source_alias_path"] = _repo_relative(paths, path)
        artifact["immutable"] = True
        try:
            frame = pd.read_parquet(immutable_path)
        except Exception as exc:
            artifact["read_error"] = str(exc)
            artifact["readable"] = False
            artifact["usable"] = False
            return artifact
        alias_metadata = parquet_context_metadata(immutable_path)
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(
        _first_present(frame, "schema_version")
    ) or _clean_string(alias_metadata.get("schema_version")) or _clean_string(
        frame.attrs.get("schema_version")
    )
    snapshot_ids = _unique_strings(frame, "snapshot_refresh_run_id")
    if not snapshot_ids:
        snapshot_ids = _frame_attr_strings(frame, "snapshot_refresh_run_id")
    if not snapshot_ids:
        snapshot_ids = _metadata_strings(alias_metadata, "snapshot_refresh_run_id")
    artifact["snapshot_refresh_run_ids"] = snapshot_ids
    artifact["source_run_ids"] = source_ids
    if name == FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME:
        artifact["fetched_at_utc"] = _clean_string(
            _first_present(frame, "fetched_at_utc")
        )
        value_statuses = _unique_strings(frame, "value_status")
        if value_statuses:
            artifact["value_statuses"] = value_statuses
    return artifact


def _csv_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    required_for_complete: bool,
) -> dict[str, Any]:
    alias_artifact = _file_artifact(
        paths=paths,
        name=name,
        path=path,
        kind="csv",
        required_for_complete=required_for_complete,
    )
    if not alias_artifact["present"]:
        return alias_artifact
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        alias_artifact["read_error"] = str(exc)
        alias_artifact["readable"] = False
        alias_artifact["usable"] = False
        return alias_artifact

    source_ids = _unique_strings(frame, "source_run_id")
    immutable_path = _resolve_run_stamped_artifact(
        paths=paths,
        name=name,
        source_run_ids=source_ids,
        suffix=".csv",
    )
    if immutable_path is None:
        immutable_path = _resolve_run_stamped_artifact_by_alias_hash(
            paths=paths,
            name=name,
            alias_path=path,
            suffix=".csv",
        )
    artifact = alias_artifact
    if immutable_path is not None:
        artifact = _file_artifact(
            paths=paths,
            name=name,
            path=immutable_path,
            kind="csv",
            required_for_complete=required_for_complete,
        )
        artifact["source_alias_path"] = _repo_relative(paths, path)
        artifact["immutable"] = True
        try:
            frame = pd.read_csv(immutable_path)
        except Exception as exc:
            artifact["read_error"] = str(exc)
            artifact["readable"] = False
            artifact["usable"] = False
            return artifact
        source_ids = _unique_strings(frame, "source_run_id")
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(_first_present(frame, "schema_version"))
    artifact["snapshot_refresh_run_ids"] = _unique_strings(frame, "snapshot_refresh_run_id")
    artifact["source_run_ids"] = source_ids
    return artifact


def _tool_a_structural_metrics_artifact(paths: ProjectPaths) -> dict[str, Any]:
    path = paths.latest_tool_a_structural_metrics_path
    alias_artifact = _file_artifact(
        paths=paths,
        name="tool_a_structural_metrics",
        path=path,
        kind="parquet",
        required_for_complete=False,
    )
    if not alias_artifact["present"]:
        return alias_artifact
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        alias_artifact["read_error"] = str(exc)
        alias_artifact["readable"] = False
        alias_artifact["usable"] = False
        return alias_artifact

    source_ids = _unique_strings(frame, "source_run_id")
    if not source_ids:
        source_ids = _metadata_strings(parquet_context_metadata(path), "source_run_id")
    immutable_path = _resolve_tool_a_structural_metrics_path(
        paths=paths,
        source_run_ids=source_ids,
    )
    artifact = alias_artifact
    if immutable_path is not None:
        artifact = _file_artifact(
            paths=paths,
            name="tool_a_structural_metrics",
            path=immutable_path,
            kind="parquet",
            required_for_complete=False,
        )
        artifact["source_alias_path"] = _repo_relative(paths, path)
        artifact["immutable"] = True
        try:
            frame = pd.read_parquet(immutable_path)
        except Exception as exc:
            artifact["read_error"] = str(exc)
            artifact["readable"] = False
            artifact["usable"] = False
            return artifact
    artifact["row_count"] = int(len(frame.index))
    artifact["columns"] = [str(column) for column in frame.columns]
    artifact["schema_version"] = _clean_string(_first_present(frame, "schema_version"))
    artifact["source_run_ids"] = source_ids
    return artifact


def _file_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    path: Path,
    kind: str,
    required_for_complete: bool,
) -> dict[str, Any]:
    present = path.exists()
    artifact: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "path": _repo_relative(paths, path),
        "source_alias_path": None,
        "immutable": False,
        "present": present,
        "readable": False,
        "usable": False,
        "required_for_complete": required_for_complete,
        "schema_version": None,
    }
    if present:
        try:
            stat = path.stat()
            artifact.update(
                {
                    "sha256": _sha256_file(path),
                    "modified_at_utc": _mtime_iso(path),
                    "size_bytes": stat.st_size,
                    "readable": True,
                    "usable": True,
                }
            )
        except Exception as exc:
            artifact["read_error"] = str(exc)
    return artifact


def _alignment(
    artifacts: dict[str, dict[str, Any]],
    *,
    carried_options_run_id: str | None = None,
    options_carried_forward: bool = False,
) -> dict[str, Any]:
    warnings: list[str] = []
    foundation_id = _clean_string(artifacts["foundation"].get("refresh_run_id"))
    options_id = _clean_string(artifacts["options"].get("refresh_run_id"))
    if artifacts["foundation"].get("usable") and not foundation_id:
        warnings.append("foundation does not carry refresh_run_id.")
    if artifacts["options"].get("usable") and not options_id:
        warnings.append("options does not carry refresh_run_id.")
    if foundation_id and options_id and foundation_id != options_id:
        warnings.append(
            f"Foundation refresh {foundation_id} does not match options refresh {options_id}."
        )
    tool_ids, tool_warnings = _refresh_alignment(
        artifacts,
        names=("tool_a", "tool_b", "tool_c", "tool_d"),
        expected_run_id=foundation_id,
        expected_label="foundation",
    )
    # Carried-forward option artifacts intentionally reference an older options
    # snapshot. Validating them against today's options ingestion run would mark
    # every carried publish WARN/incomplete, so they are validated against their
    # own carried snapshot id instead (self-consistency still checked).
    option_expected_run_id = (
        carried_options_run_id if options_carried_forward else options_id
    )
    option_expected_label = (
        "the carried options snapshot" if options_carried_forward else "options"
    )
    option_ids, option_warnings = _refresh_alignment(
        artifacts,
        names=REQUIRED_OPTION_ARTIFACT_NAMES,
        expected_run_id=option_expected_run_id,
        expected_label=option_expected_label,
    )
    # Ticker-page artifacts belong to the tool generation: they are derived from
    # all four tool frames, so a mismatch means the page would render one
    # generation's numbers under another's identity (plan §5.4).
    ticker_page_ids, ticker_page_warnings = _refresh_alignment(
        artifacts,
        names=TICKER_PAGE_ARTIFACT_NAMES,
        expected_run_id=foundation_id,
        expected_label="foundation",
    )
    portfolio_ids, portfolio_warnings = _refresh_alignment(
        artifacts,
        names=PORTFOLIO_ALIGNMENT_ARTIFACTS,
        expected_run_id=foundation_id,
        expected_label="foundation",
    )
    warnings.extend(tool_warnings)
    warnings.extend(option_warnings)
    warnings.extend(ticker_page_warnings)
    warnings.extend(portfolio_warnings)
    status = "OK" if not warnings else "WARN"
    result = {
        "status": status,
        "foundation_refresh_run_id": foundation_id,
        "options_refresh_run_id": options_id,
        "tool_refresh_run_ids": tool_ids,
        "option_artifact_refresh_run_ids": option_ids,
        "ticker_page_artifact_refresh_run_ids": ticker_page_ids,
        "ticker_page_artifact_warnings": list(ticker_page_warnings),
        "portfolio_artifact_refresh_run_ids": portfolio_ids,
        "warnings": warnings,
        # Option-artifact alignment warnings, kept separate so option freshness can
        # downgrade to MISALIGNED instead of OK when these fire (audit M4).
        "option_artifact_warnings": list(option_warnings),
    }
    if options_carried_forward:
        result["options_carried_forward"] = True
        result["carried_options_refresh_run_id"] = carried_options_run_id
    return result


def _inherited_option_publish_block(
    *,
    previous_manifest: dict[str, Any] | None,
    artifacts: dict[str, dict[str, Any]],
) -> OptionPublishBlock | None:
    """Preserve a carried/unavailable option domain across non-option publishes.

    Publishers that never ran the option-artifacts step (portfolio lot edits,
    fetch-fundamentals, partial refreshes) must not silently flip a
    CARRIED_FORWARD/UNAVAILABLE option domain back to OK: the on-disk aliases
    still hold the old snapshot, and claiming OK would both lie about
    freshness and re-trigger run-id mismatch warnings. Inherit the previous
    block unless a fresh option build aligned with the current options
    ingestion manifest has happened since.
    """

    if not isinstance(previous_manifest, dict):
        return None
    domains = previous_manifest.get("freshness_domains")
    domain = domains.get("option_artifacts") if isinstance(domains, dict) else None
    if not isinstance(domain, dict):
        return None
    status = str(domain.get("status") or "").strip().upper()
    if status not in {OPTION_FRESHNESS_CARRIED_FORWARD, OPTION_FRESHNESS_UNAVAILABLE}:
        return None
    options_id = _clean_string(artifacts.get("options", {}).get("refresh_run_id"))
    if options_id and all(
        options_id in (artifacts.get(name, {}).get("snapshot_refresh_run_ids") or [])
        for name in REQUIRED_OPTION_ARTIFACT_NAMES
    ):
        # A fresh option build aligned with the current options snapshot is on
        # disk (e.g. a successful standalone option-artifacts run); OK is the
        # truthful domain now.
        return None
    return OptionPublishBlock(
        blockers=tuple(_message_list(domain.get("blockers"))),
        market_session=_clean_string(domain.get("market_session")) or "UNKNOWN",
        inherited_reason=(
            _clean_string(domain.get("reason"))
            if status == OPTION_FRESHNESS_UNAVAILABLE
            else None
        ),
    )


def _resolve_option_carry_forward(
    *,
    paths: ProjectPaths,
    previous_manifest: dict[str, Any] | None,
) -> tuple[_OptionCarryForward | None, str | None]:
    """Re-verify the previous manifest's option artifact set for carry-forward.

    The previous manifest is the source of truth (never the mutable latest
    aliases): every entry must still exist at its immutable path, hash to the
    recorded sha256, and carry the current schema version. All ten artifacts
    must come from one source run; the four required ones must be non-empty.
    Anything less returns ``(None, reason)`` — never a partial carry.
    """

    if previous_manifest is None:
        return None, "No model-state manifest exists yet."
    if previous_manifest.get("manifest_readable") is False:
        return None, "The previous model-state manifest could not be read."
    previous_artifacts = previous_manifest.get("artifacts")
    if not isinstance(previous_artifacts, dict):
        return None, "The previous model-state manifest has no artifacts map."

    # Per-generation validation (plan §6.4): the expected NAME SET and schema
    # version come from the generation's OWN stamp, never from whatever version
    # this build publishes. A v3 generation therefore stays fully usable and
    # carry-forwardable under v4 code (legacy reader window) — the health
    # machinery must never demand v4-only artifacts from a v3 generation.
    generation_version, version_failure = _generation_option_schema_version(
        previous_artifacts
    )
    if generation_version is None:
        return None, version_failure
    generation_names = option_artifact_names_for_version(generation_version)

    entries: dict[str, dict[str, Any]] = {}
    source_run_ids: set[str] = set()
    snapshot_run_ids: set[str] = set()
    for name in generation_names:
        entry = previous_artifacts.get(name)
        if not isinstance(entry, dict):
            return None, f"Previous manifest lacks option artifact {name}."
        if not entry.get("usable") or entry.get("immutable") is not True:
            return None, f"Previous option artifact {name} is not usable/immutable."
        raw_path = str(entry.get("path") or "").strip()
        if not raw_path:
            return None, f"Previous option artifact {name} has no recorded path."
        path = paths.resolve_repo_relative(raw_path)
        if not path.exists() or not path.is_file():
            return None, f"Previous option artifact file is missing: {raw_path}."
        expected_sha = str(entry.get("sha256") or "").strip()
        if not expected_sha:
            return None, f"Previous option artifact {name} has no recorded sha256."
        try:
            actual_sha = _sha256_file(path)
        except Exception as exc:
            return None, f"Could not hash previous option artifact {name}: {exc}."
        if actual_sha != expected_sha:
            return None, f"Previous option artifact {name} failed sha256 verification."
        if normalized_option_schema_version(entry.get("schema_version")) != generation_version:
            return None, (
                f"Previous option artifact {name} has schema version "
                f"{entry.get('schema_version')!r}; the generation is "
                f"v{generation_version}."
            )
        if (
            name in REQUIRED_OPTION_ARTIFACT_NAMES
            and int(entry.get("row_count") or 0) <= 0
        ):
            return None, f"Previous option artifact {name} is empty."
        entry_source_ids = [
            value for value in (entry.get("source_run_ids") or []) if _clean_string(value)
        ]
        if not entry_source_ids:
            return None, f"Previous option artifact {name} has no source_run_id."
        source_run_ids.update(str(value) for value in entry_source_ids)
        snapshot_run_ids.update(
            str(value)
            for value in (entry.get("snapshot_refresh_run_ids") or [])
            if _clean_string(value)
        )
        carried = dict(entry)
        carried["carried_forward"] = True
        carried["carried_from_parent_refresh_id"] = _clean_string(
            previous_manifest.get("parent_refresh_id")
        )
        entries[name] = carried

    if len(source_run_ids) != 1:
        return None, (
            "Previous option artifacts do not share a single source run: "
            + ", ".join(sorted(source_run_ids))
            + "."
        )
    # A carried set must be one coherent chain snapshot. Mixed (or missing)
    # snapshot ids would stitch candidates/charts/signals from different
    # underlying chains, so that set is refused outright, never carried.
    if len(snapshot_run_ids) != 1:
        return None, (
            "Previous option artifacts do not share a single options snapshot id: "
            + (", ".join(sorted(snapshot_run_ids)) if snapshot_run_ids else "(none)")
            + "."
        )

    carry = _OptionCarryForward(
        entries=entries,
        source_run_id=next(iter(source_run_ids)),
        snapshot_refresh_run_id=next(iter(snapshot_run_ids)),
        as_of_date=_carried_option_as_of_date(
            paths=paths,
            entries=entries,
            previous_manifest=previous_manifest,
        ),
        carried_from_parent_refresh_id=_clean_string(
            previous_manifest.get("parent_refresh_id")
        ),
    )
    return carry, None


def _schema_version_matches(value: object) -> bool:
    """True when a stamped option schema version is one this build can serve.

    Set-aware (plan §6.4): both the active version and every legacy version in
    the reader window pass, because a generation is validated against ITS OWN
    name set, not the publisher's. Parity with the serve reader's gate (audit
    N2): "3" or "3.0" match version 3; "3.9" must not.
    """

    version = normalized_option_schema_version(_clean_string(value))
    return version in SUPPORTED_OPTION_SCHEMA_VERSIONS


def _single_option_schema_version(artifacts: dict[str, Any]) -> bool:
    """True when the required option artifacts all carry ONE schema version.

    Same rule as ``_generation_option_schema_version`` (a generation has exactly
    one option schema version), applied to the artifacts being published so
    freshness and carry-forward can never disagree about the same manifest.
    """

    versions = {
        normalized_option_schema_version(
            (artifacts.get(name) or {}).get("schema_version")
        )
        for name in REQUIRED_OPTION_ARTIFACT_NAMES
    }
    return len(versions) == 1 and None not in versions


def _generation_option_schema_version(
    previous_artifacts: dict[str, Any],
) -> tuple[int | None, str | None]:
    """Resolve a published generation's own option schema version.

    Read from the v3 BASE artifacts only — they exist in every supported
    generation, so the version can be resolved before the name set is known.
    """

    versions: set[int] = set()
    for name in OPTION_TRADING_READ_SET:
        entry = previous_artifacts.get(name)
        if not isinstance(entry, dict):
            return None, f"Previous manifest lacks option artifact {name}."
        version = normalized_option_schema_version(entry.get("schema_version"))
        if version is None:
            return None, (
                f"Previous option artifact {name} has no readable schema version "
                f"({entry.get('schema_version')!r})."
            )
        versions.add(version)
    if len(versions) != 1:
        return None, (
            "Previous option artifacts mix schema versions: "
            + ", ".join(str(version) for version in sorted(versions))
            + "."
        )
    version = versions.pop()
    if version not in SUPPORTED_OPTION_SCHEMA_VERSIONS:
        return None, (
            f"Previous option artifacts carry unsupported schema version {version}; "
            f"supported: {', '.join(str(item) for item in SUPPORTED_OPTION_SCHEMA_VERSIONS)}."
        )
    return version, None


def _carried_option_as_of_date(
    *,
    paths: ProjectPaths,
    entries: dict[str, dict[str, Any]],
    previous_manifest: dict[str, Any],
) -> str | None:
    """Read the snapshot date from the carried artifacts themselves.

    The artifacts are the source of truth so a multi-day chain keeps the
    original date instead of drifting. Falls back to the previous manifest's
    freshness domain, then its options ingestion entry.
    """

    entry = entries.get("option_signal_summary")
    raw_path = str((entry or {}).get("path") or "").strip()
    if raw_path:
        path = paths.resolve_repo_relative(raw_path)
        try:
            frame = pd.read_parquet(path, columns=["as_of_date"])
            values = frame["as_of_date"].dropna()
            if not values.empty:
                value = _clean_string(values.iloc[0])
                if value:
                    return value
        except Exception:
            pass
    domains = previous_manifest.get("freshness_domains")
    if isinstance(domains, dict):
        domain = domains.get("option_artifacts")
        if isinstance(domain, dict):
            value = _clean_string(domain.get("as_of_date"))
            if value:
                return value
    previous_artifacts = previous_manifest.get("artifacts")
    if isinstance(previous_artifacts, dict):
        options_entry = previous_artifacts.get("options")
        if isinstance(options_entry, dict):
            return _clean_string(options_entry.get("as_of_date"))
    return None


def _unavailable_option_artifact_entry(*, name: str, reason: str) -> dict[str, Any]:
    """Manifest entry for an option artifact the manifest refuses to reference.

    ``present`` is False on purpose: the entry must read as absent so readers
    resolve nothing and alignment skips it — even if stale files still sit on
    disk. The mutable aliases are never an authority for carry-forward.
    """

    return {
        "name": name,
        "kind": "parquet",
        "path": None,
        "source_alias_path": None,
        "immutable": False,
        "present": False,
        "readable": False,
        "usable": False,
        "required_for_complete": name in REQUIRED_OPTION_ARTIFACT_NAMES,
        "schema_version": None,
        "unavailable_reason": reason,
    }


def _freshness_domains(
    *,
    paths: ProjectPaths,
    artifacts: dict[str, dict[str, Any]],
    option_publish_block: OptionPublishBlock | None,
    carry: _OptionCarryForward | None,
    carry_failure: str | None,
    option_warnings: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    core: dict[str, Any] = {
        "status": (
            OPTION_FRESHNESS_OK
            if artifacts["foundation"].get("usable")
            else OPTION_FRESHNESS_UNAVAILABLE
        ),
        "as_of_date": _clean_string(artifacts["foundation"].get("snapshot_as_of_date")),
    }

    option_domain: dict[str, Any]
    if option_publish_block is None:
        required_usable = all(
            artifacts[name].get("usable") for name in REQUIRED_OPTION_ARTIFACT_NAMES
        )
        # Audit M3: OK must also mean CURRENT schema — otherwise a publisher
        # running over pre-bump artifacts claims OK while the serve reader
        # fails loud on the same files (dishonest split-brain).
        # And MIXED versions are never OK: carry-forward resolves a generation's
        # ONE version via _generation_option_schema_version and rejects a mix, so
        # freshness must reject it too or the two disagree about the same
        # manifest (freshness says OK, carry-forward says unusable).
        required_current_schema = all(
            _schema_version_matches(artifacts[name].get("schema_version"))
            for name in REQUIRED_OPTION_ARTIFACT_NAMES
        ) and _single_option_schema_version(artifacts)
        if required_usable and required_current_schema:
            option_domain = {
                "status": OPTION_FRESHNESS_OK,
                "source_run_id": _first_option_source_run_id(artifacts),
                "as_of_date": _option_artifact_as_of_date(paths=paths, artifacts=artifacts)
                or _clean_string(artifacts["options"].get("as_of_date")),
            }
            # Audit M4: usable + current-schema, but alignment found the option
            # artifacts reference a different refresh -> not OK. Surface MISALIGNED so
            # the freshness box can't say "current" while the banner says WARN.
            if option_warnings:
                option_domain["status"] = OPTION_FRESHNESS_MISALIGNED
                option_domain["reason"] = (
                    "Option artifacts are usable but reference a different refresh than "
                    "the current foundation/options run; run python main.py refresh to realign."
                )
                option_domain["alignment_warnings"] = list(option_warnings)
        elif required_usable:
            option_domain = {
                "status": OPTION_FRESHNESS_UNAVAILABLE,
                "reason": (
                    "Option artifacts on disk predate the current schema "
                    f"(v{ACTIVE_OPTION_SCHEMA_VERSION}); run python main.py "
                    "refresh to rebuild them."
                ),
            }
        else:
            option_domain = {
                "status": OPTION_FRESHNESS_UNAVAILABLE,
                "reason": "Required option artifacts are missing or not usable.",
            }
    elif carry is not None:
        option_domain = {
            "status": OPTION_FRESHNESS_CARRIED_FORWARD,
            "source_run_id": carry.source_run_id,
            "as_of_date": carry.as_of_date,
            "reason": _blocked_reason(option_publish_block),
            "market_session": option_publish_block.market_session,
            "blockers": list(option_publish_block.blockers),
            "carried_from_parent_refresh_id": carry.carried_from_parent_refresh_id,
        }
    else:
        option_domain = {
            "status": OPTION_FRESHNESS_UNAVAILABLE,
            "reason": option_publish_block.inherited_reason
            or carry_failure
            or "No verified prior option artifact set is available.",
            "market_session": option_publish_block.market_session,
            "blockers": list(option_publish_block.blockers),
        }
    return {"core": core, "option_artifacts": option_domain}


def _blocked_reason(block: OptionPublishBlock) -> str:
    if str(block.market_session).upper() == "CLOSED":
        return (
            "US options were closed at refresh time, so live option quotes "
            "were not refreshed."
        )
    return "Option benchmark quotes were not publishable at refresh time."


def _carried_forward_info_warning(option_domain: dict[str, Any]) -> str:
    as_of = _clean_string(option_domain.get("as_of_date")) or "an earlier snapshot"
    source = _clean_string(option_domain.get("source_run_id")) or "unknown"
    return (
        f"Option artifacts were carried forward from the stored snapshot of "
        f"{as_of} (source run {source}); fresh option quotes were not "
        "publishable this refresh."
    )


def _first_option_source_run_id(artifacts: dict[str, dict[str, Any]]) -> str | None:
    for name in REQUIRED_OPTION_ARTIFACT_NAMES:
        for value in artifacts.get(name, {}).get("source_run_ids") or []:
            cleaned = _clean_string(value)
            if cleaned:
                return cleaned
    return None


def _option_artifact_as_of_date(
    *,
    paths: ProjectPaths,
    artifacts: dict[str, dict[str, Any]],
) -> str | None:
    entry = artifacts.get("option_signal_summary") or {}
    if not entry.get("usable"):
        return None
    raw_path = str(entry.get("path") or "").strip()
    if not raw_path:
        return None
    path = paths.resolve_repo_relative(raw_path)
    try:
        frame = pd.read_parquet(path, columns=["as_of_date"])
        values = frame["as_of_date"].dropna()
        if values.empty:
            return None
        return _clean_string(values.iloc[0])
    except Exception:
        return None


def _refresh_alignment(
    artifacts: dict[str, dict[str, Any]],
    *,
    names: tuple[str, ...],
    expected_run_id: str | None,
    expected_label: str,
) -> tuple[dict[str, list[str]], list[str]]:
    ids_by_name: dict[str, list[str]] = {}
    warnings: list[str] = []
    for name in names:
        artifact = artifacts[name]
        run_ids = list(artifact.get("snapshot_refresh_run_ids") or [])
        ids_by_name[name] = run_ids
        if not artifact.get("present"):
            continue
        if not run_ids:
            warnings.append(f"{name} does not carry snapshot_refresh_run_id.")
            continue
        if len(run_ids) > 1:
            warnings.append(
                f"{name} carries multiple snapshot_refresh_run_id values: {', '.join(run_ids)}."
            )
        if expected_run_id and expected_run_id not in run_ids:
            warnings.append(
                f"{name} references {', '.join(run_ids)} while "
                f"{expected_label} is {expected_run_id}."
            )
    return ids_by_name, warnings


def _artifact_health_warnings(artifacts: dict[str, dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    foundation_status = _clean_string(artifacts["foundation"].get("foundation_status"))
    if artifacts["foundation"].get("usable") and not foundation_status:
        warnings.append("Foundation status is missing.")
    if foundation_status and foundation_status not in {"PASS", "WARN"}:
        warnings.append(f"Foundation status is not usable: {foundation_status}.")
    options_status = _clean_string(artifacts["options"].get("options_phase_status"))
    if artifacts["options"].get("usable") and not options_status:
        warnings.append("Options phase status is missing.")
    if options_status and options_status == "FAIL":
        warnings.append("Options phase status is FAIL.")
    fundamentals = artifacts.get(FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME)
    if isinstance(fundamentals, dict) and fundamentals.get("usable"):
        statuses = set(fundamentals.get("value_statuses") or [])
        if "STALE" in statuses:
            warnings.append("Official fundamentals include stale statement fields.")
    for name in REQUIRED_ARTIFACTS:
        artifact = artifacts[name]
        if (
            artifact.get("kind") == "parquet"
            and artifact.get("readable")
            and int(artifact.get("row_count") or 0) == 0
        ):
            warnings.append(f"{name} has zero rows.")
        if artifact.get("usable") and not artifact.get("immutable"):
            warnings.append(f"Required artifact is not immutable: {name}.")
    return warnings


def _manifest_warning_messages(payload: dict[str, Any]) -> list[str]:
    messages = _message_list(payload.get("warnings"))
    read_error = _clean_string(payload.get("read_error"))
    if read_error:
        messages.append(read_error)
    return _dedupe_messages(messages)


def _message_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for item in value
        for text in (_clean_string(item),)
        if text
    ]


def _dedupe_messages(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _is_required_health_warning(warning: str) -> bool:
    return (
        warning.startswith("Foundation status is not usable:")
        or warning == "Foundation status is missing."
        or warning == "Options phase status is missing."
        or warning == "Options phase status is FAIL."
        or warning.endswith(" has zero rows.")
        or warning.startswith("Required artifact is not immutable:")
    )


def _nested_status(value: object) -> object:
    if isinstance(value, dict):
        return value.get("overall_status")
    return None


def _first_present(frame: pd.DataFrame, column: str) -> object | None:
    if column not in frame.columns:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    return values.iloc[0]


def _unique_strings(frame: pd.DataFrame, column: str) -> list[str]:
    return _common_unique_strings(frame, column)


def _frame_attr_strings(frame: pd.DataFrame, key: str) -> list[str]:
    value = _clean_string(frame.attrs.get(key))
    return [value] if value else []


def _metadata_strings(metadata: dict[str, str], key: str) -> list[str]:
    value = _clean_string(metadata.get(key))
    return [value] if value else []


def _clean_string(value: object) -> str | None:
    return _common_clean_string(value)


def _manifest_artifact(
    payload: dict[str, Any],
    artifact_name: str,
) -> dict[str, Any] | None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return None
    artifact = artifacts.get(artifact_name)
    return artifact if isinstance(artifact, dict) else None


def _unreadable_manifest_payload(
    *,
    paths: ProjectPaths,
    path: Path,
    error: str,
) -> dict[str, Any]:
    return {
        "manifest_version": MODEL_STATE_MANIFEST_VERSION,
        "manifest_readable": False,
        "generated_at_utc": None,
        "parent_refresh_id": None,
        "build_kind": "full_model",
        "state": "incomplete",
        "publish": {
            "atomic_pointer": True,
            "path": _repo_relative(paths, path),
            "latest_aliases_authoritative": False,
        },
        "artifacts": {},
        "alignment": {"status": "WARN", "warnings": []},
        "read_error": error,
        "warnings": [error],
        "stage_timings": {},
    }


def _existing_path_or_none(path: Path | None) -> Path | None:
    return path if path is not None and path.exists() else None


def _snapshot_json_artifact(
    *,
    paths: ProjectPaths,
    artifact: dict[str, Any],
    source_path: Path,
    file_prefix: str,
    stamp: str | None,
) -> None:
    if not artifact.get("usable") or not stamp:
        return
    target = paths.intermediate_status_dir / f"{file_prefix}_{_safe_file_fragment(stamp)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _atomic_write_bytes(target, source_path.read_bytes())
        artifact["source_alias_path"] = _repo_relative(paths, source_path)
        artifact["path"] = _repo_relative(paths, target)
        artifact["immutable"] = True
        _refresh_file_metadata(artifact, target)
    except Exception as exc:
        artifact["read_error"] = str(exc)
        artifact["usable"] = False
        artifact["readable"] = False


def _resolve_run_stamped_parquet(
    *,
    paths: ProjectPaths,
    name: str,
    source_run_ids: list[str],
) -> Path | None:
    return _resolve_run_stamped_artifact(
        paths=paths,
        name=name,
        source_run_ids=source_run_ids,
        suffix=".parquet",
    )


def _resolve_run_stamped_artifact(
    *,
    paths: ProjectPaths,
    name: str,
    source_run_ids: list[str],
    suffix: str,
) -> Path | None:
    directory, prefix = _tool_latest_directory_and_prefix(paths, name)
    for run_id in source_run_ids:
        candidate = directory / f"{prefix}_latest_{_safe_file_fragment(run_id)}{suffix}"
        if _is_run_stamped_tool_latest(candidate, prefix, suffix=suffix):
            return candidate
    return None


def _resolve_run_stamped_artifact_by_alias_hash(
    *,
    paths: ProjectPaths,
    name: str,
    alias_path: Path,
    suffix: str,
) -> Path | None:
    if not alias_path.exists() or not alias_path.is_file():
        return None
    try:
        alias_hash = _sha256_file(alias_path)
    except Exception:
        return None
    directory, prefix = _tool_latest_directory_and_prefix(paths, name)
    for candidate in sorted(directory.glob(f"{prefix}_latest_*{suffix}"), reverse=True):
        if not _is_run_stamped_tool_latest(candidate, prefix, suffix=suffix):
            continue
        try:
            if _sha256_file(candidate) == alias_hash:
                return candidate
        except Exception:
            continue
    return None


def _resolve_tool_a_structural_metrics_path(
    *,
    paths: ProjectPaths,
    source_run_ids: list[str],
) -> Path | None:
    for run_id in source_run_ids:
        candidate = (
            paths.intermediate_tool_a_structural_dir
            / f"tool_a_structural_{_safe_file_fragment(run_id)}.parquet"
        )
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _tool_latest_directory_and_prefix(paths: ProjectPaths, name: str) -> tuple[Path, str]:
    if name == "tool_a":
        return paths.output_tool_a_dir, "tool_a"
    if name == "tool_b":
        return paths.output_tool_b_dir, "tool_b"
    if name == "tool_c":
        return paths.output_tool_c_dir, "tool_c"
    if name in {"tool_d", "tool_d_spot"}:
        return paths.output_tool_d_dir, "tool_d"
    if name == FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME:
        return paths.output_fundamentals_dir, FETCHED_FUNDAMENTALS_PREFIX
    if name in OPTION_ARTIFACT_PREFIXES:
        return paths.output_options_dir, OPTION_ARTIFACT_PREFIXES[name]
    if name in TICKER_PAGE_ARTIFACT_PREFIXES:
        return paths.output_ticker_page_dir, TICKER_PAGE_ARTIFACT_PREFIXES[name]
    if name in PORTFOLIO_ARTIFACTS:
        return paths.output_portfolio_dir, name
    if name == "portfolio_reconciliation_export_csv":
        return paths.output_portfolio_dir, "portfolio_reconciliation_export"
    raise ValueError(f"Unsupported model artifact for immutable lookup: {name}")


def _is_run_stamped_tool_latest(candidate: Path, prefix: str, *, suffix: str) -> bool:
    return (
        candidate.exists()
        and candidate.is_file()
        and _has_run_stamped_tool_latest_name(candidate.name, prefix, suffix=suffix)
    )


def _has_run_stamped_tool_latest_name(file_name: str, prefix: str, *, suffix: str) -> bool:
    pattern = rf"^{re.escape(prefix)}_latest_\d{{8}}T\d{{6}}Z-.+{re.escape(suffix)}$"
    return re.match(pattern, file_name) is not None


def _refresh_file_metadata(artifact: dict[str, Any], path: Path) -> None:
    stat = path.stat()
    artifact.update(
        {
            "sha256": _sha256_file(path),
            "modified_at_utc": _mtime_iso(path),
            "size_bytes": stat.st_size,
            "readable": True,
            "usable": True,
        }
    )


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_state_snapshot_path(paths: ProjectPaths, payload: dict[str, Any]) -> Path:
    stamp = (
        _clean_string(payload.get("parent_refresh_id"))
        or _clean_string(payload.get("generated_at_utc"))
        or "unknown"
    )
    return paths.model_state_manifests_dir / f"model_state_{_safe_file_fragment(stamp)}.json"
