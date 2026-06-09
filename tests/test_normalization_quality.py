import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.ingestion.registry import build_foundation_registry
from golden_vector.qa.normalization_quality import evaluate_normalization_quality


def _load_test_app_config():
    return load_app_config(ProjectPaths.discover()).app


def _build_usd_equities(registry, *, default_status: str = "OK"):
    return {
        target.ticker: pd.DataFrame(
            [
                {
                    "ticker": target.ticker,
                    "date": "2026-01-01",
                    "return_basis_usd": 10.0,
                    "normalization_status": default_status,
                }
            ]
        )
        for target in registry.equity_targets
    }


def _build_market_snapshots(registry, *, default_status: str = "OK"):
    return pd.DataFrame(
        [
            {
                "ticker": target.ticker,
                "snapshot_date": "2026-01-01",
                "normalization_status": default_status,
            }
            for target in registry.market_snapshot_targets
        ]
    )


def test_normalization_quality_passes_when_all_rows_are_ok():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=_build_usd_equities(registry),
        normalized_market_snapshots=_build_market_snapshots(registry),
    )

    assert report.overall_status == "PASS"


def test_normalization_quality_fails_when_ticker_has_no_usable_usd_rows():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    usd_equities = _build_usd_equities(registry)
    first_ticker = registry.equity_targets[0].ticker
    usd_equities[first_ticker] = pd.DataFrame(
        [
            {
                "ticker": first_ticker,
                "date": "2026-01-01",
                "normalization_status": "MISSING_FX",
            }
        ]
    )

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=usd_equities,
        normalized_market_snapshots=_build_market_snapshots(registry),
    )

    assert report.overall_status == "FAIL"


def test_normalization_quality_warns_when_missing_rows_came_from_fetch_failure():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    usd_equities = _build_usd_equities(registry)
    first_ticker = registry.equity_targets[0].ticker
    usd_equities[first_ticker] = pd.DataFrame()

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=usd_equities,
        normalized_market_snapshots=_build_market_snapshots(registry),
        failed_equity_tickers={first_ticker},
    )

    assert report.overall_status == "WARN"


def test_normalization_quality_warns_on_partial_fx_coverage():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    usd_equities = _build_usd_equities(registry)
    first_ticker = registry.equity_targets[0].ticker
    usd_equities[first_ticker] = pd.DataFrame(
        [
            {
                "ticker": first_ticker,
                "date": "2026-01-01",
                "normalization_status": "MISSING_FX",
            },
            {
                "ticker": first_ticker,
                "date": "2026-01-02",
                "normalization_status": "OK",
            },
        ]
    )

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=usd_equities,
        normalized_market_snapshots=_build_market_snapshots(registry),
    )

    assert report.overall_status == "WARN"


def test_normalization_quality_warns_when_tool_b_snapshots_have_issues():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=_build_usd_equities(registry),
        normalized_market_snapshots=_build_market_snapshots(
            registry,
            default_status="MISSING_FX",
        ),
    )

    assert report.overall_status == "WARN"


def test_normalization_quality_warns_on_stale_fx_by_default():
    app_config = _load_test_app_config()
    registry = build_foundation_registry(app_config.universe)
    usd_equities = _build_usd_equities(registry)
    first_ticker = registry.equity_targets[0].ticker
    usd_equities[first_ticker] = pd.DataFrame(
        [
            {
                "ticker": first_ticker,
                "date": "2026-01-10",
                "fx_staleness_days": 7,
                "normalization_status": "STALE_FX",
            }
        ]
    )

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=usd_equities,
        normalized_market_snapshots=_build_market_snapshots(registry),
    )

    assert report.overall_status == "WARN"


def test_normalization_quality_can_block_on_stale_fx():
    app_config = _load_test_app_config().model_copy(
        update={
            "qa": _load_test_app_config().qa.model_copy(update={"block_on_stale_fx": True}),
        }
    )
    registry = build_foundation_registry(app_config.universe)

    report = evaluate_normalization_quality(
        app_config=app_config,
        registry=registry,
        usd_equity_histories=_build_usd_equities(registry),
        normalized_market_snapshots=_build_market_snapshots(
            registry,
            default_status="STALE_FX",
        ),
    )

    assert report.overall_status == "FAIL"
