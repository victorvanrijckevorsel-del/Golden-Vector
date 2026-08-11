"""Tests for the one-time iv_rv_ratio history value migration."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from golden_vector.hedge.history_migrations import (
    BACKUP_FILE_NAME,
    migrate_iv_rv_history,
)
from golden_vector.hedge.option_signals import option_signal_history_path
from tests.helpers import build_test_paths

HORIZON = 3  # trading_rows == 2, so 2 returns are enough (hand-computable)


def _write_history(paths, rows: list[dict]) -> Path:
    path = option_signal_history_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _history_row(ticker: str, *, as_of_date: str, atm_iv: float | None) -> dict:
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "quote_snapshot_run_id": f"run-{ticker}",
        "benchmark_symbol": "GDX",
        "signal_horizon_days": HORIZON,
        "skew_residual": 0.01,
        "atm_iv": atm_iv,
        "iv_rv_ratio": 0.0047,
    }


def _write_prices(paths, ticker: str, dates: list[str], prices: list[float]) -> None:
    paths.intermediate_usd_equities_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": dates, "return_basis_usd": prices}).to_parquet(
        paths.intermediate_usd_equities_dir / f"{ticker}.parquet", index=False
    )


def _expected(atm_iv: float, returns: list[float]) -> float:
    series = pd.Series(returns)
    rv = float(series.std(ddof=1) * math.sqrt(252))
    return atm_iv / rv


def test_corrected_value_matches_hand_computation(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_history(paths, [_history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5)])
    _write_prices(
        paths,
        "AAA",
        ["2026-01-01", "2026-01-02", "2026-01-05"],
        [100.0, 110.0, 115.5],
    )

    stats = migrate_iv_rv_history(paths, migration_run_id="mig-1")

    frame = pd.read_parquet(option_signal_history_path(paths))
    assert stats["rows"] == 1
    assert frame.loc[0, "iv_rv_ratio"] == pytest.approx(
        _expected(0.5, [0.1, 0.05]), rel=1e-6
    )
    assert frame.loc[0, "iv_rv_migration_version"] == 1
    assert frame.loc[0, "iv_rv_migrated_run_id"] == "mig-1"
    assert (paths.output_options_dir / BACKUP_FILE_NAME).exists()


def test_future_prices_do_not_leak_into_the_value(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_history(paths, [_history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5)])
    # The 2026-01-06 row is AFTER the as-of date: including it would replace the
    # 0.05 return with a -0.5 return and change the answer completely.
    _write_prices(
        paths,
        "AAA",
        ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"],
        [100.0, 110.0, 115.5, 57.75],
    )

    migrate_iv_rv_history(paths, migration_run_id="mig-1")

    frame = pd.read_parquet(option_signal_history_path(paths))
    assert frame.loc[0, "iv_rv_ratio"] == pytest.approx(
        _expected(0.5, [0.1, 0.05]), rel=1e-6
    )


def test_rows_and_keys_are_preserved(tmp_path):
    paths = build_test_paths(tmp_path)
    rows = [
        _history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5),
        _history_row("BBB", as_of_date="2026-01-05", atm_iv=None),
        _history_row("AAA", as_of_date="2026-01-02", atm_iv=0.4),
    ]
    original = pd.DataFrame(rows)
    _write_history(paths, rows)
    _write_prices(
        paths,
        "AAA",
        ["2026-01-01", "2026-01-02", "2026-01-05"],
        [100.0, 110.0, 115.5],
    )

    migrate_iv_rv_history(paths, migration_run_id="mig-1")

    frame = pd.read_parquet(option_signal_history_path(paths))
    assert len(frame.index) == len(original.index)
    key_columns = [
        "ticker",
        "as_of_date",
        "signal_horizon_days",
        "benchmark_symbol",
        "quote_snapshot_run_id",
    ]
    pd.testing.assert_frame_equal(frame[key_columns], original[key_columns])
    # Null atm_iv -> None, and no price file for BBB either.
    assert pd.isna(frame.loc[1, "iv_rv_ratio"])


def test_insufficient_history_yields_none(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_history(paths, [_history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5)])
    _write_prices(paths, "AAA", ["2026-01-01", "2026-01-02"], [100.0, 110.0])

    stats = migrate_iv_rv_history(paths, migration_run_id="mig-1")

    frame = pd.read_parquet(option_signal_history_path(paths))
    assert pd.isna(frame.loc[0, "iv_rv_ratio"])
    assert stats["non_null_after"] == 0


def test_migration_is_idempotent(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_history(
        paths,
        [
            _history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5),
            _history_row("AAA", as_of_date="2026-01-02", atm_iv=0.4),
        ],
    )
    _write_prices(
        paths,
        "AAA",
        ["2026-01-01", "2026-01-02", "2026-01-05"],
        [100.0, 110.0, 115.5],
    )

    first_stats = migrate_iv_rv_history(paths, migration_run_id="mig-1")
    first = pd.read_parquet(option_signal_history_path(paths))
    backup_first = pd.read_parquet(paths.output_options_dir / BACKUP_FILE_NAME)

    second_stats = migrate_iv_rv_history(paths, migration_run_id="mig-1")
    second = pd.read_parquet(option_signal_history_path(paths))
    backup_second = pd.read_parquet(paths.output_options_dir / BACKUP_FILE_NAME)

    pd.testing.assert_frame_equal(first, second)
    assert first_stats["median_after"] == second_stats["median_after"]
    # The backup keeps the ORIGINAL (pre-migration) values, never overwritten.
    pd.testing.assert_frame_equal(backup_first, backup_second)
    assert backup_first["iv_rv_ratio"].tolist() == [0.0047, 0.0047]
