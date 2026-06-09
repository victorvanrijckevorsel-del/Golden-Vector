"""Foundation pipeline orchestration."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from golden_vector.common.status import combine_statuses
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import AppConfig
from golden_vector.contracts.data_models import FetchStatusRecord
from golden_vector.ingestion.collection_resilience import (
    failed_fetch_entities,
    retry_policy_from_config,
    summarize_fetch_statuses,
)
from golden_vector.ingestion.fetch_equities import fetch_equity_histories
from golden_vector.ingestion.fetch_fx import fetch_fx_histories
from golden_vector.ingestion.fetch_gold import fetch_gold_history
from golden_vector.ingestion.fetch_market_snapshot import fetch_market_snapshots
from golden_vector.ingestion.persist import (
    persist_foundation_outputs,
    persist_normalization_outputs,
)
from golden_vector.ingestion.registry import FoundationRegistry, build_foundation_registry
from golden_vector.ingestion.yahoo_client import YahooClient
from golden_vector.normalize.market_snapshot import normalize_market_snapshots_to_usd
from golden_vector.normalize.prices_usd import normalize_equity_histories_to_usd
from golden_vector.qa.normalization_quality import (
    NormalizationQaReport,
    evaluate_normalization_quality,
)
from golden_vector.qa.raw_quality import RawQaReport, evaluate_raw_quality


@dataclass(frozen=True)
class FoundationExecutionResult:
    registry: FoundationRegistry
    raw_qa_report: RawQaReport
    normalization_qa_report: NormalizationQaReport | None
    overall_status: str
    gold_history: pd.DataFrame
    normalized_equity_histories: dict[str, pd.DataFrame]
    normalized_market_snapshots: pd.DataFrame
    summary: dict[str, object]


def execute_foundation_pipeline(
    paths: ProjectPaths,
    app_config: AppConfig,
    run_context: RunContext,
    yahoo_client: YahooClient | None = None,
) -> FoundationExecutionResult:
    registry = build_foundation_registry(app_config.universe)
    client = yahoo_client or YahooClient(
        retry_policy=retry_policy_from_config(app_config.market_data)
    )

    equity_histories, equity_statuses = fetch_equity_histories(
        client,
        registry.equity_targets,
        max_workers=app_config.market_data.yahoo_max_workers,
    )
    fx_histories, fx_statuses = fetch_fx_histories(client, registry.fx_targets)
    gold_history, gold_status = fetch_gold_history(client, registry.gold_target)
    market_snapshots, snapshot_statuses = fetch_market_snapshots(
        client,
        registry.market_snapshot_targets,
        source_run_id=run_context.run_id,
        max_workers=app_config.market_data.yahoo_max_workers,
    )

    fetch_statuses: list[FetchStatusRecord] = [
        *equity_statuses,
        *fx_statuses,
        gold_status,
        *snapshot_statuses,
    ]

    raw_qa_report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=fetch_statuses,
    )

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=fetch_statuses,
        qa_results=raw_qa_report.results,
    )

    normalized_equity_histories: dict[str, pd.DataFrame] = {}
    normalized_market_snapshots = pd.DataFrame()
    normalization_qa_report: NormalizationQaReport | None = None
    normalization_executed = False

    if raw_qa_report.overall_status != "FAIL":
        normalization_executed = True
        normalized_equity_histories = normalize_equity_histories_to_usd(
            equity_histories=equity_histories,
            fx_histories=fx_histories,
            max_fx_staleness_days=app_config.qa.max_fx_staleness_days,
        )
        normalized_market_snapshots = normalize_market_snapshots_to_usd(
            market_snapshots=market_snapshots,
            fx_histories=fx_histories,
            max_fx_staleness_days=app_config.qa.max_fx_staleness_days,
        )
        normalization_qa_report = evaluate_normalization_quality(
            app_config=app_config,
            registry=registry,
            usd_equity_histories=normalized_equity_histories,
            normalized_market_snapshots=normalized_market_snapshots,
            failed_equity_tickers=failed_fetch_entities(
                fetch_statuses,
                dataset="equities",
            ),
        )
        persist_normalization_outputs(
            paths=paths,
            run_context=run_context,
            usd_equity_histories=normalized_equity_histories,
            normalized_market_snapshots=normalized_market_snapshots,
            qa_results=normalization_qa_report.results,
        )

    overall_status = combine_statuses(
        raw_qa_report.overall_status,
        normalization_qa_report.overall_status if normalization_qa_report else None,
    )
    normalization_summary = (
        _prefix_keys(
            normalization_qa_report.summary(),
            "normalization",
        )
        if normalization_qa_report is not None
        else {}
    )

    summary = {
        **registry.summary(),
        "raw_overall_status": raw_qa_report.overall_status,
        "normalization_overall_status": (
            normalization_qa_report.overall_status
            if normalization_qa_report is not None
            else "SKIPPED"
        ),
        "normalization_executed": normalization_executed,
        **_prefix_keys(raw_qa_report.summary(), "raw"),
        **normalization_summary,
        "equity_row_count": _sum_rows(equity_histories.values()),
        "fx_row_count": _sum_rows(fx_histories.values()),
        "gold_row_count": len(gold_history.index),
        "market_snapshot_row_count": len(market_snapshots.index),
        "normalized_equity_row_count": _sum_rows(normalized_equity_histories.values()),
        "normalized_market_snapshot_row_count": len(normalized_market_snapshots.index),
        "collection_stats": summarize_fetch_statuses(fetch_statuses),
    }
    return FoundationExecutionResult(
        registry=registry,
        raw_qa_report=raw_qa_report,
        normalization_qa_report=normalization_qa_report,
        overall_status=overall_status,
        gold_history=gold_history,
        normalized_equity_histories=normalized_equity_histories,
        normalized_market_snapshots=normalized_market_snapshots,
        summary=summary,
    )


def _sum_rows(frames: object) -> int:
    return sum(len(frame.index) for frame in frames if isinstance(frame, pd.DataFrame))


def _prefix_keys(summary: dict[str, object], prefix: str) -> dict[str, object]:
    return {
        f"{prefix}_{key}": value
        for key, value in summary.items()
        if key != "overall_status"
    }
