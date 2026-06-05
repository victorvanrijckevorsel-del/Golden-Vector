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
    assert payload["artifacts"]["option_candidate_slots"]["planned_phase"] == "I3"
    assert payload["artifacts"]["option_candidate_slots"]["required_for_complete"] is False
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
                    "source_run_id": "tool-a-run",
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
                    "source_run_id": "tool-b-run",
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
                        "source_run_id": "tool-c-run",
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
                        "source_run_id": "tool-d-run",
                        "gold_price_used": 4000.0,
                        "spot_gold_date": "2026-06-01",
                        "tool_d_quality_rank": 1,
                    }
                ]
            ),
        )
