from __future__ import annotations

import json

import pandas as pd
import pytest

from golden_vector.app.model_state import write_current_model_state_manifest
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.option_artifacts import (
    OPTION_ARTIFACT_NAMES,
    option_artifact_latest_path,
    option_artifact_run_stamped_path,
)
from golden_vector.hedge.candidate_puts import OptionCandidate, OptionCandidateSlot
from golden_vector.hedge.option_artifact_builder import OptionArtifactBuildResult
from golden_vector.hedge.option_artifact_frames import build_option_artifact_frames
from golden_vector.hedge.option_trading import (
    OptionTradingOverviewData,
    OptionTradingSourceContext,
)
from golden_vector.ingestion.persist_options import safe_options_file_name
from golden_vector.ingestion.persist_option_artifacts import persist_option_artifact_frames
from golden_vector.cli import run_option_artifacts
from tests.helpers import build_test_paths


def test_option_artifact_frames_preserve_finder_usable_contract():
    tradable = _candidate("AEM", liquidity_tier="tradable")
    watch = _candidate("NEM", liquidity_tier="watch")
    built = OptionArtifactBuildResult(
        overview=OptionTradingOverviewData(rows=(), liquidity_measurements=()),
        candidate_grids={"AEM": [tradable], "NEM": [watch]},
        call_candidate_grids={},
        candidate_slots={
            "AEM": [_slot("AEM", candidate=tradable)],
            "NEM": [_slot("NEM", candidate=watch)],
        },
        call_candidate_slots={},
        liquidity_measurements=(),
        source_context=OptionTradingSourceContext(refresh_run_id="options-run"),
    )

    frames = build_option_artifact_frames(
        built=built,
        contract_metrics=(),
        options_features=pd.DataFrame(
            [
                {"ticker": "AEM", "run_id": "options-run", "unused_noise": 1},
                {"ticker": "NEM", "run_id": "options-run", "unused_noise": 2},
            ]
        ),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-01"},
        source_run_id="20260601T000000Z-option-artifacts",
        parent_refresh_id="parent-refresh",
        config_hash="config-hash",
        risk_free_rate=0.04,
        risk_free_rate_is_fallback=False,
    )

    finder = frames["candidate_finder_inputs"].set_index("ticker")
    selected = frames["option_selected_candidates"]

    assert bool(finder.loc["AEM", "has_usable_put_candidate"]) is True
    assert bool(finder.loc["NEM", "has_usable_put_candidate"]) is False
    assert "unused_noise" not in finder.columns
    assert selected["ticker"].tolist() == ["AEM", "NEM"]
    assert set(selected["liquidity_tier"]) == {"tradable", "watch"}
    assert set(frames) == set(OPTION_ARTIFACT_NAMES)


