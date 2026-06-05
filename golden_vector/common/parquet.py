"""Shared Parquet read helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_optional_parquet(path: Path | None) -> pd.DataFrame:
    """Best-effort Parquet reader for optional local artifacts."""

    if path is None or not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()
