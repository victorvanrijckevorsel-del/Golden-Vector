"""Re-register the five validation backtest signals after the 2026-08-13 data loss.

Configs are built from validation.py's own named gate constants (code-derived,
matching the spec §2 registrations done by hand in June), so provenance cannot
drift from the code. register_variant is idempotent per exact config hash.
"""

import sys

sys.path.insert(0, r"c:\Users\Emanuel\code\Golden-Vector")

from golden_vector.app.paths import ProjectPaths
from golden_vector.lab import validation as val
from golden_vector.lab.ledger import n_trials, register_variant
from golden_vector.lab.vintages import lab_dir

lab = lab_dir(ProjectPaths.discover())

CONFIGS = {
    "validation_e1a": {
        "stability_lag_weeks": 52,
        "mean_ic_gate": val.E1A_MEAN_IC_GATE,
        "fold_ic_floor": val.E1A_FOLD_IC_FLOOR,
        "share_gate": val.E1A_SHARE_GATE,
        "reseeded_after_incident": "2026-08-13",
    },
    "validation_e1b": {
        "outcome": "realized_ols_beta_26w",
        "spread_gate": val.E1B_SPREAD_GATE,
        "share_directional_gate": val.SHARE_DIRECTIONAL_GATE,
        "reseeded_after_incident": "2026-08-13",
    },
    "validation_e2": {
        "outcome": "ols_down_beta_forward_gold_down_weeks",
        "spread_gate": val.E2_SPREAD_GATE,
        "down_week_floor": val.E2_DOWN_WEEK_FLOOR,
        "reseeded_after_incident": "2026-08-13",
    },
    "validation_e3": {
        "orientation": "high_score=fragile",
        "outcome": "mean_down_capture_vs_GDX",
        "reseeded_after_incident": "2026-08-13",
    },
    "validation_e3b": {
        "orientation": "high_score=upside",
        "outcome": "mean_up_capture_vs_GDX",
        "reseeded_after_incident": "2026-08-13",
    },
}

for sid, cfg in CONFIGS.items():
    missing = [k for k, v in cfg.items() if v is None]
    if missing:
        raise SystemExit(f"{sid}: missing constants {missing}")
    register_variant(lab_dir=lab, signal_id=sid, config=cfg)
    print(f"{sid}: n_trials={n_trials(lab, signal_id=sid)}")
