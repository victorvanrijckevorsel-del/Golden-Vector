"""Tool B verdict and score helpers."""

from __future__ import annotations

import pandas as pd

from golden_vector.contracts.config_models import VerdictThresholds


def determine_screening_verdict(
    *,
    confidence: str,
    layer1_status: str,
    forward_pe: float | None,
    thresholds: VerdictThresholds,
) -> str:
    if confidence == "INCOMPLETE" or layer1_status == "INCOMPLETE":
        return "INCOMPLETE"
    if forward_pe is not None and forward_pe > 0 and layer1_status == "PASS" and forward_pe < thresholds.strong_candidate_forward_pe_max:
        return "STRONG_CANDIDATE"
    if forward_pe is not None and forward_pe > 0 and forward_pe < thresholds.watchlist_forward_pe_max:
        return "WATCHLIST"
    return "SCREEN_OUT"


def compute_tool_b_score(
    *,
    screening_verdict: str,
    best_upside_pct: float | None,
) -> float | None:
    if screening_verdict == "INCOMPLETE":
        return None

    base = {
        "STRONG_CANDIDATE": 0.85,
        "WATCHLIST": 0.60,
        "SCREEN_OUT": 0.20,
    }[screening_verdict]
    upside_score = _normalize_upside(best_upside_pct)
    return round(100.0 * ((0.7 * base) + (0.3 * upside_score)), 4)


def _normalize_upside(value: float | None) -> float:
    if value is None or pd.isna(value):
        return 0.0
    clipped = max(-0.5, min(float(value), 1.5))
    return (clipped + 0.5) / 2.0
