from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from golden_vector.app.scheduled_refresh import (
    ACTION_RETRY_EXHAUSTED,
    ScheduledRefreshStateError,
    coordinate_scheduled_refresh,
    read_scheduled_refresh_state,
    scheduled_refresh_state_path,
)
from golden_vector.app.latest_successful_refresh import SuccessfulModelRefresh
from golden_vector.serve.option_refresh import (
    OptionRefreshStartResult,
    OptionRefreshStatus,
)
from tests.helpers import build_test_paths


def _running_result(job_id: str) -> OptionRefreshStartResult:
    return OptionRefreshStartResult(
        status=OptionRefreshStatus(
            status="running",
            job_id=job_id,
            process_id=123,
            started_at="2026-08-12T07:05:00Z",
        ),
        started=True,
    )


def test_first_open_starts_once_then_manifest_satisfies_slot(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    now = datetime(2026, 8, 12, 8, 5, tzinfo=UTC)
    starts: list[str] = []
    statuses = [OptionRefreshStatus(), OptionRefreshStatus(status="succeeded", job_id="job-1")]
    latest = iter(
        (
            None,
            SuccessfulModelRefresh(
                generated_at=now + timedelta(minutes=5),
                generated_at_utc="2026-08-12T08:10:00Z",
                parent_refresh_id="refresh-1",
                source_path=paths.latest_model_state_manifest_path,
            ),
        )
    )

    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.read_option_refresh_status",
        lambda _paths: statuses.pop(0),
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.start_options_refresh",
        lambda _paths: starts.append("job-1") or _running_result("job-1"),
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.load_latest_successful_model_refresh",
        lambda _paths: next(latest),
    )

    first = coordinate_scheduled_refresh(paths, trigger="first-open", now=now)
    second = coordinate_scheduled_refresh(
        paths,
        trigger="first-open",
        now=now + timedelta(minutes=10),
    )

    assert first.action == "started"
    assert second.action == "skipped"
    assert starts == ["job-1"]
    assert "first-open:2026-08-12" in second.state.completed_slots


def test_post_close_only_exists_after_5pm_et_on_trading_day(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    starts: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.read_option_refresh_status",
        lambda _paths: OptionRefreshStatus(),
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.load_latest_successful_model_refresh",
        lambda _paths: None,
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.start_options_refresh",
        lambda _paths: starts.append(("started",)) or _running_result("job-1"),
    )

    before_close = coordinate_scheduled_refresh(
        paths,
        trigger="post-close",
        now=datetime(2026, 8, 12, 20, 59, tzinfo=UTC),  # 16:59 ET
    )
    assert before_close.action == "skipped"
    assert not before_close.state.active_slots

    # A fresh state at 17:00 ET captures both still-due slots with one full refresh.
    scheduled_refresh_state_path(paths).unlink()
    after_close = coordinate_scheduled_refresh(
        paths,
        trigger="post-close",
        now=datetime(2026, 8, 12, 21, 0, tzinfo=UTC),
    )
    assert after_close.state.active_slots == (
        "first-open:2026-08-12",
        "post-close:2026-08-12",
    )

    scheduled_refresh_state_path(paths).unlink()
    holiday = coordinate_scheduled_refresh(
        paths,
        trigger="post-close",
        now=datetime(2026, 7, 4, 22, 0, tzinfo=UTC),
    )
    assert holiday.action == "skipped"
    assert not holiday.state.active_slots


def test_failed_attempts_follow_15_30_60_then_exhaust(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    now = datetime(2026, 8, 12, 7, 5, tzinfo=UTC)
    current = OptionRefreshStatus()
    jobs = iter(("job-1", "job-2", "job-3", "job-4"))

    def start(_paths):
        nonlocal current
        job = next(jobs)
        current = OptionRefreshStatus(
            status="running",
            job_id=job,
            process_id=123,
            started_at=now.isoformat(),
        )
        return OptionRefreshStartResult(status=current, started=True)

    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.read_option_refresh_status",
        lambda _paths: current,
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.start_options_refresh",
        start,
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.load_latest_successful_model_refresh",
        lambda _paths: None,
    )

    first = coordinate_scheduled_refresh(paths, trigger="first-open", now=now)
    assert first.action == "started"

    expected_delays = (15, 30, 60)
    for attempt, delay in enumerate(expected_delays, start=1):
        failed_at = now + timedelta(minutes=sum(expected_delays[: attempt - 1]))
        current = OptionRefreshStatus(
            status="failed",
            job_id=f"job-{attempt}",
            finished_at=failed_at.isoformat(),
            error_summary="network unavailable",
        )
        waiting = coordinate_scheduled_refresh(paths, trigger="retry", now=failed_at)
        assert waiting.action == "waiting"
        retry = coordinate_scheduled_refresh(
            paths,
            trigger="retry",
            now=failed_at + timedelta(minutes=delay),
        )
        assert retry.action == "started"
        assert retry.state.attempt_number == attempt + 1

    final_failed_at = now + timedelta(hours=2)
    current = OptionRefreshStatus(
        status="failed",
        job_id="job-4",
        finished_at=final_failed_at.isoformat(),
        error_summary="still unavailable",
    )
    exhausted = coordinate_scheduled_refresh(
        paths,
        trigger="retry",
        now=final_failed_at,
    )
    assert exhausted.action == ACTION_RETRY_EXHAUSTED
    assert not exhausted.state.active_slots
    assert exhausted.state.exhausted_slots == ("first-open:2026-08-12",)


