import hashlib
import json
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

import golden_vector.app.replay_manifest as replay_manifest
from golden_vector.app.config import expected_config_paths
from golden_vector.app.replay_manifest import (
    update_manifest_with_foundation,
    write_initial_replay_manifest,
)
from golden_vector.app.run_context import RunContext
from golden_vector.cli import run_verify_replay
from tests.helpers import build_test_paths


def test_phase1_creates_manifest_and_snapshots(tmp_path):
    paths = _prepare_paths(tmp_path)
    context = _start_context(paths)

    manifest_path = write_initial_replay_manifest(context)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 1
    assert manifest["run_id"] == context.run_id
    assert manifest["command"] == "tool-a"
    assert manifest["foundation_run_consumed"] is None
    assert manifest["foundation_load_status"] == "not-applicable"
    assert set(manifest["git"]) == {"commit", "dirty", "unavailable_reason"}

    config_names = {entry["name"] for entry in manifest["configs"]}
    assert config_names == {path.name for path in expected_config_paths(paths).values()}

    for entry in manifest["configs"]:
        original_path = paths.repo_root / entry["original_path"]
        snapshot_path = context.run_dir / entry["snapshot_path"]
        assert snapshot_path.exists()
        assert entry["sha256"] == _sha256(original_path)
        assert entry["sha256"] == _sha256(snapshot_path)

    manual_data = manifest["manual_data"]
    assert manual_data is not None
    manual_snapshot = context.run_dir / manual_data["snapshot_path"]
    assert manual_snapshot.exists()
    assert manual_data["sha256"] == _sha256(manual_snapshot)


def test_phase1_handles_missing_git_gracefully(tmp_path, monkeypatch):
    paths = _prepare_paths(tmp_path)
    context = _start_context(paths)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git unavailable")

    monkeypatch.setattr(replay_manifest.subprocess, "run", fake_run)

    manifest_path = write_initial_replay_manifest(context)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["commit"] is None
    assert manifest["git"]["dirty"] is None
    assert "git unavailable" in manifest["git"]["unavailable_reason"]


def test_phase1_records_dirty_working_tree(tmp_path):
    paths = _prepare_paths(tmp_path)
    _initialize_git_repo(paths.repo_root)
    (paths.repo_root / "tracked.txt").write_text("changed\n", encoding="utf-8")
    context = _start_context(paths)

    manifest_path = write_initial_replay_manifest(context)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["git"]["commit"]
    assert manifest["git"]["dirty"] is True
    assert manifest["git"]["unavailable_reason"] is None


def test_phase1_handles_missing_manual_db_for_init(tmp_path):
    paths = _prepare_paths(tmp_path, manual_db=False)
    context = _start_context(paths, command="manual-data")

    manifest_path = write_initial_replay_manifest(context)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["manual_data"] is None


def test_phase1_hard_fails_on_missing_config(tmp_path):
    paths = _prepare_paths(tmp_path)
    paths.config_path("scoring.yaml").unlink()
    context = _start_context(paths)

    with pytest.raises(FileNotFoundError, match="scoring.yaml"):
        write_initial_replay_manifest(context)


def test_phase1_hard_fails_on_locked_sqlite(tmp_path, monkeypatch):
    paths = _prepare_paths(tmp_path)
    context = _start_context(paths)
    real_connect = replay_manifest.sqlite3.connect

    def fake_connect(database, *args, **kwargs):
        if kwargs.get("uri") and "mode=ro" in str(database):
            raise sqlite3.OperationalError("database is locked")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(replay_manifest.sqlite3, "connect", fake_connect)

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        write_initial_replay_manifest(context)


def test_manifest_config_list_matches_load_app_config(tmp_path):
    paths = _prepare_paths(tmp_path)
    context = _start_context(paths)

    manifest_path = write_initial_replay_manifest(context)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_config_names = {entry["name"] for entry in manifest["configs"]}
    expected_names = {path.name for path in expected_config_paths(paths).values()}
    assert manifest_config_names == expected_names


def test_phase2_updates_foundation_block(tmp_path):
    paths = _prepare_paths(tmp_path)
    context = _start_context(paths)
    write_initial_replay_manifest(context)
    foundation_manifest_path = _write_foundation_manifest(paths)

    update_manifest_with_foundation(
        context.run_dir,
        foundation_run_id="foundation-run",
        foundation_manifest_path=foundation_manifest_path,
    )

    manifest = json.loads(
        (context.run_dir / "replay_manifest.json").read_text(encoding="utf-8")
    )
    foundation_block = manifest["foundation_run_consumed"]
    snapshot_path = context.run_dir / foundation_block["snapshot_path"]
    assert manifest["foundation_load_status"] == "captured"
    assert foundation_block["run_id"] == "foundation-run"
    assert snapshot_path.exists()
    assert foundation_block["manifest_sha256"] == _sha256(snapshot_path)
    assert foundation_block["manifest_sha256"] == _sha256(foundation_manifest_path)


