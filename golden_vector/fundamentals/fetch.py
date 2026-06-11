"""Fetch and map official fundamentals from Yahoo statements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import pandas as pd

from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext, utc_now_iso
from golden_vector.common.files import repo_relative
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.config_models import AppConfig, UniverseTicker
from golden_vector.contracts.fundamentals import (
    fetched_fundamentals_latest_path,
    fundamentals_fetch_manifest_run_stamped_path,
    raw_fundamentals_statements_latest_path,
)
from golden_vector.fundamentals.artifacts import write_fetched_fundamentals_artifact_pair
from golden_vector.fundamentals.mapper import map_raw_fundamentals_to_official
from golden_vector.fundamentals.raw_store import (
    RAW_FETCH_STATUS_EMPTY,
    RAW_FETCH_STATUS_FAIL,
    RAW_FETCH_STATUS_PASS,
    load_raw_fundamentals_statements,
    raw_statement_payload_to_frame,
    write_fundamentals_fetch_manifest,
    write_raw_fundamentals_artifact_pair,
)
from golden_vector.ingestion.collection_resilience import (
    fetch_dataset_outage_status,
    map_with_bounded_workers,
)
from golden_vector.ingestion.yahoo_client import YahooClient


@dataclass(frozen=True)
class FundamentalsFetchResult:
    source_run_id: str
    raw_row_count: int
    official_row_count: int
    ticker_statuses: tuple[dict[str, object], ...]
    manifest: dict[str, object]


def fetch_and_publish_fundamentals(
    *,
    paths: ProjectPaths,
    app_config: AppConfig,
    run_context: RunContext,
    yahoo_client: YahooClient,
    tickers: list[str] | None = None,
    publish_current: bool = True,
) -> FundamentalsFetchResult:
    """Fetch, store, map, and publish official fundamentals artifacts."""

    source_run_id = run_context.run_id
    fetched_at_utc = utc_now_iso()
    selected = _selected_universe_tickers(app_config, requested_tickers=tickers)
    timings: dict[str, object] = {}

    started_at = perf_counter()
    fetch_results = map_with_bounded_workers(
        selected,
        max_workers=app_config.market_data.yahoo_max_workers,
        func=lambda ticker_config: _fetch_one(
            ticker_config=ticker_config,
            yahoo_client=yahoo_client,
            fetched_at_utc=fetched_at_utc,
            source_run_id=source_run_id,
        ),
    )
    timings["fetch_seconds"] = round(perf_counter() - started_at, 3)

    raw_frame = (
        pd.concat([result[0] for result in fetch_results], ignore_index=True)
        if fetch_results
        else pd.DataFrame()
    )
    ticker_statuses = [result[1] for result in fetch_results]

    started_at = perf_counter()
    raw_write = write_raw_fundamentals_artifact_pair(
        paths=paths,
        frame=raw_frame,
        source_run_id=source_run_id,
        publish_latest_alias=False,
    )
    raw_run_path = Path(raw_write.run_path)
    run_context.record_artifact(raw_run_path)
    timings["raw_write_seconds"] = round(perf_counter() - started_at, 3)
    timings["raw_rows"] = raw_write.row_count

    started_at = perf_counter()
    persisted_raw = load_raw_fundamentals_statements(paths, source_run_id=source_run_id)
    official = map_raw_fundamentals_to_official(
        persisted_raw,
        fx_histories=load_statement_fx_histories(paths),
        source_run_id=source_run_id,
        max_statement_age_days=app_config.fundamentals.max_statement_age_days,
        ebitda_reconciliation_max_pct=(
            app_config.fundamentals.ebitda_reconciliation_max_pct
        ),
    )
    timings["map_seconds"] = round(perf_counter() - started_at, 3)
    timings["official_rows"] = int(len(official.index))

    publish_blocked_reason = _current_publish_blocked_reason(
        paths=paths,
        ticker_statuses=ticker_statuses,
        official=official,
    )
    publish_current_effective = publish_current and publish_blocked_reason is None
    if publish_blocked_reason is not None:
        timings["current_publish_blocked_reason"] = publish_blocked_reason
    raw_latest_path: Path | None = None
    if publish_current_effective:
        raw_latest_path = raw_fundamentals_statements_latest_path(paths)
        write_parquet_atomic(persisted_raw, raw_latest_path, index=False)
        run_context.record_artifact(raw_latest_path)

    started_at = perf_counter()
    official_write = write_fetched_fundamentals_artifact_pair(
        paths=paths,
        frame=official,
        source_run_id=source_run_id,
        publish_latest_alias=publish_current_effective,
    )
    official_run_path = Path(official_write.run_path)
    run_context.record_artifact(official_run_path)
    if official_write.latest_path is not None:
        run_context.record_artifact(Path(official_write.latest_path))
    timings["official_write_seconds"] = round(perf_counter() - started_at, 3)

    official_artifact: dict[str, object] = {
        "path": repo_relative(paths, official_run_path),
        "row_count": official_write.row_count,
    }
    if official_write.latest_path is not None:
        official_artifact["latest_alias_path"] = repo_relative(
            paths,
            Path(official_write.latest_path),
        )
    manifest = write_fundamentals_fetch_manifest(
        paths=paths,
        source_run_id=source_run_id,
        fetched_at_utc=fetched_at_utc,
        raw_run_path=raw_write.run_path,
        raw_latest_path=raw_latest_path.as_posix() if raw_latest_path is not None else None,
        ticker_statuses=ticker_statuses,
        timings=timings,
        official_artifact=official_artifact,
        publish_latest_alias=publish_current_effective,
    )
    run_context.record_artifact(
        fundamentals_fetch_manifest_run_stamped_path(paths, source_run_id)
    )
    if publish_current_effective:
        run_context.record_artifact(paths.latest_fundamentals_fetch_manifest_path)

    return FundamentalsFetchResult(
        source_run_id=source_run_id,
        raw_row_count=raw_write.row_count,
        official_row_count=official_write.row_count,
        ticker_statuses=tuple(ticker_statuses),
        manifest=manifest,
    )


def load_statement_fx_histories(paths: ProjectPaths) -> dict[str, pd.DataFrame]:
    """Load available FX histories keyed by statement currency."""

    histories: dict[str, pd.DataFrame] = {}
    if not paths.raw_fx_dir.exists():
        return histories
    for path in sorted(paths.raw_fx_dir.glob("*USD.parquet")):
        currency = path.stem.upper()
        if currency.endswith("USD") and len(currency) > 3:
            currency = currency[:-3]
        if not currency or currency == "USD":
            continue
        try:
            histories[currency] = pd.read_parquet(path)
        except Exception:
            continue
    return histories


def _current_publish_blocked_reason(
    *,
    paths: ProjectPaths,
    ticker_statuses: list[dict[str, object]],
    official: pd.DataFrame,
) -> str | None:
    """Return why the fetch must not advance current aliases, if any."""

    outage_status = fetch_dataset_outage_status(
        [
            SimpleNamespace(
                dataset="fundamentals",
                status=str(row.get("status") or "").upper(),
            )
            for row in ticker_statuses
        ],
        dataset="fundamentals",
    )
    if outage_status == "FULL_OUTAGE" or _has_no_successful_fetch(ticker_statuses):
        return "full_yahoo_outage"
    if official.empty and fetched_fundamentals_latest_path(paths).exists():
        return "empty_official_with_prior_current"
    return None


def _has_no_successful_fetch(ticker_statuses: list[dict[str, object]]) -> bool:
    statuses = [str(row.get("status") or "").upper() for row in ticker_statuses]
    return bool(statuses) and all(status != RAW_FETCH_STATUS_PASS for status in statuses)


def _fetch_one(
    *,
    ticker_config: UniverseTicker,
    yahoo_client: YahooClient,
    fetched_at_utc: str,
    source_run_id: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    ticker = ticker_config.ticker
    try:
        payload = yahoo_client.fetch_financial_statements(ticker)
        frame = raw_statement_payload_to_frame(
            ticker=ticker,
            yahoo_symbol=ticker,
            payload=payload,
            fetched_at_utc=fetched_at_utc,
            source_run_id=source_run_id,
        )
    except Exception as exc:
        frame = raw_statement_payload_to_frame(
            ticker=ticker,
            yahoo_symbol=ticker,
            payload={},
            fetched_at_utc=fetched_at_utc,
            source_run_id=source_run_id,
            error_message=f"Yahoo statement fetch failed: {exc}",
        )
    status = _ticker_status(frame)
    return frame, {
        "ticker": ticker,
        "yahoo_symbol": ticker,
        "status": status,
        "raw_row_count": int(len(frame.index)),
        "message": _ticker_message(frame),
    }


def _selected_universe_tickers(
    app_config: AppConfig,
    *,
    requested_tickers: list[str] | None,
) -> list[UniverseTicker]:
    requested = {
        ticker.strip().upper()
        for ticker in requested_tickers or []
        if ticker.strip()
    }
    selected = [
        ticker
        for ticker in app_config.universe.tickers
        if ticker.active
        and ticker.tool_b_enabled
        and (not requested or ticker.ticker in requested)
    ]
    if requested:
        known = {ticker.ticker for ticker in selected}
        missing = sorted(requested - known)
        if missing:
            raise ValueError(
                "Unknown or inactive Tool B tickers for fetch-fundamentals: "
                + ", ".join(missing)
            )
    return selected


def _ticker_status(frame: pd.DataFrame) -> str:
    statuses = set(frame["fetch_status"].dropna().astype(str).str.upper())
    if RAW_FETCH_STATUS_PASS in statuses:
        return RAW_FETCH_STATUS_PASS
    if RAW_FETCH_STATUS_FAIL in statuses:
        return RAW_FETCH_STATUS_FAIL
    return RAW_FETCH_STATUS_EMPTY


def _ticker_message(frame: pd.DataFrame) -> str | None:
    if "error_message" not in frame.columns:
        return None
    values = frame["error_message"].dropna().astype(str).str.strip()
    values = values[values != ""]
    return None if values.empty else str(values.iloc[0])
