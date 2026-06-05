"""Phase 2A unit tests for the workspace ranking lenses."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.serve.lenses import (
    DEFAULT_LENS_ID,
    LENS_DEFINITIONS,
    apply_lens,
    compute_lens_score,
    resolve_lens,
)


def _scoring():
    return load_app_config(ProjectPaths.discover()).app.scoring


def _eligible_row(**overrides):
    base = {
        "score_eligible": True,
        "score_eligibility_reason": "OK",
        "tool_a_score": 80.0,
        "structural_delta_core": 1.6,
        "up_beta_core": 2.0,
        "down_beta_core": 1.4,
        "structural_gamma_core": -0.3,
        "asymmetry_ratio_core": 1.4,
        "total_volatility_52w": 0.4,
        "residual_volatility_52w": 0.2,
        "downside_volatility_52w": 0.25,
        "r_squared_6m": 0.5,
        "r_squared_12m": 0.6,
        "r_squared_3y": 0.4,
        "window_status_6m": "ELIGIBLE",
        "window_status_12m": "ELIGIBLE",
        "window_status_3y": "ELIGIBLE",
    }
    base.update(overrides)
    return base


def test_resolve_lens_falls_back_to_composite_for_unknown_id():
    assert resolve_lens("not-a-lens").id == DEFAULT_LENS_ID
    assert resolve_lens(None).id == DEFAULT_LENS_ID
    assert resolve_lens("").id == DEFAULT_LENS_ID


def test_lens_definitions_contain_exactly_the_v1_set():
    assert set(LENS_DEFINITIONS) == {"composite", "upside_torque", "fragility", "cleanliness"}


# --- composite -------------------------------------------------------------------------


def test_composite_lens_matches_tool_a_score():
    row = _eligible_row(tool_a_score=87.2)
    assert compute_lens_score(row, lens_id="composite", scoring_config=_scoring()) == 87.2


def test_composite_lens_returns_none_when_score_ineligible():
    row = _eligible_row(score_eligible=False, tool_a_score=87.2)
    assert compute_lens_score(row, lens_id="composite", scoring_config=_scoring()) is None


def test_composite_lens_treats_missing_score_eligible_as_eligible():
    row = _eligible_row(tool_a_score=87.2)
    row.pop("score_eligible")

    assert compute_lens_score(row, lens_id="composite", scoring_config=_scoring()) == 87.2


# --- upside_torque ---------------------------------------------------------------------


def test_upside_torque_lens_uses_delta_times_positive_up_minus_down_gap():
    row = _eligible_row(structural_delta_core=2.0, up_beta_core=2.5, down_beta_core=1.5)
    score = compute_lens_score(row, lens_id="upside_torque", scoring_config=_scoring())
    assert score == pytest.approx(2.0 * 1.0)


def test_upside_torque_lens_clamps_at_zero_when_down_exceeds_up():
    row = _eligible_row(structural_delta_core=1.8, up_beta_core=1.0, down_beta_core=2.0)
    assert compute_lens_score(row, lens_id="upside_torque", scoring_config=_scoring()) == 0.0


def test_upside_torque_lens_returns_none_on_missing_or_non_finite_inputs():
    scoring = _scoring()
    assert compute_lens_score(
        _eligible_row(structural_delta_core=None),
        lens_id="upside_torque",
        scoring_config=scoring,
    ) is None
    assert compute_lens_score(
        _eligible_row(up_beta_core=float("nan")),
        lens_id="upside_torque",
        scoring_config=scoring,
    ) is None
    assert compute_lens_score(
        _eligible_row(down_beta_core=float("inf")),
        lens_id="upside_torque",
        scoring_config=scoring,
    ) is None


# --- fragility -------------------------------------------------------------------------


def test_fragility_lens_returns_none_when_delta_below_low_max_gate():
    scoring = _scoring()
    row = _eligible_row(
        structural_delta_core=scoring.delta_bands.low_max,
        up_beta_core=1.0,
        down_beta_core=2.0,
    )
    assert compute_lens_score(row, lens_id="fragility", scoring_config=scoring) is None


def test_fragility_lens_returns_positive_value_when_down_exceeds_up_above_gate():
    scoring = _scoring()
    row = _eligible_row(
        structural_delta_core=scoring.delta_bands.low_max + 0.5,
        up_beta_core=1.0,
        down_beta_core=2.5,
    )
    assert compute_lens_score(row, lens_id="fragility", scoring_config=scoring) == pytest.approx(1.5)


def test_fragility_lens_clamps_at_zero_when_up_exceeds_down():
    scoring = _scoring()
    row = _eligible_row(
        structural_delta_core=scoring.delta_bands.low_max + 0.5,
        up_beta_core=2.0,
        down_beta_core=1.0,
    )
    assert compute_lens_score(row, lens_id="fragility", scoring_config=scoring) == 0.0


# --- cleanliness -----------------------------------------------------------------------


def test_cleanliness_lens_averages_r_squared_across_eligible_windows_only():
    scoring = _scoring()
    row = _eligible_row(
        r_squared_6m=0.4,
        r_squared_12m=0.6,
        r_squared_3y=0.8,
        window_status_6m="ELIGIBLE",
        window_status_12m="ELIGIBLE",
        window_status_3y="LOW_OBSERVATION",  # excluded
        total_volatility_52w=0.5,
        residual_volatility_52w=0.2,
    )
    # mean of eligible r² = (0.4 + 0.6) / 2 = 0.5; signal_ratio = 1 - 0.2/0.5 = 0.6
    assert compute_lens_score(row, lens_id="cleanliness", scoring_config=scoring) == pytest.approx(0.5 * 0.6)


def test_cleanliness_lens_returns_none_when_total_vol_is_zero_or_missing():
    scoring = _scoring()
    assert compute_lens_score(
        _eligible_row(total_volatility_52w=0.0),
        lens_id="cleanliness",
        scoring_config=scoring,
    ) is None
    assert compute_lens_score(
        _eligible_row(total_volatility_52w=None),
        lens_id="cleanliness",
        scoring_config=scoring,
    ) is None


def test_cleanliness_lens_clamps_signal_ratio_when_residual_exceeds_total():
    scoring = _scoring()
    row = _eligible_row(
        r_squared_6m=0.5,
        r_squared_12m=0.5,
        r_squared_3y=0.5,
        total_volatility_52w=0.3,
        residual_volatility_52w=0.5,  # residual > total → ratio would be negative
    )
    # signal_ratio clamped to 0; lens score = 0.5 * 0 = 0
    assert compute_lens_score(row, lens_id="cleanliness", scoring_config=scoring) == 0.0


def test_cleanliness_lens_returns_none_when_no_eligible_window_has_r_squared():
    scoring = _scoring()
    row = _eligible_row(
        window_status_6m="LOW_OBSERVATION",
        window_status_12m="INELIGIBLE",
        window_status_3y="INELIGIBLE",
    )
    assert compute_lens_score(row, lens_id="cleanliness", scoring_config=scoring) is None


# --- cross-cutting rule: score-ineligible withholds every lens -------------------------


def test_every_lens_returns_none_for_score_ineligible_row():
    scoring = _scoring()
    row = _eligible_row(score_eligible=False)
    for lens_id in LENS_DEFINITIONS:
        assert compute_lens_score(row, lens_id=lens_id, scoring_config=scoring) is None


def test_apply_lens_attaches_lens_score_column():
    scoring = _scoring()
    frame = pd.DataFrame([_eligible_row(tool_a_score=10.0), _eligible_row(tool_a_score=20.0)])
    result = apply_lens(frame, lens_id="composite", scoring_config=scoring)
    assert "lens_score" in result.columns
    assert list(result["lens_score"]) == [10.0, 20.0]


def test_apply_lens_handles_empty_frame_without_error():
    scoring = _scoring()
    result = apply_lens(pd.DataFrame(), lens_id="composite", scoring_config=scoring)
    assert "lens_score" in result.columns
    assert result.empty
