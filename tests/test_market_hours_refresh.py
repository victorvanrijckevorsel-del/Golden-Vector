from __future__ import annotations

from datetime import date, datetime, time, timezone

from golden_vector.app.market_hours_refresh import (
    OPTION_FRESHNESS_LATEST,
    OPTION_FRESHNESS_STALE,
    OPTION_FRESHNESS_STORED,
    classify_us_trading_day_freshness,
    count_completed_us_market_close_slots,
    is_us_equity_trading_day,
    market_hours_refresh_decision,
    parse_local_task_times,
    parse_market_time,
    windows_task_scheduler_commands,
)
from golden_vector.cli import (
    run_install_market_hours_refresh_task,
    run_market_hours_refresh,
)
from tests.helpers import build_test_paths


def test_us_equity_trading_day_excludes_weekends_and_core_holidays():
    assert not is_us_equity_trading_day(date(2026, 6, 7))
    assert not is_us_equity_trading_day(date(2026, 6, 19))
    assert not is_us_equity_trading_day(date(2026, 4, 3))
    assert not is_us_equity_trading_day(date(2026, 7, 3))
    assert not is_us_equity_trading_day(date(2021, 12, 31))
    assert is_us_equity_trading_day(date(2026, 6, 8))


def test_market_hours_refresh_decision_uses_eastern_time_and_dst():
    inside = market_hours_refresh_decision(
        now=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )
    after_close = market_hours_refresh_decision(
        now=datetime(2026, 6, 8, 21, 0, tzinfo=timezone.utc),
    )

    assert inside.should_run
    assert "inside market hours" in inside.reason
    assert not after_close.should_run
    assert "outside" in after_close.reason


def test_completed_close_slots_do_not_count_current_day_before_5pm_et():
    friday_close = datetime(2026, 8, 7, 21, 0, tzinfo=timezone.utc)

    assert count_completed_us_market_close_slots(
        friday_close,
        through=datetime(2026, 8, 11, 20, 59, tzinfo=timezone.utc),
    ) == 1  # Monday only
    assert count_completed_us_market_close_slots(
        friday_close,
        through=datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc),
    ) == 2  # Monday + Tuesday


def test_option_snapshot_freshness_counts_only_us_trading_days():
    latest = classify_us_trading_day_freshness(
        "2026-08-07", through_date=date(2026, 8, 9)
    )
    stored = classify_us_trading_day_freshness(
        "2026-08-07", through_date=date(2026, 8, 11)
    )
    stale = classify_us_trading_day_freshness(
        "2026-08-07", through_date=date(2026, 8, 12)
    )

    assert (latest.trading_days, latest.status) == (0, OPTION_FRESHNESS_LATEST)
    assert (stored.trading_days, stored.status) == (2, OPTION_FRESHNESS_STORED)
    assert (stale.trading_days, stale.status) == (3, OPTION_FRESHNESS_STALE)


def test_windows_task_scheduler_commands_call_guard_command(tmp_path):
    commands = windows_task_scheduler_commands(
        python_executable="C:\\Python\\python.exe",
        main_py=tmp_path / "main.py",
        task_name="Golden Vector Test Refresh",
        local_times=("16:00", "19:30"),
    )

    assert len(commands) == 2
    assert commands[0][:2] == ["schtasks", "/Create"]
    assert "MON,TUE,WED,THU,FRI" in commands[0]
    assert "market-hours-refresh" in " ".join(commands[0])
    assert commands[0][commands[0].index("/ST") + 1] == "16:00"


def test_run_market_hours_refresh_skips_outside_guard(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)

    def fail_refresh(*args, **kwargs):
        raise AssertionError("refresh should not run outside the guard")

    monkeypatch.setattr("golden_vector.cli.run_refresh", fail_refresh)

    exit_code = run_market_hours_refresh(
        paths,
        now=datetime(2026, 6, 7, 15, 0, tzinfo=timezone.utc),
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SKIP" in output
    assert "daily-close based" in output


def test_run_market_hours_refresh_rejects_inverted_time_window(tmp_path, capsys):
    paths = build_test_paths(tmp_path)

    exit_code = run_market_hours_refresh(
        paths,
        now=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
        start_et=time(16, 0),
        end_et=time(10, 0),
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert "Invalid market-hours refresh window" in output


def test_run_market_hours_refresh_runs_inside_guard(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    calls: list[tuple[object, bool]] = []

    def fake_refresh(received_paths, *, gold_price_override=None, skip_tool_b=False):
        calls.append((gold_price_override, skip_tool_b))
        assert received_paths == paths
        return 0

    monkeypatch.setattr("golden_vector.cli.run_refresh", fake_refresh)

    exit_code = run_market_hours_refresh(
        paths,
        gold_price_override=2600.0,
        skip_tool_b=True,
        now=datetime(2026, 6, 8, 15, 0, tzinfo=timezone.utc),
    )

    assert exit_code == 0
    assert calls == [(2600.0, True)]


def test_scheduler_time_parsers_accept_strings_and_parsed_values():
    parsed = time(16, 0)

    assert parse_market_time("16:00", default=time(10, 0)) == parsed
    assert parse_market_time(parsed, default=time(10, 0)) == parsed
    assert parse_local_task_times("16:00, 19:30") == ("16:00", "19:30")
    assert parse_local_task_times(("16:00", "19:30")) == ("16:00", "19:30")


def test_install_market_hours_refresh_task_defaults_to_dry_run(
    tmp_path,
    monkeypatch,
    capsys,
):
    paths = build_test_paths(tmp_path)

    def fail_install(commands):
        raise AssertionError("dry-run scheduler helper should not call schtasks")

    monkeypatch.setattr("golden_vector.cli.install_windows_task_scheduler_commands", fail_install)

    exit_code = run_install_market_hours_refresh_task(
        paths,
        task_name="Golden Vector Test Refresh",
        local_times=("16:00",),
        apply=False,
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "schtasks" in output
    assert "market-hours-refresh" in output
    assert "Dry run only" in output
