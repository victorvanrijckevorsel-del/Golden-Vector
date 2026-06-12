"""Local refresh job state for the Option Trading workspace UI."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from golden_vector.common.files import atomic_write_text as _atomic_write_text
from golden_vector.common.files import repo_relative as _repo_relative
from golden_vector.app.paths import ProjectPaths

REFRESH_STATUS_IDLE = "idle"
REFRESH_STATUS_RUNNING = "running"
REFRESH_STATUS_SUCCEEDED = "succeeded"
REFRESH_STATUS_FAILED = "failed"
REFRESH_STATUS_UNKNOWN = "unknown"
REFRESH_JOB_ID_ENV = "GOLDEN_VECTOR_REFRESH_JOB_ID"

_STILL_ACTIVE = 259
_DETACHED_PROCESS = 0x00000008


@dataclass(frozen=True)
class OptionRefreshStatus:
    status: str = REFRESH_STATUS_IDLE
    job_id: str | None = None
    process_id: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    command: tuple[str, ...] = ()
    latest_run_id: str | None = None
    log_path: str | None = None
    stage_detail: str | None = None
    error_summary: str | None = None

    @property
    def is_running(self) -> bool:
        return self.status == REFRESH_STATUS_RUNNING

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "job_id": self.job_id,
            "process_id": self.process_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "command": list(self.command),
            "latest_run_id": self.latest_run_id,
            "log_path": self.log_path,
            "stage_detail": self.stage_detail,
            "error_summary": self.error_summary,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "OptionRefreshStatus":
        command = payload.get("command") or []
        if not isinstance(command, list):
            command = []
        return cls(
            status=str(payload.get("status") or REFRESH_STATUS_UNKNOWN),
            job_id=_optional_text(payload.get("job_id")),
            process_id=_optional_int(payload.get("process_id")),
            started_at=_optional_text(payload.get("started_at")),
            finished_at=_optional_text(payload.get("finished_at")),
            command=tuple(str(part) for part in command),
            latest_run_id=_optional_text(payload.get("latest_run_id")),
            log_path=_optional_text(payload.get("log_path")),
            stage_detail=_optional_text(payload.get("stage_detail")),
            error_summary=_optional_text(payload.get("error_summary")),
        )


@dataclass(frozen=True)
class OptionRefreshStartResult:
    status: OptionRefreshStatus
    started: bool
    already_running: bool = False
    adopted: bool = False


ProcessExists = Callable[[int], bool]
PopenFactory = Callable[..., Any]


def option_refresh_status_path(paths: ProjectPaths) -> Path:
    return paths.runs_dir / "ui_refresh_status.json"


def option_refresh_logs_dir(paths: ProjectPaths) -> Path:
    return paths.runs_dir / "ui_refresh_logs"


def read_option_refresh_status(
    paths: ProjectPaths,
    *,
    process_exists: ProcessExists | None = None,
) -> OptionRefreshStatus:
    status_path = option_refresh_status_path(paths)
    if not status_path.exists():
        return OptionRefreshStatus()
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("refresh status JSON root must be an object")
        status = OptionRefreshStatus.from_payload(payload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return OptionRefreshStatus(
            status=REFRESH_STATUS_UNKNOWN,
            finished_at=_utc_now(),
            error_summary=f"Could not read refresh status: {exc}",
        )
    if status.status == REFRESH_STATUS_RUNNING and status.process_id is not None:
        exists = process_exists or is_process_running
        # Staleness ceiling: Windows recycles PIDs aggressively, so a dead
        # runner whose PID was reused by an unrelated process would keep the
        # lock RUNNING forever (refresh button disabled until a hand-delete).
        # A real refresh takes minutes; anything past the ceiling is stale.
        if not exists(status.process_id) or _running_past_ceiling(status):
            recovered = OptionRefreshStatus(
                status=REFRESH_STATUS_FAILED,
                job_id=status.job_id,
                process_id=status.process_id,
                started_at=status.started_at,
                finished_at=_utc_now(),
                command=status.command,
                latest_run_id=status.latest_run_id,
                log_path=status.log_path,
                stage_detail=status.stage_detail,
                error_summary=(
                    "Refresh process is no longer running."
                    if not exists(status.process_id)
                    else "Refresh marked stale after exceeding the runtime ceiling."
                ),
            )
            try:
                write_option_refresh_status(paths, recovered)
            except OSError:
                # Persisting the recovery is an optimization; a transient
                # write collision must not fail the page render.
                pass
            return recovered
        return _with_log_stage(paths, status)
    return status


REFRESH_RUNTIME_CEILING_SECONDS = 2 * 60 * 60  # a real refresh takes ~3 min


def _running_past_ceiling(status: OptionRefreshStatus) -> bool:
    if not status.started_at:
        return False
    try:
        started = datetime.fromisoformat(str(status.started_at))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    return elapsed > REFRESH_RUNTIME_CEILING_SECONDS


def write_option_refresh_status(
    paths: ProjectPaths,
    status: OptionRefreshStatus,
) -> Path:
    status_path = option_refresh_status_path(paths)
    _atomic_write_text(
        status_path,
        json.dumps(status.to_payload(), indent=2, sort_keys=True),
    )
    return status_path


def _acquire_exclusive_sidecar(paths: ProjectPaths) -> int | None:
    """OS-level mutual exclusion around lock acquisition.

    read-check-write on the status JSON has a race window (two acquirers can
    both read 'not running' before either writes RUNNING - proven realistic
    with a scheduled refresh plus the UI button, or two workspace servers).
    O_CREAT|O_EXCL on a sidecar serializes the acquisition itself. The
    sidecar is held only for the milliseconds of acquisition; one older
    than a minute is a crash leftover and is broken.
    """

    sidecar = option_refresh_status_path(paths).with_suffix(".acquire.lock")
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            return os.open(str(sidecar), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - sidecar.stat().st_mtime
            except OSError:
                continue  # vanished between open and stat; retry
            if age > 60:
                try:
                    sidecar.unlink()
                except OSError:
                    return None
                continue
            return None
    return None


def _release_exclusive_sidecar(paths: ProjectPaths, handle: int) -> None:
    sidecar = option_refresh_status_path(paths).with_suffix(".acquire.lock")
    try:
        os.close(handle)
    finally:
        try:
            sidecar.unlink()
        except OSError:
            pass


def acquire_refresh_lock(
    paths: ProjectPaths,
    *,
    command: Sequence[str],
    adopted_job_id: str | None = None,
    process_id: int | None = None,
    process_exists: ProcessExists | None = None,
) -> OptionRefreshStartResult:
    current = read_option_refresh_status(paths, process_exists=process_exists)
    if (
        adopted_job_id
        and current.status == REFRESH_STATUS_RUNNING
        and current.job_id == adopted_job_id
    ):
        return OptionRefreshStartResult(status=current, started=True, adopted=True)
    if current.status == REFRESH_STATUS_RUNNING:
        return OptionRefreshStartResult(
            status=current,
            started=False,
            already_running=True,
        )

    sidecar_handle = _acquire_exclusive_sidecar(paths)
    if sidecar_handle is None:
        # Another process is acquiring right now; treat as already running.
        return OptionRefreshStartResult(
            status=current,
            started=False,
            already_running=True,
        )
    try:
        # Re-check under the sidecar: the first read may predate a
        # concurrent acquirer's RUNNING write.
        current = read_option_refresh_status(paths, process_exists=process_exists)
        if current.status == REFRESH_STATUS_RUNNING:
            return OptionRefreshStartResult(
                status=current,
                started=False,
                already_running=True,
            )
        status = OptionRefreshStatus(
            status=REFRESH_STATUS_RUNNING,
            job_id=_new_job_id(),
            process_id=process_id if process_id is not None else os.getpid(),
            started_at=_utc_now(),
            command=tuple(command),
        )
        write_option_refresh_status(paths, status)
        return OptionRefreshStartResult(status=status, started=True)
    finally:
        _release_exclusive_sidecar(paths, sidecar_handle)


def start_options_refresh(
    paths: ProjectPaths,
    *,
    process_exists: ProcessExists | None = None,
    popen_factory: PopenFactory | None = None,
) -> OptionRefreshStartResult:
    current = read_option_refresh_status(paths, process_exists=process_exists)
    if current.status == REFRESH_STATUS_RUNNING:
        return OptionRefreshStartResult(
            status=current,
            started=False,
            already_running=True,
        )

    sidecar_handle = _acquire_exclusive_sidecar(paths)
    if sidecar_handle is None:
        return OptionRefreshStartResult(
            status=current,
            started=False,
            already_running=True,
        )
    try:
        current = read_option_refresh_status(paths, process_exists=process_exists)
        if current.status == REFRESH_STATUS_RUNNING:
            return OptionRefreshStartResult(
                status=current,
                started=False,
                already_running=True,
            )
        return _start_options_refresh_locked(
            paths,
            popen_factory=popen_factory,
        )
    finally:
        _release_exclusive_sidecar(paths, sidecar_handle)


def _start_options_refresh_locked(
    paths: ProjectPaths,
    *,
    popen_factory: PopenFactory | None = None,
) -> OptionRefreshStartResult:
    job_id = _new_job_id()
    log_path = option_refresh_logs_dir(paths) / f"{job_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = _options_refresh_command(paths)
    runner_command = [
        sys.executable,
        "-m",
        "golden_vector.serve.option_refresh",
        "--run",
        "--job-id",
        job_id,
        "--log-path",
        str(log_path),
    ]
    try:
        process = _spawn_runner(
            runner_command,
            paths=paths,
            popen_factory=popen_factory,
        )
    except OSError as exc:
        failed = OptionRefreshStatus(
            status=REFRESH_STATUS_FAILED,
            job_id=job_id,
            started_at=_utc_now(),
            finished_at=_utc_now(),
            command=tuple(command),
            log_path=_repo_relative_or_absolute(paths, log_path),
            error_summary=f"Could not start refresh process: {exc}",
        )
        write_option_refresh_status(paths, failed)
        return OptionRefreshStartResult(status=failed, started=False)

    status = OptionRefreshStatus(
        status=REFRESH_STATUS_RUNNING,
        job_id=job_id,
        process_id=_optional_int(getattr(process, "pid", None)),
        started_at=_utc_now(),
        command=tuple(command),
        log_path=_repo_relative_or_absolute(paths, log_path),
    )
    write_option_refresh_status(paths, status)
    return OptionRefreshStartResult(status=status, started=True)


def complete_options_refresh(
    paths: ProjectPaths,
    *,
    job_id: str,
    return_code: int,
    error_summary: str | None = None,
) -> OptionRefreshStatus:
    current = read_option_refresh_status(paths, process_exists=lambda _pid: True)
    if current.job_id is not None and current.job_id != job_id:
        return current
    latest_run_id = _latest_model_refresh_id(paths)
    status = OptionRefreshStatus(
        status=REFRESH_STATUS_SUCCEEDED
        if return_code == 0
        else REFRESH_STATUS_FAILED,
        job_id=job_id,
        process_id=current.process_id,
        started_at=current.started_at,
        finished_at=_utc_now(),
        command=current.command or tuple(_options_refresh_command(paths)),
        latest_run_id=latest_run_id,
        log_path=current.log_path,
        stage_detail=_latest_logged_stage(_status_log_path(paths, current)),
        error_summary=error_summary if return_code != 0 else None,
    )
    write_option_refresh_status(paths, status)
    return status


def is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        return _is_windows_process_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def run_refresh_child(*, job_id: str, log_path: Path) -> int:
    paths = ProjectPaths.discover()
    _wait_for_parent_status(paths, job_id=job_id)
    command = _options_refresh_command(paths)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{_utc_now()}] Starting full model refresh: {' '.join(command)}\n")
        log_file.flush()
        run_kwargs: dict[str, Any] = {
            "cwd": paths.repo_root,
            "env": {**os.environ, REFRESH_JOB_ID_ENV: job_id},
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "text": True,
            "check": False,
        }
        if os.name == "nt":
            # Run the refresh worker windowless. Without this Windows opens a
            # visible black console window over the workspace for the duration
            # of the refresh — alarming and easy to mistake for a crash. The
            # refresh already logs to the job file, so no console is needed.
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run(command, **run_kwargs)
        log_file.write(
            f"[{_utc_now()}] Full model refresh finished with exit code {completed.returncode}.\n"
        )
    complete_options_refresh(
        paths,
        job_id=job_id,
        return_code=completed.returncode,
        error_summary=_tail_log(log_path) if completed.returncode != 0 else None,
    )
    return completed.returncode


def render_option_refresh_control(
    status: OptionRefreshStatus,
    *,
    return_to: str,
    action: str = "/refresh",
) -> str:
    disabled = " disabled" if status.status == REFRESH_STATUS_RUNNING else ""
    status_text = _refresh_status_text(status)
    return (
        "<section class=\"option-refresh-control\">"
        f"<form method=\"post\" action=\"{_html_attr(action)}\" class=\"inline-form\">"
        f"<input type=\"hidden\" name=\"return_to\" value=\"{_html_attr(return_to)}\">"
        f"<button type=\"submit\"{disabled}>Refresh all model data</button>"
        "</form>"
        f"<p class=\"hint\">{_html_text(status_text)}</p>"
        "</section>"
    )


def _spawn_runner(
    command: Sequence[str],
    *,
    paths: ProjectPaths,
    popen_factory: PopenFactory | None,
) -> Any:
    kwargs: dict[str, Any] = {
        "cwd": paths.repo_root,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | _DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    factory = popen_factory or subprocess.Popen
    return factory(list(command), **kwargs)


def _options_refresh_command(paths: ProjectPaths) -> list[str]:
    return [sys.executable, str(paths.repo_root / "main.py"), "refresh"]


def _latest_model_refresh_id(paths: ProjectPaths) -> str | None:
    try:
        payload = json.loads(paths.latest_model_state_manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    run_id = payload.get("parent_refresh_id")
    return str(run_id) if run_id else None


def _tail_log(path: Path, *, line_count: int = 8) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    tail = [line.strip() for line in lines[-line_count:] if line.strip()]
    return "\n".join(tail) if tail else None


def _with_log_stage(paths: ProjectPaths, status: OptionRefreshStatus) -> OptionRefreshStatus:
    stage = _latest_logged_stage(_status_log_path(paths, status))
    if stage == status.stage_detail:
        return status
    return replace(status, stage_detail=stage)


def _status_log_path(paths: ProjectPaths, status: OptionRefreshStatus) -> Path | None:
    if not status.log_path:
        return None
    path = Path(status.log_path)
    return path if path.is_absolute() else paths.repo_root / path


def _latest_logged_stage(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("== Step ") and stripped.endswith("=="):
            return stripped.strip("= ").strip()
    return None


def _wait_for_parent_status(
    paths: ProjectPaths,
    *,
    job_id: str,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = read_option_refresh_status(paths, process_exists=lambda _pid: True)
        if status.job_id == job_id:
            return
        time.sleep(0.05)


def _is_windows_process_running(pid: int) -> bool:
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        return bool(ok) and exit_code.value == _STILL_ACTIVE
    except Exception:  # noqa: BLE001 - fallback to conservative POSIX-style probe.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return True
        return True


def _refresh_status_text(status: OptionRefreshStatus) -> str:
    if status.status == REFRESH_STATUS_RUNNING:
        started = f" since {status.started_at}" if status.started_at else ""
        stage = f" Current logged stage: {status.stage_detail}." if status.stage_detail else ""
        return f"Full model refresh running{started}.{stage}"
    if status.status == REFRESH_STATUS_SUCCEEDED:
        finished = f" at {status.finished_at}" if status.finished_at else ""
        run = f" Latest model refresh: {status.latest_run_id}." if status.latest_run_id else ""
        return f"Full model refresh succeeded{finished}.{run}"
    if status.status == REFRESH_STATUS_FAILED:
        detail = f" {status.error_summary}" if status.error_summary else ""
        stage = f" Last logged stage: {status.stage_detail}." if status.stage_detail else ""
        return f"Full model refresh failed.{stage}{detail}"
    if status.status == REFRESH_STATUS_UNKNOWN:
        detail = f" {status.error_summary}" if status.error_summary else ""
        return f"Full model refresh status unknown.{detail}"
    return "Full model refresh idle."


def _repo_relative_or_absolute(paths: ProjectPaths, path: Path) -> str:
    return _repo_relative(paths, path)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_job_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"


def _html_text(value: str) -> str:
    from html import escape

    return escape(value)


def _html_attr(value: str) -> str:
    from html import escape

    return escape(value, quote=True)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--log-path", required=True)
    args = parser.parse_args(argv)
    if not args.run:
        parser.error("--run is required")
    return run_refresh_child(job_id=args.job_id, log_path=Path(args.log_path))


if __name__ == "__main__":
    raise SystemExit(_main())
