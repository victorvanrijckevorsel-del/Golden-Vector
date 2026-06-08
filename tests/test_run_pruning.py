import json
from pathlib import Path

from golden_vector.app.run_pruning import prune_runs
from golden_vector.cli import run_prune_runs
from tests.helpers import build_test_paths


def test_prune_runs_dry_run_default_preserves_all_retained_manifest_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    old_tool_run = "20260601T000000Z-tool-a-old"
    old_option_run = "20260601T000001Z-option-artifacts-old"
    mid_tool_run = "20260602T000000Z-tool-a-mid"
    mid_option_run = "20260602T000001Z-option-artifacts-mid"
    new_tool_run = "20260603T000000Z-tool-a-new"
    new_option_run = "20260603T000001Z-option-artifacts-new"
    old_tool, old_option = _write_artifacts(
        paths,
        tool_run_id=old_tool_run,
        option_run_id=old_option_run,
    )
    mid_tool, mid_option = _write_artifacts(
        paths,
        tool_run_id=mid_tool_run,
        option_run_id=mid_option_run,
    )
    new_tool, new_option = _write_artifacts(
        paths,
        tool_run_id=new_tool_run,
        option_run_id=new_option_run,
    )
    _write_model_state(
        paths,
        name="model_state_old.json",
        generated_at="2026-06-01T00:00:00Z",
        tool_path=old_tool,
        option_path=old_option,
        run_ids=(old_tool_run, old_option_run),
    )
    _write_model_state(
        paths,
        name="model_state_mid.json",
        generated_at="2026-06-02T00:00:00Z",
        tool_path=mid_tool,
        option_path=mid_option,
        run_ids=(mid_tool_run, mid_option_run),
    )
    latest_payload = _write_model_state(
        paths,
        name="model_state_new.json",
        generated_at="2026-06-03T00:00:00Z",
        tool_path=new_tool,
        option_path=new_option,
        run_ids=(new_tool_run, new_option_run),
    )
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(latest_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for run_id in (
        old_tool_run,
        old_option_run,
        mid_tool_run,
        mid_option_run,
        new_tool_run,
        new_option_run,
    ):
        (paths.runs_dir / run_id).mkdir(parents=True)
        (paths.runs_dir / run_id / "metadata.json").write_text("{}", encoding="utf-8")

    report = prune_runs(paths, keep_model_states=2)

    assert report.dry_run is True
    assert old_tool.exists()
    assert old_option.exists()
    assert (paths.runs_dir / old_tool_run).exists()
    assert any(candidate.path == old_tool for candidate in report.candidates)
    assert any(candidate.path == old_option for candidate in report.candidates)
    assert any(
        candidate.path == paths.model_state_manifests_dir / "model_state_old.json"
        for candidate in report.candidates
    )
    assert all(candidate.path != mid_tool for candidate in report.candidates)
    assert all(candidate.path != mid_option for candidate in report.candidates)
    assert all(candidate.path != new_tool for candidate in report.candidates)
    assert all(candidate.path != new_option for candidate in report.candidates)

    applied = prune_runs(paths, keep_model_states=2, apply=True)

    assert applied.dry_run is False
    assert not old_tool.exists()
    assert not old_option.exists()
    assert not (paths.runs_dir / old_tool_run).exists()
    assert not (paths.runs_dir / old_option_run).exists()
    assert mid_tool.exists()
    assert mid_option.exists()
    assert new_tool.exists()
    assert new_option.exists()
    assert (paths.runs_dir / mid_tool_run).exists()
    assert (paths.runs_dir / mid_option_run).exists()
    assert (paths.runs_dir / new_tool_run).exists()
    assert (paths.runs_dir / new_option_run).exists()
    for model_state_path in applied.retained_model_state_paths:
        payload = json.loads(model_state_path.read_text(encoding="utf-8"))
        for artifact in payload["artifacts"].values():
            artifact_path = paths.repo_root / artifact["path"]
            assert artifact_path.exists()


def test_prune_runs_cli_is_dry_run_without_apply(tmp_path, capsys):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    tool_run = "20260601T000000Z-tool-a-old"
    option_run = "20260601T000001Z-option-artifacts-old"
    tool_path, option_path = _write_artifacts(
        paths,
        tool_run_id=tool_run,
        option_run_id=option_run,
    )
    _write_model_state(
        paths,
        name="model_state_old.json",
        generated_at="2026-06-01T00:00:00Z",
        tool_path=tool_path,
        option_path=option_path,
        run_ids=(tool_run, option_run),
    )

    exit_code = run_prune_runs(paths, keep_model_states=1, apply=False)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Run pruning: DRY RUN" in output
    assert "No files were deleted" in output
    assert tool_path.exists()
    assert option_path.exists()


def test_prune_runs_preserves_option_signal_history_store(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    tool_run = "20260601T000000Z-tool-a-current"
    option_run = "20260601T000001Z-option-artifacts-current"
    tool_path, option_path = _write_artifacts(
        paths,
        tool_run_id=tool_run,
        option_run_id=option_run,
    )
    latest_payload = _write_model_state(
        paths,
        name="model_state_current.json",
        generated_at="2026-06-01T00:00:00Z",
        tool_path=tool_path,
        option_path=option_path,
        run_ids=(tool_run, option_run),
    )
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(latest_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    history = paths.output_options_dir / "option_signal_history.parquet"
    history.write_text("retained option signal history\n", encoding="utf-8")
    orphan = (
        paths.output_options_dir
        / "option_selected_candidates_latest_20260501T000001Z-orphan.parquet"
    )
    orphan.write_text("old option artifact\n", encoding="utf-8")

    report = prune_runs(paths, keep_model_states=1, apply=True)

    assert history.exists()
    assert orphan in report.deleted_paths
    assert not orphan.exists()
    assert all(candidate.path != history for candidate in report.candidates)


def test_prune_runs_apply_is_noop_without_any_model_state_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    run_dir = paths.runs_dir / "20260601T000000Z-tool-a-old"
    run_dir.mkdir(parents=True)
    artifact = paths.output_tool_a_dir / "tool_a_latest_20260601T000000Z-tool-a-old.parquet"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("old\n", encoding="utf-8")

    report = prune_runs(paths, apply=True)

    assert report.candidates == ()
    assert report.deleted_paths == ()
    assert "No readable retained model-state manifests" in report.warnings[0]
    assert run_dir.exists()
    assert artifact.exists()


def test_prune_runs_apply_is_noop_when_only_model_state_is_unprotectable(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    run_dir = paths.runs_dir / "20260601T000000Z-tool-a-old"
    run_dir.mkdir(parents=True)
    artifact = paths.output_tool_a_dir / "tool_a_latest_20260601T000000Z-tool-a-old.parquet"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("old\n", encoding="utf-8")
    paths.latest_model_state_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_model_state_manifest_path.write_text(
        json.dumps({"state": "complete"}, sort_keys=True),
        encoding="utf-8",
    )

    report = prune_runs(paths, apply=True)

    assert report.candidates == ()
    assert report.deleted_paths == ()
    assert any("non-protectable model-state" in warning for warning in report.warnings)
    assert any("No readable retained model-state" in warning for warning in report.warnings)
    assert run_dir.exists()
    assert artifact.exists()


def _write_artifacts(
    paths,
    *,
    tool_run_id: str,
    option_run_id: str,
) -> tuple[Path, Path]:
    tool_path = paths.output_tool_a_dir / f"tool_a_latest_{tool_run_id}.parquet"
    option_path = (
        paths.output_options_dir
        / f"option_candidate_slots_latest_{option_run_id}.parquet"
    )
    tool_path.parent.mkdir(parents=True, exist_ok=True)
    option_path.parent.mkdir(parents=True, exist_ok=True)
    tool_path.write_text(f"tool {tool_run_id}\n", encoding="utf-8")
    option_path.write_text(f"option {option_run_id}\n", encoding="utf-8")
    return tool_path, option_path


def _write_model_state(
    paths,
    *,
    name: str,
    generated_at: str,
    tool_path: Path,
    option_path: Path,
    run_ids: tuple[str, str],
) -> dict[str, object]:
    payload: dict[str, object] = {
        "generated_at_utc": generated_at,
        "artifacts": {
            "tool_a": {
                "path": tool_path.relative_to(paths.repo_root).as_posix(),
                "source_run_ids": [run_ids[0]],
                "snapshot_refresh_run_ids": [run_ids[0]],
            },
            "option_candidate_slots": {
                "path": option_path.relative_to(paths.repo_root).as_posix(),
                "source_run_ids": [run_ids[1]],
                "snapshot_refresh_run_ids": [run_ids[1]],
            },
        },
    }
    path = paths.model_state_manifests_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
