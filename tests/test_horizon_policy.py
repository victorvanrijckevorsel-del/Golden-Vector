"""Milestone C1/C2: horizon policy config + de-60d signal layer + history migration.

Pins the resolved C decisions: signal horizon is one explicit config knob (the
published Signal never silently goes UNAVAILABLE when 60 leaves the set),
optionability is judged on core horizons only, and the wide 60d/90d history
backfills into the long form so the stored IV-rank series survives.
"""

from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import HedgeReadinessConfig
from golden_vector.features.options import _optionability_tier
from golden_vector.hedge.option_signals import (
    LONG_HISTORY_COLUMNS,
    _append_history,
    _history_for_ticker,
    _iv_rank,
    _normalize_history,
)


def _hedge_config(**overrides):
    # model_copy(update=...) skips validators; rebuild through validation.
    config = load_app_config(ProjectPaths.discover()).app.hedge_readiness
    data = config.model_dump()
    data.update(overrides)
    return HedgeReadinessConfig.model_validate(data)


def test_signal_horizon_must_be_a_target_horizon():
    with pytest.raises(ValueError, match="option_signal_horizon_days"):
        _hedge_config(option_signal_horizon_days=45)


def test_core_optionability_horizons_must_be_target_subset():
    with pytest.raises(ValueError, match="optionability_core_horizons"):
        _hedge_config(optionability_core_horizons=[60, 365])


def test_every_display_horizon_needs_a_dte_band():
    with pytest.raises(ValueError, match="option_dte_bands"):
        _hedge_config(
            target_horizons_days=[60, 90, 120, 180],
            display_horizons_days=[60, 90, 120, 180],
        )


def test_long_dated_horizon_set_validates_with_bands_and_core():
    config = _hedge_config(
        target_horizons_days=[90, 180, 230],
        display_horizons_days=[90, 180, 230],
        option_dte_bands={90: [75, 104], 180: [150, 209], 230: [210, 320]},
        option_signal_horizon_days=90,
        optionability_core_horizons=[90, 180],
    )
    assert config.option_signal_horizon_days == 90


def test_optionability_judged_on_core_horizons_only():
    row = {
        "options_available": True,
        "total_open_interest": 5000,
        "put_iv_25d_90d": 0.4,
        "put_iv_25d_180d": 0.45,
        # No LEAPS quote at 550d — must NOT degrade the name.
        "put_iv_25d_550d": None,
    }
    tier = _optionability_tier(
        row=row,
        target_horizons_days=(90, 180, 550),
        optionability_core_horizons=(90, 180),
        open_interest_threshold=1000,
    )
    assert tier == "directly_hedgeable"

    legacy_tier = _optionability_tier(
        row=row,
        target_horizons_days=(90, 180, 550),
        optionability_core_horizons=(),
        open_interest_threshold=1000,
    )
    assert legacy_tier == "thin"


def test_legacy_wide_history_backfills_to_long_form():
    legacy = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": "2026-06-01",
                "quote_snapshot_run_id": "run-1",
                "benchmark_symbol": "GDX",
                "skew_residual_60d": 0.03,
                "skew_residual_90d": 0.02,
                "atm_iv_60d": 0.35,
                "iv_rv_ratio": 1.2,
            }
        ]
    )

    normalized = _normalize_history(legacy)

    assert list(normalized.columns) == list(LONG_HISTORY_COLUMNS)
    assert len(normalized.index) == 2
    row_60 = normalized[normalized["signal_horizon_days"] == 60].iloc[0]
    assert row_60["skew_residual"] == pytest.approx(0.03)
    assert row_60["atm_iv"] == pytest.approx(0.35)
    assert row_60["iv_rv_ratio"] == pytest.approx(1.2)
    row_90 = normalized[normalized["signal_horizon_days"] == 90].iloc[0]
    assert row_90["skew_residual"] == pytest.approx(0.02)
    assert pd.isna(row_90["atm_iv"])


def test_iv_rank_series_survives_backfill_at_the_boundary():
    legacy = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": f"2026-05-{day:02d}",
                "quote_snapshot_run_id": f"run-{day}",
                "benchmark_symbol": "GDX",
                "skew_residual_60d": 0.01,
                "skew_residual_90d": None,
                "atm_iv_60d": 0.30 + day / 100.0,
                "iv_rv_ratio": 1.0,
            }
            for day in range(1, 11)
        ]
    )
    normalized = _normalize_history(legacy)
    history_60 = _history_for_ticker(normalized, "NEM", signal_horizon_days=60)

    rank = _iv_rank(current=0.36, history_for_ticker=history_60, min_samples=5)

    # 0.31..0.40 series: six values (0.31..0.36) are <= 0.36 -> 60th percentile.
    assert rank == pytest.approx(60.0)
    # The 90d series is empty pre-migration: calm None, never a crash.
    history_90 = _history_for_ticker(normalized, "NEM", signal_horizon_days=90)
    assert (
        _iv_rank(current=0.36, history_for_ticker=history_90, min_samples=5) is None
    )