def test_phase2_failure_records_status_not_raise(tmp_path):
    paths = _prepare_paths(tmp_path)
    context = _start_context(paths)
    write_initial_replay_manifest(context)

    update_manifest_with_foundation(
        context.run_dir,
        foundation_run_id="foundation-run",
        foundation_manifest_path=paths.latest_foundation_manifest_path,
    )

    manifest = json.loads(
        (context.run_dir / "replay_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["foundation_run_consumed"] is None
    assert manifest["foundation_load_status"].startswith("error:")


def test_verify_replay_cli_passes_for_pristine_manifest(tmp_path, capsys):
    paths = _prepare_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={"fixture": True},
        config_hash="test-config-hash",
    )

    exit_code = run_verify_replay(paths, run_id_or_path=context.run_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Snapshot integrity:" in output
    assert "Verdict: OK." in output


def test_verify_replay_cli_detects_corrupted_snapshot(tmp_path, capsys):
    paths = _prepare_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={"fixture": True},
        config_hash="test-config-hash",
    )
    manifest = json.loads(
        (context.run_dir / "replay_manifest.json").read_text(encoding="utf-8")
    )
    corrupted_snapshot = context.run_dir / manifest["configs"][0]["snapshot_path"]
    corrupted_snapshot.write_text("corrupted", encoding="utf-8")

    exit_code = run_verify_replay(paths, run_id_or_path=context.run_id)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "[FAIL]" in output
    assert "SNAPSHOT INTEGRITY FAILED" in output


def test_verify_replay_cli_accepts_moved_folder(tmp_path, capsys):
    paths = _prepare_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={"fixture": True},
        config_hash="test-config-hash",
    )
    moved_run_dir = tmp_path / "moved-run"
    shutil.copytree(context.run_dir, moved_run_dir)

    exit_code = run_verify_replay(paths, run_id_or_path=str(moved_run_dir))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"Replay manifest: {moved_run_dir / 'replay_manifest.json'}" in output
    assert "Verdict: OK." in output


def test_verify_replay_cli_reports_predates_for_old_run(tmp_path, capsys):
    paths = _prepare_paths(tmp_path)
    old_run_dir = paths.ensure_run_dir("old-run")

    exit_code = run_verify_replay(paths, run_id_or_path=old_run_dir.name)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "run predates replay manifests" in output
    assert "PREDATES REPLAY MANIFEST" in output


def test_verify_replay_cli_rejects_missing_run_dir(tmp_path, capsys):
    paths = _prepare_paths(tmp_path)

    exit_code = run_verify_replay(paths, run_id_or_path="missing-run")

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Run directory not found:" in output


def test_verify_replay_cli_handles_missing_checkout_context(
    tmp_path,
    capsys,
    monkeypatch,
):
    paths = _prepare_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={"fixture": True},
        config_hash="test-config-hash",
    )

    def unavailable_checkout(cls):
        raise RuntimeError("no checkout")

    monkeypatch.setattr(
        replay_manifest.ProjectPaths,
        "discover",
        classmethod(unavailable_checkout),
    )

    exit_code = run_verify_replay(paths, run_id_or_path=context.run_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "unavailable - no current checkout context" in output


def test_fixture_tool_a_run_with_foundation_replay_manifest_verifies(tmp_path, capsys):
    paths = _prepare_paths(tmp_path)
    context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={"fixture": True},
        config_hash="test-config-hash",
    )
    foundation_manifest_path = _write_foundation_manifest(paths)
    update_manifest_with_foundation(
        context.run_dir,
        foundation_run_id="foundation-run",
        foundation_manifest_path=foundation_manifest_path,
    )

    exit_code = run_verify_replay(paths, run_id_or_path=context.run_id)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "[OK] foundation_manifest.json - sha256 matches recorded" in output
    assert "Verdict: OK." in output


def _prepare_paths(tmp_path: Path, *, manual_db: bool = True):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    if manual_db:
        _create_manual_db(paths.manual_screening_store_path)
    return paths


def _start_context(paths, *, command: str = "tool-a"):
    run_id = f"20260528T000000Z-{command}-fixture"
    run_dir = paths.ensure_run_dir(run_id)
    return RunContext(
        paths=paths,
        command=command,
        parameters={"fixture": True},
        config_hash="test-config-hash",
        run_id=run_id,
        run_dir=run_dir,
        started_at_utc="2026-05-28T00:00:00Z",
        metadata_path=run_dir / "metadata.json",
        log_path=run_dir / "run.log",
    )


def _create_manual_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE manual_inputs (ticker TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO manual_inputs VALUES ('NEM')")
        connection.commit()


def _initialize_git_repo(repo_root: Path) -> None:
    (repo_root / ".gitignore").write_text("data/runs/\n", encoding="utf-8")
    (repo_root / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _run_git(repo_root, "init")
    _run_git(repo_root, "config", "user.email", "tests@example.com")
    _run_git(repo_root, "config", "user.name", "Golden Vector Tests")
    _run_git(repo_root, "add", ".gitignore", "config", "data/manual", "tracked.txt")
    _run_git(repo_root, "commit", "-m", "initial")


def _write_foundation_manifest(paths) -> Path:
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps({"refresh_run_id": "foundation-run"}, sort_keys=True),
        encoding="utf-8",
    )
    return paths.latest_foundation_manifest_path


def _run_git(repo_root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
