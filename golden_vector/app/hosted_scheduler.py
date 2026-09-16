"""Service adapter for the existing refresh policy; never run in HTTP requests."""

import logging
import os
import signal
from threading import Event

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.scheduled_refresh import coordinate_scheduled_refresh, TRIGGER_FIRST_OPEN

LOGGER = logging.getLogger(__name__)


def run_scheduler(paths: ProjectPaths, stop: Event, *, interval_seconds: int = 60) -> None:
    if interval_seconds < 10:
        raise ValueError("Scheduler interval must be at least ten seconds.")
    previous = None
    while not stop.is_set():
        # The shared coordinator owns daily/post-close slots, retries, and the
        # single-writer guard. Staying alive also keeps detached jobs in this
        # service's cgroup until completion (unlike a systemd oneshot adapter).
        decision = coordinate_scheduled_refresh(paths, trigger=TRIGGER_FIRST_OPEN)
        current = (decision.action, decision.reason)
        if current != previous:
            LOGGER.info("Scheduled refresh: %s — %s", *current)
            previous = current
        stop.wait(interval_seconds)


def main() -> None:
    if os.environ.get("GV_ENABLE_HOSTED_REFRESH") != "1":
        raise SystemExit("Hosted refresh is disabled. Obtain approval for provider/API use before enabling it.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    run_scheduler(ProjectPaths.discover(), stop)


if __name__ == "__main__":
    main()
