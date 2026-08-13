from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

from golden_vector.app.windows_scheduled_refresh import (
    build_windows_scheduled_refresh_tasks,
    install_windows_scheduled_refresh_tasks,
    remove_legacy_windows_refresh_tasks,
)
from golden_vector.cli import build_parser, run_install_scheduled_refresh_tasks
from tests.helpers import build_test_paths


def test_windows_tasks_are_hidden_system_pythonw_tasks_with_expected_triggers(tmp_path):
    repo = (tmp_path / "Golden Vector").resolve()
    repo.mkdir()
    python = (repo / ".venv" / "Scripts" / "python.exe").resolve()
    main_py = (repo / "main.py").resolve()

    tasks = build_windows_scheduled_refresh_tasks(
        python_executable=python,
        main_py=main_py,
        repo_root=repo,
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )

    assert len(tasks) == 3
    first, close, heartbeat = tasks
    for task in tasks:
        root = ElementTree.fromstring(task.xml)
        assert "<UserId>S-1-5-18</UserId>" in task.xml
        assert "<LogonType>ServiceAccount</LogonType>" in task.xml
        assert "<Hidden>true</Hidden>" in task.xml
        assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in task.xml
        assert "<StartWhenAvailable>true</StartWhenAvailable>" in task.xml
        assert "<RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>" in task.xml
        assert str(python.with_name("pythonw.exe")) in task.xml
        assert f"<WorkingDirectory>{repo}</WorkingDirectory>" in task.xml
        assert "scheduled-refresh" in task.xml
        assert "<Interval>PT15M</Interval>" in task.xml
        trigger_nodes = root.find("{*}Triggers")
        assert trigger_nodes is not None
        for trigger_node in trigger_nodes:
            child_names = [child.tag.rpartition("}")[-1] for child in trigger_node]
            if "Repetition" in child_names:
                assert child_names.index("Repetition") < child_names.index("Enabled")
            if "StartBoundary" in child_names:
                assert child_names.index("Repetition") < child_names.index("StartBoundary")
    assert "<BootTrigger" in first.xml
    assert "<LogonTrigger" in first.xml
    assert "Microsoft-Windows-Power-Troubleshooter" in first.xml
    assert '<CalendarTrigger id="DailyFirstOpen">' in first.xml
    assert "<StartBoundary>2026-08-12T00:05:00</StartBoundary>" in first.xml
    assert "<DaysInterval>1</DaysInterval>" in first.xml
    assert first.xml.count("<Delay>PT5M</Delay>") == 3
    assert "--trigger first-open" in first.xml
    assert "<WakeToRun>false</WakeToRun>" in first.xml
    assert "<CalendarTrigger" in close.xml
    assert "<StartBoundary>2026-08-12T21:00:00Z</StartBoundary>" in close.xml
    assert "<Monday />" in close.xml and "<Friday />" in close.xml
    assert "--trigger post-close" in close.xml
    assert "<WakeToRun>true</WakeToRun>" in close.xml
    assert heartbeat.name.endswith(" - Retry Heartbeat")
    assert '<CalendarTrigger id="RetryHeartbeat">' in heartbeat.xml
    assert "<StartBoundary>2026-08-12T00:00:00</StartBoundary>" in heartbeat.xml
    assert "<Duration>PT24H</Duration>" in heartbeat.xml
    assert "<DaysInterval>1</DaysInterval>" in heartbeat.xml
    assert "--trigger retry" in heartbeat.xml
    assert "<WakeToRun>false</WakeToRun>" in heartbeat.xml


