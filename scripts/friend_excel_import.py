"""Shared helpers for ingesting data from the friend's Tool B workbook.

The friend maintains a canonical Excel screening workbook
(`Gold_Mining_Screening_v10226_EVEB.xlsx`) that uses ticker labels which
differ from our Yahoo-Finance-friendly universe in two cases. This module
holds the single source of truth for that mapping plus the workbook path,
so any one-off import script can rely on the same conventions.

Keeping this on the import side (not in production runtime) means the
runtime never needs to know the friend's labelling — only the scripts that
ingest his data.
"""

from __future__ import annotations

from pathlib import Path

# Tickers the friend's workbook uses on the left -> our universe.yaml ticker
# on the right. Anything not in this dict is assumed identical.
FRIEND_TICKER_MAP: dict[str, str] = {
    "ARMN": "ARIS.TO",  # Aris Mining: friend uses legacy NYSE short ticker
    "RMS": "RMS.AX",    # Ramelius Resources: friend uses bare GOOGLEFINANCE symbol
}


def map_friend_ticker(friend_ticker: str) -> str:
    """Return our universe ticker for a label from the friend's workbook."""
    return FRIEND_TICKER_MAP.get(friend_ticker, friend_ticker)


def default_workbook_path(repo_root: Path) -> Path:
    """Path to the canonical workbook copy living at the repo root."""
    return repo_root / "Gold_Mining_Screening_v10226_EVEB.xlsx"
