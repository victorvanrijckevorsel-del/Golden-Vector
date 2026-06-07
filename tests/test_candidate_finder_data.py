from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.cli import run_candidate_finder, run_option_artifacts
from golden_vector.contracts.option_artifacts import (
    option_artifact_latest_path,
    option_artifact_run_stamped_path,
)
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from golden_vector.hedge.option_trading import OptionTradingOverviewData
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.screening.manual_store import upsert_company_input
from golden_vector.serve.candidate_finder_data import (
    clear_candidate_finder_cache,
    load_candidate_finder_data,
    run_candidate_finder_screen,
    _joined_frame,
)
from golden_vector.serve.option_trading_data import OptionTradingData
from tests.helpers import build_test_paths


def test_candidate_finder_data_joins_sources_and_derives_ratios(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")

    data = load_candidate_finder_data(paths, app_config=app_config)
    frame = data.frame.set_index("ticker")

    assert data.alignment.status == "OK"
    assert data.cache_key.options_refresh_run_id == "refresh-run"
    assert data.cache_key.manual_store_hash is not None
    assert bool(frame.loc["AEM", "has_usable_put_candidate"]) is True
    assert bool(frame.loc["AEM", "has_usable_call_candidate"]) is True
    assert bool(frame.loc["NEM", "has_usable_put_candidate"]) is True
    assert bool(frame.loc["NEM", "has_usable_call_candidate"]) is False
    assert frame.loc["AEM", "debt_to_mktcap"] == pytest.approx(0.20)
    assert frame.loc["AEM", "ebitda_to_mktcap"] == pytest.approx(0.50)
    assert frame.loc["AEM", "revenue_to_mktcap"] == pytest.approx(1.20)
    assert frame.loc["AEM", "netincome_to_mktcap"] == pytest.approx(0.30)
    assert frame.loc["AEM", "tool_c_downside_rank"] == pytest.approx(90.0)
    assert frame.loc["AEM", "tool_c_upside_rank"] == pytest.approx(75.0)
    assert frame.loc["AEM", "tool_d_quality_rank"] == pytest.approx(45.0)
    assert frame.loc["NEM", "tool_d_quality_rank"] == pytest.approx(80.0)


def test_candidate_finder_cache_key_tracks_model_state_manifest(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "state": "complete",
                "parent_refresh_id": None,
                "generated_at_utc": "2026-06-05T10:00:00Z",
                "alignment": {"status": "OK"},
                "warnings": [],
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.cache_key.model_state_manifest_hash is not None
    assert data.model_state_manifest is not None
    assert data.model_state_manifest["state"] == "complete"


def test_candidate_finder_usable_side_filter_excludes_watch_candidates():
    from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
    from golden_vector.serve.candidate_finder_data import _has_usable_slots

    watch_candidate = OptionCandidate(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-17",
        days_to_expiry=43,
        strike=96.0,
        bid=3.00,
        ask=4.00,
        mid=3.50,
        open_interest=60,
        volume=5,
        implied_volatility=0.40,
        delta=-0.35,
        delta_gap=0.0,
        premium_pct_spot=0.035,
        underlying_price=100.0,
        option_type="P",
        bucket="near_atm",
        liquidity_tier="watch",
        rel_spread=1.0 / 3.5,
        otm_pct=0.04,
    )
    tradable_candidate = OptionCandidate(
        ticker="AEM",
        horizon_days=60,
        expiration="2026-07-17",
        days_to_expiry=43,
        strike=96.0,
        bid=3.20,
        ask=3.40,
        mid=3.30,
        open_interest=200,
        volume=5,
        implied_volatility=0.40,
        delta=-0.35,
        delta_gap=0.0,
        premium_pct_spot=0.033,
        underlying_price=100.0,
        option_type="P",
        bucket="near_atm",
        liquidity_tier="tradable",
        rel_spread=0.2 / 3.3,
        otm_pct=0.04,
    )

    assert not _has_usable_slots(
        [
            OptionCandidateSlot(
                ticker="AEM",
                option_type="P",
                horizon_days=60,
                target_delta=-0.25,
                expiration="2026-07-17",
                days_to_expiry=43,
                status="accepted",
                reason="Watch only.",
                candidate=watch_candidate,
                bucket="near_atm",
                liquidity_tier="watch",
            )
        ]
    )
    assert _has_usable_slots(
        [
            OptionCandidateSlot(
                ticker="AEM",
                option_type="P",
                horizon_days=60,
                target_delta=-0.25,
                expiration="2026-07-17",
                days_to_expiry=43,
                status="accepted",
                reason="Tradable.",
                candidate=tradable_candidate,
                bucket="near_atm",
                liquidity_tier="tradable",
            )
        ]
    )


def test_candidate_finder_configured_source_fields_exist_in_joined_frame(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")

    data = load_candidate_finder_data(paths, app_config=app_config)
    missing = [
        criterion.source_field
        for criterion in app_config.candidate_finder.criteria
        if criterion.source_field not in data.frame.columns
    ]

    assert missing == []


def test_candidate_finder_join_drops_stale_option_duplicate_columns(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    _add_stale_option_duplicate_columns(paths)

    data = load_candidate_finder_data(paths, app_config=app_config)
    frame = data.frame.set_index("ticker")

    assert not any(column.endswith(("_x", "_y")) for column in data.frame.columns)
    assert frame.loc["AEM", "down_beta_core"] == pytest.approx(1.4)
    assert frame.loc["AEM", "up_beta_core"] == pytest.approx(1.2)
    assert frame.loc["AEM", "aisc_usd_per_oz"] == pytest.approx(1700.0)
    assert frame.loc["AEM", "market_cap_musd"] == pytest.approx(1000.0)
    assert frame.loc["AEM", "debt_to_mktcap"] == pytest.approx(0.20)
    for source_field in _PREVIOUSLY_COLLIDED_SOURCE_FIELDS:
        assert data.frame[source_field].notna().any(), source_field
    assert not any("duplicate-suffix columns" in item for item in data.alignment.messages)


def test_candidate_finder_presets_remain_eligible_with_stale_option_duplicates(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    _add_stale_option_duplicate_columns(paths)

    data = load_candidate_finder_data(paths, app_config=app_config)
    bearish = run_candidate_finder_screen(data, spec={"preset": "bearish_put"})
    bullish = run_candidate_finder_screen(data, spec={"preset": "bullish_call"})
    down_beta = run_candidate_finder_screen(
        data,
        spec={
            "options_side": "puts",
            "criteria": [{"id": "down_beta", "direction": "high_good"}],
        },
    )
    up_beta = run_candidate_finder_screen(
        data,
        spec={
            "options_side": "calls",
            "criteria": [{"id": "up_beta", "direction": "high_good"}],
        },
    )

    assert any(row.rank_eligible for row in bearish.ranking.rows)
    assert any(row.rank_eligible for row in bullish.ranking.rows)
    assert [row.ticker for row in down_beta.ranking.rows if row.rank_eligible]
    assert [row.ticker for row in up_beta.ranking.rows if row.rank_eligible] == ["AEM"]


def test_candidate_finder_join_warns_when_configured_field_is_all_null(tmp_path):
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app

    frame = _joined_frame(
        app_config=app_config,
        tool_a=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "down_beta_core": pd.NA,
                    "up_beta_core": 1.2,
                }
            ]
        ),
        tool_b=pd.DataFrame(),
        tool_c=pd.DataFrame(),
        tool_d=pd.DataFrame(),
        options=pd.DataFrame({"ticker": ["AEM"]}),
        manual_company=pd.DataFrame(),
        option_data=OptionTradingData(
            overview=OptionTradingOverviewData(rows=()),
            candidate_grids={},
            call_candidate_grids={},
            candidate_slots={},
            call_candidate_slots={},
            options_features=pd.DataFrame(),
            tool_a=pd.DataFrame(),
            tool_b=pd.DataFrame(),
            raw_options_by_ticker={},
            risk_free_rate=0.0,
            risk_free_rate_is_fallback=False,
            cache_key=None,
        ),
    )

    warnings = tuple(frame.attrs.get("candidate_finder_join_warnings", ()))
    assert any("down_beta_core" in warning for warning in warnings)


def test_candidate_finder_data_handles_missing_sources(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "UNKNOWN"
    assert not data.frame.empty
    assert "debt_to_mktcap" in data.frame.columns
    assert data.frame["debt_to_mktcap"].isna().all()
    assert data.frame["has_usable_put_candidate"].eq(False).all()
    assert data.frame["has_usable_call_candidate"].eq(False).all()


def test_candidate_finder_data_warns_when_tool_c_or_tool_d_outputs_are_missing(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(
        paths,
        refresh_run_id="refresh-run",
        include_tool_c_d=False,
    )

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "UNKNOWN"
    assert data.alignment.message is not None
    assert "Gold Downside" in data.alignment.message
    assert "Corporate Resilience" in data.alignment.message
    assert data.frame["tool_c_downside_rank"].isna().all()
    assert data.frame["tool_d_quality_rank"].isna().all()


def test_candidate_finder_data_ignores_non_spot_mutable_tool_d_latest(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    non_spot = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    non_spot["gold_price_used"] = 3500.0
    non_spot["spot_gold_usd"] = 4000.0
    non_spot.to_parquet(paths.latest_tool_d_snapshot_parquet_path, index=False)

    data = load_candidate_finder_data(paths, app_config=app_config)

    frame = data.frame.set_index("ticker")
    assert data.alignment.status == "OK"
    assert data.alignment.message is None
    assert frame.loc["AEM", "tool_d_quality_rank"] == pytest.approx(45.0)
    assert frame.loc["NEM", "tool_d_quality_rank"] == pytest.approx(80.0)


def test_candidate_finder_data_prefers_spot_tool_d_alias_over_scenario_latest(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    spot = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    paths.latest_tool_d_spot_snapshot_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    spot.to_parquet(paths.latest_tool_d_spot_snapshot_parquet_path, index=False)
    scenario = spot.copy()
    scenario["gold_price_used"] = 3500.0
    scenario["spot_gold_usd"] = 4000.0
    scenario["tool_d_quality_rank"] = 1.0
    scenario.to_parquet(paths.latest_tool_d_snapshot_parquet_path, index=False)

    data = load_candidate_finder_data(paths, app_config=app_config)

    frame = data.frame.set_index("ticker")
    assert data.alignment.status == "OK"
    assert frame.loc["AEM", "tool_d_quality_rank"] == pytest.approx(45.0)
    assert frame.loc["NEM", "tool_d_quality_rank"] == pytest.approx(80.0)


def test_candidate_finder_data_cache_ignores_corrupt_latest_alias_without_manifest(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    first = load_candidate_finder_data(paths, app_config=app_config)
    paths.latest_tool_a_snapshot_parquet_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_tool_a_snapshot_parquet_path.write_text("not parquet", encoding="utf-8")

    second = load_candidate_finder_data(paths, app_config=app_config)

    assert first.cache_key != second.cache_key
    assert any("Gold Sensitivity latest parquet could not be read" in item for item in second.alignment.messages)


def test_candidate_finder_data_ignores_corrupt_latest_alias_with_manifest(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    paths.latest_tool_a_snapshot_parquet_path.write_text("not parquet", encoding="utf-8")

    data = load_candidate_finder_data(paths, app_config=app_config)
    screen = run_candidate_finder_screen(data, spec={"preset": "bearish_put"})

    assert data.alignment.status == "OK"
    assert not any("Gold Sensitivity latest parquet could not be read" in item for item in screen.warnings)


def test_candidate_finder_screen_filters_peer_pool_before_ranking(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    data = load_candidate_finder_data(paths, app_config=app_config)

    screen = run_candidate_finder_screen(
        data,
        spec={
            "options_side": "calls",
            "criteria": [{"id": "up_beta", "weight": 1.0}],
            "top_n": 5,
        },
    )

    assert screen.options_side == "calls"
    assert screen.peer_frame["ticker"].tolist() == ["AEM"]
    assert [row.ticker for row in screen.ranking.rows] == ["AEM"]
    assert screen.ranking.rows[0].score == 100.0


def test_candidate_finder_screen_surfaces_invalid_spec_warnings(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    data = load_candidate_finder_data(paths, app_config=app_config)

    screen = run_candidate_finder_screen(
        data,
        spec={
            "preset": "missing",
            "options_side": "banana",
            "top_n": 0,
            "criteria": "down_beta",
        },
    )

    assert screen.options_side == "either"
    assert screen.top_n == app_config.candidate_finder.default_top_n
    assert "Unknown preset ignored: missing." in screen.warnings
    assert "Invalid options_side ignored: banana." in screen.warnings
    assert "Invalid top_n ignored: 0; using 10." in screen.warnings
    assert "Invalid criteria ignored: expected a list." in screen.warnings
    assert "Pick at least one criterion." in screen.warnings


def test_candidate_finder_data_warns_on_mixed_refreshes(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(
        paths,
        refresh_run_id="options-run",
        tool_a_refresh_run_id="tool-a-run",
        tool_b_refresh_run_id="tool-b-run",
    )

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "WARN"
    assert data.alignment.message is not None
    assert "Gold Sensitivity" in data.alignment.message
    assert "Corporate Finance" in data.alignment.message
    assert "Options" in data.alignment.message


def test_candidate_finder_alignment_uses_model_state_manifest_when_present(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    payload = load_current_model_state_manifest(paths)
    assert payload is not None
    payload["alignment"] = {
        "status": "WARN",
        "warnings": [
            "tool_c references stale-run while foundation is refresh-run.",
        ],
    }
    payload["warnings"] = []
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    clear_candidate_finder_cache()

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "WARN"
    assert data.alignment.message is not None
    assert "tool_c references stale-run" in data.alignment.message


def test_candidate_finder_data_warns_when_manual_store_is_newer_than_tool_b(tmp_path):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(
        paths,
        refresh_run_id="refresh-run",
        tool_b_source_run_id="20200101T000000Z-tool-b-old",
    )

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status == "WARN"
    assert any("Manual store was updated after" in item for item in data.alignment.messages)


def test_candidate_finder_cli_writes_ranked_parquet(tmp_path, capsys):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    spec_path = tmp_path / "screen.yaml"
    output_path = tmp_path / "candidate_finder.parquet"
    spec_path.write_text(
        """
options_side: puts
top_n: 5
criteria:
  - id: down_beta
    direction: high_good
    weight: 1
  - id: debt_to_mktcap
    direction: high_good
    weight: 1
""",
        encoding="utf-8",
    )

    exit_code = run_candidate_finder(
        paths,
        spec_path=str(spec_path),
        out_path=str(output_path),
    )
    captured = capsys.readouterr().out
    ranked = pd.read_parquet(output_path)

    assert exit_code == 0
    assert output_path.exists()
    assert "Candidate Finder ranked parquet written" in captured
    assert {"AEM", "NEM"}.issubset(set(ranked["ticker"]))
    assert "percentile_down_beta" in ranked.columns
    assert "percentile_debt_to_mktcap" in ranked.columns


def test_candidate_finder_cli_allows_output_outside_repo(tmp_path, capsys):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    spec_path = tmp_path / "screen.yaml"
    output_path = tmp_path.parent / "candidate_finder_external.parquet"
    spec_path.write_text("preset: bearish_put\noptions_side: puts\n", encoding="utf-8")

    exit_code = run_candidate_finder(
        paths,
        spec_path=str(spec_path),
        out_path=str(output_path),
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert output_path.exists()
    assert str(output_path) in captured


def _write_candidate_finder_inputs(
    paths,
    *,
    refresh_run_id: str,
    tool_a_refresh_run_id: str | None = None,
    tool_b_refresh_run_id: str | None = None,
    tool_b_source_run_id: str | None = None,
    include_tool_c_d: bool = True,
) -> None:
    paths.ensure_runtime_dirs()
    tool_a_run = tool_a_refresh_run_id or refresh_run_id
    tool_b_run = tool_b_refresh_run_id or refresh_run_id
    bootstrap_manual_screening_data(paths, tickers=["AEM", "NEM"])
    upsert_company_input(paths, ticker="AEM", values={"net_debt_musd": 200.0, "aisc_usd_per_oz": 1700.0})
    upsert_company_input(paths, ticker="NEM", values={"net_debt_musd": 100.0, "aisc_usd_per_oz": 1500.0})
    tool_a_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=tool_a_context,
        tool_a_outputs=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "down_beta_core": 1.4,
                    "up_beta_core": 1.2,
                    "structural_delta_core": 1.3,
                    "downside_volatility_52w": 0.35,
                    "confidence_score": 0.9,
                    "score_eligible": True,
                    "snapshot_refresh_run_id": tool_a_run,
                    "source_run_id": tool_a_context.run_id,
                },
                {
                    "ticker": "NEM",
                    "down_beta_core": 1.1,
                    "up_beta_core": 0.9,
                    "structural_delta_core": 1.0,
                    "downside_volatility_52w": 0.25,
                    "confidence_score": 0.8,
                    "score_eligible": True,
                    "snapshot_refresh_run_id": tool_a_run,
                    "source_run_id": tool_a_context.run_id,
                },
            ]
        ),
    )
    tool_b_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=tool_b_context,
        tool_b_outputs=pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "market_cap_musd": 1000.0,
                    "share_price_usd": 100.0,
                    "forward_revenue_musd": 1200.0,
                    "forward_ebitda_musd": 500.0,
                    "forward_net_income_musd": 300.0,
                    "forward_pe": 8.0,
                    "ev_ebitda": 2.4,
                    "fcf_yield": 0.18,
                    "leverage": 0.4,
                    "best_upside_pct": 0.30,
                    "snapshot_refresh_run_id": tool_b_run,
                    "source_run_id": tool_b_context.run_id,
                },
                {
                    "ticker": "NEM",
                    "market_cap_musd": 2000.0,
                    "share_price_usd": 100.0,
                    "forward_revenue_musd": 1600.0,
                    "forward_ebitda_musd": 600.0,
                    "forward_net_income_musd": 260.0,
                    "forward_pe": 10.0,
                    "ev_ebitda": 3.6,
                    "fcf_yield": 0.12,
                    "leverage": 0.2,
                    "best_upside_pct": 0.20,
                    "snapshot_refresh_run_id": tool_b_run,
                    "source_run_id": tool_b_context.run_id,
                },
            ]
        ),
    )
    if include_tool_c_d:
        tool_c_context = RunContext.start(
            paths=paths,
            command="tool-c",
            parameters={},
            config_hash="hash",
        )
        persist_tool_c_outputs(
            paths=paths,
            run_context=tool_c_context,
            tool_c_outputs=pd.DataFrame(
                [
                    {
                        "ticker": "AEM",
                        "tool_c_downside_rank": 90.0,
                        "tool_c_upside_rank": 75.0,
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_c_context.run_id,
                    },
                    {
                        "ticker": "NEM",
                        "tool_c_downside_rank": 60.0,
                        "tool_c_upside_rank": 55.0,
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_c_context.run_id,
                    },
                ]
            ),
        )
        tool_d_context = RunContext.start(
            paths=paths,
            command="tool-d",
            parameters={},
            config_hash="hash",
        )
        persist_tool_d_outputs(
            paths=paths,
            run_context=tool_d_context,
            tool_d_outputs=pd.DataFrame(
                [
                    {
                        "ticker": "AEM",
                        "tool_d_quality_rank": 45.0,
                        "gold_price_used": 4000.0,
                        "spot_gold_usd": 4000.0,
                        "spot_gold_date": "2026-06-01",
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_d_context.run_id,
                    },
                    {
                        "ticker": "NEM",
                        "tool_d_quality_rank": 80.0,
                        "gold_price_used": 4000.0,
                        "spot_gold_usd": 4000.0,
                        "spot_gold_date": "2026-06-01",
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_d_context.run_id,
                    },
                ]
            ),
            publish_spot_latest_aliases=True,
        )
    _write_options(paths, refresh_run_id=refresh_run_id)
    _publish_option_artifacts(paths)
    if tool_b_source_run_id is not None:
        upsert_company_input(paths, ticker="AEM", values={"net_debt_musd": 201.0})


_PREVIOUSLY_COLLIDED_SOURCE_FIELDS = (
    "down_beta_core",
    "up_beta_core",
    "downside_volatility_52w",
    "confidence_score",
    "aisc_usd_per_oz",
    "debt_to_mktcap",
    "ebitda_to_mktcap",
    "revenue_to_mktcap",
    "fcf_yield",
    "best_upside_pct",
    "market_cap_musd",
)


def _add_stale_option_duplicate_columns(paths) -> None:
    path = option_artifact_latest_path(paths, "candidate_finder_inputs")
    frame = pd.read_parquet(path)
    duplicates = {
        "down_beta_core": -999.0,
        "up_beta_core": -999.0,
        "downside_volatility_52w": -999.0,
        "confidence_score": -999.0,
        "aisc_usd_per_oz": -999.0,
        "market_cap_musd": -999.0,
        "forward_ebitda_musd": -999.0,
        "forward_revenue_musd": -999.0,
        "fcf_yield": -999.0,
        "best_upside_pct": -999.0,
    }
    for column, value in duplicates.items():
        frame[column] = value
    source_run_id = str(frame["source_run_id"].dropna().iloc[0])
    run_stamped_path = option_artifact_run_stamped_path(
        paths,
        "candidate_finder_inputs",
        source_run_id,
    )
    frame.to_parquet(path, index=False)
    frame.to_parquet(run_stamped_path, index=False)
    write_current_model_state_manifest(
        paths=paths,
        config_hash="hash",
        parent_refresh_id="parent-refresh",
    )
    clear_candidate_finder_cache()


def _write_options(paths, *, refresh_run_id: str) -> None:
    snapshot_dir = paths.runs_dir / refresh_run_id / "snapshots" / "options"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_items = []
    for ticker, include_call in (("AEM", True), ("NEM", False)):
        snapshot_path = snapshot_dir / f"{safe_options_file_name(ticker)}.parquet"
        _chain(ticker, include_call=include_call).to_parquet(snapshot_path, index=False)
        snapshot_items.append(
            {
                "ticker": ticker,
                "options_available": True,
                "snapshot_path": snapshot_path.relative_to(paths.repo_root).as_posix(),
            }
        )
        feature = {
            "ticker": ticker,
            "run_id": refresh_run_id,
            "as_of_date": "2026-05-29",
            "optionability_tier": "directly_hedgeable",
            "iv_percentile_cross_sectional": 40.0 if ticker == "AEM" else 60.0,
            "iv_skew_60d": 0.05,
            "underlying_price": 100.0,
        }
        for horizon in (60, 90, 120):
            feature[f"put_iv_25d_{horizon}d"] = 0.4
            feature[f"call_iv_25d_{horizon}d"] = 0.4 if include_call else None
        paths.options_features_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([feature]).to_parquet(
            paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet",
            index=False,
        )
    paths.latest_options_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": refresh_run_id,
                "as_of_date": "2026-05-29",
                "risk_free_rate": 0.04,
                "snapshots": snapshot_items,
            }
        ),
        encoding="utf-8",
    )


def _publish_option_artifacts(paths) -> None:
    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")
    assert exit_code == 0
    write_current_model_state_manifest(
        paths=paths,
        config_hash="hash",
        parent_refresh_id="parent-refresh",
    )


def _chain(ticker: str, *, include_call: bool) -> pd.DataFrame:
    rows = [
        _option(ticker, "P", 95.0, 4.0, 4.4),
        _option(ticker, "P", 90.0, 2.0, 2.3),
    ]
    if include_call:
        rows.append(_option(ticker, "C", 105.0, 4.0, 4.4))
    return pd.DataFrame(rows)


def _option(ticker: str, option_type: str, strike: float, bid: float, ask: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "expiration": date(2026, 7, 17).isoformat(),
        "option_type": option_type,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "mid": (bid + ask) / 2,
        "last_price": (bid + ask) / 2,
        "open_interest": 100,
        "volume": 20,
        "implied_volatility": 0.40,
        "underlying_price": 100.0,
        "days_to_expiry": 49,
        "options_available": True,
    }