def test_windows_installer_uses_xml_files_without_shell_and_cleans_them(tmp_path):
    repo = tmp_path.resolve()
    tasks = build_windows_scheduled_refresh_tasks(
        python_executable=repo / "python.exe",
        main_py=repo / "main.py",
        repo_root=repo,
        now=datetime(2026, 8, 12, tzinfo=UTC),
    )
    calls = []

    def fake_run(command, **kwargs):
        xml_path = Path(command[command.index("/XML") + 1])
        calls.append(
            (list(command), kwargs, xml_path, xml_path.read_bytes())
        )

    install_windows_scheduled_refresh_tasks(tasks, command_runner=fake_run)

    assert len(calls) == 3
    for command, kwargs, xml_path, raw in calls:
        assert command[:2] == ["schtasks", "/Create"]
        assert kwargs == {"check": True}
        # Task Scheduler's /XML parser follows its own export format: UTF-16 LE
        # with BOM, and the declaration must agree with the bytes. A UTF-8 file
        # is rejected with "(1,40) unable to switch the encoding" on real
        # Windows (release gate, 2026-08-13) — this pins declaration and
        # encoding TOGETHER so neither can drift alone.
        assert raw.startswith(b"\xff\xfe"), "staged task XML must be UTF-16 LE with BOM"
        xml = raw.decode("utf-16")
        assert xml.startswith('<?xml version="1.0" encoding="UTF-16"?>')
        assert "<Task" in xml
        assert not xml_path.exists()


def test_daily_boundaries_use_computer_local_day_while_post_close_uses_utc(tmp_path):
    repo = tmp_path.resolve()
    local_time = datetime(
        2026,
        8,
        12,
        23,
        30,
        tzinfo=timezone(-timedelta(hours=7)),
    )

    first, close, heartbeat = build_windows_scheduled_refresh_tasks(
        python_executable=repo / "python.exe",
        main_py=repo / "main.py",
        repo_root=repo,
        now=local_time,
    )

    assert "<StartBoundary>2026-08-12T00:05:00</StartBoundary>" in first.xml
    assert "<StartBoundary>2026-08-12T00:00:00</StartBoundary>" in heartbeat.xml
    assert "<StartBoundary>2026-08-13T21:00:00Z</StartBoundary>" in close.xml


def test_legacy_task_cleanup_is_idempotent_and_exactly_scoped():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))

    remove_legacy_windows_refresh_tasks(command_runner=fake_run)

    assert calls == [
        (
            [
                "schtasks",
                "/Delete",
                "/TN",
                "Golden Vector Market Refresh 1600",
                "/F",
            ],
            {"check": False},
        ),
        (
            [
                "schtasks",
                "/Delete",
                "/TN",
                "Golden Vector Market Refresh 1930",
                "/F",
            ],
            {"check": False},
        ),
    ]


def test_new_scheduler_cli_commands_are_registered_and_install_defaults_to_dry_run(
    tmp_path,
    capsys,
):
    parser = build_parser()
    scheduled = parser.parse_args(["scheduled-refresh", "--trigger", "post-close"])
    install = parser.parse_args(["install-scheduled-refresh-tasks"])
    paths = build_test_paths(tmp_path)

    exit_code = run_install_scheduled_refresh_tasks(
        paths,
        task_name=install.task_name,
        apply=install.apply,
    )

    assert scheduled.trigger == "post-close"
    assert exit_code == 0
    assert "Dry run only" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --apply must never install dead tasks, and never leave a partial set
# ---------------------------------------------------------------------------


