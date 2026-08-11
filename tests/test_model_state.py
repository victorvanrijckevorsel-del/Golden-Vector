from __future__ import annotations

import json
import shutil
from datetime import date

import pandas as pd

from golden_vector.app.model_state import (
    TICKER_PAGE_ARTIFACT_NAMES,
    build_current_model_state_manifest,
    load_current_model_state_manifest,
    read_current_model_json,
    read_current_model_parquet,
    resolve_current_model_artifact_path,
    summarize_model_state_manifest,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.contracts.option_artifacts import (
    OPTION_ARTIFACT_NAMES,
    REQUIRED_OPTION_ARTIFACT_NAMES,
    option_artifact_latest_path,
    option_artifact_run_stamped_path,
)
from golden_vector.common.parquet import write_parquet_atomic
from golden_vector.contracts.ticker_page import (
    FX_ATTRIBUTION_COLUMNS,
    GOLD_RESPONSE_COLUMNS,
    PERCENTILES_COLUMNS,
    PERFORMANCE_COLUMNS,
    RESEARCH_SERIES_COLUMNS,
    TICKER_PAGE_SCHEMA_VERSIONS,
)
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from tests.helpers import build_test_paths, tool_b_output_row


def test_model_state_manifest_records_complete_aligned_build(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id=None,
        stage_timings={"tool_a": {"duration_seconds": 1.25}},
    )
    loaded = load_current_model_state_manifest(paths)

    assert loaded == payload
    assert payload["state"] == "complete"
    assert payload["manifest_readable"] is True
    assert payload["parent_refresh_id"] is None
    assert payload["publish"]["atomic_pointer"] is True
    assert payload["publish"]["latest_aliases_authoritative"] is False
    snapshot_path = paths.repo_root / payload["publish"]["retention_snapshot_path"]
    assert snapshot_path.exists()
    assert json.loads(snapshot_path.read_text(encoding="utf-8")) == payload
    assert payload["artifacts"]["foundation"]["immutable"] is True
    assert payload["artifacts"]["foundation"]["source_alias_path"] == (
        "data/intermediate/status/latest_foundation_manifest.json"
    )
    assert payload["artifacts"]["options"]["immutable"] is True
    assert payload["artifacts"]["tool_a"]["row_count"] == 1
    assert payload["artifacts"]["tool_a"]["immutable"] is True
    assert payload["artifacts"]["tool_a"]["path"].startswith("data/output/tool_a/tool_a_latest_")
    assert payload["artifacts"]["tool_a"]["path"] != "data/output/tool_a/tool_a_latest.parquet"
    assert payload["artifacts"]["tool_a"]["snapshot_refresh_run_ids"] == ["refresh-A"]
    assert payload["artifacts"]["option_candidate_slots"]["required_for_complete"] is True
    assert payload["artifacts"]["option_candidate_slots"]["immutable"] is True
    assert payload["artifacts"]["option_candidate_slots"]["row_count"] == 1
    assert payload["stage_timings"]["tool_a"]["duration_seconds"] == 1.25
    for name in TICKER_PAGE_ARTIFACT_NAMES:
        assert payload["artifacts"][name]["required_for_complete"] is True
        assert payload["artifacts"][name]["immutable"] is True


def test_model_state_manifest_requires_the_ticker_page_artifacts(tmp_path):
    """Same build as the complete case minus ticker-page: now 'incomplete', and
    every missing ticker-page artifact is named."""

    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A", include_ticker_page=False)

    payload = build_current_model_state_manifest(paths=paths, config_hash="config-hash")

    assert payload["state"] == "incomplete"
    for name in TICKER_PAGE_ARTIFACT_NAMES:
        assert f"Required artifact is missing: {name}." in payload["warnings"]


def test_model_state_manifest_warns_when_tool_c_and_tool_d_are_missing(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A", include_tool_c=False, include_tool_d=False)

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    assert "Required artifact is missing: tool_c." in payload["warnings"]
    assert "Required artifact is missing: tool_d." in payload["warnings"]


def test_model_state_manifest_requires_core_option_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(
        paths,
        refresh_run_id="refresh-A",
        include_option_artifacts=False,
    )

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    assert "Required artifact is missing: option_candidate_slots." in payload["warnings"]
    assert "Required artifact is missing: option_trading_overview." in payload["warnings"]
    assert "Required artifact is missing: candidate_finder_inputs." in payload["warnings"]


def test_model_state_manifest_rejects_empty_core_option_artifact(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    source_run_id = "20260601T000000Z-option-artifacts"
    empty = pd.DataFrame(
        {
            "schema_version": pd.Series(dtype="object"),
            "snapshot_refresh_run_id": pd.Series(dtype="object"),
            "source_run_id": pd.Series(dtype="object"),
        }
    )
    empty.attrs["schema_version"] = 1
    empty.attrs["snapshot_refresh_run_id"] = "refresh-A"
    empty.attrs["source_run_id"] = source_run_id
    artifact_name = "option_trading_overview"
    write_parquet_atomic(
        empty,
        option_artifact_run_stamped_path(paths, artifact_name, source_run_id),
        index=False,
    )
    write_parquet_atomic(
        empty,
        option_artifact_latest_path(paths, artifact_name),
        index=False,
    )

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    assert "option_trading_overview has zero rows." in payload["warnings"]


def test_model_state_manifest_warns_on_stale_core_option_artifact(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    _write_i3_option_artifacts(paths, refresh_run_id="older-options-run")

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    assert (
        "option_candidate_slots references older-options-run while options is refresh-A."
        in payload["warnings"]
    )
    assert payload["alignment"]["option_artifact_refresh_run_ids"][
        "option_candidate_slots"
    ] == ["older-options-run"]


def test_model_state_manifest_resolves_portfolio_csv_and_warns_on_stale_portfolio(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    _write_portfolio_outputs(paths, refresh_run_id="older-foundation-run")

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    assert (
        "portfolio_lines references older-foundation-run while foundation is refresh-A."
        in payload["warnings"]
    )
    assert payload["alignment"]["portfolio_artifact_refresh_run_ids"]["portfolio_lines"] == [
        "older-foundation-run"
    ]
    csv_artifact = payload["artifacts"]["portfolio_reconciliation_export_csv"]
    assert csv_artifact["immutable"] is True
    assert csv_artifact["kind"] == "csv"
    assert csv_artifact["path"].startswith(
        "data/output/portfolio/portfolio_reconciliation_export_latest_"
    )
    assert csv_artifact["path"] != (
        "data/output/portfolio/portfolio_reconciliation_export_latest.csv"
    )


def test_model_state_warns_when_only_an_m4_portfolio_artifact_is_stale(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    _write_portfolio_outputs(paths, refresh_run_id="refresh-A")   # all 9 aligned
    # Re-stamp ONLY the M4 value-history artifact to an older foundation run; the
    # 5 core artifacts stay aligned. Before M4 artifacts were alignment-checked this
    # produced no warning -- the banner could read OK over a stale chart/export.
    source_run_id = "20260601T000000Z-portfolio"
    stale = pd.DataFrame(
        [{"schema_version": 1, "snapshot_refresh_run_id": "older-foundation-run", "source_run_id": source_run_id}]
    )
    vh_latest = paths.latest_portfolio_value_history_path
    write_parquet_atomic(
        stale, vh_latest.parent / f"portfolio_value_history_latest_{source_run_id}.parquet", index=False
    )
    write_parquet_atomic(stale, vh_latest, index=False)

    payload = build_current_model_state_manifest(paths=paths, config_hash="config-hash")

    assert payload["state"] == "incomplete"
    assert (
        "portfolio_value_history references older-foundation-run while foundation is refresh-A."
        in payload["warnings"]
    )


def test_current_model_readers_use_manifest_immutable_paths_after_aliases_change(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-refresh-A",
    )

    old_tool_a_path = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    assert old_tool_a_path == paths.resolve_repo_relative(payload["artifacts"]["tool_a"]["path"])

    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-B")
    pd.DataFrame(
        [
            {
                "ticker": "BROKEN",
                "as_of_date": date(2026, 6, 2),
                "snapshot_refresh_run_id": "refresh-B",
                "source_run_id": "tool-a-new",
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)

    foundation = read_current_model_json(
        paths,
        "foundation",
        fallback_path=paths.latest_foundation_manifest_path,
    )
    tool_a = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert foundation is not None
    assert foundation["refresh_run_id"] == "refresh-A"
    assert tool_a["ticker"].tolist() == ["NEM"]
    assert tool_a["snapshot_refresh_run_id"].tolist() == ["refresh-A"]


def test_model_state_manifest_lists_all_refresh_mismatches(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(
        paths,
        refresh_run_id="foundation-run",
        options_refresh_run_id="options-run",
    )
    _write_tool_outputs(
        paths,
        refresh_run_id="tool-run",
    )

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    warnings = "\n".join(payload["warnings"])
    assert "Foundation refresh foundation-run does not match options refresh options-run" in warnings
    assert "tool_a references tool-run while foundation is foundation-run" in warnings
    assert "tool_b references tool-run while foundation is foundation-run" in warnings
    assert "tool_c references tool-run while foundation is foundation-run" in warnings
    assert "tool_d references tool-run while foundation is foundation-run" in warnings


def test_model_state_loader_and_summary_handle_missing_manifest(tmp_path):
    paths = build_test_paths(tmp_path)

    assert load_current_model_state_manifest(paths) is None
    assert summarize_model_state_manifest(None) == [
        "Model state manifest: NOT FOUND",
        "  Legacy latest files are being inspected directly.",
    ]


def test_model_state_loader_reports_corrupt_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.latest_model_state_manifest_path.write_text("{not-json", encoding="utf-8")

    payload = load_current_model_state_manifest(paths)

    assert payload is not None
    assert payload["state"] == "incomplete"
    assert payload["manifest_readable"] is False
    assert "read_error" in payload
    assert "Could not read model-state manifest" in payload["warnings"][0]


def test_current_model_reader_does_not_fall_back_when_manifest_is_corrupt(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "STALE",
                "snapshot_refresh_run_id": "stale-alias",
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    paths.latest_model_state_manifest_path.write_text("{not-json", encoding="utf-8")

    resolved = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    frame = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert resolved is None
    assert frame.empty


def test_current_model_reader_rejects_non_object_manifest(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "STALE",
                "snapshot_refresh_run_id": "stale-alias",
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    paths.latest_model_state_manifest_path.write_text("[]", encoding="utf-8")

    payload = load_current_model_state_manifest(paths)
    resolved = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    frame = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert payload is not None
    assert payload["manifest_readable"] is False
    assert "root JSON value is not an object" in payload["warnings"][0]
    assert resolved is None
    assert frame.empty


def test_current_model_reader_rejects_object_manifest_without_artifacts(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "STALE",
                "snapshot_refresh_run_id": "stale-alias",
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    paths.latest_model_state_manifest_path.write_text("{}", encoding="utf-8")

    resolved = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    frame = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert resolved is None
    assert frame.empty


def test_current_model_reader_rejects_non_immutable_manifest_artifact(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.output_tool_a_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "MUTABLE",
                "snapshot_refresh_run_id": "mutable-alias",
            }
        ]
    ).to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "manifest_readable": True,
                "state": "incomplete",
                "artifacts": {
                    "tool_a": {
                        "name": "tool_a",
                        "path": "data/output/tool_a/tool_a_latest.parquet",
                        "present": True,
                        "readable": True,
                        "usable": True,
                        "immutable": False,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    resolved = resolve_current_model_artifact_path(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )
    frame = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert resolved is None
    assert frame.empty


def test_manifest_resolves_run_stamped_artifact_by_source_run_id_not_alias_bytes(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    alias = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)
    alias.loc[:, "ticker"] = "ALIAS_ONLY"
    alias.to_parquet(paths.latest_tool_a_snapshot_parquet_path, index=False)

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-refresh-A",
    )
    frame = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert payload["artifacts"]["tool_a"]["immutable"] is True
    assert payload["artifacts"]["tool_a"]["path"].startswith("data/output/tool_a/tool_a_latest_")
    assert frame["ticker"].tolist() == ["NEM"]


def test_manifest_resolves_i3_option_artifacts_by_source_run_id(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    source_run_id = "20260601T000000Z-option-artifacts"
    artifact_name = "option_selected_candidates"
    run_stamped_path = option_artifact_run_stamped_path(
        paths,
        artifact_name,
        source_run_id,
    )
    alias_path = option_artifact_latest_path(paths, artifact_name)
    run_stamped_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "ticker": "AEM",
                "option_side": "put",
                "horizon_days": 60,
                "bucket": "near_atm",
                "liquidity_tier": "tradable",
                "schema_version": 1,
                "snapshot_refresh_run_id": "refresh-A",
                "source_run_id": source_run_id,
                "parent_refresh_id": "parent-refresh-A",
            }
        ]
    ).to_parquet(run_stamped_path, index=False)
    alias_frame = pd.read_parquet(run_stamped_path)
    alias_frame.loc[:, "ticker"] = "ALIAS_ONLY"
    alias_frame.to_parquet(alias_path, index=False)

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-refresh-A",
    )
    frame = read_current_model_parquet(
        paths,
        artifact_name,
        fallback_path=alias_path,
    )

    artifact = payload["artifacts"][artifact_name]
    assert artifact["immutable"] is True
    assert artifact["path"].startswith("data/output/options/option_selected_candidates_latest_")
    assert artifact["source_alias_path"] == "data/output/options/option_selected_candidates_latest.parquet"
    assert artifact["schema_version"] == "1"
    assert frame["ticker"].tolist() == ["AEM"]


def test_manifest_records_tool_a_structural_metrics_immutable_artifact(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    tool_a_run_id = pd.read_parquet(paths.latest_tool_a_snapshot_parquet_path)["source_run_id"].iloc[0]
    structural = pd.DataFrame(
        [
            {
                "ticker": "NEM",
                "as_of_date": date(2026, 6, 1),
                "window_id": "12M",
                "window_status": "ELIGIBLE",
                "structural_delta": 1.2,
                "source_run_id": tool_a_run_id,
            }
        ]
    )
    paths.intermediate_tool_a_structural_dir.mkdir(parents=True, exist_ok=True)
    structural.to_parquet(
        paths.intermediate_tool_a_structural_dir / f"tool_a_structural_{tool_a_run_id}.parquet",
        index=False,
    )
    structural.to_parquet(paths.latest_tool_a_structural_metrics_path, index=False)

    payload = write_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
        parent_refresh_id="parent-refresh-A",
    )

    artifact = payload["artifacts"]["tool_a_structural_metrics"]
    assert artifact["immutable"] is True
    assert artifact["path"].startswith("data/intermediate/tool_a_structural/tool_a_structural_")


def test_model_state_manifest_marks_corrupt_required_artifact_not_usable(tmp_path):
    paths = build_test_paths(tmp_path)
    _write_foundation_and_options_manifests(paths, refresh_run_id="refresh-A")
    _write_tool_outputs(paths, refresh_run_id="refresh-A")
    paths.latest_tool_c_snapshot_parquet_path.write_text(
        "not a parquet file",
        encoding="utf-8",
    )

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    tool_c = payload["artifacts"]["tool_c"]
    assert payload["state"] == "incomplete"
    assert tool_c["present"] is True
    assert tool_c["readable"] is False
    assert tool_c["usable"] is False
    assert "read_error" in tool_c
    assert "Required artifact is not usable: tool_c." in payload["warnings"]


def test_model_state_manifest_requires_foundation_and_options_status(tmp_path):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "refresh-A",
                "snapshot_as_of_date": "2026-06-01",
                "raw_qa_summary": {"overall_status": "PASS"},
                "normalization_qa_summary": {"overall_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "refresh_run_id": "refresh-A",
                "as_of_date": "2026-06-01",
                "summary": {},
            }
        ),
        encoding="utf-8",
    )
    _write_tool_outputs(paths, refresh_run_id="refresh-A")

    payload = build_current_model_state_manifest(
        paths=paths,
        config_hash="config-hash",
    )

    assert payload["state"] == "incomplete"
    assert "Foundation status is missing." in payload["warnings"]
    assert "Options phase status is missing." in payload["warnings"]


def _write_foundation_and_options_manifests(
    paths: ProjectPaths,
    *,
    refresh_run_id: str,
    options_refresh_run_id: str | None = None,
) -> None:
    paths.ensure_runtime_dirs()
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": refresh_run_id,
                "snapshot_as_of_date": "2026-06-01",
                "foundation_status": "PASS",
                "raw_qa_summary": {"overall_status": "PASS"},
                "normalization_qa_summary": {"overall_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    paths.latest_options_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "refresh_run_id": options_refresh_run_id or refresh_run_id,
                "as_of_date": "2026-06-01",
                "summary": {
                    "options_phase_status": "PASS",
                    "options_success_count": 1,
                    "options_error_count": 0,
                    "options_feature_row_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_tool_outputs(
    paths: ProjectPaths,
    *,
    refresh_run_id: str,
    include_tool_c: bool = True,
    include_tool_d: bool = True,
    include_option_artifacts: bool = True,
    include_ticker_page: bool = True,
) -> None:
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
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": tool_a_context.run_id,
                    "tool_a_rank": 1,
                    "score_eligible": True,
                }
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
                    "NEM",
                    as_of_date=date(2026, 6, 1),
                    snapshot_refresh_run_id=refresh_run_id,
                    source_run_id=tool_b_context.run_id,
                    screening_verdict="WATCHLIST",
                )
            ]
        ),
    )
    if include_tool_c:
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
                        "ticker": "NEM",
                        "as_of_date": date(2026, 6, 1),
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_c_context.run_id,
                        "tool_c_downside_rank": 1,
                        "tool_c_upside_rank": 1,
                    }
                ]
            ),
        )
    if include_tool_d:
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
                        "ticker": "NEM",
                        "as_of_date": date(2026, 6, 1),
                        "snapshot_refresh_run_id": refresh_run_id,
                        "source_run_id": tool_d_context.run_id,
                        "gold_price_used": 4000.0,
                        "spot_gold_date": "2026-06-01",
                        "tool_d_quality_rank": 1,
                    }
                ]
            ),
        )
    if include_option_artifacts:
        _write_i3_option_artifacts(paths, refresh_run_id=refresh_run_id)
    if include_ticker_page:
        _write_ticker_page_artifacts(paths, refresh_run_id=refresh_run_id)


