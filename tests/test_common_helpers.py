from __future__ import annotations

import pandas as pd
import pytest

from golden_vector.common.files import (
    atomic_write_bytes,
    atomic_write_file,
    atomic_write_text,
)
from golden_vector.common.eligibility import is_score_eligible, score_eligible_mask
from golden_vector.common.frames import latest_records_by_key, select_finance_source_rows
from golden_vector.common.numeric import (
    align_to_step,
    optional_finite_float,
    rebase_to_base,
    sum_optional_floats,
)
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


def test_select_finance_source_rows_selects_explicit_source_before_key_collapse():
    frame = pd.DataFrame(
        [
            {"ticker": "NEM", "finance_source": "our", "value": 80},
            {"ticker": "NEM", "finance_source": "yahoo", "value": 5},
            {"ticker": "AEM", "finance_source": " OUR ", "value": 70},
        ]
    )

    selected = select_finance_source_rows(
        frame,
        finance_source="our",
        label="test Tool D artifact",
    )

    assert selected[["ticker", "value"]].to_dict(orient="records") == [
        {"ticker": "NEM", "value": 80},
        {"ticker": "AEM", "value": 70},
    ]


def test_select_finance_source_rows_fails_loud_on_nonempty_unlabelled_frame():
    with pytest.raises(ValueError, match="no 'finance_source' column"):
        select_finance_source_rows(
            pd.DataFrame([{"ticker": "NEM", "value": 80}]),
            finance_source="our",
            label="test Tool D artifact",
        )

    empty = select_finance_source_rows(
        pd.DataFrame(),
        finance_source="our",
        label="empty Tool D artifact",
    )
    assert empty.empty


def test_select_finance_source_rows_rejects_noncanonical_requested_source():
    with pytest.raises(ValueError, match="canonical finance source"):
        select_finance_source_rows(
            pd.DataFrame(),
            finance_source="ours",
            label="test Tool D artifact",
        )


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


def test_rebase_to_base_indexes_to_first_finite_nonzero_anchor():
    # Anchor is the first finite, non-zero value -> 100 there; rest scale proportionally.
    assert rebase_to_base([200.0, 220.0, 180.0]) == pytest.approx([100.0, 110.0, 90.0])
    # Different absolute scale, same shape -> identical rebased curve (the whole point):
    # assert the two series produce the SAME output directly, not just equal hardcoded values.
    assert rebase_to_base([2.0, 2.2, 1.8]) == pytest.approx([100.0, 110.0, 90.0])
    assert rebase_to_base([200.0, 220.0, 180.0]) == pytest.approx(
        rebase_to_base([2.0, 2.2, 1.8])
    )


def test_rebase_to_base_nulls_pre_anchor_and_non_finite_points():
    # Leading None/zero cannot anchor; they stay None until the first usable value.
    out = rebase_to_base([None, 0.0, 50.0, 75.0])
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(100.0)
    assert out[3] == pytest.approx(150.0)
    # A non-finite value mid-series becomes a gap, not a crash; the anchor is unchanged.
    gapped = rebase_to_base([10.0, float("nan"), 12.0, float("inf")])
    assert gapped[0] == pytest.approx(100.0)
    assert gapped[1] is None
    assert gapped[2] == pytest.approx(120.0)
    assert gapped[3] is None


def test_rebase_to_base_returns_all_none_without_a_usable_anchor():
    # No finite, non-zero value anywhere -> nothing to index against.
    assert rebase_to_base([None, 0.0, float("nan"), pd.NA]) == [None, None, None, None]
    assert rebase_to_base([]) == []


def test_rebase_to_base_honors_custom_base():
    assert rebase_to_base([4.0, 6.0], base=1.0) == pytest.approx([1.0, 1.5])


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


