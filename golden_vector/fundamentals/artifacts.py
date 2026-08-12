"""Read and write official fundamentals artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from golden_vector.app.model_state import resolve_current_model_artifact_path
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.parquet import read_required_parquet, write_parquet_atomic
from golden_vector.contracts.fundamentals import (
    FETCHED_FUNDAMENTALS_COLUMNS,
    FETCHED_FUNDAMENTALS_SCHEMA_VERSION,
    FUNDAMENTAL_VALUE_STATUSES,
    FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
    fetched_fundamentals_latest_path,
    fetched_fundamentals_run_stamped_path,
)
from golden_vector.screening.manual_store import FINANCIAL_DUAL_SOURCE_FIELDS

FETCHED_FUNDAMENTALS_V1_COMPAT_COLUMNS = tuple(
    column
    for column in FETCHED_FUNDAMENTALS_COLUMNS
    if column not in {"period_type", "value_origin", "calculation_formula", "components_json"}
)


@dataclass(frozen=True)
class FetchedFundamentalsArtifactWrite:
    run_path: str
    latest_path: str | None
    row_count: int


def write_fetched_fundamentals_artifact_pair(
    *,
    paths: ProjectPaths,
    frame: pd.DataFrame,
    source_run_id: str,
    publish_latest_alias: bool = True,
) -> FetchedFundamentalsArtifactWrite:
    """Write immutable + latest official fundamentals artifacts."""

    normalized = normalize_fetched_fundamentals_frame(
        frame,
        source_run_id=source_run_id,
    )
    run_path = fetched_fundamentals_run_stamped_path(paths, source_run_id)
    latest_path = fetched_fundamentals_latest_path(paths)
    write_parquet_atomic(normalized, run_path, index=False)
    if publish_latest_alias:
        write_parquet_atomic(normalized, latest_path, index=False)
    return FetchedFundamentalsArtifactWrite(
        run_path=run_path.as_posix(),
        latest_path=latest_path.as_posix() if publish_latest_alias else None,
        row_count=int(len(normalized.index)),
    )


def load_official_fundamentals(
    paths: ProjectPaths,
    *,
    prefer_latest_alias: bool = False,
) -> pd.DataFrame:
    """Load the official fundamentals artifact, if present.

    Normally resolves through the model-state manifest (the published current state).
    During a ``refresh`` the manifest still points at the PREVIOUS run until the end-of-run
    promote, so the Tool B build passes ``prefer_latest_alias=True`` to read the latest
    fetched alias the refresh's fundamentals step just wrote — the same bypass-the-stale-
    manifest pattern Tool B already uses for the foundation."""

    frame, _source_path = load_official_fundamentals_with_source_path(
        paths,
        prefer_latest_alias=prefer_latest_alias,
    )
    return frame


def load_official_fundamentals_with_source_path(
    paths: ProjectPaths,
    *,
    prefer_latest_alias: bool = False,
    require_immutable_source: bool = False,
) -> tuple[pd.DataFrame, Path | None]:
    """Load official fundamentals and report the immutable artifact actually read.

    Tool D snapshots every upstream used by a generation for replay. Returning
    the run-stamped path with the frame prevents a mutable latest alias from
    changing between computation and replay capture. Callers that require
    auditable provenance set ``require_immutable_source=True``; legacy callers
    may still consume an alias only when no matching immutable sibling exists.
    """

    alias_path = fetched_fundamentals_latest_path(paths)
    if prefer_latest_alias and alias_path.exists():
        try:
            alias_frame = _read_official_fundamentals_path(alias_path)
        except Exception:
            # The refresh bypass should use this run's fresh alias only when it is actually
            # readable. If the stale/missing guard was triggered by a corrupt alias and the
            # optional fetch failed or was publish-blocked, fall back to the last published
            # manifest artifact instead of aborting Tool B on optional fundamentals data.
            path = resolve_current_model_artifact_path(
                paths,
                FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
                fallback_path=None,
            )
            if path is None:
                return empty_fetched_fundamentals_frame(), None
            return _load_official_fundamentals_from_provenance_path(
                paths=paths,
                frame=_read_official_fundamentals_path(path),
                path=path,
                require_immutable_source=require_immutable_source,
            )
        return _load_official_fundamentals_from_provenance_path(
            paths=paths,
            frame=alias_frame,
            path=alias_path,
            require_immutable_source=require_immutable_source,
        )

    path = resolve_current_model_artifact_path(
        paths,
        FUNDAMENTALS_OFFICIAL_ARTIFACT_NAME,
        fallback_path=alias_path,
    )
    if path is None:
        return empty_fetched_fundamentals_frame(), None
    return _load_official_fundamentals_from_provenance_path(
        paths=paths,
        frame=_read_official_fundamentals_path(path),
        path=path,
        require_immutable_source=require_immutable_source,
    )


def _load_official_fundamentals_from_provenance_path(
    *,
    paths: ProjectPaths,
    frame: pd.DataFrame,
    path: Path,
    require_immutable_source: bool,
) -> tuple[pd.DataFrame, Path]:
    source_run_id = _source_run_id_from_frame(frame)
    immutable_path = fetched_fundamentals_run_stamped_path(paths, source_run_id)
    if path == immutable_path:
        return frame, immutable_path
    if not immutable_path.exists():
        if require_immutable_source:
            raise FileNotFoundError(
                "official fundamentals alias names source_run_id "
                f"{source_run_id!r}, but immutable artifact {immutable_path} is missing"
            )
        return frame, path

    immutable_frame = _read_official_fundamentals_path(immutable_path)
    try:
        pd.testing.assert_frame_equal(frame, immutable_frame)
    except AssertionError as exc:
        if require_immutable_source:
            raise ValueError(
                "official fundamentals alias does not match its immutable "
                f"source_run_id generation {source_run_id!r}"
            ) from exc
        return frame, path
    return immutable_frame, immutable_path


def _read_official_fundamentals_path(path: Path) -> pd.DataFrame:
    frame = read_required_parquet(
        path,
        label="official fundamentals",
        required_columns=FETCHED_FUNDAMENTALS_V1_COMPAT_COLUMNS,
    )
    return normalize_fetched_fundamentals_frame(
        frame,
        source_run_id=_source_run_id_from_frame(frame),
    )


def normalize_fetched_fundamentals_frame(
    frame: pd.DataFrame,
    *,
    source_run_id: str,
) -> pd.DataFrame:
    """Normalize and validate the canonical official fundamentals frame."""

    source_run_id = str(source_run_id or "").strip()
    if not source_run_id:
        raise ValueError("official fundamentals source_run_id is required")
    normalized = frame.copy()
    period_type_missing = "period_type" not in normalized.columns
    for column in FETCHED_FUNDAMENTALS_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA
    normalized["schema_version"] = FETCHED_FUNDAMENTALS_SCHEMA_VERSION
    normalized["source_run_id"] = source_run_id
    normalized["ticker"] = normalized["ticker"].fillna("").astype(str).str.upper().str.strip()
    normalized["field_name"] = normalized["field_name"].fillna("").astype(str).str.strip()
    normalized["value"] = pd.to_numeric(normalized["value"], errors="coerce")
    normalized["value_status"] = (
        normalized["value_status"].fillna("MISSING").astype(str).str.upper().str.strip()
    )
    normalized["source"] = normalized["source"].fillna("YAHOO").astype(str).str.upper().str.strip()
    for column in (
        "fetched_at_utc",
        "statement_period",
        "period_end",
        "period_type",
        "statement_currency",
        "statement_scale",
        "value_origin",
        "calculation_formula",
        "components_json",
    ):
        normalized[column] = normalized[column].astype("object").where(
            normalized[column].notna(),
            None,
        )
    if period_type_missing:
        normalized["period_type"] = "ANNUAL"
    normalized = normalized[normalized["ticker"] != ""].copy()
    normalized = normalized[normalized["field_name"] != ""].copy()
    normalized = normalized.drop_duplicates(
        subset=["ticker", "field_name"],
        keep="last",
    )
    normalized = normalized[list(FETCHED_FUNDAMENTALS_COLUMNS)].reset_index(drop=True)
    normalized.attrs["schema_version"] = FETCHED_FUNDAMENTALS_SCHEMA_VERSION
    normalized.attrs["source_run_id"] = source_run_id
    return validate_fetched_fundamentals_frame(normalized)


def validate_fetched_fundamentals_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate official fundamentals values against the shared contract."""

    missing_columns = [
        column for column in FETCHED_FUNDAMENTALS_COLUMNS if column not in frame.columns
    ]
    if missing_columns:
        raise ValueError(
            "official fundamentals artifact is missing columns: "
            + ", ".join(missing_columns)
        )
    invalid_fields = sorted(set(frame["field_name"].dropna()) - FINANCIAL_DUAL_SOURCE_FIELDS)
    if invalid_fields:
        raise ValueError(
            "official fundamentals may only contain financial dual-source fields; "
            f"invalid fields: {', '.join(invalid_fields)}"
        )
    invalid_statuses = sorted(
        set(frame["value_status"].dropna().astype(str)) - set(FUNDAMENTAL_VALUE_STATUSES)
    )
    if invalid_statuses:
        raise ValueError(
            "official fundamentals artifact contains unsupported value_status values: "
            + ", ".join(invalid_statuses)
        )
    return frame.copy()


def empty_fetched_fundamentals_frame() -> pd.DataFrame:
    """Return an empty official fundamentals frame with the canonical columns."""

    frame = pd.DataFrame(columns=FETCHED_FUNDAMENTALS_COLUMNS)
    frame.attrs["schema_version"] = FETCHED_FUNDAMENTALS_SCHEMA_VERSION
    return frame


def _source_run_id_from_frame(frame: pd.DataFrame) -> str:
    if "source_run_id" in frame.columns:
        values = frame["source_run_id"].dropna().astype(str).str.strip()
        if not values.empty and values.iloc[0]:
            return values.iloc[0]
    attr_value = str(frame.attrs.get("source_run_id") or "").strip()
    if attr_value:
        return attr_value
    raise ValueError("official fundamentals source_run_id is required")
