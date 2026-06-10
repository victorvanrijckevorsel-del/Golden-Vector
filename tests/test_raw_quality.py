from datetime import datetime, timezone

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.contracts.data_models import FetchStatusRecord, QaCheckResult
from golden_vector.ingestion import registry as registry_module
from golden_vector.ingestion.registry import FoundationRegistry, build_foundation_registry
from golden_vector.qa.raw_quality import evaluate_raw_quality


def _status(dataset: str, entity: str, source_symbol: str, status: str, row_count: int) -> FetchStatusRecord:
    now = datetime.now(timezone.utc)
    return FetchStatusRecord(
        dataset=dataset,
        entity=entity,
        source_symbol=source_symbol,
        status=status,
        row_count=row_count,
        started_at_utc=now,
        completed_at_utc=now,
        message=None,
    )


def _load_test_app_config(**qa_updates):
    loaded = load_app_config(ProjectPaths.discover())
    qa_config = loaded.app.qa.model_copy(
        update={
            "minimum_equity_history_days": 1,
            "minimum_fx_history_days": 1,
            "minimum_gold_history_days": 1,
            **qa_updates,
        }
    )
    return loaded.app.model_copy(update={"qa": qa_config})


def _build_healthy_inputs(registry: FoundationRegistry):
    equity_histories = {
        target.ticker: pd.DataFrame(
            [
                {
                    "ticker": target.ticker,
                    "date": "2026-01-01",
                }
            ]
        )
        for target in registry.equity_targets
    }
    fx_histories = {
        target.base_currency: pd.DataFrame(
            [
                {
                    "base_currency": target.base_currency,
                    "date": "2026-01-01",
                }
            ]
        )
        for target in registry.fx_targets
    }
    gold_history = pd.DataFrame([{"date": "2026-01-01"}])
    market_snapshots = pd.DataFrame(
        [
            {
                "ticker": target.ticker,
                "snapshot_date": "2026-01-01",
                "share_price_local": 10.0,
                "shares_outstanding": 100.0,
            }
            for target in registry.market_snapshot_targets
        ]
    )
    fetch_statuses = [
        *[
            _status("equities", target.ticker, target.yahoo_symbol, "PASS", 1)
            for target in registry.equity_targets
        ],
        *[
            _status("fx", target.base_currency, target.yahoo_symbol, "PASS", 1)
            for target in registry.fx_targets
        ],
        _status("gold", registry.gold_target.yahoo_symbol, registry.gold_target.yahoo_symbol, "PASS", 1),
        *[
            _status("market_snapshots", target.ticker, target.yahoo_symbol, "PASS", 1)
            for target in registry.market_snapshot_targets
        ],
    ]
    return equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses


def _find_result(
    results: list[QaCheckResult],
    *,
    check_name: str,
    dataset: str,
    entity: str,
) -> QaCheckResult:
    for result in results:
        if (
            result.check_name == check_name
            and result.dataset == dataset
            and result.entity == entity
        ):
            return result
    raise AssertionError(
        f"Missing QA result for check={check_name}, dataset={dataset}, entity={entity}"
    )


def test_raw_quality_warns_on_missing_market_snapshot():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, _, fetch_statuses = _build_healthy_inputs(
        registry
    )

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=pd.DataFrame(),
        fetch_statuses=fetch_statuses,
    )

    assert report.overall_status == "WARN"


def test_raw_quality_warns_but_continues_on_single_equity_fetch_failure():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses = (
        _build_healthy_inputs(registry)
    )
    failed_ticker = registry.equity_targets[0].ticker
    equity_histories[failed_ticker] = pd.DataFrame()
    fetch_statuses = [
        (
            _status("equities", failed_ticker, status.source_symbol, "FAIL", 0)
            if status.dataset == "equities" and status.entity == failed_ticker
            else status
        )
        for status in fetch_statuses
    ]

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=fetch_statuses,
    )

    outage = _find_result(
        report.results,
        check_name="vendor_outage_policy",
        dataset="market_data",
        entity="yahoo",
    )
    fetch_status = _find_result(
        report.results,
        check_name="fetch_status",
        dataset="equities",
        entity=failed_ticker,
    )
    history_status = _find_result(
        report.results,
        check_name="history_presence",
        dataset="equities",
        entity=failed_ticker,
    )

    assert report.overall_status == "WARN"
    assert outage.status == "WARN"
    assert fetch_status.status == "WARN"
    assert history_status.status == "WARN"
    assert "per-ticker" in outage.message


