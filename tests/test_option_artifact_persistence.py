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


def test_tool_refresh_run_id_uses_snapshot_only_and_marks_mixed():
    from golden_vector.hedge.option_artifact_frames import tool_refresh_run_id

    assert tool_refresh_run_id(None) == ""
    assert tool_refresh_run_id(pd.DataFrame()) == ""
    # One distinct foundation refresh id across rows -> that id (source_run_id ignored).
    assert (
        tool_refresh_run_id(
            pd.DataFrame(
                [
                    {"snapshot_refresh_run_id": "snap-1", "source_run_id": "src-1"},
                    {"snapshot_refresh_run_id": "snap-1", "source_run_id": "src-2"},
                ]
            )
        )
        == "snap-1"
    )
    # NO source_run_id fallback: a tool run id is the wrong semantics, so report unknown.
    assert tool_refresh_run_id(pd.DataFrame([{"source_run_id": "src-1"}])) == ""
    # Genuinely mixed inputs are surfaced, not hidden behind the first value.
    assert (
        tool_refresh_run_id(
            pd.DataFrame(
                [{"snapshot_refresh_run_id": "snap-2"}, {"snapshot_refresh_run_id": "snap-1"}]
            )
        )
        == "mixed:snap-1,snap-2"
    )
    assert tool_refresh_run_id(pd.DataFrame([{"ticker": "X"}])) == ""


def test_build_option_artifact_frames_stamps_tool_refresh_provenance():
    # M1: every published option artifact durably records which Tool A / Tool B
    # foundation refresh the build read, so a mixed-refresh state is auditable from
    # the artifact rather than reconstructed from mutable latest inputs.
    built = OptionArtifactBuildResult(
        overview=OptionTradingOverviewData(rows=(), liquidity_measurements=()),
        candidate_grids={},
        call_candidate_grids={},
        candidate_slots={},
        call_candidate_slots={},
        liquidity_measurements=(),
        source_context=OptionTradingSourceContext(refresh_run_id="options-run"),
    )
    frames = build_option_artifact_frames(
        built=built,
        contract_metrics=(),
        options_features=pd.DataFrame([{"ticker": "AEM", "run_id": "options-run"}]),
        manifest={"refresh_run_id": "options-run", "as_of_date": "2026-06-16"},
        source_run_id="20260616T000000Z-option-artifacts",
        parent_refresh_id="parent-refresh",
        config_hash="config-hash",
        risk_free_rate=0.04,
        risk_free_rate_is_fallback=False,
        tool_a_refresh_id="tool-run-A",
        tool_b_refresh_id="tool-run-B",
    )
    for name, frame in frames.items():
        assert "built_from_tool_a_refresh_id" in frame.columns, name
        assert "built_from_tool_b_refresh_id" in frame.columns, name
        # .all() on an empty series is True, so this holds for empty frames too.
        assert (frame["built_from_tool_a_refresh_id"].astype(str) == "tool-run-A").all(), name
        assert (frame["built_from_tool_b_refresh_id"].astype(str) == "tool-run-B").all(), name


def test_stamp_per_horizon_candidate_status_and_roundtrip():
    # Part A backend: the overview artifact carries each side's per-horizon status +
    # expiry (derived from the candidate slots, tradable>watch>none) so serve can show
    # any horizon without recomputing. Horizons with no slot are omitted, and the map
    # roundtrips back onto the row via overview_rows_from_frame.
    import json

    from golden_vector.hedge.option_artifact_frames import (
        _stamp_per_horizon_candidate_status,
        overview_rows_from_frame,
    )

    def _put_slot(tier: str, horizon: int) -> OptionCandidateSlot:
        candidate = OptionCandidate(
            ticker="AEM",
            horizon_days=horizon,
            expiration=f"exp-{horizon}",
            days_to_expiry=horizon - 5,
            strike=95.0,
            bid=3.0,
            ask=3.2,
            mid=3.1,
            open_interest=100,
            volume=5,
            implied_volatility=0.4,
            delta=-0.3,
            delta_gap=0.05,
            premium_pct_spot=0.031,
            underlying_price=100.0,
            option_type="P",
            bucket="near_atm",
            liquidity_tier=tier,
        )
        return OptionCandidateSlot(
            ticker="AEM",
            option_type="P",
            horizon_days=horizon,
            target_delta=-0.25,
            expiration=candidate.expiration,
            days_to_expiry=candidate.days_to_expiry,
            status="accepted",
            reason="x",
            candidate=candidate,
            bucket="near_atm",
            liquidity_tier=tier,
        )

    put_slots = {"aem": [_put_slot("tradable", 90), _put_slot("watch", 230)]}
    frame = pd.DataFrame([{"ticker": "AEM", "put_status": "tradable", "call_status": "none"}])

    stamped = _stamp_per_horizon_candidate_status(
        frame, put_slots=put_slots, call_slots={}, display_horizons=(90, 180, 230)
    )
    payload = json.loads(stamped.loc[0, "per_horizon_status_json"])
    assert payload["P"]["90"] == {"status": "tradable", "expiration": "exp-90", "dte": 85}
    assert payload["P"]["230"]["status"] == "watch"
    assert "180" not in payload["P"]  # no slot at 180 -> omitted, not faked as "none"
    assert payload["C"] == {}  # no call slots -> empty

    # The map roundtrips back onto the row (serve reads it from here).
    rows = overview_rows_from_frame(stamped)
    assert rows[0].per_horizon_status_json is not None
    assert json.loads(rows[0].per_horizon_status_json)["P"]["90"]["status"] == "tradable"


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
