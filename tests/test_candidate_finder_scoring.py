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


def test_candidate_finder_zero_weight_disables_criterion_when_others_are_active():
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
            CriterionSelection("down_beta", weight=1.0),
            CriterionSelection("aisc", weight=0.0),
        ],
    )

    assert [criterion.id for criterion in result.selected_criteria] == ["down_beta"]
    assert "aisc" not in result.top_lists
    assert all(row.selected_criteria_count == 1 for row in result.rows)
    assert all("aisc" not in row.raw_values for row in result.rows)
    assert "Zero-weight criteria disabled: aisc." in result.warnings


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


def test_candidate_finder_omits_universally_missing_criteria_from_coverage_gate():
    frame = pd.DataFrame(
        [
            {
                "ticker": "A",
                "down_beta_core": 3.0,
                "aisc_usd_per_oz": 1800,
                "confidence_score": 0.9,
            },
            {
                "ticker": "B",
                "down_beta_core": 2.0,
                "aisc_usd_per_oz": 1700,
                "confidence_score": 0.8,
            },
        ]
    )

    result = rank_candidates(
        frame,
        criteria=_criteria(),
        selections=[
            CriterionSelection("down_beta"),
            CriterionSelection("aisc"),
            CriterionSelection("confidence"),
            CriterionSelection("iv", direction="low_good"),
        ],
        min_criteria_fraction=0.75,
    )
    rows = {row.ticker: row for row in result.rows}

    assert [criterion.id for criterion in result.selected_criteria] == [
        "down_beta",
        "aisc",
        "confidence",
    ]
    assert all(row.rank_eligible for row in rows.values())
    assert all(row.selected_criteria_count == 3 for row in rows.values())
    assert "iv" not in rows["A"].missing_criteria
    assert any("every row is missing: iv" in item for item in result.warnings)


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


def test_score_eligible_gate_applies_to_every_candidate_criterion():
    # Degraded rows are excluded from rankings globally, not just for Tool A beta fields.
    # That keeps non-beta screens (confidence, AISC, valuation, etc.) from re-admitting stale data.
    frame = pd.DataFrame(
        [
            {
                "ticker": "DEGRADED",
                "confidence_score": 0.99,
                "aisc_usd_per_oz": 900,
                "score_eligible": False,
            },
            {
                "ticker": "HEALTHY",
                "confidence_score": 0.70,
                "aisc_usd_per_oz": 1500,
                "score_eligible": True,
            },
        ]
    )

    result = rank_candidates(
        frame,
        criteria=_criteria(),
        selections=[
            CriterionSelection("confidence"),
            CriterionSelection("aisc"),
        ],
        min_criteria_fraction=1.0,
    )
    rows = {row.ticker: row for row in result.rows}

    assert rows["DEGRADED"].raw_values["confidence"] is None
    assert rows["DEGRADED"].raw_values["aisc"] is None
    assert rows["DEGRADED"].rank_eligible is False
    assert rows["DEGRADED"].score is None
    assert rows["HEALTHY"].rank == 1
    assert [entry.ticker for entry in result.top_lists["confidence"]] == ["HEALTHY"]
    assert [entry.ticker for entry in result.top_lists["aisc"]] == ["HEALTHY"]


