"""Portable policy coordinator for unattended full-data refreshes.

This module owns timing, once-per-slot state, and retry decisions. Operating
system schedulers and future cloud schedulers only wake it; they do not contain
business rules.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from golden_vector.app.latest_successful_refresh import (
    SuccessfulModelRefresh,
    load_latest_successful_model_refresh,
)
from golden_vector.app.market_hours_refresh import (
    DEFAULT_POST_CLOSE_REFRESH_ET,
    US_MARKET_TIMEZONE,
    is_us_equity_trading_day,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.datetimes import parse_iso_datetime
from golden_vector.common.files import atomic_write_text
from golden_vector.common.files import release_exclusive_file_lock
from golden_vector.common.files import try_acquire_exclusive_file_lock
from golden_vector.serve.option_refresh import (
    REFRESH_STATUS_FAILED,
    REFRESH_STATUS_RUNNING,
    REFRESH_STATUS_SUCCEEDED,
    OptionRefreshStartResult,
    OptionRefreshStatus,
    read_option_refresh_status,
    start_options_refresh,
)

SCHEDULED_REFRESH_STATE_VERSION = 1
SCHEDULED_REFRESH_STATE_FILE = "scheduled_refresh_state.json"
POST_CLOSE_TIME_ET = DEFAULT_POST_CLOSE_REFRESH_ET
RETRY_DELAYS_MINUTES = (15, 30, 60)
TRIGGER_FIRST_OPEN = "first-open"
TRIGGER_POST_CLOSE = "post-close"
TRIGGER_RETRY = "retry"
ScheduledRefreshTrigger = Literal["first-open", "post-close", "retry"]
VALID_TRIGGERS = frozenset({TRIGGER_FIRST_OPEN, TRIGGER_POST_CLOSE, TRIGGER_RETRY})

ACTION_STARTED = "started"
ACTION_WAITING = "waiting"
ACTION_SKIPPED = "skipped"
ACTION_RETRY_SCHEDULED = "retry-scheduled"
ACTION_RETRY_EXHAUSTED = "retry-exhausted"


class ScheduledRefreshStateError(RuntimeError):
    """Raised when durable scheduler state is unreadable or incompatible."""


@dataclass(frozen=True)
class ScheduledRefreshState:
    schema_version: int = SCHEDULED_REFRESH_STATE_VERSION
    completed_slots: tuple[str, ...] = ()
    exhausted_slots: tuple[str, ...] = ()
    active_slots: tuple[str, ...] = ()
    active_job_id: str | None = None
    attempt_number: int = 0
    last_attempt_started_at_utc: str | None = None
    next_retry_at_utc: str | None = None
    last_decision_at_utc: str | None = None
    last_decision: str | None = None
    last_error: str | None = None
    #: Breadcrumb left when the coordinator had to rebuild this file because the
    #: stored one was unreadable or written by another schema version.
    state_recovered_from_error: str | None = None
    state_recovered_at_utc: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "completed_slots": list(self.completed_slots),
            "exhausted_slots": list(self.exhausted_slots),
            "active_slots": list(self.active_slots),
            "active_job_id": self.active_job_id,
            "attempt_number": self.attempt_number,
            "last_attempt_started_at_utc": self.last_attempt_started_at_utc,
            "next_retry_at_utc": self.next_retry_at_utc,
            "last_decision_at_utc": self.last_decision_at_utc,
            "last_decision": self.last_decision,
            "last_error": self.last_error,
            "state_recovered_from_error": self.state_recovered_from_error,
            "state_recovered_at_utc": self.state_recovered_at_utc,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ScheduledRefreshState":
        version = payload.get("schema_version")
        if type(version) is not int or version != SCHEDULED_REFRESH_STATE_VERSION:
            raise ScheduledRefreshStateError(
                "Unsupported scheduled-refresh state schema: "
                f"expected {SCHEDULED_REFRESH_STATE_VERSION}, got {version!r}."
            )
        attempt_number = payload.get("attempt_number", 0)
        if type(attempt_number) is not int or attempt_number < 0:
            raise ScheduledRefreshStateError(
                "Scheduled-refresh state attempt_number must be a non-negative integer."
            )
        state = cls(
            schema_version=version,
            completed_slots=_string_tuple(payload, "completed_slots"),
            exhausted_slots=_string_tuple(payload, "exhausted_slots"),
            active_slots=_string_tuple(payload, "active_slots"),
            active_job_id=_optional_text(payload.get("active_job_id")),
            attempt_number=attempt_number,
            last_attempt_started_at_utc=_optional_text(payload.get("last_attempt_started_at_utc")),
            next_retry_at_utc=_optional_text(payload.get("next_retry_at_utc")),
            last_decision_at_utc=_optional_text(payload.get("last_decision_at_utc")),
            last_decision=_optional_text(payload.get("last_decision")),
            last_error=_optional_text(payload.get("last_error")),
            state_recovered_from_error=_optional_text(
                payload.get("state_recovered_from_error")
            ),
            state_recovered_at_utc=_optional_text(payload.get("state_recovered_at_utc")),
        )
        if state.active_slots and (state.attempt_number < 1 or state.active_job_id is None):
            raise ScheduledRefreshStateError(
                "Active scheduled-refresh slots require a job id and positive attempt number."
            )
        if not state.active_slots and (
            state.attempt_number != 0
            or state.active_job_id is not None
            or state.next_retry_at_utc is not None
        ):
            raise ScheduledRefreshStateError(
                "Inactive scheduled-refresh state cannot retain attempt or retry fields."
            )
        return state


@dataclass(frozen=True)
class ScheduledRefreshDecision:
    action: str
    reason: str
    state: ScheduledRefreshState
    refresh_status: OptionRefreshStatus

    @property
    def started(self) -> bool:
        return self.action == ACTION_STARTED


def scheduled_refresh_state_path(paths: ProjectPaths) -> Path:
    return paths.runs_dir / SCHEDULED_REFRESH_STATE_FILE


def read_scheduled_refresh_state(paths: ProjectPaths) -> ScheduledRefreshState:
    """Fail-loud read for tools and tests.

    The unattended coordinator must never brick on this, so it reads through
    ``_read_state_or_recover`` instead: under ``pythonw`` there is no console
    to show the traceback, nothing repairs the file, and a future
    ``SCHEDULED_REFRESH_STATE_VERSION`` bump would silently stop every install
    from ever refreshing again.
    """

    path = scheduled_refresh_state_path(paths)
    if not path.exists():
        return ScheduledRefreshState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ScheduledRefreshStateError(
            f"Could not read scheduled-refresh state at {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ScheduledRefreshStateError(
            f"Scheduled-refresh state at {path} must contain a JSON object."
        )
    return ScheduledRefreshState.from_payload(payload)


def write_scheduled_refresh_state(
    paths: ProjectPaths,
    state: ScheduledRefreshState,
) -> Path:
    path = scheduled_refresh_state_path(paths)
    return atomic_write_text(
        path,
        json.dumps(state.to_payload(), indent=2, sort_keys=True) + "\n",
    )


def _read_state_or_recover(
    paths: ProjectPaths,
    *,
    persist: bool,
    now_utc: datetime | None = None,
) -> ScheduledRefreshState:
    """Read durable state, rebuilding it in place when it cannot be read.

    A corrupt or version-mismatched state file used to raise out of the
    scheduled task, which under ``pythonw`` fails invisibly and forever: no
    console, no repair, no refresh. Rebuilding the default state records WHY
    (message + the version that was found) so the recovery is auditable rather
    than silent, then the run continues -- the manifest re-marks any slot the
    last successful refresh already satisfied, so nothing is double-run.

    ``persist`` is False when another process holds the decision lock: that
    process owns the file, and this one only needs a state to report.
    """

    try:
        return read_scheduled_refresh_state(paths)
    except ScheduledRefreshStateError as exc:
        recovered = ScheduledRefreshState(
            state_recovered_from_error=_trim_error(str(exc)),
            state_recovered_at_utc=_iso_utc(now_utc or datetime.now(UTC)),
        )
        if persist:
            write_scheduled_refresh_state(paths, recovered)
        return recovered


def coordinate_scheduled_refresh(
    paths: ProjectPaths,
    *,
    trigger: ScheduledRefreshTrigger,
    now: datetime | None = None,
) -> ScheduledRefreshDecision:
    """Reconcile prior work, decide whether data is due, and start one worker.

    ``now`` should use the computer/cloud scheduler's local timezone. Naive
    values are treated as UTC. The US post-close slot is always calculated in
    Eastern Time, including daylight-saving transitions.
    """

    if trigger not in VALID_TRIGGERS:
        raise ValueError(f"Unknown scheduled refresh trigger: {trigger!r}.")
    instant = _aware_datetime(now)
    now_utc = instant.astimezone(UTC)
    lock_path = scheduled_refresh_state_path(paths).with_suffix(".acquire.lock")
    lock_handle = try_acquire_exclusive_file_lock(lock_path)
    if lock_handle is None:
        return ScheduledRefreshDecision(
            action=ACTION_WAITING,
            reason="Another scheduler decision is already in progress.",
            state=_read_state_or_recover(paths, persist=False, now_utc=now_utc),
            refresh_status=read_option_refresh_status(paths),
        )
    try:
        return _coordinate_locked(paths, trigger=trigger, instant=instant, now_utc=now_utc)
    finally:
        release_exclusive_file_lock(lock_path, lock_handle)


def _coordinate_locked(
    paths: ProjectPaths,
    *,
    trigger: ScheduledRefreshTrigger,
    instant: datetime,
    now_utc: datetime,
) -> ScheduledRefreshDecision:
    state = _prune_state(
        _read_state_or_recover(paths, persist=True, now_utc=now_utc),
        instant=instant,
    )
    latest_success = load_latest_successful_model_refresh(paths)
    current_slots = _current_slot_ids(instant)
    state = _mark_manifest_satisfied_slots(
        state,
        slots=tuple(dict.fromkeys((*current_slots, *state.active_slots))),
        latest_success=latest_success,
        local_timezone=instant.tzinfo,
    )
    refresh_status = read_option_refresh_status(paths)

    if state.active_slots:
        observed_active_slots = state.active_slots
        if all(slot in state.completed_slots for slot in state.active_slots):
            state = _clear_active(state)
        elif (
            refresh_status.job_id == state.active_job_id
            and refresh_status.status == REFRESH_STATUS_RUNNING
        ):
            return _persist_decision(
                paths,
                state,
                refresh_status,
                now_utc=now_utc,
                action=ACTION_WAITING,
                reason=f"Refresh attempt {state.attempt_number} is still running.",
            )
        elif (
            refresh_status.job_id == state.active_job_id
            and refresh_status.status == REFRESH_STATUS_SUCCEEDED
        ):
            state = _schedule_retry_or_exhaust(
                state,
                failed_at=parse_iso_datetime(refresh_status.finished_at) or now_utc,
                error=(
                    "Refresh finished without publishing a newer complete model-state manifest."
                ),
            )
        else:
            state = _record_observed_failure(
                state,
                refresh_status=refresh_status,
                now_utc=now_utc,
            )

        if (
            not state.active_slots
            and observed_active_slots
            and all(slot in state.exhausted_slots for slot in observed_active_slots)
        ):
            return _persist_decision(
                paths,
                state,
                refresh_status,
                now_utc=now_utc,
                action=ACTION_RETRY_EXHAUSTED,
                reason="Scheduled refresh exhausted its 15/30/60 minute retries.",
            )

        if state.active_slots:
            next_retry = parse_iso_datetime(state.next_retry_at_utc)
            if next_retry is None:
                state = _exhaust_active(state)
                return _persist_decision(
                    paths,
                    state,
                    refresh_status,
                    now_utc=now_utc,
                    action=ACTION_RETRY_EXHAUSTED,
                    reason="Scheduled refresh exhausted its 15/30/60 minute retries.",
                )
            if now_utc < next_retry.astimezone(UTC):
                return _persist_decision(
                    paths,
                    state,
                    refresh_status,
                    now_utc=now_utc,
                    action=ACTION_WAITING,
                    reason=f"Retry {state.attempt_number + 1} is scheduled for {state.next_retry_at_utc}.",
                )
            return _start_attempt(
                paths,
                state,
                slots=state.active_slots,
                attempt_number=state.attempt_number + 1,
                now_utc=now_utc,
            )

    if trigger == TRIGGER_RETRY:
        return _persist_decision(
            paths,
            state,
            refresh_status,
            now_utc=now_utc,
            action=ACTION_SKIPPED,
            reason="No failed scheduled refresh is waiting for a retry.",
        )

    post_close_due = any(slot.startswith(f"{TRIGGER_POST_CLOSE}:") for slot in current_slots)
    if trigger == TRIGGER_POST_CLOSE and not post_close_due:
        return _persist_decision(
            paths,
            state,
            refresh_status,
            now_utc=now_utc,
            action=ACTION_SKIPPED,
            reason="The 17:00 ET post-close slot is not due on this trading day.",
        )

    due_slots = tuple(
        slot
        for slot in current_slots
        if slot not in state.completed_slots and slot not in state.exhausted_slots
    )
    if not due_slots:
        return _persist_decision(
            paths,
            state,
            refresh_status,
            now_utc=now_utc,
            action=ACTION_SKIPPED,
            reason="All refresh slots currently due are already satisfied.",
        )
    return _start_attempt(
        paths,
        state,
        slots=due_slots,
        attempt_number=1,
        now_utc=now_utc,
    )


def _start_attempt(
    paths: ProjectPaths,
    state: ScheduledRefreshState,
    *,
    slots: tuple[str, ...],
    attempt_number: int,
    now_utc: datetime,
) -> ScheduledRefreshDecision:
    result: OptionRefreshStartResult = start_options_refresh(paths)
    if result.already_running:
        return _persist_decision(
            paths,
            state,
            result.status,
            now_utc=now_utc,
            action=ACTION_WAITING,
            reason="A full refresh is already running; this scheduled invocation did not duplicate it.",
        )

    started_at = parse_iso_datetime(result.status.started_at) or now_utc
    state = replace(
        state,
        active_slots=slots,
        active_job_id=result.status.job_id,
        attempt_number=attempt_number,
        last_attempt_started_at_utc=_iso_utc(started_at),
        next_retry_at_utc=None,
        last_error=None,
    )
    if result.started and result.status.status == REFRESH_STATUS_RUNNING:
        return _persist_decision(
            paths,
            state,
            result.status,
            now_utc=now_utc,
            action=ACTION_STARTED,
            reason=f"Started scheduled refresh attempt {attempt_number} for {', '.join(slots)}.",
        )

    state = _schedule_retry_or_exhaust(
        state,
        failed_at=parse_iso_datetime(result.status.finished_at) or now_utc,
        error=result.status.error_summary or "Refresh process could not be started.",
    )
    if state.active_slots:
        return _persist_decision(
            paths,
            state,
            result.status,
            now_utc=now_utc,
            action=ACTION_RETRY_SCHEDULED,
            reason=f"Refresh attempt {attempt_number} failed; next retry is {state.next_retry_at_utc}.",
        )
    return _persist_decision(
        paths,
        state,
        result.status,
        now_utc=now_utc,
        action=ACTION_RETRY_EXHAUSTED,
        reason="Scheduled refresh exhausted its 15/30/60 minute retries.",
    )


def _record_observed_failure(
    state: ScheduledRefreshState,
    *,
    refresh_status: OptionRefreshStatus,
    now_utc: datetime,
) -> ScheduledRefreshState:
    if state.next_retry_at_utc is not None:
        return state
    failed_at = parse_iso_datetime(refresh_status.finished_at) or now_utc
    error = refresh_status.error_summary
    if refresh_status.job_id != state.active_job_id:
        error = "The scheduled refresh job is no longer the active refresh job."
    elif refresh_status.status != REFRESH_STATUS_FAILED:
        error = "The scheduled refresh job stopped without a success status."
    return _schedule_retry_or_exhaust(state, failed_at=failed_at, error=error)


def _schedule_retry_or_exhaust(
    state: ScheduledRefreshState,
    *,
    failed_at: datetime,
    error: str | None,
) -> ScheduledRefreshState:
    if state.attempt_number > len(RETRY_DELAYS_MINUTES):
        return _exhaust_active(replace(state, last_error=_trim_error(error)))
    delay = RETRY_DELAYS_MINUTES[state.attempt_number - 1]
    return replace(
        state,
        next_retry_at_utc=_iso_utc(failed_at + timedelta(minutes=delay)),
        last_error=_trim_error(error),
    )


def _exhaust_active(state: ScheduledRefreshState) -> ScheduledRefreshState:
    exhausted = _merge_slots(state.exhausted_slots, state.active_slots)
    return replace(
        _clear_active(state),
        exhausted_slots=exhausted,
    )


def _clear_active(state: ScheduledRefreshState) -> ScheduledRefreshState:
    return replace(
        state,
        active_slots=(),
        active_job_id=None,
        attempt_number=0,
        last_attempt_started_at_utc=None,
        next_retry_at_utc=None,
    )


def _persist_decision(
    paths: ProjectPaths,
    state: ScheduledRefreshState,
    refresh_status: OptionRefreshStatus,
    *,
    now_utc: datetime,
    action: str,
    reason: str,
) -> ScheduledRefreshDecision:
    updated = replace(
        state,
        last_decision_at_utc=_iso_utc(now_utc),
        last_decision=action,
    )
    write_scheduled_refresh_state(paths, updated)
    return ScheduledRefreshDecision(
        action=action,
        reason=reason,
        state=updated,
        refresh_status=refresh_status,
    )


def _current_slot_ids(instant: datetime) -> tuple[str, ...]:
    slots = [_slot_id(TRIGGER_FIRST_OPEN, instant.date().isoformat())]
    now_et = instant.astimezone(US_MARKET_TIMEZONE)
    if (
        is_us_equity_trading_day(now_et.date())
        and now_et.timetz().replace(tzinfo=None) >= POST_CLOSE_TIME_ET
    ):
        slots.append(_slot_id(TRIGGER_POST_CLOSE, now_et.date().isoformat()))
    return tuple(slots)


def _mark_manifest_satisfied_slots(
    state: ScheduledRefreshState,
    *,
    slots: tuple[str, ...],
    latest_success: SuccessfulModelRefresh | None,
    local_timezone: Any,
) -> ScheduledRefreshState:
    if latest_success is None:
        return state
    satisfied = tuple(
        slot
        for slot in slots
        if _successful_refresh_satisfies_slot(
            latest_success.generated_at,
            slot,
            local_timezone=local_timezone,
        )
    )
    if not satisfied:
        return state
    return replace(
        state,
        completed_slots=_merge_slots(state.completed_slots, satisfied),
        exhausted_slots=tuple(slot for slot in state.exhausted_slots if slot not in satisfied),
    )


def _successful_refresh_satisfies_slot(
    generated_at: datetime,
    slot: str,
    *,
    local_timezone: Any,
) -> bool:
    kind, raw_day = _split_slot(slot)
    try:
        day = datetime.fromisoformat(raw_day).date()
    except ValueError:
        return False
    if kind == TRIGGER_FIRST_OPEN:
        return generated_at.astimezone(local_timezone).date() >= day
    if kind == TRIGGER_POST_CLOSE:
        cutoff = datetime.combine(day, POST_CLOSE_TIME_ET, tzinfo=US_MARKET_TIMEZONE)
        return generated_at >= cutoff
    return False


def _prune_state(
    state: ScheduledRefreshState,
    *,
    instant: datetime,
) -> ScheduledRefreshState:
    cutoff = instant.date() - timedelta(days=31)

    def keep(slot: str) -> bool:
        _kind, raw_day = _split_slot(slot)
        try:
            return datetime.fromisoformat(raw_day).date() >= cutoff
        except ValueError:
            return False

    active = set(state.active_slots)
    return replace(
        state,
        completed_slots=tuple(slot for slot in state.completed_slots if keep(slot)),
        exhausted_slots=tuple(
            slot for slot in state.exhausted_slots if keep(slot) or slot in active
        ),
    )


def _string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ScheduledRefreshStateError(
            f"Scheduled-refresh state {key} must be a list of strings."
        )
    return tuple(dict.fromkeys(item for item in value if item))


def _merge_slots(existing: tuple[str, ...], added: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*existing, *added)))


def _slot_id(kind: str, raw_day: str) -> str:
    return f"{kind}:{raw_day}"


def _split_slot(slot: str) -> tuple[str, str]:
    kind, separator, raw_day = slot.partition(":")
    return (kind, raw_day) if separator else ("", "")


def _aware_datetime(value: datetime | None) -> datetime:
    instant = value or datetime.now().astimezone()
    return instant if instant.tzinfo is not None else instant.replace(tzinfo=UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _trim_error(value: str | None) -> str | None:
    text = _optional_text(value)
    return text[:500] if text else None