def test_raw_quality_fails_closed_when_all_equity_fetches_fail():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses = (
        _build_healthy_inputs(registry)
    )
    failed_statuses = [
        (
            _status(status.dataset, status.entity, status.source_symbol, "FAIL", 0)
            if status.dataset == "equities"
            else status
        )
        for status in fetch_statuses
    ]

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories={ticker: pd.DataFrame() for ticker in equity_histories},
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=failed_statuses,
    )

    outage = _find_result(
        report.results,
        check_name="vendor_outage_policy",
        dataset="market_data",
        entity="yahoo",
    )
    first_equity_status = _find_result(
        report.results,
        check_name="fetch_status",
        dataset="equities",
        entity=registry.equity_targets[0].ticker,
    )

    assert report.overall_status == "FAIL"
    assert outage.status == "FAIL"
    assert "equity outage" in outage.message
    assert first_equity_status.status == "FAIL"


def test_raw_quality_fails_closed_on_full_yahoo_outage():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses = (
        _build_healthy_inputs(registry)
    )
    failed_statuses = [
        _status(
            status.dataset,
            status.entity,
            status.source_symbol,
            "FAIL",
            0,
        )
        for status in fetch_statuses
    ]

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories={ticker: pd.DataFrame() for ticker in equity_histories},
        fx_histories={currency: pd.DataFrame() for currency in fx_histories},
        gold_history=pd.DataFrame(),
        market_snapshots=pd.DataFrame(),
        fetch_statuses=failed_statuses,
    )

    outage = _find_result(
        report.results,
        check_name="vendor_outage_policy",
        dataset="market_data",
        entity="yahoo",
    )

    assert report.overall_status == "FAIL"
    assert outage.status == "FAIL"
    assert "full outage" in outage.message


def test_raw_quality_fails_on_missing_gold_history():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, _, _, fetch_statuses = _build_healthy_inputs(registry)

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=pd.DataFrame(),
        market_snapshots=pd.DataFrame(),
        fetch_statuses=[
            status
            for status in fetch_statuses
            if not (status.dataset == "gold" and status.entity == registry.gold_target.yahoo_symbol)
        ]
        + [_status("gold", registry.gold_target.yahoo_symbol, registry.gold_target.yahoo_symbol, "FAIL", 0)],
    )

    assert report.overall_status == "FAIL"


def test_raw_quality_fails_on_missing_currency_map(monkeypatch):
    app_config = _load_test_app_config(block_on_missing_currency_map=True)
    monkeypatch.delitem(registry_module.FX_SYMBOL_BY_CURRENCY, "CAD", raising=False)
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses = (
        _build_healthy_inputs(registry)
    )

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=fetch_statuses,
    )

    currency_map_result = _find_result(
        report.results,
        check_name="currency_map_coverage",
        dataset="fx",
        entity="currency_map",
    )

    assert currency_map_result.status == "FAIL"
    assert "CAD" in currency_map_result.message
    assert report.overall_status == "FAIL"


def test_raw_quality_can_suppress_duplicate_warnings():
    app_config = _load_test_app_config(warn_on_duplicate_rows=False)
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses = (
        _build_healthy_inputs(registry)
    )
    first_ticker = registry.equity_targets[0].ticker
    equity_histories[first_ticker] = pd.DataFrame(
        [
            {"ticker": first_ticker, "date": "2026-01-01"},
            {"ticker": first_ticker, "date": "2026-01-01"},
        ]
    )

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=fetch_statuses,
    )

    duplicate_result = _find_result(
        report.results,
        check_name="duplicate_rows",
        dataset="equities",
        entity=first_ticker,
    )

    assert duplicate_result.status == "PASS"
    assert "disabled" in duplicate_result.message
    assert report.overall_status == "PASS"


def test_raw_quality_warns_on_incomplete_market_snapshot_fields():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    equity_histories, fx_histories, gold_history, market_snapshots, fetch_statuses = (
        _build_healthy_inputs(registry)
    )
    market_snapshots.loc[0, "shares_outstanding"] = None

    report = evaluate_raw_quality(
        app_config=app_config,
        registry=registry,
        equity_histories=equity_histories,
        fx_histories=fx_histories,
        gold_history=gold_history,
        market_snapshots=market_snapshots,
        fetch_statuses=fetch_statuses,
    )

    shares_result = _find_result(
        report.results,
        check_name="market_snapshot_shares_outstanding",
        dataset="market_snapshots",
        entity="tool-b",
    )

    assert shares_result.status == "WARN"
    assert registry.market_snapshot_targets[0].ticker in shares_result.message
    assert report.overall_status == "WARN"
