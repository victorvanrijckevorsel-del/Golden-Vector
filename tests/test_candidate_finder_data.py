from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from golden_vector.app.config import load_app_config
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    resolve_current_model_artifact_path,
    write_current_model_state_manifest,
)
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
from golden_vector.model.candidate_finder import (
    CriterionDefinition,
    CriterionSelection,
    rank_candidates,
)
from golden_vector.model.tool_d import TOOL_D_OUTPUT_COLUMNS
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from golden_vector.screening.manual_store import upsert_company_input
from golden_vector.screening.schema import TOOL_B_OUTPUT_COLUMNS
from golden_vector.contracts.config_models import (
    CandidateFinderConfig,
    CandidateFinderCriterion,
)
from golden_vector.serve.candidate_finder_data import (
    CandidateFinderScenario,
    CandidateFinderScenarioError,
    CandidateFinderSourceError,
    TOOL_D_FINDER_FIELDS,
    _criteria_config_for_beta_window,
    candidate_finder_result_frame,
    clear_candidate_finder_cache,
    load_candidate_finder_data,
    parse_candidate_finder_scenario,
    run_candidate_finder_screen,
    _joined_frame,
)
from golden_vector.serve.option_trading_data import OptionTradingData
from tests.helpers import build_test_paths, tool_b_output_row


def test_candidate_finder_data_joins_sources_and_persisted_fundamentals(tmp_path):
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
    assert frame.loc["AEM", "fundamental_check_score"] == pytest.approx(85.7143)
    assert frame.loc["AEM", "margin_pct"] == pytest.approx(0.575)
    assert frame.loc["AEM", "ev_ebitda"] == pytest.approx(2.4)
    assert frame.loc["AEM", "forward_pe"] == pytest.approx(8.0)
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
    assert frame.loc["AEM", "fundamental_check_score"] == pytest.approx(85.7143)
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
    bearish = run_candidate_finder_screen(data, spec={"preset": "bear"})
    bullish = run_candidate_finder_screen(data, spec={"preset": "bull"})
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


def test_candidate_finder_excludes_score_ineligible_rows_from_all_rankings():
    frame = pd.DataFrame(
        [
            {"ticker": "DEG", "score_eligible": False, "ev_ebitda": 1.0},
            {"ticker": "OK", "score_eligible": True, "ev_ebitda": 2.0},
        ]
    )
    criteria = [
        CriterionDefinition(
            id="ev_ebitda",
            label="EV/EBITDA",
            description="Enterprise value over EBITDA.",
            source_field="ev_ebitda",
            group="Corporate Finance",
            default_direction="low_good",
        )
    ]

    result = rank_candidates(
        frame,
        criteria=criteria,
        selections=[CriterionSelection(id="ev_ebitda")],
        min_criteria_fraction=1.0,
        top_n=10,
    )

    by_ticker = {row.ticker: row for row in result.rows}
    assert by_ticker["DEG"].source_score_eligible is False
    assert by_ticker["DEG"].rank_eligible is False
    assert by_ticker["DEG"].rank is None
    assert by_ticker["DEG"].score is None
    assert by_ticker["OK"].rank == 1
    assert [entry.ticker for entry in result.top_lists["ev_ebitda"]] == ["OK"]


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
    assert "aisc_usd_per_oz" in data.frame.columns
    assert data.frame["aisc_usd_per_oz"].isna().all()
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
    assert data.frame["interest_cover_gold_usd"].isna().all()


def test_candidate_finder_tool_d_guard_fields_match_configured_tool_d_only_fields():
    app_config = load_app_config(ProjectPaths.discover()).app
    tool_d_only_fields = set(TOOL_D_OUTPUT_COLUMNS) - set(TOOL_B_OUTPUT_COLUMNS)
    configured_tool_d_fields = {
        criterion.source_field
        for criterion in app_config.candidate_finder.criteria
        if criterion.source_field in tool_d_only_fields
    }

    assert TOOL_D_FINDER_FIELDS == configured_tool_d_fields


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
    assert frame.loc["AEM", "interest_cover_gold_usd"] == pytest.approx(1500.0)


