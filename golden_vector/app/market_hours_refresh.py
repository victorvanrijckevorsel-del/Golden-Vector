"""Helpers for market-hours refresh scheduling.

The scheduler stays outside the web server. Windows Task Scheduler can call
``python main.py market-hours-refresh``; this module decides whether that
invocation is inside a normal US equity trading window before the expensive
refresh runs.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from golden_vector.contracts.config_models import OPTION_STALENESS_WARNING_TRADING_DAYS

US_MARKET_TIMEZONE = ZoneInfo("America/New_York")
DEFAULT_MARKET_START_ET = time(10, 0)
DEFAULT_MARKET_END_ET = time(15, 45)
DEFAULT_POST_CLOSE_REFRESH_ET = time(17, 0)
DEFAULT_LOCAL_TASK_TIMES = ("16:00", "19:30")
TASK_WEEKDAYS = "MON,TUE,WED,THU,FRI"


@dataclass(frozen=True)
class MarketHoursDecision:
    should_run: bool
    now_et: datetime
    reason: str


OPTION_FRESHNESS_LATEST = "LATEST"
OPTION_FRESHNESS_STORED = "STORED"
OPTION_FRESHNESS_STALE = "STALE"
OPTION_FRESHNESS_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class TradingDayFreshness:
    """Age of a persisted market snapshot in US trading days."""

    trading_days: int | None
    status: str


def count_completed_us_market_close_slots(
    since: datetime,
    *,
    through: datetime | None = None,
    close_et: time = DEFAULT_POST_CLOSE_REFRESH_ET,
) -> int:
    """Count US trading-day close slots available after ``since``.

    Unlike date-only snapshot age, the current trading date does not count
    until its configured post-close availability time. This is the shared
    basis for the product-wide last-refresh warning.
    """

    started = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
    ended = through or datetime.now(timezone.utc)
    if ended.tzinfo is None:
        ended = ended.replace(tzinfo=timezone.utc)
    started_et = started.astimezone(US_MARKET_TIMEZONE)
    ended_et = ended.astimezone(US_MARKET_TIMEZONE)
    if ended_et <= started_et:
        return 0
    count = 0
    current = started_et.date()
    while current <= ended_et.date():
        cutoff = datetime.combine(current, close_et, tzinfo=US_MARKET_TIMEZONE)
        if is_us_equity_trading_day(current) and started_et < cutoff <= ended_et:
            count += 1
        current += timedelta(days=1)
    return count


def classify_us_trading_day_freshness(
    source_date: date | str | None,
    *,
    through_date: date | None = None,
) -> TradingDayFreshness:
    """Classify a snapshot without treating weekends/holidays as missing days.

    Zero means the source is from the latest US trading date in the interval,
    anything below the configured warning age is a normal stored snapshot, and
    reaching it is the stronger STALE warning used by option-data screens.

    This is the ONLY place the warning age is compared against. Screens read the
    emitted status, never the number, so the threshold cannot be restated at a
    render site (contracts.config_models.OPTION_STALENESS_WARNING_TRADING_DAYS).
    """

    parsed = _coerce_date(source_date)
    end = through_date or datetime.now(timezone.utc).astimezone(US_MARKET_TIMEZONE).date()
    if parsed is None or parsed > end:
        return TradingDayFreshness(None, OPTION_FRESHNESS_UNKNOWN)
    age = sum(
        1
        for offset in range(1, (end - parsed).days + 1)
        if is_us_equity_trading_day(parsed + timedelta(days=offset))
    )
    if age == 0:
        status = OPTION_FRESHNESS_LATEST
    elif age < OPTION_STALENESS_WARNING_TRADING_DAYS:
        status = OPTION_FRESHNESS_STORED
    else:
        status = OPTION_FRESHNESS_STALE
    return TradingDayFreshness(age, status)


def market_hours_refresh_decision(
    *,
    now: datetime | None = None,
    start_et: time = DEFAULT_MARKET_START_ET,
    end_et: time = DEFAULT_MARKET_END_ET,
) -> MarketHoursDecision:
    """Return whether a scheduled refresh should run at ``now``.

    ``now`` can be any timezone-aware datetime. Naive values are treated as UTC
    to keep scheduled-task calls deterministic.
    """

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    now_et = instant.astimezone(US_MARKET_TIMEZONE)
    if not is_us_equity_trading_day(now_et.date()):
        return MarketHoursDecision(False, now_et, f"{now_et.date()} is not a US trading day.")
    current = now_et.time()
    if current < start_et or current > end_et:
        return MarketHoursDecision(
            False,
            now_et,
            f"{current.strftime('%H:%M')} ET is outside {start_et.strftime('%H:%M')}-{end_et.strftime('%H:%M')} ET.",
        )
    return MarketHoursDecision(True, now_et, f"{current.strftime('%H:%M')} ET is inside market hours.")


def is_us_equity_trading_day(day: date) -> bool:
    """Return False for weekends and standard full-day US equity holidays."""

    if day.weekday() >= 5:
        return False
    return day not in us_equity_market_holidays(day.year)


def us_equity_market_holidays(year: int) -> set[date]:
    """NYSE-style full-day holidays for the given year.

    This intentionally does not model early closes. The scheduled wrapper is a
    guardrail for refresh timing; it is not an exchange calendar package.
    """

    holidays = {
        _observed_fixed_holiday(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Presidents' Day
        _good_friday(year),
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_fixed_holiday(date(year, 6, 19)),
        _observed_fixed_holiday(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed_holiday(date(year, 12, 25)),
    }
    next_new_year_observed = _observed_fixed_holiday(date(year + 1, 1, 1))
    if next_new_year_observed.year == year:
        holidays.add(next_new_year_observed)
    return holidays


def windows_task_scheduler_commands(
    *,
    python_executable: str,
    main_py: Path,
    task_name: str = "Golden Vector Market Refresh",
    local_times: tuple[str, ...] = DEFAULT_LOCAL_TASK_TIMES,
) -> list[list[str]]:
    """Build ``schtasks`` commands without executing them."""

    main_path = str(main_py)
    task_run = f'"{python_executable}" "{main_path}" market-hours-refresh'
    commands: list[list[str]] = []
    for local_time in local_times:
        safe_suffix = local_time.replace(":", "")
        commands.append(
            [
                "schtasks",
                "/Create",
                "/TN",
                f"{task_name} {safe_suffix}",
                "/SC",
                "WEEKLY",
                "/D",
                TASK_WEEKDAYS,
                "/ST",
                local_time,
                "/TR",
                task_run,
                "/F",
            ]
        )
    return commands


def install_windows_task_scheduler_commands(commands: list[list[str]]) -> None:
    """Execute pre-built ``schtasks`` commands."""

    for command in commands:
        subprocess.run(command, check=True)


def parse_local_task_times(raw: str | tuple[str, ...] | None) -> tuple[str, ...]:
    if isinstance(raw, tuple):
        values = tuple(value.strip() for value in raw if value.strip())
    else:
        values = tuple(
            value.strip()
            for value in str(raw or "").split(",")
            if value.strip()
        )
    if not values:
        return DEFAULT_LOCAL_TASK_TIMES
    for value in values:
        _parse_hhmm(value)
    return values


def parse_market_time(raw: str | time | None, *, default: time) -> time:
    if isinstance(raw, time):
        return raw
    if not raw:
        return default
    return _parse_hhmm(raw)


def _parse_hhmm(raw: str) -> time:
    try:
        hour_raw, minute_raw = raw.split(":", 1)
        return time(int(hour_raw), int(minute_raw))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Expected HH:MM time, got {raw!r}.") from exc


def _coerce_date(value: date | str | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _observed_fixed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    return current + timedelta(days=7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def _good_friday(year: int) -> date:
    return _easter_sunday(year) - timedelta(days=2)


def _easter_sunday(year: int) -> date:
    # Meeus/Jones/Butcher Gregorian algorithm.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)
