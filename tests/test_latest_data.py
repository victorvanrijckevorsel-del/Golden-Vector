from datetime import date, datetime, timezone

import pandas as pd

from golden_vector.app.latest_data import (
    load_latest_foundation_snapshot,
    write_latest_foundation_manifest,
)
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.config_models import (
    AppConfig,
    BenchmarksConfig,
    CandidateFinderConfig,
    HorizonsConfig,
    QaConfig,
    ScoringConfig,
    ScreeningParamsConfig,
    UniverseConfig,
    UniverseTicker,
)
from golden_vector.contracts.data_models import FetchStatusRecord, QaCheckResult
from golden_vector.ingestion.foundation import FoundationExecutionResult
from golden_vector.ingestion.persist import (
    persist_foundation_outputs,
    persist_normalization_outputs,
)
from golden_vector.ingestion.registry import (
    EquityFetchTarget,
    FoundationRegistry,
    GoldFetchTarget,
    MarketSnapshotTarget,
)
from golden_vector.qa.normalization_quality import NormalizationQaReport
from golden_vector.qa.raw_quality import RawQaReport
from tests.helpers import build_test_paths


def _app_config() -> AppConfig:
    return AppConfig(
        universe=UniverseConfig(
            tickers=[
                UniverseTicker(
                    ticker="NEM",
                    company="Newmont",
                    currency="USD",
                    active=True,
                    tool_a_enabled=True,
                    tool_b_enabled=True,
                    jurisdiction_tier=1,
                )
            ]
        ),
        benchmarks=BenchmarksConfig(
            benchmarks=[
                {"ticker": "GDX", "yahoo_symbol": "GDX"},
                {"ticker": "GDXJ", "yahoo_symbol": "GDXJ"},
            ]
        ),
        candidate_finder=CandidateFinderConfig(
            criteria=[
                {
                    "id": "down_beta",
                    "label": "Down-beta",
                    "source_field": "down_beta_core",
                    "group": "Sensitivity",
                    "default_direction": "high_good",
                    "unit": "beta",
                }
            ]
        ),
        horizons=HorizonsConfig(
            core_horizons=["5D", "1M"],
            custom_validation={"allowed_units": ["D", "M", "Y"], "min_value": 1, "max_value": 120},
        ),
        qa=QaConfig(),
        scoring=ScoringConfig(),
        screening_params=ScreeningParamsConfig(
            gold_price_scenarios=[4000.0],
            peer_benchmarks={
                "large": {
                    "pe_2026": 10.0,
                    "pe_2011_peak": 14.0,
                    "evebitda_2026": 7.0,
                    "evebitda_2011": 10.0,
                    "fcf_yield_2026": 0.10,
                    "fcf_yield_2011": 0.06,
                },
                "mid": {
                    "pe_2026": 9.0,
                    "pe_2011_peak": 13.0,
                    "evebitda_2026": 6.5,
                    "evebitda_2011": 9.5,
                    "fcf_yield_2026": 0.11,
                    "fcf_yield_2011": 0.065,
                },
                "small": {
                    "pe_2026": 8.0,
                    "pe_2011_peak": 12.0,
                    "evebitda_2026": 6.0,
                    "evebitda_2011": 9.0,
                    "fcf_yield_2026": 0.12,
                    "fcf_yield_2011": 0.07,
                },
                "micro": {
                    "pe_2026": 7.0,
                    "pe_2011_peak": 11.0,
                    "evebitda_2026": 5.5,
                    "evebitda_2011": 8.5,
                    "fcf_yield_2026": 0.13,
                    "fcf_yield_2011": 0.075,
                },
            },
        ),
    )


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


def _foundation_registry() -> FoundationRegistry:
    return FoundationRegistry(
        equity_targets=[EquityFetchTarget(ticker="NEM", exchange="NYSE", currency="USD", yahoo_symbol="NEM")],
        fx_targets=[],
        gold_target=GoldFetchTarget(yahoo_symbol="GC=F"),
        market_snapshot_targets=[MarketSnapshotTarget(ticker="NEM", currency="USD", yahoo_symbol="NEM")],
    )


def _foundation_result() -> FoundationExecutionResult:
    return FoundationExecutionResult(
        registry=_foundation_registry(),
        raw_qa_report=RawQaReport(
            overall_status="PASS",
            results=[
                QaCheckResult(
                    check_name="raw_gate",
                    status="PASS",
                    dataset="foundation",
                    entity="all",
                    message="ok",
                )
            ],
        ),
        normalization_qa_report=NormalizationQaReport(
            overall_status="PASS",
            results=[
                QaCheckResult(
                    check_name="normalization_gate",
                    status="PASS",
                    dataset="normalization",
                    entity="all",
                    message="ok",
                )
            ],
        ),
        overall_status="PASS",
        gold_history=pd.DataFrame(
            [{"date": date(2026, 2, 1), "gold_symbol": "GC=F", "adj_close_usd": 2800.0}]
        ),
        normalized_equity_histories={
            "NEM": pd.DataFrame(
                [{"ticker": "NEM", "date": date(2026, 2, 1), "return_basis_usd": 60.0}]
            )
        },
        normalized_market_snapshots=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "snapshot_date": date(2026, 2, 1),
                    "share_price_usd": 60.0,
                    "market_cap_usd": 48_000_000_000.0,
                    "shares_outstanding": 800_000_000.0,
                }
            ]
        ),
        summary={"foundation_marker": True},
    )