def test_candidate_finder_data_blanks_non_spot_tool_d_finder_fields_without_spot_alias(
    tmp_path,
):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    paths.latest_model_state_manifest_path.unlink()
    paths.latest_tool_d_spot_snapshot_parquet_path.unlink()
    non_spot = pd.read_parquet(paths.latest_tool_d_snapshot_parquet_path)
    non_spot["gold_price_used"] = 3500.0
    non_spot["spot_gold_usd"] = 4000.0
    non_spot.to_parquet(paths.latest_tool_d_snapshot_parquet_path, index=False)

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status in {"WARN", "UNKNOWN"}
    assert any("Corporate Resilience criteria as missing" in item for item in data.alignment.messages)
    for column in TOOL_D_FINDER_FIELDS:
        assert data.frame[column].isna().all(), column


def test_candidate_finder_data_blanks_non_spot_tool_b_gold_fields_without_manifest(
    tmp_path,
):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    paths.latest_model_state_manifest_path.unlink()
    non_spot = pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path)
    non_spot["gold_price_used"] = 3500.0
    non_spot["spot_gold_usd"] = 4000.0
    non_spot["gold_price_basis"] = "custom_scenario"
    non_spot.to_parquet(paths.latest_tool_b_snapshot_parquet_path, index=False)

    data = load_candidate_finder_data(paths, app_config=app_config)

    assert data.alignment.status in {"WARN", "UNKNOWN"}
    assert any("Corporate Finance criteria as missing" in item for item in data.alignment.messages)
    for column in ("ev_ebitda", "forward_pe", "fcf_yield", "margin_pct"):
        assert data.frame[column].isna().all(), column
    assert data.frame["aisc_usd_per_oz"].notna().any()
    assert data.frame["leverage"].notna().any()


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
    scenario["interest_cover_gold_usd"] = 9999.0
    scenario.to_parquet(paths.latest_tool_d_snapshot_parquet_path, index=False)

    data = load_candidate_finder_data(paths, app_config=app_config)

    frame = data.frame.set_index("ticker")
    assert data.alignment.status == "OK"
    assert frame.loc["AEM", "tool_d_quality_rank"] == pytest.approx(45.0)
    assert frame.loc["NEM", "tool_d_quality_rank"] == pytest.approx(80.0)
    assert frame.loc["AEM", "interest_cover_gold_usd"] == pytest.approx(1500.0)


