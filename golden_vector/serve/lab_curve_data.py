"""Read-only loader for the multi-horizon / multi-benchmark Lab artifacts.

Serve renders; the lab package computes. This module reads the persisted
``dial_cells_latest.parquet`` (wide overview) and ``dial_episodes_latest.parquet``
(long-form chart detail) by direct path (the Lab lives outside the model-state
manifest), with three distinct failure states a decision surface must not blur:

- MISSING  -> not built yet (run the builder)
- CORRUPT  -> built but unreadable (rebuild / investigate)
- STALE    -> built by an older schema or without the configured horizons /
              benchmarks (rebuild to refresh shape)

No arithmetic, no rank decisions: every number + the rank order come from the
artifact. This module only filters by (ticker / scenario / horizon / benchmark)
and validates inputs against the configured set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.features.weekly_returns import BENCHMARK_COLUMN_MAP
from golden_vector.lab.conditional_dial import (
    BUCKET_LABELS,
    CELLS_COLUMNS,
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_BENCHMARKS,
    DIAL_CELLS_FILENAME,
    DIAL_EPISODES_FILENAME,
    DIAL_HORIZONS_WEEKS,
    DIAL_RELSTRENGTH_FILENAME,
    DIAL_SCHEMA_VERSION,
    RELSTRENGTH_COLUMNS,
    dial_config_hash,
)
from golden_vector.lab.vintages import lab_dir

_EPISODE_REQUIRED = [
    "ticker",
    "horizon_weeks",
    "benchmark",
    "week_date",
    "gold_bucket",
    "alpha",
    "beat",
    "is_nonoverlap_anchor",
]


@dataclass(frozen=True)
class LabCellsData:
    """Wide overview rows for one (horizon, bucket)."""

    available: bool
    horizon: int = 13
    horizons: list[int] = field(default_factory=list)
    buckets: list[tuple[str, str]] = field(default_factory=list)
    bucket_availability: dict[str, dict[str, int]] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    error_status: str | None = None


@dataclass(frozen=True)
class LabCurveData:
    """Per-(ticker, scenario, horizon, benchmark) chart detail + matching cell."""

    available: bool
    ticker: str = ""
    benchmark: str = "GDX"
    horizon: int = 13
    scenario_bucket: str = ""
    scenario_label: str = ""
    points: list[dict[str, Any]] = field(default_factory=list)
    relstrength_points: list[dict[str, Any]] = field(default_factory=list)
    # Chart B's own artifact health: None = ok (it may still be empty for a thin
    # ticker), "MISSING"/"CORRUPT" = the relstrength artifact itself is bad.
    relstrength_status: str | None = None
    cell: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    error_status: str | None = None


def _read_meta(paths: ProjectPaths) -> dict[str, Any]:
    meta_path = lab_dir(paths) / DIAL_ARTIFACT_META_FILENAME
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _load_frame(
    paths: ProjectPaths,
    *,
    filename: str,
    required_columns: list[str],
) -> tuple[pd.DataFrame | None, str | None]:
    """Return (frame, error_status). error_status is one of MISSING/CORRUPT/STALE."""

    path = lab_dir(paths) / filename
    if not path.exists():
        return None, "MISSING"
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None, "CORRUPT"
    if frame.empty:
        return None, "MISSING"
    if any(column not in frame.columns for column in required_columns):
        # Built by an older shape (missing the multi-horizon/benchmark columns).
        return None, "STALE"
    return frame, None


def _schema_is_current(meta: dict[str, Any]) -> bool:
    return int(meta.get("schema_version") or 0) == DIAL_SCHEMA_VERSION


def _config_is_current(meta: dict[str, Any]) -> bool:
    """The artifact's config_hash must match the LIVE config — computed from the
    live ``DIAL_HORIZONS_WEEKS`` / ``DIAL_BENCHMARKS`` (and buckets / floors), NOT
    from the artifact's own stored lists. Hashing the stored lists back against
    themselves would miss a live horizon/benchmark change (Codex MED): the
    workspace "current" reader must fail closed when the live dial config drifts."""

    expected = dial_config_hash(DIAL_HORIZONS_WEEKS, DIAL_BENCHMARKS)
    return str(meta.get("config_hash") or "") == expected


def _artifact_is_current(meta: dict[str, Any]) -> bool:
    return _schema_is_current(meta) and _config_is_current(meta)


def configured_benchmarks(meta: dict[str, Any]) -> list[str]:
    raw = meta.get("benchmarks") or DIAL_BENCHMARKS
    return [str(b).upper() for b in raw]


def load_dial_cells(
    paths: ProjectPaths,
    *,
    horizon: int = 13,
    bucket: str | None = None,
) -> LabCellsData:
    """Wide overview rows for one (horizon, bucket), GDX-ranked."""

    meta = _read_meta(paths)
    frame, status = _load_frame(
        paths, filename=DIAL_CELLS_FILENAME, required_columns=CELLS_COLUMNS
    )
    if frame is None:
        return LabCellsData(available=False, error_status=status)
    if not _artifact_is_current(meta):
        return LabCellsData(available=False, error_status="STALE")

    horizons = sorted({int(h) for h in frame["horizon_weeks"].dropna().tolist()})
    selected_horizon = int(horizon) if int(horizon) in horizons else (horizons[0] if horizons else int(horizon))
    horizon_frame = frame.loc[frame["horizon_weeks"] == selected_horizon]

    bucket_pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for record in horizon_frame[["bucket", "bucket_label"]].to_dict(orient="records"):
        key = str(record["bucket"])
        if key not in seen:
            seen.add(key)
            bucket_pairs.append((key, str(record["bucket_label"])))
    # Stable display order: follow the configured bucket order, not row order.
    order = {name: i for i, name in enumerate(BUCKET_LABELS)}
    bucket_pairs.sort(key=lambda pair: order.get(pair[0], len(order)))

    # Per-(horizon, bucket) availability (how many GDX cells carry numbers) drives
    # the selector labels + the empty-state contract. Counted in the BUILD and
    # read from meta — serve never aggregates.
    availability: dict[str, dict[str, int]] = {
        str(hz): {str(bkt): int(count) for bkt, count in per.items()}
        for hz, per in (meta.get("usable_gdx_cells_by_horizon_bucket") or {}).items()
    }

    selected_bucket = bucket if (bucket in seen) else (bucket_pairs[0][0] if bucket_pairs else None)
    rows: list[dict[str, Any]] = []
    if selected_bucket is not None:
        view = horizon_frame.loc[horizon_frame["bucket"] == selected_bucket]
        view = view.sort_values("rank_in_bucket", na_position="last")
        rows = view.to_dict(orient="records")

    return LabCellsData(
        available=True,
        horizon=selected_horizon,
        horizons=horizons,
        buckets=bucket_pairs,
        bucket_availability=availability,
        rows=rows,
        meta=meta,
    )


def load_ticker_curve(
    paths: ProjectPaths,
    *,
    ticker: str,
    scenario_bucket: str,
    horizon: int = 13,
    benchmark: str = "GDX",
) -> LabCurveData:
    """Per-week forward-alpha points + the matching wide cell for the drill-down."""

    bench = str(benchmark).upper()
    if bench not in BENCHMARK_COLUMN_MAP:
        return LabCurveData(available=False, error_status="MISSING")

    meta = _read_meta(paths)
    if meta and bench not in configured_benchmarks(meta):
        return LabCurveData(available=False, error_status="STALE")

    episodes, status = _load_frame(
        paths, filename=DIAL_EPISODES_FILENAME, required_columns=_EPISODE_REQUIRED
    )
    if episodes is None:
        return LabCurveData(available=False, error_status=status)
    if not _artifact_is_current(meta):
        return LabCurveData(available=False, error_status="STALE")

    ticker_u = str(ticker).upper()
    horizon_i = int(horizon)
    selected = episodes.loc[
        (episodes["ticker"].astype(str).str.upper() == ticker_u)
        & (episodes["horizon_weeks"] == horizon_i)
        & (episodes["benchmark"].astype(str).str.upper() == bench)
    ].sort_values("week_date")

    points: list[dict[str, Any]] = []
    for record in selected.to_dict(orient="records"):
        bucket_value = str(record.get("gold_bucket") or "")
        points.append(
            {
                "date": str(record.get("week_date") or ""),
                "alpha": record.get("alpha"),
                "beat": bool(record.get("beat")),
                "is_scenario": bucket_value == str(scenario_bucket),
                "is_anchor": bool(record.get("is_nonoverlap_anchor")),
            }
        )

    cell = _matching_cell(paths, ticker=ticker_u, bucket=str(scenario_bucket), horizon=horizon_i)
    relstrength_points, relstrength_status = _relstrength_points(
        paths, ticker=ticker_u, benchmark=bench
    )
    return LabCurveData(
        available=bool(points) or cell is not None,
        ticker=ticker_u,
        benchmark=bench,
        horizon=horizon_i,
        scenario_bucket=str(scenario_bucket),
        scenario_label=str(BUCKET_LABELS.get(str(scenario_bucket), scenario_bucket)),
        points=points,
        relstrength_points=relstrength_points,
        relstrength_status=relstrength_status,
        cell=cell,
        meta=meta,
        error_status=None if (points or cell is not None) else "MISSING",
    )


def _relstrength_points(
    paths: ProjectPaths,
    *,
    ticker: str,
    benchmark: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Weekly relative-strength line points for (ticker, benchmark) — Chart B.

    Returns (points, status). status distinguishes an artifact-level problem
    (MISSING/CORRUPT) from a healthy-but-empty result for a thin ticker, so the
    page can fail loud on a bad artifact instead of silently showing blank."""

    frame, status = _load_frame(
        paths, filename=DIAL_RELSTRENGTH_FILENAME, required_columns=RELSTRENGTH_COLUMNS
    )
    if frame is None:
        return [], status
    view = frame.loc[
        (frame["ticker"].astype(str).str.upper() == str(ticker).upper())
        & (frame["benchmark"].astype(str).str.upper() == str(benchmark).upper())
    ].sort_values("week_date")
    points = [
        {"date": str(record.get("week_date") or ""), "relstrength": record.get("relstrength")}
        for record in view.to_dict(orient="records")
    ]
    return points, None


def _matching_cell(
    paths: ProjectPaths,
    *,
    ticker: str,
    bucket: str,
    horizon: int,
) -> dict[str, Any] | None:
    frame, status = _load_frame(
        paths, filename=DIAL_CELLS_FILENAME, required_columns=CELLS_COLUMNS
    )
    if frame is None:
        return None
    view = frame.loc[
        (frame["ticker"].astype(str).str.upper() == str(ticker).upper())
        & (frame["bucket"] == bucket)
        & (frame["horizon_weeks"] == int(horizon))
    ]
    if view.empty:
        return None
    return view.iloc[0].to_dict()