def test_atomic_write_many_writes_all_on_success(tmp_path):
    from golden_vector.common.files import atomic_write_many

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    written = atomic_write_many(
        [
            (a, lambda p: p.write_text("AA", encoding="utf-8")),
            (b, lambda p: p.write_text("BB", encoding="utf-8")),
        ]
    )
    assert set(written) == {a, b}
    assert a.read_text(encoding="utf-8") == "AA"
    assert b.read_text(encoding="utf-8") == "BB"
    assert not list(tmp_path.glob(".*"))  # no leftover temp/backup siblings


def test_atomic_write_many_staging_failure_leaves_targets_untouched(tmp_path):
    from golden_vector.common.files import atomic_write_many

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("old-a", encoding="utf-8")
    b.write_text("old-b", encoding="utf-8")

    def boom(_p):
        raise RuntimeError("writer boom")

    with pytest.raises(RuntimeError, match="writer boom"):
        atomic_write_many(
            [
                (a, lambda p: p.write_text("new-a", encoding="utf-8")),
                (b, boom),  # staging fails -> nothing is swapped
            ]
        )
    # No live target changed (a was only staged to a temp, never swapped).
    assert a.read_text(encoding="utf-8") == "old-a"
    assert b.read_text(encoding="utf-8") == "old-b"
    assert not list(tmp_path.glob(".*"))


def test_atomic_write_many_rolls_back_prior_contents_on_swap_failure(tmp_path, monkeypatch):
    import golden_vector.common.files as files_mod
    from golden_vector.common.files import atomic_write_many

    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("old-a", encoding="utf-8")
    b.write_text("old-b", encoding="utf-8")

    real_replace = files_mod._replace_with_retry
    calls = {"n": 0}

    def flaky_replace(tmp, path):
        # Fail the SECOND forward swap; allow the rollback restore (call 3) through.
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("swap boom")
        return real_replace(tmp, path)

    monkeypatch.setattr(files_mod, "_replace_with_retry", flaky_replace)

    with pytest.raises(OSError, match="swap boom"):
        atomic_write_many(
            [
                (a, lambda p: p.write_text("new-a", encoding="utf-8")),
                (b, lambda p: p.write_text("new-b", encoding="utf-8")),
            ]
        )
    # a was swapped then rolled back to its prior bytes; b never swapped. Neither
    # target is left half-updated, and temps/backups are cleaned.
    assert a.read_text(encoding="utf-8") == "old-a"
    assert b.read_text(encoding="utf-8") == "old-b"
    assert not list(tmp_path.glob(".*"))


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


def test_align_to_step_matches_html_range_snap_semantics():
    """The ONE copy of the slider-grid math (redesign plan D9): nearest

    ``min + k*step`` position, mirroring how a browser normalizes a range
    input's value before any script runs."""
    assert align_to_step(4477.4, minimum=2000.0, step=1.0) == 4477.0
    assert align_to_step(4477.6, minimum=2000.0, step=1.0) == 4478.0
    assert align_to_step(4477.4, minimum=2000.0, step=25.0) == 4475.0
    assert align_to_step(4477.4, minimum=2000.0, step=0.25) == pytest.approx(4477.5)
    # off-grid minimum: the grid is anchored at min, not at zero
    assert align_to_step(4477.4, minimum=2000.5, step=1.0) == pytest.approx(4477.5)
    # HTML resolves exact-half ties toward positive infinity, not ties-to-even.
    assert align_to_step(4476.5, minimum=2000.0, step=1.0) == 4477.0
    assert align_to_step(2001.0, minimum=2000.5, step=1.0) == pytest.approx(2001.5)
    # A maximum that is not itself on the grid clamps to the highest legal step.
    assert align_to_step(9.0, minimum=0.0, step=6.0, maximum=10.0) == 6.0
    # degenerate inputs pass through untouched — bound-checking is the caller's job
    assert align_to_step(4477.4, minimum=2000.0, step=0.0) == 4477.4
    import math

    assert math.isnan(align_to_step(float("nan"), minimum=2000.0, step=1.0))


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
