"""Tests for the new operational `refresh` and `status` CLI commands.

These cover the daily-use ergonomics layer: collapsing the three-command
update-data → tool-a → tool-b sequence into one, and surfacing pipeline state
without requiring the user to inspect three different files.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from golden_vector.app.config import load_app_config
from golden_vector.app.model_state import (
    load_current_model_state_manifest,
    read_current_model_parquet,
    write_current_model_state_manifest,
)
from golden_vector.app.paths import ProjectPaths
from golden_vector.app.run_context import RunContext
from golden_vector.cli import run_refresh, run_status, run_tool_b
from golden_vector.ingestion.persist import persist_tool_a_outputs, persist_tool_b_outputs
from golden_vector.ingestion.persist_tool_c import persist_tool_c_outputs
from golden_vector.ingestion.persist_tool_d import persist_tool_d_outputs
from golden_vector.screening.manual_data import bootstrap_manual_screening_data
from tests.helpers import build_test_paths


class _LoadedConfigStub:
    def __init__(self, app: object, combined_hash: str) -> None:
        self.app = app
        self.combined_hash = combined_hash


def test_tool_b_falls_back_to_config_default_gold_price_when_cli_omits_it(tmp_path, monkeypatch):
    """The headline ergonomic fix: `python main.py tool-b` (no --gold-price) should
    pick up the config's `default_gold_price_assumption` instead of erroring out.
    """
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    captured: dict[str, object] = {}

    def fake_pipeline(*, paths, app_config, run_context, normalized_market_snapshots,
                     gold_price_assumption, snapshot_refresh_run_id, snapshot_as_of_date):
        captured["gold_price"] = gold_price_assumption
        return type(
            "ToolBResultStub",
            (),
            {
                "tool_b_outputs": pd.DataFrame(),
                "manual_data": type("MD", (), {
                    "store_path": paths.manual_screening_store_path,
                    "store_created": False,
                    "seeded_tickers": [],
                    "imported_csv_files": [],
                    "stock_notes": pd.DataFrame(),
                })(),
                "overall_status": "WARN",
                "summary": {},
            },
        )()

    monkeypatch.setattr("golden_vector.cli.execute_tool_b_pipeline", fake_pipeline)

    def fake_snapshot(**_):
        return type("Snap", (), {
            "refresh_run_id": "test-refresh",
            "snapshot_as_of_date": "2026-04-22",
            "foundation_status": "PASS",
            "manifest_path": paths.latest_foundation_manifest_path,
            "raw_qa_summary": {"overall_status": "PASS"},
            "normalization_qa_summary": {"overall_status": "PASS"},
            "summary": {},
            "normalized_market_snapshots": pd.DataFrame(),
        })()

    monkeypatch.setattr("golden_vector.cli.load_latest_foundation_snapshot", fake_snapshot)

    exit_code = run_tool_b(paths, gold_price=None)

    assert exit_code == 0
    # Default in shipped config is 4000.
    assert captured["gold_price"] == real_loaded.screening_params.resolve_gold_price(None)
    assert captured["gold_price"] == 4000.0


def test_status_command_runs_cleanly_with_no_artifacts(tmp_path, monkeypatch, capsys):
    """`status` must not crash when the foundation manifest, Tool A latest, Tool B
    latest, and manual store are all missing. It should print actionable next steps.
    """
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    exit_code = run_status(paths)
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Model state manifest: NOT FOUND" in captured
    assert "Foundation snapshot:  NOT FOUND" in captured
    assert "Tool A latest output: NOT FOUND" in captured
    assert "Tool B latest output: NOT FOUND" in captured
    assert "Tool C latest output: NOT FOUND" in captured
    assert "Tool D latest output: NOT FOUND" in captured
    assert "Refresh alignment:    UNKNOWN" in captured
    assert "No manual-data store yet" in captured


def test_status_command_lists_blank_tickers_when_some_have_no_manual_data(tmp_path, monkeypatch, capsys):
    """When some active Tool B tickers have no manual data, the status command must
    name them so the user knows what to fill in. This is the most common operational
    gap in the live tool.
    """
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    # Initialize the store but populate no fields.
    tickers = sorted(
        t.ticker for t in real_loaded.universe.tickers if t.active and t.tool_b_enabled
    )
    bootstrap_manual_screening_data(paths, tickers=tickers)

    exit_code = run_status(paths)
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Manual data coverage" in captured
    # All tickers should be reported as blank.
    assert f"0/{len(tickers)} tickers fully populated" in captured
    assert "Blank:" in captured
    for ticker in tickers:
        assert ticker in captured


def test_status_command_surfaces_refresh_id_mismatch(tmp_path, monkeypatch, capsys):
    """If the foundation manifest's refresh id doesn't match Tool A latest's
    snapshot_refresh_run_id, the status command must say so explicitly.
    """
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    # Foundation manifest → refresh-A.
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps({
            "refresh_run_id": "refresh-A",
            "snapshot_as_of_date": "2026-04-22",
            "foundation_status": "PASS",
        }),
        encoding="utf-8",
    )

    # Tool A latest → refresh-B (mismatch).
    run_context = RunContext.start(
        paths=paths, command="tool-a", parameters={}, config_hash="h",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=pd.DataFrame(
            [{"ticker": "NEM", "as_of_date": date(2026, 4, 22),
              "snapshot_refresh_run_id": "refresh-B", "tool_a_rank": 1, "score_eligible": True}]
        ),
    )

    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    exit_code = run_status(paths)
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Refresh alignment:    MISMATCH" in captured
    assert "refresh-A" in captured
    assert "refresh-B" in captured


def test_status_command_reads_model_state_manifest(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    paths.latest_model_state_manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "generated_at_utc": "2026-06-05T10:00:00Z",
                "parent_refresh_id": None,
                "state": "incomplete",
                "alignment": {"status": "WARN"},
                "warnings": [
                    "Required artifact is missing: tool_c.",
                    "Required artifact is missing: tool_d.",
                ],
                "artifacts": {},
            }
        ),
        encoding="utf-8",
    )
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    exit_code = run_status(paths)
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Model state manifest: INCOMPLETE" in captured
    assert "parent_refresh_id: (none)" in captured
    assert "Required artifact is missing: tool_c." in captured
    assert "Required artifact is missing: tool_d." in captured


def test_status_command_summarizes_tool_c_and_tool_d_outputs(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.latest_foundation_manifest_path.write_text(
        json.dumps(
            {
                "refresh_run_id": "refresh-A",
                "snapshot_as_of_date": "2026-04-22",
                "foundation_status": "PASS",
            }
        ),
        encoding="utf-8",
    )
    tool_c_context = RunContext.start(
        paths=paths, command="tool-c", parameters={}, config_hash="h",
    )
    persist_tool_c_outputs(
        paths=paths,
        run_context=tool_c_context,
        tool_c_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "snapshot_refresh_run_id": "refresh-A",
                    "tool_c_downside_rank": 100.0,
                    "tool_c_upside_rank": 50.0,
                }
            ]
        ),
    )
    tool_d_context = RunContext.start(
        paths=paths, command="tool-d", parameters={}, config_hash="h",
    )
    persist_tool_d_outputs(
        paths=paths,
        run_context=tool_d_context,
        tool_d_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 4, 22),
                    "snapshot_refresh_run_id": "refresh-A",
                    "gold_price_used": 4000.0,
                    "spot_gold_date": "2026-04-22",
                    "tool_d_quality_rank": 100.0,
                }
            ]
        ),
    )
    bootstrap_manual_screening_data(paths, tickers=["NEM"])

    exit_code = run_status(paths)
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "Tool C latest output: 1 rows, 1 downside ranked, 1 upside ranked." in captured
    assert "Tool D latest output: 1 rows, 1 ranked, gold price used $4000/oz" in captured


def test_refresh_command_chains_update_then_tool_a_then_tool_b(tmp_path, monkeypatch, capsys):
    """The refresh command must call the operational pipeline in order
    and then print the status summary. If a step fails, it must stop early.
    """
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    call_order: list[str] = []

    def fake_foundation(_paths, *, command_name="update-data"):
        call_order.append("update-data")
        return 0

    def fake_tool_a(_paths):
        call_order.append("tool-a")
        return 0

    def fake_tool_b(_paths, *, gold_price):
        call_order.append(f"tool-b@{gold_price}")
        return 0

    def fake_tool_c(_paths, **_kwargs):
        call_order.append("tool-c")
        return 0

    def fake_tool_d(_paths, *, gold_price, **_kwargs):
        call_order.append(f"tool-d@{gold_price}")
        return 0

    monkeypatch.setattr("golden_vector.cli.run_foundation", fake_foundation)
    monkeypatch.setattr("golden_vector.cli.run_tool_a", fake_tool_a)
    monkeypatch.setattr("golden_vector.cli.run_tool_b", fake_tool_b)
    monkeypatch.setattr("golden_vector.cli.run_tool_c", fake_tool_c)
    monkeypatch.setattr("golden_vector.cli.run_tool_d", fake_tool_d)

    exit_code = run_refresh(paths, gold_price_override=None, skip_tool_b=False)

    assert exit_code == 0
    assert call_order == ["update-data", "tool-a", "tool-b@None", "tool-c", "tool-d@None"]
    assert paths.latest_model_state_manifest_path.exists()
    model_state = json.loads(paths.latest_model_state_manifest_path.read_text(encoding="utf-8"))
    assert "-refresh-" in model_state["parent_refresh_id"]
    assert "tool_a" in model_state["artifacts"]
    assert "option_candidate_slots" in model_state["artifacts"]
    assert model_state["stage_timings"]["update_data"]["exit_code"] == 0
    assert model_state["stage_timings"]["tool_d"]["exit_code"] == 0
    out = capsys.readouterr().out
    assert "Step 1/5: update-data" in out
    assert "Step 2/5: tool-a" in out
    assert "Step 3/5: tool-b" in out
    assert "Step 4/5: tool-c" in out
    assert "Step 5/5: tool-d (spot gold)" in out
    assert "Model state manifest published:" in out
    assert "Refresh complete" in out


def test_refresh_fault_after_tool_b_keeps_previous_manifest_and_readers_intact(
    tmp_path,
    monkeypatch,
    capsys,
):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    _write_refresh_inputs(paths, refresh_run_id="refresh-old")
    previous_manifest = write_current_model_state_manifest(
        paths=paths,
        config_hash="hash",
        parent_refresh_id="parent-refresh-old",
    )

    call_order: list[str] = []

    def fake_foundation(_paths, *, command_name="update-data"):
        call_order.append("update-data")
        _write_foundation_and_options(_paths, refresh_run_id="refresh-new")
        return 0

    def fake_tool_a(_paths):
        call_order.append("tool-a")
        _write_tool_a(_paths, refresh_run_id="refresh-new", rank=99)
        return 0

    def fake_tool_b(_paths, *, gold_price):
        call_order.append("tool-b")
        _write_tool_b(_paths, refresh_run_id="refresh-new", rank=99)
        return 0

    def fake_tool_c(_paths, **_kwargs):
        raise AssertionError("Tool C must not run after injected Tool B fault.")

    monkeypatch.setattr("golden_vector.cli.run_foundation", fake_foundation)
    monkeypatch.setattr("golden_vector.cli.run_tool_a", fake_tool_a)
    monkeypatch.setattr("golden_vector.cli.run_tool_b", fake_tool_b)
    monkeypatch.setattr("golden_vector.cli.run_tool_c", fake_tool_c)

    exit_code = run_refresh(
        paths,
        gold_price_override=None,
        skip_tool_b=False,
        _fault_after_step="tool_b",
    )

    latest_alias = pd.read_parquet(paths.latest_tool_b_snapshot_parquet_path)
    current_tool_b = read_current_model_parquet(
        paths,
        "tool_b",
        fallback_path=paths.latest_tool_b_snapshot_parquet_path,
    )
    current_manifest = load_current_model_state_manifest(paths)
    out = capsys.readouterr().out

    assert exit_code == 97
    assert call_order == ["update-data", "tool-a", "tool-b"]
    assert current_manifest == previous_manifest
    assert current_manifest is not None
    assert current_manifest["parent_refresh_id"] == "parent-refresh-old"
    assert latest_alias["snapshot_refresh_run_id"].tolist() == ["refresh-new"]
    assert current_tool_b["snapshot_refresh_run_id"].tolist() == ["refresh-old"]
    assert "Model-state manifest was not published" in out


def test_refresh_command_stops_after_update_data_failure(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    call_order: list[str] = []

    def fake_foundation(_paths, *, command_name="update-data"):
        call_order.append("update-data")
        return 1  # fail

    def fake_tool_a(_paths):
        call_order.append("tool-a")
        return 0

    def fake_tool_b(_paths, *, gold_price):
        call_order.append("tool-b")
        return 0

    monkeypatch.setattr("golden_vector.cli.run_foundation", fake_foundation)
    monkeypatch.setattr("golden_vector.cli.run_tool_a", fake_tool_a)
    monkeypatch.setattr("golden_vector.cli.run_tool_b", fake_tool_b)

    exit_code = run_refresh(paths, gold_price_override=None, skip_tool_b=False)

    assert exit_code == 1
    assert call_order == ["update-data"]  # tool-a and tool-b never called
    out = capsys.readouterr().out
    assert "update-data failed" in out


def test_refresh_command_skips_tool_b_when_flag_passed(tmp_path, monkeypatch, capsys):
    paths = build_test_paths(tmp_path)
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )

    call_order: list[str] = []

    def fake_foundation(_paths, *, command_name="update-data"):
        call_order.append("update-data")
        return 0

    def fake_tool_a(_paths):
        call_order.append("tool-a")
        return 0

    def fake_tool_b(_paths, *, gold_price):
        call_order.append("tool-b")
        return 0

    monkeypatch.setattr("golden_vector.cli.run_foundation", fake_foundation)
    monkeypatch.setattr("golden_vector.cli.run_tool_a", fake_tool_a)
    monkeypatch.setattr("golden_vector.cli.run_tool_b", fake_tool_b)

    exit_code = run_refresh(paths, gold_price_override=None, skip_tool_b=True)

    assert exit_code == 0
    assert call_order == ["update-data", "tool-a"]
    out = capsys.readouterr().out
    assert "tool-b/tool-c/tool-d SKIPPED" in out
    assert "Model state manifest published after partial refresh" in out
    assert paths.latest_model_state_manifest_path.exists()


def test_refresh_skip_tool_b_publishes_partial_manifest_for_new_tool_a(
    tmp_path,
    monkeypatch,
    capsys,
):
    paths = build_test_paths(tmp_path)
    paths.ensure_runtime_dirs()
    real_loaded = load_app_config(ProjectPaths.discover()).app
    monkeypatch.setattr(
        "golden_vector.cli.load_app_config",
        lambda _: _LoadedConfigStub(app=real_loaded, combined_hash="hash"),
    )
    _write_refresh_inputs(paths, refresh_run_id="refresh-old")
    previous_manifest = write_current_model_state_manifest(
        paths=paths,
        config_hash="hash",
        parent_refresh_id="parent-refresh-old",
    )

    def fake_foundation(_paths, *, command_name="update-data"):
        _write_foundation_and_options(_paths, refresh_run_id="refresh-new")
        return 0

    def fake_tool_a(_paths):
        _write_tool_a(_paths, refresh_run_id="refresh-new", rank=99)
        return 0

    def fake_tool_b(_paths, *, gold_price):
        raise AssertionError("Tool B must not run with --skip-tool-b.")

    monkeypatch.setattr("golden_vector.cli.run_foundation", fake_foundation)
    monkeypatch.setattr("golden_vector.cli.run_tool_a", fake_tool_a)
    monkeypatch.setattr("golden_vector.cli.run_tool_b", fake_tool_b)

    exit_code = run_refresh(paths, gold_price_override=None, skip_tool_b=True)
    current_manifest = json.loads(paths.latest_model_state_manifest_path.read_text(encoding="utf-8"))
    current_tool_a = read_current_model_parquet(
        paths,
        "tool_a",
        fallback_path=paths.latest_tool_a_snapshot_parquet_path,
    )

    assert exit_code == 0
    assert current_manifest != previous_manifest
    assert current_manifest["parent_refresh_id"] != "parent-refresh-old"
    assert current_manifest["state"] == "incomplete"
    assert current_tool_a["snapshot_refresh_run_id"].tolist() == ["refresh-new"]
    assert current_tool_a["tool_a_rank"].tolist() == [99]
    out = capsys.readouterr().out
    assert "Model state manifest published after partial refresh" in out


def _write_refresh_inputs(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    _write_foundation_and_options(paths, refresh_run_id=refresh_run_id)
    _write_tool_a(paths, refresh_run_id=refresh_run_id, rank=1)
    _write_tool_b(paths, refresh_run_id=refresh_run_id, rank=1)
    _write_tool_c(paths, refresh_run_id=refresh_run_id)
    _write_tool_d(paths, refresh_run_id=refresh_run_id)


def _write_foundation_and_options(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    paths.latest_foundation_manifest_path.parent.mkdir(parents=True, exist_ok=True)
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
                "refresh_run_id": refresh_run_id,
                "as_of_date": "2026-06-01",
                "summary": {"options_phase_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )


def _write_tool_a(paths: ProjectPaths, *, refresh_run_id: str, rank: int) -> None:
    run_context = RunContext.start(
        paths=paths,
        command="tool-a",
        parameters={},
        config_hash="hash",
    )
    persist_tool_a_outputs(
        paths=paths,
        run_context=run_context,
        tool_a_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": run_context.run_id,
                    "tool_a_rank": rank,
                    "score_eligible": True,
                }
            ]
        ),
    )


def _write_tool_b(paths: ProjectPaths, *, refresh_run_id: str, rank: int) -> None:
    run_context = RunContext.start(
        paths=paths,
        command="tool-b",
        parameters={},
        config_hash="hash",
    )
    persist_tool_b_outputs(
        paths=paths,
        run_context=run_context,
        tool_b_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": run_context.run_id,
                    "tool_b_rank": rank,
                    "screening_verdict": "PASS",
                }
            ]
        ),
    )


def _write_tool_c(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    run_context = RunContext.start(
        paths=paths,
        command="tool-c",
        parameters={},
        config_hash="hash",
    )
    persist_tool_c_outputs(
        paths=paths,
        run_context=run_context,
        tool_c_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": run_context.run_id,
                    "tool_c_downside_rank": 1,
                    "tool_c_upside_rank": 1,
                }
            ]
        ),
    )


def _write_tool_d(paths: ProjectPaths, *, refresh_run_id: str) -> None:
    run_context = RunContext.start(
        paths=paths,
        command="tool-d",
        parameters={},
        config_hash="hash",
    )
    persist_tool_d_outputs(
        paths=paths,
        run_context=run_context,
        tool_d_outputs=pd.DataFrame(
            [
                {
                    "ticker": "NEM",
                    "as_of_date": date(2026, 6, 1),
                    "snapshot_refresh_run_id": refresh_run_id,
                    "source_run_id": run_context.run_id,
                    "gold_price_used": 4000.0,
                    "spot_gold_usd": 4000.0,
                    "spot_gold_date": "2026-06-01",
                    "tool_d_quality_rank": 1,
                }
            ]
        ),
        publish_spot_latest_aliases=True,
    )
