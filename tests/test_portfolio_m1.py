from __future__ import annotations

import io
import json
import re
import subprocess
from datetime import date
from urllib.parse import urlencode

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.latest_data import _foundation_signature
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    resolve_current_model_artifact_path,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.config_models import HedgeReadinessConfig, PortfolioConfig
from golden_vector.hedge.holdings import Holding
from golden_vector.hedge.portfolio_totals import compute_portfolio_totals
from golden_vector.ingestion.persist_options import safe_options_file_name
import golden_vector.portfolio.manual_store as manual_store_module
from golden_vector.portfolio.manual_store import (
    add_lot,
    delete_lot,
    edit_lot,
    load_lots,
    validate_lot_input,
)
from golden_vector.portfolio.m4_artifacts import (
    build_correlation_frame,
    build_hedge_sizing_frame,
    build_value_history_frame,
)
from golden_vector.portfolio.models import PortfolioStaleSchemaError, PortfolioValidationError
from golden_vector.portfolio.pipeline import build_portfolio_artifacts, build_ticker_info
from golden_vector.portfolio.reader import PortfolioData, load_portfolio_data
from golden_vector.portfolio.valuation import (
    ValuationInput,
    value_major_unit_price,
    value_raw_feed_quote,
)
from golden_vector.serve.workspace import create_workspace_app, run_workspace_server
from golden_vector.serve.portfolio_page import _render_data_issues, _render_hedge_sizing
from tests.helpers import build_test_paths


def test_manual_lot_store_add_edit_delete_and_validation_are_atomic(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    ticker_info = build_ticker_info(app_config)

    first = add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "2",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
            "note": "first buy",
        },
        ticker_info=ticker_info,
    )

    assert first.id
    assert len(load_lots(paths)) == 1

    edited = edit_lot(
        paths,
        first.id,
        {
            "ticker": "NEM",
            "shares": "3",
            "buy_price": "55",
            "buy_currency": "USD",
            "buy_date": "2026-01-03",
            "note": "",
        },
        ticker_info=ticker_info,
    )

    assert edited.id == first.id
    assert edited.created_at == first.created_at
    assert load_lots(paths)[0].shares == 3.0

    before = paths.manual_portfolio_lots_path.read_text(encoding="utf-8")
    with pytest.raises(PortfolioValidationError, match="greater than zero"):
        add_lot(
            paths,
            {
                "ticker": "NEM",
                "shares": "0",
                "buy_price": "55",
                "buy_currency": "USD",
                "buy_date": "2026-01-03",
            },
            ticker_info=ticker_info,
        )
    assert paths.manual_portfolio_lots_path.read_text(encoding="utf-8") == before

    delete_lot(paths, first.id)
    assert load_lots(paths) == []


def test_manual_store_write_failure_keeps_prior_file(tmp_path, monkeypatch):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "1",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    before = paths.manual_portfolio_lots_path.read_text(encoding="utf-8")

    def fail_write(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(manual_store_module, "atomic_write_text", fail_write)
    with pytest.raises(OSError, match="disk full"):
        add_lot(
            paths,
            {
                "ticker": "NEM",
                "shares": "2",
                "buy_price": "55",
                "buy_currency": "USD",
                "buy_date": "2026-01-03",
            },
            ticker_info=ticker_info,
        )

    assert paths.manual_portfolio_lots_path.read_text(encoding="utf-8") == before


def test_manual_lot_validation_rejects_unknown_future_and_wrong_currency(tmp_path):
    app_config = _portfolio_config()
    ticker_info = build_ticker_info(app_config)

    with pytest.raises(PortfolioValidationError, match="Add it to the universe first"):
        validate_lot_input(
            {
                "ticker": "NOTREAL",
                "shares": "1",
                "buy_price": "1",
                "buy_currency": "USD",
                "buy_date": "2026-01-01",
            },
            ticker_info=ticker_info,
            today=date(2026, 6, 8),
        )

    with pytest.raises(PortfolioValidationError, match="future"):
        validate_lot_input(
            {
                "ticker": "NEM",
                "shares": "1",
                "buy_price": "1",
                "buy_currency": "USD",
                "buy_date": "2026-06-09",
            },
            ticker_info=ticker_info,
            today=date(2026, 6, 8),
        )

    with pytest.raises(PortfolioValidationError, match="configured currency"):
        validate_lot_input(
            {
                "ticker": "AAR.AX",
                "shares": "1",
                "buy_price": "1",
                "buy_currency": "USD",
                "buy_date": "2026-01-01",
            },
            ticker_info=ticker_info,
            today=date(2026, 6, 8),
        )

    defaulted = validate_lot_input(
        {
            "ticker": "NEM",
            "shares": "1",
            "buy_price": "1",
            "buy_currency": "",
            "buy_date": "2026-01-01",
        },
        ticker_info=ticker_info,
        today=date(2026, 6, 8),
    )
    assert defaulted.buy_currency == "USD"


def test_portfolio_pipeline_groups_lots_and_computes_local_pnl(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {"ticker": "NEM", "shares": "2", "buy_price": "50", "buy_currency": "USD", "buy_date": "2026-01-02"},
        ticker_info=ticker_info,
    )
    add_lot(
        paths,
        {"ticker": "NEM", "shares": "1", "buy_price": "40", "buy_currency": "USD", "buy_date": "2026-01-03"},
        ticker_info=ticker_info,
    )

    result = build_portfolio_artifacts(paths=paths, app_config=app_config)
    data = load_portfolio_data(paths)

    assert result.positions_count == 1
    assert len(data.lines.index) == 2
    position = data.positions.iloc[0]
    assert position["total_shares"] == pytest.approx(3.0)
    assert position["avg_cost_local"] == pytest.approx(140.0 / 3.0)
    assert position["value_local"] == pytest.approx(180.0)
    assert position["pnl_local"] == pytest.approx(40.0)
    assert position["pnl_fraction_local"] == pytest.approx(40.0 / 140.0)
    assert data.summary.iloc[0]["total_value_usd"] == pytest.approx(180.0)


def test_portfolio_pipeline_degrades_missing_snapshot_line_without_aborting(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="AEM", price=60.0, currency="USD")
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "2",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)

    line = data.lines.iloc[0]
    position = data.positions.iloc[0]
    assert line["line_status"] == "MISSING_PRICE"
    assert "No current snapshot price" in line["line_status_reason"]
    assert pd.isna(line["value_usd"])
    assert position["position_status"] == "MISSING_PRICE"
    assert data.summary.iloc[0]["portfolio_status"] == "WARN"


