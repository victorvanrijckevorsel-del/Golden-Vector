from golden_vector.app.paths import ProjectPaths
from tests.helpers import build_test_paths


def test_discover_uses_repo_root():
    paths = ProjectPaths.discover()
    assert (paths.repo_root / "main.py").exists()
    assert paths.config_dir.name == "config"
    assert paths.runs_dir == paths.repo_root / "data" / "runs"


def test_runtime_directories_are_created(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()

    assert paths.config_dir.exists()
    assert paths.raw_dir.exists()
    assert paths.raw_equities_dir.exists()
    assert paths.manual_screening_dir.exists()
    assert paths.manual_screening_store_path.parent == paths.manual_screening_dir
    assert paths.output_dir.exists()
    assert paths.intermediate_usd_equities_dir.exists()
    assert paths.intermediate_market_snapshots_dir.exists()
    assert paths.intermediate_horizon_metrics_dir.exists()
    assert paths.intermediate_tool_a_profiles_dir.exists()
    assert paths.intermediate_tool_b_dir.exists()
    assert paths.intermediate_status_dir.exists()
    assert paths.output_tool_a_dir.exists()
    assert paths.output_tool_b_dir.exists()
    assert paths.output_combined_dir.exists()
    assert paths.runs_dir.exists()
    assert paths.latest_foundation_manifest_path.parent == paths.intermediate_status_dir
    assert paths.latest_normalized_market_snapshots_path.parent == paths.intermediate_market_snapshots_dir
    assert paths.latest_raw_market_snapshots_path.parent == paths.raw_market_snapshots_dir

    run_dir = paths.ensure_run_dir("sample-run")
    assert run_dir.exists()
