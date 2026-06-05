from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.common.eligibility import is_score_eligible, score_eligible_mask
from golden_vector.common.status import combine_statuses


def test_score_eligible_policy_defaults_missing_to_eligible():
    assert is_score_eligible(None) is True
    assert is_score_eligible(pd.NA) is True
    assert is_score_eligible("") is True
    assert is_score_eligible("false") is False
    assert is_score_eligible("0") is False
    assert is_score_eligible("no") is False
    assert is_score_eligible("yes") is True


def test_score_eligible_mask_uses_shared_policy():
    mask = score_eligible_mask(pd.Series([True, False, None, "0", "yes"]))

    assert mask.tolist() == [True, False, True, False, True]


def test_combine_statuses_uses_fail_warn_pass_precedence_and_skipped_is_neutral():
    assert combine_statuses("PASS", "SKIPPED") == "PASS"
    assert combine_statuses("PASS", "WARN") == "WARN"
    assert combine_statuses("WARN", "FAIL") == "FAIL"


def test_combine_statuses_rejects_unknown_values():
    with pytest.raises(ValueError, match="NOT_IMPLEMENTED"):
        combine_statuses("PASS", "NOT_IMPLEMENTED")
