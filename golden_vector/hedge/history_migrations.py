"""One-off durable-history value corrections for option signal artifacts.

The realized-volatility bug fixed in ``ce2583a`` (stdev of raw USD price
LEVELS instead of pct returns) left ``iv_rv_ratio`` in the canonical
``option_signal_history.parquet`` about 100x too small. That file is the ONLY
copy of the accumulated series, so the values must be recomputed in place with
the corrected semantics rather than rebuilt from a refresh.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.features.options import _realized_vol
from golden_vector.hedge.option_signals import option_signal_history_path
from golden_vector.ingestion.persist_options import safe_options_file_name

BACKUP_FILE_NAME = "option_signal_history.pre_iv_rv_migration.parquet"
IV_RV_MIGRATION_VERSION = 1


class _MigrationPaths(Protocol):
    output_options_dir: Path
    intermediate_usd_equities_dir: Path
    benchmarks_dir: Path


def _price_frame(paths: _MigrationPaths, ticker: str) -> pd.DataFrame | None:
    """Load the ticker's price frame: normalized USD equities, else benchmarks.

    The BASIS column is not chosen here — ``features.options`` owns that single
    resolution order (including the ``*_local`` benchmark fallback for the
    US-listed USD ETFs stored in the benchmarks directory).
    """

    name = safe_options_file_name(ticker)
    equity_path = paths.intermediate_usd_equities_dir / f"{name}.parquet"
    benchmark_path = paths.benchmarks_dir / f"{name}.parquet"
    if equity_path.exists():
        frame = pd.read_parquet(equity_path)
    elif benchmark_path.exists():
        frame = pd.read_parquet(benchmark_path)
    else:
        return None
    if frame.empty or "date" not in frame.columns:
        return None
    return frame


def _realized_vol_as_of(
    frame: pd.DataFrame | None, *, as_of_date: str, window_days: int
) -> float | None:
    """Slice the price frame to rows dated <= as_of, then call PRODUCTION vol.

    There is exactly ONE realized-vol implementation
    (``features.options._realized_vol``); this function only bounds the input by
    date so no future price can leak into a historical row. Dates are compared
    as TIMESTAMPS on both sides — string comparison silently mis-orders mixed
    date formats (e.g. ``2026-1-5`` vs ``2026-01-05``).
    """

    if frame is None or frame.empty:
        return None
    as_of = pd.to_datetime(as_of_date, errors="coerce")
    if pd.isna(as_of):
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce")
    sliced = frame[dates.notna() & (dates <= as_of)]
    if sliced.empty:
        return None
    return _realized_vol(sliced, window_days=window_days)


def migrate_iv_rv_history(
    paths: _MigrationPaths, *, migration_run_id: str
) -> dict[str, Any]:
    """Recompute ``iv_rv_ratio`` in the canonical option signal history."""

    path = option_signal_history_path(paths)
    if not path.exists():
        raise FileNotFoundError(f"Option signal history is missing: {path}")
    frame = pd.read_parquet(path)

    before = pd.to_numeric(frame.get("iv_rv_ratio"), errors="coerce")

    frame_cache: dict[str, pd.DataFrame | None] = {}
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
            if ticker not in frame_cache:
                frame_cache[ticker] = _price_frame(paths, ticker)
            vol_cache[key] = _realized_vol_as_of(
                frame_cache[ticker], as_of_date=as_of_date, window_days=horizon
            )
        rv = vol_cache[key]
        if rv is None or rv == 0:
            new_values.append(None)
            continue
        new_values.append(float(atm_iv) / float(rv))

    after = pd.Series(new_values, index=frame.index, dtype="float64")

    # LOSS GUARD: this file is the ONLY copy of the accumulated series. A
    # recompute that ends with FEWER populated ratios than it started with is
    # data destruction (a missing/renamed price file, a delisted ticker), not a
    # correction — abort before anything is written so the live store and its
    # backup both stay exactly as they were.
    lost = before.notna() & after.isna()
    if int(after.notna().sum()) < int(before.notna().sum()):
        tickers = sorted({str(value) for value in frame.loc[lost, "ticker"]})
        raise ValueError(
            "Refusing to migrate iv_rv history: the recompute would wipe "
            f"{int(lost.sum())} previously populated iv_rv_ratio value(s) "
            f"({int(before.notna().sum())} -> {int(after.notna().sum())}). "
            f"Affected tickers: {', '.join(tickers) or 'unknown'}."
        )

    backup_path = path.parent / BACKUP_FILE_NAME
    if not backup_path.exists():
        write_parquet_atomic(frame, backup_path, index=False)

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