class _Completed:
    def __init__(self, returncode: int, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def _fake_venv(tmp_path: Path) -> Path:
    """A pythonw.exe (plus its python.exe sibling) that passes the is_file check."""

    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_text("", encoding="utf-8")
    (scripts / "pythonw.exe").write_text("", encoding="utf-8")
    return scripts / "python.exe"


def test_apply_prints_the_resolved_command_and_dry_run_does_too(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)
    interpreter = _fake_venv(tmp_path)
    monkeypatch.setattr("golden_vector.cli.sys.executable", str(interpreter))

    exit_code = run_install_scheduled_refresh_tasks(
        paths,
        task_name="Golden Vector Data Refresh",
        apply=False,
    )
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Resolved task command:" in out
    assert str(interpreter.with_name("pythonw.exe")) in out
    assert str((paths.repo_root / "main.py").resolve()) in out
    assert str(paths.repo_root.resolve()) in out


def test_apply_refuses_before_touching_schtasks_when_the_interpreter_cannot_import(
    tmp_path, monkeypatch, capsys
):
    """An elevated shell resolves sys.executable to the SYSTEM python.

    Installing then leaves three tasks that can never import the project and
    fail invisibly every day, so the import probe must run BEFORE any schtasks
    call and name the interpreter to use instead.
    """

    paths = build_test_paths(tmp_path)
    interpreter = _fake_venv(tmp_path)
    monkeypatch.setattr("golden_vector.cli.sys.executable", str(interpreter))
    schtasks_calls: list[list[str]] = []
    probes: list[dict] = []

    def fake_probe(command, **kwargs):
        probes.append({"command": list(command), "kwargs": kwargs})
        return _Completed(1, stderr="ModuleNotFoundError: No module named 'golden_vector'")

    exit_code = run_install_scheduled_refresh_tasks(
        paths,
        task_name="Golden Vector Data Refresh",
        apply=True,
        _command_runner=lambda command, **kwargs: schtasks_calls.append(list(command)),
        _probe_runner=fake_probe,
    )
    out = capsys.readouterr().out

    assert exit_code == 1
    assert schtasks_calls == []
    # Probed through python.exe, not pythonw.exe (which swallows the output).
    assert probes[0]["command"] == [
        str(interpreter),
        "-c",
        "import golden_vector",
    ]
    assert probes[0]["kwargs"]["cwd"] == str(paths.repo_root.resolve())
    assert "cannot import the Golden Vector project" in out
    assert "ModuleNotFoundError" in out
    assert str(paths.repo_root.resolve() / "venv" / "Scripts" / "python.exe") in out


def test_apply_installs_then_removes_legacy_tasks_when_the_probe_passes(
    tmp_path, monkeypatch, capsys
):
    paths = build_test_paths(tmp_path)
    interpreter = _fake_venv(tmp_path)
    monkeypatch.setattr("golden_vector.cli.sys.executable", str(interpreter))
    calls: list[list[str]] = []

    exit_code = run_install_scheduled_refresh_tasks(
        paths,
        task_name="Golden Vector Data Refresh",
        apply=True,
        _command_runner=lambda command, **kwargs: calls.append(list(command)),
        _probe_runner=lambda command, **kwargs: _Completed(0),
    )

    assert exit_code == 0
    assert [call[1] for call in calls] == ["/Create", "/Create", "/Create", "/Delete", "/Delete"]
    assert "installed" in capsys.readouterr().out


def test_a_failed_create_rolls_back_and_leaves_the_legacy_tasks_alone(
    tmp_path, monkeypatch, capsys
):
    """Non-elevated apply used to delete the legacy tasks then half-install.

    The machine must be left exactly as it was found: legacy tasks untouched,
    the already-created task deleted again, a nonzero exit and an elevation hint.
    """

    paths = build_test_paths(tmp_path)
    interpreter = _fake_venv(tmp_path)
    monkeypatch.setattr("golden_vector.cli.sys.executable", str(interpreter))
    calls: list[list[str]] = []

    def failing_runner(command, **kwargs):
        calls.append(list(command))
        creates = [call for call in calls if call[1] == "/Create"]
        if command[1] == "/Create" and len(creates) == 2:
            raise subprocess.CalledProcessError(1, command, stderr="Access is denied.")

    exit_code = run_install_scheduled_refresh_tasks(
        paths,
        task_name="Golden Vector Data Refresh",
        apply=True,
        _command_runner=failing_runner,
        _probe_runner=lambda command, **kwargs: _Completed(0),
    )
    out = capsys.readouterr().out

    assert exit_code == 1
    assert [call[1] for call in calls] == ["/Create", "/Create", "/Delete"]
    # The rollback removed the ONE task this run had created...
    assert calls[2][3] == "Golden Vector Data Refresh - First Open"
    # ...and no legacy task was deleted.
    assert not any("Market Refresh" in call[3] for call in calls)
    assert "US Post Close" in out  # names the task that failed
    assert "elevated terminal" in out
    assert "left in place" in out