def test_portfolio_pipeline_computes_non_usd_book_totals_at_current_fx(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(
        paths,
        app_config,
        ticker="DPM.TO",
        price=120.0,
        currency="CAD",
        fx_rate=0.75,
    )
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "DPM.TO",
            "shares": "10",
            "buy_price": "100",
            "buy_currency": "CAD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(paths=paths, app_config=app_config)
    data = load_portfolio_data(paths)
    position = data.positions.iloc[0]

    assert position["pnl_local"] == pytest.approx(200.0)
    assert position["value_usd"] == pytest.approx(900.0)
    assert position["cost_usd_at_current_fx"] == pytest.approx(750.0)
    assert position["pnl_usd_at_current_fx"] == pytest.approx(150.0)
    currency_split = json.loads(data.summary.iloc[0]["currency_split_json"])
    assert currency_split["CAD"]["value_usd"] == pytest.approx(900.0)


def test_portfolio_reader_rejects_stale_schema(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {"ticker": "NEM", "shares": "1", "buy_price": "50", "buy_currency": "USD", "buy_date": "2026-01-02"},
        ticker_info=ticker_info,
    )
    build_portfolio_artifacts(paths=paths, app_config=app_config)
    current_positions_path = resolve_current_model_artifact_path(paths, "portfolio_positions")
    assert current_positions_path is not None
    stale = pd.read_parquet(current_positions_path)
    stale["schema_version"] = 0
    write_parquet_atomic(stale, current_positions_path, index=False)

    with pytest.raises(PortfolioStaleSchemaError, match="schema_version expected"):
        load_portfolio_data(paths)

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    page = _call_wsgi(app, method="GET", path="/portfolio")
    assert page["status"].startswith("503")
    assert "Your local Portfolio data is from the previous version" in page["body"]
    assert "Run python main.py refresh" in page["body"]


def test_portfolio_reader_fails_loud_on_partial_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "1",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    build_portfolio_artifacts(paths=paths, app_config=app_config)
    current_summary_path = resolve_current_model_artifact_path(paths, "portfolio_summary")
    assert current_summary_path is not None
    current_summary_path.unlink()

    with pytest.raises(PortfolioStaleSchemaError, match="incomplete"):
        load_portfolio_data(paths)


def test_portfolio_workspace_privacy_and_no_inline_store_read(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    disabled_config = _portfolio_config(enabled=False)
    paths.output_hedge_readiness_dir.mkdir(parents=True, exist_ok=True)
    (paths.output_hedge_readiness_dir / "latest.md").write_text("SECRET HOLDINGS", encoding="utf-8")

    disabled_app = create_workspace_app(paths, app_config=disabled_config, tool_b_tickers=["NEM"])
    disabled_page = _call_wsgi(disabled_app, method="GET", path="/portfolio")
    blocked_download = _call_wsgi(disabled_app, method="GET", path="/hedge-readiness/latest.md")
    blocked_csv = _call_wsgi(disabled_app, method="GET", path="/portfolio/reconciliation.csv")

    assert disabled_page["status"].startswith("403")
    assert "Portfolio is disabled" in disabled_page["body"]
    assert blocked_download["status"].startswith("403")
    assert blocked_csv["status"].startswith("403")
    assert "SECRET HOLDINGS" not in blocked_download["body"]

    enabled_config = _portfolio_config(enabled=True)
    _write_foundation_snapshot(paths, enabled_config, ticker="NEM", price=60.0, currency="USD")
    ticker_info = build_ticker_info(enabled_config)
    add_lot(
        paths,
        {"ticker": "NEM", "shares": "1", "buy_price": "50", "buy_currency": "USD", "buy_date": "2026-01-02"},
        ticker_info=ticker_info,
    )
    build_portfolio_artifacts(paths=paths, app_config=enabled_config)
    paths.manual_portfolio_lots_path.write_text("not json", encoding="utf-8")

    enabled_app = create_workspace_app(paths, app_config=enabled_config, tool_b_tickers=["NEM"])
    page = _call_wsgi(enabled_app, method="GET", path="/portfolio")

    assert page["status"].startswith("200")
    assert "Positions" in page["body"]
    assert "selected ticker's configured currency" in page["body"]
    assert "enter buy prices in pounds" in page["body"]
    assert "USD 60.00" in page["body"]
    with pytest.raises(ValueError, match="loopback"):
        run_workspace_server(
            paths,
            app_config=enabled_config,
            tool_b_tickers=["NEM"],
            host="0.0.0.0",
        )


def test_portfolio_manual_paths_are_gitignored():
    gitignore = (ProjectPaths.discover().repo_root / ".gitignore").read_text(encoding="utf-8")

    assert "data/manual/portfolio/" in gitignore
    assert "data/manual/**/ibkr*.csv" in gitignore
    assert "data/manual/**/*portfolio*.csv" in gitignore


def test_tracked_files_do_not_contain_broker_account_numbers():
    repo_root = ProjectPaths.discover().repo_root
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    account_pattern = re.compile(r"\b(?:DU|U)\d{7,}\b")
    offenders: list[str] = []
    for relative_path in result.stdout.splitlines():
        path = repo_root / relative_path
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if account_pattern.search(content):
            offenders.append(relative_path)
    assert offenders == []


def test_portfolio_post_adds_lot_recomputes_artifacts_and_redirects(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config(enabled=True)
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])

    response = _call_wsgi(
        app,
        method="POST",
        path="/portfolio/lots",
        data={
            "ticker": "NEM",
            "shares": "2",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
    )

    assert response["status"].startswith("303")
    data = load_portfolio_data(paths)
    assert data.positions.iloc[0]["pnl_local"] == pytest.approx(20.0)


def test_portfolio_rebuild_preserves_existing_manifest_config_hash(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config(enabled=True)
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "1",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        config_hash="config-hash-123",
    )

    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "2",
            "buy_price": "55",
            "buy_currency": "USD",
            "buy_date": "2026-01-03",
        },
        ticker_info=ticker_info,
    )
    build_portfolio_artifacts(paths=paths, app_config=app_config)

    manifest = load_current_model_state_manifest(paths)
    assert manifest is not None
    assert manifest["config"]["config_hash"] == "config-hash-123"


