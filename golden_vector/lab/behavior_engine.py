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
    DIAL_ARTIFACT_META_FILENAME,
    DIAL_BENCHMARKS,
    DIAL_EPISODES_FILENAME,
    DIAL_HORIZONS_WEEKS,
    DIAL_SCHEMA_VERSION,
    DOWN_BUCKETS,
    UP_BUCKETS,
)
from golden_vector.lab.statistics import (
    benjamini_hochberg,
    decay_effective_n,
    decay_weights,
    eb_shrink,
    mann_kendall,
    mde_proportion_pp,
    peer_percentile,
    theil_sen,
    two_proportion_p,
    weighted_median,
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
CAPTURE_STATUSES = (
    "OK",
    "THIN_DOWN",
    "THIN_UP",
    "THIN_BOTH",
    "INVALID_DOWN_DENOMINATOR",
    "INVALID_UP_DENOMINATOR",
)
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
    "archetype_all_rows",
    "archetype",
    "archetype_anchor",
    "archetype_anchor_agrees",
    "archetype_confidence",
    "capture_status",
    "caveat",
]

# --- Peer ranking (Phase 2) ---
PEER_POINTS_ARTIFACT = "dial_peer_points"
PEER_POINTS_FILENAME = "dial_peer_points_latest.parquet"
PEER_ARTIFACT = "dial_peer"
PEER_FILENAME = "dial_peer_latest.parquet"
PEER_STATUSES = ("OK", "THIN_PEER_POOL")
PEER_DIRECTIONS = ("down", "up")
PEER_CAVEAT = (
    "peer percentile ranks the miner's OWN forward return against every other miner "
    "with valid data that same week (100 = best, 0 = worst); point-in-time membership, "
    "survivor-only universe (failed miners are absent from old pools, so historical "
    "ranks read optimistically), exploratory — not a prediction. Peer TREND is deferred "
    "until dead-miner records exist."
)
PEER_POINT_COLUMNS = [
    "schema_version",
    "behavior_config_hash",
    "ticker",
    "horizon_weeks",
    "gold_bucket",
    "week_period",
    "peer_count",
    "peer_rank_1_best",
    "peer_percentile",
    "point_status",
]
PEER_COLUMNS = [
    "schema_version",
    "behavior_config_hash",
    "ticker",
    "horizon_weeks",
    "direction",
    "peer_event_n",
    "peer_effective_n",
    "peer_percentile_median",
    "top_quartile_rate",
    "bottom_quartile_rate",
    "peer_status",
    "survivor_universe",
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
    the grain. The capture NUMBERS are emitted at every horizon. The ARCHETYPE box is
    only emitted at ``config.default_capture_horizon`` (the horizon its tercile cutoffs
    are grounded on); other horizons keep the numbers but no box. ``archetype_all_rows``
    is the raw all-rows label; the display-safe ``archetype`` is populated ONLY when the
    independent-anchor capture CONFIRMS it (``archetype_confidence == 'confirmed'``) —
    an unconfirmed or anchor-disagreeing cell ships numbers + ``archetype_all_rows`` but
    a null ``archetype`` so the UI can never present it as settled. A side that clears
    the N floor but has no finite capture (zero/invalid gold denominator) abstains with
    an INVALID_*_DENOMINATOR status.
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
            # A side that clears the N floor but has no finite capture = bad denominator.
            down_bad = (not down_thin) and d["capture_mean"] is None
            up_bad = (not up_thin) and u["capture_mean"] is None
            confidence: str | None = None
            archetype_all: str | None = None
            archetype: str | None = None
            arch_anc_out: str | None = None
            agrees_out: bool | None = None
            if down_thin and up_thin:
                status = "THIN_BOTH"
            elif down_thin:
                status = "THIN_DOWN"
            elif up_thin:
                status = "THIN_UP"
            elif down_bad:
                status = "INVALID_DOWN_DENOMINATOR"
            elif up_bad:
                status = "INVALID_UP_DENOMINATOR"
            else:
                status = "OK"
                # Archetypes are only emitted at the default capture horizon — the one
                # the tercile cutoffs are grounded on. Other horizons keep the numbers.
                if h == int(config.default_capture_horizon):
                    archetype_all = arch_all
                    arch_anc_out, agrees_out = arch_anc, agrees
                    # The independent-anchor capture is a cross-check: the DISPLAY-SAFE
                    # `archetype` is populated ONLY when anchors confirm. archetype_all_rows
                    # keeps the raw label so nothing is lost, but the bold box can never
                    # show an unconfirmed/anchor-disagreeing label as settled.
                    if anchor_n < int(config.min_anchor_episodes) or arch_anc is None:
                        confidence = "unconfirmed_thin_anchor"
                    elif agrees:
                        confidence = "confirmed"
                    else:
                        confidence = "unconfirmed_disagrees"
                    archetype = archetype_all if confidence == "confirmed" else None

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
                    "archetype_all_rows": archetype_all,
                    "archetype": archetype,
                    "archetype_anchor": arch_anc_out,
                    "archetype_anchor_agrees": agrees_out,
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
    # Ground on LABEL-ELIGIBLE (OK) rows only — the population the archetype actually
    # partitions — so the reported cutoffs match the cells they classify (Codex review).
    hz = table[(table["horizon_weeks"] == int(horizon)) & (table["capture_status"] == "OK")]
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


CUTOFF_DRIFT_TOLERANCE = 0.15  # warn when a config cutoff drifts this far from live p33/p67


def _warn_cutoff_drift(cfg: CaptureBehaviorConfig, dist: dict[str, dict[str, float]]) -> None:
    """Print a loud warning if the archetype cutoffs have drifted from this run's live
    p33/p67. The cutoffs are config constants grounded on the cross-sectional distribution;
    a material data change can move the quantiles, so the daily build re-confirms them.
    Warn (not fail) — re-grounding is a deliberate human decision, recorded in config."""

    checks = (
        ("hedge_down_capture_max", cfg.hedge_down_capture_max, "down_capture_mean", "p33"),
        ("torque_up_capture_min", cfg.torque_up_capture_min, "up_capture_mean", "p67"),
    )
    for name, value, col, q in checks:
        live = (dist.get(col) or {}).get(q)
        if live is None:
            continue
        drift = abs(float(value) - float(live))
        if drift > CUTOFF_DRIFT_TOLERANCE:
            print(
                f"WARNING: archetype cutoff {name}={value} has drifted {drift:.3f} from the "
                f"live {col} {q}={live} (tolerance {CUTOFF_DRIFT_TOLERANCE}). Re-ground the "
                f"cutoff in config/lab_behavior_trend.yaml and rebuild."
            )


def compute_peer_points(episodes: pd.DataFrame, *, behavior_hash: str) -> pd.DataFrame:
    """Per-episode cross-sectional peer rank (benchmark-independent, point-in-time).

    For each (week, horizon, gold_bucket) the miner's OWN forward return is ranked
    against EVERY other miner that had valid data that same week — 100 = best, 0 = worst.
    Benchmark-INDEPENDENT: the ranked value (``stock_fwd_simple``) does not depend on
    GDX vs GDXJ, so it is computed once on the GDX rows (the widest cross-section), never
    twice per benchmark (Codex review #1). RAW: ``peer_percentile`` is defined whenever
    there are >= 2 valid peers and is NEVER nulled by a display threshold — the
    ``min_peer_count`` cut lives only in the snapshot (Codex review #3). Flat-gold weeks
    are excluded — peer scouting is a gold-down / gold-up question.
    """

    required = {
        "ticker",
        "horizon_weeks",
        "gold_bucket",
        "week_period",
        "stock_fwd_simple",
    }
    missing = required - set(episodes.columns)
    if missing:
        raise ValueError(
            f"dial_peer build needs episode columns {sorted(missing)} "
            "(rebuild the dial spine to schema v4)."
        )
    directional = set(DOWN_BUCKETS) | set(UP_BUCKETS)
    base = episodes[episodes["gold_bucket"].isin(directional)].copy()
    base["stock_fwd_simple"] = pd.to_numeric(base["stock_fwd_simple"], errors="coerce")
    base = base.dropna(subset=["stock_fwd_simple"])
    # Benchmark-INDEPENDENT union cross-section (Codex review #1): stock_fwd_simple is the
    # miner's OWN forward return (identical across benchmarks), so collapse to one row per
    # (ticker, week, horizon, bucket) regardless of which benchmark carried it — a
    # GDXJ-only week is included, never silently dropped by a GDX-only filter.
    base = base.drop_duplicates(
        subset=["ticker", "week_period", "horizon_weeks", "gold_bucket"]
    )
    if base.empty:
        return pd.DataFrame(columns=PEER_POINT_COLUMNS)
    keys = ["week_period", "horizon_weeks", "gold_bucket"]
    grouped = base.groupby(keys)["stock_fwd_simple"]
    base["peer_count"] = grouped.transform("count").astype(int)
    base["peer_rank_1_best"] = grouped.rank(ascending=False, method="average").round(2)
    # peer_percentile via the ONE shared primitive (NaN for < 2 peers, ties averaged).
    base["peer_percentile"] = (
        base.groupby(keys)["stock_fwd_simple"]
        .transform(lambda s: peer_percentile(s.to_numpy()))
        .round(2)
    )
    # A lone name has no peer pool: abstain UNIFORMLY across both rank columns
    # (peer_percentile is already NaN from the primitive).
    base.loc[base["peer_count"] < 2, "peer_rank_1_best"] = pd.NA
    base["point_status"] = base["peer_count"].map(
        lambda c: "OK" if c >= 2 else "SINGLETON"
    )
    base["schema_version"] = BEHAVIOR_SCHEMA_VERSION
    base["behavior_config_hash"] = behavior_hash
    return base[PEER_POINT_COLUMNS].reset_index(drop=True)


def compute_peer_snapshot(
    points: pd.DataFrame,
    *,
    behavior_hash: str,
    config: CaptureBehaviorConfig,
) -> pd.DataFrame:
    """Per (ticker, horizon, direction) peer SNAPSHOT — "was it one of the best miners
    to own when gold fell / rose?"

    Median peer percentile + top/bottom-quartile rates over events with a USABLE peer
    pool (``peer_count >= min_peer_count`` — the display threshold, applied here, never
    in the raw points). ``peer_effective_n = events / horizon`` deflates the overlapping
    weekly events; below the per-side floor the snapshot is flagged ``THIN_PEER_POOL``.
    NO peer trend in v1 — deferred until dead-miner records exist (survivorship would
    manufacture a fake "improving").
    """

    if points.empty:
        return pd.DataFrame(columns=PEER_COLUMNS)
    down, up = set(DOWN_BUCKETS), set(UP_BUCKETS)
    pts = points.copy()
    pts["direction"] = pts["gold_bucket"].map(
        lambda b: "down" if b in down else ("up" if b in up else None)
    )
    pts = pts[pts["direction"].notna()]
    records: list[dict[str, object]] = []
    for (ticker, horizon, direction), group in pts.groupby(
        ["ticker", "horizon_weeks", "direction"], sort=True
    ):
        h = int(horizon)
        usable = group[
            (group["peer_count"] >= config.min_peer_count)
            & group["peer_percentile"].notna()
        ]
        event_n = int(len(usable))
        eff_n = effective_n(event_n, label_horizon_weeks=h) if event_n else 0.0
        if event_n == 0:
            median = top = bottom = None
            status = "THIN_PEER_POOL"
        else:
            pct = usable["peer_percentile"].astype(float)
            median = round(float(pct.median()), 2)
            top = round(float((pct >= config.top_peer_percentile_cutoff).mean()), 4)
            bottom = round(float((pct <= config.bottom_peer_percentile_cutoff).mean()), 4)
            status = "OK" if eff_n >= config.min_peer_effective_n else "THIN_PEER_POOL"
        records.append(
            {
                "schema_version": BEHAVIOR_SCHEMA_VERSION,
                "behavior_config_hash": behavior_hash,
                "ticker": str(ticker),
                "horizon_weeks": h,
                "direction": str(direction),
                "peer_event_n": event_n,
                "peer_effective_n": round(float(eff_n), 2),
                "peer_percentile_median": median,
                "top_quartile_rate": top,
                "bottom_quartile_rate": bottom,
                "peer_status": status,
                "survivor_universe": True,
                "caveat": PEER_CAVEAT,
            }
        )
    if not records:
        return pd.DataFrame(columns=PEER_COLUMNS)
    return pd.DataFrame.from_records(records, columns=PEER_COLUMNS)


# --- Behaviour trend (Phase 3) ---
TREND_ARTIFACT = "dial_behavior_trend"
TREND_FILENAME = "dial_behavior_trend_latest.parquet"
TREND_LABELS = ("IMPROVING", "DETERIORATING", "NO_CHANGE_DETECTED", "INSUFFICIENT_EVIDENCE")
ALPHA_TREND_LABELS = (
    "ALPHA_IMPROVING",
    "ALPHA_DETERIORATING",
    "ALPHA_NO_CHANGE",
    "INSUFFICIENT",
)
TREND_STATUSES = ("OK", "THIN_ALL", "THIN_ANCHORS", "THIN_RECENT", "THIN_OLDER")
# The FDR family scope stamped on every trend row (so a reader can never mistake a
# scenario-local mover for a global winner).
TREND_FDR_SCOPE = "benchmark+horizon+gold_bucket"
TREND_CAVEAT = (
    "behaviour trend = recent vs older split on the cell's INDEPENDENT (non-overlap "
    "anchor) episodes in EVENT time. BOTH the beat-rate and the alpha (size) labels are "
    "gated by effective-N floors, Benjamini-Hochberg FDR within the SCENARIO-LOCAL "
    "family (benchmark+horizon+bucket — NOT global, so a label means 'changed within "
    "this scenario', not 'global winner'), and sign agreement; alpha additionally needs "
    "a Theil-Sen slope past threshold. NO_CHANGE_DETECTED means the gates did not detect "
    "a change (often underpowered — see mde_80pct_pp), NOT proven stable. Counted "
    "history, survivor-only, exploratory — NOT a forecast."
)
TREND_COLUMNS = [
    "schema_version",
    "behavior_config_hash",
    "ticker",
    "benchmark",
    "horizon_weeks",
    "gold_bucket",
    "all_n_rows",
    "all_effective_n",
    "all_p_beat_raw",
    "all_p_beat_shrunk",
    "all_alpha_median",
    "recent_anchor_n",
    "recent_p_beat_raw",
    "recent_p_beat_shrunk",
    "recent_alpha_median",
    "recent_prior_source",
    "older_anchor_n",
    "older_p_beat_raw",
    "older_p_beat_shrunk",
    "older_alpha_median",
    "decay_effective_n",
    "decay_p_beat_raw",
    "decay_p_beat_shrunk",
    "decay_alpha_median",
    "n_anchors",
    "trend_delta",
    "trend_tau",
    "trend_mk_z",
    "trend_mk_p",
    "trend_p_value",
    "trend_q_value",
    "trend_fdr_scope",
    "trend_fdr_family_size",
    "mde_80pct_pp",
    "alpha_slope_per_year",
    "alpha_trend_mk_p",
    "alpha_trend_tau",
    "alpha_trend_mk_z",
    "alpha_trend_q_value",
    "alpha_trend_label",
    "trend_label",
    "trend_status",
    "caveat",
]

# The FULL behaviour artifact set, published all-or-nothing (one place that knows the
# set, so a build can never half-wire it — mirrors DIAL_ARTIFACT_SPECS).
BEHAVIOR_ARTIFACT_SPECS: dict[str, tuple[str, str]] = {
    "capture": (CAPTURE_ARTIFACT, CAPTURE_FILENAME),
    "peer_points": (PEER_POINTS_ARTIFACT, PEER_POINTS_FILENAME),
    "peer": (PEER_ARTIFACT, PEER_FILENAME),
    "trend": (TREND_ARTIFACT, TREND_FILENAME),
}


def _recency_weights(n_points: int, half_life: float):
    """Event-time decay weights for ``n_points`` time-ordered (oldest-first) anchors —
    the newest anchor weighs 1.0 and each step back halves every ``half_life`` episodes.
    """

    ages = [float(n_points - 1 - i) for i in range(n_points)]
    return decay_weights(ages, half_life)


def _loo_mean(means: dict[str, float | None], ticker: str) -> tuple[float | None, int]:
    """Leave-one-out mean of per-ticker window means (equal ticker weight) + the peer
    count it averaged over. ONE copy of the LOO averaging (used by both prior helpers)."""

    others = [
        v for t, v in means.items() if t != ticker and v is not None and not pd.isna(v)
    ]
    return (sum(others) / len(others), len(others)) if others else (None, 0)


def _loo_prior(means: dict[str, float | None], ticker: str) -> float | None:
    """Leave-one-out all-history peer prior."""

    return _loo_mean(means, ticker)[0]


def _window_prior(
    means: dict[str, float | None], ticker: str, min_pool_tickers: float
) -> tuple[float, str]:
    """Window-matched cross-sectional peer prior (leave-one-out). Falls back to the
    neutral 0.5 when fewer than ``min_pool_tickers`` peer tickers contribute a window
    mean (so the prior rests on a real cross-section, not one or two names)."""

    mean, n_peers = _loo_mean(means, ticker)
    if mean is not None and n_peers >= min_pool_tickers:
        return mean, "cross_sectional"
    return 0.5, "neutral_0.5"


def compute_trend_table(
    episodes: pd.DataFrame,
    *,
    horizons: list[int],
    benchmarks: list[str],
    config: CaptureBehaviorConfig,
    behavior_hash: str,
) -> pd.DataFrame:
    """One row per (ticker, benchmark, horizon, gold_bucket): the behaviour-change layer.

    Recent vs older is split on the cell's INDEPENDENT anchors in EVENT time (not
    calendar — gold rarely fell in 2022-2026, so a calendar window would be empty on the
    hedge side). Each window shrinks toward its OWN window-matched peer pool (leave-one-
    out) so a genuine divergence survives; the priors LARGELY offset in the delta but do
    not perfectly cancel (different effective-N weights the prior unequally), which is why
    the label is NOT taken on the shrunk delta alone. The beat label fires only when ALL
    hold: effective-N floors, |delta| >= threshold, BH-FDR q <= q_fdr on the two-proportion
    p (computed on RAW counts), and Mann-Kendall (on RAW anchors) agrees in sign — else
    INSUFFICIENT_EVIDENCE. Those raw-based gates are what guard against a pure prior
    artifact. Alpha (size) trend is a separate leading indicator.
    """

    required = {
        "ticker",
        "benchmark",
        "horizon_weeks",
        "gold_bucket",
        "week_period",
        "week_date",
        "beat",
        "alpha_simple",
        "is_nonoverlap_anchor",
    }
    missing = required - set(episodes.columns)
    if missing:
        raise ValueError(
            f"dial_behavior_trend build needs episode columns {sorted(missing)} "
            "(rebuild the dial spine to schema v4)."
        )
    directional = list(DOWN_BUCKETS) + list(UP_BUCKETS)
    records: list[dict[str, object]] = []
    for benchmark in [str(b).upper() for b in benchmarks]:
        bsub = episodes[episodes["benchmark"].astype(str).str.upper() == benchmark]
        for horizon in horizons:
            h = int(horizon)
            hsub = bsub[bsub["horizon_weeks"] == h]
            for bucket in directional:
                sub = hsub[hsub["gold_bucket"] == bucket]
                if sub.empty:
                    continue
                per: dict[str, dict] = {}
                for ticker, g in sub.groupby("ticker", sort=True):
                    g = g.sort_values("week_period")
                    beat = pd.to_numeric(g["beat"], errors="coerce")
                    # Drop NA beats ONCE (consistent with the capture side) so a NA row
                    # never inflates a window count or poisons a window mean with NaN.
                    anc = g[g["is_nonoverlap_anchor"].astype(bool)].sort_values("week_period")
                    anc_beat_all = pd.to_numeric(anc["beat"], errors="coerce")
                    anc = anc[anc_beat_all.notna()]
                    anc_beat = pd.to_numeric(anc["beat"], errors="coerce").to_numpy()
                    anc_alpha = pd.to_numeric(anc["alpha_simple"], errors="coerce").to_numpy()
                    na = int(len(anc))
                    n_rec = int(round(na * config.recent_anchor_fraction))
                    cut = na - n_rec
                    per[str(ticker)] = {
                        "g": g,
                        "anc": anc,
                        "anc_beat": anc_beat,
                        "anc_alpha": anc_alpha,
                        "na": na,
                        "all_n": int(beat.notna().sum()),
                        "all_mean": optional_finite_float(beat.mean()) if beat.notna().any() else None,
                        "all_alpha": pd.to_numeric(g["alpha_simple"], errors="coerce"),
                        "rec_beat": anc_beat[cut:],
                        "old_beat": anc_beat[:cut],
                        "rec_alpha": anc_alpha[cut:],
                        "old_alpha": anc_alpha[:cut],
                        "rec_mean": optional_finite_float(anc_beat[cut:].mean()) if n_rec else None,
                        "old_mean": optional_finite_float(anc_beat[:cut].mean()) if cut else None,
                    }
                all_means = {t: d["all_mean"] for t, d in per.items()}
                rec_means = {t: d["rec_mean"] for t, d in per.items()}
                old_means = {t: d["old_mean"] for t, d in per.items()}
                for ticker, d in per.items():
                    records.append(
                        _trend_record(
                            ticker=ticker,
                            benchmark=benchmark,
                            horizon=h,
                            bucket=bucket,
                            d=d,
                            all_prior=_loo_prior(all_means, ticker),
                            rec_prior=_window_prior(
                                rec_means, ticker, config.recent_prior_min_pool_tickers
                            ),
                            old_prior=_window_prior(
                                old_means, ticker, config.recent_prior_min_pool_tickers
                            ),
                            config=config,
                            behavior_hash=behavior_hash,
                        )
                    )
    if not records:
        return pd.DataFrame(columns=TREND_COLUMNS)
    df = pd.DataFrame.from_records(records, columns=TREND_COLUMNS)
    for col in ("trend_q_value", "trend_fdr_family_size", "alpha_trend_q_value"):
        df[col] = df[col].astype("object")
    fam_keys = ["benchmark", "horizon_weeks", "gold_bucket"]

    # --- Beat-trend FDR WITHIN each (benchmark, horizon, bucket) family — the natural
    # cross-sectional scan "which miners changed in THIS scenario?" (one test per
    # ticker). Scope + family size are stamped on every row so a reader can never read a
    # scenario-local mover as a global winner. ---
    ok = df["trend_status"] == "OK"
    for _key, grp in df[ok].groupby(fam_keys):
        _, q_values = benjamini_hochberg(grp["trend_p_value"].to_numpy(dtype=float), config.q_fdr)
        df.loc[grp.index, "trend_q_value"] = [round(float(q), 6) for q in q_values]
        df.loc[grp.index, "trend_fdr_family_size"] = int(len(grp))
    for idx in df.index[ok]:
        df.at[idx, "trend_label"] = _beat_label(
            delta=df.at[idx, "trend_delta"],
            tau=df.at[idx, "trend_tau"],
            q_value=df.at[idx, "trend_q_value"],
            config=config,
        )
    df.loc[~ok, "trend_label"] = "INSUFFICIENT_EVIDENCE"

    # --- Alpha-trend FDR: the alpha (leading) label is held to the SAME multiplicity
    # bar as beat (BH within the scenario family) + a Theil-Sen/MK sign-agreement gate.
    # Its power floor is its OWN anchor count, independent of the beat split. ---
    alpha_ok = df["alpha_slope_per_year"].notna() & (df["n_anchors"] >= config.min_anchors)
    for _key, grp in df[alpha_ok].groupby(fam_keys):
        _, q_values = benjamini_hochberg(
            grp["alpha_trend_mk_p"].to_numpy(dtype=float), config.q_fdr
        )
        df.loc[grp.index, "alpha_trend_q_value"] = [round(float(q), 6) for q in q_values]
    for idx in df.index[alpha_ok]:
        df.at[idx, "alpha_trend_label"] = _alpha_label(
            slope=df.at[idx, "alpha_slope_per_year"],
            tau=df.at[idx, "alpha_trend_tau"],
            q_value=df.at[idx, "alpha_trend_q_value"],
            config=config,
        )
    df.loc[~alpha_ok, "alpha_trend_label"] = "INSUFFICIENT"
    return df


def _beat_label(*, delta, tau, q_value, config: CaptureBehaviorConfig) -> str:
    """IMPROVING / DETERIORATING only when the effect clears the threshold, survives FDR,
    AND the Mann-Kendall trend agrees in sign; otherwise NO_CHANGE_DETECTED (which means
    'no change detected at this power', not 'proven stable')."""

    if delta is None or tau is None or q_value is None or pd.isna(delta) or pd.isna(tau):
        return "NO_CHANGE_DETECTED"
    significant = q_value <= config.q_fdr and abs(delta) >= config.trend_delta_threshold
    sign_agrees = (delta > 0) == (tau > 0) and tau != 0
    if significant and sign_agrees:
        return "IMPROVING" if delta > 0 else "DETERIORATING"
    return "NO_CHANGE_DETECTED"


def _alpha_label(*, slope, tau, q_value, config: CaptureBehaviorConfig) -> str:
    """ALPHA_IMPROVING / ALPHA_DETERIORATING only when the Theil-Sen slope clears its
    threshold, the Mann-Kendall p survives FDR, AND the slope and MK tau agree in sign;
    otherwise ALPHA_NO_CHANGE."""

    if slope is None or tau is None or q_value is None or pd.isna(slope) or pd.isna(tau):
        return "ALPHA_NO_CHANGE"
    significant = q_value <= config.q_fdr and abs(slope) >= config.alpha_slope_threshold
    sign_agrees = (slope > 0) == (tau > 0) and tau != 0
    if significant and sign_agrees:
        return "ALPHA_IMPROVING" if slope > 0 else "ALPHA_DETERIORATING"
    return "ALPHA_NO_CHANGE"


def _trend_record(
    *, ticker, benchmark, horizon, bucket, d, all_prior, rec_prior, old_prior, config, behavior_hash
) -> dict[str, object]:
    h = int(horizon)
    eb = config.eb_prior_strength
    all_eff = effective_n(d["all_n"], label_horizon_weeks=h) if d["all_n"] else 0.0
    all_shrunk = (
        eb_shrink(d["all_mean"], all_eff, all_prior if all_prior is not None else 0.5, eb)
        if d["all_mean"] is not None
        else None
    )
    rec_eff = float(len(d["rec_beat"]))
    old_eff = float(len(d["old_beat"]))
    rec_prior_val, rec_src = rec_prior
    old_prior_val, _old_src = old_prior
    rec_shrunk = eb_shrink(d["rec_mean"], rec_eff, rec_prior_val, eb) if d["rec_mean"] is not None else None
    old_shrunk = eb_shrink(d["old_mean"], old_eff, old_prior_val, eb) if d["old_mean"] is not None else None
    trend_delta = (
        rec_shrunk - old_shrunk if rec_shrunk is not None and old_shrunk is not None else None
    )
    # Decay over the independent anchors (Kish ESS, no /h — anchors are independent).
    # NOTE: decay_* are DESCRIPTIVE/reserved diagnostics (a smooth exponential view of the
    # same anchors) — they are persisted for future use and the UI, but they do NOT drive
    # the beat/alpha labels, which use the discrete recent-vs-older split + raw-based gates.
    na = d["na"]
    if na:
        w = _recency_weights(na, config.decay_half_life_episodes)
        wsum = float(w.sum())
        decay_p_raw = float((w * d["anc_beat"]).sum() / wsum) if wsum > 0 else None
        decay_eff = decay_effective_n(w, label_horizon_weeks=1)
        decay_shrunk = (
            eb_shrink(decay_p_raw, decay_eff, all_prior if all_prior is not None else 0.5, eb)
            if decay_p_raw is not None
            else None
        )
        decay_alpha_med = weighted_median(d["anc_alpha"], w)
    else:
        decay_p_raw = decay_eff = decay_shrunk = decay_alpha_med = None
    mk = mann_kendall(d["anc_beat"])
    # Alpha (size) trend: Theil-Sen slope per year + Mann-Kendall, both on anchors only.
    if na >= 2:
        t_days = pd.to_datetime(d["anc"]["week_date"]).astype("int64") / (1e9 * 86400.0)
        t_years = ((t_days - t_days.min()) / 365.25).to_numpy()
        slope = theil_sen(t_years, d["anc_alpha"])
        alpha_mk = mann_kendall(d["anc_alpha"])
    else:
        slope = None
        alpha_mk = {"p_value": 1.0, "tau": 0.0, "z": 0.0}
    raw_p = (
        two_proportion_p(d["rec_mean"], rec_eff, d["old_mean"], old_eff)
        if d["rec_mean"] is not None and d["old_mean"] is not None
        else 1.0
    )
    mde = mde_proportion_pp(rec_eff, old_eff)
    if all_eff < config.min_all_effective_n:
        status = "THIN_ALL"
    elif na < config.min_anchors:
        status = "THIN_ANCHORS"
    elif rec_eff < config.min_recent_effective_n:
        status = "THIN_RECENT"
    elif old_eff < config.min_older_effective_n:
        status = "THIN_OLDER"
    else:
        status = "OK"
    return {
        "schema_version": BEHAVIOR_SCHEMA_VERSION,
        "behavior_config_hash": behavior_hash,
        "ticker": str(ticker),
        "benchmark": str(benchmark),
        "horizon_weeks": h,
        "gold_bucket": str(bucket),
        "all_n_rows": d["all_n"],
        "all_effective_n": round(all_eff, 2),
        "all_p_beat_raw": _round(d["all_mean"]),
        "all_p_beat_shrunk": _round(all_shrunk),
        "all_alpha_median": _round(float(d["all_alpha"].median()) if d["all_n"] else None),
        "recent_anchor_n": int(len(d["rec_beat"])),
        "recent_p_beat_raw": _round(d["rec_mean"]),
        "recent_p_beat_shrunk": _round(rec_shrunk),
        "recent_alpha_median": _round(
            float(pd.Series(d["rec_alpha"]).median()) if len(d["rec_alpha"]) else None
        ),
        "recent_prior_source": rec_src,
        "older_anchor_n": int(len(d["old_beat"])),
        "older_p_beat_raw": _round(d["old_mean"]),
        "older_p_beat_shrunk": _round(old_shrunk),
        "older_alpha_median": _round(
            float(pd.Series(d["old_alpha"]).median()) if len(d["old_alpha"]) else None
        ),
        "decay_effective_n": round(float(decay_eff), 2) if decay_eff is not None else None,
        "decay_p_beat_raw": _round(decay_p_raw),
        "decay_p_beat_shrunk": _round(decay_shrunk),
        "decay_alpha_median": _round(decay_alpha_med),
        "n_anchors": na,
        "trend_delta": _round(trend_delta),
        "trend_tau": _round(mk["tau"]),
        "trend_mk_z": _round(mk["z"]),
        "trend_mk_p": _round(mk["p_value"]),
        "trend_p_value": _round(raw_p) if raw_p is not None else 1.0,
        "trend_q_value": None,
        "trend_fdr_scope": TREND_FDR_SCOPE,
        "trend_fdr_family_size": None,
        "mde_80pct_pp": _round(mde, 2),
        "alpha_slope_per_year": _round(slope),
        "alpha_trend_mk_p": _round(alpha_mk["p_value"]),
        "alpha_trend_tau": _round(alpha_mk["tau"]),
        "alpha_trend_mk_z": _round(alpha_mk["z"]),
        "alpha_trend_q_value": None,
        "alpha_trend_label": None,
        "trend_label": None,
        "trend_status": status,
        "caveat": TREND_CAVEAT,
    }


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

    from golden_vector.common.files import atomic_write_text, optional_sha256_file
    from golden_vector.common.parquet import write_run_stamped_set
    from golden_vector.lab.vintages import lab_dir

    target_dir = lab_dir(paths)
    # Resolve the spine through the published dial_meta pointer so we consume the IMMUTABLE
    # run-stamped episode file (not the mutable latest alias) and can stamp its EXACT
    # identity — a later dial rebuild with the same schema must not leave behaviour
    # artifacts silently looking current. (No dial meta -> hand-built test fixture.)
    spine_meta_path = target_dir / DIAL_ARTIFACT_META_FILENAME
    source_spine: dict[str, object] = {}
    episode_filename = DIAL_EPISODES_FILENAME
    if spine_meta_path.exists():
        spine_meta = json.loads(spine_meta_path.read_text(encoding="utf-8"))
        spine_schema = int(spine_meta.get("schema_version") or 0)
        if spine_schema != DIAL_SCHEMA_VERSION:
            raise ValueError(
                f"dial spine schema_version {spine_schema} != expected {DIAL_SCHEMA_VERSION}; "
                "rebuild the dial spine before the behaviour layer."
            )
        episode_filename = (
            (spine_meta.get("run_stamped_artifacts") or {}).get("episodes")
            or DIAL_EPISODES_FILENAME
        )
        source_spine = {
            "dial_built_at_utc": spine_meta.get("built_at_utc"),
            "dial_config_hash": spine_meta.get("config_hash"),
            "dial_schema_version": spine_schema,
            "episodes_artifact": episode_filename,
        }
    episode_path = target_dir / episode_filename
    if not episode_path.exists():
        raise FileNotFoundError(
            f"dial_capture build needs the spine at {episode_path}; build the dial first."
        )
    t_read = time.perf_counter()
    episodes = pd.read_parquet(episode_path)
    read_seconds = round(time.perf_counter() - t_read, 3)
    source_spine["episodes_rows"] = int(len(episodes))
    source_spine["episodes_sha256"] = optional_sha256_file(episode_path)

    cfg = default_capture_behavior_config()
    horizon_list = [int(h) for h in (horizons if horizons is not None else DIAL_HORIZONS_WEEKS)]
    for label, default_h in (
        ("default_capture_horizon", cfg.default_capture_horizon),
        ("default_trend_horizon", cfg.default_trend_horizon),
    ):
        if default_h not in horizon_list:
            raise ValueError(
                f"{label} {default_h} is not in the built horizons {horizon_list}; "
                "the grounded distribution / default view would be empty."
            )
    chash = behavior_config_hash(cfg, spine_schema_version=DIAL_SCHEMA_VERSION)

    t_build = time.perf_counter()
    table = compute_capture_table(
        episodes, horizons=horizon_list, config=cfg, behavior_hash=chash
    )
    build_seconds = round(time.perf_counter() - t_build, 3)

    # Peer ranking (Phase 2) + behaviour trend (Phase 3), from the SAME spine + hash.
    t_peer = time.perf_counter()
    peer_points = compute_peer_points(episodes, behavior_hash=chash)
    peer_snapshot = compute_peer_snapshot(peer_points, behavior_hash=chash, config=cfg)
    peer_seconds = round(time.perf_counter() - t_peer, 3)
    t_trend = time.perf_counter()
    trend = compute_trend_table(
        episodes,
        horizons=horizon_list,
        benchmarks=DIAL_BENCHMARKS,
        config=cfg,
        behavior_hash=chash,
    )
    trend_seconds = round(time.perf_counter() - t_trend, 3)

    # Stamp Parquet-level context metadata so the shared checked-read path can validate
    # artifact identity from the file itself, not just the columns.
    frames = {"capture": table, "peer_points": peer_points, "peer": peer_snapshot, "trend": trend}
    for frame in frames.values():
        frame.attrs["schema_version"] = BEHAVIOR_SCHEMA_VERSION
        frame.attrs["behavior_config_hash"] = chash

    moment = datetime.now(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%S%fZ")  # microsecond precision: immutable names
    # All-or-nothing publish (every run-stamped file first, then every latest alias,
    # with a missing/extra-key guard); the meta is written last so a crash mid-publish
    # leaves the previous good state intact.
    stamped, latest_aliases = write_run_stamped_set(
        target_dir, frames, BEHAVIOR_ARTIFACT_SPECS, stamp=stamp
    )

    status_counts = (
        table["capture_status"].value_counts().to_dict() if not table.empty else {}
    )
    archetype_counts = (
        table["archetype"].value_counts(dropna=False).to_dict()
        if not table.empty
        else {}
    )
    # The archetype cutoffs are config constants grounded on the cross-sectional p33/p67.
    # Re-confirm them against THIS run's live distribution and warn loudly on drift, so a
    # material data change can't silently leave the thresholds mis-grounded (config + the
    # live distribution are both stamped in meta below for an exact audit).
    grounded_dist = capture_distribution(table, horizon=cfg.default_capture_horizon)
    _warn_cutoff_drift(cfg, grounded_dist)
    meta = {
        "built_at_utc": moment.isoformat(),
        "schema_version": BEHAVIOR_SCHEMA_VERSION,
        "behavior_config_hash": chash,
        "spine_schema_version": DIAL_SCHEMA_VERSION,
        "source_spine": source_spine,
        "signal_id": BEHAVIOR_SIGNAL_ID,
        "source_benchmark": CAPTURE_SOURCE_BENCHMARK,
        "horizons_weeks": horizon_list,
        "run_stamped_artifacts": stamped,
        "latest_aliases": latest_aliases,
        "stage_timings": {
            "read_episodes_seconds": read_seconds,
            "build_capture_seconds": build_seconds,
            "build_peer_seconds": peer_seconds,
            "build_trend_seconds": trend_seconds,
        },
        "rows": int(len(table)),
        "capture_status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "archetype_counts": {str(k): int(v) for k, v in archetype_counts.items()},
        "capture_distribution_default_horizon": grounded_dist,
        "peer_points_rows": int(len(peer_points)),
        "peer_rows": int(len(peer_snapshot)),
        "peer_status_counts": (
            {
                str(k): int(v)
                for k, v in peer_snapshot["peer_status"].value_counts().to_dict().items()
            }
            if not peer_snapshot.empty
            else {}
        ),
        "trend_rows": int(len(trend)),
        "trend_label_counts": (
            {
                str(k): int(v)
                for k, v in trend["trend_label"].value_counts(dropna=False).to_dict().items()
            }
            if not trend.empty
            else {}
        ),
        "alpha_trend_label_counts": (
            {
                str(k): int(v)
                for k, v in trend["alpha_trend_label"].value_counts(dropna=False).to_dict().items()
            }
            if not trend.empty
            else {}
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
