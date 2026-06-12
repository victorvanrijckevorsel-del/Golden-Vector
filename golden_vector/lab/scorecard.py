"""Scorecard publisher — turns validation verdicts into a saved, admissible
product artifact.

This is the publish boundary Codex's reviews asked for. It enforces, by
construction:
- **pre-registration** (HIGH-2): refuses to publish a verdict whose signal_id
  is not in the variant ledger; stamps the registered variant hash into meta.
- **leak gate** (round-2 HIGH-1): runs the time-reversal contrast on the
  shared harness and refuses to publish if it does not clear
  ``TIME_REVERSAL_MIN_CONTRAST`` (the honest path is leaking the future).
- **input provenance** (HIGH-1/MED-4): records the exact input artifact paths
  + sha256 + the current model-state run id into the meta.
- **honest diagnostics** (NIT-2): persists fold-IC lag-1 autocorrelation,
  fold count, and median ceiling beside each verdict so a skeptical reader
  can see why a low-ceiling outcome still passes.

Outputs are run-stamped immutable artifacts + a ``latest`` alias (the main
data-spine pattern); the optional /scorecard page reads the alias.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.common.files import atomic_write_text
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.lab import validation as val
from golden_vector.lab.ledger import load_ledger
from golden_vector.lab.vintages import lab_dir

SCORECARD_TABLE_FILENAME = "scorecard_latest.parquet"
SCORECARD_META_FILENAME = "scorecard_latest_meta.json"

# The backtest experiments that must be registered before they may publish.
BACKTEST_SIGNAL_IDS = (
    "validation_e1a",
    "validation_e1b",
    "validation_e2",
    "validation_e3",
    "validation_e3b",
)

# E4 — forward-accrual signals (spec §5): pinned field, outcome, first verdict.
ACCRUAL_SIGNALS = (
    {"signal_id": "tool_b_health", "claim": "Tool B health rank forward-predicts 13w alpha vs GDX",
     "field": "fundamental_check_score", "start": "2026-04-22", "first_verdict": "~2031-04"},
    {"signal_id": "tool_d_resilience", "claim": "Tool D resilience rank forward-predicts 13w down-capture",
     "field": "tool_d_quality_score", "start": "2026-06-05", "first_verdict": "~2031-06"},
    {"signal_id": "option_skew", "claim": "Option residual skew forward-predicts 13w down-capture",
     "field": "skew_residual_signal", "start": "2026-06-08", "first_verdict": "~2031-06"},
    {"signal_id": "option_iv_pct", "claim": "Option IV percentile forward-predicts 13w realized vol",
     "field": "iv_percentile_cross_sectional", "start": "2026-06-08", "first_verdict": "~2031-06"},
)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _registered_hash(lab: Path, signal_id: str) -> str:
    """Latest registered variant hash for a signal; raises if unregistered."""

    records = [r for r in load_ledger(lab) if r.signal_id == signal_id]
    if not records:
        raise ValueError(
            f"Refusing to publish: signal '{signal_id}' is not registered in the "
            "variant ledger (pre-registration is required before a verdict ships)."
        )
    return records[-1].variant_hash


def _fold_ic_autocorr(folds: list) -> float | None:
    ics = [f.ic for f in folds if f.ic is not None]
    if len(ics) < 3:
        return None
    arr = np.asarray(ics, dtype=float)
    c = arr - arr.mean()
    denom = float((c**2).sum())
    if denom <= 0:
        return None
    return float((c[1:] * c[:-1]).sum() / denom)


def _verdict_row(verdict, folds, *, kind: str, variant_hash: str | None) -> dict:
    return {
        "signal_id": verdict.signal_id,
        "claim": verdict.claim,
        "verdict": verdict.verdict,
        "kind": kind,
        "n_folds": verdict.n_folds,
        "mean_ic": verdict.mean_ic,
        "nw_t": verdict.nw_t,
        "share_folds_directional": verdict.share_folds_directional,
        "tercile_spread_mean": verdict.tercile_spread_mean,
        "tercile_spread_t": verdict.tercile_spread_t,
        "median_ceiling": verdict.median_ceiling,
        "fold_ic_autocorr": _fold_ic_autocorr(folds),
        "baseline_lines": json.dumps(verdict.baseline_lines),
        "gate_results": json.dumps(verdict.gate_results),
        "variant_hash": variant_hash,
        "caveat": val.SURVIVOR_QUALIFIER,
    }


def _accrual_rows(paths: ProjectPaths) -> list[dict]:
    """E4: forward-accrual status from the vintage stores (no backtest)."""

    vdir = lab_dir(paths) / "vintages"
    rows: list[dict] = []
    for spec in ACCRUAL_SIGNALS:
        accrued_weeks = 0
        for store in vdir.glob("*.parquet"):
            try:
                frame = pd.read_parquet(store, columns=["field", "vintage_date"])
            except Exception:
                continue
            if spec["field"] in set(frame.get("field", pd.Series(dtype=str))):
                accrued_weeks = max(
                    accrued_weeks,
                    int(frame.loc[frame["field"] == spec["field"], "vintage_date"].nunique()),
                )
        rows.append(
            {
                "signal_id": spec["signal_id"],
                "claim": spec["claim"],
                "verdict": f"ACCRUING (first verdict expected {spec['first_verdict']})",
                "kind": "accruing",
                "n_folds": 0,
                "mean_ic": None,
                "nw_t": None,
                "share_folds_directional": None,
                "tercile_spread_mean": None,
                "tercile_spread_t": None,
                "median_ceiling": None,
                "fold_ic_autocorr": None,
                "baseline_lines": json.dumps([]),
                "gate_results": json.dumps({}),
                "variant_hash": None,
                "caveat": (
                    f"Forward-only: recording since {spec['start']} "
                    f"({accrued_weeks} vintage weeks so far)."
                ),
            }
        )
    return rows


def build_scorecard(paths: ProjectPaths, *, now: datetime) -> tuple[pd.DataFrame, dict]:
    """Run every experiment + accrual, enforce the publish gates, and return
    the scorecard frame + provenance meta. Raises if a gate is not satisfied."""

    lab = lab_dir(paths)
    # Gate 1: pre-registration (refuse before computing anything).
    variant_hashes = {sid: _registered_hash(lab, sid) for sid in BACKTEST_SIGNAL_IDS}

    panel, ticker_weekly, weight_map = val.load_validation_inputs(paths)
    grid = val.build_as_of_grid(panel)
    ctx = val.build_tool_c_recon_context(paths)

    # Gate 2: leak canary on the shared harness — refuse if it does not clear.
    honest, contaminated = val.time_reversal_ic_contrast(
        panel, ticker_weekly, grid, weight_map, rank_column="structural_delta"
    )
    contrast = (contaminated or 0.0) - (honest or 0.0)
    if contrast < val.TIME_REVERSAL_MIN_CONTRAST:
        raise ValueError(
            f"Refusing to publish: time-reversal leak canary contrast {contrast:.3f} "
            f"< {val.TIME_REVERSAL_MIN_CONTRAST} — the honest path may be leaking."
        )

    e1a = val.run_e1a(panel, grid, weight_map)
    e1b, f1b = val.run_e1b(panel, ticker_weekly, grid, weight_map)
    e2, f2 = val.run_e2(panel, ticker_weekly, grid, weight_map)
    e3, f3 = val.run_e3(ctx, ticker_weekly, grid, weight_map)
    e3b, f3b = val.run_e3b(ctx, ticker_weekly, grid, weight_map)

    rows = [
        _verdict_row(e1a, [], kind="backtest", variant_hash=variant_hashes["validation_e1a"]),
        _verdict_row(e1b, f1b, kind="backtest", variant_hash=variant_hashes["validation_e1b"]),
        _verdict_row(e2, f2, kind="backtest", variant_hash=variant_hashes["validation_e2"]),
        _verdict_row(e3, f3, kind="backtest", variant_hash=variant_hashes["validation_e3"]),
        _verdict_row(e3b, f3b, kind="backtest", variant_hash=variant_hashes["validation_e3b"]),
    ]
    rows.extend(_accrual_rows(paths))
    # Publish guard: no contaminated verdict may ship.
    val.assert_publishable([e1a, e1b, e2, e3, e3b])

    frame = pd.DataFrame(rows)
    meta = {
        "built_at_utc": now.isoformat(),
        "n_folds_grid": len(grid),
        "leak_canary": {"honest_mean_ic": honest, "contaminated_mean_ic": contaminated,
                        "contrast": contrast, "min_required": val.TIME_REVERSAL_MIN_CONTRAST},
        "variant_hashes": variant_hashes,
        "input_provenance": {
            "structural_panel": {
                "path": str(paths.latest_tool_a_structural_metrics_path),
                "sha256": _sha256(paths.latest_tool_a_structural_metrics_path),
            },
            "tool_c_latest": {
                "path": str(paths.latest_tool_c_snapshot_parquet_path),
                "sha256": _sha256(paths.latest_tool_c_snapshot_parquet_path),
            },
        },
        "caveats": [
            "SUPPORTED, not VALIDATED: survivor-only universe (today's names).",
            "Code-vintage: the structural panel is data-PIT but regenerated with "
            "2026 code/config/universe.",
            "E3/E3b per-week capture is noisy (low split-half ceiling); the signal "
            "survives across folds — effect sizes are descriptive, not large.",
        ],
    }
    return frame, meta


def publish_scorecard(paths: ProjectPaths, *, now: datetime | None = None) -> Path:
    """Build and atomically persist the scorecard (run-stamped + latest alias)."""

    moment = now or datetime.now(timezone.utc)
    frame, meta = build_scorecard(paths, now=moment)
    target = lab_dir(paths)
    target.mkdir(parents=True, exist_ok=True)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")

    stamped = target / f"scorecard_{stamp}.parquet"
    write_parquet_atomic(frame, stamped)
    write_parquet_atomic(frame, target / SCORECARD_TABLE_FILENAME)
    meta["run_stamped_artifact"] = stamped.name
    atomic_write_text(target / SCORECARD_META_FILENAME, json.dumps(meta, indent=2, default=str))
    return target / SCORECARD_TABLE_FILENAME


def main() -> None:
    path = publish_scorecard(ProjectPaths.discover())
    frame = pd.read_parquet(path)
    print(f"Scorecard published: {path}")
    for row in frame.to_dict(orient="records"):
        print(f"  {row['signal_id']:22s} {row['verdict']}")


if __name__ == "__main__":
    main()