def test_append_history_dedupes_per_horizon():
    base = _normalize_history(
        pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": "2026-06-01",
                    "quote_snapshot_run_id": "run-1",
                    "benchmark_symbol": "GDX",
                    "signal_horizon_days": 60,
                    "skew_residual": 0.01,
                    "atm_iv": 0.30,
                    "iv_rv_ratio": 1.0,
                }
            ]
        )
    )
    incoming = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": "2026-06-01",
                "quote_snapshot_run_id": "run-2",
                "benchmark_symbol": "GDX",
                "signal_horizon_days": 60,
                "skew_residual": 0.02,
                "atm_iv": 0.31,
                "iv_rv_ratio": 1.1,
            },
            {
                "ticker": "NEM",
                "as_of_date": "2026-06-01",
                "quote_snapshot_run_id": "run-2",
                "benchmark_symbol": "GDX",
                "signal_horizon_days": 90,
                "skew_residual": 0.03,
                "atm_iv": 0.32,
                "iv_rv_ratio": 1.2,
            },
        ]
    )

    result = _append_history(base, incoming)

    assert len(result.index) == 2
    row_60 = result[result["signal_horizon_days"] == 60].iloc[0]
    assert row_60["skew_residual"] == pytest.approx(0.02)


def test_backfill_skips_missing_90d_residuals_nan_safe():
    """Audit H2: to_dict() yields NaN for missing values and `nan is not None`
    is True — missing 90d residuals must NOT manufacture 90d rows."""

    legacy = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": "2026-06-01",
                "quote_snapshot_run_id": "run-1",
                "benchmark_symbol": "GDX",
                "skew_residual_60d": 0.03,
                "skew_residual_90d": None,
                "atm_iv_60d": 0.35,
                "iv_rv_ratio": 1.2,
            },
            {
                "ticker": "NEM",
                "as_of_date": "2026-06-02",
                "quote_snapshot_run_id": "run-2",
                "benchmark_symbol": "GDX",
                "skew_residual_60d": 0.04,
                "skew_residual_90d": 0.02,
                "atm_iv_60d": 0.36,
                "iv_rv_ratio": 1.3,
            },
        ]
    )

    normalized = _normalize_history(legacy)

    rows_90 = normalized[normalized["signal_horizon_days"] == 90]
    assert len(rows_90.index) == 1  # only the day that HAD a 90d residual
    assert rows_90.iloc[0]["as_of_date"] == "2026-06-02"
    assert len(normalized[normalized["signal_horizon_days"] == 60].index) == 2


def test_skew_curve_points_cover_long_dated_horizons():
    """Audit H1 (triple-confirmed): tradable long-dated quotes must produce
    chart points with real IV at 230/550 — the 45-150 signal-area clamp must
    never pre-filter the per-horizon chart frames."""

    from golden_vector.hedge.option_signals import _skew_curve_points_frame
    from tests.test_option_horizon_selection import _metric as liquidity_metric

    config = load_app_config(ProjectPaths.discover()).app
    metrics_by_ticker = {
        "NEM": (
            liquidity_metric(side="P", expiration="2027-02-19", days_to_expiry=240),
            liquidity_metric(side="C", expiration="2027-02-19", days_to_expiry=240),
            liquidity_metric(side="P", expiration="2027-11-19", days_to_expiry=500),
        ),
    }

    frame = _skew_curve_points_frame(
        metrics_by_ticker=metrics_by_ticker,
        app_config=config,
    )

    rows_230 = frame[(frame["horizon_days"] == 230) & (frame["iv"].notna())]
    rows_550 = frame[(frame["horizon_days"] == 550) & (frame["iv"].notna())]
    assert not rows_230.empty, "230d band must carry IV from DTE-240 quotes"
    assert not rows_550.empty, "550d band must carry IV from DTE-500 quotes"


def test_limited_history_until_enough_usable_observations():
    """Audit M1: backfilled 90d rows have no ATM IV; the cost lane must show
    LIMITED_HISTORY (not RICH/CHEAP) until IV-rank's own series is deep
    enough."""

    legacy = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": f"2026-05-{day:02d}",
                "quote_snapshot_run_id": f"run-{day}",
                "benchmark_symbol": "GDX",
                "skew_residual_60d": 0.01,
                "skew_residual_90d": 0.01,
                "atm_iv_60d": 0.30,
                "iv_rv_ratio": 1.0,
            }
            for day in range(1, 26)
        ]
    )
    normalized = _normalize_history(legacy)
    history_90 = _history_for_ticker(normalized, "NEM", signal_horizon_days=90)

    # 25 backfilled rows exist at 90d, but ZERO usable ATM IV observations.
    assert len(history_90.index) == 25
    usable = pd.to_numeric(history_90["atm_iv"], errors="coerce").notna().sum()
    assert usable == 0
    assert _iv_rank(current=0.35, history_for_ticker=history_90, min_samples=20) is None
