"""Milestone A: option snapshot carry-forward when publish gates block.

Covers the carry-forward contract end to end: a blocked option refresh keeps
the previous verified option artifact set in the manifest (CARRIED_FORWARD),
falls back to a calm UNAVAILABLE when nothing verifies, never marks a healthy
carried publish incomplete, and surfaces one shared freshness message across
the CLI and the serve pages.
"""

from __future__ import annotations

import json

import pandas as pd

from golden_vector.app.model_state import (
    OptionPublishBlock,
    summarize_model_state_alignment,
    summarize_option_freshness,
    write_current_model_state_manifest,
)
from golden_vector.app.run_pruning import prune_runs
from golden_vector.cli import OptionArtifactsOutcome, run_option_artifacts_outcome, run_status
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.option_artifacts import (
    OPTION_ARTIFACT_NAMES,
    OPTION_ARTIFACT_SCHEMA_VERSION,
    REQUIRED_OPTION_ARTIFACT_NAMES,
    option_artifact_latest_path,
    option_artifact_run_stamped_path,
)
from golden_vector.hedge.option_signals import option_signal_history_path
from golden_vector.serve.detail_panels import _render_option_trading_panel
from golden_vector.serve.model_state_banner import render_option_freshness_box
from golden_vector.serve.option_trading_data import _read_option_artifact_frames
from tests.helpers import build_test_paths
from tests.test_model_state import (
    _write_foundation_and_options_manifests,
    _write_tool_outputs,
)

DAY1_SOURCE_RUN_ID = "20260610T150000Z-option-artifacts"
DAY1_AS_OF = "2026-06-10"


def _write_option_artifacts(
    paths,
    *,
    refresh_run_id: str,
    source_run_id: str = DAY1_SOURCE_RUN_ID,
    as_of_date: str = DAY1_AS_OF,
    schema_version: int = OPTION_ARTIFACT_SCHEMA_VERSION,
    artifact_names: tuple[str, ...] = OPTION_ARTIFACT_NAMES,
) -> None:
    for artifact_name in artifact_names:
        frame = pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": as_of_date,
                    "schema_version": schema_version,
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": source_run_id,
                }
            ]
        )
        write_parquet_atomic(
            frame,
            option_artifact_run_stamped_path(paths, artifact_name, source_run_id),
            index=False,
        )
        write_parquet_atomic(
            frame,
            option_artifact_latest_path(paths, artifact_name),
            index=False,
        )


def _publish_good_manifest(
    paths,
    *,
    refresh_run_id: str = "refresh-A",
    parent_refresh_id: str = "parent-A",
    source_run_id: str = DAY1_SOURCE_RUN_ID,
    as_of_date: str = DAY1_AS_OF,
    schema_version: int = OPTION_ARTIFACT_SCHEMA_VERSION,
    include_tool_c: bool = True,
    artifact_names: tuple[str, ...] = OPTION_ARTIFACT_NAMES,
):
    _write_foundation_and_options_manifests(paths, refresh_run_id=refresh_run_id)
    _write_tool_outputs(
        paths,
        refresh_run_id=refresh_run_id,
        include_tool_c=include_tool_c,
        include_option_artifacts=False,
    )
    _write_option_artifacts(
        paths,
        refresh_run_id=refresh_run_id,
        source_run_id=source_run_id,
        as_of_date=as_of_date,
        schema_version=schema_version,
        artifact_names=artifact_names,
    )
    return write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id=parent_refresh_id,
    )


def _write_day2_core(paths, *, refresh_run_id: str = "refresh-B") -> None:
    """Fresh core inputs for the next refresh; option artifacts untouched."""

    _write_foundation_and_options_manifests(paths, refresh_run_id=refresh_run_id)
    _write_tool_outputs(
        paths,
        refresh_run_id=refresh_run_id,
        include_option_artifacts=False,
    )


def _blocked_publish(paths, *, parent_refresh_id: str, market_session: str = "CLOSED"):
    return write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id=parent_refresh_id,
        option_publish_block=OptionPublishBlock(
            blockers=("GDX=SPARSE", "GDXJ=LOW_LIQUIDITY"),
            market_session=market_session,
        ),
    )


def test_option_freshness_misaligned_when_artifacts_reference_other_refresh(tmp_path):
    # Option artifacts are usable + current schema but reference an OLDER refresh than
    # the current foundation/options run. Freshness must read MISALIGNED, never OK,
    # so the box can't say "current" while the banner says WARN (audit M4).
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A", include_option_artifacts=False)
    _write_option_artifacts(paths, refresh_run_id="older-refresh", source_run_id=DAY1_SOURCE_RUN_ID)

    payload = write_current_model_state_manifest(
        paths=paths, config_hash="config-hash", parent_refresh_id="parent-A"
    )

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "MISALIGNED"
    assert domain.get("alignment_warnings")
    assert payload["alignment"]["status"] == "WARN"
    assert payload["state"] == "incomplete"