def test_persist_foundation_outputs_writes_latest_aliases(tmp_path):
    paths = build_test_paths(tmp_path)
    run_context = RunContext.start(paths=paths, command="update-data", parameters={}, config_hash="hash")

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories={"NEM": pd.DataFrame([{"ticker": "NEM", "date": date(2026, 2, 1)}])},
        fx_histories={},
        gold_history=pd.DataFrame([{"date": date(2026, 2, 1), "gold_symbol": "GC=F"}]),
        market_snapshots=pd.DataFrame([{"ticker": "NEM", "snapshot_date": date(2026, 2, 1)}]),
        fetch_statuses=[_fetch_status("equities", "NEM", "NEM")],
        qa_results=[
            QaCheckResult(
                check_name="raw_gate",
                status="PASS",
                dataset="foundation",
                entity="all",
                message="ok",
            )
        ],
    )

    assert paths.latest_raw_market_snapshots_path.exists()
    assert paths.latest_fetch_status_path.exists()
    assert paths.latest_raw_qa_results_path.exists()


def test_load_latest_foundation_snapshot_reads_manifest_backed_local_data(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _app_config()
    run_context = RunContext.start(paths=paths, command="update-data", parameters={}, config_hash="hash")
    foundation_result = _foundation_result()

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories={"NEM": pd.DataFrame([{"ticker": "NEM", "date": date(2026, 2, 1)}])},
        fx_histories={},
        gold_history=foundation_result.gold_history,
        market_snapshots=pd.DataFrame([{"ticker": "NEM", "snapshot_date": date(2026, 2, 1)}]),
        fetch_statuses=[_fetch_status("equities", "NEM", "NEM")],
        qa_results=foundation_result.raw_qa_report.results,
    )
    persist_normalization_outputs(
        paths=paths,
        run_context=run_context,
        usd_equity_histories=foundation_result.normalized_equity_histories,
        normalized_market_snapshots=foundation_result.normalized_market_snapshots,
        qa_results=foundation_result.normalization_qa_report.results,
    )
    write_latest_foundation_manifest(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        foundation_result=foundation_result,
    )

    loaded = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
    )

    assert loaded.refresh_run_id == run_context.run_id
    assert loaded.snapshot_as_of_date == "2026-02-01"
    assert loaded.raw_qa_summary["overall_status"] == "PASS"
    assert loaded.normalization_qa_summary["overall_status"] == "PASS"
    assert list(loaded.normalized_equity_histories.keys()) == ["NEM"]
    assert len(loaded.normalized_market_snapshots.index) == 1


def test_load_latest_foundation_snapshot_uses_immutable_run_snapshot_paths(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _app_config()
    run_context = RunContext.start(paths=paths, command="update-data", parameters={}, config_hash="hash")
    foundation_result = _foundation_result()

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories={"NEM": pd.DataFrame([{"ticker": "NEM", "date": date(2026, 2, 1)}])},
        fx_histories={},
        gold_history=foundation_result.gold_history,
        market_snapshots=pd.DataFrame([{"ticker": "NEM", "snapshot_date": date(2026, 2, 1)}]),
        fetch_statuses=[_fetch_status("equities", "NEM", "NEM")],
        qa_results=foundation_result.raw_qa_report.results,
    )
    persist_normalization_outputs(
        paths=paths,
        run_context=run_context,
        usd_equity_histories=foundation_result.normalized_equity_histories,
        normalized_market_snapshots=foundation_result.normalized_market_snapshots,
        qa_results=foundation_result.normalization_qa_report.results,
    )
    write_latest_foundation_manifest(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        foundation_result=foundation_result,
    )

    # Simulate a later failed/partial refresh overwriting generic latest aliases.
    pd.DataFrame(
        [{"ticker": "NEM", "snapshot_date": date(2030, 1, 1), "share_price_usd": 999.0}]
    ).to_parquet(paths.latest_normalized_market_snapshots_path, index=False)

    loaded = load_latest_foundation_snapshot(paths=paths, app_config=app_config)

    assert str(loaded.normalized_market_snapshots["snapshot_date"].iloc[0]) == "2026-02-01"


