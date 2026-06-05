from __future__ import annotations

import json
from datetime import date

import pandas as pd

from golden_vector.app.model_state import (
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
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from tests.helpers import build_test_paths


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
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": tool_b_context.run_id,
                    "tool_b_rank": 1,
                    "screening_verdict": "PASS",
                }
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