def test_portfolio_valuation_separates_major_unit_and_raw_feed_quotes():
    major = value_major_unit_price(
        ValuationInput(
            quantity=10,
            price_local=0.39,
            price_currency="GBP",
            fx_rate_to_usd=1.25,
        )
    )
    raw = value_raw_feed_quote(
        ValuationInput(
            quantity=10,
            price_local=39.0,
            price_currency="GBP",
            fx_rate_to_usd=1.25,
            feed_currency="GBp",
        )
    )

    assert major.market_value_usd == pytest.approx(raw.market_value_usd)
    assert major.minor_unit_adjusted is False
    assert raw.minor_unit_adjusted is True


def test_portfolio_valuation_rejects_nonfinite_or_nonpositive_inputs():
    with pytest.raises(ValueError, match="quantity"):
        value_major_unit_price(
            ValuationInput(
                quantity=0,
                price_local=10,
                price_currency="USD",
                fx_rate_to_usd=1,
            )
        )
    with pytest.raises(ValueError, match="quantity"):
        value_major_unit_price(
            ValuationInput(
                quantity=float("nan"),
                price_local=10,
                price_currency="USD",
                fx_rate_to_usd=1,
            )
        )
    with pytest.raises(ValueError, match="price_local"):
        value_major_unit_price(
            ValuationInput(
                quantity=1,
                price_local=float("nan"),
                price_currency="USD",
                fx_rate_to_usd=1,
            )
        )
    with pytest.raises(ValueError, match="fx_rate_to_usd"):
        value_major_unit_price(
            ValuationInput(
                quantity=1,
                price_local=10,
                price_currency="USD",
                fx_rate_to_usd=float("inf"),
            )
        )


