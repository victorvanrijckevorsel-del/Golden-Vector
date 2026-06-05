from __future__ import annotations

import json
from datetime import date

import pandas as pd

from golden_vector.app.model_state import (
    build_current_model_state_manifest,
    load_current_model_state_manifest,
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
    assert payload["parent_refresh_id"] is None
    assert payload["publish"]["atomic_pointer"] is True
    assert payload["publish"]["latest_aliases_authoritative"] is False
    assert payload["artifacts"]["tool_a"]["row_count"] == 1
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
    assert "Could not read model-state manifest" in payload["warnings"][0]


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