def test_load_latest_foundation_snapshot_can_skip_unneeded_equity_histories(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _app_config()
    run_context = RunContext.start(paths=paths, command="update-data", parameters={}, config_hash="hash")
    foundation_result = _foundation_result()

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories={"NEM": pd.DataFrame([{"ticker": "NEM", "date": date(2026, 2, 1)}])},
        fx_histories={},
        gold_history=foundation_result.gold_history,
        market_snapshots=pd.DataFrame([{"ticker": "NEM", "snapshot_date": date(2026, 2, 1)}]),
        fetch_statuses=[_fetch_status("equities", "NEM", "NEM")],
        qa_results=foundation_result.raw_qa_report.results,
    )
    persist_normalization_outputs(
        paths=paths,
        run_context=run_context,
        usd_equity_histories=foundation_result.normalized_equity_histories,
        normalized_market_snapshots=foundation_result.normalized_market_snapshots,
        qa_results=foundation_result.normalization_qa_report.results,
    )
    write_latest_foundation_manifest(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        foundation_result=foundation_result,
    )

    equity_snapshot_path = run_context.run_dir / "snapshots" / "usd_equities.parquet"
    equity_snapshot_path.unlink()

    loaded = load_latest_foundation_snapshot(
        paths=paths,
        app_config=app_config,
        include_gold_history=False,
        include_equity_histories=False,
        include_market_snapshots=True,
    )

    assert loaded.gold_history.empty
    assert loaded.normalized_equity_histories == {}
    assert len(loaded.normalized_market_snapshots.index) == 1


def test_load_latest_foundation_snapshot_rejects_mismatched_universe_signature(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _app_config()
    run_context = RunContext.start(paths=paths, command="update-data", parameters={}, config_hash="hash")
    foundation_result = _foundation_result()

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories={"NEM": pd.DataFrame([{"ticker": "NEM", "date": date(2026, 2, 1)}])},
        fx_histories={},
        gold_history=foundation_result.gold_history,
        market_snapshots=pd.DataFrame([{"ticker": "NEM", "snapshot_date": date(2026, 2, 1)}]),
        fetch_statuses=[_fetch_status("equities", "NEM", "NEM")],
        qa_results=foundation_result.raw_qa_report.results,
    )
    persist_normalization_outputs(
        paths=paths,
        run_context=run_context,
        usd_equity_histories=foundation_result.normalized_equity_histories,
        normalized_market_snapshots=foundation_result.normalized_market_snapshots,
        qa_results=foundation_result.normalization_qa_report.results,
    )
    write_latest_foundation_manifest(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        foundation_result=foundation_result,
    )

    changed_app_config = app_config.model_copy(
        update={
            "universe": UniverseConfig(
                tickers=[
                    UniverseTicker(
                        ticker="NEM",
                        company="Newmont",
                        currency="CAD",
                        active=True,
                        tool_a_enabled=True,
                        tool_b_enabled=True,
                        jurisdiction_tier=1,
                    )
                ]
            )
        }
    )

    try:
        load_latest_foundation_snapshot(paths=paths, app_config=changed_app_config)
    except ValueError as exc:
        assert "update-data" in str(exc)
    else:
        raise AssertionError("Expected ValueError when the universe signature no longer matches the refresh snapshot.")


def test_load_latest_foundation_snapshot_rejects_mismatched_refresh_policy_signature(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = _app_config()
    run_context = RunContext.start(paths=paths, command="update-data", parameters={}, config_hash="hash")
    foundation_result = _foundation_result()

    persist_foundation_outputs(
        paths=paths,
        run_context=run_context,
        equity_histories={"NEM": pd.DataFrame([{"ticker": "NEM", "date": date(2026, 2, 1)}])},
        fx_histories={},
        gold_history=foundation_result.gold_history,
        market_snapshots=pd.DataFrame([{"ticker": "NEM", "snapshot_date": date(2026, 2, 1)}]),
        fetch_statuses=[_fetch_status("equities", "NEM", "NEM")],
        qa_results=foundation_result.raw_qa_report.results,
    )
    persist_normalization_outputs(
        paths=paths,
        run_context=run_context,
        usd_equity_histories=foundation_result.normalized_equity_histories,
        normalized_market_snapshots=foundation_result.normalized_market_snapshots,
        qa_results=foundation_result.normalization_qa_report.results,
    )
    write_latest_foundation_manifest(
        paths=paths,
        run_context=run_context,
        app_config=app_config,
        foundation_result=foundation_result,
    )

    changed_app_config = app_config.model_copy(
        update={
            "qa": app_config.qa.model_copy(update={"max_fx_staleness_days": 2}),
        }
    )

    try:
        load_latest_foundation_snapshot(paths=paths, app_config=changed_app_config)
    except ValueError as exc:
        assert "update-data" in str(exc)
    else:
        raise AssertionError("Expected ValueError when the refresh policy signature no longer matches the snapshot.")


def test_load_latest_foundation_snapshot_fails_cleanly_when_manifest_is_missing(tmp_path):
    paths = build_test_paths(tmp_path)

    try:
        load_latest_foundation_snapshot(paths=paths, app_config=_app_config())
    except FileNotFoundError as exc:
        assert "update-data" in str(exc)
    else:
        raise AssertionError("Expected FileNotFoundError when no local snapshot exists.")