def test_portfolio_pipeline_degrades_invalid_stored_lot_instead_of_failing_build(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    paths.manual_portfolio_lots_path.parent.mkdir(parents=True, exist_ok=True)
    paths.manual_portfolio_lots_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "lots": [
                    {
                        "id": "bad-lot",
                        "ticker": "NEM",
                        "shares": float("nan"),
                        "buy_price": 50.0,
                        "buy_currency": "USD",
                        "buy_date": "2026-01-02",
                        "note": None,
                        "created_at": "2026-01-02T00:00:00+00:00",
                        "updated_at": "2026-01-02T00:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)

    assert data.lines.iloc[0]["line_status"] == "INVALID_INPUT"
    assert "quantity" in data.lines.iloc[0]["line_status_reason"]
    assert data.positions.iloc[0]["position_status"] == "INVALID_INPUT"
    assert data.summary.iloc[0]["portfolio_status"] == "WARN"


def test_portfolio_pipeline_writes_benchmark_betas_without_universe_pollution(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")
    _write_benchmark_history(paths, "GDX", beta=1.1)
    _write_benchmark_history(paths, "GDXJ", beta=1.4)

    build_portfolio_artifacts(paths=paths, app_config=app_config)
    data = load_portfolio_data(paths)

    assert "GDX" not in {ticker.ticker for ticker in app_config.universe.tickers}
    assert set(data.benchmark_betas["benchmark_ticker"]) == {"GDX", "GDXJ"}
    assert data.benchmark_betas["anchor_window_id"].notna().any()
    assert data.benchmark_betas["n_weeks"].max() > 0
    assert data.benchmark_betas["down_beta_core"].notna().any()
    assert data.reconciliation["status"].tolist() == [
        "MANUAL_ENTRY_NO_BROKER_TOTALS",
        "MANUAL_ENTRY_NO_BROKER_PRICES",
    ]


def test_portfolio_pipeline_enriches_core_analytics_from_tool_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=100.0, currency="USD")
    _write_benchmark_history(paths, "GDX", beta=1.1)
    _write_benchmark_history(paths, "GDXJ", beta=1.4)
    _write_latest_tool_a(paths, ticker="NEM", down_beta=1.5)
    _write_latest_tool_d(paths, ticker="NEM", rank=82.0)
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "10",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)
    position = data.positions.iloc[0]
    summary = data.summary.iloc[0]

    assert position["nav_weight_fraction"] == pytest.approx(1.0)
    assert "position_weight_fraction" not in data.positions.columns
    assert position["down_beta_core"] == pytest.approx(1.5)
    assert position["gold_down_10_pnl_usd"] == pytest.approx(-150.0)
    assert position["gold_down_10_loss_usd"] == pytest.approx(150.0)
    assert position["beta_contribution_fraction"] == pytest.approx(1.0)
    assert position["effective_exposure_bucket"] == "Measured beta"
    assert position["resilience_bucket"] == "Strong resilience"
    assert summary["tool_a_coverage_fraction"] == pytest.approx(1.0)
    assert summary["modeled_gold_down_10_loss_usd"] == pytest.approx(150.0)
    assert summary["largest_position_weight_fraction"] == pytest.approx(1.0)


def test_portfolio_pipeline_uses_fresh_foundation_during_refresh_not_pinned_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "PAF.L",
            "shares": "200",
            "buy_price": "0.30",
            "buy_currency": "GBP",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    _write_foundation_snapshot(
        paths,
        app_config,
        ticker="PAF.L",
        price=0.39,
        currency="GBP",
        fx_rate=1.25,
        feed_currency="GBp",
        price_scale_factor=0.01,
        minor_unit_adjusted=True,
        refresh_run_id="refresh-old",
    )
    write_current_model_state_manifest(
        paths=paths,
        config_hash="old-hash",
        parent_refresh_id="parent-old",
    )
    model_state_before = load_current_model_state_manifest(paths)
    _write_foundation_snapshot(
        paths,
        app_config,
        ticker="PAF.L",
        price=0.42,
        currency="GBP",
        fx_rate=1.25,
        feed_currency="GBp",
        price_scale_factor=0.01,
        minor_unit_adjusted=True,
        refresh_run_id="refresh-new",
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        publish_model_state=False,
        use_model_state_artifacts=False,
    )
    fresh_positions = pd.read_parquet(paths.latest_portfolio_positions_path)
    model_state_after_fresh = load_current_model_state_manifest(paths)

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        publish_model_state=False,
        use_model_state_artifacts=True,
    )
    pinned_positions = pd.read_parquet(paths.latest_portfolio_positions_path)

    assert fresh_positions.iloc[0]["snapshot_refresh_run_id"] == "refresh-new"
    assert fresh_positions.iloc[0]["value_local"] == pytest.approx(84.0)
    assert model_state_after_fresh == model_state_before
    assert pinned_positions.iloc[0]["snapshot_refresh_run_id"] == "refresh-old"
    assert pinned_positions.iloc[0]["value_local"] == pytest.approx(78.0)


def test_portfolio_pipeline_flags_low_beta_stale_fx_and_currency_mismatch(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshots(
        paths,
        app_config,
        rows=[
            {
                "ticker": "NEM",
                "price": 100.0,
                "currency": "USD",
                "fx_rate": 1.0,
                "fx_staleness_days": 30,
            },
            {
                "ticker": "DPM.TO",
                "price": 20.0,
                "currency": "USD",
                "fx_rate": 1.0,
            },
            {
                "ticker": "AEM",
                "price": 80.0,
                "currency": "USD",
                "fx_rate": None,
            },
        ],
    )
    _write_latest_tool_a_rows(
        paths,
        [
            {"ticker": "NEM", "down_beta": 0.05},
            {"ticker": "DPM.TO", "down_beta": 1.2},
            {"ticker": "AEM", "down_beta": 1.2},
        ],
    )
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "1",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    add_lot(
        paths,
        {
            "ticker": "DPM.TO",
            "shares": "1",
            "buy_price": "10",
            "buy_currency": "CAD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    add_lot(
        paths,
        {
            "ticker": "AEM",
            "shares": "1",
            "buy_price": "70",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)
    positions = data.positions.set_index("ticker")
    issues = json.loads(data.summary.iloc[0]["data_issues_json"])
    issue_codes = {issue["issue"] for issue in issues}

    assert "STALE_FX" in positions.loc["NEM", "position_status"]
    assert positions.loc["NEM", "effective_exposure_bucket"] == "Degraded data"
    assert positions.loc["DPM.TO", "position_status"] == "CURRENCY_MISMATCH"
    assert positions.loc["AEM", "position_status"] == "MISSING_FX"
    assert "stale_fx" in issue_codes
    assert "degraded_position_data" in issue_codes
    assert "currency_mismatch" in issue_codes
    assert "missing_fx" in issue_codes


def test_portfolio_pipeline_excludes_degraded_value_from_confident_exposure(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(
        paths,
        app_config,
        ticker="NEM",
        price=100.0,
        currency="USD",
        fx_staleness_days=30,
    )
    _write_benchmark_history(paths, "GDX", beta=1.1)
    _write_benchmark_history(paths, "GDXJ", beta=1.4)
    _write_latest_tool_a(paths, ticker="NEM", down_beta=1.5)
    _write_latest_tool_d(paths, ticker="NEM", rank=82.0)
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "10",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)
    position = data.positions.iloc[0]
    summary = data.summary.iloc[0]
    hedge = data.hedge_sizing.set_index("benchmark_ticker").loc["GDX"]

    assert position["position_status"] == "STALE_FX"
    assert position["value_local"] == pytest.approx(1000.0)
    assert position["value_usd"] == pytest.approx(1000.0)
    assert position["down_beta_core"] == pytest.approx(1.5)
    assert position["effective_exposure_bucket"] == "Degraded data"
    assert pd.isna(position["gold_down_10_loss_usd"])
    assert summary["tool_a_coverage_value_usd"] == pytest.approx(0.0)
    assert summary["tool_a_coverage_fraction"] == pytest.approx(0.0)
    assert summary["modeled_gold_down_10_loss_usd"] == pytest.approx(0.0)
    assert hedge["effective_gold_exposure_usd"] == pytest.approx(0.0)
    assert hedge["hedge_status"] == "NO_MEASURED_EXPOSURE"


def test_portfolio_pipeline_uses_configured_gold_beta_gate(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    base_config = _portfolio_config()
    app_config = base_config.model_copy(
        update={
            "hedge_readiness": base_config.hedge_readiness.model_copy(
                update={"down_beta_min_for_scenario": 2.0}
            )
        }
    )
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=100.0, currency="USD")
    _write_benchmark_history(paths, "GDX", beta=1.1)
    _write_benchmark_history(paths, "GDXJ", beta=1.4)
    _write_latest_tool_a(paths, ticker="NEM", down_beta=1.5)
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "10",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)

    assert data.positions.iloc[0]["effective_exposure_bucket"] == "Low/negative beta"
    assert data.summary.iloc[0]["tool_a_coverage_value_usd"] == pytest.approx(0.0)


def test_portfolio_pipeline_writes_m4_artifacts_and_reconciliation_csv(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config(enabled=True)
    _write_foundation_snapshots(
        paths,
        app_config,
        rows=[
            {"ticker": "NEM", "price": 100.0, "currency": "USD", "fx_rate": 1.0},
            {"ticker": "AEM", "price": 80.0, "currency": "USD", "fx_rate": 1.0},
        ],
    )
    _write_benchmark_history(paths, "GDX", beta=1.1)
    _write_benchmark_history(paths, "GDXJ", beta=1.4)
    _write_latest_tool_a_rows(
        paths,
        [
            {"ticker": "NEM", "down_beta": 1.5},
            {"ticker": "AEM", "down_beta": 1.2},
        ],
    )
    _write_latest_tool_d_rows(
        paths,
        [
            {"ticker": "NEM", "rank": 82.0},
            {"ticker": "AEM", "rank": 71.0},
        ],
    )
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "10",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )
    add_lot(
        paths,
        {
            "ticker": "AEM",
            "shares": "5",
            "buy_price": "60",
            "buy_currency": "USD",
            "buy_date": "2026-01-03",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)

    assert {"GDX", "GDXJ"} == set(data.hedge_sizing["benchmark_ticker"])
    gdx = data.hedge_sizing.set_index("benchmark_ticker").loc["GDX"]
    assert gdx["hedge_status"] == "OK"
    expected_exposure = 1000.0 * 1.5 + 400.0 * 1.2
    assert gdx["effective_gold_exposure_usd"] == pytest.approx(expected_exposure)
    assert gdx["modeled_short_notional_usd"] == pytest.approx(
        expected_exposure / gdx["benchmark_down_beta"]
    )
    assert gdx["modeled_put_contracts"] >= 1

    pair = data.correlations[data.correlations["pair_rank"].eq(1)].iloc[0]
    assert {pair["row_ticker"], pair["column_ticker"]} == {"AEM", "NEM"}
    assert pair["pair_exposure_fraction"] == pytest.approx(1.0)
    assert pair["overlap_days"] >= 30
    assert pair["correlation_heat_bucket"] in {"high", "very-high"}

    assert not data.value_history.empty
    assert data.value_history["chart_x"].notna().all()
    assert data.value_history["chart_y"].notna().all()
    assert data.value_history.iloc[-1]["covered_market_value_usd"] == pytest.approx(1400.0)

    assert len(data.reconciliation_export.index) == 2
    csv_path = paths.latest_portfolio_reconciliation_export_csv_path
    assert csv_path.exists()
    assert "canonical_value_usd" in csv_path.read_text(encoding="utf-8")
    resolved_csv = resolve_current_model_artifact_path(
        paths,
        "portfolio_reconciliation_export_csv",
    )
    assert resolved_csv is not None
    assert resolved_csv != csv_path
    assert resolved_csv.name.startswith("portfolio_reconciliation_export_latest_")
    csv_path.write_text("alias_only\nBROKEN\n", encoding="utf-8")

    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM", "AEM"])
    page = _call_wsgi(app, method="GET", path="/portfolio")
    download = _call_wsgi(app, method="GET", path="/portfolio/reconciliation.csv")
    assert page["status"].startswith("200")
    assert "Modeled GDX/GDXJ hedge size" in page["body"]
    assert "Gold -10% loss is a simple linear beta estimate" in page["body"]
    assert "Total USD P&L blends stock movement and FX movement" in page["body"]
    assert "Equity Weight" in page["body"]
    assert "Linear Loss @ Gold -10%" in page["body"]
    assert "Show all 1 paired exposures" in page["body"]
    assert "Corporate resilience coverage" in page["body"]
    assert "Market value of today" in page["body"]
    assert download["status"].startswith("200")
    assert "canonical_value_usd" in download["body"]
    assert "alias_only" not in download["body"]


def test_portfolio_empty_book_builds_artifacts_and_renders_clean_empty_state(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config(enabled=True)
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=60.0, currency="USD")

    result = build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)
    app = create_workspace_app(paths, app_config=app_config, tool_b_tickers=["NEM"])
    page = _call_wsgi(app, method="GET", path="/portfolio")
    download = _call_wsgi(app, method="GET", path="/portfolio/reconciliation.csv")

    assert result.summary_status == "EMPTY"
    assert data.summary.iloc[0]["portfolio_status"] == "EMPTY"
    assert data.positions.empty
    assert page["status"].startswith("200")
    assert "Add your first position below" in page["body"]
    assert download["status"].startswith("200")
    assert "schema_version" in download["body"]


def test_portfolio_hedge_sizing_math_and_fail_closed_statuses():
    positions = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "value_usd": 1_000.0,
                "down_beta_core": 1.50,
                "effective_exposure_bucket": "Measured beta",
            },
            {
                "ticker": "AEM",
                "value_usd": 500.0,
                "down_beta_core": 1.00,
                "effective_exposure_bucket": "Measured beta",
            },
            {
                "ticker": "NO_BETA",
                "value_usd": 700.0,
                "down_beta_core": None,
                "effective_exposure_bucket": "Missing beta",
            },
        ]
    )
    benchmarks = pd.DataFrame(
        [
            {
                "benchmark_ticker": "GDX",
                "benchmark_label": "VanEck Gold Miners ETF",
                "benchmark_status": "OK",
                "benchmark_status_reason": None,
                "benchmark_price_usd": 7.0,
                "benchmark_price_date": "2026-06-08",
                "down_beta_core": 1.25,
            },
            {
                "benchmark_ticker": "GDXJ",
                "benchmark_label": "VanEck Junior Gold Miners ETF",
                "benchmark_status": "LOW_CONFIDENCE",
                "benchmark_status_reason": "Benchmark beta confidence is LOW.",
                "benchmark_price_usd": 10.0,
                "benchmark_price_date": "2026-06-08",
                "down_beta_core": 1.40,
            },
            {
                "benchmark_ticker": "MISSING_BETA",
                "benchmark_label": "Missing beta",
                "benchmark_status": "OK",
                "benchmark_status_reason": None,
                "benchmark_price_usd": 10.0,
                "benchmark_price_date": "2026-06-08",
                "down_beta_core": None,
            },
            {
                "benchmark_ticker": "MISSING_PRICE",
                "benchmark_label": "Missing price",
                "benchmark_status": "OK",
                "benchmark_status_reason": None,
                "benchmark_price_usd": None,
                "benchmark_price_date": None,
                "down_beta_core": 1.10,
            },
        ]
    )

    frame = build_hedge_sizing_frame(
        positions=positions,
        benchmark_betas=benchmarks,
        source_run_id="portfolio-run",
        snapshot_refresh_run_id="refresh-run",
    )

    rows = frame.set_index("benchmark_ticker")
    effective_exposure = 1_000.0 * 1.50 + 500.0 * 1.00
    notional = effective_exposure / 1.25
    assert rows.loc["GDX", "effective_gold_exposure_usd"] == pytest.approx(effective_exposure)
    assert rows.loc["GDX", "modeled_short_notional_usd"] == pytest.approx(notional)
    assert rows.loc["GDX", "modeled_put_contracts"] == 3
    assert rows.loc["GDX", "hedge_status"] == "OK"

    assert rows.loc["GDXJ", "hedge_status"] == "UNAVAILABLE"
    assert "LOW" in rows.loc["GDXJ", "hedge_status_reason"]
    assert rows.loc["MISSING_BETA", "hedge_status"] == "UNAVAILABLE"
    assert "beta" in rows.loc["MISSING_BETA", "hedge_status_reason"].lower()
    assert rows.loc["MISSING_PRICE", "hedge_status"] == "UNAVAILABLE"
    assert "price" in rows.loc["MISSING_PRICE", "hedge_status_reason"].lower()

    zero_exposure = build_hedge_sizing_frame(
        positions=pd.DataFrame(
            [
                {
                    "ticker": "LOW_BETA",
                    "value_usd": 1_000.0,
                    "down_beta_core": 0.0,
                    "effective_exposure_bucket": "Low/negative beta",
                }
            ]
        ),
        benchmark_betas=benchmarks.iloc[[1]],
        source_run_id="portfolio-run",
        snapshot_refresh_run_id="refresh-run",
    )
    zero_row = zero_exposure.iloc[0]
    assert zero_row["hedge_status"] == "NO_MEASURED_EXPOSURE"
    assert zero_row["hedge_status_reason"] == "No measured gold exposure to hedge."
    assert pd.isna(zero_row["modeled_short_notional_usd"])
    assert pd.isna(zero_row["modeled_put_contracts"])


