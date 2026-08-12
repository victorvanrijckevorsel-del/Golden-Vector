"""F1 point-in-time vintage recorder — "start the clock now".

Fundamentals, option signals, and hedge fields are NOT backtestable (one
fetch vintage, no release dates), so every week we fail to snapshot them is
training data lost forever. This module appends the current latest artifacts
into long-format, append-only vintage stores under ``data/lab/vintages/``.

PIT semantics: the dedupe key is (vintage_date, source, ticker, field) and
the FIRST recorded value wins — a later re-run on the same date never
rewrites what we knew. Run it after every refresh (or standalone via
``python -m golden_vector.lab.vintages``); re-running is a no-op.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    resolve_current_model_artifact_path,
    summarize_option_freshness,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.frames import select_finance_source_rows
from golden_vector.common.parquet import write_parquet_atomic

LOGGER = logging.getLogger(__name__)

# Option artifacts are only recorded when the manifest's freshness domain says
# OK. CARRIED_FORWARD/UNAVAILABLE (or no manifest at all) means the data on
# disk may be stale or schema-rejected — and first-write-wins dedupe would
# make a bad capture permanent. A skipped week is honest; a contaminated
# week is forever.
_OPTION_SOURCES = frozenset({"option_signal_summary", "option_trading_overview"})
# Lab's survivor-only methodology is intentionally Our View. Tool D now carries
# both finance sources in one artifact, so these destructive append-only inputs
# must be narrowed before they are melted into ticker-keyed vintage rows.
_TOOL_D_SOURCES = frozenset({"tool_d", "tool_d_spot"})

VINTAGE_COLUMNS = [
    "vintage_date",
    "recorded_at_utc",
    "source",
    "ticker",
    "field",
    "value_num",
    "value_text",
]
_DEDUPE_KEY = ["vintage_date", "source", "ticker", "field"]


def lab_dir(paths: ProjectPaths) -> Path:
    return paths.data_dir / "lab"


def vintages_dir(paths: ProjectPaths) -> Path:
    return lab_dir(paths) / "vintages"


@dataclass(frozen=True)
class VintageSourceResult:
    source: str
    rows_appended: int
    rows_skipped_existing: int


def _melt_snapshot(frame: pd.DataFrame, *, source: str, vintage_date: str, recorded_at_utc: str) -> pd.DataFrame:
    if "ticker" not in frame.columns:
        raise ValueError(f"Vintage source '{source}' has no ticker column.")
    rows: list[dict[str, object]] = []
    for record in frame.to_dict(orient="records"):
        ticker = str(record.get("ticker"))
        for field, value in record.items():
            if field == "ticker" or value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            value_num: float | None = None
            value_text: str | None = None
            if isinstance(value, bool):
                value_num = float(value)
            elif isinstance(value, (int, float)):
                value_num = float(value)
            else:
                try:
                    if pd.isna(value):
                        continue
                except (TypeError, ValueError):
                    pass  # non-scalar (list/array) — keep its text form
                value_text = str(value)
            rows.append(
                {
                    "vintage_date": vintage_date,
                    "recorded_at_utc": recorded_at_utc,
                    "source": source,
                    "ticker": ticker,
                    "field": field,
                    "value_num": value_num,
                    "value_text": value_text,
                }
            )
    return pd.DataFrame(rows, columns=VINTAGE_COLUMNS)


def _append_vintage(store_path: Path, new_rows: pd.DataFrame, *, source: str) -> VintageSourceResult:
    missing_key_columns = [column for column in _DEDUPE_KEY if column not in new_rows.columns]
    if missing_key_columns:
        raise ValueError(
            f"Vintage source '{source}' lacks dedupe columns: {missing_key_columns}."
        )
    new_keys = new_rows[_DEDUPE_KEY].astype(str).apply(tuple, axis=1)
    duplicate_mask = new_keys.duplicated(keep=False)
    if duplicate_mask.any():
        duplicate_key = new_keys.loc[duplicate_mask].iloc[0]
        raise ValueError(
            f"Vintage source '{source}' contains duplicate keys within one new batch "
            f"(e.g. {duplicate_key}); refusing an ambiguous first write."
        )
    if store_path.exists():
        existing = pd.read_parquet(store_path)
    else:
        existing = pd.DataFrame(columns=VINTAGE_COLUMNS)
    existing_keys = set(
        map(tuple, existing[_DEDUPE_KEY].astype(str).itertuples(index=False, name=None))
    )
    fresh_mask = ~new_keys.isin(existing_keys)
    fresh = new_rows.loc[fresh_mask]
    skipped = int((~fresh_mask).sum())
    if not fresh.empty:
        combined = pd.concat([existing, fresh], ignore_index=True)
        store_path.parent.mkdir(parents=True, exist_ok=True)
        write_parquet_atomic(combined, store_path)
    return VintageSourceResult(
        source=source,
        rows_appended=int(len(fresh)),
        rows_skipped_existing=skipped,
    )


def _vintage_sources(paths: ProjectPaths) -> dict[str, Path]:
    return {
        "tool_b": paths.latest_tool_b_snapshot_parquet_path,
        "tool_d": paths.latest_tool_d_snapshot_parquet_path,
        "tool_d_spot": paths.latest_tool_d_spot_snapshot_parquet_path,
        "option_signal_summary": paths.output_options_dir / "option_signal_summary_latest.parquet",
        "option_trading_overview": paths.output_options_dir / "option_trading_overview_latest.parquet",
    }


def record_vintages(paths: ProjectPaths, *, now: datetime | None = None) -> list[VintageSourceResult]:
    """Snapshot the current manifest-resolved artifacts into the vintage stores.

    Sources resolve through the model-state manifest (never a bare mutable
    alias when a manifest exists), option sources require freshness OK, and
    each source is isolated — one corrupt artifact must not cost the week's
    snapshot of the others.
    """

    moment = now or datetime.now(timezone.utc)
    vintage_date = moment.date().isoformat()
    recorded_at_utc = moment.isoformat()

    # Lost-update guard: the stores are read-modify-rewrite, so a manual
    # recorder racing the refresh-end recorder can silently drop the other's
    # rows. Defer to a live refresh owned by another process.
    try:
        from golden_vector.serve.option_refresh import read_option_refresh_status

        lock = read_option_refresh_status(paths)
        if (
            lock.status == "running"
            and lock.process_id is not None
            and int(lock.process_id) != os.getpid()
        ):
            LOGGER.warning(
                "A refresh is running (job %s); skipping vintage recording — "
                "the refresh records vintages itself when it completes.",
                lock.job_id,
            )
            return []
    except Exception:  # pragma: no cover - lock readability is best-effort
        pass

    manifest = load_current_model_state_manifest(paths)
    option_freshness = summarize_option_freshness(manifest)
    option_data_ok = (
        option_freshness is not None and option_freshness.get("status") == "OK"
    )

    results: list[VintageSourceResult] = []
    for source, alias_path in _vintage_sources(paths).items():
        try:
            if source in _OPTION_SOURCES and not option_data_ok:
                status = (
                    option_freshness.get("status")
                    if option_freshness is not None
                    else "NO_MANIFEST"
                )
                LOGGER.warning(
                    "Vintage source %s skipped: option freshness is %s, not OK.",
                    source,
                    status,
                )
                continue
            artifact_path = resolve_current_model_artifact_path(
                paths, source, fallback_path=alias_path
            )
            if artifact_path is None or not artifact_path.exists():
                LOGGER.warning(
                    "Vintage source %s is not usable in the current model state — skipped.",
                    source,
                )
                continue
            frame = pd.read_parquet(artifact_path)
            if source in _TOOL_D_SOURCES:
                frame = select_finance_source_rows(
                    frame,
                    finance_source="our",
                    label=f"Lab vintage source {source}",
                )
            melted = _melt_snapshot(
                frame,
                source=source,
                vintage_date=vintage_date,
                recorded_at_utc=recorded_at_utc,
            )
            store_path = vintages_dir(paths) / f"{source}.parquet"
            result = _append_vintage(store_path, melted, source=source)
        except Exception as exc:
            LOGGER.warning("Vintage source %s failed: %s — continuing.", source, exc)
            continue
        results.append(result)
        LOGGER.info(
            "Vintage %s on %s: +%d rows (%d already recorded).",
            source,
            vintage_date,
            result.rows_appended,
            result.rows_skipped_existing,
        )
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    paths = ProjectPaths.discover()
    results = record_vintages(paths)
    total = sum(item.rows_appended for item in results)
    print(f"Recorded {total} new vintage rows across {len(results)} sources.")


if __name__ == "__main__":
    main()
