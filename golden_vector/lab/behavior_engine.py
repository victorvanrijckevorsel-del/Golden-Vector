"""Lab Capture & Behaviour engine — Phase 1: capture ratios + convexity + archetype.

Symmetric by construction. For each miner it measures how much of GOLD's move it
takes when gold FALLS (``down_capture``; low = good hedge) vs when gold RISES
(``up_capture``; high = good torque), and the ``convexity`` gap between them. The two
axes sort every miner into four honest archetypes — HEDGE / TORQUE / CONVEX / DEAD
WEIGHT.

Contract (matches the rest of the Lab):
- Reads the PERSISTED episode spine (``dial_episodes``); computes per (ticker,
  horizon); writes ``dial_capture``. No arithmetic in serve.
- Capture is the standard ratio-of-means (Morningstar up/down-capture). Bucket
  conditioning (|gold| >= 5%) keeps the denominator away from zero by construction.
- Capture is measured vs GOLD only (decision 2026-06-17) and is benchmark-independent,
  so it is computed on the GDX rows — the widest-coverage source of each miner's own
  forward return (GDXJ weeks are a subset).
- Each side carries its EFFECTIVE N (n_weeks / horizon) and abstains below the floor.
  The independent-anchor capture is a DIAGNOSTIC cross-check recorded as a confidence
  flag (confirmed / unconfirmed_disagrees / unconfirmed_thin_anchor), NOT a veto —
  overlap inflates variance, not bias, so the all-rows archetype (already overlap-
  deflated via effective N) ships, transparently flagged where the anchors disagree.
- Survivor-only universe (no dead-miner records yet) -> every capture reads
  optimistically; the caveat is stamped on the artifact and never sold as reassurance.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pandas as pd

from golden_vector.common.numeric import optional_finite_float
from golden_vector.contracts.config_models import CaptureBehaviorConfig
from golden_vector.lab.conditional_dial import (
    DEFAULT_BUCKETS,
    DIAL_EPISODES_FILENAME,
    DIAL_HORIZONS_WEEKS,
    DIAL_SCHEMA_VERSION,
    DOWN_BUCKETS,
    UP_BUCKETS,
)
from golden_vector.lab.walk_forward import effective_n

BEHAVIOR_SIGNAL_ID = "capture_behavior_engine"
BEHAVIOR_SCHEMA_VERSION = 1
CAPTURE_ARTIFACT = "dial_capture"
CAPTURE_FILENAME = "dial_capture_latest.parquet"
BEHAVIOR_META_FILENAME = "behavior_meta.json"
# Capture is the gold-frame, benchmark-independent lens; GDX rows are the widest
# source of the miner's own forward return (GDXJ weeks are a subset of GDX-era weeks).
CAPTURE_SOURCE_BENCHMARK = "GDX"

ARCHETYPES = ("CONVEX", "HEDGE", "TORQUE", "DEAD_WEIGHT")
CAPTURE_STATUSES = ("OK", "THIN_DOWN", "THIN_UP", "THIN_BOTH")
# How well the independent-anchor sample confirms the all-rows archetype (diagnostic,
# never a veto — see the demote note in compute_capture_table).
ARCHETYPE_CONFIDENCES = ("confirmed", "unconfirmed_disagrees", "unconfirmed_thin_anchor")
CAPTURE_CAVEAT = (
    "capture = mean(miner forward return) / mean(gold forward return) within the "
    "gold-down (resp. gold-up) buckets; counted history, survivor-only universe (no "
    "dead-miner records yet, so reads optimistically), exploratory — not a prediction."
)

CAPTURE_COLUMNS = [
    "schema_version",
    "behavior_config_hash",
    "ticker",
    "horizon_weeks",
    # down side (gold falling)
    "down_n_weeks",
    "down_effective_n",
    "down_stock_mean",
    "down_gold_mean",
    "down_capture_mean",
    "down_capture_median",
    "down_capture_anchor",
    "down_anchor_n",
    # up side (gold rising)
    "up_n_weeks",
    "up_effective_n",
    "up_stock_mean",
    "up_gold_mean",
    "up_capture_mean",
    "up_capture_median",
    "up_capture_anchor",
    "up_anchor_n",
    # synthesis
    "convexity",
    "archetype",
    "archetype_anchor",
    "archetype_anchor_agrees",
    "archetype_confidence",
    "capture_status",
    "caveat",
]


def default_capture_behavior_config() -> CaptureBehaviorConfig:
    """Load + validate ``config/lab_behavior_trend.yaml`` on EVERY call (uncached, like
    the gold-profile config): the serve staleness check recomputes the behavior hash
    through this, so a YAML edit must invalidate a stale artifact without a restart. A
    missing file falls back to the model defaults; a present-but-invalid file fails loud.
    """

    import yaml

    from golden_vector.app.paths import ProjectPaths

    try:
        config_path = ProjectPaths.discover().config_path("lab_behavior_trend.yaml")
    except Exception:
        return CaptureBehaviorConfig()
    if not config_path.exists():
        return CaptureBehaviorConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return CaptureBehaviorConfig.model_validate(raw)


def behavior_config_hash(
    config: CaptureBehaviorConfig,
    *,
    spine_schema_version: int = DIAL_SCHEMA_VERSION,
    buckets: list[tuple[str, float | None, float | None]] | None = None,
) -> str:
    """One stable hash over the behaviour config + the SPINE it is derived from.

    Separate from the raw ``dial_config_hash`` (Codex review #2): editing a capture/
    trend threshold invalidates only the behaviour artifacts, never the raw
    episode/cell/profile spine. It ALSO folds in ``spine_schema_version`` + the bucket
    bounds (Claude review #9): a spine rebuild / schema bump invalidates the derived
    artifact even when the behaviour thresholds are unchanged.
    """

    from golden_vector.lab.ledger import variant_hash

    bucket_defs = buckets if buckets is not None else DEFAULT_BUCKETS
    return variant_hash(
        BEHAVIOR_SIGNAL_ID,
        {
            "schema_version": BEHAVIOR_SCHEMA_VERSION,
            "spine_schema_version": int(spine_schema_version),
            "buckets": [[name, low, high] for name, low, high in bucket_defs],
            "config": config.model_dump(),
        },
    )


def _capture_side(frame: pd.DataFrame, *, horizon_weeks: int) -> dict[str, float | None]:
    """Capture stats for ONE direction (all of a miner's down- or up-bucket episodes).

    Ratio-of-means is the standard capture definition; the median ratio is a
    heavy-tail-robust companion. ``n_weeks`` / effective N count only VALID (non-NA)
    observations, so a side padded with NA returns never overstates its evidence at the
    floor gate. A non-finite or zero denominator (or no valid rows) -> ``None`` capture:
    an explicit abstain, never a NaN that would slip past the None-guards downstream and
    ship as a confident label.
    """

    stock = pd.to_numeric(frame["stock_fwd_simple"], errors="coerce")
    gold = pd.to_numeric(frame["gold_fwd_simple"], errors="coerce")
    both = stock.notna() & gold.notna()
    stock, gold = stock[both], gold[both]
    n = int(len(stock))
    out: dict[str, float | None] = {
        "n_weeks": n,
        "effective_n": effective_n(n, label_horizon_weeks=horizon_weeks) if n else 0.0,
        "stock_mean": None,
        "gold_mean": None,
        "capture_mean": None,
        "capture_median": None,
    }
    if n == 0:
        return out
    stock_mean = optional_finite_float(stock.mean())
    gold_mean = optional_finite_float(gold.mean())
    out["stock_mean"] = stock_mean
    out["gold_mean"] = gold_mean
    if stock_mean is not None and gold_mean not in (None, 0.0):
        out["capture_mean"] = stock_mean / gold_mean
    stock_median = optional_finite_float(stock.median())
    gold_median = optional_finite_float(gold.median())
    if stock_median is not None and gold_median not in (None, 0.0):
        out["capture_median"] = stock_median / gold_median
    return out


def _archetype(
    down_capture: float | None,
    up_capture: float | None,
    *,
    hedge_down_capture_max: float,
    torque_up_capture_min: float,
) -> str | None:
    """The four-box label from the two standard capture numbers + config cutoffs.

    Not a composite score: a 2-D classification. ``None`` if either side is unknown.
    """

    if down_capture is None or up_capture is None:
        return None
    hedgey = down_capture <= hedge_down_capture_max
    torquey = up_capture >= torque_up_capture_min
    if hedgey and torquey:
        return "CONVEX"
    if hedgey:
        return "HEDGE"
    if torquey:
        return "TORQUE"
    return "DEAD_WEIGHT"


def compute_capture_table(
    episodes: pd.DataFrame,
    *,
    horizons: list[int],
    config: CaptureBehaviorConfig,
    behavior_hash: str,
) -> pd.DataFrame:
    """One row per (ticker, horizon): symmetric capture + convexity + archetype.

    Capture is benchmark-independent, so it is computed on the GDX rows only (the
    widest-coverage source of the miner's own return); ``benchmark`` is dropped from
    the grain. The archetype abstains (INSUFFICIENT) when a side is below the
    effective-N floor OR when the independent-anchor capture disagrees with the
    all-rows archetype (overlap-robustness gate).
    """

    required = {
        "ticker",
        "horizon_weeks",
        "benchmark",
        "gold_bucket",
        "stock_fwd_simple",
        "gold_fwd_simple",
        "is_nonoverlap_anchor",
    }
    missing = required - set(episodes.columns)
    if missing:
        raise ValueError(
            f"dial_capture build needs episode columns {sorted(missing)} "
            "(rebuild the dial spine to schema v4)."
        )

    down_names = set(DOWN_BUCKETS)
    up_names = set(UP_BUCKETS)
    floor = float(config.min_direction_effective_n)
    base = episodes[
        episodes["benchmark"].astype(str).str.upper() == CAPTURE_SOURCE_BENCHMARK
    ]
    records: list[dict[str, object]] = []
    for horizon in horizons:
        h = int(horizon)
        hz = base[base["horizon_weeks"] == h]
        if hz.empty:
            continue
        for ticker, group in hz.groupby("ticker", sort=True):
            down = group[group["gold_bucket"].isin(down_names)]
            up = group[group["gold_bucket"].isin(up_names)]
            d = _capture_side(down, horizon_weeks=h)
            u = _capture_side(up, horizon_weeks=h)
            anchors = group["is_nonoverlap_anchor"].astype(bool)
            d_anc = _capture_side(down[anchors.loc[down.index]], horizon_weeks=h)
            u_anc = _capture_side(up[anchors.loc[up.index]], horizon_weeks=h)

            arch_all = _archetype(
                d["capture_mean"],
                u["capture_mean"],
                hedge_down_capture_max=config.hedge_down_capture_max,
                torque_up_capture_min=config.torque_up_capture_min,
            )
            arch_anc = _archetype(
                d_anc["capture_mean"],
                u_anc["capture_mean"],
                hedge_down_capture_max=config.hedge_down_capture_max,
                torque_up_capture_min=config.torque_up_capture_min,
            )
            agrees = (
                None if arch_anc is None or arch_all is None else (arch_anc == arch_all)
            )
            # Independent anchors available on BOTH sides. Anchors are >= h weeks
            # apart, so their COUNT already IS the independent-episode count — do NOT
            # deflate it again by the horizon.
            anchor_n = min(int(d_anc["n_weeks"] or 0), int(u_anc["n_weeks"] or 0))

            down_thin = float(d["effective_n"] or 0.0) < floor
            up_thin = float(u["effective_n"] or 0.0) < floor
            confidence: str | None = None
            if down_thin and up_thin:
                status, archetype = "THIN_BOTH", None
            elif down_thin:
                status, archetype = "THIN_DOWN", None
            elif up_thin:
                status, archetype = "THIN_UP", None
            else:
                # The all-rows capture IS the archetype — its effective_n already
                # deflates for overlap (overlap inflates VARIANCE, not bias). The
                # independent-anchor capture is a DIAGNOSTIC cross-check, NOT a veto:
                # a tercile-boundary disagreement between two small samples is
                # ambiguity, not corruption. (Phase-1 review HIGH: a hard abstain here
                # blanked well-powered cells; demoted to a confidence flag.)
                status, archetype = "OK", arch_all
                if anchor_n < int(config.min_anchor_episodes) or arch_anc is None:
                    confidence = "unconfirmed_thin_anchor"
                elif agrees:
                    confidence = "confirmed"
                else:
                    confidence = "unconfirmed_disagrees"

            convexity = (
                u["capture_mean"] - d["capture_mean"]
                if u["capture_mean"] is not None and d["capture_mean"] is not None
                else None
            )
            records.append(
                {
                    "schema_version": BEHAVIOR_SCHEMA_VERSION,
                    "behavior_config_hash": behavior_hash,
                    "ticker": str(ticker),
                    "horizon_weeks": h,
                    "down_n_weeks": d["n_weeks"],
                    "down_effective_n": round(float(d["effective_n"] or 0.0), 2),
                    "down_stock_mean": _round(d["stock_mean"]),
                    "down_gold_mean": _round(d["gold_mean"]),
                    "down_capture_mean": _round(d["capture_mean"]),
                    "down_capture_median": _round(d["capture_median"]),
                    "down_capture_anchor": _round(d_anc["capture_mean"]),
                    "down_anchor_n": d_anc["n_weeks"],
                    "up_n_weeks": u["n_weeks"],
                    "up_effective_n": round(float(u["effective_n"] or 0.0), 2),
                    "up_stock_mean": _round(u["stock_mean"]),
                    "up_gold_mean": _round(u["gold_mean"]),
                    "up_capture_mean": _round(u["capture_mean"]),
                    "up_capture_median": _round(u["capture_median"]),
                    "up_capture_anchor": _round(u_anc["capture_mean"]),
                    "up_anchor_n": u_anc["n_weeks"],
                    "convexity": _round(convexity),
                    "archetype": archetype,
                    "archetype_anchor": arch_anc,
                    "archetype_anchor_agrees": agrees,
                    "archetype_confidence": confidence,
                    "capture_status": status,
                    "caveat": CAPTURE_CAVEAT,
                }
            )
    if not records:
        return pd.DataFrame(columns=CAPTURE_COLUMNS)
    return pd.DataFrame.from_records(records, columns=CAPTURE_COLUMNS)


def _round(value: float | None, digits: int = 6) -> float | None:
    finite = optional_finite_float(value)
    return None if finite is None else round(finite, digits)


def capture_distribution(table: pd.DataFrame, *, horizon: int) -> dict[str, dict[str, float]]:
    """Cross-sectional quantiles of down/up capture at ``horizon`` — the evidence the
    archetype cutoffs are GROUNDED on (Codex review #10), not a number picked by feel.
    """

    out: dict[str, dict[str, float]] = {}
    hz = table[table["horizon_weeks"] == int(horizon)]
    # Include p33 / p67 so the persisted distribution literally contains the quantiles
    # the archetype cutoffs are grounded on (auditable data-grounding, Codex review #10).
    quants = [0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 0.9]
    for col in ("down_capture_mean", "up_capture_mean", "convexity"):
        series = pd.to_numeric(hz[col], errors="coerce").dropna()
        out[col] = {
            "n": float(len(series)),
            **{f"p{int(q * 100)}": round(float(series.quantile(q)), 4) for q in quants},
        }
    return out


def build_capture(
    episodes: pd.DataFrame,
    *,
    horizons: list[int] | None = None,
    config: CaptureBehaviorConfig | None = None,
    spine_schema_version: int = DIAL_SCHEMA_VERSION,
) -> pd.DataFrame:
    """End-to-end capture table from an episode frame (pure; no I/O)."""

    cfg = config if config is not None else default_capture_behavior_config()
    horizon_list = [int(h) for h in (horizons if horizons is not None else DIAL_HORIZONS_WEEKS)]
    chash = behavior_config_hash(cfg, spine_schema_version=spine_schema_version)
    return compute_capture_table(
        episodes, horizons=horizon_list, config=cfg, behavior_hash=chash
    )


def build_and_save(paths, *, horizons: list[int] | None = None) -> pd.DataFrame:
    """Compute once -> persist. Reads the persisted ``dial_episodes`` spine and writes
    ``dial_capture`` (run-stamped + latest alias) plus ``behavior_meta.json`` with the
    behaviour hash, the spine schema it was built from, timings and provenance.
    """

    from golden_vector.common.files import atomic_write_text
    from golden_vector.common.parquet import write_parquet_atomic
    from golden_vector.lab.vintages import lab_dir

    target_dir = lab_dir(paths)
    episode_path = target_dir / DIAL_EPISODES_FILENAME
    if not episode_path.exists():
        raise FileNotFoundError(
            f"dial_capture build needs the spine at {episode_path}; build the dial first."
        )
    t_read = time.perf_counter()
    episodes = pd.read_parquet(episode_path)
    read_seconds = round(time.perf_counter() - t_read, 3)

    cfg = default_capture_behavior_config()
    horizon_list = [int(h) for h in (horizons if horizons is not None else DIAL_HORIZONS_WEEKS)]
    if cfg.default_capture_horizon not in horizon_list:
        raise ValueError(
            f"default_capture_horizon {cfg.default_capture_horizon} is not in the built "
            f"horizons {horizon_list}; the grounded capture distribution would be empty."
        )
    chash = behavior_config_hash(cfg, spine_schema_version=DIAL_SCHEMA_VERSION)

    t_build = time.perf_counter()
    table = compute_capture_table(
        episodes, horizons=horizon_list, config=cfg, behavior_hash=chash
    )
    build_seconds = round(time.perf_counter() - t_build, 3)

    moment = datetime.now(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    stamped_name = f"{CAPTURE_ARTIFACT}_{stamp}.parquet"
    write_parquet_atomic(table, target_dir / stamped_name)
    write_parquet_atomic(table, target_dir / CAPTURE_FILENAME)

    status_counts = (
        table["capture_status"].value_counts().to_dict() if not table.empty else {}
    )
    archetype_counts = (
        table["archetype"].value_counts(dropna=False).to_dict()
        if not table.empty
        else {}
    )
    meta = {
        "built_at_utc": moment.isoformat(),
        "schema_version": BEHAVIOR_SCHEMA_VERSION,
        "behavior_config_hash": chash,
        "spine_schema_version": DIAL_SCHEMA_VERSION,
        "signal_id": BEHAVIOR_SIGNAL_ID,
        "source_benchmark": CAPTURE_SOURCE_BENCHMARK,
        "horizons_weeks": horizon_list,
        "run_stamped_artifacts": {"capture": stamped_name},
        "latest_aliases": {"capture": CAPTURE_FILENAME},
        "stage_timings": {"read_episodes_seconds": read_seconds, "build_capture_seconds": build_seconds},
        "rows": int(len(table)),
        "capture_status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "archetype_counts": {str(k): int(v) for k, v in archetype_counts.items()},
        "capture_distribution_default_horizon": capture_distribution(
            table, horizon=cfg.default_capture_horizon
        ),
        "config": cfg.model_dump(),
        "caveat": CAPTURE_CAVEAT,
    }
    atomic_write_text(target_dir / BEHAVIOR_META_FILENAME, json.dumps(meta, indent=2))
    return table


def main() -> None:
    from golden_vector.app.paths import ProjectPaths

    cfg = default_capture_behavior_config()
    table = build_and_save(ProjectPaths.discover())
    if table.empty:
        print("dial_capture rebuilt: 0 rows.")
        return
    print(
        f"dial_capture rebuilt: {len(table)} rows across horizons "
        f"{sorted({int(h) for h in table['horizon_weeks']})}."
    )
    dist = capture_distribution(table, horizon=cfg.default_capture_horizon)
    print(f"\nCross-sectional capture distribution @ {cfg.default_capture_horizon}w:")
    for col, q in dist.items():
        print(f"  {col}: {q}")
    print("\ncapture_status counts:")
    print(table["capture_status"].value_counts().to_string())
    ok = table[table["capture_status"] == "OK"]
    if not ok.empty:
        print("\narchetype counts (OK cells):")
        print(ok["archetype"].value_counts().to_string())


if __name__ == "__main__":
    main()
