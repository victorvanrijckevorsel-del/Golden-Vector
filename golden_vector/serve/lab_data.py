"""Read-only loader for persisted Lab artifacts.

Serve renders; the lab package computes. This module reads the dial-table
parquet + meta JSON and hands rows to the page. No arithmetic, no rank
decisions — the artifact carries `rank_in_bucket` and display labels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.lab.conditional_dial import (
    DIAL_META_FILENAME,
    DIAL_TABLE_FILENAME,
)
from golden_vector.lab.vintages import lab_dir


@dataclass(frozen=True)
class LabDialData:
    available: bool
    buckets: list[tuple[str, str]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def load_lab_dial_data(
    paths: ProjectPaths,
    *,
    bucket: str | None = None,
) -> LabDialData:
    table_path = lab_dir(paths) / DIAL_TABLE_FILENAME
    if not table_path.exists():
        return LabDialData(available=False)
    try:
        frame = pd.read_parquet(table_path)
    except Exception:
        # Optional research panel: a torn/corrupt artifact degrades to the
        # "not built yet" notice instead of a 500 on every request.
        return LabDialData(available=False)
    if frame.empty:
        return LabDialData(available=False)

    bucket_pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for record in frame[["bucket", "bucket_label"]].to_dict(orient="records"):
        key = str(record["bucket"])
        if key not in seen:
            seen.add(key)
            bucket_pairs.append((key, str(record["bucket_label"])))

    selected = bucket if bucket in seen else bucket_pairs[0][0]
    view = frame.loc[frame["bucket"] == selected]
    view = view.sort_values("rank_in_bucket")

    meta: dict[str, Any] = {}
    meta_path = lab_dir(paths) / DIAL_META_FILENAME
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}

    return LabDialData(
        available=True,
        buckets=bucket_pairs,
        rows=view.to_dict(orient="records"),
        meta=meta,
    )