def test_portfolio_hedge_sizing_zero_exposure_message_renders_in_serve_layer():
    data = PortfolioData(
        lines=pd.DataFrame(),
        positions=pd.DataFrame(),
        summary=pd.DataFrame(),
        benchmark_betas=pd.DataFrame(),
        reconciliation=pd.DataFrame(),
        hedge_sizing=pd.DataFrame(
            [
                {
                    "benchmark_ticker": "GDX",
                    "benchmark_label": "VanEck Gold Miners ETF",
                    "benchmark_status": "OK",
                    "benchmark_status_reason": None,
                    "benchmark_price_usd": 50.0,
                    "benchmark_down_beta": 1.2,
                    "effective_gold_exposure_usd": 0.0,
                    "modeled_short_notional_usd": None,
                    "modeled_put_contracts": None,
                    "hedge_status": "NO_MEASURED_EXPOSURE",
                    "hedge_status_reason": "No measured gold exposure to hedge.",
                    "basis_risk_note": "basis risk note",
                }
            ]
        ),
        correlations=pd.DataFrame(),
        value_history=pd.DataFrame(),
        reconciliation_export=pd.DataFrame(),
    )

    html = _render_hedge_sizing(data)

    assert "No measured gold exposure to hedge" in html
    assert "GDX hedge size unavailable" not in html


