from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.run_context import RunContext
from golden_vector.cli import build_parser, run_hedge_readiness
from golden_vector.features.options import compute_options_features
from golden_vector.hedge import report as report_module
from golden_vector.hedge.candidate_puts import CandidatePut
from golden_vector.hedge.scenarios import CandidateScenarioBundle, ScenarioRow
from golden_vector.ingestion.persist_options import (
    persist_options_snapshot,
    write_latest_options_manifest,
)
from tests.helpers import build_test_paths


def test_hedge_readiness_parser_accepts_all_cli_flags():
    args = build_parser().parse_args(
        [
            "hedge-readiness",
            "--comparison-sort-by",
            "breakeven_gold_pct",
            "--ranking-sort-by",
            "down_beta_core",
            "--ranking-max-tickers",
            "5",
            "--speculation-max-tickers",
            "3",
            "--quantity",
            "10",
        ]
    )

    assert args.command == "hedge-readiness"
    assert args.comparison_sort_by == "breakeven_gold_pct"
    assert args.ranking_sort_by == "down_beta_core"
    assert args.ranking_max_tickers == 5
    assert args.speculation_max_tickers == 3
    assert args.quantity == 10


def test_hedge_readiness_parser_rejects_invalid_sort_choice():
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            ["hedge-readiness", "--comparison-sort-by", "not_a_column"]
        )


def test_run_hedge_readiness_plumbs_cli_options(tmp_path, monkeypatch):
    import golden_vector.cli as cli_module

    paths = build_test_paths(tmp_path)
    captured = {}

    def fake_write_hedge_readiness_report(**kwargs):
        captured.update(kwargs)
        output_path = paths.output_hedge_readiness_dir / "fake.md"
        latest_path = paths.output_hedge_readiness_dir / "latest.md"
        paths.output_hedge_readiness_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text("# fake\n", encoding="utf-8")
        latest_path.write_text("# fake\n", encoding="utf-8")
        return SimpleNamespace(
            report_path=output_path,
            latest_path=latest_path,
            markdown="# fake\n",
            summary={
                "context_alignment_status": "OK",
                "directly_hedgeable_count": 1,
                "thin_count": 2,
                "none_count": 3,
                "holdings_count": 4,
            },
        )

    monkeypatch.setattr(
        cli_module,
        "write_hedge_readiness_report",
        fake_write_hedge_readiness_report,
    )

    exit_code = run_hedge_readiness(
        paths,
        comparison_sort_by="pnl_per_contract_minus20",
        ranking_sort_by="down_beta_core",
        ranking_max_tickers=5,
        speculation_max_tickers=3,
        quantity=10,
    )

    assert exit_code == 0
    assert captured["comparison_sort_by"] == "pnl_per_contract_minus20"
    assert captured["ranking_sort_by"] == "down_beta_core"
    assert captured["ranking_max_tickers"] == 5
    assert captured["speculation_max_tickers"] == 3
    assert captured["quantity"] == 10


def test_run_hedge_readiness_writes_markdown_report(tmp_path, capsys):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id=update_context.run_id)
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
    _assert_heading_order(
        markdown,
        [
            "# Hedge Readiness Report",
            "## Snapshot Summary",
            "## Sensitivity Ranking",
            "## Portfolio Totals",
            "## Held Positions",
            "## Speculation Candidates",
            "## Cross-ticker Comparison View",
            "## Proxy Hedges",
            "## Sources / Run Summary",
        ],
    )
    assert "## Held Positions" in markdown
    assert "## Portfolio Totals" in markdown
    assert "| Holdings mode | mixed |" in markdown
    assert "| Scenario quantity | 5 contracts |" in markdown
    assert "### AEM" in markdown
    assert "Premium vs modeled downside:" in markdown
    assert "## Proxy Hedges" in markdown
    assert "AAUC.TO" in markdown
    assert "Tool B WATCH" in markdown
    assert "| Analytical context alignment | OK |" in markdown
    assert "- Options feature rows: 2" in markdown
    aem_block = markdown.split("### AEM", 1)[1].split("### AAUC.TO", 1)[0]
    assert aem_block.count("No usable listed put candidate found") == 1
    assert "Candidate puts:" not in aem_block
    aauc_block = markdown.split("### AAUC.TO", 1)[1].split("## Speculation Candidates", 1)[0]
    assert aauc_block.count("No usable listed put candidate found") == 1
    assert "Candidate puts:" not in aauc_block


