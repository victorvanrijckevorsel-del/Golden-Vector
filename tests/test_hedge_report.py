from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.run_context import RunContext
from golden_vector.cli import run_hedge_readiness
from golden_vector.features.options import compute_options_features
from golden_vector.ingestion.persist_options import (
    persist_options_snapshot,
    write_latest_options_manifest,
)
from tests.helpers import build_test_paths


def test_run_hedge_readiness_writes_markdown_report(tmp_path, capsys):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths)
    _write_holdings(paths)
    _write_options_inputs(paths, update_context, app_config)

    exit_code = run_hedge_readiness(paths)

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Hedge readiness report written:" in output
    latest_report = paths.output_hedge_readiness_dir / "latest.md"
    assert latest_report.exists()
    markdown = latest_report.read_text(encoding="utf-8")
    assert "# Hedge Readiness Report" in markdown
    assert "## Held Positions" in markdown
    assert "### AEM" in markdown
    assert "Candidate puts:" in markdown
    assert "Premium vs modeled downside:" in markdown
    assert "## Proxy-Hedge Map" in markdown
    assert "AAUC.TO" in markdown


def test_run_hedge_readiness_reports_missing_options_manifest(tmp_path, capsys):
    paths = build_test_paths(tmp_path)

    exit_code = run_hedge_readiness(paths)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Run `python main.py update-data` first" in output


def _write_options_inputs(paths, context: RunContext, app_config) -> None:
    chain = pd.read_parquet("tests/fixtures/options/aem_chain_20260529.parquet")
    aem_record = persist_options_snapshot(
        paths=paths,
        run_context=context,
        ticker="AEM",
        frame=chain,
        as_of_date=date(2026, 5, 29),
        options_available=True,
    )
    aauc_record = persist_options_snapshot(
        paths=paths,
        run_context=context,
        ticker="AAUC.TO",
        frame=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
        options_available=False,
        message="No listed options returned by Yahoo.",
    )
    write_latest_options_manifest(
        paths=paths,
        run_context=context,
        as_of_date=date(2026, 5, 29),
        snapshot_records=[aem_record, aauc_record],
        risk_free_rate=0.04,
        summary={"options_phase_status": "PASS"},
    )
    aem_features = compute_options_features(
        chain=pd.read_parquet(aem_record.snapshot_path),
        underlying_price=50.0,
        risk_free_rate=0.04,
        price_history=_price_history(),
        as_of_date=date(2026, 5, 29),
        target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
        optionability_open_interest_threshold=100,
    )
    aem_features.update(
        {
            "ticker": "AEM",
            "run_id": context.run_id,
            "underlying_price": 50.0,
            "iv_percentile_cross_sectional": 100.0,
        }
    )
    aauc_features = compute_options_features(
        chain=pd.read_parquet(aauc_record.snapshot_path),
        underlying_price=20.0,
        risk_free_rate=0.04,
        price_history=pd.DataFrame(),
        as_of_date=date(2026, 5, 29),
        target_horizons_days=tuple(app_config.hedge_readiness.target_horizons_days),
    )
    aauc_features.update(
        {
            "ticker": "AAUC.TO",
            "run_id": context.run_id,
            "underlying_price": 20.0,
            "iv_percentile_cross_sectional": None,
        }
    )
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([aem_features]).to_parquet(paths.options_features_dir / "AEM.parquet", index=False)
    pd.DataFrame([aauc_features]).to_parquet(paths.options_features_dir / "AAUC.TO.parquet", index=False)


def _write_tool_outputs(paths) -> None:
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    paths.output_tool_b_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"ticker": "AEM", "down_beta_core": 1.4, "confidence_score": 0.8},
            {"ticker": "AAUC.TO", "down_beta_core": 1.2, "confidence_score": 0.6},
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    pd.DataFrame(
        [
            {"ticker": "AEM", "share_price_usd": 50.0, "screening_verdict": "WATCH"},
            {"ticker": "AAUC.TO", "share_price_usd": 20.0, "screening_verdict": "INCOMPLETE"},
        ]
    ).to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)


def _write_holdings(paths) -> None:
    paths.manual_holdings_dir.mkdir(parents=True, exist_ok=True)
    paths.holdings_path.write_text(
        """
version: 1
holdings:
  - ticker: AEM
    dollar_exposure: 10000
  - ticker: AAUC.TO
    dollar_exposure: 5000
""".lstrip(),
        encoding="utf-8",
    )


def _price_history() -> pd.DataFrame:
    return pd.DataFrame({"return_basis_usd": [0.001, -0.002, 0.003, -0.001] * 30})
