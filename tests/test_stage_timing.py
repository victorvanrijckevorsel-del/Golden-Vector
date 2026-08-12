from time import perf_counter

from golden_vector.common.stage_timing import record_step_timing
from golden_vector.model import pipeline as pipeline_module


def test_record_step_timing_records_duration_only_by_default():
    timings: dict[str, dict[str, object]] = {}

    record_step_timing(timings, "load_inputs", perf_counter())

    assert list(timings) == ["load_inputs"]
    entry = timings["load_inputs"]
    assert list(entry) == ["duration_seconds"]
    assert isinstance(entry["duration_seconds"], float)
    assert entry["duration_seconds"] >= 0.0


def test_record_step_timing_includes_row_counts_and_extra():
    timings: dict[str, dict[str, object]] = {}

    record_step_timing(
        timings,
        "build_outputs",
        perf_counter(),
        rows_built=12,
        rows_persisted=4,
        extra={"note": "ok", "build_keep_ratio": 3.0},
    )

    entry = timings["build_outputs"]
    assert entry["rows_built"] == 12
    assert entry["rows_persisted"] == 4
    assert entry["note"] == "ok"
    assert entry["build_keep_ratio"] == 3.0
    assert entry["duration_seconds"] >= 0.0


def test_record_step_timing_zero_row_counts_are_recorded_not_dropped():
    timings: dict[str, dict[str, object]] = {}

    record_step_timing(timings, "empty_step", perf_counter(), rows_built=0, rows_persisted=0)

    assert timings["empty_step"]["rows_built"] == 0
    assert timings["empty_step"]["rows_persisted"] == 0


def test_pipeline_alias_points_at_the_shared_helper():
    assert pipeline_module._record_step_timing is record_step_timing