def test_candidate_finder_scenario_injects_in_memory_tool_b_and_tool_d_without_writes(
    tmp_path,
    monkeypatch,
):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    persisted_tool_b = pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path)
    persisted_tool_d = pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path)

    def fake_foundation_snapshot(**_kwargs):
        return SimpleNamespace(
            gold_history=pd.DataFrame(
                [{"date": "2026-06-01", "close_usd": 4000.0}]
            ),
            normalized_market_snapshots=pd.DataFrame(),
            refresh_run_id="fresh-foundation",
            snapshot_as_of_date="2026-06-01",
        )

    def fake_manual_data(_paths, *, tickers):
        return SimpleNamespace(company_inputs=pd.DataFrame({"ticker": list(tickers)}))

    def fake_tool_b(**kwargs):
        gold_price = float(kwargs["gold_price_assumption"])
        basis = str(kwargs["gold_price_basis"])
        return pd.DataFrame(
            [
                tool_b_output_row(
                    "AEM",
                    gold_price_assumption=gold_price,
                    gold_price_used=gold_price,
                    spot_gold_usd=4000.0,
                    spot_gold_date="2026-06-01",
                    gold_price_basis=basis,
                    ev_ebitda=9.9,
                    forward_pe=18.0,
                    fcf_yield=0.02,
                    margin_pct=0.42,
                    snapshot_refresh_run_id="fresh-foundation",
                    source_run_id="candidate-finder-scenario",
                ),
                tool_b_output_row(
                    "NEM",
                    gold_price_assumption=gold_price,
                    gold_price_used=gold_price,
                    spot_gold_usd=4000.0,
                    spot_gold_date="2026-06-01",
                    gold_price_basis=basis,
                    ev_ebitda=7.7,
                    forward_pe=16.0,
                    fcf_yield=0.03,
                    margin_pct=0.44,
                    snapshot_refresh_run_id="fresh-foundation",
                    source_run_id="candidate-finder-scenario",
                ),
            ]
        )

    def fake_tool_d(**kwargs):
        gold_price = float(kwargs["gold_price"])
        return pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "tool_d_quality_rank": 12.0,
                    "interest_cover_gold_usd": 2100.0,
                    "debt_stress_gold_usd": 2050.0,
                    "fcf_breakeven_gold_usd": 2200.0,
                    "cost_curve_aisc_percentile": 55.0,
                    "gold_price_used": gold_price,
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "snapshot_refresh_run_id": "fresh-foundation",
                    "source_run_id": "candidate-finder-scenario",
                },
                {
                    "ticker": "NEM",
                    "tool_d_quality_rank": 34.0,
                    "interest_cover_gold_usd": 1900.0,
                    "debt_stress_gold_usd": 1850.0,
                    "fcf_breakeven_gold_usd": 2000.0,
                    "cost_curve_aisc_percentile": 35.0,
                    "gold_price_used": gold_price,
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "snapshot_refresh_run_id": "fresh-foundation",
                    "source_run_id": "candidate-finder-scenario",
                },
            ]
        )

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_latest_foundation_snapshot",
        fake_foundation_snapshot,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.resolve_current_foundation_manifest_path",
        lambda _paths, *, require_current_manifest: None,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_manual_screening_data",
        fake_manual_data,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_b_in_memory",
        fake_tool_b,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_d_outputs",
        fake_tool_d,
    )

    data = load_candidate_finder_data(
        paths,
        app_config=app_config,
        scenario=CandidateFinderScenario.from_value(3500.0),
    )
    frame = data.frame.set_index("ticker")
    screen = run_candidate_finder_screen(data, spec={"preset": "bull"})
    result = candidate_finder_result_frame(screen)

    assert data.scenario_active is True
    assert data.gold_price_used == pytest.approx(3500.0)
    assert data.spot_gold_usd == pytest.approx(4000.0)
    assert data.source_basis == "custom_scenario"
    assert data.rank_basis == "custom_gold_scenario"
    assert frame.loc["AEM", "ev_ebitda"] == pytest.approx(9.9)
    assert frame.loc["AEM", "tool_d_quality_rank"] == pytest.approx(12.0)
    assert result["gold_price_used"].dropna().eq(3500.0).all()
    assert result["rank_basis"].dropna().eq("custom_gold_scenario").all()
    pd.testing.assert_frame_equal(
        pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path),
        persisted_tool_b,
    )
    pd.testing.assert_frame_equal(
        pd.read_parquet(paths.latest_tool_d_spot_snapshot_parquet_path),
        persisted_tool_d,
    )


