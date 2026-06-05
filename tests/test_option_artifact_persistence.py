from __future__ import annotations

import pandas as pd
import pytest

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
from golden_vector.ingestion.persist_option_artifacts import persist_option_artifact_frames
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
                {"ticker": "AEM", "run_id": "options-run"},
                {"ticker": "NEM", "run_id": "options-run"},
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
