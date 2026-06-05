from datetime import datetime, timezone

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.data_models import FetchStatusRecord, QaCheckResult
from golden_vector.ingestion.foundation import execute_foundation_pipeline
from golden_vector.ingestion.registry import (
    EquityFetchTarget,
    FoundationRegistry,
    GoldFetchTarget,
    MarketSnapshotTarget,
)
from golden_vector.qa.normalization_quality import NormalizationQaReport
from golden_vector.qa.raw_quality import RawQaReport
from tests.helpers import build_test_paths


def _fetch_status(dataset: str, entity: str, symbol: str) -> FetchStatusRecord:
    now = datetime.now(timezone.utc)
    return FetchStatusRecord(
        dataset=dataset,
        entity=entity,
        source_symbol=symbol,
        status="PASS",
        row_count=1,
        started_at_utc=now,
        completed_at_utc=now,
    )


def _registry() -> FoundationRegistry:
    return FoundationRegistry(
        equity_targets=[EquityFetchTarget(ticker="NEM", exchange="NYSE", currency="USD", yahoo_symbol="NEM")],
        fx_targets=[],
        gold_target=GoldFetchTarget(yahoo_symbol="GC=F"),
        market_snapshot_targets=[MarketSnapshotTarget(ticker="NEM", currency="USD", yahoo_symbol="NEM")],
    )


def test_foundation_pipeline_skips_normalization_when_raw_qa_fails(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(paths=paths, command="foundation", parameters={}, config_hash="hash")
    registry = _registry()

    monkeypatch.setattr("golden_vector.ingestion.foundation.build_foundation_registry", lambda _: registry)
    monkeypatch.setattr("golden_vector.ingestion.foundation.YahooClient", lambda **_: object())
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_equity_histories",
        lambda client, targets: (
            {"NEM": pd.DataFrame([{"ticker": "NEM", "date": "2026-01-30"}])},
            [_fetch_status("equities", "NEM", "NEM")],
        ),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_fx_histories",
        lambda client, targets: ({}, []),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_gold_history",
        lambda client, target: (pd.DataFrame([{"date": "2026-01-30"}]), _fetch_status("gold", "GC=F", "GC=F")),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_market_snapshots",
        lambda client, targets, source_run_id: (
            pd.DataFrame([{"ticker": "NEM", "snapshot_date": "2026-02-01"}]),
            [_fetch_status("market_snapshots", "NEM", "NEM")],
        ),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.evaluate_raw_quality",
        lambda **kwargs: RawQaReport(
            overall_status="FAIL",
            results=[
                QaCheckResult(
                    check_name="raw_gate",
                    status="FAIL",
                    dataset="foundation",
                    entity="all",
                    message="raw qa failed",
                )
            ],
        ),
    )

    persisted = {"foundation": 0, "normalization": 0}
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.persist_foundation_outputs",
        lambda **kwargs: persisted.__setitem__("foundation", persisted["foundation"] + 1),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.persist_normalization_outputs",
        lambda **kwargs: persisted.__setitem__("normalization", persisted["normalization"] + 1),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.normalize_equity_histories_to_usd",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Normalization should not run after raw FAIL.")),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.normalize_market_snapshots_to_usd",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Normalization should not run after raw FAIL.")),
    )

    result = execute_foundation_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
    )

    assert result.overall_status == "FAIL"
    assert result.normalization_qa_report is None
    assert result.summary["normalization_executed"] is False
    assert persisted["foundation"] == 1
    assert persisted["normalization"] == 0


def test_foundation_pipeline_runs_normalization_and_combines_statuses(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(ProjectPaths.discover()).app
    run_context = RunContext.start(paths=paths, command="foundation", parameters={}, config_hash="hash")
    registry = _registry()

    monkeypatch.setattr("golden_vector.ingestion.foundation.build_foundation_registry", lambda _: registry)
    monkeypatch.setattr("golden_vector.ingestion.foundation.YahooClient", lambda **_: object())
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_equity_histories",
        lambda client, targets: (
            {"NEM": pd.DataFrame([{"ticker": "NEM", "date": "2026-01-30"}])},
            [_fetch_status("equities", "NEM", "NEM")],
        ),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_fx_histories",
        lambda client, targets: ({}, []),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_gold_history",
        lambda client, target: (pd.DataFrame([{"date": "2026-01-30"}]), _fetch_status("gold", "GC=F", "GC=F")),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.fetch_market_snapshots",
        lambda client, targets, source_run_id: (
            pd.DataFrame([{"ticker": "NEM", "snapshot_date": "2026-02-01"}]),
            [_fetch_status("market_snapshots", "NEM", "NEM")],
        ),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.evaluate_raw_quality",
        lambda **kwargs: RawQaReport(
            overall_status="PASS",
            results=[
                QaCheckResult(
                    check_name="raw_gate",
                    status="PASS",
                    dataset="foundation",
                    entity="all",
                    message="raw qa passed",
                )
            ],
        ),
    )

    normalized_equities = {
        "NEM": pd.DataFrame(
            [{"ticker": "NEM", "date": "2026-01-30", "normalization_status": "OK"}]
        )
    }
    normalized_snapshots = pd.DataFrame(
        [{"ticker": "NEM", "snapshot_date": "2026-02-01", "normalization_status": "OK"}]
    )

    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.normalize_equity_histories_to_usd",
        lambda **kwargs: normalized_equities,
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.normalize_market_snapshots_to_usd",
        lambda **kwargs: normalized_snapshots,
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.evaluate_normalization_quality",
        lambda **kwargs: NormalizationQaReport(
            overall_status="WARN",
            results=[
                QaCheckResult(
                    check_name="normalization_gate",
                    status="WARN",
                    dataset="normalization",
                    entity="all",
                    message="normalization warning",
                )
            ],
        ),
    )

    persisted = {"foundation": 0, "normalization": 0}
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.persist_foundation_outputs",
        lambda **kwargs: persisted.__setitem__("foundation", persisted["foundation"] + 1),
    )
    monkeypatch.setattr(
        "golden_vector.ingestion.foundation.persist_normalization_outputs",
        lambda **kwargs: persisted.__setitem__("normalization", persisted["normalization"] + 1),
    )

    result = execute_foundation_pipeline(
        paths=paths,
        app_config=app_config,
        run_context=run_context,
    )

    assert result.overall_status == "WARN"
    assert result.normalization_qa_report is not None
    assert result.summary["normalization_executed"] is True
    assert result.summary["normalization_overall_status"] == "WARN"
    assert result.summary["normalized_equity_row_count"] == 1
    assert result.summary["normalized_market_snapshot_row_count"] == 1
    assert persisted["foundation"] == 1
    assert persisted["normalization"] == 1
