"""Correct the five reconstructed Lab validation ledger records (incident 2026-08-13).

The original `data/lab/variant_ledger.jsonl` was destroyed with the rest of the
data store and is gitignored, so no copy survives anywhere. The first
reconstruction (same day, ~09:41 UTC) invented a FLAT config shape; the
guardrail test `test_ledger_constants_match_registered_gates` reads a nested
`gates` mapping and so failed with KeyError once the records existed at all.

This rewrites those five records IN PLACE (never appending — appending would
double every signal's `n_trials`, which is a real input elsewhere) with the
schema the guardrail specifies, sourcing every threshold from
`golden_vector.lab.validation` so the record mirrors the implementation.

HONEST LIMITATION, recorded in the incident file: a ledger regenerated from
today's constants can no longer prove those constants have not drifted, and it
is not genuine pre-registration. Every reconstructed record therefore carries
`reseeded_after_incident`, which also changes its variant_hash — so a
reconstruction can never be mistaken for the original registration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(r"c:\Users\Emanuel\code\Golden-Vector")
sys.path.insert(0, str(REPO))

from golden_vector.lab import validation as v  # noqa: E402
from golden_vector.lab.ledger import variant_hash  # noqa: E402

MARKER = "2026-08-13"

CONFIGS: dict[str, dict] = {
    "validation_e1a": {
        "claim": "Tool A Delta Core gearing ranking is stable out of sample",
        "direction": "stability IC > 0 (rank persistence t -> t+52)",
        "fold_ic_floor": v.E1A_FOLD_IC_FLOOR,
        "gates": {
            "mean_ic_min": v.E1A_MEAN_IC_GATE,
            "share_folds_ge_030": v.E1A_SHARE_GATE,
        },
        "stability_lag_weeks": v.STABILITY_LAG_PERIODS,
        "reseeded_after_incident": MARKER,
    },
    "validation_e1b": {
        "claim": "Tool A Delta Core ranking forward-predicts realized gold beta",
        "direction": "mean IC > 0",
        "forward_horizon_weeks": v.FORWARD_HORIZON_WEEKS,
        "gates": {
            "mean_ic_gt0_nw_t": v.NW_T_GATE,
            "share_folds_pos": v.SHARE_DIRECTIONAL_GATE,
            "spread_t": v.SPREAD_T_GATE,
            "tercile_portfolio_spread_min": v.E1B_SPREAD_GATE,
        },
        "reseeded_after_incident": MARKER,
    },
    "validation_e2": {
        "claim": "Down-beta ranking forward-predicts down-beta in gold-down weeks",
        "direction": "mean IC > 0",
        "down_week_floor": v.E2_DOWN_WEEK_FLOOR,
        "forward_horizon_weeks": v.FORWARD_HORIZON_WEEKS,
        "gates": {
            "mean_ic_gt0_nw_t": v.NW_T_GATE,
            "share_folds_pos": v.SHARE_DIRECTIONAL_GATE,
            "spread_t": v.SPREAD_T_GATE,
            "tercile_portfolio_spread_min": v.E2_SPREAD_GATE,
        },
        "reseeded_after_incident": MARKER,
    },
    "validation_e3": {
        "claim": (
            "Tool C downside rank identifies the most fragile miners when gold falls"
        ),
        # run_e3(direction=-1): a HIGH downside score must predict the LOWEST
        # forward capture, so the admissible IC is negative.
        "direction": "mean IC < 0 (high downside score = most fragile)",
        "baselines_paired_t2": ["down_beta_core_only"],
        "gates": {
            "neg_mean_ic_nw_t": v.NW_T_GATE,
            "share_folds_neg": v.SHARE_DIRECTIONAL_GATE,
            "spread_neg_t": v.SPREAD_T_GATE,
        },
        "reseeded_after_incident": MARKER,
    },
    "validation_e3b": {
        "claim": (
            "Tool C upside rank identifies the miners that capture most when gold rallies"
        ),
        "direction": "mean IC > 0 (high upside score = most capture)",
        "baselines_paired_t2": ["up_beta_core_only"],
        "gates": {
            "mean_ic_nw_t": v.NW_T_GATE,
            "share_folds": v.SHARE_DIRECTIONAL_GATE,
        },
        "reseeded_after_incident": MARKER,
    },
}

ledger = REPO / "data" / "lab" / "variant_ledger.jsonl"
lines = ledger.read_text(encoding="utf-8").splitlines()

out: list[str] = []
rewritten: list[str] = []
for line in lines:
    if not line.strip():
        continue
    payload = json.loads(line)
    signal_id = payload["signal_id"]
    if signal_id in CONFIGS:
        config = CONFIGS[signal_id]
        payload["config"] = config
        payload["variant_hash"] = variant_hash(signal_id, config)
        rewritten.append(signal_id)
        line = json.dumps(payload, sort_keys=True)
    out.append(line)

missing = sorted(set(CONFIGS) - set(rewritten))
if missing:
    raise SystemExit(f"expected records absent from the ledger: {missing}")

tmp = ledger.with_suffix(".jsonl.tmp")
tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
tmp.replace(ledger)
print(f"rewrote {len(rewritten)} validation records; {len(out)} total records kept")
for signal_id in sorted(rewritten):
    print(" -", signal_id)
