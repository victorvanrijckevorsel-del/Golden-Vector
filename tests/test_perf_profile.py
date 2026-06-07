from golden_vector.app.model_state import write_current_model_state_manifest
from golden_vector.app.perf_profile import _real_tool_a_reconciliation
from tests.helpers import build_test_paths


def test_perf_profile_reconciles_against_real_tool_a_stage_timing(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    write_current_model_state_manifest(
        paths=paths,
        config_hash="hash",
        parent_refresh_id="parent-refresh",
        stage_timings={"tool_a": {"duration_seconds": 10.0}},
    )

    assert _real_tool_a_reconciliation(paths=paths, harness_seconds=10.5)["status"] == "ok"
    diverged = _real_tool_a_reconciliation(paths=paths, harness_seconds=5.0)
    assert diverged["status"] == "diverged"
    assert diverged["ratio"] == 0.5