def test_candidate_finder_yahoo_source_recomputes_tool_b_and_tool_d_at_spot(
    tmp_path,
    monkeypatch,
):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_latest_foundation_snapshot",
        lambda **_kwargs: SimpleNamespace(
            gold_history=pd.DataFrame([{"date": "2026-06-01", "close_usd": 4000.0}]),
            normalized_market_snapshots=pd.DataFrame(),
            refresh_run_id="fresh-foundation",
            snapshot_as_of_date="2026-06-01",
        ),
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.resolve_current_foundation_manifest_path",
        lambda _paths, *, require_current_manifest: None,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_manual_screening_data",
        lambda _paths, *, tickers: SimpleNamespace(
            company_inputs=pd.DataFrame({"ticker": list(tickers)})
        ),
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_official_fundamentals",
        lambda _paths: pd.DataFrame({"ticker": ["AEM"]}),
    )

    def fake_tool_b(**kwargs):
        captured["tool_b_finance_source"] = kwargs["finance_source"]
        gold_price = float(kwargs["gold_price_assumption"])
        row = tool_b_output_row(
            "AEM",
            gold_price_assumption=gold_price,
            gold_price_used=gold_price,
            spot_gold_usd=4000.0,
            spot_gold_date="2026-06-01",
            gold_price_basis=str(kwargs["gold_price_basis"]),
            snapshot_refresh_run_id="fresh-foundation",
            source_run_id="candidate-finder-scenario",
        )
        row["finance_source"] = kwargs["finance_source"]
        return pd.DataFrame([row])

    def fake_tool_d(**kwargs):
        captured["tool_d_finance_source"] = kwargs["inputs"].finance_source
        return pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "tool_d_quality_rank": 12.0,
                    "interest_cover_gold_usd": 2100.0,
                    "debt_stress_gold_usd": 2050.0,
                    "fcf_breakeven_gold_usd": 2200.0,
                    "cost_curve_aisc_percentile": 55.0,
                    "gold_price_used": float(kwargs["gold_price"]),
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "snapshot_refresh_run_id": "fresh-foundation",
                    "source_run_id": "candidate-finder-scenario",
                    "finance_source": kwargs["inputs"].finance_source,
                }
            ]
        )

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_b_in_memory",
        fake_tool_b,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_d_outputs",
        fake_tool_d,
    )

    data = load_candidate_finder_data(
        paths,
        app_config=app_config,
        fundamentals_source="yahoo",
    )

    assert data.scenario_active is True
    assert data.scenario_requested_gold_price is None
    assert data.fundamentals_source == "yahoo"
    assert data.gold_price_used == pytest.approx(4000.0)
    assert data.rank_basis == "latest_daily_gold_close_yahoo_fundamentals"
    assert captured == {
        "tool_b_finance_source": "yahoo",
        "tool_d_finance_source": "yahoo",
    }
    row = data.frame.set_index("ticker").loc["AEM"]
    assert row["gold_price_used"] == pytest.approx(4000.0)
    assert row["tool_d_quality_rank"] == pytest.approx(12.0)
    assert row["interest_cover_gold_usd"] == pytest.approx(2100.0)


def test_candidate_finder_yahoo_source_failure_does_not_fallback_to_our_view(
    tmp_path,
    monkeypatch,
):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_latest_foundation_snapshot",
        lambda **_kwargs: SimpleNamespace(
            gold_history=pd.DataFrame([{"date": "2026-06-01", "close_usd": 4000.0}]),
            normalized_market_snapshots=pd.DataFrame(),
            refresh_run_id="fresh-foundation",
            snapshot_as_of_date="2026-06-01",
        ),
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.resolve_current_foundation_manifest_path",
        lambda _paths, *, require_current_manifest: None,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_manual_screening_data",
        lambda _paths, *, tickers: SimpleNamespace(
            company_inputs=pd.DataFrame({"ticker": list(tickers)})
        ),
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_b_in_memory",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("official artifact corrupt")),
    )

    with pytest.raises(
        CandidateFinderSourceError,
        match="Yahoo Fundamentals view",
    ):
        load_candidate_finder_data(
            paths,
            app_config=app_config,
            fundamentals_source="yahoo",
        )