def test_option_freshness_ok_when_artifacts_aligned(tmp_path):
    paths = build_test_paths(tmp_path)
    payload = _publish_good_manifest(paths)

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "OK"
    assert "alignment_warnings" not in domain


def test_blocked_refresh_carries_forward_previous_option_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    previous = _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "CARRIED_FORWARD"
    assert domain["source_run_id"] == DAY1_SOURCE_RUN_ID
    assert domain["as_of_date"] == DAY1_AS_OF
    assert domain["market_session"] == "CLOSED"
    assert domain["blockers"] == ["GDX=SPARSE", "GDXJ=LOW_LIQUIDITY"]
    assert domain["carried_from_parent_refresh_id"] == "parent-A"

    for name in OPTION_ARTIFACT_NAMES:
        carried = payload["artifacts"][name]
        original = previous["artifacts"][name]
        assert carried["path"] == original["path"]
        assert carried["sha256"] == original["sha256"]
        assert carried["carried_forward"] is True
        assert carried["usable"] is True
        assert carried["immutable"] is True

    assert payload["state"] == "complete"
    assert payload["alignment"]["status"] == "OK"
    assert payload["alignment"]["options_carried_forward"] is True
    assert any(
        warning.startswith("Option artifacts were carried forward")
        for warning in payload["warnings"]
    )


def test_carried_forward_manifest_keeps_authoritative_consumers_calm(tmp_path):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")
    verdict = summarize_model_state_alignment(payload)

    # Candidate Finder and the ticker report treat this verdict as
    # authoritative; OK-with-no-messages means no mismatch warnings anywhere.
    assert verdict is not None
    assert verdict["status"] == "OK"
    assert verdict["warnings"] == ()

    freshness = summarize_option_freshness(payload)
    assert freshness is not None
    assert freshness["status"] == "CARRIED_FORWARD"
    assert "stored snapshot: 2026-06-10" in freshness["message"]
    assert "US options were closed at refresh time" in freshness["message"]


def test_blocked_refresh_when_market_open_does_not_claim_closed(tmp_path):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B", market_session="OPEN")
    freshness = summarize_option_freshness(payload)

    assert freshness is not None
    assert "closed" not in freshness["message"].lower()
    assert "not publishable" in freshness["message"]


def test_blocked_refresh_without_previous_manifest_is_unavailable(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    # Stray aliases on disk must NOT be scavenged without a previous manifest.
    _write_option_artifacts(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "UNAVAILABLE"
    assert "No model-state manifest exists yet" in domain["reason"]
    assert payload["state"] == "incomplete"
    for name in REQUIRED_OPTION_ARTIFACT_NAMES:
        assert payload["artifacts"][name]["present"] is False
        assert payload["artifacts"][name]["usable"] is False
        assert f"Required artifact is missing: {name}." in payload["warnings"]
    # Core analytics still publish as usable artifacts.
    assert payload["artifacts"]["tool_a"]["usable"] is True
    assert payload["artifacts"]["foundation"]["usable"] is True


def test_blocked_refresh_with_tampered_previous_artifact_is_unavailable(tmp_path):
    paths = build_test_paths(tmp_path)
    previous = _publish_good_manifest(paths)
    tampered_relative = previous["artifacts"]["option_candidate_slots"]["path"]
    tampered_path = paths.repo_root / tampered_relative
    tampered = pd.DataFrame(
        [
            {
                "ticker": "TAMPERED",
                "as_of_date": DAY1_AS_OF,
                "schema_version": OPTION_ARTIFACT_SCHEMA_VERSION,
                "snapshot_refresh_run_id": "refresh-A",
                "source_run_id": DAY1_SOURCE_RUN_ID,
            }
        ]
    )
    write_parquet_atomic(tampered, tampered_path, index=False)
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "UNAVAILABLE"
    assert "sha256" in domain["reason"]


def test_blocked_refresh_with_mixed_snapshot_ids_is_unavailable(tmp_path):
    """Codex review finding 1: a stitched carried set must be refused.

    All ten artifacts verify (one source run, valid sha256, current schema,
    non-empty required frames) but one chart artifact references a different
    options snapshot id. Carrying that forward would mix chain snapshots, so
    carry-forward is refused and the manifest is truthfully incomplete.
    """

    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(
        paths,
        refresh_run_id="refresh-A",
        include_option_artifacts=False,
    )
    _write_option_artifacts(paths, refresh_run_id="refresh-A")
    mixed = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": DAY1_AS_OF,
                "schema_version": OPTION_ARTIFACT_SCHEMA_VERSION,
                "snapshot_refresh_run_id": "refresh-OTHER",
                "source_run_id": DAY1_SOURCE_RUN_ID,
            }
        ]
    )
    mixed_name = "option_skew_curve_points"
    write_parquet_atomic(
        mixed,
        option_artifact_run_stamped_path(paths, mixed_name, DAY1_SOURCE_RUN_ID),
        index=False,
    )
    write_parquet_atomic(
        mixed,
        option_artifact_latest_path(paths, mixed_name),
        index=False,
    )
    previous = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-A",
    )
    # The donor looks healthy: the mixed artifact is a chart frame outside the
    # required alignment set, so the previous manifest still published clean.
    assert previous["state"] == "complete"
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "UNAVAILABLE"
    assert "single options snapshot id" in domain["reason"]
    assert payload["state"] == "incomplete"


