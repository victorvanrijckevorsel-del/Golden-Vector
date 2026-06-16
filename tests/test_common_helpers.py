from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.common.files import (
    atomic_write_bytes,
    atomic_write_file,
    atomic_write_text,
)
from golden_vector.common.eligibility import is_score_eligible, score_eligible_mask
from golden_vector.common.frames import latest_records_by_key
from golden_vector.common.numeric import optional_finite_float, sum_optional_floats
from golden_vector.common.status import combine_statuses
from golden_vector.common.strings import clean_string, unique_strings
from golden_vector.serve.format_helpers import format_dte_suffix


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


def test_latest_records_by_key_normalizes_keys_and_keeps_latest_sort_value():
    frame = pd.DataFrame(
        [
            {"ticker": "nem", "as_of_date": "2026-06-01", "value": 1},
            {"ticker": "NEM", "as_of_date": "2026-06-08", "value": 2},
            {"ticker": "AEM", "as_of_date": "2026-06-03", "value": 3},
        ]
    )

    records = latest_records_by_key(frame, "ticker", sort_column="as_of_date")

    assert records["NEM"]["value"] == 2
    assert records["AEM"]["value"] == 3


def test_sum_optional_floats_ignores_missing_values_and_reports_no_data():
    assert sum_optional_floats([1, None, "2.5", pd.NA]) == pytest.approx(3.5)
    assert sum_optional_floats([None, pd.NA, ""]) is None
    assert sum_optional_floats(None) is None


def test_optional_finite_float_rejects_missing_invalid_and_infinite_values():
    assert optional_finite_float("2.5") == pytest.approx(2.5)
    assert optional_finite_float(None) is None
    assert optional_finite_float(pd.NA) is None
    assert optional_finite_float("not-a-number") is None
    assert optional_finite_float(float("nan")) is None
    assert optional_finite_float(float("inf")) is None


def test_format_dte_suffix_ignores_missing_values():
    assert format_dte_suffix(46) == " (46 DTE)"
    assert format_dte_suffix(None) == ""
    assert format_dte_suffix(pd.NA) == ""
    assert format_dte_suffix(float("nan")) == ""


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


def test_collapsible_text_td_keeps_rows_even():
    from golden_vector.serve.format_helpers import collapsible_text_td

    # Empty -> dash; a single short note renders inline (no tower).
    assert collapsible_text_td([]) == "<td>-</td>"
    assert collapsible_text_td(None) == "<td>-</td>"
    one = collapsible_text_td(["Put candidate is Watch tier."])
    assert one == "<td>Put candidate is Watch tier.</td>"
    assert "<details" not in one

    # Several notes (the tall-tower case) collapse behind a click-to-expand summary,
    # but the full text is still present (just not inline).
    many = collapsible_text_td(
        [
            "Put candidate is Watch tier; spread may be expensive.",
            "Call candidate is Watch tier; spread may be expensive.",
        ]
    )
    assert "<details" in many and "<summary>" in many
    assert "Call candidate is Watch tier" in many  # full text retained

    # A long joined tag string also collapses; HTML is escaped.
    tags = collapsible_text_td("steep_down_beta;frequent_deep_drops;persistent_relative_weakness;thin_history")
    assert "<details" in tags
    assert "<script>" not in collapsible_text_td(["<script>x</script> a very long note that exceeds the inline threshold for sure"])


def test_collapsible_text_td_drops_null_members():
    import pandas as pd

    from golden_vector.serve.format_helpers import collapsible_text_td

    # Null-like members (None, pd.NA, NaN) must be dropped, never rendered as
    # the literal "None" / "<NA>" / "nan".
    mixed = collapsible_text_td([pd.NA, "ok", None, float("nan")])
    assert mixed == "<td>ok</td>"
    assert "None" not in mixed and "NA" not in mixed and "nan" not in mixed

    # An all-null list collapses to the empty dash, same as []/None.
    assert collapsible_text_td([None, pd.NA]) == "<td>-</td>"


def test_option_note_tuple_loader_drops_null_members():
    import pandas as pd

    from golden_vector.hedge.option_artifact_frames import _tuple_value

    # Python list with null members.
    assert _tuple_value([None, "ok", pd.NA]) == ("ok",)
    # JSON-null payload (the on-disk note form) must not surface "None".
    assert _tuple_value('["ok", null, "two"]') == ("ok", "two")
    # All-null / missing inputs stay empty.
    assert _tuple_value([None, pd.NA]) == ()
    assert _tuple_value(None) == ()