def test_run_hedge_readiness_warns_when_tool_context_is_stale(tmp_path, capsys):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id="older-refresh")
    _write_options_inputs(paths, update_context, app_config)

    exit_code = run_hedge_readiness(paths)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Context alignment: WARN" in output
    markdown = (paths.output_hedge_readiness_dir / "latest.md").read_text(encoding="utf-8")
    assert "| Analytical context alignment | WARN |" in markdown
    assert "Tool A snapshot refresh does not match options source run" in markdown


def test_run_hedge_readiness_warns_when_tool_context_has_no_refresh_id(tmp_path, capsys):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id=None)
    _write_options_inputs(paths, update_context, app_config)

    exit_code = run_hedge_readiness(paths)

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Context alignment: UNKNOWN" in output
    markdown = (paths.output_hedge_readiness_dir / "latest.md").read_text(encoding="utf-8")
    assert "| Analytical context alignment | UNKNOWN |" in markdown
    assert "Tool A snapshot refresh run id is missing" in markdown


def test_run_hedge_readiness_reports_missing_options_manifest(tmp_path, capsys):
    paths = build_test_paths(tmp_path)

    exit_code = run_hedge_readiness(paths)

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "Run `python main.py update-data` first" in output


def test_run_hedge_readiness_omits_portfolio_sections_without_holdings(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id=update_context.run_id)
    _write_options_inputs(paths, update_context, app_config)

    exit_code = run_hedge_readiness(paths)

    assert exit_code == 0
    markdown = (paths.output_hedge_readiness_dir / "latest.md").read_text(encoding="utf-8")
    assert "## Sensitivity Ranking" in markdown
    assert "## Speculation Candidates" in markdown
    assert "## Cross-ticker Comparison View" in markdown
    assert "## Portfolio Totals" not in markdown
    assert "## Held Positions" not in markdown


def test_run_hedge_readiness_surfaces_zero_rate_fallback(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id=update_context.run_id)
    _write_options_inputs(paths, update_context, app_config, risk_free_rate=None)

    exit_code = run_hedge_readiness(paths)

    assert exit_code == 0
    markdown = (paths.output_hedge_readiness_dir / "latest.md").read_text(encoding="utf-8")
    assert "| Risk-free rate | 0.0% fallback |" in markdown
    assert "scenario Black-Scholes values use a 0% fallback" in markdown
    assert "Risk-free rate is unavailable; using 0% fallback." in markdown


def test_run_hedge_readiness_surfaces_resolved_flag_values(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id=update_context.run_id)
    _write_options_inputs(paths, update_context, app_config)

    exit_code = run_hedge_readiness(
        paths,
        ranking_max_tickers=1,
        speculation_max_tickers=1,
        quantity=10,
    )

    assert exit_code == 0
    markdown = (paths.output_hedge_readiness_dir / "latest.md").read_text(encoding="utf-8")
    assert "| Scenario quantity | 10 contracts |" in markdown
    assert "| Ranking max tickers | 1 |" in markdown
    assert "| Speculation max tickers | 1 |" in markdown
    assert "Showing 1 of 2 tickers." in markdown
    assert "Showing up to 1 optionable tickers." in markdown