def test_option_overview_page_shows_carried_forward_message(tmp_path):
    """Codex review finding 2: the user-facing page states the carry-forward."""

    from golden_vector.hedge.option_trading import OptionTradingOverviewData
    from golden_vector.serve.overview_option_trading import (
        _render_option_trading_overview_page,
    )

    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    carried = _blocked_publish(paths, parent_refresh_id="parent-B")

    html = _render_option_trading_overview_page(
        OptionTradingOverviewData(rows=(), liquidity_measurements=()),
        model_state_manifest=carried,
    )

    assert "Option prices are from the latest stored snapshot: 2026-06-10" in html
    assert "Stored option snapshot" in html


def test_blocked_refresh_with_stale_schema_previous_artifacts_is_unavailable(tmp_path):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths, schema_version=2)
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "UNAVAILABLE"
    assert "schema version" in domain["reason"]


def test_two_consecutive_blocked_refreshes_keep_original_source(tmp_path):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    day2 = _blocked_publish(paths, parent_refresh_id="parent-B")
    _write_day2_core(paths, refresh_run_id="refresh-C")

    day3 = _blocked_publish(paths, parent_refresh_id="parent-C")

    day2_domain = day2["freshness_domains"]["option_artifacts"]
    day3_domain = day3["freshness_domains"]["option_artifacts"]
    assert day3_domain["status"] == "CARRIED_FORWARD"
    assert day3_domain["source_run_id"] == DAY1_SOURCE_RUN_ID
    assert day3_domain["as_of_date"] == DAY1_AS_OF
    assert day2_domain["source_run_id"] == day3_domain["source_run_id"]
    assert day3["state"] == "complete"
    for name in OPTION_ARTIFACT_NAMES:
        assert day3["artifacts"][name]["sha256"] == day2["artifacts"][name]["sha256"]


def test_previous_manifest_incomplete_for_non_option_reason_still_donates(tmp_path):
    paths = build_test_paths(tmp_path)
    previous = _publish_good_manifest(paths, include_tool_c=False)
    assert previous["state"] == "incomplete"
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    assert payload["freshness_domains"]["option_artifacts"]["status"] == "CARRIED_FORWARD"
    assert payload["state"] == "complete"


def test_fresh_publish_records_ok_freshness_domain(tmp_path):
    paths = build_test_paths(tmp_path)
    payload = _publish_good_manifest(paths)

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "OK"
    assert domain["source_run_id"] == DAY1_SOURCE_RUN_ID
    assert domain["as_of_date"] == DAY1_AS_OF
    assert payload["freshness_domains"]["core"]["status"] == "OK"


def test_pruning_protects_carried_forward_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    previous = _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    _blocked_publish(paths, parent_refresh_id="parent-B")

    # Even with only the newest snapshot retained, the carried manifest still
    # references the day-1 option files, so pruning must protect them.
    report = prune_runs(paths, keep_model_states=1, apply=True)

    for name in OPTION_ARTIFACT_NAMES:
        carried_path = paths.repo_root / previous["artifacts"][name]["path"]
        assert carried_path.exists()
    assert report.dry_run is False


def test_run_status_reports_option_freshness(tmp_path, capsys):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    _blocked_publish(paths, parent_refresh_id="parent-B")

    exit_code = run_status(paths)
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Option data freshness: CARRIED_FORWARD" in out
    assert "stored snapshot: 2026-06-10" in out


