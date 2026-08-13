"""Windows Task Scheduler adapter for the portable refresh coordinator."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, time
from html import escape
from pathlib import Path
from typing import Callable, Sequence

from golden_vector.app.scheduled_refresh import (
    TRIGGER_FIRST_OPEN,
    TRIGGER_POST_CLOSE,
    TRIGGER_RETRY,
)

DEFAULT_TASK_NAME = "Golden Vector Data Refresh"
LEGACY_DEFAULT_TASK_NAMES = (
    "Golden Vector Market Refresh 1600",
    "Golden Vector Market Refresh 1930",
)
FIRST_OPEN_DELAY = "PT5M"
RETRY_POLL_INTERVAL = "PT15M"
FIRST_OPEN_RETRY_WINDOW = "PT8H"
POST_CLOSE_RETRY_WINDOW = "PT8H"
RETRY_HEARTBEAT_WINDOW = "PT24H"
POST_CLOSE_EARLIEST_UTC = time(21, 0)
DAILY_FIRST_OPEN_LOCAL_TIME = time(0, 5)
DAILY_HEARTBEAT_LOCAL_TIME = time(0, 0)


@dataclass(frozen=True)
class WindowsScheduledTask:
    name: str
    xml: str
    trigger_summary: str
    wake_to_run: bool


CommandRunner = Callable[..., object]


class WindowsScheduledTaskInstallError(RuntimeError):
    """A ``schtasks`` registration failed; the partial set was rolled back."""

    def __init__(self, task_name: str, *, cause: BaseException) -> None:
        super().__init__(
            f"could not register the scheduled task {task_name!r} ({cause}). "
            "Any tasks created by this run were removed again. Registering "
            "SYSTEM tasks requires an elevated terminal - re-run the install "
            "from an Administrator prompt."
        )
        self.task_name = task_name


def build_windows_scheduled_refresh_tasks(
    *,
    python_executable: str | Path,
    main_py: Path,
    repo_root: Path,
    task_name: str = DEFAULT_TASK_NAME,
    now: datetime | None = None,
) -> tuple[WindowsScheduledTask, ...]:
    """Build hidden SYSTEM task definitions without installing them.

    Three tasks keep trigger intent explicit while the coordinator remains the
    single source of truth. The post-close task begins at 21:00 UTC and polls
    through the US daylight-saving offset window; only the coordinator's 17:00
    ET trading-calendar guard can start the refresh. An independent all-day
    heartbeat keeps a failed long-running job's 15/30/60-minute retries
    callable after either originating trigger's bounded polling window ends.
    """

    pythonw = pythonw_path(python_executable)
    main_path = main_py.resolve()
    working_directory = repo_root.resolve()
    for label, path in (
        ("pythonw executable", pythonw),
        ("main.py", main_path),
        ("working directory", working_directory),
    ):
        if not path.is_absolute():
            raise ValueError(f"Windows scheduled task {label} must be absolute: {path}")

    instant = now or datetime.now().astimezone()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    post_close_boundary = (
        datetime.combine(
            instant.astimezone(UTC).date(),
            POST_CLOSE_EARLIEST_UTC,
            tzinfo=UTC,
        )
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    daily_first_open_boundary = datetime.combine(
        instant.date(),
        DAILY_FIRST_OPEN_LOCAL_TIME,
    ).isoformat(timespec="seconds")
    daily_heartbeat_boundary = datetime.combine(
        instant.date(),
        DAILY_HEARTBEAT_LOCAL_TIME,
    ).isoformat(timespec="seconds")

    first_name = f"{task_name} - First Open"
    close_name = f"{task_name} - US Post Close"
    heartbeat_name = f"{task_name} - Retry Heartbeat"
    return (
        WindowsScheduledTask(
            name=first_name,
            xml=_task_xml(
                description=(
                    "Starts Golden Vector's once-daily refresh five minutes after "
                    "startup, logon, or resume, and at 00:05 each local day, then "
                    "polls for bounded retries."
                ),
                triggers=_first_open_triggers_xml(daily_first_open_boundary),
                pythonw=pythonw,
                main_py=main_path,
                repo_root=working_directory,
                trigger=TRIGGER_FIRST_OPEN,
                wake_to_run=False,
            ),
            trigger_summary=(
                "startup, logon, resume, and daily local 00:05; 5-minute event delay; "
                "15-minute retry polling"
            ),
            wake_to_run=False,
        ),
        WindowsScheduledTask(
            name=close_name,
            xml=_task_xml(
                description=(
                    "Wakes on weekday US post-close windows; Golden Vector's trading "
                    "calendar and 17:00 ET guard decide whether data is actually due."
                ),
                triggers=_post_close_trigger_xml(post_close_boundary),
                pythonw=pythonw,
                main_py=main_path,
                repo_root=working_directory,
                trigger=TRIGGER_POST_CLOSE,
                wake_to_run=True,
            ),
            trigger_summary=(
                "weekdays from 21:00 UTC through the ET DST window; wakes computer; "
                "15-minute retry polling"
            ),
            wake_to_run=True,
        ),
        WindowsScheduledTask(
            name=heartbeat_name,
            xml=_task_xml(
                description=(
                    "Checks all day for a scheduled refresh retry that has become "
                    "due, independently of the trigger that started the refresh."
                ),
                triggers=_retry_heartbeat_trigger_xml(daily_heartbeat_boundary),
                pythonw=pythonw,
                main_py=main_path,
                repo_root=working_directory,
                trigger=TRIGGER_RETRY,
                wake_to_run=False,
            ),
            trigger_summary=(
                "every 15 minutes from the daily local boundary; does not wake the computer"
            ),
            wake_to_run=False,
        ),
    )


def install_windows_scheduled_refresh_tasks(
    tasks: Sequence[WindowsScheduledTask],
    *,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Install pre-built task XML through ``schtasks``, all-or-nothing.

    Each temporary XML file is closed before ``schtasks`` reads it, which is
    required on Windows. Registration runs without a shell and therefore does
    not interpolate paths or arguments.

    A non-elevated (or otherwise failing) run used to leave a partial set
    installed. If any registration fails, the ones this call already created
    are deleted again so the machine is left exactly as it was found, and
    ``WindowsScheduledTaskInstallError`` carries the actionable message.
    """

    created: list[str] = []
    for task in tasks:
        temp_path: Path | None = None
        try:
            # Both the staging write and the registration are covered: either
            # one failing halfway through would otherwise strand a partial set.
            try:
                # Task Scheduler's /XML parser follows its own exports: UTF-16
                # LE with BOM. A utf-8 file whose declaration says UTF-8 is
                # rejected with "(1,40) unable to switch the encoding" on real
                # Windows (release gate, 2026-08-13), so declaration and bytes
                # are pinned to UTF-16 together — see the paired regression.
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".xml",
                    encoding="utf-16",
                    newline="\n",
                    delete=False,
                ) as handle:
                    handle.write(task.xml)
                    temp_path = Path(handle.name)
                command_runner(
                    [
                        "schtasks",
                        "/Create",
                        "/TN",
                        task.name,
                        "/XML",
                        str(temp_path),
                        "/F",
                    ],
                    check=True,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                _rollback_created_tasks(created, command_runner=command_runner)
                raise WindowsScheduledTaskInstallError(task.name, cause=exc) from exc
            created.append(task.name)
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def _rollback_created_tasks(
    task_names: Sequence[str],
    *,
    command_runner: CommandRunner,
) -> None:
    """Best-effort removal of the subset this run created (never raises)."""

    for task_name in reversed(list(task_names)):
        try:
            command_runner(
                ["schtasks", "/Delete", "/TN", task_name, "/F"],
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            continue


def remove_legacy_windows_refresh_tasks(
    *,
    task_names: Sequence[str] = LEGACY_DEFAULT_TASK_NAMES,
    command_runner: CommandRunner = subprocess.run,
) -> None:
    """Remove superseded visible-console tasks when they are present.

    The former installer used these two fixed names and launched ``python.exe``
    directly. Keeping them would retain unwanted terminals and duplicate
    refresh checks. A missing task is the normal idempotent case, so deletion
    deliberately uses ``check=False``.
    """

    for task_name in task_names:
        command_runner(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            check=False,
        )


def pythonw_path(python_executable: str | Path) -> Path:
    """The console-free interpreter the tasks will actually run.

    Public because the CLI must print (and verify) exactly the interpreter the
    task XML embeds -- resolving it a second time in the CLI is how the two
    quietly disagreed.
    """

    resolved = Path(python_executable).resolve()
    if resolved.name.lower() == "pythonw.exe":
        return resolved
    return resolved.with_name("pythonw.exe")


def _first_open_triggers_xml(daily_local_boundary: str) -> str:
    repetition = _repetition_xml(FIRST_OPEN_RETRY_WINDOW)
    subscription = escape(
        "<QueryList><Query Id='0' Path='System'><Select Path='System'>"
        "*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] "
        "and EventID=1]]</Select></Query></QueryList>"
    )
    return f"""
    <BootTrigger id="Startup">
      {repetition}
      <Enabled>true</Enabled>
      <Delay>{FIRST_OPEN_DELAY}</Delay>
    </BootTrigger>
    <LogonTrigger id="Logon">
      {repetition}
      <Enabled>true</Enabled>
      <Delay>{FIRST_OPEN_DELAY}</Delay>
    </LogonTrigger>
    <EventTrigger id="Resume">
      {repetition}
      <Enabled>true</Enabled>
      <Subscription>{subscription}</Subscription>
      <Delay>{FIRST_OPEN_DELAY}</Delay>
    </EventTrigger>
    <CalendarTrigger id="DailyFirstOpen">
      {repetition}
      <StartBoundary>{escape(daily_local_boundary)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>"""


def _post_close_trigger_xml(start_boundary: str) -> str:
    repetition = _repetition_xml(POST_CLOSE_RETRY_WINDOW)
    return f"""
    <CalendarTrigger id="USPostCloseWindow">
      {repetition}
      <StartBoundary>{escape(start_boundary)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <WeeksInterval>1</WeeksInterval>
        <DaysOfWeek>
          <Monday />
          <Tuesday />
          <Wednesday />
          <Thursday />
          <Friday />
        </DaysOfWeek>
      </ScheduleByWeek>
    </CalendarTrigger>"""


def _retry_heartbeat_trigger_xml(start_boundary: str) -> str:
    repetition = _repetition_xml(RETRY_HEARTBEAT_WINDOW)
    return f"""
    <CalendarTrigger id="RetryHeartbeat">
      {repetition}
      <StartBoundary>{escape(start_boundary)}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>"""


def _repetition_xml(duration: str) -> str:
    return f"""<Repetition>
        <Interval>{RETRY_POLL_INTERVAL}</Interval>
        <Duration>{duration}</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>"""


def _task_xml(
    *,
    description: str,
    triggers: str,
    pythonw: Path,
    main_py: Path,
    repo_root: Path,
    trigger: str,
    wake_to_run: bool,
) -> str:
    arguments = subprocess.list2cmdline([str(main_py), "scheduled-refresh", "--trigger", trigger])
    wake = "true" if wake_to_run else "false"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>Golden Vector</Author>
    <Description>{escape(description)}</Description>
  </RegistrationInfo>
  <Triggers>{triggers}
  </Triggers>
  <Principals>
    <Principal id="System">
      <UserId>S-1-5-18</UserId>
      <LogonType>ServiceAccount</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>{wake}</WakeToRun>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="System">
    <Exec>
      <Command>{escape(str(pythonw))}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(repo_root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