def test_portfolio_hedge_sizing_uses_unclamped_effective_exposure_for_high_beta():
    benchmarks = pd.DataFrame(
        [
            {
                "benchmark_ticker": "GDX",
                "benchmark_label": "VanEck Gold Miners ETF",
                "benchmark_status": "OK",
                "benchmark_status_reason": None,
                "benchmark_price_usd": 50.0,
                "benchmark_price_date": "2026-06-08",
                "down_beta_core": 1.50,
            }
        ]
    )
    frame = build_hedge_sizing_frame(
        positions=pd.DataFrame(
            [
                {
                    "ticker": "EXTREME",
                    "value_usd": 10_000.0,
                    "down_beta_core": 15.0,
                    "effective_exposure_bucket": "Measured beta",
                }
            ]
        ),
        benchmark_betas=benchmarks,
        source_run_id="portfolio-run",
        snapshot_refresh_run_id="refresh-run",
    )
    row = frame.iloc[0]

    assert row["effective_gold_exposure_usd"] == pytest.approx(150_000.0)
    assert row["modeled_short_notional_usd"] == pytest.approx(100_000.0)
    assert row["modeled_put_contracts"] == 20


def test_portfolio_and_hedge_paths_agree_on_negative_and_high_beta_exposure(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshots(
        paths,
        app_config,
        rows=[
            {"ticker": "NEM", "price": 100.0, "currency": "USD", "fx_rate": 1.0},
            {"ticker": "AEM", "price": 100.0, "currency": "USD", "fx_rate": 1.0},
        ],
    )
    _write_latest_tool_a_rows(
        paths,
        [
            {"ticker": "NEM", "down_beta": 12.0},
            {"ticker": "AEM", "down_beta": -1.0},
        ],
    )
    ticker_info = build_ticker_info(app_config)
    for ticker in ("NEM", "AEM"):
        add_lot(
            paths,
            {
                "ticker": ticker,
                "shares": "10",
                "buy_price": "50",
                "buy_currency": "USD",
                "buy_date": "2026-01-02",
            },
            ticker_info=ticker_info,
        )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    portfolio_data = load_portfolio_data(paths)
    hedge_totals = compute_portfolio_totals(
        holdings=[
            Holding(ticker="NEM", dollar_exposure=1_000.0),
            Holding(ticker="AEM", dollar_exposure=1_000.0),
        ],
        tool_a_frame=pd.DataFrame(
            [
                {"ticker": "NEM", "down_beta_core": 12.0},
                {"ticker": "AEM", "down_beta_core": -1.0},
            ]
        ),
        tool_b_frame=pd.DataFrame(),
        options_features=None,
        candidate_grids={},
        config=HedgeReadinessConfig(),
    )
    assert hedge_totals is not None
    hedge_down_10 = next(
        row
        for row in hedge_totals.scenario_rows
        if row.gold_pct_change == pytest.approx(-0.10)
    )

    assert portfolio_data.positions.set_index("ticker").loc["AEM", "effective_exposure_bucket"] == "Low/negative beta"
    assert portfolio_data.summary.iloc[0]["modeled_gold_down_10_loss_usd"] == pytest.approx(
        hedge_down_10.portfolio_loss_dollars
    )
    assert hedge_down_10.portfolio_loss_dollars == pytest.approx(1_000.0)


def test_portfolio_data_issues_render_all_rows_not_first_twelve():
    issues = [
        {"ticker": f"T{index:02d}", "issue": f"issue_{index}", "message": f"message_{index}"}
        for index in range(13)
    ]
    data = PortfolioData(
        lines=pd.DataFrame(),
        positions=pd.DataFrame(),
        summary=pd.DataFrame([{"data_issues_json": json.dumps(issues)}]),
        benchmark_betas=pd.DataFrame(),
        reconciliation=pd.DataFrame(),
        hedge_sizing=pd.DataFrame(),
        correlations=pd.DataFrame(),
        value_history=pd.DataFrame(),
        reconciliation_export=pd.DataFrame(),
    )

    html = _render_data_issues(data)

    assert "Showing all 13 current data issues" in html
    assert "issue_12" in html
    assert "message_12" in html


def test_portfolio_correlation_fails_closed_with_insufficient_overlap():
    positions = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "nav_weight_fraction": 0.60,
                "effective_exposure_bucket": "Measured beta",
            },
            {
                "ticker": "AEM",
                "nav_weight_fraction": 0.40,
                "effective_exposure_bucket": "Measured beta",
            },
        ]
    )
    dates = pd.bdate_range("2026-01-01", periods=10)
    histories = {
        "NEM": pd.DataFrame(
            {
                "date": dates.date,
                "return_basis_usd": [100 + index for index in range(len(dates))],
            }
        ),
        "AEM": pd.DataFrame(
            {
                "date": dates.date,
                "return_basis_usd": [80 + index * 1.5 for index in range(len(dates))],
            }
        ),
    }

    frame = build_correlation_frame(
        positions=positions,
        normalized_equity_histories=histories,
        source_run_id="portfolio-run",
        snapshot_refresh_run_id="refresh-run",
    )

    pair = frame[
        frame["row_ticker"].eq("AEM")
        & frame["column_ticker"].eq("NEM")
    ].iloc[0]
    assert pair["overlap_days"] == 9
    assert pair["correlation_status"] == "INSUFFICIENT_HISTORY"
    assert pd.isna(pair["correlation"])
    assert pair["correlation_heat_bucket"] == "unavailable"