def test_corrupt_durable_state_fails_loud(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    scheduled_refresh_state_path(paths).write_text("{bad", encoding="utf-8")

    with pytest.raises(ScheduledRefreshStateError, match="Could not read"):
        read_scheduled_refresh_state(paths)


def test_inconsistent_active_state_fails_loud(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    scheduled_refresh_state_path(paths).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "completed_slots": [],
                "exhausted_slots": [],
                "active_slots": ["first-open:2026-08-12"],
                "active_job_id": None,
                "attempt_number": 0,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ScheduledRefreshStateError, match="require a job id"):
        read_scheduled_refresh_state(paths)


def test_state_writes_schema_version_atomically(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.load_latest_successful_model_refresh",
        lambda _paths: None,
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.read_option_refresh_status",
        lambda _paths: OptionRefreshStatus(),
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.start_options_refresh",
        lambda _paths: _running_result("job-1"),
    )

    coordinate_scheduled_refresh(
        paths,
        trigger="first-open",
        now=datetime(2026, 8, 12, 7, 5, tzinfo=UTC),
    )
    payload = json.loads(scheduled_refresh_state_path(paths).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert not list(paths.runs_dir.glob("*.tmp*"))


# ---------------------------------------------------------------------------
# durable state must never brick an unattended install
# ---------------------------------------------------------------------------


def _stub_healthy_run(monkeypatch, starts: list[str]) -> None:
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.load_latest_successful_model_refresh",
        lambda _paths: None,
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.read_option_refresh_status",
        lambda _paths: OptionRefreshStatus(),
    )
    monkeypatch.setattr(
        "golden_vector.app.scheduled_refresh.start_options_refresh",
        lambda _paths: starts.append("job-1") or _running_result("job-1"),
    )


@pytest.mark.parametrize(
    "stored,expected_note",
    [
        ("{bad", "Could not read"),
        (
            json.dumps(
                {
                    "schema_version": 999,
                    "completed_slots": [],
                    "exhausted_slots": [],
                    "active_slots": [],
                    "attempt_number": 0,
                }
            ),
            "got 999",
        ),
    ],
    ids=["corrupt-file", "future-schema-version"],
)
def test_the_coordinator_rebuilds_unreadable_state_and_keeps_running(
    tmp_path, monkeypatch, stored, expected_note
):
    """A scheduled task runs under pythonw: a raise here is an invisible brick.

    Nothing repairs the file, so the install would simply stop refreshing --
    and a future SCHEDULED_REFRESH_STATE_VERSION bump would do it to every
    install at once. The coordinator rebuilds the state, records WHY, and runs.
    """

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    scheduled_refresh_state_path(paths).write_text(stored, encoding="utf-8")
    starts: list[str] = []
    _stub_healthy_run(monkeypatch, starts)

    decision = coordinate_scheduled_refresh(
        paths,
        trigger="first-open",
        now=datetime(2026, 8, 12, 7, 5, tzinfo=UTC),
    )

    assert decision.started is True
    assert starts == ["job-1"]

    payload = json.loads(scheduled_refresh_state_path(paths).read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert expected_note in payload["state_recovered_from_error"]
    assert payload["state_recovered_at_utc"] == "2026-08-12T07:05:00Z"
    # The rebuilt file is valid again: the fail-loud reader accepts it.
    assert read_scheduled_refresh_state(paths).state_recovered_from_error is not None


def test_a_healthy_state_is_never_marked_as_recovered(tmp_path, monkeypatch):
    """The control: a readable state file leaves no recovery breadcrumb."""

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    starts: list[str] = []
    _stub_healthy_run(monkeypatch, starts)

    coordinate_scheduled_refresh(
        paths,
        trigger="first-open",
        now=datetime(2026, 8, 12, 7, 5, tzinfo=UTC),
    )

    payload = json.loads(scheduled_refresh_state_path(paths).read_text(encoding="utf-8"))
    assert payload["state_recovered_from_error"] is None
    assert payload["state_recovered_at_utc"] is None
