"""Read-only loader for the persisted Scorecard artifact.

Serve renders; the lab publisher computes. This reads the run-stamped
scorecard parquet + meta JSON and hands rows to the page. No arithmetic, no
verdict decisions — the artifact already carries the verdict, gates, and
diagnostics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.lab.scorecard import SCORECARD_META_FILENAME, SCORECARD_TABLE_FILENAME
from golden_vector.lab.vintages import lab_dir


@dataclass(frozen=True)
class ScorecardData:
    available: bool
    backtest_rows: list[dict[str, Any]] = field(default_factory=list)
    accruing_rows: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    error_status: str | None = None


def load_scorecard_data(paths: ProjectPaths) -> ScorecardData:
    table_path = lab_dir(paths) / SCORECARD_TABLE_FILENAME
    if not table_path.exists():
        return ScorecardData(available=False, error_status="MISSING")
    try:
        frame = pd.read_parquet(table_path)
    except Exception:
        return ScorecardData(available=False, error_status="CORRUPT")
    if frame.empty:
        return ScorecardData(available=False, error_status="MISSING")

    meta: dict[str, Any] = {}
    meta_path = lab_dir(paths) / SCORECARD_META_FILENAME
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}

    records = frame.to_dict(orient="records")
    backtest = [r for r in records if r.get("kind") == "backtest"]
    accruing = [r for r in records if r.get("kind") == "accruing"]
    return ScorecardData(
        available=True,
        backtest_rows=backtest,
        accruing_rows=accruing,
        meta=meta,
    )