def test_portfolio_correlation_ranks_all_pairs_not_first_eight():
    positions = pd.DataFrame(
        [
            {
                "ticker": f"T{index}",
                "nav_weight_fraction": 0.20,
                "effective_exposure_bucket": "Measured beta",
            }
            for index in range(5)
        ]
    )
    dates = pd.bdate_range("2026-01-01", periods=45)
    histories = {
        f"T{index}": pd.DataFrame(
            {
                "date": dates.date,
                "return_basis_usd": [
                    100.0 + day * (index + 1) + ((day + index) % 5) * 0.1
                    for day in range(len(dates))
                ],
            }
        )
        for index in range(5)
    }

    frame = build_correlation_frame(
        positions=positions,
        normalized_equity_histories=histories,
        source_run_id="portfolio-run",
        snapshot_refresh_run_id="refresh-run",
    )

    pair_ranks = pd.to_numeric(frame["pair_rank"], errors="coerce").dropna()
    assert len(pair_ranks.index) == 10
    assert int(pair_ranks.max()) == 10


def test_portfolio_value_history_reports_only_included_history_coverage():
    positions = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "total_shares": 10.0,
                "nav_weight_fraction": 0.60,
                "effective_exposure_bucket": "Measured beta",
            },
            {
                "ticker": "AEM",
                "total_shares": 5.0,
                "nav_weight_fraction": 0.40,
                "effective_exposure_bucket": "Measured beta",
            },
        ]
    )
    history = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=3, freq="D").date,
            "close_usd": [90.0, 95.0, 100.0],
        }
    )
    summary = pd.DataFrame([{"nav_value_usd": 1_000.0}])

    frame = build_value_history_frame(
        positions=positions,
        normalized_equity_histories={"NEM": history, "AEM": pd.DataFrame()},
        summary=summary,
        source_run_id="portfolio-run",
        snapshot_refresh_run_id="refresh-run",
    )

    assert len(frame.index) == 3
    assert frame["covered_position_count"].tolist() == [1, 1, 1]
    assert frame["covered_book_weight_fraction"].tolist() == pytest.approx([0.60, 0.60, 0.60])
    assert frame["covered_market_value_usd"].tolist() == pytest.approx([900.0, 950.0, 1000.0])