def test_candidate_finder_scenario_cache_is_keyed_by_gold_price(tmp_path, monkeypatch):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    calls = {"tool_b": 0, "tool_d": 0}
    foundation_manifest = tmp_path / "foundation-manifest.json"
    foundation_manifest.write_text("v1", encoding="utf-8")

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_latest_foundation_snapshot",
        lambda **_kwargs: SimpleNamespace(
            gold_history=pd.DataFrame([{"date": "2026-06-01", "close_usd": 4000.0}]),
            normalized_market_snapshots=pd.DataFrame(),
            refresh_run_id="fresh-foundation",
            snapshot_as_of_date="2026-06-01",
        ),
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.resolve_current_foundation_manifest_path",
        lambda _paths, *, require_current_manifest: foundation_manifest,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_manual_screening_data",
        lambda _paths, *, tickers: SimpleNamespace(
            company_inputs=pd.DataFrame({"ticker": list(tickers)})
        ),
    )

    def fake_tool_b(**kwargs):
        calls["tool_b"] += 1
        return pd.DataFrame(
            [
                tool_b_output_row(
                    "AEM",
                    gold_price_assumption=float(kwargs["gold_price_assumption"]),
                    gold_price_used=float(kwargs["gold_price_assumption"]),
                    spot_gold_usd=4000.0,
                    gold_price_basis=str(kwargs["gold_price_basis"]),
                    snapshot_refresh_run_id="fresh-foundation",
                    source_run_id="candidate-finder-scenario",
                )
            ]
        )

    def fake_tool_d(**kwargs):
        calls["tool_d"] += 1
        return pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "tool_d_quality_rank": 20.0,
                    "interest_cover_gold_usd": 1500.0,
                    "debt_stress_gold_usd": 1300.0,
                    "fcf_breakeven_gold_usd": 1700.0,
                    "cost_curve_aisc_percentile": 40.0,
                    "gold_price_used": float(kwargs["gold_price"]),
                    "spot_gold_usd": 4000.0,
                    "snapshot_refresh_run_id": "fresh-foundation",
                    "source_run_id": "candidate-finder-scenario",
                }
            ]
        )

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_b_in_memory",
        fake_tool_b,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_d_outputs",
        fake_tool_d,
    )

    first = load_candidate_finder_data(
        paths,
        app_config=app_config,
        scenario=CandidateFinderScenario.from_value(3500.0),
    )
    second = load_candidate_finder_data(
        paths,
        app_config=app_config,
        scenario=CandidateFinderScenario.from_value(3500.0),
    )
    foundation_manifest.write_text("v2", encoding="utf-8")
    third = load_candidate_finder_data(
        paths,
        app_config=app_config,
        scenario=CandidateFinderScenario.from_value(3500.0),
    )
    fourth = load_candidate_finder_data(
        paths,
        app_config=app_config,
        scenario=CandidateFinderScenario.from_value(3600.0),
    )

    assert first is second
    assert third is not first
    assert fourth is not third
    assert calls == {"tool_b": 3, "tool_d": 3}


def test_parse_candidate_finder_scenario_rejects_nonfinite_gold_price():
    with pytest.raises(CandidateFinderScenarioError):
        parse_candidate_finder_scenario({"gold_price": ["nan"]})


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
    screen = run_candidate_finder_screen(data, spec={"preset": "bear"})

    assert data.alignment.status == "OK"
    assert not any("Gold Sensitivity latest parquet could not be read" in item for item in screen.warnings)


def test_candidate_finder_fails_loud_on_corrupt_manifest_resolved_source(tmp_path):
    # A corrupt MANIFEST-resolved current artifact (not just a stray alias) must fail
    # loud, never silently render a sparse ranking missing a whole dimension (M7).
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    resolved = resolve_current_model_artifact_path(paths, "tool_a")
    assert resolved is not None  # the manifest points at a real current Tool A artifact
    resolved.write_text("not parquet", encoding="utf-8")

    with pytest.raises(CandidateFinderSourceError, match="could not be read"):
        load_candidate_finder_data(paths, app_config=app_config)


def test_candidate_finder_fails_loud_on_manifest_source_missing_columns(tmp_path):
    # A manifest-resolved current artifact that READS fine but is missing its core
    # ranking columns must ALSO fail loud, not silently drop a whole dimension to
    # all-null behind a warning (Codex options-UI review; extends M7 beyond Tool B).
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    resolved = resolve_current_model_artifact_path(paths, "tool_c")
    assert resolved is not None  # the manifest points at a real current Tool C artifact
    # Readable parquet, but ticker-only: the Tool C rank columns are gone.
    pd.DataFrame({"ticker": ["NEM", "AEM"]}).to_parquet(resolved, index=False)

    with pytest.raises(CandidateFinderSourceError, match="missing required ranking columns"):
        load_candidate_finder_data(paths, app_config=app_config)


