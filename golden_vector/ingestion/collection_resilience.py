"""Shared retry and collection-stat helpers for market-data ingestion."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from random import random as default_random
from time import sleep as default_sleep
from typing import TypeVar

import pandas as pd

from golden_vector.common.numeric import int_or_zero, is_missing, optional_float
from golden_vector.contracts.config_models import MarketDataConfig
from golden_vector.contracts.data_models import FetchStatusRecord

T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class RetryPolicy:
    """Retry/backoff settings for unofficial Yahoo/yfinance calls."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.5
    backoff_multiplier: float = 2.0
    throttle_seconds: float = 0.0
    backoff_jitter_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if self.initial_backoff_seconds < 0 or self.backoff_jitter_seconds < 0:
            raise ValueError("backoff timing values must be non-negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if self.throttle_seconds < 0:
            raise ValueError("throttle_seconds must be non-negative")


def retry_policy_from_config(config: MarketDataConfig) -> RetryPolicy:
    """Build the Yahoo retry policy from validated app config."""

    return RetryPolicy(
        max_attempts=config.yahoo_max_attempts,
        initial_backoff_seconds=config.yahoo_initial_backoff_seconds,
        backoff_multiplier=config.yahoo_backoff_multiplier,
        throttle_seconds=config.yahoo_throttle_seconds,
        backoff_jitter_seconds=config.yahoo_backoff_jitter_seconds,
    )


def bounded_worker_count(*, max_workers: int, item_count: int) -> int:
    """Return a safe worker count for a bounded parallel collection step."""

    if max_workers <= 0:
        raise ValueError("max_workers must be positive")
    if item_count <= 0:
        return 0
    return max(1, min(int(max_workers), item_count))


def map_with_bounded_workers(
    items: Iterable[T],
    *,
    max_workers: int,
    func: Callable[[T], U],
) -> list[U]:
    """Apply ``func`` with bounded workers while preserving input order."""

    item_list = list(items)
    worker_count = bounded_worker_count(
        max_workers=max_workers,
        item_count=len(item_list),
    )
    if worker_count <= 1:
        return [func(item) for item in item_list]
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        return list(executor.map(func, item_list))


def call_with_retries(
    operation: str,
    func: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    logger: logging.Logger | None = None,
    sleep_func: Callable[[float], None] = default_sleep,
    random_func: Callable[[], float] = default_random,
    before_attempt: Callable[[], None] | None = None,
) -> T:
    """Run ``func`` with retry/backoff, preserving the original final exception."""

    retry_policy = policy or RetryPolicy()
    active_logger = logger or logging.getLogger(__name__)
    backoff = retry_policy.initial_backoff_seconds
    last_attempt = retry_policy.max_attempts
    for attempt in range(1, last_attempt + 1):
        try:
            if before_attempt is not None:
                before_attempt()
            result = func()
            if retry_policy.throttle_seconds:
                sleep_func(retry_policy.throttle_seconds)
            return result
        except Exception as exc:
            if attempt >= last_attempt:
                raise
            sleep_seconds = backoff + _jitter_seconds(
                retry_policy.backoff_jitter_seconds,
                random_func=random_func,
            )
            active_logger.warning(
                "%s failed on attempt %s/%s: %s. Retrying in %.2fs.",
                operation,
                attempt,
                last_attempt,
                exc,
                sleep_seconds,
            )
            if sleep_seconds:
                sleep_func(sleep_seconds)
            backoff *= retry_policy.backoff_multiplier

    raise RuntimeError(f"{operation} retry loop exited unexpectedly")


def _jitter_seconds(
    max_jitter_seconds: float,
    *,
    random_func: Callable[[], float],
) -> float:
    if max_jitter_seconds <= 0:
        return 0.0
    return float(max_jitter_seconds) * max(0.0, min(1.0, float(random_func())))


def summarize_fetch_statuses(
    statuses: Iterable[FetchStatusRecord],
    *,
    slow_threshold_seconds: float = 10.0,
    max_items: int = 10,
) -> dict[str, object]:
    """Summarize per-entity foundation fetch statuses for manifest telemetry."""

    rows = [
        {
            "dataset": status.dataset,
            "entity": status.entity,
            "source_symbol": status.source_symbol,
            "status": status.status,
            "row_count": int(status.row_count),
            "duration_seconds": _duration_seconds(
                status.started_at_utc,
                status.completed_at_utc,
            ),
            "message": status.message,
        }
        for status in statuses
    ]
    return summarize_fetch_status_rows(
        pd.DataFrame(rows),
        slow_threshold_seconds=slow_threshold_seconds,
        max_items=max_items,
    )


def failed_fetch_entities(
    statuses: Iterable[FetchStatusRecord],
    *,
    dataset: str,
) -> set[str]:
    """Return entities whose fetch failed for one dataset."""

    return {
        status.entity
        for status in statuses
        if status.dataset == dataset and str(status.status).upper() == "FAIL"
    }


def summarize_fetch_status_rows(
    frame: pd.DataFrame,
    *,
    slow_threshold_seconds: float = 10.0,
    max_items: int = 10,
) -> dict[str, object]:
    """Summarize a persisted fetch-status table using the same manifest shape."""

    if frame.empty:
        return {
            "total_count": 0,
            "pass_count": 0,
            "fail_count": 0,
            "slow_count": 0,
            "failed": [],
            "slowest": [],
        }

    working = frame.copy()
    if "duration_seconds" not in working.columns:
        started_values = (
            working["started_at_utc"]
            if "started_at_utc" in working.columns
            else [None] * len(working.index)
        )
        completed_values = (
            working["completed_at_utc"]
            if "completed_at_utc" in working.columns
            else [None] * len(working.index)
        )
        working["duration_seconds"] = [
            _duration_seconds(started, completed)
            for started, completed in zip(
                started_values,
                completed_values,
                strict=False,
            )
        ]
    status_values = (
        working["status"]
        if "status" in working.columns
        else pd.Series(["UNKNOWN"] * len(working.index), index=working.index)
    )
    status = status_values.astype(str).str.upper()
    failures = working[status == "FAIL"].copy()
    duration = pd.to_numeric(working["duration_seconds"], errors="coerce")
    slow = working[duration >= float(slow_threshold_seconds)].copy()
    return {
        "total_count": int(len(working.index)),
        "pass_count": int((status == "PASS").sum()),
        "fail_count": int((status == "FAIL").sum()),
        "slow_count": int(len(slow.index)),
        "failed": _status_rows(failures, max_items=max_items),
        "slowest": _status_rows(
            working.sort_values("duration_seconds", ascending=False),
            max_items=max_items,
        ),
    }


def _status_rows(frame: pd.DataFrame, *, max_items: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, row in frame.head(max_items).iterrows():
        rows.append(
            {
                "dataset": _string_value(row.get("dataset")),
                "entity": _string_value(row.get("entity")),
                "source_symbol": _string_value(row.get("source_symbol")),
                "status": _string_value(row.get("status")),
                "row_count": int_or_zero(row.get("row_count")),
                "duration_seconds": optional_float(row.get("duration_seconds")),
                "message": _string_value(row.get("message")) or None,
            }
        )
    return rows


def _duration_seconds(started: object, completed: object) -> float | None:
    start_dt = _as_datetime(started)
    completed_dt = _as_datetime(completed)
    if start_dt is None or completed_dt is None:
        return None
    return max(0.0, round((completed_dt - start_dt).total_seconds(), 3))


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if _is_missing(value):
        return None
    try:
        parsed = pd.to_datetime(value, utc=True)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def _string_value(value: object) -> str:
    if _is_missing(value):
        return ""
    return str(value)


def _is_missing(value: object) -> bool:
    return is_missing(value)