TICKER_PAGE_ARTIFACT_SPECS = {
    "gold_response": (
        "latest_ticker_page_gold_response_path",
        GOLD_RESPONSE_COLUMNS,
        {"ticker": "NEM", "finance_source": "our"},
    ),
    "percentiles": (
        "latest_ticker_page_percentiles_path",
        PERCENTILES_COLUMNS,
        {"ticker": "NEM", "finance_source": "our", "metric_key": "margin_pct"},
    ),
    "performance": (
        "latest_ticker_page_performance_path",
        PERFORMANCE_COLUMNS,
        {
            "ticker": "NEM",
            "series": "stock",
            "view": "rebased",
            "horizon": "1Y",
            "date": "2026-06-01",
        },
    ),
    "research_series": (
        "latest_ticker_page_research_series_path",
        RESEARCH_SERIES_COLUMNS,
        {"ticker": "NEM", "kind": "weekly", "date": "2026-06-01"},
    ),
    # Feature A: the fifth ticker artifact is part of a complete generation.
    "fx_attribution": (
        "latest_ticker_page_fx_attribution_path",
        FX_ATTRIBUTION_COLUMNS,
        {"ticker": "NEM", "horizon": "1Y"},
    ),
}


def _write_ticker_page_artifacts(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    """Write the four ticker-page artifacts (run-stamped immutable + alias).

    They are REQUIRED artifacts, so a build without them is 'incomplete'.
    """

    source_run_id = "20260601T000000Z-ticker-page"
    paths.output_ticker_page_dir.mkdir(parents=True, exist_ok=True)
    for prefix, (path_attr, columns, keys) in TICKER_PAGE_ARTIFACT_SPECS.items():
        row: dict[str, object] = dict.fromkeys(columns, None)
        row.update(keys)
        row.update(
            {
                "schema_version": TICKER_PAGE_SCHEMA_VERSIONS[prefix],
                "snapshot_refresh_run_id": refresh_run_id,
                "source_run_id": source_run_id,
                "parent_refresh_id": "parent-refresh-A",
                "config_hash": "config-hash",
            }
        )
        frame = pd.DataFrame([row])
        run_stamped = paths.output_ticker_page_dir / f"{prefix}_latest_{source_run_id}.parquet"
        frame.to_parquet(run_stamped, index=False)
        shutil.copyfile(run_stamped, getattr(paths, path_attr))


def _write_i3_option_artifacts(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    source_run_id = "20260601T000000Z-option-artifacts"
    for artifact_name in OPTION_ARTIFACT_NAMES:
        frame = pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "schema_version": 1,
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": source_run_id,
                    "parent_refresh_id": "parent-refresh-A",
                    "risk_free_rate": 0.04,
                    "risk_free_rate_is_fallback": False,
                }
            ]
        )
        if artifact_name not in REQUIRED_OPTION_ARTIFACT_NAMES:
            frame["diagnostic_artifact"] = True
        run_stamped_path = option_artifact_run_stamped_path(
            paths,
            artifact_name,
            source_run_id,
        )
        latest_path = option_artifact_latest_path(paths, artifact_name)
        write_parquet_atomic(frame, run_stamped_path, index=False)
        write_parquet_atomic(frame, latest_path, index=False)