def test_candidate_finder_fails_loud_on_manifest_source_missing_ticker(tmp_path):
    # The join key matters too: a current artifact WITH ranking columns but no
    # `ticker` would collapse to an empty ticker-only frame in _prepare_source and
    # silently drop the whole dimension. It must 503 instead (Codex re-review).
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    resolved = resolve_current_model_artifact_path(paths, "tool_c")
    assert resolved is not None
    # Readable parquet with the rank columns but the join key (ticker) dropped.
    pd.DataFrame(
        {"tool_c_downside_rank": [10.0, 20.0], "tool_c_upside_rank": [30.0, 40.0]}
    ).to_parquet(resolved, index=False)

    with pytest.raises(CandidateFinderSourceError, match="missing required ranking columns"):
        load_candidate_finder_data(paths, app_config=app_config)


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
  - id: leverage
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
    assert "percentile_leverage" in ranked.columns


def test_candidate_finder_cli_allows_output_outside_repo(tmp_path, capsys):
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    spec_path = tmp_path / "screen.yaml"
    output_path = tmp_path.parent / "candidate_finder_external.parquet"
    spec_path.write_text("preset: bear\noptions_side: puts\n", encoding="utf-8")

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
                tool_b_output_row(
                    "AEM",
                    market_cap_musd=1000.0,
                    share_price_usd=100.0,
                    net_debt_musd=200.0,
                    aisc_usd_per_oz=1700.0,
                    enterprise_value_musd=1200.0,
                    forward_revenue_musd=1200.0,
                    forward_ebitda_musd=500.0,
                    forward_net_income_musd=300.0,
                    forward_pe=8.0,
                    ev_ebitda=2.4,
                    fcf_yield=0.18,
                    leverage=0.4,
                    fundamental_check_score=85.7143,
                    fundamental_check_rank=1,
                    snapshot_refresh_run_id=tool_b_run,
                    source_run_id=tool_b_context.run_id,
                ),
                tool_b_output_row(
                    "NEM",
                    market_cap_musd=2000.0,
                    share_price_usd=100.0,
                    net_debt_musd=100.0,
                    aisc_usd_per_oz=1500.0,
                    enterprise_value_musd=2100.0,
                    forward_revenue_musd=1600.0,
                    forward_ebitda_musd=600.0,
                    forward_net_income_musd=260.0,
                    forward_pe=10.0,
                    ev_ebitda=3.5,
                    fcf_yield=0.12,
                    leverage=0.2,
                    fundamental_check_score=71.4286,
                    fundamental_check_rank=2,
                    snapshot_refresh_run_id=tool_b_run,
                    source_run_id=tool_b_context.run_id,
                ),
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
                        "finance_source": "our",
                        "tool_d_quality_rank": 45.0,
                        "interest_cover_gold_usd": 1500.0,
                        "debt_stress_gold_usd": 1300.0,
                        "fcf_breakeven_gold_usd": 1700.0,
                        "cost_curve_aisc_percentile": 40.0,
                        "gold_price_used": 4000.0,
                        "spot_gold_usd": 4000.0,
                        "spot_gold_date": "2026-06-01",
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_d_context.run_id,
                    },
                    {
                        "ticker": "NEM",
                        "finance_source": "our",
                        "tool_d_quality_rank": 80.0,
                        "interest_cover_gold_usd": 1200.0,
                        "debt_stress_gold_usd": 1100.0,
                        "fcf_breakeven_gold_usd": 1400.0,
                        "cost_curve_aisc_percentile": 20.0,
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
    "leverage",
    "ev_ebitda",
    "margin_pct",
    "fcf_yield",
    "fundamental_check_score",
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
        "fundamental_check_score": -999.0,
        "margin_pct": -999.0,
        "ev_ebitda": -999.0,
        "leverage": -999.0,
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
    for ticker, include_call in (
        ("AEM", True),
        ("NEM", False),
        ("GDX", True),
        ("GDXJ", True),
    ):
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

            "underlying_price": 100.0,
            "option_vehicle_type": (
                "benchmark_etf" if ticker in {"GDX", "GDXJ"} else "single_stock"
            ),
        }
        for horizon in (90, 180, 230, 550):
            feature[f"put_iv_25d_{horizon}d"] = 0.4
            feature[f"call_iv_25d_{horizon}d"] = 0.4 if include_call else None
            feature[f"iv_skew_{horizon}d"] = 0.05
            feature[f"iv_rv_ratio_{horizon}d"] = 1.2
            feature[f"atm_iv_{horizon}d"] = 0.4
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
        _option(ticker, "P", 85.0, 1.2, 1.4),
        _option(ticker, "P", 80.0, 0.8, 1.0),
    ]
    if include_call:
        rows.append(_option(ticker, "C", 105.0, 4.0, 4.4))
        rows.append(_option(ticker, "C", 110.0, 2.0, 2.3))
        rows.append(_option(ticker, "C", 115.0, 1.3, 1.5))
    return pd.DataFrame(rows)