def test_blocked_outcome_persists_nothing_and_reports_blockers(tmp_path):
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

    outcome = run_option_artifacts_outcome(paths, parent_refresh_id="parent-refresh")

    assert outcome.status == "BLOCKED"
    assert outcome.blockers
    assert outcome.market_session in {"OPEN", "CLOSED", "UNKNOWN"}
    assert not option_signal_history_path(paths).exists()
    for artifact_name in OPTION_ARTIFACT_NAMES:
        assert not option_artifact_latest_path(paths, artifact_name).exists()


def test_refresh_continues_past_blocked_options_and_runs_portfolio(
    tmp_path,
    monkeypatch,
    capsys,
):
    from golden_vector.app.config import load_app_config
    from golden_vector.app.paths import ProjectPaths
    from golden_vector.cli import run_refresh

    class _LoadedConfigStub:
        def __init__(self, app, config_hash):
            self.app = app
            self.config_hash = config_hash

    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    real_loaded = load_app_config(ProjectPaths.discover()).app
    app_with_portfolio = real_loaded.model_copy(
        update={"portfolio": real_loaded.portfolio.model_copy(update={"enabled": True})}
    )
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=app_with_portfolio, config_hash="config-hash"),
    )
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")

    call_order: list[str] = []

    monkeypatch.setattr(
        "golden_vector.cli.run_foundation",
        lambda _paths, **_kwargs: call_order.append("update-data") or 0,
    )
    monkeypatch.setattr(
        "golden_vector.cli.run_tool_a",
        lambda _paths: call_order.append("tool-a") or 0,
    )
    # Refresh now runs a guarded fetch-fundamentals step before Tool B; stub it (like the
    # other pipeline steps) so this carry-forward test never reaches Yahoo. Non-appending so
    # it can't disturb the call_order assertion.
    monkeypatch.setattr(
        "golden_vector.cli.run_fetch_fundamentals",
        lambda _paths, **_kwargs: 0,
    )
    monkeypatch.setattr(
        "golden_vector.cli.run_tool_b",
        lambda _paths, **_kwargs: call_order.append("tool-b") or 0,
    )
    monkeypatch.setattr(
        "golden_vector.cli.run_tool_c",
        lambda _paths, **_kwargs: call_order.append("tool-c") or 0,
    )
    monkeypatch.setattr(
        "golden_vector.cli.run_tool_d",
        lambda _paths, **_kwargs: call_order.append("tool-d") or 0,
    )
    monkeypatch.setattr(
        "golden_vector.cli.run_ticker_page",
        lambda _paths, **_kwargs: call_order.append("ticker-page") or 0,
    )
    monkeypatch.setattr(
        "golden_vector.cli.run_option_artifacts_outcome",
        lambda _paths, **_kwargs: (
            call_order.append("option-artifacts"),
            OptionArtifactsOutcome(
                status="BLOCKED",
                blockers=("GDX=SPARSE",),
                market_session="CLOSED",
            ),
        )[1],
    )
    monkeypatch.setattr(
        "golden_vector.cli._run_portfolio_refresh_step",
        lambda _paths, **_kwargs: call_order.append("portfolio") or 0,
    )

    exit_code = run_refresh(paths, gold_price_override=None, skip_tool_b=False)
    out = capsys.readouterr().out

    assert exit_code == 0, out
    assert "portfolio" in call_order
    assert call_order.index("ticker-page") > call_order.index("tool-d")
    assert call_order.index("option-artifacts") > call_order.index("ticker-page")
    assert call_order.index("portfolio") > call_order.index("option-artifacts")
    manifest = json.loads(
        paths.latest_model_state_manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["freshness_domains"]["option_artifacts"]["status"] == "CARRIED_FORWARD"
    assert manifest["stage_timings"]["option_artifacts"]["status"] == "BLOCKED"
    assert "carried forward" in out
    assert "Option data: CARRIED_FORWARD" in out


def test_freshness_box_renders_for_each_status(tmp_path):
    paths = build_test_paths(tmp_path)
    fresh = _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    carried = _blocked_publish(paths, parent_refresh_id="parent-B")

    fresh_box = render_option_freshness_box(fresh)
    assert "option-freshness-ok" in fresh_box
    assert render_option_freshness_box(fresh, only_when_stale=True) == ""

    carried_box = render_option_freshness_box(carried)
    assert "Stored option snapshot" in carried_box
    assert "2026-06-10" in carried_box
    assert render_option_freshness_box(carried, only_when_stale=True) == carried_box

    assert render_option_freshness_box(None) == ""
    assert render_option_freshness_box({"state": "complete"}) == ""


def test_detail_panel_shows_freshness_box_even_without_detail_data(tmp_path):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    carried = _blocked_publish(paths, parent_refresh_id="parent-B")

    html = _render_option_trading_panel(None, model_state_manifest=carried)

    assert "Stored option snapshot" in html
    assert "2026-06-10" in html


def test_non_option_publisher_inherits_carried_forward_domain(tmp_path):
    """Merge-verification HIGH: portfolio edits / fetch-fundamentals republish
    the manifest WITHOUT an option block; during a carried window that must
    not flip the option domain back to OK (the aliases still hold the old
    snapshot) nor break the calm-consumers guarantee."""

    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    carried = _blocked_publish(paths, parent_refresh_id="parent-B")

    # Simulate a portfolio lot edit: republish with NO option block.
    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-C",
    )

    domain = payload["freshness_domains"]["option_artifacts"]
    carried_domain = carried["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "CARRIED_FORWARD"
    assert domain["source_run_id"] == carried_domain["source_run_id"]
    assert domain["as_of_date"] == carried_domain["as_of_date"]
    assert domain["market_session"] == carried_domain["market_session"]
    assert payload["state"] == "complete"
    assert payload["alignment"]["status"] == "OK"
    verdict = summarize_model_state_alignment(payload)
    assert verdict is not None and verdict["status"] == "OK" and verdict["warnings"] == ()


def test_non_option_publisher_returns_to_ok_after_fresh_option_build(tmp_path):
    paths = build_test_paths(tmp_path)
    _publish_good_manifest(paths)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    _blocked_publish(paths, parent_refresh_id="parent-B")

    # A fresh successful option build aligned with the CURRENT options
    # ingestion manifest lands on disk (e.g. standalone option-artifacts run).
    _write_option_artifacts(
        paths,
        refresh_run_id="refresh-B",
        source_run_id="20260611T160000Z-option-artifacts",
        as_of_date="2026-06-11",
    )

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-C",
    )

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "OK"
    assert domain["source_run_id"] == "20260611T160000Z-option-artifacts"