def test_candidate_finder_per_window_beta_still_excludes_score_ineligible():
    # Regression (fleet review HIGH): a degraded (score_eligible=False) ticker must be excluded
    # from the ranking under a PER-WINDOW beta selection exactly as it is under the blend — picking
    # a horizon must not silently re-admit degraded rows. Healthy control proves the screen works.
    per_window_down_beta = CriterionDefinition(
        id="down_beta",
        label="Down-beta",
        description="Gold downside sensitivity.",
        source_field="down_beta_6m",
        group="Sensitivity",
        default_direction="high_good",
        unit="beta",
    )
    frame = pd.DataFrame(
        [
            {"ticker": "DEGRADED", "down_beta_6m": 3.0, "confidence_score": 0.9, "score_eligible": False},
            {"ticker": "HEALTHY", "down_beta_6m": 2.0, "confidence_score": 0.7, "score_eligible": True},
        ]
    )

    result = rank_candidates(
        frame,
        criteria=[per_window_down_beta] + [c for c in _criteria() if c.id != "down_beta"],
        selections=[
            CriterionSelection("down_beta"),
            CriterionSelection("confidence"),
        ],
        min_criteria_fraction=0.67,
    )
    rows = {row.ticker: row for row in result.rows}

    assert rows["DEGRADED"].raw_values["down_beta"] is None
    assert rows["DEGRADED"].percentiles["down_beta"] is None
    assert rows["DEGRADED"].rank_eligible is False
    assert rows["HEALTHY"].rank_eligible is True


def test_candidate_finder_empty_selection_returns_guard_warning():
    result = rank_candidates(
        pd.DataFrame([{"ticker": "A", "down_beta_core": 1.0}]),
        criteria=_criteria(),
        selections=[],
    )

    assert result.rows == ()
    assert "Pick at least one criterion." in result.warnings


def test_candidate_finder_ignores_duplicate_selected_criteria():
    result = rank_candidates(
        pd.DataFrame(
            [
                {"ticker": "A", "down_beta_core": 1.0},
                {"ticker": "B", "down_beta_core": 2.0},
            ]
        ),
        criteria=_criteria(),
        selections=[
            CriterionSelection("down_beta"),
            CriterionSelection("down_beta", weight=5.0),
        ],
    )

    assert len(result.selected_criteria) == 1
    assert result.selected_criteria[0].weight == 1.0
    assert "Duplicate criterion ignored: down_beta" in result.warnings


def test_candidate_finder_defaults_invalid_direction_and_weight_inputs():
    result = rank_candidates(
        pd.DataFrame(
            [
                {"ticker": "A", "down_beta_core": 1.0, "aisc_usd_per_oz": 2000},
                {"ticker": "B", "down_beta_core": 2.0, "aisc_usd_per_oz": 1000},
            ]
        ),
        criteria=_criteria(),
        selections=[
            CriterionSelection(  # type: ignore[arg-type]
                "down_beta",
                direction="banana",
                weight="bad",
            ),
            CriterionSelection("aisc", weight=-1.0),
        ],
    )

    criteria = {criterion.id: criterion for criterion in result.selected_criteria}

    assert criteria["down_beta"].direction == "high_good"
    assert criteria["down_beta"].weight == 1.0
    assert "aisc" not in criteria
    assert any("Invalid direction for down_beta" in item for item in result.warnings)
    assert any("Invalid weight for down_beta" in item for item in result.warnings)
    assert any("Negative weight for aisc" in item for item in result.warnings)
    assert "Zero-weight criteria disabled: aisc." in result.warnings


def _criteria() -> list[CriterionDefinition]:
    return [
        CriterionDefinition(
            id="down_beta",
            label="Down-beta",
            description="Gold downside sensitivity.",
            source_field="down_beta_core",
            group="Sensitivity",
            default_direction="high_good",
            unit="beta",
        ),
        CriterionDefinition(
            id="aisc",
            label="AISC",
            description="All-in cost to mine one ounce.",
            source_field="aisc_usd_per_oz",
            group="Fragility",
            default_direction="high_good",
            unit="usd_per_oz",
        ),
        CriterionDefinition(
            id="iv",
            label="IV percentile",
            description="Option price level vs peers.",
            source_field="iv",
            group="Options",
            default_direction="low_good",
            unit="percentile",
        ),
        CriterionDefinition(
            id="confidence",
            label="Confidence",
            description="Historical model fit.",
            source_field="confidence_score",
            group="Quality",
            default_direction="high_good",
            unit="score",
        ),
    ]