def test_portfolio_pipeline_flags_missing_tool_rows_without_silent_blanks(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    app_config = _portfolio_config()
    _write_foundation_snapshot(paths, app_config, ticker="NEM", price=100.0, currency="USD")
    ticker_info = build_ticker_info(app_config)
    add_lot(
        paths,
        {
            "ticker": "NEM",
            "shares": "1",
            "buy_price": "50",
            "buy_currency": "USD",
            "buy_date": "2026-01-02",
        },
        ticker_info=ticker_info,
    )

    build_portfolio_artifacts(
        paths=paths,
        app_config=app_config,
        use_model_state_artifacts=False,
    )
    data = load_portfolio_data(paths)
    issues = json.loads(data.summary.iloc[0]["data_issues_json"])
    issue_codes = {issue["issue"] for issue in issues}

    assert data.positions.iloc[0]["effective_exposure_bucket"] == "Missing beta"
    assert pd.isna(data.positions.iloc[0]["gold_down_10_pnl_usd"])
    assert "missing_tool_a" in issue_codes
    assert "missing_tool_d" in issue_codes


def _portfolio_config(*, enabled: bool = True):
    app_config = load_app_config(ProjectPaths.discover()).app
    return app_config.model_copy(update={"portfolio": PortfolioConfig(enabled=enabled)})


def _write_foundation_snapshot(
    paths,
    app_config,
    *,
    ticker: str,
    price: float,
    currency: str,
    fx_rate: float = 1.0,
    fx_staleness_days: int = 0,
    feed_currency: str | None = None,
    price_scale_factor: float = 1.0,
    minor_unit_adjusted: bool = False,
    refresh_run_id: str = "refresh-run",
) -> None:
    _write_foundation_snapshots(
        paths,
        app_config,
        rows=[
            {
                "ticker": ticker,
                "price": price,
                "currency": currency,
                "fx_rate": fx_rate,
                "fx_staleness_days": fx_staleness_days,
                "feed_currency": feed_currency,
                "price_scale_factor": price_scale_factor,
                "minor_unit_adjusted": minor_unit_adjusted,
            }
        ],
        refresh_run_id=refresh_run_id,
    )


def _write_foundation_snapshots(
    paths,
    app_config,
    *,
    rows: list[dict[str, object]],
    refresh_run_id: str = "refresh-run",
) -> None:
    run_dir = paths.ensure_run_dir(refresh_run_id)
    snapshot_path = run_dir / "market_snapshots_usd.parquet"
    equities_path = run_dir / "usd_equities.parquet"
    gold_path = run_dir / "gold_history.parquet"
    snapshots = pd.DataFrame(
        [
            {
                "ticker": row["ticker"],
                "snapshot_date": "2026-06-08",
                "currency": row["currency"],
                "share_price_local": row["price"],
                "fx_rate_to_usd": row["fx_rate"],
                "fx_source_date": "2026-06-08",
                "fx_source_symbol": (
                    "USD"
                    if row["currency"] == "USD"
                    else f"{row['currency']}USD"
                ),
                "fx_staleness_days": row.get("fx_staleness_days", 0),
                "share_price_usd": (
                    float(row["price"]) * float(row["fx_rate"])
                    if row["fx_rate"] is not None
                    else None
                ),
                "market_cap_usd": (
                    6000.0 * float(row["fx_rate"])
                    if row["fx_rate"] is not None
                    else None
                ),
                "shares_outstanding": 100.0,
                "source": "test",
                "source_run_id": "refresh-run",
                "feed_currency": row.get("feed_currency") or row["currency"],
                "price_scale_factor": row.get("price_scale_factor", 1.0),
                "minor_unit_adjusted": bool(row.get("minor_unit_adjusted", False)),
                "normalization_status": row.get("normalization_status", "OK"),
            }
            for row in rows
        ]
    )
    equities = pd.concat(
        [
            _equity_history_frame(
                ticker=str(row["ticker"]),
                latest_price=float(row["price"]),
                currency=str(row["currency"]),
                fx_rate=float(row["fx_rate"] or 1.0),
                feed_currency=str(row.get("feed_currency") or row["currency"]),
                price_scale_factor=float(row.get("price_scale_factor", 1.0)),
                minor_unit_adjusted=bool(row.get("minor_unit_adjusted", False)),
            )
            for row in rows
        ],
        ignore_index=True,
    )
    write_parquet_atomic(snapshots, snapshot_path, index=False)
    write_parquet_atomic(equities, equities_path, index=False)
    write_parquet_atomic(_gold_history_frame(), gold_path, index=False)
    payload = {
        "refresh_run_id": refresh_run_id,
        "foundation_status": "PASS",
        "foundation_signature": _foundation_signature(app_config),
        "raw_qa_summary": {"overall_status": "PASS"},
        "normalization_qa_summary": {"overall_status": "PASS"},
        "snapshot_as_of_date": "2026-06-08",
        "gold_history_path": gold_path.relative_to(paths.repo_root).as_posix(),
        "raw_equities_snapshot_path": "",
        "raw_fx_snapshot_path": "",
        "normalized_equities_snapshot_path": equities_path.relative_to(paths.repo_root).as_posix(),
        "normalized_market_snapshots_snapshot_path": snapshot_path.relative_to(paths.repo_root).as_posix(),
        "summary": {},
    }
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(json.dumps(payload), encoding="utf-8")


def _equity_history_frame(
    *,
    ticker: str,
    latest_price: float,
    currency: str,
    fx_rate: float,
    feed_currency: str | None = None,
    price_scale_factor: float = 1.0,
    minor_unit_adjusted: bool = False,
) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-06-08", periods=70)
    raw = pd.Series(
        [
            1.0
            + index * 0.003
            + ((index % 7) - 3) * 0.004
            + (0.001 if ticker.startswith("A") else 0.0)
            for index in range(len(dates))
        ],
        dtype="float64",
    )
    close_usd = latest_price * fx_rate * raw / float(raw.iloc[-1])
    close_local = close_usd / fx_rate
    return pd.DataFrame(
        {
            "ticker": ticker,
            "date": dates.date,
            "open_local": close_local,
            "high_local": close_local * 1.01,
            "low_local": close_local * 0.99,
            "close_local": close_local,
            "adj_close_local": close_local,
            "close_usd": close_usd,
            "return_basis_usd": close_usd,
            "currency": currency,
            "exchange": "TEST",
            "source": "test",
            "source_symbol": ticker,
            "feed_currency": feed_currency or currency,
            "price_scale_factor": price_scale_factor,
            "minor_unit_adjusted": minor_unit_adjusted,
            "fx_rate_to_usd": fx_rate,
            "fetched_at_utc": pd.Timestamp("2026-06-08T00:00:00Z"),
        }
    )


def _gold_history_frame() -> pd.DataFrame:
    dates = pd.date_range("2022-01-07", periods=180, freq="W-FRI")
    gold = [1800.0]
    for index in range(1, len(dates)):
        move = 0.01 if index % 2 else -0.006
        gold.append(gold[-1] * (1.0 + move))
    return pd.DataFrame(
        {
            "date": dates.date,
            "gold_symbol": "GC=F",
            "close_usd": gold,
            "adj_close_usd": gold,
            "source": "test",
            "source_symbol": "GC=F",
            "fetched_at_utc": pd.Timestamp("2026-06-08T00:00:00Z"),
        }
    )


def _write_benchmark_history(paths: ProjectPaths, ticker: str, *, beta: float) -> None:
    gold = _gold_history_frame()
    base_gold = float(gold["adj_close_usd"].iloc[0])
    prices = 40.0 * (pd.to_numeric(gold["adj_close_usd"]) / base_gold) ** beta
    frame = pd.DataFrame(
        {
            "ticker": ticker,
            "date": gold["date"],
            "open_local": prices,
            "high_local": prices * 1.01,
            "low_local": prices * 0.99,
            "close_local": prices,
            "adj_close_local": prices,
            "volume": 1_000_000,
            "currency": "USD",
            "exchange": "BENCHMARK",
            "source": "test",
            "source_symbol": ticker,
            "feed_currency": "USD",
            "price_scale_factor": 1.0,
            "minor_unit_adjusted": False,
            "fetched_at_utc": pd.Timestamp("2026-06-08T00:00:00Z"),
        }
    )
    paths.benchmarks_dir.mkdir(parents=True, exist_ok=True)
    write_parquet_atomic(
        frame,
        paths.benchmarks_dir / f"{safe_options_file_name(ticker)}.parquet",
        index=False,
    )


def _write_latest_tool_a(paths: ProjectPaths, *, ticker: str, down_beta: float) -> None:
    _write_latest_tool_a_rows(paths, [{"ticker": ticker, "down_beta": down_beta}])


def _write_latest_tool_a_rows(paths: ProjectPaths, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(
        [
            {
                "ticker": row["ticker"],
                "as_of_date": "2026-06-08",
                "down_beta_core": row["down_beta"],
                "confidence_label": "HIGH",
                "score_eligible": True,
            }
            for row in rows
        ]
    )
    write_parquet_atomic(frame, paths.latest_tool_a_snapshot_parquet_path, index=False)


def _write_latest_tool_d(paths: ProjectPaths, *, ticker: str, rank: float) -> None:
    _write_latest_tool_d_rows(paths, [{"ticker": ticker, "rank": rank}])


def _write_latest_tool_d_rows(paths: ProjectPaths, rows: list[dict[str, object]]) -> None:
    frame = pd.DataFrame(
        [
            {
                "ticker": row["ticker"],
                "as_of_date": "2026-06-08",
                "tool_d_quality_rank": row["rank"],
                "tool_d_quality_score": float(row["rank"]) - 5.0,
                "tool_d_tags": "strong_headroom",
            }
            for row in rows
        ]
    )
    write_parquet_atomic(frame, paths.latest_tool_d_spot_snapshot_parquet_path, index=False)


def _call_wsgi(app, *, method: str, path: str, data: dict[str, str] | None = None):
    payload = urlencode(data or {}).encode("utf-8")
    captured: dict[str, object] = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_LENGTH": str(len(payload)),
        "wsgi.input": io.BytesIO(payload),
    }
    body = b"".join(app(environ, start_response)).decode("utf-8")
    return {
        "status": str(captured["status"]),
        "headers": captured["headers"],
        "body": body,
    }