def _write_portfolio_outputs(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    source_run_id = "20260601T000000Z-portfolio"
    rows = [
        {
            "schema_version": 1,
            "snapshot_refresh_run_id": refresh_run_id,
            "source_run_id": source_run_id,
        }
    ]
    latest_paths = {
        "portfolio_lines": paths.latest_portfolio_lines_path,
        "portfolio_positions": paths.latest_portfolio_positions_path,
        "portfolio_summary": paths.latest_portfolio_summary_path,
        "benchmark_betas": paths.latest_benchmark_betas_path,
        "portfolio_reconciliation": paths.latest_portfolio_reconciliation_path,
        "portfolio_hedge_sizing": paths.latest_portfolio_hedge_sizing_path,
        "portfolio_correlations": paths.latest_portfolio_correlations_path,
        "portfolio_value_history": paths.latest_portfolio_value_history_path,
        "portfolio_reconciliation_export": paths.latest_portfolio_reconciliation_export_path,
    }
    for name, latest_path in latest_paths.items():
        frame = pd.DataFrame(rows)
        run_stamped_path = latest_path.parent / f"{name}_latest_{source_run_id}.parquet"
        write_parquet_atomic(frame, run_stamped_path, index=False)
        write_parquet_atomic(frame, latest_path, index=False)
    csv = pd.DataFrame(rows)
    csv_run_path = (
        paths.output_portfolio_dir
        / f"portfolio_reconciliation_export_latest_{source_run_id}.csv"
    )
    csv_run_path.parent.mkdir(parents=True, exist_ok=True)
    csv.to_csv(csv_run_path, index=False)
    csv.to_csv(paths.latest_portfolio_reconciliation_export_csv_path, index=False)


def _freshness_artifacts(versions: dict[str, int]) -> dict[str, dict]:
    artifacts = {
        "foundation": {"usable": True, "snapshot_as_of_date": "2026-08-10"},
        "options": {"usable": True, "as_of_date": "2026-08-10"},
    }
    for name in REQUIRED_OPTION_ARTIFACT_NAMES:
        artifacts[name] = {
            "usable": True,
            "schema_version": versions[name],
            "source_run_ids": ["20260810T120000Z-refresh-aaaaaaaa"],
        }
    return artifacts


def _option_domain(artifacts, tmp_path):
    from golden_vector.app.model_state import _freshness_domains

    return _freshness_domains(
        paths=build_test_paths(tmp_path),
        artifacts=artifacts,
        option_publish_block=None,
        carry=None,
        carry_failure=None,
    )["option_artifacts"]


def test_mixed_option_schema_versions_are_never_reported_fresh(tmp_path):
    """A manifest mixing v3 and v4 must not claim OK.

    Both versions are individually SUPPORTED, so the per-artifact check passes;
    only the single-version rule catches the mix. Carry-forward already rejects
    a mixed generation, so freshness saying OK would be a split brain.
    """

    versions = dict.fromkeys(REQUIRED_OPTION_ARTIFACT_NAMES, 4)
    versions[REQUIRED_OPTION_ARTIFACT_NAMES[0]] = 3
    domain = _option_domain(_freshness_artifacts(versions), tmp_path)
    assert domain["status"] != "OK"

    # Control: one uniform supported version still reports OK.
    uniform = _option_domain(
        _freshness_artifacts(dict.fromkeys(REQUIRED_OPTION_ARTIFACT_NAMES, 4)), tmp_path
    )
    assert uniform["status"] == "OK"
