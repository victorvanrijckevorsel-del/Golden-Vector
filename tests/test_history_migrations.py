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
from golden_vector.features.options import _realized_vol
from golden_vector.hedge.option_signals import option_signal_history_path
from tests.helpers import build_test_paths

HORIZON = 3  # trading_rows == 2, so 2 returns are enough (hand-computable)


def _write_history(paths, rows: list[dict]) -> Path:
    path = option_signal_history_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return path


def _history_row(
    ticker: str,
    *,
    as_of_date: str,
    atm_iv: float | None,
    iv_rv_ratio: float | None = 0.0047,
) -> dict:
    return {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "quote_snapshot_run_id": f"run-{ticker}",
        "benchmark_symbol": "GDX",
        "signal_horizon_days": HORIZON,
        "skew_residual": 0.01,
        "atm_iv": atm_iv,
        "iv_rv_ratio": iv_rv_ratio,
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
        _history_row("BBB", as_of_date="2026-01-05", atm_iv=None, iv_rv_ratio=None),
        _history_row("AAA", as_of_date="2026-01-02", atm_iv=0.4, iv_rv_ratio=None),
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
    _write_history(
        paths,
        [_history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5, iv_rv_ratio=None)],
    )
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
            # Only one return exists on/before 2026-01-02, so this row has no
            # computable ratio -- and therefore no prior value to lose.
            _history_row("AAA", as_of_date="2026-01-02", atm_iv=0.4, iv_rv_ratio=None),
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
    assert backup_first["iv_rv_ratio"].iloc[0] == 0.0047
    assert pd.isna(backup_first["iv_rv_ratio"].iloc[1])


def _write_benchmark_prices(paths, ticker: str, dates: list[str], prices: list[float]) -> None:
    """Benchmark ETFs (GDX/GDXJ) are stored with *_local columns only."""

    paths.benchmarks_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"date": dates, "adj_close_local": prices}).to_parquet(
        paths.benchmarks_dir / f"{ticker}.parquet", index=False
    )


def test_migration_matches_production_realized_vol_on_the_presliced_frame(tmp_path):
    """ONE implementation: the migration path == features.options._realized_vol."""

    paths = build_test_paths(tmp_path)
    _write_history(paths, [_history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5)])
    dates = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06"]
    prices = [100.0, 110.0, 115.5, 57.75]
    _write_prices(paths, "AAA", dates, prices)

    migrate_iv_rv_history(paths, migration_run_id="mig-1")
    migrated = pd.read_parquet(option_signal_history_path(paths)).loc[0, "iv_rv_ratio"]

    presliced = pd.DataFrame({"date": dates[:3], "return_basis_usd": prices[:3]})
    expected = 0.5 / _realized_vol(presliced, window_days=HORIZON)
    assert migrated == pytest.approx(expected, rel=0, abs=0)


def test_benchmark_local_only_prices_resolve_through_the_shared_basis(tmp_path):
    """GDX/GDXJ carry *_local columns only; production must still emit a value."""

    paths = build_test_paths(tmp_path)
    _write_history(paths, [_history_row("GDX", as_of_date="2026-01-05", atm_iv=0.5)])
    dates = ["2026-01-01", "2026-01-02", "2026-01-05"]
    prices = [100.0, 110.0, 115.5]
    _write_benchmark_prices(paths, "GDX", dates, prices)

    migrate_iv_rv_history(paths, migration_run_id="mig-1")

    frame = pd.read_parquet(option_signal_history_path(paths))
    assert frame.loc[0, "iv_rv_ratio"] == pytest.approx(
        _expected(0.5, [0.1, 0.05]), rel=1e-6
    )
    # And the SAME frame run through the production feature path agrees.
    assert _realized_vol(
        pd.DataFrame({"date": dates, "adj_close_local": prices}), window_days=HORIZON
    ) == pytest.approx(0.5 / frame.loc[0, "iv_rv_ratio"], rel=1e-9)


def test_missing_price_file_aborts_instead_of_wiping_populated_ratios(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_history(
        paths,
        [
            _history_row("AAA", as_of_date="2026-01-05", atm_iv=0.5),
            _history_row("GONE", as_of_date="2026-01-05", atm_iv=0.5),
        ],
    )
    _write_prices(
        paths, "AAA", ["2026-01-01", "2026-01-02", "2026-01-05"], [100.0, 110.0, 115.5]
    )

    with pytest.raises(ValueError, match="GONE"):
        migrate_iv_rv_history(paths, migration_run_id="mig-1")

    # NOTHING was written: the live store keeps its original values and no
    # backup was created either.
    frame = pd.read_parquet(option_signal_history_path(paths))
    assert frame["iv_rv_ratio"].tolist() == [0.0047, 0.0047]
    assert not (paths.output_options_dir / BACKUP_FILE_NAME).exists()
