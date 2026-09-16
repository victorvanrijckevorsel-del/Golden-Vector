from threading import Event
from types import SimpleNamespace

import pytest

from golden_vector.app import hosted_scheduler
from golden_vector.app.scheduled_refresh import TRIGGER_FIRST_OPEN


def test_hosted_scheduler_reuses_policy_and_stops(monkeypatch):
    stop = Event()
    calls = []
    paths = object()

    def coordinate(actual_paths, *, trigger):
        calls.append((actual_paths, trigger))
        stop.set()
        return SimpleNamespace(action="skipped", reason="Already complete")

    monkeypatch.setattr(hosted_scheduler, "coordinate_scheduled_refresh", coordinate)
    hosted_scheduler.run_scheduler(paths, stop)
    assert calls == [(paths, TRIGGER_FIRST_OPEN)]


def test_hosted_scheduler_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GV_ENABLE_HOSTED_REFRESH", raising=False)
    with pytest.raises(SystemExit, match="disabled"):
        hosted_scheduler.main()


def test_hosted_scheduler_does_not_spin_or_hide_errors(monkeypatch):
    with pytest.raises(ValueError, match="ten seconds"):
        hosted_scheduler.run_scheduler(object(), Event(), interval_seconds=0)

    def failed(*args, **kwargs):
        raise OSError("Persistent store unavailable")

    monkeypatch.setattr(hosted_scheduler, "coordinate_scheduled_refresh", failed)
    with pytest.raises(OSError, match="Persistent store unavailable"):
        hosted_scheduler.run_scheduler(object(), Event())
