from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.common.files import (
    atomic_write_bytes,
    atomic_write_file,
    atomic_write_text,
)
from golden_vector.common.eligibility import is_score_eligible, score_eligible_mask
from golden_vector.common.status import combine_statuses
from golden_vector.common.strings import clean_string, unique_strings


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


def test_unique_strings_filters_blank_and_nan_like_values():
    frame = pd.DataFrame({"run_id": ["b", "", None, "nan", "a", "b"]})

    assert unique_strings(frame, "run_id") == ["a", "b"]
    assert clean_string(" nan ") is None


def test_atomic_write_helpers_replace_existing_files(tmp_path):
    text_path = tmp_path / "status.json"
    bytes_path = tmp_path / "payload.bin"
    text_path.write_text("old", encoding="utf-8")
    bytes_path.write_bytes(b"old")

    atomic_write_text(text_path, "new")
    atomic_write_bytes(bytes_path, b"newer")

    assert text_path.read_text(encoding="utf-8") == "new"
    assert bytes_path.read_bytes() == b"newer"
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_write_file_keeps_existing_file_when_writer_fails(tmp_path):
    target = tmp_path / "payload.parquet"
    target.write_text("old", encoding="utf-8")

    def failing_writer(path):
        path.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        atomic_write_file(target, failing_writer)

    assert target.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob("*.tmp"))