def _option(ticker: str, option_type: str, strike: float, bid: float, ask: float) -> dict[str, object]:
    return {
        "ticker": ticker,
        "expiration": date(2026, 8, 29).isoformat(),
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
        "days_to_expiry": 92,
        "options_available": True,
    }


def test_candidate_finder_scenario_threads_official_fundamentals(tmp_path, monkeypatch):
    """Merge-verification HIGH: the scenario recompute must use the same
    official-fundamentals inputs as the persisted Tool B pipeline and the
    Tool B gold dial, or a scenario at spot silently disagrees with the
    default screen for official-only tickers."""

    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")
    sentinel_officials = pd.DataFrame(
        [{"ticker": "AEM", "net_debt_musd": 123.0, "value_status": "OK"}]
    )
    captured: dict[str, object] = {}

    def fake_foundation_snapshot(**_kwargs):
        return SimpleNamespace(
            gold_history=pd.DataFrame([{"date": "2026-06-01", "close_usd": 4000.0}]),
            normalized_market_snapshots=pd.DataFrame(),
            refresh_run_id="fresh-foundation",
            snapshot_as_of_date="2026-06-01",
        )

    def fake_tool_b(**kwargs):
        captured["official_fundamentals"] = kwargs.get("official_fundamentals")
        gold_price = float(kwargs["gold_price_assumption"])
        return pd.DataFrame(
            [
                tool_b_output_row(
                    "AEM",
                    gold_price_assumption=gold_price,
                    gold_price_used=gold_price,
                    spot_gold_usd=4000.0,
                    spot_gold_date="2026-06-01",
                    gold_price_basis=str(kwargs["gold_price_basis"]),
                    snapshot_refresh_run_id="fresh-foundation",
                    source_run_id="candidate-finder-scenario",
                )
            ]
        )

    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_latest_foundation_snapshot",
        fake_foundation_snapshot,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.resolve_current_foundation_manifest_path",
        lambda _paths, *, require_current_manifest: None,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_manual_screening_data",
        lambda _paths, *, tickers: SimpleNamespace(
            company_inputs=pd.DataFrame({"ticker": list(tickers)})
        ),
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.load_official_fundamentals",
        lambda _paths: sentinel_officials,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_b_in_memory",
        fake_tool_b,
    )
    monkeypatch.setattr(
        "golden_vector.serve.candidate_finder_data.compute_tool_d_outputs",
        lambda **kwargs: pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "tool_d_quality_rank": 12.0,
                    "gold_price_used": float(kwargs["gold_price"]),
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "snapshot_refresh_run_id": "fresh-foundation",
                    "source_run_id": "candidate-finder-scenario",
                }
            ]
        ),
    )

    data = load_candidate_finder_data(
        paths,
        app_config=app_config,
        scenario=CandidateFinderScenario.from_value(3500.0),
    )

    assert data.scenario_active is True
    passed = captured.get("official_fundamentals")
    assert passed is not None, (
        "scenario compute_tool_b_in_memory must receive official_fundamentals"
    )
    pd.testing.assert_frame_equal(passed, sentinel_officials)


def _beta_window_test_config() -> CandidateFinderConfig:
    def crit(cid: str, source: str) -> CandidateFinderCriterion:
        return CandidateFinderCriterion(
            id=cid,
            label=cid,
            description=cid,
            source_field=source,
            group="Gold Sensitivity",
            default_direction="high_good",
            unit="beta",
        )

    return CandidateFinderConfig(
        version=1,
        default_top_n=10,
        min_criteria_fraction=0.67,
        criteria=[
            crit("up_beta", "up_beta_core"),
            crit("down_beta", "down_beta_core"),
            crit("gold_beta_core", "structural_delta_core"),
            crit("confidence", "confidence_score"),
        ],
        presets=[],
    )


