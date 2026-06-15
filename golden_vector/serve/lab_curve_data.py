"""Read-only loader for the multi-horizon / multi-benchmark Lab artifacts.

Serve renders; the lab package computes. This module reads the persisted
``dial_cells_latest.parquet`` (wide overview) and ``dial_episodes_latest.parquet``
(long-form chart detail) by direct path (the Lab lives outside the model-state
manifest), with three distinct failure states a decision surface must not blur:

- MISSING  -> not built yet (run the builder)
- CORRUPT  -> built but unreadable (rebuild / investigate)
- STALE    -> built by an older schema or without the configured horizons /
              benchmarks (rebuild to refresh shape)

No model aggregation, shrinkage, ratio, or rank decisions: every published number
+ the rank order come from the artifact. This module filters by (ticker / scenario /
horizon / benchmark), validates inputs against the configured set, and does only
display-only counts (e.g. usable down/up buckets) over already-resolved rows.
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
    DEFAULT_DIAL_BUCKET,
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_BENCHMARKS,
    DIAL_CELLS_FILENAME,
    DIAL_EPISODES_FILENAME,
    DIAL_HORIZONS_WEEKS,
    DIAL_PROFILE_FILENAME,
    DIAL_RELSTRENGTH_FILENAME,
    DIAL_SCHEMA_VERSION,
    DOWN_BUCKETS,
    PROFILE_COLUMNS,
    RELSTRENGTH_COLUMNS,
    UP_BUCKETS,
    cell_bucket_is_usable,
    default_gold_profile_config,
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
    "alpha_simple",
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
    # The bucket actually loaded (requested-if-known -> default -> first). ONE
    # resolver feeds both the rows and the page's dropdown/banner label.
    selected_bucket: str = ""
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
    # The miner's behaviour across ALL gold scenarios at the selected horizon
    # (P(beat) per bucket, gaps where insufficient) — the gold-profile hero.
    profile_points: list[dict[str, Any]] = field(default_factory=list)
    # STRUCTURAL coverage counts (how many usable down / up scenarios by the gold
    # bounds) — for the CHART's slope wording. Derived via the shared
    # cell_bucket_is_usable rule (one copy with the build).
    profile_usable_down: int = 0
    profile_usable_up: int = 0
    # The TILT-PARTITION counts the build actually computed gold_tilt over (the
    # config's down/up buckets) — read straight from the persisted artifact and
    # shown as the label's coverage basis, so the basis can never disagree with the
    # partition the tilt was averaged over even if the config buckets are edited.
    profile_basis_down: int = 0
    profile_basis_up: int = 0
    # The auto gold-tilt characterization (v2) — ALL build-computed and read from
    # dial_profile; serve only chooses display text from label + status, never
    # re-derives the tilt or re-decides the threshold. status "UNAVAILABLE" means
    # the profile artifact is absent/stale (label degrades; the chart still shows).
    profile_label: str | None = None
    profile_label_status: str = "UNAVAILABLE"
    profile_tilt: float | None = None
    profile_down_mean: float | None = None
    profile_up_mean: float | None = None
    profile_tilt_threshold: float | None = None
    profile_used_buckets: str = ""
    profile_caveat: str = ""
    cell: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    error_status: str | None = None


def _read_meta(paths: ProjectPaths) -> tuple[dict[str, Any], str | None]:
    """Return (meta, meta_status). meta_status is None (ok), "MISSING" (no file),
    or "CORRUPT" (unreadable) — so a bad meta beside intact cells is reported as a
    metadata problem, not falsely as 'data missing the multi-horizon columns'."""

    meta_path = lab_dir(paths) / DIAL_ARTIFACT_META_FILENAME
    if not meta_path.exists():
        return {}, "MISSING"
    try:
        return json.loads(meta_path.read_text(encoding="utf-8")), None
    except (json.JSONDecodeError, OSError):
        return {}, "CORRUPT"


def _current_artifact_filename(meta: dict[str, Any], key: str, latest_filename: str) -> str:
    """Resolve to the IMMUTABLE run-stamped file named by the published meta — the
    atomic current-state pointer — falling back to the mutable ``*_latest`` alias only
    when meta has no run_stamped entry (pre-manifest artifacts / hand-written test
    fixtures).

    Why: ``dial_meta.json`` is published (atomically) AFTER all run-stamped + latest
    files are written. Resolving reads through the meta's run_stamped_artifacts means a
    half-finished rebuild (new latest aliases on disk, meta not yet replaced) is read as
    the LAST COHERENT set named by the still-old meta — never a torn mix of new+old
    latest frames. One manifest pointer defines the current artifact set.
    """

    stamped = (meta.get("run_stamped_artifacts") or {}).get(key)
    return str(stamped) if stamped else latest_filename


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
        # Built + readable, but zero rows (e.g. empty universe) — distinct from
        # "not built yet" so the page doesn't tell the operator to run a build
        # that already ran.
        return None, "EMPTY"
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


def default_lab_horizon() -> int:
    """The default look-ahead horizon for the Lab routes, sourced from the live
    gold-profile config (``default_profile_horizon``) — one config-driven knob, not a
    hardcoded ``13`` duplicated in each route. The loader still resolves an unbuilt
    horizon gracefully, so a misconfigured value degrades rather than breaks."""

    return int(default_gold_profile_config().default_profile_horizon)


def load_dial_cells(
    paths: ProjectPaths,
    *,
    horizon: int = 13,
    bucket: str | None = None,
) -> LabCellsData:
    """Wide overview rows for one (horizon, bucket), GDX-ranked."""

    meta, meta_status = _read_meta(paths)
    frame, status = _load_frame(
        paths,
        filename=_current_artifact_filename(meta, "cells", DIAL_CELLS_FILENAME),
        required_columns=CELLS_COLUMNS,
    )
    if frame is None:
        return LabCellsData(available=False, error_status=status)
    if meta_status is not None:
        # Cells are intact but the metadata is missing/unreadable — a metadata
        # problem, not a stale-shape one.
        return LabCellsData(available=False, error_status="META_" + meta_status)
    if not _artifact_is_current(meta):
        return LabCellsData(available=False, error_status="STALE")

    horizons = sorted({int(h) for h in frame["horizon_weeks"].dropna().tolist()})
    selected_horizon = _select_horizon(horizons, int(horizon))
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
    # read from meta — serve does no model aggregation.
    availability: dict[str, dict[str, int]] = {
        str(hz): {str(bkt): int(count) for bkt, count in per.items()}
        for hz, per in (meta.get("usable_gdx_cells_by_horizon_bucket") or {}).items()
    }

    selected_bucket = _select_bucket(bucket, seen, bucket_pairs)
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
        selected_bucket=str(selected_bucket or ""),
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
    # Validate the requested scenario against the configured buckets up front, so a
    # mistyped ?scenario= reads as "unknown scenario" rather than masquerading as
    # "not enough history" (no matching cell -> blank win-rate bar + headline).
    if str(scenario_bucket) not in BUCKET_LABELS:
        return LabCurveData(
            available=False,
            ticker=str(ticker).upper(),
            benchmark=bench,
            horizon=int(horizon),
            scenario_bucket=str(scenario_bucket),
            error_status="UNKNOWN_SCENARIO",
        )

    meta, meta_status = _read_meta(paths)
    if meta and bench not in configured_benchmarks(meta):
        return LabCurveData(available=False, error_status="STALE")

    episodes, status = _load_frame(
        paths,
        filename=_current_artifact_filename(meta, "episodes", DIAL_EPISODES_FILENAME),
        required_columns=_EPISODE_REQUIRED,
    )
    if episodes is None:
        return LabCurveData(available=False, error_status=status)
    if meta_status is not None:
        # Intact episodes but missing/unreadable metadata — a metadata problem, not
        # a stale-shape one (mirror the overview loader's distinct diagnosis, so the
        # operator gets the right rebuild reason instead of a misleading STALE).
        return LabCurveData(available=False, error_status="META_" + meta_status)
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
                "alpha": record.get("alpha"),  # log gap: time-series dots + beat sign
                "alpha_simple": record.get("alpha_simple"),  # simple return: strip basis
                "beat": bool(record.get("beat")),
                "is_scenario": bucket_value == str(scenario_bucket),
                "is_anchor": bool(record.get("is_nonoverlap_anchor")),
            }
        )

    # Read dial_cells ONCE per request; feed both the matching cell and the
    # cross-scenario profile (avoids a triple read). The cells artifact drives the
    # profile hero, the win-rate bar AND the headline numbers, so a missing/corrupt/
    # stale/empty cells file (while episodes exist) is a broken build — fail loud
    # with a distinct status, never misreport it as "no cross-scenario history"
    # (which reads as an evidence gap, not an artifact gap).
    cells_frame, cells_status = _load_frame(
        paths,
        filename=_current_artifact_filename(meta, "cells", DIAL_CELLS_FILENAME),
        required_columns=CELLS_COLUMNS,
    )
    if cells_status is not None:
        return LabCurveData(
            available=False,
            ticker=ticker_u,
            benchmark=bench,
            horizon=horizon_i,
            scenario_bucket=str(scenario_bucket),
            scenario_label=str(BUCKET_LABELS.get(str(scenario_bucket), scenario_bucket)),
            error_status="CELLS_" + cells_status,
        )
    cell = _matching_cell(cells_frame, ticker=ticker_u, bucket=str(scenario_bucket), horizon=horizon_i)
    relstrength_points, relstrength_status = _relstrength_points(
        paths, ticker=ticker_u, benchmark=bench, meta=meta
    )
    profile_points, usable_down, usable_up = _ticker_profile(
        cells_frame, ticker=ticker_u, horizon=horizon_i, benchmark=bench
    )
    # The auto tilt-label (v2): a PURE READ of the build-computed dial_profile.
    # Optional enrichment — a missing/stale profile artifact degrades the label to
    # UNAVAILABLE (the chart still renders), it does not fail the page.
    profile_frame, _profile_status = _load_frame(
        paths,
        filename=_current_artifact_filename(meta, "profile", DIAL_PROFILE_FILENAME),
        required_columns=PROFILE_COLUMNS,
    )
    label = _ticker_profile_label(
        profile_frame, ticker=ticker_u, horizon=horizon_i, benchmark=bench
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
        profile_points=profile_points,
        profile_usable_down=usable_down,
        profile_usable_up=usable_up,
        profile_label=label.get("gold_tilt_label"),
        profile_label_status=str(label.get("label_status") or "UNAVAILABLE"),
        profile_tilt=label.get("gold_tilt"),
        profile_down_mean=label.get("down_mean_p_beat"),
        profile_up_mean=label.get("up_mean_p_beat"),
        profile_tilt_threshold=label.get("tilt_threshold"),
        profile_basis_down=int(label.get("usable_down_bucket_count") or 0),
        profile_basis_up=int(label.get("usable_up_bucket_count") or 0),
        profile_used_buckets=str(label.get("used_buckets") or ""),
        profile_caveat=str(label.get("caveat") or ""),
        cell=cell,
        meta=meta,
        error_status=None if (points or cell is not None) else "MISSING",
    )


def _ticker_profile(
    frame: pd.DataFrame | None,
    *,
    ticker: str,
    horizon: int,
    benchmark: str,
) -> tuple[list[dict[str, Any]], int, int]:
    """One row per gold scenario (down-big -> up-big) for this ticker/horizon: the
    benchmark's P(beat) etc., with a `usable` flag. Pure read of an already-loaded
    dial_cells frame — no aggregation; non-usable buckets render as honest gaps.
    Returns (points, usable_down_count, usable_up_count)."""

    if frame is None:
        return [], 0, 0
    b = str(benchmark).lower()
    view = frame.loc[
        (frame["ticker"].astype(str).str.upper() == str(ticker).upper())
        & (frame["horizon_weeks"] == int(horizon))
    ]
    by_bucket = {str(record["bucket"]): record for record in view.to_dict(orient="records")}
    points: list[dict[str, Any]] = []
    usable_down = 0
    usable_up = 0
    for bucket in BUCKET_LABELS:  # configured scenario order: most-down -> most-up
        row = by_bucket.get(bucket)
        shrunk = row.get(f"p_beat_{b}_shrunk") if row else None
        # ONE usability rule, shared with the build (no forked copy here).
        usable = cell_bucket_is_usable(row, benchmark)
        if usable and bucket in DOWN_BUCKETS:
            usable_down += 1
        elif usable and bucket in UP_BUCKETS:
            usable_up += 1
        points.append(
            {
                "bucket": bucket,
                "label": BUCKET_LABELS.get(bucket, bucket),
                "usable": usable,
                "p_beat_shrunk": shrunk if usable else None,
                "p_beat_raw": (row.get(f"p_beat_{b}") if usable else None),
                "median_alpha": (row.get(f"median_alpha_{b}") if usable else None),
                "effective_n": (row.get(f"{b}_effective_n") if row else None),
            }
        )
    return points, usable_down, usable_up


def _ticker_profile_label(
    frame: pd.DataFrame | None,
    *,
    ticker: str,
    horizon: int,
    benchmark: str,
) -> dict[str, Any]:
    """Pure read of the build-computed ``dial_profile`` row for this
    (ticker, horizon, benchmark): the tilt label, status, and basis fields.

    Returns an empty dict when the artifact is absent or has no matching row (the
    caller maps that to label_status "UNAVAILABLE"). NaN placeholders are normalised
    to real ``None`` so the renderer never prints a stray "nan"."""

    if frame is None:
        return {}
    view = frame.loc[
        (frame["ticker"].astype(str).str.upper() == str(ticker).upper())
        & (frame["horizon_weeks"] == int(horizon))
        & (frame["benchmark"].astype(str).str.upper() == str(benchmark).upper())
    ]
    if view.empty:
        return {}
    row = view.iloc[0].to_dict()
    return {
        key: (None if (value is None or (isinstance(value, float) and value != value)) else value)
        for key, value in row.items()
    }


def _relstrength_points(
    paths: ProjectPaths,
    *,
    ticker: str,
    benchmark: str,
    meta: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """Weekly relative-strength line points for (ticker, benchmark) — Chart B.

    Returns (points, status). status distinguishes an artifact-level problem
    (MISSING/CORRUPT) from a healthy-but-empty result for a thin ticker, so the
    page can fail loud on a bad artifact instead of silently showing blank."""

    if not _artifact_is_current(meta):
        return [], "STALE"
    frame, status = _load_frame(
        paths,
        filename=_current_artifact_filename(meta, "relstrength", DIAL_RELSTRENGTH_FILENAME),
        required_columns=RELSTRENGTH_COLUMNS,
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


def _select_horizon(horizons: list[int], requested: int) -> int:
    if requested in horizons:
        return requested
    if 13 in horizons:
        return 13
    return horizons[0] if horizons else requested


def _select_bucket(
    requested: str | None,
    known: set[str],
    bucket_pairs: list[tuple[str, str]],
) -> str | None:
    if requested in known:
        return requested
    if DEFAULT_DIAL_BUCKET in known:
        return DEFAULT_DIAL_BUCKET
    return bucket_pairs[0][0] if bucket_pairs else None


def _matching_cell(
    frame: pd.DataFrame | None,
    *,
    ticker: str,
    bucket: str,
    horizon: int,
) -> dict[str, Any] | None:
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
