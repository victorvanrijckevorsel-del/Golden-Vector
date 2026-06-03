from __future__ import annotations

import pandas as pd

from golden_vector.model.candidate_finder import (
    CriterionDefinition,
    CriterionSelection,
    rank_candidates,
)


def test_candidate_finder_blends_present_criteria_and_sinks_low_coverage_rows():
    frame = pd.DataFrame(
        [
            {"ticker": "A", "down_beta_core": 3.0, "aisc_usd_per_oz": 1900, "iv": 10},
            {"ticker": "B", "down_beta_core": 2.0, "aisc_usd_per_oz": 1700, "iv": None},
            {"ticker": "C", "down_beta_core": 4.0, "aisc_usd_per_oz": None, "iv": None},
        ]
    )

    result = rank_candidates(
        frame,
        criteria=_criteria(),
        selections=[
            CriterionSelection("down_beta"),
            CriterionSelection("aisc"),
            CriterionSelection("iv", direction="low_good"),
        ],
        top_n=1,
        min_criteria_fraction=0.67,
    )

    rows = {row.ticker: row for row in result.rows}

    assert [row.ticker for row in result.rows] == ["A", "B", "C"]
    assert rows["A"].rank_eligible is True
    assert rows["B"].rank_eligible is True
    assert rows["C"].rank_eligible is False
    assert rows["C"].score == 100.0
    assert rows["C"].rank is None
    assert rows["C"].criteria_fraction == 1 / 3
    assert rows["A"].top_n_tally == 2
    assert result.top_lists["down_beta"][0].ticker == "C"


def test_candidate_finder_all_zero_weights_falls_back_to_equal_weights():
    frame = pd.DataFrame(
        [
            {"ticker": "A", "down_beta_core": 1.0, "aisc_usd_per_oz": 2000},
            {"ticker": "B", "down_beta_core": 2.0, "aisc_usd_per_oz": 1000},
        ]
    )

    result = rank_candidates(
        frame,
        criteria=_criteria(),
        selections=[
            CriterionSelection("down_beta", weight=0.0),
            CriterionSelection("aisc", weight=0.0),
        ],
    )

    assert [criterion.weight for criterion in result.selected_criteria] == [1.0, 1.0]
    assert all(row.score == 75.0 for row in result.rows)


def test_candidate_finder_single_criterion_score_equals_percentile():
    frame = pd.DataFrame(
        [
            {"ticker": "A", "down_beta_core": 1.0},
            {"ticker": "B", "down_beta_core": 2.0},
        ]
    )

    result = rank_candidates(
        frame,
        criteria=_criteria(),
        selections=[CriterionSelection("down_beta")],
    )

    rows = {row.ticker: row for row in result.rows}

    assert rows["A"].score == 50.0
    assert rows["B"].score == 100.0


def test_candidate_finder_score_ineligible_treats_tool_a_beta_as_missing():
    frame = pd.DataFrame(
        [
            {
                "ticker": "A",
                "down_beta_core": 3.0,
                "confidence_score": 0.9,
                "score_eligible": False,
            },
            {
                "ticker": "B",
                "down_beta_core": 2.0,
                "confidence_score": 0.7,
                "score_eligible": True,
            },
        ]
    )

    result = rank_candidates(
        frame,
        criteria=_criteria(),
        selections=[
            CriterionSelection("down_beta"),
            CriterionSelection("confidence"),
        ],
        min_criteria_fraction=0.67,
    )
    rows = {row.ticker: row for row in result.rows}

    assert rows["A"].source_score_eligible is False
    assert rows["A"].raw_values["down_beta"] is None
    assert rows["A"].percentiles["down_beta"] is None
    assert rows["A"].rank_eligible is False
    assert rows["B"].rank_eligible is True


def test_candidate_finder_empty_selection_returns_guard_warning():
    result = rank_candidates(
        pd.DataFrame([{"ticker": "A", "down_beta_core": 1.0}]),
        criteria=_criteria(),
        selections=[],
    )

    assert result.rows == ()
    assert "Pick at least one criterion." in result.warnings


def _criteria() -> list[CriterionDefinition]:
    return [
        CriterionDefinition(
            id="down_beta",
            label="Down-beta",
            source_field="down_beta_core",
            group="Sensitivity",
            default_direction="high_good",
            unit="beta",
        ),
        CriterionDefinition(
            id="aisc",
            label="AISC",
            source_field="aisc_usd_per_oz",
            group="Fragility",
            default_direction="high_good",
            unit="usd_per_oz",
        ),
        CriterionDefinition(
            id="iv",
            label="IV percentile",
            source_field="iv",
            group="Options",
            default_direction="low_good",
            unit="percentile",
        ),
        CriterionDefinition(
            id="confidence",
            label="Confidence",
            source_field="confidence_score",
            group="Quality",
            default_direction="high_good",
            unit="score",
        ),
    ]