def test_persist_option_artifact_frames_writes_run_stamped_aliases(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    run_context = RunContext.start(
        paths=paths,
        command="option-artifacts",
        parameters={},
        config_hash="config-hash",
    )
    frames = {
        name: pd.DataFrame(
            [
                {
                    "ticker": "AEM",
                    "schema_version": 1,
                    "snapshot_refresh_run_id": "options-run",
                    "source_run_id": run_context.run_id,
                }
            ]
        )
        for name in OPTION_ARTIFACT_NAMES
    }

    written = persist_option_artifact_frames(
        paths=paths,
        run_context=run_context,
        frames=frames,
    )

    for artifact_name in OPTION_ARTIFACT_NAMES:
        assert option_artifact_latest_path(paths, artifact_name).exists()
        assert option_artifact_run_stamped_path(
            paths,
            artifact_name,
            run_context.run_id,
        ).exists()
    assert len(written) == len(OPTION_ARTIFACT_NAMES) * 3


def test_persist_option_artifact_frames_rejects_incomplete_artifact_set(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    run_context = RunContext.start(
        paths=paths,
        command="option-artifacts",
        parameters={},
        config_hash="config-hash",
    )

    with pytest.raises(ValueError, match="Missing option artifact frame"):
        persist_option_artifact_frames(
            paths=paths,
            run_context=run_context,
            frames={},
        )


def test_run_option_artifacts_writes_manifest_addressable_outputs(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    snapshot_dir = paths.runs_dir / "options-run" / "snapshots" / "options"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_items = []
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    for ticker in ("GDX", "GDXJ"):
        snapshot_path = snapshot_dir / f"{safe_options_file_name(ticker)}.parquet"
        _benchmark_chain(ticker).to_parquet(snapshot_path, index=False)
        snapshot_items.append(
            {
                "ticker": ticker,
                "options_available": True,
                "snapshot_path": snapshot_path.relative_to(paths.repo_root).as_posix(),
            }
        )
        _benchmark_feature(ticker).to_parquet(
            paths.options_features_dir / f"{safe_options_file_name(ticker)}.parquet",
            index=False,
        )
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "options-run",
                "as_of_date": "2026-06-01",
                "risk_free_rate": 0.04,
                "snapshots": snapshot_items,
                "summary": {"options_phase_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )

    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")
    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-refresh",
    )

    assert exit_code == 0
    for artifact_name in OPTION_ARTIFACT_NAMES:
        assert option_artifact_latest_path(paths, artifact_name).exists()
        assert payload["artifacts"][artifact_name]["immutable"] is True


def test_run_option_artifacts_refuses_empty_benchmark_signal_area(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "options-run",
                "as_of_date": "2026-06-01",
                "risk_free_rate": 0.04,
                "snapshots": [],
                "summary": {"options_phase_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )

    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")

    assert exit_code == 1


def test_run_option_artifacts_fails_on_corrupt_manifest_chain_snapshot(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    snapshot_path = paths.runs_dir / "options-run" / "snapshots" / "options" / "AEM.parquet"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text("not parquet", encoding="utf-8")
    paths.options_features_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{"ticker": "AEM", "run_id": "options-run"}]).to_parquet(
        paths.options_features_dir / "AEM.parquet",
        index=False,
    )
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "options-run",
                "as_of_date": "2026-06-01",
                "risk_free_rate": 0.04,
                "snapshots": [
                    {
                        "ticker": "AEM",
                        "options_available": True,
                        "snapshot_path": snapshot_path.relative_to(
                            paths.repo_root
                        ).as_posix(),
                    }
                ],
                "summary": {"options_phase_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )

    exit_code = run_option_artifacts(paths, parent_refresh_id="parent-refresh")

    assert exit_code == 1
    for artifact_name in OPTION_ARTIFACT_NAMES:
        assert not option_artifact_latest_path(paths, artifact_name).exists()


def _candidate(ticker: str, *, liquidity_tier: str) -> OptionCandidate:
    return OptionCandidate(
        ticker=ticker,
        horizon_days=60,
        expiration="2026-07-17",
        days_to_expiry=42,
        strike=95.0,
        bid=3.0,
        ask=3.2,
        mid=3.1,
        open_interest=100,
        volume=5,
        implied_volatility=0.4,
        delta=-0.30,
        delta_gap=0.05,
        premium_pct_spot=0.031,
        underlying_price=100.0,
        option_type="P",
        bucket="near_atm",
        liquidity_tier=liquidity_tier,
    )


def _slot(ticker: str, *, candidate: OptionCandidate) -> OptionCandidateSlot:
    return OptionCandidateSlot(
        ticker=ticker,
        option_type="P",
        horizon_days=60,
        target_delta=-0.25,
        expiration=candidate.expiration,
        days_to_expiry=candidate.days_to_expiry,
        status="accepted",
        reason="Selected.",
        candidate=candidate,
        bucket="near_atm",
        liquidity_tier=candidate.liquidity_tier,
    )


def _benchmark_feature(ticker: str) -> pd.DataFrame:
    row: dict[str, object] = {
        "ticker": ticker,
        "run_id": "options-run",
        "as_of_date": "2026-06-01",
        "optionability_tier": "directly_hedgeable",
        "iv_percentile_cross_sectional": 50.0,
        "underlying_price": 100.0,
        "option_vehicle_type": "benchmark_etf",
        "options_source_symbol": ticker,
    }
    for horizon in (60, 90, 120):
        row[f"put_iv_25d_{horizon}d"] = 0.45
        row[f"call_iv_25d_{horizon}d"] = 0.40
        row[f"iv_skew_{horizon}d"] = 0.05
        row[f"iv_rv_ratio_{horizon}d"] = 1.2
    return pd.DataFrame([row])


def _benchmark_chain(ticker: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _option(ticker, "P", 95.0, 4.0, 4.4),
            _option(ticker, "P", 90.0, 2.0, 2.3),
            _option(ticker, "C", 105.0, 4.0, 4.4),
            _option(ticker, "C", 110.0, 2.0, 2.3),
            _option(ticker, "C", 115.0, 1.3, 1.5),
        ]
    )


def _option(
    ticker: str,
    option_type: str,
    strike: float,
    bid: float,
    ask: float,
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "expiration": "2026-07-17",
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
        "days_to_expiry": 46,
        "options_available": True,
    }
