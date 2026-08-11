"""One-off durable-history value corrections for option signal artifacts.

The realized-volatility bug fixed in ``ce2583a`` (stdev of raw USD price
LEVELS instead of pct returns) left ``iv_rv_ratio`` in the canonical
``option_signal_history.parquet`` about 100x too small. That file is the ONLY
copy of the accumulated series, so the values must be recomputed in place with
the corrected semantics rather than rebuilt from a refresh.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.features.options_chain import CALENDAR_DAYS_PER_YEAR
from golden_vector.hedge.option_signals import option_signal_history_path
from golden_vector.ingestion.persist_options import safe_options_file_name

TRADING_DAYS_PER_YEAR = 252
BACKUP_FILE_NAME = "option_signal_history.pre_iv_rv_migration.parquet"
IV_RV_MIGRATION_VERSION = 1


class _MigrationPaths(Protocol):
    output_options_dir: Path
    intermediate_usd_equities_dir: Path
    benchmarks_dir: Path


def _price_returns(paths: _MigrationPaths, ticker: str) -> pd.Series | None:
    """Return the daily pct-return series indexed by ISO date string."""

    name = safe_options_file_name(ticker)
    equity_path = paths.intermediate_usd_equities_dir / f"{name}.parquet"
    benchmark_path = paths.benchmarks_dir / f"{name}.parquet"
    if equity_path.exists():
        frame = pd.read_parquet(equity_path)
        basis_columns = ("return_basis_usd", "adj_close_usd")
    elif benchmark_path.exists():
        # GDX/GDXJ are US-listed USD ETFs stored with *_local columns only.
        frame = pd.read_parquet(benchmark_path)
        basis_columns = ("adj_close_local", "close_local")
    else:
        return None
    if frame.empty or "date" not in frame.columns:
        return None
    basis = next((col for col in basis_columns if col in frame.columns), None)
    if basis is None:
        return None
    prices = pd.DataFrame(
        {
            "date": frame["date"].astype(str),
            "price": pd.to_numeric(frame[basis], errors="coerce"),
        }
    )
    prices = (
        prices.sort_values("date", kind="mergesort")
        .drop_duplicates(subset="date", keep="last")
        .set_index("date")["price"]
    )
    returns = prices.pct_change(fill_method=None).dropna()
    return returns


def _realized_vol_as_of(
    returns: pd.Series | None, *, as_of_date: str, window_days: int
) -> float | None:
    """Mirror ``features.options._realized_vol`` using prices dated <= as_of."""

    if returns is None or returns.empty:
        return None
    window = returns[returns.index <= as_of_date]
    trading_rows = max(
        2, int(round(window_days * TRADING_DAYS_PER_YEAR / CALENDAR_DAYS_PER_YEAR))
    )
    window = window.tail(trading_rows)
    if len(window.index) < max(2, int(trading_rows * 0.8)):
        return None
    return float(window.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))


def migrate_iv_rv_history(
    paths: _MigrationPaths, *, migration_run_id: str
) -> dict[str, Any]:
    """Recompute ``iv_rv_ratio`` in the canonical option signal history."""

    path = option_signal_history_path(paths)
    if not path.exists():
        raise FileNotFoundError(f"Option signal history is missing: {path}")
    frame = pd.read_parquet(path)

    backup_path = path.parent / BACKUP_FILE_NAME
    if not backup_path.exists():
        write_parquet_atomic(frame, backup_path, index=False)

    before = pd.to_numeric(frame.get("iv_rv_ratio"), errors="coerce")

    returns_cache: dict[str, pd.Series | None] = {}
    vol_cache: dict[tuple[str, str, int], float | None] = {}
    new_values: list[float | None] = []
    for _, row in frame.iterrows():
        ticker = str(row["ticker"])
        as_of_date = str(row["as_of_date"])
        try:
            horizon = int(row["signal_horizon_days"])
        except (TypeError, ValueError):
            new_values.append(None)
            continue
        atm_iv = pd.to_numeric(pd.Series([row.get("atm_iv")]), errors="coerce").iloc[0]
        if pd.isna(atm_iv):
            new_values.append(None)
            continue
        key = (ticker, as_of_date, horizon)
        if key not in vol_cache:
            if ticker not in returns_cache:
                returns_cache[ticker] = _price_returns(paths, ticker)
            vol_cache[key] = _realized_vol_as_of(
                returns_cache[ticker], as_of_date=as_of_date, window_days=horizon
            )
        rv = vol_cache[key]
        if rv is None or rv == 0:
            new_values.append(None)
            continue
        new_values.append(float(atm_iv) / float(rv))

    after = pd.Series(new_values, index=frame.index, dtype="float64")
    frame["iv_rv_ratio"] = after
    frame["iv_rv_migration_version"] = IV_RV_MIGRATION_VERSION
    frame["iv_rv_migrated_run_id"] = str(migration_run_id)

    path.parent.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(frame, path, index=False)

    examples = [
        {
            "ticker": str(frame.iloc[i]["ticker"]),
            "as_of_date": str(frame.iloc[i]["as_of_date"]),
            "signal_horizon_days": int(frame.iloc[i]["signal_horizon_days"]),
            "before": None if pd.isna(before.iloc[i]) else float(before.iloc[i]),
            "after": None if pd.isna(after.iloc[i]) else float(after.iloc[i]),
        }
        for i in range(min(3, len(frame.index)))
    ]
    return {
        "rows": int(len(frame.index)),
        "non_null_before": int(before.notna().sum()),
        "non_null_after": int(after.notna().sum()),
        "median_before": None if before.dropna().empty else float(before.median()),
        "median_after": None if after.dropna().empty else float(after.median()),
        "examples": examples,
    }
