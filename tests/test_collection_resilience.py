from datetime import datetime, timezone

from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.collection_resilience import (
    RetryPolicy,
    call_with_retries,
    summarize_fetch_statuses,
)


def test_call_with_retries_returns_after_transient_failure():
    attempts = {"count": 0}
    sleeps: list[float] = []

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary")
        return "ok"

    result = call_with_retries(
        "test operation",
        flaky,
        policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.25),
        sleep_func=sleeps.append,
    )

    assert result == "ok"
    assert attempts["count"] == 2
    assert sleeps == [0.25]


def test_summarize_fetch_statuses_records_failures_and_slowest_rows():
    started = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    records = [
        FetchStatusRecord(
            dataset="equities",
            entity="AEM",
            source_symbol="AEM",
            status="PASS",
            row_count=10,
            started_at_utc=started,
            completed_at_utc=started.replace(second=2),
        ),
        FetchStatusRecord(
            dataset="fx",
            entity="CAD",
            source_symbol="CADUSD=X",
            status="FAIL",
            row_count=0,
            started_at_utc=started,
            completed_at_utc=started.replace(second=12),
            message="temporary",
        ),
    ]

    summary = summarize_fetch_statuses(records, slow_threshold_seconds=10)

    assert summary["total_count"] == 2
    assert summary["pass_count"] == 1
    assert summary["fail_count"] == 1
    assert summary["slow_count"] == 1
    assert summary["failed"][0]["entity"] == "CAD"
    assert summary["slowest"][0]["duration_seconds"] == 12.0
