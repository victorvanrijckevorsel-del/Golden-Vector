"""View-only ranking lenses for the workspace overview.

Per plan v3 §3, lenses are deterministic re-projections of fields already on the
published Tool A row. They are presentation-layer only — never persisted, never
consumed by any model code, never written to any output file.

Cross-cutting rules:
- If `score_eligible` is False on the row → every lens returns ``None``.
- Any non-finite input (NaN, +inf, -inf) → ``None``.
- Lens score ``None`` is rendered as ``-`` in the UI and sorts to the bottom.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from golden_vector.contracts.config_models import ScoringConfig


@dataclass(frozen=True)
class LensSpec:
    """Definition of a single overview lens."""

    id: str
    title: str
    hint: str
    sort_descending: bool
    compute: Callable[[dict[str, Any], ScoringConfig], float | None]


def _is_score_eligible(row: dict[str, Any]) -> bool:
    value = row.get("score_eligible")
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        try:
            if pd.isna(value):
                return False
        except (TypeError, ValueError):
            pass
        return bool(value)
    text = str(value).strip().lower()
    return text in {"true", "1", "yes"}


def _finite_float(value: Any) -> float | None:
    """Coerce to float, return None for missing or non-finite values."""

    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _compute_composite(row: dict[str, Any], scoring_config: ScoringConfig) -> float | None:
    """Default lens — the published Tool A composite score."""

    if not _is_score_eligible(row):
        return None
    return _finite_float(row.get("tool_a_score"))


def _compute_upside_torque(row: dict[str, Any], scoring_config: ScoringConfig) -> float | None:
    """delta_core × max(up_beta_core − down_beta_core, 0).

    Avoids the word "gamma" in user-facing copy: this is "strong delta plus favorable
    upside-regime participation", not a raw gamma reading.
    """

    if not _is_score_eligible(row):
        return None
    delta = _finite_float(row.get("structural_delta_core"))
    up = _finite_float(row.get("up_beta_core"))
    down = _finite_float(row.get("down_beta_core"))
    if delta is None or up is None or down is None:
        return None
    return delta * max(up - down, 0.0)


def _compute_fragility(row: dict[str, Any], scoring_config: ScoringConfig) -> float | None:
    """max(down_beta_core − up_beta_core, 0), gated on delta_core > delta_bands.low_max.

    This is a *negative-skew gap*, not a measure of total stock danger. A medium-delta
    name with a large skew gap can outrank a strong-linkage name with a smaller gap —
    that is correct behavior because the lens measures regime skew, not absolute risk.
    """

    if not _is_score_eligible(row):
        return None
    delta = _finite_float(row.get("structural_delta_core"))
    up = _finite_float(row.get("up_beta_core"))
    down = _finite_float(row.get("down_beta_core"))
    if delta is None or up is None or down is None:
        return None
    if delta <= scoring_config.delta_bands.low_max:
        return None
    return max(down - up, 0.0)


def _compute_cleanliness(row: dict[str, Any], scoring_config: ScoringConfig) -> float | None:
    """Eligible-window mean R² × clamped (1 − residual_vol_52w / total_vol_52w).

    This measures *signal cleanliness* — how much weekly movement is actually explained
    by gold — averaged across eligible windows. It is not a measure of stock attractiveness.
    A lower-torque but cleaner name can outrank a high-torque noisy name; that is correct
    because the lens is about signal-to-noise, not upside.
    """

    if not _is_score_eligible(row):
        return None
    eligible_r2_values: list[float] = []
    for window_id in ("6m", "12m", "3y"):
        window_status = str(row.get(f"window_status_{window_id}") or "").strip().upper()
        if window_status != "ELIGIBLE":
            continue
        r_squared = _finite_float(row.get(f"r_squared_{window_id}"))
        if r_squared is None:
            continue
        eligible_r2_values.append(r_squared)
    if not eligible_r2_values:
        return None
    eligible_r2_mean = sum(eligible_r2_values) / len(eligible_r2_values)

    total_vol = _finite_float(row.get("total_volatility_52w"))
    residual_vol = _finite_float(row.get("residual_volatility_52w"))
    if total_vol is None or total_vol <= 0 or residual_vol is None:
        return None

    signal_ratio = 1.0 - (residual_vol / total_vol)
    if signal_ratio < 0.0:
        signal_ratio = 0.0
    elif signal_ratio > 1.0:
        signal_ratio = 1.0
    return eligible_r2_mean * signal_ratio


LENS_DEFINITIONS: dict[str, LensSpec] = {
    "composite": LensSpec(
        id="composite",
        title="Composite (Tool A score)",
        hint="Overall Tool A rank — delta, gamma, asymmetry, and confidence combined.",
        sort_descending=True,
        compute=_compute_composite,
    ),
    "upside_torque": LensSpec(
        id="upside_torque",
        title="Upside torque",
        hint=(
            "Strong gold linkage plus favorable upside-regime participation — "
            "who benefits most when gold rallies."
        ),
        sort_descending=True,
        compute=_compute_upside_torque,
    ),
    "fragility": LensSpec(
        id="fragility",
        title="Fragility (negative-skew gap)",
        hint=(
            "Negative-skew gap — where a stock's down-gold sensitivity exceeds "
            "its up-gold sensitivity. Not a measure of total stock danger."
        ),
        sort_descending=True,
        compute=_compute_fragility,
    ),
    "cleanliness": LensSpec(
        id="cleanliness",
        title="Cleanliness (signal share)",
        hint=(
            "Clean-signal measure — how much of this stock's weekly movement is "
            "actually explained by gold, averaged across eligible windows. "
            "Not a measure of stock attractiveness."
        ),
        sort_descending=True,
        compute=_compute_cleanliness,
    ),
}

DEFAULT_LENS_ID = "composite"


def resolve_lens(lens_id: str | None) -> LensSpec:
    """Look up a lens, falling back to ``composite`` for unknown / missing ids."""

    candidate = (lens_id or "").strip().lower()
    return LENS_DEFINITIONS.get(candidate, LENS_DEFINITIONS[DEFAULT_LENS_ID])


def compute_lens_score(
    row: dict[str, Any],
    *,
    lens_id: str,
    scoring_config: ScoringConfig,
) -> float | None:
    """Compute one lens score for a single Tool A row dict."""

    lens = resolve_lens(lens_id)
    return lens.compute(row, scoring_config)


def apply_lens(
    tool_a_outputs: pd.DataFrame,
    *,
    lens_id: str,
    scoring_config: ScoringConfig,
) -> pd.DataFrame:
    """Return a copy of ``tool_a_outputs`` with a ``lens_score`` column attached."""

    lens = resolve_lens(lens_id)
    if tool_a_outputs.empty:
        result = tool_a_outputs.copy()
        result["lens_score"] = pd.Series(dtype="float64")
        return result
    result = tool_a_outputs.copy()
    result["lens_score"] = [
        lens.compute(row, scoring_config) for row in result.to_dict(orient="records")
    ]
    return result