def test_non_option_publisher_inherits_unavailable_domain(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    _write_option_artifacts(paths, refresh_run_id="refresh-OLD")
    _blocked_publish(paths, parent_refresh_id="parent-B")

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-C",
    )

    assert payload["freshness_domains"]["option_artifacts"]["status"] == "UNAVAILABLE"
    assert payload["state"] == "incomplete"


def test_unavailable_manifest_yields_calm_empty_frames_not_schema_error(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_day2_core(paths, refresh_run_id="refresh-B")
    _write_option_artifacts(paths, refresh_run_id="refresh-B")
    _blocked_publish(paths, parent_refresh_id="parent-B")

    # Manifest exists and lists option artifact keys, but the freshness domain
    # says UNAVAILABLE: the reader must return None (calm empty page), not
    # raise the stale-schema error.
    assert _read_option_artifact_frames(paths) is None


def test_v3_generation_carries_forward_and_serves_under_v4_code(tmp_path):
    """Legacy reader window (plan §6.4): a v3 generation stays fully usable."""

    from golden_vector.contracts.option_artifacts import OPTION_TRADING_READ_SET
    from golden_vector.serve.option_trading_data import _read_option_artifact_frames

    paths = build_test_paths(tmp_path)
    _publish_good_manifest(
        paths,
        schema_version=3,
        artifact_names=OPTION_TRADING_READ_SET,
    )
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "CARRIED_FORWARD"
    assert domain["source_run_id"] == DAY1_SOURCE_RUN_ID
    # The v4-only artifacts are NOT demanded from a v3 generation.
    for name in ("option_chain_history_daily", "option_availability"):
        assert payload["artifacts"][name].get("usable") is not True
    for name in OPTION_TRADING_READ_SET:
        assert payload["artifacts"][name]["usable"] is True

    frames = _read_option_artifact_frames(paths)
    assert frames is not None
    assert set(frames) == set(OPTION_TRADING_READ_SET) - {"option_contract_metrics"}


def test_v4_generation_requires_the_full_v4_set(tmp_path):
    """A v4-stamped generation missing a v4 artifact refuses to carry forward."""

    from golden_vector.contracts.option_artifacts import OPTION_TRADING_READ_SET

    paths = build_test_paths(tmp_path)
    _publish_good_manifest(
        paths,
        schema_version=4,
        artifact_names=OPTION_TRADING_READ_SET,
    )
    _write_day2_core(paths, refresh_run_id="refresh-B")

    payload = _blocked_publish(paths, parent_refresh_id="parent-B")

    domain = payload["freshness_domains"]["option_artifacts"]
    assert domain["status"] == "UNAVAILABLE"
    assert "option_chain_history_daily" in domain["reason"]
