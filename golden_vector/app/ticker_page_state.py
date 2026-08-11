"""Validated readers for the ticker-page artifacts (M1a stubs).

Each loader returns an explicit state object so a bad artifact renders a
degraded section with a reason and never a valid-looking empty section
(plan §5). M1a deliberately resolves only the latest-alias path: no caching and
no model-state manifest logic — both land with the producers in M1b.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.ticker_page import (
    GOLD_RESPONSE_COLUMNS,
    GOLD_RESPONSE_KEY_COLUMNS,
    PERCENTILES_COLUMNS,
    PERCENTILES_KEY_COLUMNS,
    PERFORMANCE_COLUMNS,
    PERFORMANCE_KEY_COLUMNS,
    RESEARCH_KINDS,
    RESEARCH_SERIES_COLUMNS,
    RESEARCH_SERIES_KEY_COLUMNS,
    RESEARCH_SERIES_KIND_KEY_COLUMNS,
    validate_frame_schema,
)

STATUS_MISSING = "MISSING"
STATUS_OK = "OK"
STATUS_STALE = "STALE"
STATUS_CORRUPT = "CORRUPT"


@dataclass(frozen=True)
class TickerPageArtifactState:
    """Resolved state of one ticker-page artifact."""

    status: str
    reason: str | None
    frame: pd.DataFrame


def _empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _load_artifact(
    path: Path,
    *,
    name: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    check_duplicate_keys: bool = True,
) -> TickerPageArtifactState:
    if not path.exists():
        return TickerPageArtifactState(
            status=STATUS_MISSING,
            reason=(
                f"{name} artifact has not been built yet (expected at {path}); "
                "it is produced by the ticker-page stage."
            ),
            frame=_empty_frame(columns),
        )
    try:
        frame = pd.read_parquet(path)
    except Exception as error:  # noqa: BLE001 - any read failure is CORRUPT
        return TickerPageArtifactState(
            status=STATUS_CORRUPT,
            reason=f"{name} artifact could not be read from {path}: {error}",
            frame=_empty_frame(columns),
        )

    violations = validate_frame_schema(
        frame,
        columns=columns,
        key_columns=key_columns if check_duplicate_keys else (),
        allow_extra=False,
    )
    if check_duplicate_keys is False:
        violations.extend(
            f"null values in key column {column}: {int(frame[column].isna().sum())} row(s)"
            for column in key_columns
            if column in frame.columns and int(frame[column].isna().sum())
        )
        violations.extend(
            f"missing key columns: {column}"
            for column in key_columns
            if column not in frame.columns
        )
    if violations:
        return TickerPageArtifactState(
            status=STATUS_CORRUPT,
            reason=f"{name} artifact failed schema validation: " + "; ".join(violations),
            frame=_empty_frame(columns),
        )
    return TickerPageArtifactState(status=STATUS_OK, reason=None, frame=frame)


def load_gold_response(paths: ProjectPaths) -> TickerPageArtifactState:
    return _load_artifact(
        paths.latest_ticker_page_gold_response_path,
        name="ticker_page_gold_response",
        columns=GOLD_RESPONSE_COLUMNS,
        key_columns=GOLD_RESPONSE_KEY_COLUMNS,
    )


def load_score_percentiles(paths: ProjectPaths) -> TickerPageArtifactState:
    return _load_artifact(
        paths.latest_ticker_page_percentiles_path,
        name="ticker_page_percentiles",
        columns=PERCENTILES_COLUMNS,
        key_columns=PERCENTILES_KEY_COLUMNS,
    )


def load_performance_series(paths: ProjectPaths) -> TickerPageArtifactState:
    return _load_artifact(
        paths.latest_ticker_page_performance_path,
        name="ticker_page_performance",
        columns=PERFORMANCE_COLUMNS,
        key_columns=PERFORMANCE_KEY_COLUMNS,
    )


def load_research_series(paths: ProjectPaths) -> TickerPageArtifactState:
    """Research series uniqueness is per row-kind (§5.6), not on (ticker, kind)."""
    state = _load_artifact(
        paths.latest_ticker_page_research_series_path,
        name="ticker_page_research_series",
        columns=RESEARCH_SERIES_COLUMNS,
        key_columns=RESEARCH_SERIES_KEY_COLUMNS,
        check_duplicate_keys=False,
    )
    if state.status != STATUS_OK:
        return state

    violations: list[str] = []
    for kind, kind_keys in RESEARCH_SERIES_KIND_KEY_COLUMNS.items():
        subset = state.frame[state.frame["kind"] == kind]
        if subset.empty:
            continue
        violations.extend(
            f"[kind={kind}] {message}"
            for message in validate_frame_schema(
                subset,
                columns=RESEARCH_SERIES_COLUMNS,
                key_columns=kind_keys,
                allow_extra=False,
            )
        )
    unknown_kinds = sorted(set(state.frame["kind"].dropna()) - set(RESEARCH_KINDS))
    if unknown_kinds:
        violations.append("unknown row kinds: " + ", ".join(unknown_kinds))
    if violations:
        return TickerPageArtifactState(
            status=STATUS_CORRUPT,
            reason=(
                "ticker_page_research_series artifact failed schema validation: "
                + "; ".join(violations)
            ),
            frame=_empty_frame(RESEARCH_SERIES_COLUMNS),
        )
    return state