def test_run_hedge_readiness_ignores_stale_feature_rows(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    update_context = RunContext.start(
        paths=paths,
        command="update-data",
        parameters={"options": True},
        config_hash="test-config",
    )
    _write_tool_outputs(paths, refresh_run_id=update_context.run_id)
    _write_options_inputs(paths, update_context, app_config)
    stale = pd.read_parquet(paths.options_features_dir / "AEM.parquet")
    stale["run_id"] = "older-run"
    stale.to_parquet(paths.options_features_dir / "AEM.parquet", index=False)

    exit_code = run_hedge_readiness(paths)

    assert exit_code == 0
    markdown = (paths.output_hedge_readiness_dir / "latest.md").read_text(encoding="utf-8")
    assert "| Directly hedgeable | 0 |" in markdown
    assert "- Raw option snapshots: 2" in markdown
    assert "- Options feature rows: 1" in markdown
    sensitivity_block = markdown.split("## Sensitivity Ranking", 1)[1].split(
        "## Speculation Candidates",
        1,
    )[0]
    assert "AEM" in sensitivity_block
    assert "no options features; no listed options" in sensitivity_block
    speculation_block = markdown.split("## Speculation Candidates", 1)[1].split(
        "## Cross-ticker Comparison View",
        1,
    )[0]
    assert "### AEM" not in speculation_block


def test_report_price_resolution_prefers_chain_over_tool_b_when_feature_missing():
    price = report_module._current_stock_price(
        feature={"ticker": "AEM"},
        tool_b_row=pd.Series({"share_price_usd": 40.0}),
        chain=pd.DataFrame([{"underlying_price": 55.0}]),
    )

    assert price == 55.0


def test_report_optionable_tickers_treats_missing_tier_as_not_optionable():
    optionable = report_module._optionable_tickers(
        pd.DataFrame(
            [
                {"ticker": "AEM", "optionability_tier": pd.NA},
                {"ticker": "NEM", "optionability_tier": "thin"},
                {"ticker": "KGC", "optionability_tier": "none"},
            ]
        )
    )

    assert optionable == {"NEM"}


def test_scenario_rendering_labels_quote_units_and_multiplier():
    bundle = CandidateScenarioBundle(
        ticker="AEM",
        horizon="60d",
        candidate=_candidate_put(),
        rows=[
            ScenarioRow(
                gold_pct_change=-0.10,
                implied_stock_price=43.0,
                stock_clamped_at_zero=False,
                expiry_value_per_contract=2.0,
                current_value_per_contract=2.4,
                pnl_per_contract_at_expiry=0.8,
                pnl_per_contract_if_closed_today=1.2,
                net_pnl_at_expiry=400.0,
                net_pnl_if_closed_today=600.0,
            )
        ],
        breakeven_gold_pct=None,
        breakeven_annotation=None,
        down_beta_used=1.4,
        confidence_label="HIGH",
    )

    rendered = "\n".join(report_module._render_scenario_bundles([bundle]))

    assert "P&L/share expiry" in rendered
    assert "standard 100-share multiplier" in rendered
    assert "P&L/contract" not in rendered


def _assert_heading_order(markdown: str, headings: list[str]) -> None:
    positions = [markdown.index(heading) for heading in headings]
    assert positions == sorted(positions)


def _write_options_inputs(
    paths,
    context: RunContext,
    app_config,
    *,
    risk_free_rate: float | None = 0.04,
) -> None:
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
        risk_free_rate=risk_free_rate,
        summary={"options_phase_status": "PASS"},
    )
    aem_features = compute_options_features(
        chain=pd.read_parquet(aem_record.snapshot_path),
        underlying_price=50.0,
        risk_free_rate=risk_free_rate,
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
            "optionability_tier": "directly_hedgeable",
            "iv_percentile_cross_sectional": 100.0,
        }
    )
    aauc_features = compute_options_features(
        chain=pd.read_parquet(aauc_record.snapshot_path),
        underlying_price=20.0,
        risk_free_rate=risk_free_rate,
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


def _write_tool_outputs(paths, *, refresh_run_id: str | None = "refresh-run") -> None:
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    paths.output_tool_b_dir.mkdir(parents=True, exist_ok=True)
    tool_a_rows = [
        {"ticker": "AEM", "down_beta_core": 1.4, "confidence_score": 0.8},
        {"ticker": "AAUC.TO", "down_beta_core": 1.2, "confidence_score": 0.6},
    ]
    tool_b_rows = [
        {"ticker": "AEM", "share_price_usd": 50.0, "screening_verdict": "WATCH"},
        {
            "ticker": "AAUC.TO",
            "share_price_usd": 20.0,
            "screening_verdict": "INCOMPLETE",
        },
    ]
    if refresh_run_id is not None:
        for row in [*tool_a_rows, *tool_b_rows]:
            row["snapshot_refresh_run_id"] = refresh_run_id
    pd.DataFrame(tool_a_rows).to_parquet(
        paths.latest_tool_a_snapshot_parquet_path,
        index=False,
    )
    pd.DataFrame(tool_b_rows).to_parquet(
        paths.latest_tool_b_snapshot_parquet_path,
        index=False,
    )


def _write_holdings(paths) -> None:
    paths.manual_holdings_dir.mkdir(parents=True, exist_ok=True)
    paths.holdings_path.write_text(
        """
version: 1
holdings:
  - ticker: AEM
    shares: 200
  - ticker: AAUC.TO
    dollar_exposure: 5000
""".lstrip(),
        encoding="utf-8",
    )


def _price_history() -> pd.DataFrame:
    return pd.DataFrame({"return_basis_usd": [0.001, -0.002, 0.003, -0.001] * 30})


def _candidate_put() -> CandidatePut:
    return CandidatePut(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-31",
        days_to_expiry=60,
        strike=45.0,
        bid=1.15,
        ask=1.25,
        mid=1.20,
        open_interest=500,
        volume=50,
        implied_volatility=0.40,
        delta=-0.25,
        delta_gap=0.01,
        premium_pct_spot=1.20 / 50.0,
        underlying_price=50.0,
    )