def test_criteria_config_for_beta_window_remaps_only_per_window_betas():
    # Selecting a window repoints the *_core beta/delta criteria to that window's columns,
    # and leaves non-window criteria (confidence) untouched.
    config = _beta_window_test_config()
    frame = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "up_beta_core": 2.0,
                "up_beta_6m": 1.3,
                "down_beta_core": 1.8,
                "down_beta_6m": 1.1,
                "structural_delta_core": 1.5,
                "structural_delta_6m": 0.9,
                "confidence_score": 0.9,
            }
        ]
    )

    remapped = _criteria_config_for_beta_window(config, "6M", frame)

    by_id = {c.id: c.source_field for c in remapped.criteria}
    assert by_id["up_beta"] == "up_beta_6m"
    assert by_id["down_beta"] == "down_beta_6m"
    assert by_id["gold_beta_core"] == "structural_delta_6m"
    assert by_id["confidence"] == "confidence_score"


def test_criteria_config_for_beta_window_blend_returns_identity():
    # The blend (None) must be a no-op so default rankings never silently change.
    config = _beta_window_test_config()
    frame = pd.DataFrame([{"ticker": "AEM", "up_beta_core": 2.0}])

    assert _criteria_config_for_beta_window(config, None, frame) is config


def test_criteria_config_for_beta_window_degrades_when_per_window_column_absent():
    # If a per-window column is missing, the criterion keeps its blend column (degrade per item).
    config = _beta_window_test_config()
    frame = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "up_beta_core": 2.0,
                "down_beta_core": 1.8,
                "structural_delta_core": 1.5,
                "confidence_score": 0.9,
            }
        ]
    )

    remapped = _criteria_config_for_beta_window(config, "2Y", frame)

    by_id = {c.id: c.source_field for c in remapped.criteria}
    assert by_id["up_beta"] == "up_beta_core"
    assert by_id["down_beta"] == "down_beta_core"
    assert by_id["gold_beta_core"] == "structural_delta_core"


def test_criteria_config_for_beta_window_degrades_per_item_in_mixed_frame():
    # Forces the changed=True branch with ONE per-window column present and TWO absent, proving
    # per-ITEM degradation (the all-absent test only exercises the no-op shortcut).
    config = _beta_window_test_config()
    frame = pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "up_beta_core": 2.0,
                "up_beta_6m": 1.3,  # only up_beta has a 6M column
                "down_beta_core": 1.8,
                "structural_delta_core": 1.5,
                "confidence_score": 0.9,
            }
        ]
    )

    remapped = _criteria_config_for_beta_window(config, "6M", frame)

    by_id = {c.id: c.source_field for c in remapped.criteria}
    assert by_id["up_beta"] == "up_beta_6m"  # remapped (column present)
    assert by_id["down_beta"] == "down_beta_core"  # degrades (column absent)
    assert by_id["gold_beta_core"] == "structural_delta_core"  # degrades
    assert by_id["confidence"] == "confidence_score"


def test_candidate_finder_cache_key_isolates_beta_window(tmp_path):
    # Regression: a per-window selection must not collide with the blend in the cache (else
    # picking a window could serve the blend's cached ranking). beta_window is part of the key
    # and is normalized via the registry.
    clear_candidate_finder_cache()
    paths = build_test_paths(tmp_path)
    app_config = load_app_config(paths).app
    _write_candidate_finder_inputs(paths, refresh_run_id="refresh-run")

    blend = load_candidate_finder_data(paths, app_config=app_config)
    window = load_candidate_finder_data(paths, app_config=app_config, beta_window="6m")

    assert blend.beta_window is None
    assert window.beta_window == "6M"
    assert blend.cache_key.beta_window == "core"
    assert window.cache_key.beta_window == "6M"
    assert blend.cache_key != window.cache_key
