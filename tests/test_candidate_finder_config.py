from __future__ import annotations

import pytest
from pydantic import ValidationError

from golden_vector.app.config import EXPECTED_CONFIG_FILES, load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.config_models import CandidateFinderConfig


def test_candidate_finder_config_loads_and_is_hashed():
    loaded = load_app_config(ProjectPaths.discover())

    assert ("candidate_finder", "candidate_finder.yaml") in EXPECTED_CONFIG_FILES
    assert loaded.app.candidate_finder.default_top_n == 10
    assert loaded.app.candidate_finder.min_criteria_fraction == 0.67
    assert "candidate_finder" in loaded.file_hashes
    assert any(
        criterion.id == "iv_percentile"
        for criterion in loaded.app.candidate_finder.criteria
    )


def test_candidate_finder_config_rejects_duplicate_criteria():
    payload = _payload()
    payload["criteria"].append(dict(payload["criteria"][0]))

    with pytest.raises(ValidationError):
        CandidateFinderConfig.model_validate(payload)


def test_candidate_finder_config_rejects_unknown_preset_criteria():
    payload = _payload()
    payload["presets"][0]["criteria"].append({"id": "missing", "weight": 1.0})

    with pytest.raises(ValidationError):
        CandidateFinderConfig.model_validate(payload)


def test_candidate_finder_config_rejects_invalid_thresholds():
    payload = _payload()
    payload["min_criteria_fraction"] = 1.5

    with pytest.raises(ValidationError):
        CandidateFinderConfig.model_validate(payload)


def _payload() -> dict:
    return {
        "version": 1,
        "default_top_n": 10,
        "min_criteria_fraction": 0.67,
        "criteria": [
            {
                "id": "down_beta",
                "label": "Down-beta",
                "source_field": "down_beta_core",
                "group": "Sensitivity",
                "default_direction": "high_good",
                "unit": "beta",
            }
        ],
        "presets": [
            {
                "id": "bearish_put",
                "label": "Bearish put screen",
                "options_side": "puts",
                "criteria": [{"id": "down_beta", "weight": 1.0}],
            }
        ],
    }
